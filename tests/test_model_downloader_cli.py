"""STT モデル取得コマンド（python -m speech_summarizer_ai.stt.model_downloader）のテスト。"""

from __future__ import annotations

import sys
from pathlib import Path

from speech_summarizer_ai.stt import model_downloader as md


def test_cli_without_project_root_uses_default_root(monkeypatch, tmp_path: Path, capsys) -> None:
    """--project-root 省略時に既定のデータフォルダを使う（以前は UnboundLocalError で落ちた）。"""
    monkeypatch.setenv("SSAI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(md, "download_stt_model", lambda root, name: calls.append((root, name)) or root / name)
    monkeypatch.setattr(sys, "argv", ["model_downloader", "--model", "base"])
    md.main()
    assert calls == [(tmp_path, "base")]


def test_cli_all(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(md, "download_all_stt_models", lambda root: {"base": root / "base"})
    monkeypatch.setattr(sys, "argv", ["model_downloader", "--all", "--project-root", str(tmp_path)])
    md.main()
    assert "base:" in capsys.readouterr().out
