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
    candidates = (
        ("icons/app.icns", "icons/app.svg")
        if sys.platform == "darwin"
        else ("icons/app.ico", "icons/app.svg")
    )
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


def _redirect_output_when_bundled() -> None:
    """macOS の .app（PyInstaller）起動時、標準出力をログファイルへ向ける。

    Finder から起動した .app ではコンソールが無く ``print`` の行き先が無い（``None`` の場合は
    例外になる）ため、``~/Library/Logs/SpeechSummarizerAI.log`` に追記する。

    Returns:
        None
    """
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return
    try:
        log_dir = Path.home() / "Library" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        f = open(  # noqa: SIM115 - プロセス終了まで開いたままにする
            log_dir / "SpeechSummarizerAI.log", "a", encoding="utf-8", buffering=1
        )
        sys.stdout = f
        sys.stderr = f
    except OSError:
        pass


def _install_macos_app_behaviour(app: QApplication, overlay: object) -> None:
    """macOS: Dock アイコンのクリックでウィンドウを再表示し、⌘Q でも後始末を行う。

    Args:
        app: ``QApplication``。
        overlay: ``RecordingOverlay``。

    Returns:
        None
    """
    if sys.platform != "darwin":
        return
    from PySide6.QtCore import Qt  # noqa: PLC0415

    def _on_state(state: Qt.ApplicationState) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            return
        if any(w.isVisible() and not w.isMinimized() for w in app.topLevelWidgets()):
            return
        overlay.bring_to_foreground_from_second_instance()  # type: ignore[attr-defined]

    app.applicationStateChanged.connect(_on_state)
    app.aboutToQuit.connect(overlay._quit_application)  # type: ignore[attr-defined]


def _run_bundle_selftest() -> int:
    """``SSAI_SELFTEST=1`` のとき、同梱ライブラリが読み込めるかだけ確認して終了する（CI 用）。

    Returns:
        int: すべて import できれば 0、失敗があれば 1。
    """
    import importlib  # noqa: PLC0415

    mods = ["numpy", "PySide6.QtWidgets", "webrtcvad", "ctranslate2", "faster_whisper"]
    if sys.platform == "darwin":
        mods += ["sounddevice", "mlx.core", "mlx_lm", "mlx_lm.models.qwen2", "transformers"]
    failed = 0
    for m in mods:
        try:
            importlib.import_module(m)
            print(f"[selftest] OK   {m}", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[selftest] FAIL {m}: {type(e).__name__}: {e}", flush=True)
    if sys.platform == "darwin" and not failed:
        try:
            import mlx.core as mx  # noqa: PLC0415

            v = mx.array([1.0, 2.0]) * 2
            mx.eval(v)
            print(f"[selftest] OK   mlx compute {v.tolist()}", flush=True)
            from transformers import AutoTokenizer  # noqa: F401, PLC0415

            print("[selftest] OK   transformers.AutoTokenizer", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[selftest] FAIL runtime: {type(e).__name__}: {e}", flush=True)
    return 1 if failed else 0


def main() -> int:
    """GUI アプリケーションを初期化し、メインループを実行する。

    Returns:
        int: ``QApplication.exec()`` の終了コード。
    """
    if os.environ.get("SSAI_SELFTEST") == "1":
        return _run_bundle_selftest()
    _redirect_output_when_bundled()
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
    _install_macos_app_behaviour(app, recording_overlay)
    recording_overlay.show_at_startup()
    return app.exec()
