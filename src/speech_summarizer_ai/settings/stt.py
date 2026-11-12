"""STT（faster-whisper）とリアルタイム VAD。``webrtcvad-wheels`` が無いときは RMS のみ。"""

from __future__ import annotations

from typing import Literal

# UI に出す選択肢（モデル名, 日本語説明）のタプル。
STT_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    # ("tiny", "最低精度・最高速"),
    ("base", "低精度・高速"),
    ("small", "中精度・中速"),
    ("medium", "高精度・低速"),
    # ("large", "最高精度・最低速"),
)

# 起動時・UI 未同期時の既定 STT モデル（``STT_MODEL_OPTIONS`` のフォルダ名のいずれか）。
STT_DEFAULT_MODEL: str = "small"
if STT_DEFAULT_MODEL not in {f for f, _ in STT_MODEL_OPTIONS}:
    raise ValueError(
        f"STT_DEFAULT_MODEL={STT_DEFAULT_MODEL!r} must appear in STT_MODEL_OPTIONS"
    )

# 推論デバイスの選択肢（型エイリアス）。
SttDevice = Literal["cpu", "cuda", "auto"]

# 既定の推論デバイス。
STT_DEVICE: SttDevice = "cpu"

# WebRTC VAD（``webrtcvad``）の積極度（0〜3）。大きいほど非発話を切り落とす。
REALTIME_VAD_AGGRESSIVENESS: int = 2

# WebRTC VAD が使えないとき、またはフォールバック時の正規化 RMS 閾値（10ms フレーム）。
REALTIME_ENERGY_RMS_THRESHOLD: float = 0.018

# 発話終端と判定する無音フレーム数（10ms 単位）。
REALTIME_SILENCE_FRAMES_10MS: int = 25

# 短すぎる発話を捨てる最小サンプル数（48 kHz で 0.2 秒相当）。
REALTIME_MIN_UTTERANCE_SAMPLES: int = 9600

# 1 発話として扱う最大秒数（安全装置）。
REALTIME_MAX_UTTERANCE_SECONDS: float = 25.0
