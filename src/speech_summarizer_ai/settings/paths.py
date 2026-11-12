"""セッション・DB・モデル用のディレクトリ／ファイル名。:mod:`platform_utils.paths` から参照。"""

from __future__ import annotations

# プロジェクトルート直下のセッションルートディレクトリ名。
SESSIONS_DIR_NAME: str = "sessions"

# セッション内に置く録音 WAV のファイル名。
SESSION_AUDIO_FILENAME: str = "audio.wav"

# SQLite データベースディレクトリ名。
DATABASE_DIR_NAME: str = "database"

# SQLite データベースファイル名。
DATABASE_FILENAME: str = "speech_summarizer_ai.sqlite3"

# ローカルに配置する ML 重み類のルート名。
MODELS_DIR_NAME: str = "models"

# ``models/`` 配下の STT モデル用サブディレクトリ名。
MODELS_STT_SUBDIR: str = "stt"

# ``models/`` 配下の LLM モデル用サブディレクトリ名。
MODELS_LLM_SUBDIR: str = "llm"

# Windows: ``%LOCALAPPDATA%`` 下のベンダー／アプリフォルダ（``QSettings("WEEL", ...)`` と揃える）。
WINDOWS_APPDATA_VENDOR_DIR: str = "WEEL"
WINDOWS_APPDATA_APP_DIR: str = "SpeechSummarizerAI"
