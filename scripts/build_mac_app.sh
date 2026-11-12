#!/bin/bash
# macOS 用: 「Speech Summarizer AI.app」と配布用 .dmg をビルドし、/Applications にインストールする。
#
#   ./scripts/build_mac_app.sh              # .app + .dmg を作り、/Applications にもコピー
#   ./scripts/build_mac_app.sh --no-install # /Applications へはコピーしない（CI 等）
#   ./scripts/build_mac_app.sh --no-dmg     # .dmg を作らない
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="Speech Summarizer AI"
APP="dist/${APP_NAME}.app"
INSTALL=1
MAKE_DMG=1
for a in "$@"; do
  case "$a" in
    --no-install) INSTALL=0 ;;
    --dmg) MAKE_DMG=1 ;;
    --no-dmg) MAKE_DMG=0 ;;
    *) echo "不明なオプション: $a" >&2; exit 2 ;;
  esac
done

if [[ "$(uname)" != "Darwin" ]]; then
  echo "このスクリプトは macOS 用です。" >&2
  exit 1
fi

# 1) 仮想環境と依存関係
if [[ ! -x .venv/bin/python ]]; then
  echo "==> 仮想環境が無いのでセットアップします"
  ./scripts/setup_mac.sh
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> 依存関係を確認"
pip install -q -r requirements-mac.txt
pip install -q -e . --no-deps
VERSION="$(python -c 'import speech_summarizer_ai as m; print(m.__version__)')"
ARCH="$(uname -m)"
pip install -q "pyinstaller>=6.19" "pyinstaller-hooks-contrib>=2026.1"

# 2) ビルド
echo "==> .app をビルド中（数分かかります）"
rm -rf build "dist/SpeechSummarizerAI" "$APP"
pyinstaller --noconfirm --clean --log-level WARN speech_summarizer_ai_mac.spec

if [[ ! -d "$APP" ]]; then
  echo "ビルドに失敗しました: $APP が見つかりません。" >&2
  exit 1
fi

# 3) 署名（ローカル用のアドホック署名。Apple Silicon では署名が無いと起動できない）
echo "==> アドホック署名"
codesign --force --deep --sign - "$APP"
xattr -cr "$APP" || true

# 4) 配布用 DMG（ドラッグ＆ドロップで「アプリケーション」へ入れる形式）
DMG=""
if [[ "$MAKE_DMG" == 1 ]]; then
  DMG="dist/SpeechSummarizerAI-${VERSION}-${ARCH}.dmg"
  echo "==> ${DMG} を作成"
  STAGE="$(mktemp -d)"
  ditto "$APP" "${STAGE}/${APP_NAME}.app"
  ln -s /Applications "${STAGE}/Applications"
  cat > "${STAGE}/はじめにお読みください.txt" <<'TXT'
Speech Summarizer AI のインストール

1. 「Speech Summarizer AI」を右の「Applications」フォルダへドラッグします。
2. アプリケーションフォルダから「Speech Summarizer AI」を開きます。
   ※ 初回だけ「開けません」と出た場合は、アイコンを右クリック →「開く」→「開く」。
     （macOS 15 以降は「システム設定 → プライバシーとセキュリティ」下部の「このまま開く」）
3. マイクへのアクセスを求められたら「許可」してください。

初回起動時に音声認識・要約用の AI モデル（約 5GB）をダウンロードします。
音声・文字起こし・要約はこの Mac の中だけで処理されます。
ログ: ~/Library/Logs/SpeechSummarizerAI.log
TXT
  rm -f "$DMG"
  hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -fs HFS+ -format UDZO "$DMG" >/dev/null
  rm -rf "$STAGE"
  codesign --force --sign - "$DMG" || true
fi

# 5) インストール
if [[ "$INSTALL" == 1 ]]; then
  DEST="/Applications/${APP_NAME}.app"
  echo "==> ${DEST} にインストール"
  if [[ -d "$DEST" ]]; then
    osascript -e "tell application \"${APP_NAME}\" to quit" >/dev/null 2>&1 || true
    rm -rf "$DEST" 2>/dev/null || sudo rm -rf "$DEST"
  fi
  ditto "$APP" "$DEST" 2>/dev/null || sudo ditto "$APP" "$DEST"
  APP="$DEST"
fi

echo
echo "完了: ${APP}"
[[ -n "$DMG" ]] && echo "DMG : $(pwd)/${DMG}"
echo "Launchpad または アプリケーションフォルダから「${APP_NAME}」をダブルクリックで起動できます。"
echo "ログ: ~/Library/Logs/SpeechSummarizerAI.log"
if [[ "$INSTALL" == 1 ]]; then
  open -R "$APP" || true
fi
