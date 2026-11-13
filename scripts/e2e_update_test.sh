#!/bin/bash
# 自動アップデートの E2E テスト（macOS・CI 用）。ビルド済みの .app を使い、実際の更新経路を通す。
#
#   ./scripts/e2e_update_test.sh "dist/Speech Summarizer AI.app"
#
# 1. 「インストール済み」の .app と、目印ファイルを入れた「新しい版」の DMG を用意する
# 2. ローカルの偽リリースサーバーで GitHub API の /releases/latest を真似る
# 3. 改ざんした DMG（SHA-256 不一致）→ 入れ替えられないこと
# 4. 正しい DMG → 入れ替え・再起動されること、作業ファイルが残らないこと
set -euo pipefail

SRC_APP="${1:?ビルド済み .app のパスを指定してください}"
APP_NAME="Speech Summarizer AI"
W="${RUNNER_TEMP:-$(mktemp -d)}/update-e2e"
PORT=8765
rm -rf "$W"; mkdir -p "$W/Applications" "$W/new" "$W/srv"
DEST="$W/Applications/${APP_NAME}.app"
BIN="$DEST/Contents/MacOS/SpeechSummarizerAI"
MARKER="Contents/Resources/e2e-update-marker"

cleanup() {
  [[ -n "${SRV_PID:-}" ]] && kill "$SRV_PID" 2>/dev/null || true
  pkill -f "$W/Applications" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> インストール済みの版を用意"
ditto "$SRC_APP" "$DEST"

echo "==> 新しい版（目印ファイル入り）の DMG を用意"
ditto "$SRC_APP" "$W/new/${APP_NAME}.app"
echo "e2e" > "$W/new/${APP_NAME}.app/$MARKER"
codesign --force --deep --sign - "$W/new/${APP_NAME}.app"
DMG="$W/srv/SpeechSummarizerAI-9.9.9-arm64.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$W/new" -ov -fs HFS+ -format UDZO "$DMG" >/dev/null
SHA="$(shasum -a 256 "$DMG" | cut -d' ' -f1)"
SIZE="$(stat -f%z "$DMG")"

write_release() {  # $1 = 公開する SHA-256
  cat > "$W/srv/latest.json" <<JSON
{"tag_name": "v9.9.9", "draft": false, "prerelease": false, "body": "e2e",
 "html_url": "http://127.0.0.1:${PORT}/",
 "assets": [{"name": "$(basename "$DMG")", "size": ${SIZE},
             "browser_download_url": "http://127.0.0.1:${PORT}/$(basename "$DMG")",
             "digest": "sha256:$1"}]}
JSON
}

python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$W/srv" >/dev/null 2>&1 &
SRV_PID=$!
for _ in $(seq 1 50); do curl -s "http://127.0.0.1:${PORT}/" >/dev/null && break; sleep 0.1; done

run_update() {
  SSAI_UPDATE_SELFTEST=1 SSAI_UPDATE_API_URL="http://127.0.0.1:${PORT}/latest.json" "$BIN"
}

echo "==> ケース 1: 改ざんされた DMG は入れ替えない"
write_release "0000000000000000000000000000000000000000000000000000000000000000"
if run_update; then echo "FAIL: 改ざんを検出できませんでした"; exit 1; fi
sleep 2
[[ ! -e "$DEST/$MARKER" ]] || { echo "FAIL: 改ざん版に入れ替わりました"; exit 1; }
ls -A "$W/Applications" | grep -q '^\.ssai-update-' && { echo "FAIL: 作業フォルダが残っています"; exit 1; }
echo "OK: 改ざんを検出し、入れ替えませんでした"

echo "==> ケース 2: 正しい DMG で入れ替えと再起動"
write_release "$SHA"
run_update
for _ in $(seq 1 150); do [[ -e "$DEST/$MARKER" ]] && break; sleep 0.2; done
[[ -e "$DEST/$MARKER" ]] || { echo "FAIL: 新しい版に入れ替わりませんでした"; ls -la "$W/Applications"; exit 1; }
codesign --verify --deep "$DEST"
[[ ! -e "${DEST}.previous" ]] || { echo "FAIL: 旧版のバックアップが残っています"; exit 1; }
for _ in $(seq 1 50); do ls -A "$W/Applications" | grep -q '^\.ssai-update-' || break; sleep 0.2; done
ls -A "$W/Applications" | grep -q '^\.ssai-update-' && { echo "FAIL: 作業フォルダが残っています"; exit 1; }
RELAUNCHED=0
for _ in $(seq 1 75); do pgrep -f "$DEST/Contents/MacOS" >/dev/null && { RELAUNCHED=1; break; }; sleep 0.2; done
[[ "$RELAUNCHED" == 1 ]] || { echo "FAIL: 再起動されませんでした"; exit 1; }
echo "OK: 新しい版に入れ替わり、署名も有効で、再起動しました"
echo "E2E: 自動アップデートは正常です"
