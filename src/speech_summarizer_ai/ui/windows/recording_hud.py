"""録音 HUD の View（無枠・最前面）。描画と入力シグナルのみ。録音ロジックは Controller 側。"""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QPoint, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from speech_summarizer_ai.ui.icons import action_icons
from speech_summarizer_ai.ui.theme import (
    DEFAULT_UI_DARK_UNSAVED,
    apply_application_popup_chrome,
    recording_hud_close_icon_disabled_muted,
    recording_hud_rec_led_dim_qss,
    recording_hud_rec_led_on_qss,
    recording_hud_theme,
    recording_hud_time_label_qss,
)
from speech_summarizer_ai.ui.widgets.record_control_button import RecordControlButton


class RecordingHudWindow(QWidget):
    """録音 HUD ウィジェット。"""

    record_button_clicked = Signal()
    close_button_clicked = Signal()
    summary_list_requested = Signal()
    close_requested_by_user = Signal()

    _WINDOW_TITLE = "Speech Summarizer AI"
    _WINDOW_TITLE_RECORDING = "Speech Summarizer AI — 録音中"
    _WINDOW_TITLE_STT_PENDING = "Speech Summarizer AI — 音声認識処理中"

    _EDGE_MARGIN = 24
    _RADIUS = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        """録音 HUD ウィンドウを初期化する。

        Args:
            parent (QWidget | None): 親ウィジェット。通常は ``None``。

        Returns:
            None: 無枠・最前面・タイマー・レイアウト・テーマを設定する。
        """
        super().__init__(parent)
        self.setWindowTitle(self._WINDOW_TITLE)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self._apply_window_icon_for_taskbar()

        self._drag_offset: QPoint | None = None
        self._accept_close = False

        self._settings = QSettings("WEEL", "SpeechSummarizerAI")
        self._ui_dark = bool(
            self._settings.value("ui/dark", DEFAULT_UI_DARK_UNSAVED, type=bool)
        )

        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_time_label)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_rec_led_blink)
        self._rec_led_blink_on = True

        self._rec_led = QLabel()
        self._rec_led.setFixedSize(12, 12)
        self._rec_led.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        self._time_label = QLabel("00:00")
        mono = QFont("Consolas", 15)
        if not mono.exactMatch():
            mono = QFont("Courier New", 15)
        self._time_label.setFont(mono)
        self._time_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        self._close_btn = QPushButton()
        self._close_btn.setText("")
        self._close_btn.setIconSize(QSize(16, 16))
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("アプリを終了する")
        self._close_btn.clicked.connect(self.close_button_clicked)

        self._record_btn = RecordControlButton(self)
        self._record_btn.setToolTip("録音を開始 / 停止")
        self._record_btn.clicked.connect(self.record_button_clicked)

        row = QHBoxLayout(self)
        # 左右対称。ストレッチは入れず、ウィンドウ幅は内容に合わせてコンパクトにする
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(6)
        row.addWidget(self._rec_led, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._time_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(10)
        row.addWidget(self._record_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._close_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._recording_ui_active = False
        self._stt_pending = False
        self._apply_hud_theme()

    def is_ui_dark(self) -> bool:
        """一覧ウィンドウと同期しているダークモード設定を返す。

        Returns:
            bool: ダーク UI なら ``True``。
        """
        return self._ui_dark

    def set_ui_dark(self, dark: bool) -> None:
        """一覧ウィンドウのテーマ切替と同期する（設定 ``ui/dark`` と同じ論理値）。

        Args:
            dark (bool): ダーク UI に合わせるなら ``True``。

        Returns:
            None: 値が変わったときだけ HUD テーマを再適用する。
        """
        if self._ui_dark == dark:
            return
        self._ui_dark = dark
        self._apply_hud_theme()

    def _apply_hud_theme(self) -> None:
        """現在の ``_ui_dark`` に合わせ、パネル・ラベル・ボタン・LED 待機色を更新する。

        Returns:
            None: テーマを再生成し、ポップアップ用クロームも同期する。
        """
        self._hud_theme = recording_hud_theme(dark=self._ui_dark)
        ht = self._hud_theme
        self._time_label.setStyleSheet(
            recording_hud_time_label_qss(ht.time_label_color)
        )
        self._close_btn.setStyleSheet(ht.close_button_qss)
        c_en = ht.close_icon_color
        c_dis = recording_hud_close_icon_disabled_muted(ht)
        self._close_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_window_close(self, color=c_en),
                action_icons.icon_window_close(self, color=c_dis),
                24,
            )
        )
        self._record_btn.set_hud_dark(self._ui_dark)
        if not self._recording_ui_active:
            self._set_rec_led_idle()
        self.update()
        apply_application_popup_chrome(dark=self._ui_dark)

    def set_record_interactive(self, interactive: bool) -> None:
        """録音ボタンの有効／無効とカーソルを切り替える。

        Args:
            interactive (bool): クリック可能にするなら ``True``（停止後パイプライン待ちなどでは ``False``）。

        Returns:
            None: ``RecordControlButton`` の ``setEnabled`` とカーソルを更新する。
        """
        self._record_btn.setEnabled(interactive)
        self._record_btn.setCursor(
            Qt.CursorShape.ArrowCursor
            if not interactive
            else Qt.CursorShape.PointingHandCursor
        )

    def show_recording_active(self, active: bool) -> None:
        """録音中と待機で UI 状態（タイトル・ボタン・経過タイマー・LED）を切り替える。

        Args:
            active (bool): 録音中なら ``True``。

        Returns:
            None: タイマーの開始／停止と LED 点滅、ウィンドウを前面へ出す。
        """
        self._recording_ui_active = active
        if active:
            self.setWindowTitle(self._WINDOW_TITLE_RECORDING)
            self._record_btn.set_recording(True)
            self._record_btn.setToolTip("録音を停止する")
            self._elapsed.start()
            self._update_time_label()
            self._timer.start()
            self._rec_led_blink_on = True
            self._set_rec_led_on()
            self._blink_timer.start()
        else:
            self._record_btn.set_recording(False)
            self._record_btn.setToolTip("録音を開始する")
            self._timer.stop()
            self._time_label.setText("00:00")
            self._blink_timer.stop()
            self._set_rec_led_idle()
            self.apply_idle_window_title(self._stt_pending)
        self.raise_()

    def apply_idle_window_title(self, stt_pending: bool) -> None:
        """録音していないときのウィンドウタイトルを更新する。

        Args:
            stt_pending (bool): バックグラウンド音声認識が進行中なら ``True``。

        Returns:
            None: 録音 UI がアクティブならタイトルは変えず、それ以外は STT 待ち／通常を反映しテーマを再適用する。
        """
        self._stt_pending = stt_pending
        if self._recording_ui_active:
            return
        if stt_pending:
            self.setWindowTitle(self._WINDOW_TITLE_STT_PENDING)
        else:
            self.setWindowTitle(self._WINDOW_TITLE)
        self._apply_hud_theme()

    def allow_close(self) -> None:
        """次の ``closeEvent`` でウィンドウを実際に閉じることを許可する。

        Returns:
            None: 内部フラグ ``_accept_close`` を立てる。
        """
        self._accept_close = True

    def closeEvent(self, event: QCloseEvent) -> None:
        """閉じる操作を処理する（許可済みなら閉じる、未許可ならシグナルで Facade へ）。

        Args:
            event (QCloseEvent): クローズイベント。

        Returns:
            None: 許可時は ``accept``、未許可時は ``ignore`` して ``close_requested_by_user`` を emit する。
        """
        if self._accept_close:
            event.accept()
            return
        event.ignore()
        self.close_requested_by_user.emit()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """角丸の半透明パネル塗りと縁を描画する。

        Args:
            event (QPaintEvent): Qt が渡すペイントイベント。

        Returns:
            None: ``QPainter`` で ``_hud_theme`` に基づき角丸矩形を描く。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ht = self._hud_theme
        bw = ht.panel_border_width
        inset = max(1, int(round(bw / 2)))
        r = self.rect().adjusted(inset, inset, -inset, -inset)
        rr = max(1.0, self._RADIUS - inset)
        pen = QPen(ht.panel_border)
        pen.setWidthF(bw)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(ht.panel_fill)
        painter.drawRoundedRect(r, rr, rr)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左クリックでウィンドウドラッグ用のオフセットを記録する。

        Args:
            event (QMouseEvent): マウスイベント。

        Returns:
            None: 左ボタン時は ``accept`` する。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """左ボタン押下中のドラッグでウィンドウ位置を更新する。

        Args:
            event (QMouseEvent): マウスイベント。

        Returns:
            None: ドラッグ中は ``move`` して ``accept`` する。
        """
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """左ボタン解放でドラッグオフセットをクリアする。

        Args:
            event (QMouseEvent): マウスイベント。

        Returns:
            None: 左ボタン時は ``accept`` する。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """左ダブルクリックで商談一覧を開くよう ``summary_list_requested`` を emit する。

        Args:
            event (QMouseEvent): マウスイベント。

        Returns:
            None: 左ボタン以外は基底処理へ委譲する。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.summary_list_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        """表示時にプライマリスクリーン右下へウィンドウを配置する。

        Args:
            event (QShowEvent): Qt が渡す表示イベント。

        Returns:
            None: 基底の ``showEvent`` の後に :meth:`move_to_bottom_right` を呼ぶ。
        """
        super().showEvent(event)
        self.move_to_bottom_right()

    def move_to_bottom_right(self) -> None:
        """プライマリスクリーンの利用可能領域の右下（``_EDGE_MARGIN`` 付き）へ移動する。

        Returns:
            None: スクリーンが取得できない場合は何もしない。
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.adjustSize()
        x = geo.x() + geo.width() - self.width() - self._EDGE_MARGIN
        y = geo.y() + geo.height() - self.height() - self._EDGE_MARGIN
        self.move(x, y)

    def _apply_window_icon_for_taskbar(self) -> None:
        """タスクバー用に ``QApplication.windowIcon`` をこのウィンドウへコピーする。

        Returns:
            None: アプリにアイコンが無い場合は何もしない。
        """
        a = QApplication.instance()
        if a is not None and not a.windowIcon().isNull():
            self.setWindowIcon(a.windowIcon())

    @staticmethod
    def _format_elapsed(ms: int) -> str:
        """経過ミリ秒を時刻ラベル用の文字列に整形する。

        Args:
            ms (int): 経過時間（ミリ秒）。

        Returns:
            str: 1 時間未満は ``MM:SS``、それ以上は ``H:MM:SS``。
        """
        total_sec = ms // 1000
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _update_time_label(self) -> None:
        """``QElapsedTimer`` の経過に合わせて時刻ラベルの文字列を更新する。

        Returns:
            None: ``_format_elapsed`` の結果を ``_time_label`` に設定する。
        """
        self._time_label.setText(self._format_elapsed(self._elapsed.elapsed()))

    def _set_rec_led_idle(self) -> None:
        """録音 LED を待機（消灯相当）の QSS にする。

        Returns:
            None: ``_hud_theme.rec_led_idle_stylesheet`` を適用する。
        """
        self._rec_led.setStyleSheet(self._hud_theme.rec_led_idle_stylesheet)

    def _set_rec_led_on(self) -> None:
        """録音 LED を点灯（強い赤）の QSS にする。

        Returns:
            None: ``recording_hud_rec_led_on_qss`` を適用する。
        """
        self._rec_led.setStyleSheet(recording_hud_rec_led_on_qss())

    def _set_rec_led_dim(self) -> None:
        """録音 LED を点滅用の弱い赤の QSS にする。

        Returns:
            None: ``recording_hud_rec_led_dim_qss`` を適用する。
        """
        self._rec_led.setStyleSheet(recording_hud_rec_led_dim_qss())

    def _toggle_rec_led_blink(self) -> None:
        """録音中 LED の点滅トグルを反転し、強／弱のスタイルを切り替える。

        Returns:
            None: ``_set_rec_led_on`` または ``_set_rec_led_dim`` を呼ぶ。
        """
        self._rec_led_blink_on = not self._rec_led_blink_on
        if self._rec_led_blink_on:
            self._set_rec_led_on()
        else:
            self._set_rec_led_dim()
