"""自動アップデート（macOS の .app 向け）。

公開の配布用リポジトリ（``settings.UPDATE_RELEASES_REPO``）の GitHub Releases を確認し、
新しい版があれば DMG をダウンロードして .app を置き換え、再起動する。

- 確認は認証なしの GitHub API（``/releases/latest``）。ソースコードのリポジトリは非公開のままでよい。
- アプリ自身が HTTPS で取得したファイルには「ダウンロードしたファイル」の印（quarantine）が付かないため、
  更新後の起動で Gatekeeper の許可操作は求められない。
- GitHub が公開している SHA-256 ダイジェストがあれば照合し、一致しなければ置き換えない。
- 置き換えはアプリ終了後に小さなシェルスクリプトで行う（実行中の .app は上書きしない）。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from speech_summarizer_ai import __version__
from speech_summarizer_ai import settings as config

_API = "https://api.github.com/repos/{repo}/releases/latest"
_TIMEOUT = httpx.Timeout(15.0, read=60.0)


@dataclass(frozen=True)
class UpdateInfo:
    """配信中の最新版。"""

    version: str
    tag: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: str | None


def parse_version(text: str) -> tuple[int, ...]:
    """``v0.1.2`` / ``0.1.2`` / ``0.2.0-beta`` などを比較用のタプルにする（数字部分のみ）。"""
    nums = re.findall(r"\d+", text.split("-", 1)[0].split("+", 1)[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str | None = None) -> bool:
    """``candidate`` が ``current``（省略時は実行中の版）より新しいか。"""
    a, b = parse_version(candidate), parse_version(current if current is not None else __version__)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _arch_token() -> str:
    import platform

    return "arm64" if platform.machine() == "arm64" else "x86_64"


def pick_asset(assets: list[dict]) -> dict | None:
    """この Mac 向けの DMG を選ぶ（``…-arm64.dmg`` など）。"""
    arch = _arch_token()
    dmgs = [a for a in assets if str(a.get("name", "")).lower().endswith(".dmg")]
    for a in dmgs:
        if arch in str(a.get("name", "")):
            return a
    return dmgs[0] if len(dmgs) == 1 else None


def check_for_update(*, repo: str | None = None, client: httpx.Client | None = None) -> UpdateInfo | None:
    """最新版を確認し、今より新しければ ``UpdateInfo`` を返す。

    ネットワーク障害やリリース未作成のときは ``None``（アプリの動作は止めない）。

    Raises:
        なし（失敗は ``None`` とログで扱う）。
    """
    repo = repo or config.UPDATE_RELEASES_REPO
    if not repo:
        return None
    own = client is None
    c = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        r = c.get(
            _API.format(repo=repo),
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"SpeechSummarizerAI/{__version__}",
            },
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[update] 確認に失敗: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        if own:
            c.close()

    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag or not is_newer(tag):
        return None
    asset = pick_asset(list(data.get("assets") or []))
    if asset is None:
        print(f"[update] {tag} にこの Mac 用の DMG がありません", flush=True)
        return None
    digest = str(asset.get("digest") or "")
    return UpdateInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or ""),
        asset_name=str(asset.get("name")),
        asset_url=str(asset.get("browser_download_url")),
        asset_size=int(asset.get("size") or 0),
        sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
    )


def current_app_bundle() -> Path | None:
    """実行中の ``.app`` のパス。.app として動いていなければ ``None``（開発実行など）。"""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    p = Path(sys.executable).resolve()
    for parent in p.parents:
        if parent.suffix == ".app":
            return parent
    return None


def can_self_update() -> bool:
    """この環境でアプリ自身を置き換えられるか。"""
    app = current_app_bundle()
    return app is not None and os.access(app.parent, os.W_OK)


def download(info: UpdateInfo, dest_dir: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    """DMG をダウンロードし、サイズとダイジェストを検証して保存先を返す。

    Raises:
        RuntimeError: 検証に失敗した場合。
        httpx.HTTPError: 通信エラー。
    """
    dest = dest_dir / info.asset_name
    h = hashlib.sha256()
    done = 0
    with httpx.stream(
        "GET", info.asset_url, timeout=_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": f"SpeechSummarizerAI/{__version__}"},
    ) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or info.asset_size or 0)
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(256 * 1024):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if info.asset_size and done != info.asset_size:
        raise RuntimeError(f"ダウンロードが不完全です（{done}/{info.asset_size} バイト）")
    if info.sha256 and h.hexdigest() != info.sha256.lower():
        raise RuntimeError("ダウンロードしたファイルの検証（SHA-256）に失敗しました")
    return dest


def extract_app_from_dmg(dmg: Path, work_dir: Path) -> Path:
    """DMG をマウントして中の .app を ``work_dir`` にコピーし、そのパスを返す。"""
    mount = Path(tempfile.mkdtemp(prefix="ssai-mnt-"))
    subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mount), str(dmg)],
        check=True, capture_output=True,
    )
    try:
        apps = list(mount.glob("*.app"))
        if len(apps) != 1:
            raise RuntimeError(f"DMG 内に .app が見つかりません: {[p.name for p in mount.iterdir()]}")
        out = work_dir / apps[0].name
        subprocess.run(["ditto", str(apps[0]), str(out)], check=True)
    finally:
        subprocess.run(["hdiutil", "detach", "-quiet", str(mount)], check=False)
        shutil.rmtree(mount, ignore_errors=True)
    # 念のため quarantine を外す（アプリ自身のダウンロードでは通常付かない）
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(out)], check=False)
    verify = subprocess.run(["codesign", "--verify", "--deep", str(out)], capture_output=True, text=True)
    if verify.returncode != 0:
        raise RuntimeError(f"新しいアプリの署名を確認できません: {verify.stderr.strip()}")
    return out


_SWAP_SCRIPT = """#!/bin/bash
# Speech Summarizer AI の更新: 旧プロセスの終了を待ってから .app を入れ替えて再起動する。
PID="$1"; NEW="$2"; DEST="$3"; WORK="$4"
for _ in $(seq 1 300); do kill -0 "$PID" 2>/dev/null || break; sleep 0.2; done
BACKUP="${DEST}.previous"
rm -rf "$BACKUP"
if mv "$DEST" "$BACKUP" && mv "$NEW" "$DEST"; then
  rm -rf "$BACKUP"
