"""マイク・ループバック録音と WAV 出力（PyAudioWPatch / WASAPI）。

録音スレッドは read() とキュー投入のみ。NumPy 処理は別スレッドに寄せ、WASAPI の
data discontinuity を抑える。停止時はセンチネルでキューを完走させる。
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from speech_summarizer_ai import settings as config

_pa_module = None


def _pyaudio() -> Any:
    """PyAudioWPatch を遅延 import する。"""
    global _pa_module
    if _pa_module is None:
        import pyaudiowpatch as pyaudio

        _pa_module = pyaudio
    return _pa_module


def get_loopback_device_info(pa_instance: Any) -> dict | None:
    """既定スピーカーに対応する WASAPI ループバックデバイス情報を返す。

    Args:
        pa_instance: ``pyaudiowpatch.PyAudio`` インスタンス。

    Returns:
        dict | None: デバイス情報辞書。見つからなければ ``None``。
    """
    try:
        return pa_instance.get_default_wasapi_loopback()
    except Exception:
        return None


def get_default_wasapi_microphone_device_info(pa_instance: Any) -> dict | None:
    """WASAPI の既定録音デバイス（既定マイク）を返す。

    MME/DirectSound の既定入力は WASAPI ループバックとずれ、再生だけ入りマイクが
    聞こえないことがある。WASAPI の ``defaultInputDevice`` を使う。

    Args:
        pa_instance: ``pyaudiowpatch.PyAudio`` インスタンス。

    Returns:
        dict | None: 入力チャンネルあり・ループバックでないデバイス。失敗時は ``None``。
    """
    try:
        pa_cls = type(pa_instance)
        api = pa_instance.get_host_api_info_by_type(pa_cls.paWASAPI)
        idx = int(api["defaultInputDevice"])
        if idx < 0:
            return None
        info = pa_instance.get_device_info_by_index(idx)
        if int(info.get("maxInputChannels", 0)) < 1:
            return None
        if info.get("isLoopbackDevice"):
            return None
        return info
    except Exception:
        return None


def to_mono(samples: np.ndarray) -> np.ndarray:
    """多チャンネル音声をモノラル float32 に変換する。

    Args:
        samples: 入力サンプル（1D または 2D）。

    Returns:
        np.ndarray: モノラル ``float32`` 1 次元配列。
    """
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    if samples.ndim == 1:
        return samples.astype(np.float32, copy=False)
    return np.mean(samples, axis=1).astype(np.float32)


def to_stereo_interleaved(mono_left: np.ndarray, mono_right: np.ndarray) -> np.ndarray:
    """左右モノラルをインターリーブされた int16 PCM に変換する。

    Args:
        mono_left: 左チャンネル（マイク相当）の float サンプル。
        mono_right: 右チャンネル（PC 音相当）の float サンプル。

    Returns:
        np.ndarray: LRLR… の ``int16`` 1 次元配列。
    """
    n = mono_left.shape[0]
    assert mono_right.shape[0] == n
    left_i16 = (np.clip(mono_left, -1.0, 1.0) * 32767.0).astype(np.int16)
    right_i16 = (np.clip(mono_right, -1.0, 1.0) * 32767.0).astype(np.int16)
    out = np.empty(n * 2, dtype=np.int16)
    out[0::2] = left_i16
    out[1::2] = right_i16
    return out


def mix_to_mono_pcm(mono_mic: np.ndarray, mono_pc: np.ndarray) -> np.ndarray:
    """マイクと PC 音をゲイン付きで合成し int16 PCM にする。

    Args:
        mono_mic: マイクのモノラル float サンプル。
        mono_pc: ループバックのモノラル float サンプル。

    Returns:
        np.ndarray: クリップ済み ``int16`` モノラル PCM。
    """
    mixed = mono_mic * config.MONO_MIC_GAIN + mono_pc * config.MONO_PC_GAIN
    return (np.clip(mixed, -1.0, 1.0) * 32767.0).astype(np.int16)


def _bytes_to_float32(data: bytes, channels: int) -> np.ndarray:
    """int16 PCM バイト列を shape=(frames, channels) の float32 配列に変換する。

    Args:
        data: int16 リトルエンディアン PCM バイト列。
        channels: チャンネル数。

    Returns:
        np.ndarray: shape ``(frames, channels)`` の ``float32`` 配列（-1.0〜1.0 正規化済み）。
    """
    arr = np.frombuffer(data, dtype=np.int16)
    if arr.size == 0 or channels == 0:
        return np.zeros((0, max(channels, 1)), dtype=np.float32)
    frames = arr.size // channels
    return (
        arr[: frames * channels].reshape(frames, channels).astype(np.float32) / 32768.0
    )


def _resample_to_target(
    frames: np.ndarray, src_rate: int, target_len: int
) -> np.ndarray:
    """線形補間で ``frames`` を ``target_len`` サンプルにリサンプルする。

    Args:
        frames: shape ``(src_len, channels)`` の float32 配列。
        src_rate: 入力のサンプルレート（ログ用。実際には src_len と target_len の比で計算）。
        target_len: 出力フレーム数。

    Returns:
        np.ndarray: shape ``(target_len, channels)`` の float32 配列。
    """
    src_len = frames.shape[0]
    if src_len == 0 or target_len == 0:
        return np.zeros(
            (target_len, frames.shape[1] if frames.ndim > 1 else 1), dtype=np.float32
        )
    if src_len == target_len:
        return frames
    indices = np.linspace(0, src_len - 1, target_len)
    low = np.floor(indices).astype(np.int32)
    high = np.minimum(low + 1, src_len - 1)
    frac = (indices - low).astype(np.float32)
    if frames.ndim == 1:
        return frames[low] * (1.0 - frac) + frames[high] * frac
    frac_2d = frac[:, np.newaxis]
    return frames[low] * (1.0 - frac_2d) + frames[high] * frac_2d


def _process_raw_pair(
    mic_frames: np.ndarray,
    loopback: np.ndarray | None,
    nm: int,
    *,
    recording_pcm_sink: Callable[[np.ndarray], None] | None,
    live_mono_chunk_callback: Callable[[np.ndarray], None] | None,
) -> None:
    """1 組の生フレームを混合し、任意でファイル_sink とライブ STT に渡す（処理スレッド専用）。

    Args:
        mic_frames: マイクの float32 配列 shape ``(nm, channels)``。
        loopback: ループバック。無い場合は ``None``。
        nm: マイクフレームのサンプル数。
        recording_pcm_sink: 任意。保存が有効なときのみ WAV に書き込む ``int16`` PCM を渡す。
        live_mono_chunk_callback: 任意。リアルタイム STT 用モノラル int16。

    Returns:
        None
    """
    mono_m = to_mono(mic_frames)
    if loopback is not None:
        nl = int(loopback.shape[0])
        if nl == 0:
            mono_l = np.zeros(nm, dtype=np.float32)
        else:
            mono_l = to_mono(loopback)
            if nl != nm:
                mono_l = to_mono(_resample_to_target(loopback, 0, nm))
    else:
        mono_l = np.zeros(nm, dtype=np.float32)

    # 保存用と STT 用を分け、STT には mix_to_mono_pcm（マイク重視）を渡す。
    # L/R 単純平均だと再生が大きいとマイクが VAD に届かない。
    mono_for_stt = mix_to_mono_pcm(mono_m, mono_l)
    if config.RECORD_LAYOUT == "mono":
        pcm = mono_for_stt
    else:
        pcm = to_stereo_interleaved(mono_m, mono_l)
    if recording_pcm_sink is not None:
        recording_pcm_sink(pcm)
    if live_mono_chunk_callback is not None:
        live_mono_chunk_callback(mono_for_stt.copy())


def capture_loop(
    mic_stream: Any,
    loopback_stream: Any | None,
    mic_channels: int,
    mic_open_rate: int,
    loopback_channels: int,
    loopback_rate: int,
    stop_event: threading.Event,
    recording_pcm_sink: Callable[[np.ndarray], None] | None,
    live_mono_chunk_callback: Callable[[np.ndarray], None] | None = None,
) -> None:
    """PyAudioWPatch ストリームからマイク（と任意のループバック）を録音する。

    マイクは ``mic_open_rate`` で開き、内部で ``config.SAMPLE_RATE`` に揃えてから混合する。
    ループバックはマイク 1 ブロックと同じ時間幅になるようフレーム数を合わせる。
    録音ファイルへは ``recording_pcm_sink`` でチャンク単位書き込みし、メモリには蓄えない。

    Args:
        mic_stream: マイク PyAudio ストリーム。
        loopback_stream: ループバック PyAudio ストリーム。無ければ ``None``。
        mic_channels: マイクのチャンネル数。
        mic_open_rate: マイクストリームのサンプルレート（Hz）。
        loopback_channels: ループバックのチャンネル数。
        loopback_rate: ループバックのサンプルレート（Hz）。
        stop_event: ループ終了用イベント。
        recording_pcm_sink: 任意。保存が有効なときのみ WAV 用 PCM を渡す。
        live_mono_chunk_callback: 任意。リアルタイム STT 用 int16 モノラル（処理スレッドから呼ぶ）。

    Returns:
        None
    """
    raw_queue: queue.Queue[tuple[bytes, bytes | None] | None] = queue.Queue()

    def processor() -> None:
        """キューから生バイト列を取り出し変換・混合する。"""
        while True:
            item = raw_queue.get()
            if item is None:
                return
            m_bytes, l_bytes = item
            try:
                mic_frames = _bytes_to_float32(m_bytes, mic_channels)
                nm = mic_frames.shape[0]
                if mic_open_rate != config.SAMPLE_RATE:
                    nm_tgt = max(1, int(round(nm * config.SAMPLE_RATE / mic_open_rate)))
                    mic_frames = _resample_to_target(mic_frames, mic_open_rate, nm_tgt)
                    nm = mic_frames.shape[0]
                if l_bytes is not None and loopback_channels > 0:
                    lb_raw = _bytes_to_float32(l_bytes, loopback_channels)
                    if lb_raw.shape[0] != nm:
                        lb_raw = _resample_to_target(lb_raw, loopback_rate, nm)
                    lb: np.ndarray | None = lb_raw
                else:
                    lb = None
                _process_raw_pair(
                    mic_frames,
                    lb,
                    nm,
                    recording_pcm_sink=recording_pcm_sink,
                    live_mono_chunk_callback=live_mono_chunk_callback,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[audio] 処理スレッドでエラー: {e}", file=sys.stderr, flush=True)

    proc_thread = threading.Thread(target=processor, name="AudioProcessor", daemon=True)
    proc_thread.start()

    try:
        while not stop_event.is_set():
            try:
                m_bytes = mic_stream.read(
                    config.BLOCK_FRAMES, exception_on_overflow=False
                )
            except Exception as e:  # noqa: BLE001
                print(f"[audio] マイク読み取りエラー: {e}", file=sys.stderr, flush=True)
                time.sleep(0.005)
                continue

            l_bytes: bytes | None = None
            if loopback_stream is not None:
                lb_frames = max(
                    1,
                    int(
                        round(
                            config.BLOCK_FRAMES
                            * float(loopback_rate)
                            / float(mic_open_rate)
                        )
                    ),
                )
                try:
                    # 再生が無いとループバック read がブロックし録音・STT が止まる。
                    # 取れる分だけ読み、不足分は無音で埋める。
                    avail = loopback_stream.get_read_available()
                    if avail < 0:
                        avail = 0
                    if avail <= 0:
                        n_int16 = lb_frames * loopback_channels
                        l_bytes = np.zeros(n_int16, dtype=np.int16).tobytes()
                    elif avail >= lb_frames:
                        l_bytes = loopback_stream.read(
                            lb_frames, exception_on_overflow=False
                        )
                    else:
                        l_bytes = loopback_stream.read(
                            int(avail), exception_on_overflow=False
                        )
                        need_bytes = (
                            lb_frames * loopback_channels * config.SAMPLE_WIDTH
                            - len(l_bytes)
                        )
                        if need_bytes > 0:
                            l_bytes = l_bytes + bytes(need_bytes)
                except Exception:  # noqa: BLE001
                    l_bytes = None

            raw_queue.put((m_bytes, l_bytes))
    finally:
        raw_queue.put(None)
        proc_thread.join()


def run_recording_session(
    stop_event: threading.Event,
    error_slot: list[str | None],
    *,
    live_mono_chunk_callback: Callable[[np.ndarray], None] | None = None,
    recording_pcm_sink: Callable[[np.ndarray], None] | None = None,
) -> None:
    """バックグラウンドスレッドから呼び出し、録音セッションを実行する（PyAudioWPatch）。

    マイクと WASAPI ループバック（PC 再生音）を同時録音する。
    PCM はメモリにリスト蓄積せず、``recording_pcm_sink`` があればチャンク単位で渡す。
    終了時に例外があれば ``error_slot[0]`` にメッセージ文字列を格納する。

    Args:
        stop_event: 録音ループを止めるイベント。
        error_slot: 長さ 1 のリスト。エラー時に ``[0]`` に文字列を書き込む。
        live_mono_chunk_callback: 任意。リアルタイム STT 用（``capture_loop`` 参照）。
        recording_pcm_sink: 任意。ファイル保存が有効なとき WAV 用 PCM（``capture_loop`` 参照）。

    Returns:
        None
    """
    error_slot[0] = None
    pyaudio = _pyaudio()
    pa = pyaudio.PyAudio()

    mic_stream = None
    loopback_stream = None

    try:
        # --- マイク: WASAPI 既定入力（Windows の「既定のデバイス」と一致しやすい）
        mic_info = get_default_wasapi_microphone_device_info(pa)
        if mic_info is None:
            mic_info = pa.get_default_input_device_info()
        mic_index = int(mic_info["index"])
        max_in = int(mic_info.get("maxInputChannels", 0))
        mic_channels = max(1, min(max_in, 2))
        native_rate = int(
            round(float(mic_info.get("defaultSampleRate", config.SAMPLE_RATE)))
        )

        # --- ループバックデバイス（PC 再生音）---
        loopback_info = get_loopback_device_info(pa)
        loopback_channels = 0
        loopback_rate = config.SAMPLE_RATE

        mic_stream = None
        mic_open_rate = config.SAMPLE_RATE
        open_err: BaseException | None = None
        for rate in (config.SAMPLE_RATE, native_rate):
            if rate <= 0:
                continue
            try:
                mic_stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=mic_channels,
                    rate=rate,
                    input=True,
                    frames_per_buffer=config.BLOCK_FRAMES,
                    input_device_index=mic_index,
                )
                mic_open_rate = rate
                break
            except Exception as e:
                open_err = e
        if mic_stream is None:
            if open_err is not None:
                raise open_err
            raise RuntimeError("マイクストリームを開けませんでした。")

        print(
            f"[audio] マイク: {mic_info.get('name', '?')} "
            f"(ch={mic_channels} open={mic_open_rate}Hz native={native_rate}Hz idx={mic_index})",
            flush=True,
        )

        # ループバックストリームを開く
        if loopback_info is not None:
            try:
                loopback_channels = int(loopback_info["maxInputChannels"])
                loopback_rate = int(
                    loopback_info.get("defaultSampleRate", config.SAMPLE_RATE)
                )
                loopback_block_frames = max(
                    1,
                    int(
                        round(
                            config.BLOCK_FRAMES
                            * float(loopback_rate)
                            / float(mic_open_rate)
                        )
                    ),
                )
                loopback_stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=loopback_channels,
                    rate=loopback_rate,
                    input=True,
                    frames_per_buffer=loopback_block_frames,
                    input_device_index=int(loopback_info["index"]),
                )
                print(
                    f"[audio] ループバック: {loopback_info.get('name', '?')} "
                    f"({loopback_channels}ch, {loopback_rate}Hz)",
                    flush=True,
                )
            except Exception as e:
                print(
                    f"[audio] ループバックストリームの開設に失敗しました: {e}",
                    file=sys.stderr,
                    flush=True,
                )
                loopback_stream = None
                loopback_channels = 0
        else:
            print(
                "[audio] ループバックデバイスが見つかりません。マイクのみで録音します。",
                file=sys.stderr,
                flush=True,
            )

        capture_loop(
            mic_stream,
            loopback_stream,
            mic_channels,
            mic_open_rate,
            loopback_channels,
            loopback_rate,
            stop_event,
            recording_pcm_sink,
            live_mono_chunk_callback=live_mono_chunk_callback,
        )

    except Exception as e:
        print(f"[audio] 録音エラー: {e}", file=sys.stderr, flush=True)
        error_slot[0] = str(e)
    finally:
        if mic_stream is not None:
            try:
                mic_stream.stop_stream()
                mic_stream.close()
            except Exception:  # noqa: BLE001
                pass
        if loopback_stream is not None:
            try:
                loopback_stream.stop_stream()
                loopback_stream.close()
            except Exception:  # noqa: BLE001
                pass
        pa.terminate()
