"""自動アップデート（版数比較・最新版の確認・ダウンロード検証・入れ替え）のテスト。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from speech_summarizer_ai import updater


@pytest.mark.parametrize(
    ("cand", "cur", "newer"),
    [("v0.1.2", "0.1.1", True), ("0.2.0", "0.1.9", True), ("v0.1.1", "0.1.1", False),
     ("v0.1.0", "0.1.1", False), ("v1.0", "0.9.9", True), ("v0.1.10", "0.1.9", True),
     ("v0.2.0-beta", "0.1.9", True)],
)
def test_is_newer(cand: str, cur: str, newer: bool) -> None:
    assert updater.is_newer(cand, cur) is newer


def _release(tag: str, dmg: bytes, **extra) -> dict:
    return {
        "tag_name": tag, "draft": False, "prerelease": False, "body": "改善点",
        "html_url": f"https://github.com/x/y/releases/tag/{tag}",
        "assets": [
            {"name": f"SpeechSummarizerAI-{tag[1:]}-x86_64.dmg", "browser_download_url": "https://dl/x86.dmg",
             "size": 1, "digest": None},
            {"name": f"SpeechSummarizerAI-{tag[1:]}-arm64.dmg", "browser_download_url": "https://dl/arm.dmg",
             "size": len(dmg), "digest": "sha256:" + hashlib.sha256(dmg).hexdigest()},
        ],
        **extra,
    }


def _client(payload: dict | None, status: int = 200) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/repos/owner/rel/releases/latest"
        return httpx.Response(status, content=json.dumps(payload or {}).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_finds_newer_arm64_asset(monkeypatch) -> None:
    monkeypatch.setattr(updater, "__version__", "0.1.1")
    monkeypatch.setattr(updater, "_arch_token", lambda: "arm64")
    info = updater.check_for_update(repo="owner/rel", client=_client(_release("v0.1.2", b"dmg")))
    assert info is not None
    assert info.version == "0.1.2" and info.asset_name.endswith("arm64.dmg")
    assert info.sha256 == hashlib.sha256(b"dmg").hexdigest()


@pytest.mark.parametrize(
    ("payload", "status"),
    [(_release("v0.1.1", b"x"), 200), (_release("v0.1.0", b"x"), 200),
     (_release("v0.2.0", b"x", draft=True), 200), (_release("v0.2.0", b"x", prerelease=True), 200),
     (None, 404), (None, 500)],
)
def test_check_returns_none_when_nothing_to_install(monkeypatch, payload, status) -> None:
    monkeypatch.setattr(updater, "__version__", "0.1.1")
    assert updater.check_for_update(repo="owner/rel", client=_client(payload, status)) is None


def _info(data: bytes, digest: bytes | None = None) -> updater.UpdateInfo:
    return updater.UpdateInfo(
        version="0.1.2", tag="v0.1.2", notes="", page_url="", asset_name="a.dmg",
        asset_url="https://dl/a.dmg", asset_size=len(data),
        sha256=hashlib.sha256(digest if digest is not None else data).hexdigest(),
    )


def _serve(monkeypatch, data: bytes) -> None:
    real_stream = httpx.stream

    def fake_stream(method, url, **kw):
        kw.pop("timeout", None)
        kw.pop("follow_redirects", None)
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data)))
        return client.stream(method, url, **kw)

    monkeypatch.setattr(updater.httpx, "stream", fake_stream)
    assert real_stream is not fake_stream


def test_download_verifies_digest(monkeypatch, tmp_path: Path) -> None:
    data = b"0123456789" * 1000
    _serve(monkeypatch, data)
    seen: list[tuple[int, int]] = []
    out = updater.download(_info(data), tmp_path, lambda d, t: seen.append((d, t)))
    assert out.read_bytes() == data and seen[-1] == (len(data), len(data))


def test_download_rejects_tampered_file(monkeypatch, tmp_path: Path) -> None:
    data = b"tampered" * 100
    _serve(monkeypatch, data)
    with pytest.raises(RuntimeError, match="SHA-256"):
        updater.download(_info(data, digest=b"original"), tmp_path)


def test_swap_script_replaces_app_after_process_exits(tmp_path: Path) -> None:
    dest = tmp_path / "Speech Summarizer AI.app"
    (dest / "Contents").mkdir(parents=True)
    (dest / "Contents" / "v").write_text("old")
    work = tmp_path / ".ssai-update-1"
    new = work / "Speech Summarizer AI.app"
    (new / "Contents").mkdir(parents=True)
    (new / "Contents" / "v").write_text("new")
    script = tmp_path / "swap.sh"
    script.write_text(updater._SWAP_SCRIPT)
    # 実際のアプリと同じく「親が回収済み」のプロセスにするため、孫プロセスの PID を使う
    pid = int(subprocess.run(["/bin/bash", "-c", "sleep 0.5 >/dev/null 2>&1 & echo $!"],
                             capture_output=True, text=True, check=True).stdout.strip())
    # `open` は macOS のコマンド。テストでは何もしない代用品を PATH に置く
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "open").write_text("#!/bin/bash\necho opened \"$@\" > \"$(dirname \"$0\")/opened\"\n")
    (bindir / "open").chmod(0o755)
    env = {"PATH": f"{bindir}:/usr/bin:/bin"}
    t0 = time.time()
    subprocess.run(["/bin/bash", str(script), str(pid), str(new), str(dest), str(work)],
                   check=True, env=env, timeout=30)
    assert time.time() - t0 >= 0.4  # 旧プロセスの終了を待ってから入れ替えた
    assert (dest / "Contents" / "v").read_text() == "new"
    assert not work.exists() and not Path(f"{dest}.previous").exists()
    assert "opened" in (bindir / "opened").read_text()
