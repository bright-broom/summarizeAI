"""HUD・RecordingController・一覧を束ねる Facade。既存の ``app.py`` / 一覧からの API を維持する。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from speech_summarizer_ai.controllers.recording_controller import RecordingController
from speech_summarizer_ai.platform_utils import paths
from speech_summarizer_ai.ui.windows.meeting_summary_list import (
    MeetingSummaryListWindow,
)
from speech_summarizer_ai.ui.windows.recording_hud import RecordingHudWindow


class RecordingOverlay(QObject):
    """録音 HUD と Controller の Facade。"""

    recording_meeting_created = Signal(int)
    live_transcript_line_saved = Signal(int, str, str)
    meeting_summarization_started = Signal(int)
    meeting_summarization_finished = Signal(int)

    def __init__(self) -> None:
        """録音 HUD と ``RecordingController`` を初期化し、シグナルを接続する。

        Returns:
            None: 保存ディレクトリ・HUD・コントローラを用意し、配線メソッドを呼ぶ。
        """
        super().__init__(None)

        self._save_dir: Path = paths.project_root()
        self._app_quit_started = False
        self._meeting_summary_list_window: MeetingSummaryListWindow | None = None

        self._hud = RecordingHudWindow()
        self._controller = RecordingController(project_root=self._save_dir, parent=self)

        self._wire_hud_signals()
        self._wire_controller_signals()

    def _wire_hud_signals(self) -> None:
        """HUD のユーザー操作シグナルをこの Facade のスロットへ接続する。

        Returns:
            None: 録音トグル・終了・一覧表示要求を配線する。
        """
        self._hud.record_button_clicked.connect(self.toggle_recording)
        self._hud.close_button_clicked.connect(self._quit_application)
        self._hud.summary_list_requested.connect(self._open_meeting_summary_list_window)
        self._hud.close_requested_by_user.connect(self._quit_application)

    def _wire_controller_signals(self) -> None:
        """コントローラの通知を HUD／一覧の更新と外部公開シグナルへ橋渡しする。

        Returns:
            None: ドメインシグナルの中継とメッセージボックス要求を接続する。
        """
        self._controller.recording_meeting_created.connect(
            self.recording_meeting_created
        )
        self._controller.live_transcript_line_saved.connect(
            self.live_transcript_line_saved
        )
        self._controller.meeting_summarization_started.connect(
            self.meeting_summarization_started
        )
        self._controller.meeting_summarization_finished.connect(
            self.meeting_summarization_finished
        )

        self._controller.recording_state_changed.connect(
            self._on_controller_recording_state_changed
        )
        self._controller.post_stop_pipeline_changed.connect(
            self._on_controller_post_stop_changed
        )
        self._controller.idle_title_should_update.connect(
            self._on_controller_idle_title_update
        )
        self._controller.message_info_requested.connect(self._show_message_info)
        self._controller.message_warning_requested.connect(self._show_message_warning)

    def set_live_stt_folder_name(self, folder: str) -> None:
        """リアルタイム STT が参照する ``models/stt/<folder>`` のフォルダ名を設定する。

        Args:
            folder (str): モデルサブディレクトリ名（一覧のコンボから渡される）。

        Returns:
            None: ``RecordingController.set_live_stt_folder_name`` に委譲する。
        """
        self._controller.set_live_stt_folder_name(folder)

    def set_ui_dark(self, dark: bool) -> None:
        """一覧と同じ論理値で HUD のダーク／ライトを同期する。

        Args:
            dark (bool): ダーク UI なら ``True``（設定 ``ui/dark`` と一致させる）。

        Returns:
            None: ``RecordingHudWindow.set_ui_dark`` に委譲する。
        """
        self._hud.set_ui_dark(dark)

    def toggle_recording(self) -> None:
        """録音の開始または停止をコントローラへ委譲する。

        Returns:
            None: ``RecordingController.toggle_recording`` を呼ぶ。
        """
        self._controller.toggle_recording()

    def _on_controller_recording_state_changed(self, recording: bool) -> None:
        """コントローラの録音 ON/OFF を HUD と一覧の録音ボタン表示に反映する。

        Args:
            recording (bool): 録音中なら ``True``。

        Returns:
            None: 停止直後は待機タイトルを STT 待ち扱いにし、HUD 状態とボタンを同期する。
        """
        if not recording:
            self._hud.apply_idle_window_title(True)
        self._hud.show_recording_active(recording)
        self._sync_record_button()

    def _on_controller_post_stop_changed(self, _active: bool) -> None:
        """停止後パイプライン（STT・要約）の進行に合わせ録音ボタンの操作可否を更新する。

        Args:
            _active (bool): パイプラインが進行中か（詳細はコントローラ側。現状は同期のみ）。

        Returns:
            None: :meth:`_sync_record_button` を呼ぶ。
        """
        self._sync_record_button()

    def _on_controller_idle_title_update(self, stt_pending: bool) -> None:
        """待機中ウィンドウタイトル（音声認識処理中など）の更新を HUD とボタンへ反映する。

        Args:
            stt_pending (bool): バックグラウンド STT が進行中なら ``True``。

        Returns:
            None: ``apply_idle_window_title`` と :meth:`_sync_record_button` を行う。
        """
        self._hud.apply_idle_window_title(stt_pending)
        self._sync_record_button()

    def _sync_record_button(self) -> None:
        """HUD と一覧ヘッダの録音ボタンを、録音中フラグと操作可否に合わせる。

        Returns:
            None: 一覧ウィンドウが無い、または ``sync_record_button`` が無い場合は HUD のみ更新する。
        """
        interactive = self._controller.recording_controls_interactive()
        self._hud.set_record_interactive(interactive)
        w = self._meeting_summary_list_window
        if w is None:
            return
        sync = getattr(w, "sync_record_button", None)
        if callable(sync):
            sync(
                recording=self._controller.is_recording(),
                interaction_enabled=interactive,
            )

    def _show_message_info(self, title: str, body: str) -> None:
        """コントローラからの情報ダイアログ表示要求を処理する。

        Args:
            title (str): ダイアログタイトル。
            body (str): 本文。

        Returns:
            None: ``QMessageBox.information`` を表示する。
        """
        QMessageBox.information(self._message_parent() or self._hud, title, body)

    def _show_message_warning(self, title: str, body: str) -> None:
        """コントローラからの警告ダイアログ表示要求を処理する。

        Args:
            title (str): ダイアログタイトル。
            body (str): 本文。

        Returns:
            None: ``QMessageBox.warning`` を表示する。
        """
        QMessageBox.warning(self._message_parent() or self._hud, title, body)

    def _message_parent(self) -> QWidget | None:
        """``QMessageBox`` の親にする可視ウィジェットを返す。

        Returns:
            QWidget | None: HUD が可視なら HUD、次に一覧ウィンドウが可視ならそれ。
                どちらも無ければ ``None``。
        """
        if self._hud.isVisible():
            return self._hud
        if (
            self._meeting_summary_list_window is not None
            and self._meeting_summary_list_window.isVisible()
        ):
            return self._meeting_summary_list_window
        return None

    def _open_meeting_summary_list_window(self) -> None:
        """音声要約一覧ウィンドウを開くか、既存なら前面・アクティブにする。

        未生成なら ``MeetingSummaryListWindow`` を作成し、破棄シグナルとサイズ・位置を設定する。
        既存の場合は最小化なら復元し、非表示なら ``show`` し、
        ``raise_`` / ``activateWindow`` でフォーカスを移す。

        Returns:
            None: 表示後に :meth:`_sync_record_button` を呼ぶ経路がある。
        """
        w = self._meeting_summary_list_window
        if w is not None:
            if w.isMinimized():
                restore = getattr(
                    w, "restore_from_minimized_preserving_window_state", None
                )
                if callable(restore):
                    restore()
                else:
                    w.showNormal()
                    w.raise_()
                    w.activateWindow()
                self._sync_record_button()
                return
            if not w.isVisible():
                w.show()
            w.raise_()
            w.activateWindow()
            self._sync_record_button()
            return

        self._meeting_summary_list_window = MeetingSummaryListWindow(
            recording_host=self
        )
        self._meeting_summary_list_window.destroyed.connect(
            self._on_meeting_summary_list_destroyed
        )
        self._meeting_summary_list_window.resize(600, 560)
        self._sync_record_button()
        self._meeting_summary_list_window.show()
        self._meeting_summary_list_window.center_on_primary_screen()
        self._meeting_summary_list_window.raise_()
        self._meeting_summary_list_window.activateWindow()

    def _on_meeting_summary_list_destroyed(self) -> None:
        """一覧ウィンドウ破棄時に内部参照を ``None`` に戻す。

        Returns:
            None: ``_meeting_summary_list_window`` をクリアする。
        """
        self._meeting_summary_list_window = None

    def _begin_recording_after_cold_start(self) -> None:
        """コールドスタート直後（他インスタンスなし）、条件が揃えば録音を開始する。

        既に録音中・ボタン非活性・STT ワーカー生存時は何もしない。

        Returns:
            None: 条件を満たせば ``RecordingController.toggle_recording`` を 1 回呼ぶ。
        """
        if self._controller.is_recording():
            return
        if not self._controller.recording_controls_interactive():
            return
        if self._controller.is_stt_worker_alive():
            return
        self._controller.toggle_recording()

    def show_at_startup(self) -> None:
        """起動時に待機状態の HUD を表示し、音声要約一覧を開く。

        一覧は :meth:`_open_meeting_summary_list_window` で用意したあと、HUD を再び前面・
        アクティブにする。次イベントループで :meth:`_begin_recording_after_cold_start` を
        予約し、初回コールドスタート時に録音開始しうる。

        Returns:
            None: ``QTimer.singleShot`` でコールドスタート録音をスケジュールする。
        """
        self._hud.show_recording_active(False)
        self._hud.show()
        self._open_meeting_summary_list_window()
        self._hud.raise_()
        self._hud.activateWindow()
        QTimer.singleShot(0, self._begin_recording_after_cold_start)

    def bring_to_foreground_from_second_instance(self) -> None:
        """二重起動検知時に、既存の一覧と HUD を前面・アクティブにする。

        一覧が最小化・非表示の場合は復元・表示し、最後に HUD を表示してフォーカスする。

        Returns:
            None: 一覧が存在すれば :meth:`_sync_record_button` を呼ぶことがある。
        """
        w = self._meeting_summary_list_window
        if w is not None:
            if w.isMinimized():
                restore = getattr(
                    w, "restore_from_minimized_preserving_window_state", None
                )
                if callable(restore):
                    restore()
                else:
                    w.showNormal()
                    w.raise_()
                    w.activateWindow()
                self._sync_record_button()
            else:
                if not w.isVisible():
                    w.show()
                w.raise_()
                w.activateWindow()
                self._sync_record_button()
        self._hud.show()
        self._hud.raise_()
        self._hud.activateWindow()

    def _quit_application(self) -> None:
        """終了処理を開始する（コントローラのシャットダウン後 ``QApplication.quit``）。

        二重呼び出しは無視する。HUD の閉じる許可を立ててから終了する。

        Returns:
            None: 初回のみ ``shutdown_for_quit`` と ``QApplication.quit`` を行う。
        """
        if self._app_quit_started:
            return
        self._app_quit_started = True
        self._controller.shutdown_for_quit()
        self._sync_record_button()
        self._hud.allow_close()
        QApplication.quit()
