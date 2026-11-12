"""開発用エントリポイント。

リポジトリルートから ``python scripts/run_dev.py`` で起動する。

``src/`` を ``sys.path`` に追加することで、editable install していない状態でも
``speech_summarizer_ai`` パッケージを import できるようにする。

本番配布では ``pip install -e .`` 後に以下のいずれかで起動すること。

- ``python -m speech_summarizer_ai``
- ``speech-summarizer-ai``
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from speech_summarizer_ai.app import main  # noqa: E402  sys.path 調整後の import

if __name__ == "__main__":
    sys.exit(main())
