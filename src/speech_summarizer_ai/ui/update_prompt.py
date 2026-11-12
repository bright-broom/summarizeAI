"""自動アップデートの UI（確認ダイアログ・進捗・再起動）。ロジックは :mod:`speech_summarizer_ai.updater`。"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QApplication, QMenuBar, QMessageBox, QProgressDialog, QWidget

from speech_summarizer_ai import __version__, updater
from speech_summarizer_ai import settings as config

_SKIP_KEY = "update/skipped_version"


class UpdateController(QObject):
    """起動時と定期的に更新を確認し、ユーザーの同意のうえで更新・再起動する。"""

    _checked = Signal(object, bool)          # (UpdateInfo | None, manual)
    _progress = Signal(int, int)
    _prepared = Signal(object, object, str)  # (new_app, work_dir, error)

    def __init__(self, overlay: QObject) -> None:
        super().__init__(overlay)
        self._overlay = overlay
        self._settings = QSettings("WEEL", "SpeechSummarizerAI")
        self._busy = False
        self._pending: updater.UpdateInfo | None = None
        self._dialog: QProgressDialog | None = None
        self._cancel = threading.Event()
        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._prepared.connect(self._on_prepared)
        self._timer = QTimer(self)
        self._timer.setInterval(int(config.UPDATE_CHECK_INTERVAL_HOURS * 3600 * 1000))
        self._timer.timeout.connect(lambda: self.check(manual=False))
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(60_000)
        self._idle_timer.timeout.connect(self._retry_when_idle)
        self._menubar: QMenuBar | None = None

    # ------------------------------------------------------------------ 起動
    def start(self) -> None:
        if not config.UPDATE_RELEASES_REPO:
            return
        self._install_menu()
        QTimer.singleShot(config.UPDATE_FIRST_CHECK_DELAY_SECONDS * 1000, lambda: self.check(manual=False))
        self._timer.start()

    def _install_menu(self) -> None:
        """macOS のメニューバーに「アップデートを確認…」を追加する。"""
        mb = QMenuBar(None)  # 親なし = macOS のグローバルメニューバー
        menu = mb.addMenu("ヘルプ")
        act = QAction("アップデートを確認…", mb)
        act.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        act.triggered.connect(lambda: self.check(manual=True))
        menu.addAction(act)
        ver = QAction(f"バージョン {__version__}", mb)
        ver.setEnabled(False)
        menu.addAction(ver)
        self._menubar = mb

    # ------------------------------------------------------------------ 確認
    def check(self, *, manual: bool) -> None:
        if self._busy:
            return
        self._busy = True

        def run() -> None:
            info = updater.check_for_update()
            self._checked.emit(info, manual)

        threading.Thread(target=run, name="UpdateCheck", daemon=True).start()

    def _parent(self) -> QWidget | None:
        fn = getattr(self._overlay, "_message_parent", None)
        return fn() if callable(fn) else None

    def _on_checked(self, info: updater.UpdateInfo | None, manual: bool) -> None:
        self._busy = False
        if info is None:
            if manual:
                QMessageBox.information(
                    self._parent(), "アップデート",
                    f"最新のバージョンです（{__version__}）。",
                )
            return
        if not manual and self._settings.value(_SKIP_KEY, "") == info.tag:
            return
        self._offer(info)

    def _offer(self, info: updater.UpdateInfo) -> None:
        mb = QMessageBox(self._parent())
        mb.setIcon(QMessageBox.Icon.Information)
        mb.setWindowTitle("アップデート")
        mb.setText(f"新しいバージョン {info.version} があります（現在 {__version__}）。")
        notes = info.notes.strip()
        detail = (notes[:500] + "…") if len(notes) > 500 else notes
        can_install = updater.can_self_update()
        mb.setInformativeText(
            ("今すぐ更新すると、ダウンロード後にアプリが再起動します。\n\n" if can_install
             else "ダウンロードページを開きます。\n\n") + detail
        )
        b_now = mb.addButton("今すぐ更新" if can_install else "ダウンロードページを開く",
                             QMessageBox.ButtonRole.AcceptRole)
        mb.addButton("後で", QMessageBox.ButtonRole.RejectRole)
        b_skip = mb.addButton("この版をスキップ", QMessageBox.ButtonRole.DestructiveRole)
        mb.setDefaultButton(b_now)
        mb.exec()
        clicked = mb.clickedButton()
        if clicked is b_skip:
            self._settings.setValue(_SKIP_KEY, info.tag)
            return
        if clicked is not b_now:
            return
        if not can_install:
            QDesktopServices.openUrl(QUrl(info.page_url))
            return
        self._pending = info
        self._retry_when_idle(first=True)

    # ------------------------------------------------------------------ 更新
    def _app_is_busy(self) -> bool:
        ctl = getattr(self._overlay, "_controller", None)
        if ctl is None:
            return False
        return bool(ctl.is_recording() or ctl.is_post_stop_pipeline_active())

    def _retry_when_idle(self, first: bool = False) -> None:
        if self._pending is None:
            self._idle_timer.stop()
            return
        if self._app_is_busy():
            if first:
                QMessageBox.information(
                    self._parent(), "アップデート",
                    "録音または要約の処理中です。終わり次第、自動で更新を始めます。",
                )
            self._idle_timer.start()
            return
        self._idle_timer.stop()
        info, self._pending = self._pending, None
        self._begin_download(info)

    def _begin_download(self, info: updater.UpdateInfo) -> None:
        dlg = QProgressDialog(f"バージョン {info.version} をダウンロードしています…", "キャンセル", 0, 100, self._parent())
        dlg.setWindowTitle("アップデート")
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        self._cancel.clear()
        dlg.canceled.connect(self._cancel.set)
        dlg.show()
        self._dialog = dlg

        def progress(done: int, total: int) -> None:
            if self._cancel.is_set():
                raise RuntimeError("キャンセルしました")
            self._progress.emit(done, total)

        def run() -> None:
            try:
                new_app, work = updater.prepare_update(info, progress)
                self._prepared.emit(new_app, work, "")
            except Exception as e:  # noqa: BLE001
                self._prepared.emit(None, None, str(e))

        threading.Thread(target=run, name="UpdateDownload", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if self._dialog is None:
            return
        if total > 0:
            self._dialog.setMaximum(100)
            self._dialog.setValue(int(done * 100 / total))
            self._dialog.setLabelText(
                f"ダウンロードしています… {done / 1_048_576:.0f} / {total / 1_048_576:.0f} MB"
            )
        if done >= total > 0:
            self._dialog.setLabelText("新しいバージョンを準備しています…")

    def _on_prepared(self, new_app: Path | None, work: Path | None, error: str) -> None:
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
        if error or new_app is None or work is None:
            if not self._cancel.is_set():
                QMessageBox.warning(self._parent(), "アップデート", f"更新できませんでした。\n{error}")
            return
        if self._app_is_busy():
            # ダウンロード中に録音が始まった場合は、今回は入れ替えない
            shutil.rmtree(work, ignore_errors=True)
            QMessageBox.information(self._parent(), "アップデート",
                                    "録音中のため更新を中止しました。後でもう一度お試しください。")
            return
        try:
            updater.schedule_swap_and_relaunch(new_app, work)
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(work, ignore_errors=True)
            QMessageBox.warning(self._parent(), "アップデート", f"更新できませんでした。\n{e}")
            return
        quit_fn = getattr(self._overlay, "_quit_application", None)
        if callable(quit_fn):
            quit_fn()
        else:
            QApplication.quit()
