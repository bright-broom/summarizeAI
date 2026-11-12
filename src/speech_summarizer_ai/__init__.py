"""Speech Summarizer AI パッケージ。"""

from __future__ import annotations

from importlib.metadata import version

try:
    __version__ = version("speech-summarizer-ai")
except Exception:  # noqa: BLE001 — editable install 前のフォールバック
    __version__ = "0.1.0"
