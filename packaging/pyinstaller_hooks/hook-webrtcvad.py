"""``webrtcvad`` / ``webrtcvad-wheels`` 用 PyInstaller hook。

``pyinstaller-hooks-contrib`` の ``hook-webrtcvad`` が、ビルド用 venv にパッケージが無い、
または hook 実装と環境の組み合わせで ``ImportErrorWhenRunningHook`` になることがある。
このリポジトリの ``speech_summarizer_ai.spec`` は ``hookspath`` で本ディレクトリを先に指定し、
こちらの定義を優先させる。

- ネイティブ拡張は ``collect_dynamic_libs`` で収集
- 配布メタデータは ``webrtcvad-wheels`` → ``webrtcvad`` の順で試す
"""

from __future__ import annotations

from PyInstaller.utils.hooks import collect_dynamic_libs, copy_metadata

binaries: list = []
try:
    binaries = collect_dynamic_libs("webrtcvad")
except Exception:
    pass

datas: list = []
for _dist in ("webrtcvad-wheels", "webrtcvad"):
    try:
        datas = copy_metadata(_dist)
        break
    except Exception:
        continue

hiddenimports = ["webrtcvad"]
