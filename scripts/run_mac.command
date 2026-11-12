#!/bin/bash
# macOS 用起動スクリプト（Finder からダブルクリックで起動できる）。
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "先に ./scripts/setup_mac.sh を実行してください。"
  read -r -p "Enter で閉じます..." _
  exit 1
fi
exec .venv/bin/python -m speech_summarizer_ai "$@"
