"""faster-whisper（Fast Whisper）による音声認識。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.stt.model_layout import (
    canonical_stt_folder_name,
    is_stt_model_directory_ready,
    resolve_whisper_model_name,
)
from speech_summarizer_ai.platform_utils import paths

DeviceLiteral = Literal["auto", "cpu", "cuda"]


def _lowpass_fir(cutoff_ratio: float, taps: int = 63) -> np.ndarray:
    """窓付き sinc（Blackman 窓）のローパス FIR 係数を返す。

    Args:
        cutoff_ratio: 遮断周波数 ÷ 入力サンプリングレート（0〜0.5）。
        taps: タップ数（奇数）。

    Returns:
        np.ndarray: 合計 1 に正規化した係数。
    """
    n = np.arange(taps) - (taps - 1) / 2.0
    h = 2.0 * cutoff_ratio * np.sinc(2.0 * cutoff_ratio * n)
    h *= np.blackman(taps)
    return (h / h.sum()).astype(np.float64)


_FIR_CACHE: dict[tuple[int, int], np.ndarray] = {}


def _resample_linear_float32(x: np.ndarray, *, src_sr: int, dst_sr: int) -> np.ndarray:
    """1 次元 float32 波形をリサンプルする（外部リサンプラに依存しない）。

    ダウンサンプル時は先にアンチエイリアスのローパスを掛ける。掛けないと 48 kHz → 16 kHz で
    8 kHz 超の成分（子音の摩擦音・環境ノイズ）が音声帯域に折り返し、認識精度が落ちる。
    整数比（48k→16k の 3:1 など）は間引き、それ以外は線形補間。

    Args:
        x: 入力波形（1 次元）。``float32`` 以外は内部で扱いやすい型に寄せる。
        src_sr: 入力のサンプリングレート（Hz）。
        dst_sr: 出力のサンプリングレート（Hz）。

    Returns:
        np.ndarray: リサンプル後の ``float32`` 1 次元配列。``src_sr == dst_sr`` のときはコピー最小の ``float32``。
    """
    if src_sr == dst_sr:
        return x.astype(np.float32, copy=False)
    if x.size == 0:
        return np.zeros(0, dtype=np.float32)
    xf = x.astype(np.float64)
    if dst_sr < src_sr:
        key = (src_sr, dst_sr)
        h = _FIR_CACHE.get(key)
        if h is None:
            # 出力ナイキストの 90% で遮断（16 kHz 出力なら約 7.2 kHz）
            h = _lowpass_fir(0.45 * dst_sr / src_sr)
            _FIR_CACHE[key] = h
        xf = np.convolve(xf, h, mode="same")
        if src_sr % dst_sr == 0:
            return xf[:: src_sr // dst_sr].astype(np.float32)
    n_out = max(1, int(round(x.size * dst_sr / src_sr)))
    t_old = np.linspace(0.0, 1.0, num=x.size, endpoint=False)
    t_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(t_new, t_old, xf).astype(np.float32)


def _normalize_level(x: np.ndarray, *, target_peak: float = 0.8, max_gain: float = 6.0) -> np.ndarray:
    """小さすぎる入力を聞き取りやすい音量まで持ち上げる（大きい入力はそのまま）。

    Args:
        x: float32 波形（-1〜1）。
        target_peak: 目標ピーク。
        max_gain: 最大倍率（無音に近いノイズを増幅しすぎないため）。

    Returns:
        np.ndarray: 調整後の波形。
    """
    if x.size == 0:
        return x
    peak = float(np.max(np.abs(x)))
    if peak <= 1e-4 or peak >= target_peak:
        return x
    gain = min(max_gain, target_peak / peak)
    return (x * gain).astype(np.float32)


def default_cpu_threads() -> int:
    """CPU 推論のスレッド数（CTranslate2 の既定 4 は最近の Mac / PC では少ない）。"""
    n = os.cpu_count() or 4
    return max(4, min(8, n))


@dataclass(frozen=True)
class TranscriptionSegment:
    """認識結果の 1 セグメント（タイムスタンプ付き）。

    Attributes:
        start: セグメント開始時刻（秒）。
        end: セグメント終了時刻（秒）。
        text: 当該区間の認識テキスト（前後空白は除いた状態で格納される想定）。
    """

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    """1 回の認識あたりの文字起こし結果（ファイル／バッファ共通）。

    Attributes:
        text: 全文（セグメント文字列の連結）。
        language: 検出または指定された言語コード。
        language_probability: 言語判定の信頼度。
        duration: 入力音声の長さ（秒）。
        segments: タイムスタンプ付きセグメント列。
    """

    text: str
    language: str
    language_probability: float
    duration: float
    segments: tuple[TranscriptionSegment, ...]


def default_device() -> Literal["cpu", "cuda"]:
    """ctranslate2 経由で CUDA デバイスが使えるか確認し、推奨デバイス名を返す。

    Returns:
        Literal["cpu", "cuda"]: GPU が利用可能なら ``cuda``、それ以外は ``cpu``。
    """
    try:
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def default_compute_type(device: Literal["cpu", "cuda"]) -> str:
    """デバイスに合わせた ``WhisperModel`` 用 ``compute_type`` の推奨値を返す。

    Args:
        device: 実行デバイス（``cpu`` または ``cuda``）。

    Returns:
        str: GPU 時は ``float16``、CPU 時は ``int8``。
    """
    return "float16" if device == "cuda" else "int8"


class FastWhisperTranscriber:
    """faster-whisper の ``WhisperModel`` を遅延ロードし、ファイルまたは PCM バッファを認識する。

    ローカル ``models/stt/<folder>`` または Hugging Face 解決名のいずれかでモデルを開く。
    """

    def __init__(
        self,
        model_size: str = config.STT_DEFAULT_MODEL,
        *,
        project_root: Path | None = None,
        use_project_models: bool = True,
        device: DeviceLiteral | None = None,
        compute_type: str | None = None,
        device_index: int | list[int] = 0,
        cpu_threads: int = 0,
        num_workers: int = 1,
    ) -> None:
        """トランスクライバを構築する（モデル読み込みは遅延）。

        Args:
            model_size: ``tiny`` / ``base`` / ``small`` / ``medium`` / ``large``（→ ``models/stt/large``）など。
            project_root: 指定かつ ``use_project_models`` が True のとき、
                ``models/stt/<サイズ>/`` のローカル重みを使う。
            use_project_models: ``project_root`` がある場合にローカル専用にするか。
                False のとき Hugging Face 既定キャッシュへフォールバック（初回は自動ダウンロード）。
            device: ``None`` のとき ``config.STT_DEVICE``（既定は ``cpu``）。
                ``auto`` のとき ``default_device()`` を使用。
            compute_type: ``None`` のとき ``default_compute_type`` に従う。
            device_index: GPU 番号など（faster-whisper にそのまま渡す）。
            cpu_threads: CPU スレッド数。``0`` は自動。
            num_workers: デコード用ワーカー数。

        Returns:
            None

        Raises:
            FileNotFoundError: ローカル利用を要求したが ``models/stt/...`` が未配置の場合。
        """
        self._device_index = device_index
        self._cpu_threads = cpu_threads if cpu_threads > 0 else default_cpu_threads()
        self._num_workers = num_workers

        dev: DeviceLiteral = device if device is not None else config.STT_DEVICE
        if dev == "auto":
            resolved_device: Literal["cpu", "cuda"] = default_device()
        else:
            resolved_device = dev
        self._device = resolved_device
        self._compute_type = compute_type or default_compute_type(resolved_device)

        self._model_path: Path | None = None
        self._model_name: str | None = None

        if project_root is not None and use_project_models:
            folder = canonical_stt_folder_name(model_size)
            local_dir = paths.stt_model_directory(project_root, folder)
            if not is_stt_model_directory_ready(local_dir):
                raise FileNotFoundError(
                    f"STT モデルが未配置です: {local_dir}\n"
                    "事前ダウンロード例: python -m "
                    "speech_summarizer_ai.stt.model_downloader "
                    f"--model {folder}"
                )
            self._model_path = local_dir
        else:
            self._model_name = resolve_whisper_model_name(model_size)

        self._model: WhisperModel | None = None

    def _ensure_model(self) -> WhisperModel:
        """初回呼び出し時に ``WhisperModel`` を構築し、以降は同一インスタンスを返す。

        Returns:
            WhisperModel: ロード済みモデル。
        """
        if self._model is None:
            if self._model_path is not None:
                self._model = WhisperModel(
                    str(self._model_path),
                    device=self._device,
                    device_index=self._device_index,
                    compute_type=self._compute_type,
                    cpu_threads=self._cpu_threads,
                    num_workers=self._num_workers,
                )
            else:
                assert self._model_name is not None
                self._model = WhisperModel(
                    self._model_name,
                    device=self._device,
                    device_index=self._device_index,
                    compute_type=self._compute_type,
                    cpu_threads=self._cpu_threads,
                    num_workers=self._num_workers,
                )
        return self._model

    def transcribe_file(
        self,
        audio_path: str | Path,
        *,
        language: str | None = "ja",
        beam_size: int = 5,
        vad_filter: bool = True,
        task: Literal["transcribe", "translate"] = "transcribe",
    ) -> TranscriptionResult:
        """音声ファイル（WAV / MP3 等）を文字起こしする。

        Args:
            audio_path: 入力ファイルパス（アプリの ``audio.wav`` 等）。
            language: 言語コード（日本語は ``ja``）。``None`` で先頭区間から自動検出。
            beam_size: ビーム探索幅。
            vad_filter: 無音区間をスキップする VAD を有効にするか。
            task: ``transcribe`` または ``translate``（英語テキスト化）。

        Returns:
            TranscriptionResult: 全文・言語情報・セグメント列。

        Raises:
            FileNotFoundError: ファイルが存在しない場合。
        """
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"音声ファイルが見つかりません: {path}")

        model = self._ensure_model()
        segments_iter, info = model.transcribe(
            str(path.resolve()),
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            task=task,
        )

        parts: list[TranscriptionSegment] = []
        text_chunks: list[str] = []
        for seg in segments_iter:
            t = seg.text.strip()
            parts.append(TranscriptionSegment(start=seg.start, end=seg.end, text=t))
            if t:
                text_chunks.append(t)

        full_text = "".join(text_chunks)

        return TranscriptionResult(
            text=full_text.strip(),
            language=info.language or (language or ""),
            language_probability=float(info.language_probability),
            duration=float(info.duration),
            segments=tuple(parts),
        )

    def transcribe_int16_mono(
        self,
        pcm_int16: np.ndarray,
        *,
        sample_rate: int,
        language: str | None = "ja",
        beam_size: int = 3,
        vad_filter: bool = False,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        """モノラル int16 PCM を 16 kHz float32 に合わせて ``transcribe`` する（リアルタイム区間向け）。

        Args:
            pcm_int16: モノラル ``int16`` 1 次元配列。
            sample_rate: ``pcm_int16`` のサンプリングレート（Hz）。
            language: 言語コード。``None`` で自動検出。
            beam_size: ビーム幅（短い区間では小さめ推奨）。
            vad_filter: 区間内の無音除去（外側で VAD 済みなら ``False``）。
            condition_on_previous_text: 直前テキストへの依存（チャンク独立なら ``False``）。
            initial_prompt: 直前の発話など、表記・用語のヒントとして渡す文字列。

        Returns:
            TranscriptionResult: 認識結果。

        Raises:
            ValueError: ``pcm_int16`` が 1 次元モノラルでない場合。
        """
        if pcm_int16.ndim != 1:
            raise ValueError("pcm_int16 は 1 次元モノラルである必要があります")
        x = pcm_int16.astype(np.float32) / 32768.0
        audio_16k = _normalize_level(
            _resample_linear_float32(x, src_sr=sample_rate, dst_sr=16_000)
        )
        model = self._ensure_model()
        segments_iter, info = model.transcribe(
            audio_16k,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            task="transcribe",
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt or None,
        )
        parts: list[TranscriptionSegment] = []
        text_chunks: list[str] = []
        for seg in segments_iter:
            t = seg.text.strip()
            parts.append(TranscriptionSegment(start=seg.start, end=seg.end, text=t))
            if t:
                text_chunks.append(t)
        full_text = "".join(text_chunks)
        return TranscriptionResult(
            text=full_text.strip(),
            language=info.language or (language or ""),
            language_probability=float(info.language_probability),
            duration=float(info.duration),
            segments=tuple(parts),
        )


def transcribe_file(
    audio_path: str | Path,
    *,
    model_size: str = config.STT_DEFAULT_MODEL,
    project_root: Path | None = None,
    use_project_models: bool = True,
    language: str | None = "ja",
    device: DeviceLiteral | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
) -> TranscriptionResult:
    """一時的に ``FastWhisperTranscriber`` を生成し、1 ファイルだけ文字起こしする。

    繰り返し処理には :class:`FastWhisperTranscriber` を直接保持する方が効率的。

    Args:
        audio_path: 入力音声ファイルパス。
        model_size: モデル識別子（``tiny`` / ``base`` / ``large`` 等。ローカル時はフォルダ名に正規化）。
        project_root: ローカル ``models/stt`` を参照するときのプロジェクトルート。
        use_project_models: True でローカル配置を必須にする（False で HF 名・キャッシュ）。
        language: 言語コード（例: ``ja``）。``None`` で自動検出。
        device: ``auto`` / ``cpu`` / ``cuda``。``None`` で ``config.STT_DEVICE``。
        beam_size: ビーム探索幅。
        vad_filter: faster-whisper 内蔵 VAD で無音をスキップするか。

    Returns:
        TranscriptionResult: 全文・言語情報・セグメント列。

    Raises:
        FileNotFoundError: 音声ファイルが無い、またはローカルモデル未配置の場合。
    """
    tr = FastWhisperTranscriber(
        model_size=model_size,
        project_root=project_root,
        use_project_models=use_project_models,
        device=device,
    )
    return tr.transcribe_file(
        audio_path,
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
    )
