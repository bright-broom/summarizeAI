"""キュー経由の int16 PCM を VAD で区切り faster-whisper で逐次認識する。

PCM はキューからチャンク単位で取り込み、発話単位だけバッファする（全文音声・全文テキストは RAM に溜めない）。
認識結果はコールバックで即 DB 追記し、本モジュールは長いトランスクリプト文字列を保持しない。
要約は録音終了後に一回だけコントローラ側で実行する（増分要約なし）。

WebRTC VAD（``webrtcvad-wheels``）を優先し、無ければ RMS 閾値。
"""

from __future__ import annotations

import importlib
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import numpy as np

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.stt.faster_whisper_engine import FastWhisperTranscriber

_FRAME_SAMPLES_48K_10MS = 480


def _webrtcvad_module() -> ModuleType | None:
    """``webrtcvad-wheels`` が入っていればモジュールを返す（未インストールなら ``None``）。

    トップレベルで ``import webrtcvad`` しない。PyInstaller が contrib の
    ``hook-webrtcvad`` 解析で失敗しやすいため、実行時にだけ読み込む。

    Returns:
        ModuleType | None: ``webrtcvad`` モジュール。利用不可時は ``None``。
    """
    try:
        return importlib.import_module("webrtcvad")
    except Exception:  # noqa: BLE001
        return None


def format_stt_timestamp(seconds: float) -> str:
    """録音開始からの経過秒を表示用タイムコード文字列に変換する。

    Args:
        seconds: 経過秒。負の値は 0 秒として扱う。

    Returns:
        str: ``HH:MM:SS``。100 時間以上は先頭の時間幅を詰めた ``H:MM:SS``。
    """
    s = max(0.0, float(seconds))
    total = int(s)
    h = total // 3600
    m = (total % 3600) // 60
    sec = total % 60
    if h >= 100:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _frame_is_speech_energy(frame_int16: np.ndarray) -> bool:
    """10 ms 分の int16 フレームを RMS で判定するフォールバック VAD。

    Args:
        frame_int16: モノラル ``int16`` 1 フレーム（想定長は ``_FRAME_SAMPLES_48K_10MS``）。

    Returns:
        bool: 正規化 RMS が ``REALTIME_ENERGY_RMS_THRESHOLD`` 以上なら True（発話とみなす）。
    """
    x = frame_int16.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x)))
    return rms >= config.REALTIME_ENERGY_RMS_THRESHOLD


