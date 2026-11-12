"""自動アップデートの設定。"""

from __future__ import annotations

# 更新を配信する公開リポジトリ（GitHub Releases）。空文字で自動アップデートを無効化。
# ソースコードのリポジトリは非公開のまま、DMG だけをここに載せる（.github/workflows/build-macos-dmg.yml）。
UPDATE_RELEASES_REPO: str = "bright-broom/summarizeAI-releases"

# 起動後、最初に確認するまでの秒数と、その後の確認間隔（時間）。
UPDATE_FIRST_CHECK_DELAY_SECONDS: int = 8
UPDATE_CHECK_INTERVAL_HOURS: float = 6.0