else
  # 失敗したら元に戻す
  [ -d "$BACKUP" ] && [ ! -d "$DEST" ] && mv "$BACKUP" "$DEST"
fi
open "$DEST"
rm -rf "$WORK"
"""


def schedule_swap_and_relaunch(new_app: Path, work_dir: Path) -> None:
    """アプリ終了後に .app を入れ替えて再起動するスクリプトを起動する（呼び出し側はこの後すぐ終了する）。"""
    dest = current_app_bundle()
    if dest is None:
        raise RuntimeError("アプリ（.app）として実行されていないため置き換えできません")
    script = work_dir / "swap.sh"
    script.write_text(_SWAP_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    subprocess.Popen(
        ["/bin/bash", str(script), str(os.getpid()), str(new_app), str(dest), str(work_dir)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def prepare_update(info: UpdateInfo, progress: Callable[[int, int], None] | None = None) -> tuple[Path, Path]:
    """ダウンロードと展開まで行い、``(新しい .app, 作業ディレクトリ)`` を返す。"""
    dest = current_app_bundle()
    if dest is None:
        raise RuntimeError("アプリ（.app）として実行されていないため自動更新できません")
    # 同じボリューム上に置くと最後の入れ替え（mv）が一瞬で済む
    work = Path(tempfile.mkdtemp(prefix=".ssai-update-", dir=str(dest.parent)))
    try:
        dmg = download(info, work, progress)
        new_app = extract_app_from_dmg(dmg, work)
        dmg.unlink(missing_ok=True)
        return new_app, work
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
