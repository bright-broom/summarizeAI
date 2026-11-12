"""セッション・DB・モデル・LLM プローブ用パスの合成。"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from speech_summarizer_ai import settings as config


def new_session_id() -> str:
    """新しいセッション用の一意な ID 文字列を生成する。

    Returns:
        str: 現在時刻に基づく ``%Y%m%d_%H%M%S_%f`` 形式の ID。
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def sessions_root(project_root: Path) -> Path:
    """セッションルートディレクトリ（``sessions`` 等）のパスを返す。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        Path: ``project_root / SESSIONS_DIR_NAME``。
    """
    return project_root / config.SESSIONS_DIR_NAME


def session_directory(project_root: Path, session_id: str) -> Path:
    """指定セッション ID のディレクトリパスを返す。

    Args:
        project_root: プロジェクトルートディレクトリ。
        session_id: セッション ID。

    Returns:
        Path: セッション専用ディレクトリ。
    """
    return sessions_root(project_root) / session_id


def database_directory(project_root: Path) -> Path:
    """SQLite 用ディレクトリ（``database/``）のパスを返す。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        Path: ``project_root / DATABASE_DIR_NAME``。
    """
    return project_root / config.DATABASE_DIR_NAME


def database_path(project_root: Path) -> Path:
    """SQLite データベースファイルのフルパスを返す。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        Path: ``database_directory(project_root) / DATABASE_FILENAME``。
    """
    return database_directory(project_root) / config.DATABASE_FILENAME


def _repo_root() -> Path:
    """インストール済みパッケージの場所からリポジトリルート（``src`` の親）を推定して返す。

    非 Windows、または Windows でもユーザーデータルートを使わないフォールバックで
    ``project_root`` から参照される。

    Returns:
        Path: ``platform_utils/paths.py`` から見た ``parents[3]``（通常はクローン直下）。
    """
    return Path(__file__).resolve().parents[3]


def _windows_user_data_root() -> Path | None:
    """Windows 用のユーザー別データルート（書き込み可能領域）。

    優先: WinRT ``ApplicationData.current.local_folder``（MSIX 等でパッケージ ID がある場合）。
    非パッケージ EXE では WinRT が使えないため、
    ``%LOCALAPPDATA%/<vendor>/<app>`` にフォールバックする（従来インストーラ / PyInstaller 向け）。

    Returns:
        Path | None: Windows 以外、または ``LOCALAPPDATA`` が無い場合は ``None``。
    """
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.storage import ApplicationData  # noqa: PLC0415

        folder = ApplicationData.current.local_folder
        p = folder.path
        if p:
            return Path(str(p))
    except OSError:
        # 例: WinError パッケージ ID なし（未パッケージの Win32 プロセス）
        pass
    except ImportError:
        pass
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    return (
        Path(local) / config.WINDOWS_APPDATA_VENDOR_DIR / config.WINDOWS_APPDATA_APP_DIR
    )


def project_root() -> Path:
    """DB・モデル・セッションの基準ディレクトリ（ユーザーデータルート）を返す。

    Windows では WinRT のローカルフォルダ、または ``LOCALAPPDATA`` 下の
    ``WEEL/SpeechSummarizerAI``（``database/``・``models/``・``sessions/`` をこの下に配置）。
    それ以外の OS ではリポジトリルート（従来どおり）。

    Returns:
        Path: データルート。存在しない場合は親まで含めて作成する。
    """
    w = _windows_user_data_root()
    root = w if w is not None else _repo_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def models_directory(project_root: Path) -> Path:
    """``project_root / models`` を返す。

    Args:
        project_root: プロジェクトルート。

    Returns:
        Path: ``models`` ディレクトリ。
    """
    return project_root / config.MODELS_DIR_NAME


def stt_model_directory(project_root: Path, folder: str) -> Path:
    """``models/stt/<folder>`` を返す。

    Args:
        project_root: プロジェクトルート。
        folder: STT モデル用サブフォルダ名。

    Returns:
        Path: STT モデルディレクトリ。
    """
    return models_directory(project_root) / config.MODELS_STT_SUBDIR / folder


def foundry_llm_cache_directory(project_root: Path) -> Path:
    """Foundry の ``model_cache_dir``（``models/llm``）を返す。

    Args:
        project_root: プロジェクトルート。

    Returns:
        Path: LLM キャッシュディレクトリ。
    """
    return models_directory(project_root) / config.MODELS_LLM_SUBDIR


_LLM_PROBE_OK_FILENAME = ".speech_summarizer_llm_probe_ok"


def foundry_llm_probe_marker_path(project_root: Path) -> Path:
    """LLM ロード成功マーカー ``models/llm/.speech_summarizer_llm_probe_ok`` のパス。

    Args:
        project_root: プロジェクトルート。

    Returns:
        Path: マーカーファイル。
    """
    return foundry_llm_cache_directory(project_root) / _LLM_PROBE_OK_FILENAME