def run_realtime_transcription_loop(
    *,
    stop_event: threading.Event,
    audio_queue: queue.Queue,
    project_root: Path,
    get_model_folder: Callable[[], str],
    emit_text: Callable[[str, float], None],
    emit_error: Callable[[str], None],
) -> None:
    """録音キューから流れるモノラル int16 PCM（48 kHz）を VAD で区切り、逐次文字起こしする。

    ``stop_event`` がセットされ、かつキューが空になったあと、バッファ上の未処理発話を処理して終了する。

    Args:
        stop_event: 録音停止などでセットする ``threading.Event``。
        audio_queue: 録音側が ``put`` する ``int16`` モノラルチャンクの ``queue.Queue``（48 kHz）。
        project_root: ``models/stt/<folder>`` を解決するプロジェクトルート。
        get_model_folder: 使用中の STT サブフォルダ名を返すコールバック（変更時はモデルを差し替える）。
        emit_text: 認識 1 件ごとに ``(text, t_start_sec)`` を渡すコールバック（秒は録音先頭から）。
        emit_error: モデルオープン失敗など致命エラー時にメッセージ文字列を渡すコールバック。

    Returns:
        None
    """
    tr: FastWhisperTranscriber | None = None
    loaded_folder: str | None = None

    def ensure_tr() -> FastWhisperTranscriber | None:
        """``get_model_folder()`` の戻り値に合わせて ``FastWhisperTranscriber`` をロードまたは切り替える。

        Returns:
            FastWhisperTranscriber | None: 利用可能なトランスクライバ。オープン失敗時は ``None``（``emit_error`` 済み）。
        """
        nonlocal tr, loaded_folder
        folder = get_model_folder()
        if tr is not None and loaded_folder == folder:
            return tr
        try:
            new_tr = FastWhisperTranscriber(
                model_size=folder,
                project_root=project_root,
                use_project_models=True,
                device=config.STT_DEVICE,
            )
        except Exception as e:
            emit_error(f"STT モデルを開けません ({folder!r}): {e}")
            return None
        if loaded_folder is not None:
            print(
                f"[STT] モデル切替: {loaded_folder!r} → {folder!r}",
                flush=True,
            )
        else:
            print(
                f"[STT] faster-whisper 準備完了 device={config.STT_DEVICE!r} "
                f"folder={folder!r}",
                flush=True,
            )
        tr = new_tr
        loaded_folder = folder
        return tr

    sr = config.SAMPLE_RATE
    vad_mod = _webrtcvad_module()
    if vad_mod is not None:
        vad = vad_mod.Vad(config.REALTIME_VAD_AGGRESSIVENESS)

        def frame_is_speech(frame: np.ndarray) -> bool:
            return bool(vad.is_speech(frame.tobytes(), sr))

        vad_label = (
            f"webrtcvad (aggressiveness={config.REALTIME_VAD_AGGRESSIVENESS}; "
            "package: webrtcvad-wheels)"
        )
    else:

        def frame_is_speech(frame: np.ndarray) -> bool:
            return _frame_is_speech_energy(frame)

        vad_label = (
            f"RMS>={config.REALTIME_ENERGY_RMS_THRESHOLD}（フォールバック; "
            "``pip install webrtcvad-wheels`` で WebRTC VAD を有効化）"
        )

    if ensure_tr() is None:
        return
    print(f"[STT] VAD: {vad_label}", flush=True)

    silence_need = config.REALTIME_SILENCE_FRAMES_10MS
    min_samples = config.REALTIME_MIN_UTTERANCE_SAMPLES
    max_samples = int(config.SAMPLE_RATE * config.REALTIME_MAX_UTTERANCE_SECONDS)

    pending = np.zeros(0, dtype=np.int16)
    speech_buf = np.zeros(0, dtype=np.int16)
    silence_run = 0
    # 録音セッション先頭からのサンプル番号（モノラル 48kHz）。``pending`` 先頭 = この値。
    next_global_sample = 0
    # 現在 ``speech_buf`` の先頭サンプルが録音全体のどこか（``speech_buf`` が空のときは未使用）
    utterance_first_sample: int | None = None

    def transcribe_chunk(pcm: np.ndarray, global_start_samples: int) -> None:
        """1 発話相当の PCM を必要なら分割して認識し、``emit_text`` で送出する。

        Args:
            pcm: モノラル ``int16`` 波形（48 kHz）。
            global_start_samples: ``pcm`` 先頭が録音全体の何サンプル目か。

        Returns:
            None
        """
        if pcm.size < min_samples:
            return
        offset_samps = global_start_samples
        while pcm.size > 0:
            tr_use = ensure_tr()
            if tr_use is None:
                return
            piece = pcm[:max_samples]
            pcm = pcm[max_samples:]
            piece_t0_sec = offset_samps / sr
            try:
                result = tr_use.transcribe_int16_mono(
                    piece,
                    sample_rate=sr,
                    language="ja",
                    beam_size=3,
                    vad_filter=False,
                    condition_on_previous_text=False,
                )
            except Exception as e:
                emit_error(f"文字起こしエラー: {e}")
                return
            offset_samps += piece.size
            emitted = False
            for seg in result.segments:
                st = seg.text.strip()
                if not st:
                    continue
                g0 = piece_t0_sec + float(seg.start)
                emit_text(st, g0)
                emitted = True
            if not emitted:
                full = result.text.strip()
                if full:
                    emit_text(full, piece_t0_sec)

    def on_silence_flush() -> None:
        """無音が十分続いたときに ``speech_buf`` を 1 発話として ``transcribe_chunk`` へ渡す。

        Returns:
            None
        """
        nonlocal speech_buf, silence_run, utterance_first_sample
        if speech_buf.size == 0:
            silence_run = 0
            return
        buf = speech_buf
        start_s = utterance_first_sample
        speech_buf = np.zeros(0, dtype=np.int16)
        silence_run = 0
        utterance_first_sample = None
        if start_s is None:
            return
        transcribe_chunk(buf, start_s)

    def consume_frame(frame: np.ndarray, frame_global_start: int) -> None:
        """10 ms 1 フレームを VAD し、発話バッファの蓄積・長発話分割・無音フラッシュを行う。

        Args:
            frame: モノラル ``int16``、長さ ``_FRAME_SAMPLES_48K_10MS``。
            frame_global_start: 当該フレーム先頭のグローバルサンプル番号。

        Returns:
            None
        """
        nonlocal speech_buf, silence_run, utterance_first_sample
        is_speech = frame_is_speech(frame)
        if is_speech:
            if speech_buf.size == 0:
                utterance_first_sample = frame_global_start
            speech_buf = np.concatenate([speech_buf, frame])
            silence_run = 0
            if speech_buf.size >= max_samples:
                head = speech_buf[:max_samples]
                speech_buf = speech_buf[max_samples:]
                if utterance_first_sample is not None:
                    transcribe_chunk(head, utterance_first_sample)
                    utterance_first_sample += max_samples
        else:
            silence_run += 1
            if speech_buf.size > 0 and silence_run >= silence_need:
                on_silence_flush()

    def feed_pcm(chunk: np.ndarray) -> None:
        """可変長チャンクを ``pending`` に足し、10 ms フレーム単位で ``consume_frame`` に回す。

        Args:
            chunk: モノラル ``int16`` の録音チャンク（任意長）。

        Returns:
            None
        """
        nonlocal pending, next_global_sample
        if chunk.size == 0:
            return
        pending = np.concatenate([pending, chunk])
        while pending.size >= _FRAME_SAMPLES_48K_10MS:
            frame = pending[:_FRAME_SAMPLES_48K_10MS]
            pending = pending[_FRAME_SAMPLES_48K_10MS:]
            fs = next_global_sample
            next_global_sample += _FRAME_SAMPLES_48K_10MS
            consume_frame(frame, fs)

    backlog_notice_shown = False
    while True:
        if stop_event.is_set() and audio_queue.empty():
            break
        if stop_event.is_set() and not backlog_notice_shown:
            try:
                n_wait = audio_queue.qsize()
            except NotImplementedError:
                n_wait = 0
            if n_wait > 0:
                print(
                    "[STT] 録音を停止しました。キューに残った音声を順に文字起こしします…",
                    flush=True,
                )
                backlog_notice_shown = True
        try:
            chunk = audio_queue.get(timeout=0.08)
        except queue.Empty:
            continue
        feed_pcm(chunk)

    while not audio_queue.empty():
        try:
            feed_pcm(audio_queue.get_nowait())
        except queue.Empty:
            break

    rem = pending
    pending = np.zeros(0, dtype=np.int16)
    while rem.size >= _FRAME_SAMPLES_48K_10MS:
        frame = rem[:_FRAME_SAMPLES_48K_10MS]
        rem = rem[_FRAME_SAMPLES_48K_10MS:]
        fs = next_global_sample
        next_global_sample += _FRAME_SAMPLES_48K_10MS
        consume_frame(frame, fs)
    if rem.size > 0:
        last = np.zeros(_FRAME_SAMPLES_48K_10MS, dtype=np.int16)
        last[: rem.size] = rem
        fs = next_global_sample
        next_global_sample += _FRAME_SAMPLES_48K_10MS
        consume_frame(last, fs)

    if speech_buf.size >= min_samples and utterance_first_sample is not None:
        transcribe_chunk(speech_buf, utterance_first_sample)

    print("[STT] このセッションのリアルタイム文字起こしを完了しました。", flush=True)
