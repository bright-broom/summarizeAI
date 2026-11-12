"""STT（faster-whisper）とリアルタイム VAD。``webrtcvad-wheels`` が無いときは RMS のみ。"""

from __future__ import annotations

from typing import Literal

# UI に出す選択肢（モデル名, 日本語説明）のタプル。
# ``kotoba`` は日本語特化の kotoba-whisper v2.0（large-v3 を日本語で蒸留。汎用 medium より日本語が大幅に高精度）。
STT_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    # ("tiny", "最低精度・最高速"),
    ("base", "高速（精度低）"),
    ("small", "標準"),
    ("kotoba", "日本語・高精度（推奨）"),
    # ("medium", "高精度・低速"),
    # ("large", "最高精度・最低速"),
)

# 起動時・UI 未同期時の既定 STT モデル（``STT_MODEL_OPTIONS`` のフォルダ名のいずれか）。
STT_DEFAULT_MODEL: str = "kotoba"
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

# 発話終端と判定する無音フレーム数（10ms 単位）。短すぎると文の途中で切れて文脈を失うため 0.6 秒。
REALTIME_SILENCE_FRAMES_10MS: int = 60

# 発話が短い（REALTIME_MERGE_MIN_SECONDS 未満）ときは、この長さの無音まで待って次の発話とまとめる。
# Whisper は 1 回の認識が常に 30 秒窓なので、細切れより数秒以上まとめた方が速く、文脈も保てる。
REALTIME_SHORT_UTTERANCE_SILENCE_FRAMES_10MS: int = 120
REALTIME_MERGE_MIN_SECONDS: float = 4.0

# 短すぎる発話を捨てる最小サンプル数（48 kHz で 0.2 秒相当）。
REALTIME_MIN_UTTERANCE_SAMPLES: int = 9600

# 1 発話として扱う最大秒数（Whisper の 30 秒窓に収める）。超えたら直近の最も静かな位置で区切る。
REALTIME_MAX_UTTERANCE_SECONDS: float = 25.0

# 認識のビーム幅（大きいほど高精度・低速）。
STT_BEAM_SIZE: int = 5

# 直前の認識結果をヒントとして渡す文字数（用語・表記・句読点の一貫性が上がる）。0 で無効。
STT_CONTEXT_PROMPT_CHARS: int = 120

# 文脈ヒントを使うモデル。scripts/stt_benchmark.py の計測で、small は改善（CER 5.3%→3.3%）、
# kotoba（蒸留モデル）は文が丸ごと欠落して大幅に悪化（2.0%→59.8%）、base も悪化したため small のみ。
STT_CONTEXT_PROMPT_MODELS: tuple[str, ...] = ("small",)
