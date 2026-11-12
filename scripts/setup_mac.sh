#!/bin/bash
# macOS 用セットアップ: 仮想環境 (.venv) を作成し依存関係を入れる。
#   ./scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname)" != "Darwin" ]]; then
  echo "このスクリプトは macOS 用です。" >&2
  exit 1
fi

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in python3.12 python3.11 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        PY="$c"; break
      fi
    fi
  done
fi
if [[ -z "$PY" ]]; then
  echo "Python 3.11 以上が必要です。例: brew install python@3.12" >&2
  exit 1
fi
echo "使用する Python: $($PY --version) ($PY)"

"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-mac.txt
pip install -e . --no-deps

echo
echo "セットアップ完了。起動するには:"
echo "  ./scripts/run_mac.command   （Finder からダブルクリックでも可）"
if [[ "$(uname -m)" != "arm64" ]]; then
  echo
  echo "※ Intel Mac のため要約 LLM は Ollama を使います:"
  echo "   brew install ollama && ollama serve &  &&  ollama pull qwen2.5:7b"
fi
