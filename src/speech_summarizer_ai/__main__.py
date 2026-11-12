"""``python -m speech_summarizer_ai`` による CLI エントリ。"""

from __future__ import annotations

import sys

from speech_summarizer_ai.app import main

if __name__ == "__main__":
    sys.exit(main())
