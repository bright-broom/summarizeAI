"""macOS 用: ``pyaudiowpatch`` 互換の最小 API を ``sounddevice``（PortAudio / CoreAudio）で提供する。

:mod:`speech_summarizer_ai.audio.backend` は PyAudioWPatch（Windows / WASAPI）前提で書かれている。
macOS には WASAPI ループバックが無いため、PC 再生音は **BlackHole 等の仮想オーディオデバイス**
を入力として開いて代用する。

ループバック相当として扱う入力デバイス:

- 環境変数 ``SSAI_LOOPBACK_DEVICE`` に指定した名前（部分一致・大文字小文字無視）
- 未指定時は名前に ``BlackHole`` / ``Loopback`` / ``Soundflower`` を含む入力デバイス

見つからない場合はマイクのみで録音する（backend 側で従来どおり処理される）。
"""

from __future__ import annotations

import os
from typing import Any

paInt16 = 8  # PyAudio の定数値に合わせる（backend からは識別子としてのみ使用）
paWASAPI = 13

_LOOPBACK_NAME_HINTS = ("blackhole", "loopback", "soundflower")


def _sd() -> Any:
    try:
        import sounddevice as sd  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - 環境依存
        raise RuntimeError(
            "sounddevice が見つかりません。pip install sounddevice を実行してください。"
        ) from e
    return sd


def _to_info(index: int, dev: dict[str, Any], *, loopback: bool = False) -> dict[str, Any]:
    return {
        "index": index,
        "name": dev.get("name", "?"),
        "maxInputChannels": int(dev.get("max_input_channels", 0)),
        "maxOutputChannels": int(dev.get("max_output_channels", 0)),
        "defaultSampleRate": float(dev.get("default_samplerate", 48000.0)),
        "isLoopbackDevice": loopback,
    }


def _is_loopback_name(name: str) -> bool:
    want = os.environ.get("SSAI_LOOPBACK_DEVICE", "").strip().lower()
    n = name.lower()
    if want:
        return want in n
    return any(h in n for h in _LOOPBACK_NAME_HINTS)


class _InputStream:
    """``pyaudio.Stream`` 互換（read / get_read_available / stop_stream / close）。"""

    def __init__(self, sd: Any, *, channels: int, rate: int, frames: int, device: int) -> None:
        self._channels = channels
        self._stream = sd.RawInputStream(
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=frames,
            device=device,
            latency="low",
        )
        self._stream.start()

    def read(self, num_frames: int, exception_on_overflow: bool = True) -> bytes:
        data, overflowed = self._stream.read(int(num_frames))
        if overflowed and exception_on_overflow:
            raise OSError("Input overflowed")
        return bytes(data)

    def get_read_available(self) -> int:
        return int(self._stream.read_available)

    def stop_stream(self) -> None:
        if self._stream.active:
            self._stream.stop()

    def close(self) -> None:
        self._stream.close()


class PyAudio:
    """``pyaudiowpatch.PyAudio`` のうち backend が使うメソッドだけを実装する。"""

    paInt16 = paInt16
    paWASAPI = paWASAPI

    def __init__(self) -> None:
        self._sd = _sd()

    def _devices(self) -> list[dict[str, Any]]:
        return list(self._sd.query_devices())

    def get_device_info_by_index(self, index: int) -> dict[str, Any]:
        dev = self._sd.query_devices(index)
        return _to_info(index, dev, loopback=_is_loopback_name(str(dev.get("name", ""))))

    def get_host_api_info_by_type(self, _api_type: int) -> dict[str, Any]:
        # WASAPI は無い。backend は例外時に get_default_input_device_info へフォールバックする。
        raise OSError("WASAPI is not available on macOS")

    def get_default_input_device_info(self) -> dict[str, Any]:
        idx = self._sd.default.device[0]
        if idx is None or int(idx) < 0:
            raise OSError("既定の入力デバイス（マイク）が見つかりません。")
        idx = int(idx)
        dev = self._sd.query_devices(idx)
        if _is_loopback_name(str(dev.get("name", ""))):
            # 既定入力が BlackHole になっている場合は実マイクを探す。
            for i, d in enumerate(self._devices()):
                if int(d.get("max_input_channels", 0)) > 0 and not _is_loopback_name(
                    str(d.get("name", ""))
                ):
                    return _to_info(i, d)
        return _to_info(idx, dev)

    def get_default_wasapi_loopback(self) -> dict[str, Any] | None:
        for i, d in enumerate(self._devices()):
            if int(d.get("max_input_channels", 0)) > 0 and _is_loopback_name(
                str(d.get("name", ""))
            ):
                info = _to_info(i, d, loopback=True)
                info["maxInputChannels"] = min(2, info["maxInputChannels"])
                return info
        return None

    def open(
        self,
        *,
        format: int = paInt16,  # noqa: A002 - PyAudio 互換の引数名
        channels: int,
        rate: int,
        input: bool = True,  # noqa: A002
        frames_per_buffer: int = 1024,
        input_device_index: int | None = None,
        **_: Any,
    ) -> _InputStream:
        if format != paInt16 or not input:
            raise ValueError("int16 入力ストリームのみ対応しています。")
        device = (
            int(input_device_index)
            if input_device_index is not None
            else int(self._sd.default.device[0])
        )
        return _InputStream(
            self._sd, channels=channels, rate=rate, frames=frames_per_buffer, device=device
        )

    def terminate(self) -> None:
        pass
