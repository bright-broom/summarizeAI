"""STT（faster-whisper）、モデル配置・DL、リアルタイム文字起こし。"""

from speech_summarizer_ai.settings import STT_MODEL_OPTIONS
from speech_summarizer_ai.stt.faster_whisper_engine import (
    FastWhisperTranscriber,
    TranscriptionResult,
    TranscriptionSegment,
    default_compute_type,
    default_device,
    transcribe_file,
)
from speech_summarizer_ai.stt.model_downloader import (
    download_all_stt_models,
    download_stt_model,
    list_stt_model_status,
)
from speech_summarizer_ai.stt.model_layout import (
    STT_STORAGE_FOLDER_NAMES,
    canonical_stt_folder_name,
    is_stt_model_directory_ready,
    resolve_whisper_model_name,
    stt_download_model_id,
)

__all__ = [
    "STT_MODEL_OPTIONS",
    "STT_STORAGE_FOLDER_NAMES",
    "FastWhisperTranscriber",
    "TranscriptionResult",
    "TranscriptionSegment",
    "canonical_stt_folder_name",
    "default_compute_type",
    "default_device",
    "download_all_stt_models",
    "download_stt_model",
    "is_stt_model_directory_ready",
    "list_stt_model_status",
    "resolve_whisper_model_name",
    "stt_download_model_id",
    "transcribe_file",
]