def _read_probe_marker_lines(project_root: Path) -> list[str]:
    p = foundry_llm_probe_marker_path(project_root)
    if not p.is_file():
        return []
    try:
        return [
            ln.strip()
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    except OSError:
        return []


def llm_probe_marker_matches(project_root: Path, model_alias: str) -> bool:
    """マーカー 1 行目が ``model_alias`` と一致するか。

    Args:
        project_root: プロジェクトルート。
        model_alias: 設定の LLM 別名。

    Returns:
        bool: 一致すれば True。
    """
    lines = _read_probe_marker_lines(project_root)
    return bool(lines) and lines[0] == model_alias.strip()


def read_llm_resolved_id(project_root: Path, model_alias: str) -> str | None:
    """マーカー 2 行目の解決済み完全 ID を返す。

    Args:
        project_root: プロジェクトルート。
        model_alias: 1 行目と突き合わせる別名。

    Returns:
        str | None: 有効なら完全 ID。無ければ ``None``。
    """
    lines = _read_probe_marker_lines(project_root)
    if len(lines) < 2 or lines[0] != model_alias.strip():
        return None
    return lines[1] or None


def write_llm_probe_marker(
    project_root: Path,
    model_alias: str,
    resolved_id: str | None = None,
) -> None:
    """ロード成功後にマーカーを書く（1 行目: 別名、2 行目: 任意で完全 ID）。

    Args:
        project_root: プロジェクトルート。
        model_alias: カタログ別名。
        resolved_id: SDK が解決した完全 ID。省略可。

    Returns:
        None
    """
    root = foundry_llm_cache_directory(project_root)
    root.mkdir(parents=True, exist_ok=True)
    body = model_alias.strip() + "\n"
    if resolved_id:
        body += resolved_id.strip() + "\n"
    foundry_llm_probe_marker_path(project_root).write_text(body, encoding="utf-8")


def clear_llm_probe_marker(project_root: Path) -> None:
    """マーカーを削除し次回起動で再検証させる。

    Args:
        project_root: プロジェクトルート。

    Returns:
        None
    """
    p = foundry_llm_probe_marker_path(project_root)
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass


def foundry_llm_model_weights_present(project_root: Path, model_alias: str) -> bool:
    """``models/llm`` 配下に、設定エイリアスに対応する ONNX 重みがあるか（起動時の存在チェック用）。

    Foundry が展開するパス（例: ``.../qwen2.5-0.5b-instruct-.../v2/model.onnx``）を
    ``model_alias`` の部分一致で判定する。音声認識の ``model.bin`` チェックに相当。

    Args:
        project_root: リポジトリルート。
        model_alias: ``config.FOUNDRY_LLM_MODEL_ALIAS`` などカタログのエイリアス。

    Returns:
        bool: エイリアスに一致するパスに ``model.onnx`` が存在し、かつ
        単体で十分大きいか、または ``model.onnx.data`` に重みがある場合 ``True``。
    """
    root = foundry_llm_cache_directory(project_root)
    if not root.is_dir():
        return False
    token = model_alias.strip()
    if not token:
        return False
    min_bytes = 512 * 1024
    for p in root.rglob("model.onnx"):
        try:
            if token not in p.as_posix():
                continue
            if not p.is_file():
                continue
            sz = p.stat().st_size
            data = p.with_name(p.name + ".data")
            data_sz = data.stat().st_size if data.is_file() else 0
            if sz >= min_bytes or data_sz >= min_bytes:
                return True
        except OSError:
            continue
    return False


def _llm_tree_contains_model_onnx(dir_path: Path) -> bool:
    """``dir_path`` 直下またはその配下に ``model.onnx`` があるか。"""
    try:
        if (dir_path / "model.onnx").is_file():
            return True
        for p in dir_path.rglob("model.onnx"):
            if p.is_file():
                return True
    except OSError:
        pass
    return False


def foundry_llm_model_onnx_present(project_root: Path, resolved_id: str) -> bool:
    """``models/llm`` 以下で resolved_id に対応するパスに ``model.onnx`` があるか。

    Args:
        project_root: リポジトリルート。
        resolved_id: マーカー 2 行目の解決済みモデル ID。

    Returns:
        bool: 名前が一致するディレクトリのいずれかに ``model.onnx`` があれば ``True``。
    """
    root = foundry_llm_cache_directory(project_root)
    if not root.is_dir():
        return False
    rid = resolved_id.strip()
    if not rid:
        return False
    prefix = rid.split(":", 1)[0] if ":" in rid else rid
    for candidate in root.rglob("*"):
        try:
            if not candidate.is_dir():
                continue
            if rid in candidate.name or prefix in candidate.name:
                if _llm_tree_contains_model_onnx(candidate):
                    return True
        except OSError:
            continue
    return False


def foundry_llm_resolved_weights_present(project_root: Path, resolved_id: str) -> bool:
    """``models/llm`` 配下に、マーカー 2 行目の解決済み ID に対応する ONNX があるか。

    カタログ ID に ``:`` が付く場合、フォルダ名側には含まれないことが多いため、
    ``:`` より前のプレフィックスでもパス一致を見る。

    Args:
        project_root: リポジトリルート。
        resolved_id: マーカーに保存した解決済みモデル ID。

    Returns:
        bool: 該当パスに実体のある ``model.onnx``（または十分な ``.data``）があれば ``True``。
    """
    rid = resolved_id.strip()
    if not rid:
        return False
    tokens = {rid}
    if ":" in rid:
        tokens.add(rid.split(":", 1)[0])
    root = foundry_llm_cache_directory(project_root)
    if not root.is_dir():
        return False
    min_bytes = 512 * 1024
    for p in root.rglob("model.onnx"):
        try:
            pos = p.as_posix()
            if not any(t in pos for t in tokens):
                continue
            if not p.is_file():
                continue
            sz = p.stat().st_size
            data = p.with_name(p.name + ".data")
            data_sz = data.stat().st_size if data.is_file() else 0
            if sz >= min_bytes or data_sz >= min_bytes:
                return True
        except OSError:
            continue
    return False


def new_session_audio_path(project_root: Path) -> tuple[Path, Path]:
    """新しいセッション用ディレクトリと、その中の音声ファイルパスを返す。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        tuple[Path, Path]: ``(セッションディレクトリ, 音声 WAV ファイルパス)`` のタプル。
    """
    sid = new_session_id()
    sdir = session_directory(project_root, sid)
    return sdir, sdir / config.SESSION_AUDIO_FILENAME
