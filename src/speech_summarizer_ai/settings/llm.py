"""LLM 要約（Foundry Local）の設定。"""

from __future__ import annotations

# STT 反映後、その会議を自動で LLM 要約するか。
AUTO_LLM_SUMMARIZE_AFTER_STT: bool = True

# Foundry Local ``Configuration(app_name=...)`` 用のアプリ名。
FOUNDRY_LLM_APP_NAME: str = "Speech-Summarizer-AI"

# 要約モデルのカタログ別名。SDK が環境に合う完全 ID に解決する。完全 ID 直書きも可。
FOUNDRY_LLM_MODEL_ALIAS: str = "qwen2.5-7b"

# ``True`` で LLM 重みを ``models/llm`` に置き起動時に検査。``False`` は SDK 既定キャッシュ。
FOUNDRY_LLM_CACHE_IN_PROJECT: bool = True

# Foundry モデル DL が「Download was cancelled」等で失敗したときの自動再試行上限（起動ダイアログ）。
FOUNDRY_LLM_DOWNLOAD_CANCEL_AUTO_RETRY_MAX: int = 3

# 会話タイトルの最大文字数。
FOUNDRY_LLM_TITLE_MAX_CHARS: int = 48

# タイトル生成の ``max_tokens``。
FOUNDRY_LLM_TITLE_MAX_TOKENS: int = 160

# Refine 各ステップの ``max_tokens``（小さいと文が途中で切れ、大きいと繰り返し出やすい）。
FOUNDRY_LLM_REFINE_MAX_TOKENS: int = 1280

# Refine: 1 チャンク最大文字数（改行で分割。VAD 非使用）。
FOUNDRY_LLM_REFINE_CHUNK_SIZE: int = 2200

# Refine: 隣接チャンク間の重ね文字数（文脈のつなぎ）。
FOUNDRY_LLM_REFINE_CHUNK_OVERLAP: int = 240

# Map: 文字起こし 1 チャンクの最大文字数（改行単位で分割）。
FOUNDRY_LLM_MAP_CHUNK_SIZE: int = 6000

# Map: チャンクから JSON 抽出するときの ``max_tokens``。小さいと JSON が途中で切れる。
FOUNDRY_LLM_MAP_EXTRACT_MAX_TOKENS: int = 2400

# Map: 抽出 JSON の解析失敗時、再試行だけに使う ``max_tokens``（初回より多め）。
FOUNDRY_LLM_MAP_EXTRACT_RETRY_MAX_TOKENS: int = 4096

# Write: 統合メモから最終要約を生成するときの ``max_tokens``。
FOUNDRY_LLM_MAP_WRITE_MAX_TOKENS: int = 1280
