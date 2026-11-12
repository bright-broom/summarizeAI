"""``python -m speech_summarizer_ai`` による CLI エントリ。"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    # PyInstaller でまとめた実行ファイル（.exe / .app）で子プロセスが再起動ループしないように。
    multiprocessing.freeze_support()

    from speech_summarizer_ai.app import main

    sys.exit(main())
