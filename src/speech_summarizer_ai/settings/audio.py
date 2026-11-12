"""録音・音声入出力に関する設定定数。"""

from __future__ import annotations

from typing import Literal

# WASAPI は 48 kHz で安定しやすい。
SAMPLE_RATE: int = 48_000

# int16 PCM の 1 サンプルあたりのバイト数。
SAMPLE_WIDTH: int = 2

# 録音コールバックでまとめて扱うフレーム数。
BLOCK_FRAMES: int = 1024

# ``mono`` はマイク + PC 音を 1ch に合成、``stereo`` は L=マイク / R=PC。
RecordLayout = Literal["mono", "stereo"]

# 既定の録音レイアウト。
RECORD_LAYOUT: RecordLayout = "mono"

# モノラル合成時のマイク側ゲイン（ループバックより小さいため持ち上げる）。
MONO_MIC_GAIN: float = 3.5

# モノラル合成時の PC ループバック側ゲイン。
MONO_PC_GAIN: float = 1.0

# True のとき、録音中にセッション WAV へストリーミング書き込みする。False ではファイルに保存しない。
SAVE_RECORDED_AUDIO_TO_FILE: bool = False


def output_channel_count() -> int:
    """現在の :data:`RECORD_LAYOUT` に応じた WAV 出力チャンネル数を返す。

    Returns:
        int: モノラル設定なら ``1``、ステレオなら ``2``。
    """
    return 1 if RECORD_LAYOUT == "mono" else 2
