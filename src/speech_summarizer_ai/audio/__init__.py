"""マイク・ループバックの録音（ストリーミング WAV はコントローラ側で ``wave`` に書き込む）。"""

from speech_summarizer_ai.audio.backend import run_recording_session

__all__ = [
    "run_recording_session",
]
