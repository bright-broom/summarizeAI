#!/bin/bash
# macOS 用: 「Speech Summarizer AI.app」と配布用 .dmg をビルドし、/Applications にインストールする。
#
#   ./scripts/build_mac_app.sh              # .app + .dmg を作り、/Applications にもコピー
#   ./scripts/build_mac_app.sh --no-install # /Applications へはコピーしない（CI 等）
#   ./scripts/build_mac_app.sh --no-dmg     # .dmg を作らない
#
# 署名と公証（任意。設定するとダウンロードした人の Mac で警告が出なくなる）:
#   MACOS_SIGN_IDENTITY  "Developer ID Application: 氏名 (TEAMID)"（キーチェーンにある証明書名）
#   APPLE_ID / APPLE_TEAM_ID / APPLE_APP_PASSWORD  公証用（App 用パスワードは appleid.apple.com で発行）
# 未設定ならアドホック署名（自分の Mac で使う分には問題なし。配布先では初回に許可操作が必要）。
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

# 3) 署名
SIGN_ID="${MACOS_SIGN_IDENTITY:-}"
ENTITLEMENTS="packaging/macos/entitlements.plist"
if [[ -n "$SIGN_ID" ]]; then
  echo "==> Developer ID で署名（Hardened Runtime）: ${SIGN_ID}"
  xattr -cr "$APP" || true
  sign_one() {
    codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" \
      --sign "$SIGN_ID" "$1"
  }
  # 内側から順に署名する（dylib / so / 実行ファイル → .framework → .app）
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then sign_one "$f"; fi
  done < <(find "$APP/Contents" -type f -print0)
  while IFS= read -r -d '' fw; do
    sign_one "$fw"
  done < <(find "$APP/Contents" -type d -name "*.framework" -print0 | sort -rz)
  sign_one "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  # アドホック署名（Apple Silicon では署名が無いと起動できない）
  echo "==> アドホック署名（MACOS_SIGN_IDENTITY 未設定）"
  codesign --force --deep --sign - "$APP"
  xattr -cr "$APP" || true
fi

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
3. マイクへのアクセスを求められたら「許可」してください。

■「開けません」「マルウェアが含まれていないことを検証できません」と出た場合
  このアプリは Apple の公証を受けていないため、初回だけ許可が必要です。
  ※ ダイアログでは「ゴミ箱に入れる」ではなく「完了」を押してください。

  方法A（設定画面から）
    「システム設定」→「プライバシーとセキュリティ」→ 下の方にある
    「"Speech Summarizer AI" は…ブロックされました」の「このまま開く」を押し、
    もう一度アプリを開いて「このまま開く」→ パスワード入力。

  方法B（ターミナルで 1 行）
    xattr -dr com.apple.quarantine "/Applications/Speech Summarizer AI.app"

初回起動時に音声認識・要約用の AI モデル（約 5GB）をダウンロードします。
音声・文字起こし・要約はこの Mac の中だけで処理されます。
ログ: ~/Library/Logs/SpeechSummarizerAI.log
TXT
  rm -f "$DMG"
  hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -fs HFS+ -format UDZO "$DMG" >/dev/null
  rm -rf "$STAGE"
  # DMG はアドホック署名しない（アドホック署名の DMG はダウンロード後に開く時点で
  # 「マルウェアの可能性」としてブロックされる）。Developer ID がある場合のみ署名・公証する。
  if [[ -n "$SIGN_ID" ]]; then
    echo "==> DMG に署名"
    codesign --force --timestamp --sign "$SIGN_ID" "$DMG"
    if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
      echo "==> Apple に公証を依頼（数分かかります）"
      xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" --wait
      xcrun stapler staple "$DMG"
      spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
    else
      echo "（APPLE_ID / APPLE_TEAM_ID / APPLE_APP_PASSWORD が未設定のため公証はスキップ）"
    fi
  fi
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
