"""GUI エントリ。``RecordingOverlay`` は生成後に import（PyAudioWPatch と Qt の初期化順序の問題を回避）。"""

from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from speech_summarizer_ai.data import meetings_repository as meetings_db
from speech_summarizer_ai.ui.theme import (
    DEFAULT_UI_DARK_UNSAVED,
    apply_application_popup_chrome,
)
from speech_summarizer_ai.ui.dialogs.startup_ai_models import (
    run_startup_models_setup_if_needed,
)
from speech_summarizer_ai.platform_utils import paths
from speech_summarizer_ai.platform_utils.single_instance import attach_single_instance


def _set_windows_app_user_model_id() -> None:
    """Windows で AppUserModelID を設定し、タスクバーとアイコンをアプリ単位にまとめる。

    ``QApplication`` より前に呼ぶ。Windows 以外では何もしない。

    Returns:
        None
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "WEEL.HPCommittee.Recorder.1.0"
        )
    except Exception:
        pass


def _project_root() -> Path:
    """``app.py`` の位置からリポジトリルート（``src`` の親）を返す。

    Returns:
        Path: プロジェクトルート。
    """
    return Path(__file__).resolve().parent.parent.parent


def _resolve_icon_path() -> Path | None:
    """``resources/icons/app.ico`` を優先し、無ければ ``app.svg``。frozen 時は ``_MEIPASS`` 配下。

    Returns:
        Path | None: 見つかったパス。無ければ ``None``。
    """
    candidates = ("icons/app.ico", "icons/app.svg")
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(getattr(sys, "_MEIPASS"))
        for name in candidates:
            p = base / "resources" / name
            if p.is_file():
                return p
        return None
    root = _project_root()
    for name in candidates:
        p = root / "resources" / name
        if p.is_file():
            return p
    return None


def _set_app_icon(app: QApplication) -> None:
    """QApplication にウィンドウアイコンを設定する。

    Args:
        app: ``QApplication`` インスタンス。

    Returns:
        None
    """
    path = _resolve_icon_path()
    if path is None:
        return
    app.setWindowIcon(QIcon(str(path)))


def _prepare_windows_pyside_dlls() -> None:
    """Windows で PySide6 / shiboken6 を ``add_dll_directory`` し、VC ランタイム等を読み込む。

    Returns:
        None
    """
    if sys.platform != "win32":
        return

    spec = importlib.util.find_spec("PySide6")
    if spec is None or not spec.origin:
        return
    pyside_dir = Path(spec.origin).resolve().parent
    shiboken_dir = pyside_dir.parent / "shiboken6"
    if shiboken_dir.is_dir():
        os.add_dll_directory(os.fspath(shiboken_dir))
    os.add_dll_directory(os.fspath(pyside_dir))
    os.environ["PATH"] = os.fspath(pyside_dir) + os.pathsep + os.environ.get("PATH", "")
    for name in (
        "msvcp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140_1.dll",
    ):
        dll = pyside_dir / name
        if dll.is_file():
            ctypes.WinDLL(os.fspath(dll))
    icuuc = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icuuc.dll"
    if icuuc.is_file():
        ctypes.WinDLL(os.fspath(icuuc))


def main() -> int:
    """GUI アプリケーションを初期化し、メインループを実行する。

    Returns:
        int: ``QApplication.exec()`` の終了コード。
    """
    _prepare_windows_pyside_dlls()
    _set_windows_app_user_model_id()

    app = QApplication(sys.argv)
    # 起動時モデル取得のみ表示中に最後のウィンドウが閉じても終了しない
    app.setQuitOnLastWindowClosed(False)
    _set_app_icon(app)

    _instance_relay = attach_single_instance(app)
    if _instance_relay is None:
        return 0

    _qs = QSettings("WEEL", "SpeechSummarizerAI")
    _ui_dark = bool(_qs.value("ui/dark", DEFAULT_UI_DARK_UNSAVED, type=bool))
    apply_application_popup_chrome(dark=_ui_dark)

    root = paths.project_root()
    if not run_startup_models_setup_if_needed(root):
        return 1

    meetings_db.ensure_database(root)

    from speech_summarizer_ai.ui.recording_overlay import RecordingOverlay

    recording_overlay = RecordingOverlay()
    _instance_relay.activate_requested.connect(
        recording_overlay.bring_to_foreground_from_second_instance
    )
    _instance_relay.toggle_recording_requested.connect(
        recording_overlay.toggle_recording
    )
    recording_overlay.show_at_startup()
    return app.exec()
