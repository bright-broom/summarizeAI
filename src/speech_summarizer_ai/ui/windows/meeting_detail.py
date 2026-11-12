"""商談の要約・文字起こし全文を Tab で表示する詳細パネル（一覧ウィンドウ内で使用）。

未保存の要約は一覧へ戻る・前後ナビ・Esc 等で確認ダイアログを挟む。
ライブ録音中は ``append_transcript_line`` で文字起こし行を追記し、メタ行を DB と同期する。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QSize, Qt, QSettings, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from speech_summarizer_ai.data import meetings_repository as meetings_db
from speech_summarizer_ai.ui.icons import action_icons
from speech_summarizer_ai.ui.theme import (
    DEFAULT_UI_DARK_UNSAVED,
    MeetingDetailTheme,
    MeetingListTheme,
    list_card_detail_icon_button_qss,
    list_icon_disabled_muted_on_list_card,
    meeting_detail_meta_label_qss,
    meeting_detail_shell_background_qss,
    meeting_detail_theme,
    meeting_detail_transcript_body_label_qss,
    meeting_detail_transcript_row_frame_qss,
    meeting_detail_transcript_ts_label_qss,
    meeting_list_theme,
    scroll_area_overlay_qss,
    transparent_background_qss,
)

# ヘッダ戻る／前後: アイコンボタンの最小正方形と SVG キャンバス（QSS min-width/height と整合）
_HEADER_NAV_BUTTON_MIN_PX = 36
_HEADER_NAV_ICON_CANVAS_PX = 34
_HEADER_NAV_ICON_SZ = QSize(_HEADER_NAV_ICON_CANVAS_PX, _HEADER_NAV_ICON_CANVAS_PX)
# 要約タブ編集: min 正方形・表示アイコン・高解像 SVG キャンバス（ヘッダナビと同系。padding 0 でセル内を最大化）
_SUMMARY_EDIT_BUTTON_MIN_PX = 32
_SUMMARY_EDIT_ICON_DISPLAY_PX = 32
_SUMMARY_EDIT_ICON_CANVAS_PX = 36
_SUMMARY_EDIT_ICON_SZ = QSize(
    _SUMMARY_EDIT_ICON_DISPLAY_PX, _SUMMARY_EDIT_ICON_DISPLAY_PX
)
# 要約ツールバー右端と編集ボタンのあいだ
_SUMMARY_EDIT_BTN_MARGIN_RIGHT_PX = 12
# 要約タブのみ：報告と編集のあいだ（報告は編集の左）
_SUMMARY_REPORT_EDIT_GAP_PX = 12
_SUMMARY_REPORT_BTN_MIN_WIDTH_PX = 70
_SUMMARY_REPORT_CAPTION_FONT_PT_DELTA = 2.0
_SUMMARY_REPORT_ICON_DISPLAY_PX = 24
_SUMMARY_REPORT_ICON_CANVAS_PX = 28
_SUMMARY_REPORT_ICON_SZ = QSize(
    _SUMMARY_REPORT_ICON_DISPLAY_PX, _SUMMARY_REPORT_ICON_DISPLAY_PX
)
# 要約／文字起こしタブでメタ行右列の幅を一致（要約＝報告＋隙間＋編集、文字起こし＝スペーサのみ）
_DETAIL_TOOLBAR_RIGHT_COLUMN_WIDTH_PX = (
    _SUMMARY_REPORT_BTN_MIN_WIDTH_PX
    + _SUMMARY_REPORT_EDIT_GAP_PX
    + _SUMMARY_EDIT_BUTTON_MIN_PX
    + _SUMMARY_EDIT_BTN_MARGIN_RIGHT_PX
)

_INAPPROPRIATE_CONTENT_REPORT_FORM_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLScNXl7jgO1emgtoG9H5iVDGia-7wvRSg1M0tf1a-mVhFeHQfQ/"
    "viewform?usp=dialog"
)
# 詳細ヘッダ行の上下余白（上をやや多めにしてタップ領域と空気感を確保）
_HEADER_ROW_VMARGIN_TOP = 14
_HEADER_ROW_VMARGIN_BOTTOM = 14
# 詳細ヘッダ右列の「前へ」「次へ」のあいだ
_HEADER_PREV_NEXT_SPACING = 10
# QTabWidget ラッパー四辺の余白（左右はネイティブ QTabBar の横張り付き対策、上下は同じ値で揃える）
_TAB_WIDGET_WRAP_MARGIN = 20


def _summary_save_discard_cancel_dialog(
    parent: QWidget,
    *,
    title: str,
    text: str,
) -> Literal["save", "discard", "cancel"]:
    """要約の未保存確認（保存／保存しない／キャンセル）。ボタン表記は日本語。

    Args:
        parent: ダイアログの親ウィジェット。
        title: ウィンドウタイトル。
        text: 本文メッセージ。

    Returns:
        ユーザーが選んだ操作。``"save"`` / ``"discard"`` / ``"cancel"`` のいずれか。
    """
    mb = QMessageBox(parent)
    mb.setIcon(QMessageBox.Icon.Question)
    mb.setWindowTitle(title)
    mb.setText(text)
    b_save = mb.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
    b_discard = mb.addButton("保存しない", QMessageBox.ButtonRole.DestructiveRole)
    b_cancel = mb.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
    mb.setDefaultButton(b_save)
    mb.exec()
    clicked = mb.clickedButton()
    if clicked == b_save:
        return "save"
    if clicked == b_discard:
        return "discard"
    return "cancel"


class MeetingDetailWidget(QWidget):
    """一覧と同一ウィンドウ内で表示する詳細（要約 / 文字起こし全文の Tab）。"""

    def __init__(
        self,
        parent: QWidget | None,
        on_back: Callable[[], None],
        *,
        project_root: Path,
        theme: MeetingDetailTheme | None = None,
        list_header_theme: MeetingListTheme | None = None,
        on_nav_prev: Callable[[], None] | None = None,
        on_nav_next: Callable[[], None] | None = None,
    ) -> None:
        """ウィジェットを構築する。

        Args:
            parent: 親ウィジェット。
            on_back: 「一覧に戻る」時に呼ぶコールバック。
            project_root: プロジェクトルート（DB 参照用）。
            theme: 詳細テーマ。``None`` のとき ``meeting_detail_theme()`` を使用。
            list_header_theme: 一覧と同じ色のヘッダナビ（戻る等）用。``None`` のとき ``ui/dark``（未保存ならダーク既定）に合わせた一覧テーマ。
            on_nav_prev: 「前へ」で前の商談へ進むコールバック。``None`` のときボタンを出さない。
            on_nav_next: 「次へ」で次の商談へ進むコールバック。``None`` のときボタンを出さない。

        Returns:
            None
        """
        super().__init__(parent)
        self._on_back = on_back
        self._on_nav_prev = on_nav_prev
        self._on_nav_next = on_nav_next
        self._project_root = project_root
        self._theme = theme if theme is not None else meeting_detail_theme()
        self._list_header_lt = (
            list_header_theme
            if list_header_theme is not None
            else meeting_list_theme(
                dark=bool(
                    QSettings("WEEL", "SpeechSummarizerAI").value(
                        "ui/dark", DEFAULT_UI_DARK_UNSAVED, type=bool
                    )
                )
            )
        )
        self._meeting_id: int | None = None
        self._baseline_summary: str = ""
        self._last_transcript_lines: tuple[tuple[str, str], ...] = ()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._detail_header = QFrame()
        self._detail_header.setFrameShape(QFrame.Shape.NoFrame)
        self._detail_header.setStyleSheet(self._theme.header_frame_qss)
        hb = QHBoxLayout(self._detail_header)
        hb.setContentsMargins(
            16, _HEADER_ROW_VMARGIN_TOP, 16, _HEADER_ROW_VMARGIN_BOTTOM
        )

        self._back_btn = QPushButton()
        self._back_btn.setText("")
        self._back_btn.setToolTip("一覧に戻る")
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self._on_back_clicked)

        show_nav = on_nav_prev is not None and on_nav_next is not None

        self._prev_btn = QPushButton()
        self._next_btn = QPushButton()
        self._prev_btn.setText("")
        self._next_btn.setText("")
        self._prev_btn.setIconSize(_HEADER_NAV_ICON_SZ)
        self._next_btn.setIconSize(_HEADER_NAV_ICON_SZ)
        self._back_btn.setIconSize(_HEADER_NAV_ICON_SZ)
        self._prev_btn.setToolTip("前の商談")
        self._next_btn.setToolTip("次の商談")
        for b in (self._prev_btn, self._next_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.clicked.connect(self._on_nav_prev_clicked)
        self._next_btn.clicked.connect(self._on_nav_next_clicked)
        self._prev_btn.setVisible(show_nav)
        self._next_btn.setVisible(show_nav)

        left_wrap = QWidget(self._detail_header)
        left_ll = QHBoxLayout(left_wrap)
        left_ll.setContentsMargins(0, 0, 0, 0)
        left_ll.setSpacing(0)
        left_ll.addWidget(self._back_btn)
        left_ll.addStretch(1)

        right_wrap = QWidget(self._detail_header)
        right_ll = QHBoxLayout(right_wrap)
        right_ll.setContentsMargins(0, 0, 0, 0)
        right_ll.setSpacing(0)
        right_ll.addStretch(1)
        right_ll.addWidget(self._prev_btn)
        right_ll.addSpacing(_HEADER_PREV_NEXT_SPACING)
        right_ll.addWidget(self._next_btn)

        self._apply_header_nav_buttons_appearance()

        _header_col_bg = transparent_background_qss()
        for _w in (left_wrap, right_wrap):
            _w.setStyleSheet(_header_col_bg)

        hb.addWidget(left_wrap, 1)
        hb.addStretch(1)
        hb.addWidget(right_wrap, 1)
        root.addWidget(self._detail_header)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.tabBar().setDrawBase(False)
        self._tabs.setStyleSheet(self._theme.tabs_qss)
        self._summary_tab = self._build_summary_tab_shell()
        self._transcript_tab, self._transcript_vl = self._build_transcript_tab_shell()
        self._tabs.addTab(self._summary_tab, "要約")
        self._tabs.addTab(self._transcript_tab, "文字起こし全文")
        # ネイティブスタイルでは setCornerWidget / QTabBar の QSS 余白が効かないことがあるため、
        # タブウィジェット全体をインデントする（各タブ内の横マージンは 0 にして合計を維持）
        self._tabs_wrap = QWidget()
        tabs_wrap_lay = QVBoxLayout(self._tabs_wrap)
        m = _TAB_WIDGET_WRAP_MARGIN
        tabs_wrap_lay.setContentsMargins(m, m, m, m)
        tabs_wrap_lay.setSpacing(0)
        tabs_wrap_lay.addWidget(self._tabs)
        root.addWidget(self._tabs_wrap, stretch=1)

        self.setStyleSheet(
            meeting_detail_shell_background_qss(self._theme.summary_shell_bg)
        )

    def current_meeting_id(self) -> int | None:
        """表示中の商談 ID。

        Returns:
            int | None: 設定済みなら商談 ID。未設定時は ``None``。
        """
        return self._meeting_id

    def populate(
        self,
        *,
        meeting_id: int,
        header_meta: str,
        summary_text: str | None = None,
        transcript_lines: tuple[tuple[str, str], ...] | None = None,
        start_summary_editing: bool = False,
        start_on_transcript_tab: bool = False,
        preserve_tab: bool = False,
    ) -> None:
        """詳細表示の内容を読み込み、タブを初期化する。

        Args:
            meeting_id: 商談 ID。
            header_meta: 要約タブ・文字起こしタブ上部に表示するメタ文字列。
            summary_text: 要約本文。``None`` は空として扱う。
            transcript_lines: 文字起こし行。``None`` は空。
            start_summary_editing: ``True`` のとき要約を編集モードで開く。
            start_on_transcript_tab: ``True`` のとき「文字起こし全文」タブを表示（録音中の確認用）。
            preserve_tab: ``True`` のとき現在のタブ選択を維持する（DB 再読込用）。

        Returns:
            None
        """
        self._meeting_id = meeting_id
        self._set_detail_meta_labels(header_meta)
        summary = summary_text if summary_text is not None else ""
        self._baseline_summary = summary
        self._summary_edit.setReadOnly(True)
        self._sync_edit_button_appearance()
        self._summary_edit.setPlainText(summary)
        lines = transcript_lines if transcript_lines is not None else ()
        self._last_transcript_lines = lines
        self._rebuild_transcript_rows(lines)
        if preserve_tab:
            pass
        elif start_summary_editing:
            self._tabs.setCurrentIndex(0)
            self._summary_edit.setReadOnly(False)
            self._sync_edit_button_appearance()
            QTimer.singleShot(0, self._summary_edit.setFocus)
        elif start_on_transcript_tab:
            self._tabs.setCurrentIndex(1)
        else:
            self._tabs.setCurrentIndex(0)

    def focus_transcript_tab(self) -> None:
        """「文字起こし全文」タブを前面にする（ライブ追記時に利用）。

        Returns:
            None
        """
        self._tabs.setCurrentIndex(1)

    def _sync_edit_button_appearance(self) -> None:
        """要約編集ボタンを閲覧／編集状態に合わせてアイコンとツールチップだけ更新する。

        Returns:
            None
        """
        lt = self._list_header_lt
        fg = QColor(lt.card_text)
        fg_dis = list_icon_disabled_muted_on_list_card(lt, base_fg=fg)
        iz = _SUMMARY_EDIT_ICON_DISPLAY_PX
        cp = _SUMMARY_EDIT_ICON_CANVAS_PX
        if self._summary_edit.isReadOnly():
            self._edit_btn.setIcon(
                action_icons.merge_icon_normal_and_disabled_pixmaps(
                    action_icons.icon_edit_summary(
                        self._edit_btn, color=fg, canvas_px=cp
                    ),
                    action_icons.icon_edit_summary(
                        self._edit_btn, color=fg_dis, canvas_px=cp
                    ),
                    iz,
                )
            )
            self._edit_btn.setToolTip("要約を編集")
        else:
            self._edit_btn.setIcon(
                action_icons.merge_icon_normal_and_disabled_pixmaps(
                    action_icons.icon_save_summary(
                        self._edit_btn, color=fg, canvas_px=cp
                    ),
                    action_icons.icon_save_summary(
                        self._edit_btn, color=fg_dis, canvas_px=cp
                    ),
                    iz,
                )
            )
            self._edit_btn.setToolTip("要約を保存（編集終了）")
        self._edit_btn.setText("")

    def _apply_summary_edit_button_chrome(self) -> None:
        """要約編集ボタンをヘッダの戻る等と同型（透明＋一覧系ホバー）にする。

        Returns:
            None
        """
        base = list_card_detail_icon_button_qss(
            self._list_header_lt,
            transparent=True,
            padding_px=0,
            min_side_px=_SUMMARY_EDIT_BUTTON_MIN_PX,
        )
        self._edit_btn.setStyleSheet(
            base
            + f"\nQPushButton {{ margin-right: {_SUMMARY_EDIT_BTN_MARGIN_RIGHT_PX}px; }}\n"
        )

    def _scroll_bars_dark(self) -> bool:
        """一覧テーマのカード背景から、スクロールバーグリップのトーンを推定する。

        Returns:
            bool: カード背景が暗いとき ``True``（``scroll_area_overlay_qss`` の ``dark`` 分岐に渡し、
            グリップを明るい半透明にする）。
        """
        return QColor(self._list_header_lt.card_bg).lightness() < 140

    def _apply_transcript_scroll_style(self) -> None:
        """文字起こしタブの ``QScrollArea`` を一覧と同型のスクロールバーにする。

        Returns:
            None
        """
        if not hasattr(self, "_transcript_scroll"):
            return
        self._transcript_scroll.setStyleSheet(
            scroll_area_overlay_qss(
                self._theme.transcript_shell_bg,
                dark=self._scroll_bars_dark(),
            )
        )

    def _apply_header_nav_buttons_appearance(self) -> None:
        """一覧カード「詳細」と同型のナビボタン（戻る・前・次）の QSS とアイコン色。

        Returns:
            None
        """
        lt = self._list_header_lt
        qss = list_card_detail_icon_button_qss(
            lt,
            transparent=True,
            padding_px=1,
            min_side_px=_HEADER_NAV_BUTTON_MIN_PX,
        )
        fg = QColor(lt.card_text)
        cp = _HEADER_NAV_ICON_CANVAS_PX
        self._back_btn.setStyleSheet(qss)
        self._prev_btn.setStyleSheet(qss)
        self._next_btn.setStyleSheet(qss)
        fg_dis = list_icon_disabled_muted_on_list_card(lt, base_fg=fg)
        self._back_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_back_to_list(self, color=fg, canvas_px=cp),
                action_icons.icon_back_to_list(self, color=fg_dis, canvas_px=cp),
                cp,
            )
        )
        self._prev_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_nav_previous(self, color=fg, canvas_px=cp),
                action_icons.icon_nav_previous(self, color=fg_dis, canvas_px=cp),
                cp,
            )
        )
        self._next_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_nav_next(self, color=fg, canvas_px=cp),
                action_icons.icon_nav_next(self, color=fg_dis, canvas_px=cp),
                cp,
            )
        )

    def apply_theme(
        self,
        theme: MeetingDetailTheme,
        *,
        list_header_lt: MeetingListTheme | None = None,
    ) -> None:
        """一覧側のライト／ダーク切替に合わせてスタイルを更新する。

        Args:
            theme: 詳細パネル用テーマ（ヘッダ・タブ・要約／文字起こしシェル等）。
            list_header_lt: ヘッダナビ（戻る・前・次）と要約編集ボタンの色合わせ用。
                ``None`` のとき既存の一覧テーマを維持する。

        Returns:
            None
        """
        self._theme = theme
        t = theme
        if list_header_lt is not None:
            self._list_header_lt = list_header_lt
        self._detail_header.setStyleSheet(t.header_frame_qss)
        self._apply_header_nav_buttons_appearance()
        self._summary_meta_label.setStyleSheet(
            meeting_detail_meta_label_qss(t.meta_color)
        )
        self._transcript_meta_label.setStyleSheet(
            meeting_detail_meta_label_qss(t.meta_color)
        )
        self.setStyleSheet(meeting_detail_shell_background_qss(t.summary_shell_bg))
        self._tabs.setStyleSheet(t.tabs_qss)
        self._summary_tab.setStyleSheet(
            meeting_detail_shell_background_qss(t.summary_shell_bg)
        )
        self._apply_report_button()
        self._apply_summary_edit_button_chrome()
        self._summary_edit.setStyleSheet(t.summary_edit_qss)
        self._transcript_tab.setStyleSheet(
            meeting_detail_shell_background_qss(t.transcript_shell_bg)
        )
        self._apply_transcript_scroll_style()
        self._sync_report_button_appearance()
        self._sync_edit_button_appearance()
        self._rebuild_transcript_rows(self._last_transcript_lines)

    def set_navigation_enabled(self, can_prev: bool, can_next: bool) -> None:
        """前へ／次へボタンの有効状態を更新する。

        Args:
            can_prev: 「前の商談」を押せるなら ``True``。
            can_next: 「次の商談」を押せるなら ``True``。

        Returns:
            None
        """
        self._prev_btn.setEnabled(can_prev)
        self._next_btn.setEnabled(can_next)

    def confirm_ready_to_leave_detail(self) -> bool:
        """一覧へ戻る・前後の商談へ移る前に要約の未保存を解決する。

        Returns:
            bool: 遷移してよいとき ``True``。キャンセル時 ``False``。
        """
        if self._meeting_id is not None and self._summary_dirty():
            choice = _summary_save_discard_cancel_dialog(
                self,
                title="要約の確認",
                text="要約が変更されています。保存しますか？",
            )
            if choice == "cancel":
                return False
            if choice == "save":
                if not self._persist_summary():
                    return False
            else:
                self._summary_edit.setPlainText(self._baseline_summary)
            self._summary_edit.setReadOnly(True)
            self._sync_edit_button_appearance()
            return True
        if not self._summary_edit.isReadOnly():
            if not self._persist_summary():
                return False
            self._summary_edit.setReadOnly(True)
            self._sync_edit_button_appearance()
        return True

    def _on_nav_prev_clicked(self) -> None:
        """「前の商談」ボタン押下。コンストラクタで渡した ``on_nav_prev`` を呼ぶ。

        Returns:
            None
        """
        if self._on_nav_prev is not None:
            self._on_nav_prev()

    def _on_nav_next_clicked(self) -> None:
        """「次の商談」ボタン押下。コンストラクタで渡した ``on_nav_next`` を呼ぶ。

        Returns:
            None
        """
        if self._on_nav_next is not None:
            self._on_nav_next()

    def _build_summary_tab_shell(self) -> QWidget:
        """要約タブのコンテナ（ツールバーと ``QTextEdit``）を組み立てる。

        Returns:
            QWidget: 要約タブのルートウィジェット。
        """
        w = QWidget()
        t = self._theme
        w.setStyleSheet(meeting_detail_shell_background_qss(t.summary_shell_bg))
        lay = QVBoxLayout(w)
        # 下は 0（タブペイン下端＝QTabWidget 本文下端に揃え、窓からの余白は _tabs_wrap のみ）
        lay.setContentsMargins(0, 16, 0, 0)
        lay.setSpacing(12)

        self._summary_meta_label = QLabel()
        self._summary_meta_label.setTextFormat(Qt.TextFormat.PlainText)
        self._summary_meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary_meta_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._summary_meta_label.setStyleSheet(
            meeting_detail_meta_label_qss(t.meta_color)
        )
        self._report_btn = QPushButton()
        self._report_btn.setText("報告")
        self._report_btn.setIconSize(_SUMMARY_REPORT_ICON_SZ)
        self._report_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # 動的プロパティ（UI 挙動は不変）— 自動化・補助が「報告」ボタンを識別しやすくする
        self._report_btn.setProperty("id", "submitReport")
        self._apply_report_button()
        self._report_btn.clicked.connect(self._on_report_inappropriate_content_clicked)

        self._edit_btn = QPushButton()
        self._edit_btn.setText("")
        self._edit_btn.setIconSize(_SUMMARY_EDIT_ICON_SZ)
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_summary_edit_button_chrome()
        self._edit_btn.clicked.connect(self._toggle_summary_edit)

        tool = QHBoxLayout()
        tool.setSpacing(8)
        tool.setContentsMargins(0, 0, 0, 0)
        tool.addWidget(self._summary_meta_label, stretch=1)
        self._summary_edit_toolbar_right = QWidget()
        self._summary_edit_toolbar_right.setFixedWidth(
            _DETAIL_TOOLBAR_RIGHT_COLUMN_WIDTH_PX
        )
        _edit_col_lay = QHBoxLayout(self._summary_edit_toolbar_right)
        _edit_col_lay.setContentsMargins(0, 0, 0, 0)
        _edit_col_lay.setSpacing(0)
        _edit_col_lay.addStretch(1)
        _edit_col_lay.addWidget(
            self._report_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        _edit_col_lay.addSpacing(_SUMMARY_REPORT_EDIT_GAP_PX)
        _edit_col_lay.addWidget(self._edit_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        tool.addWidget(
            self._summary_edit_toolbar_right, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        lay.addLayout(tool)

        self._summary_edit = QTextEdit()
        self._summary_edit.setReadOnly(True)
        self._summary_edit.setFont(QApplication.font())
        self._summary_edit.setStyleSheet(t.summary_edit_qss)
        lay.addWidget(self._summary_edit, stretch=1)
        self._sync_edit_button_appearance()

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), w)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self._on_summary_escape_shortcut)
        self._sync_report_button_appearance()
        return w

    def _apply_report_button(self) -> None:
        """要約タブ「報告」ボタンの QSS・フォントを一覧カード系スタイルで適用する。

        Returns:
            None
        """
        lt = self._list_header_lt
        base = list_card_detail_icon_button_qss(
            lt,
            transparent=True,
            padding_px=0,
            min_side_px=_SUMMARY_EDIT_BUTTON_MIN_PX,
        )
        self._report_btn.setFixedHeight(_SUMMARY_EDIT_BUTTON_MIN_PX)
        cap = QFont(QApplication.font())
        pt = cap.pointSizeF()
        if pt <= 0:
            pt = float(cap.pointSize() if cap.pointSize() > 0 else 10)
        cap.setPointSizeF(pt + _SUMMARY_REPORT_CAPTION_FONT_PT_DELTA)
        self._report_btn.setFont(cap)
        self._report_btn.setStyleSheet(
            base + f"\nQPushButton {{ color: {lt.card_text}; "
            f"min-width: {_SUMMARY_REPORT_BTN_MIN_WIDTH_PX}px; padding: 0 4px; }}\n"
        )

    def _sync_report_button_appearance(self) -> None:
        """要約タブ「報告」ボタンのメガホンアイコンとツールチップを更新する。

        Returns:
            None
        """
        lt = self._list_header_lt
        fg = QColor(lt.card_text)
        fg_dis = list_icon_disabled_muted_on_list_card(lt, base_fg=fg)
        iz = _SUMMARY_REPORT_ICON_DISPLAY_PX
        cp = _SUMMARY_REPORT_ICON_CANVAS_PX
        self._report_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_report(self._report_btn, color=fg, canvas_px=cp),
                action_icons.icon_report(self._report_btn, color=fg_dis, canvas_px=cp),
                iz,
            )
        )
        self._report_btn.setToolTip("AIが生成した不適切なコンテンツを報告する")

    def _on_report_inappropriate_content_clicked(self) -> None:
        """Google フォーム（不適切コンテンツ報告）を既定ブラウザで開く。

        Returns:
            None
        """
        QDesktopServices.openUrl(QUrl(_INAPPROPRIATE_CONTENT_REPORT_FORM_URL))

    def _summary_dirty(self) -> bool:
        """要約が最後に読み込んだ基準から変更されているか。

        Returns:
            bool: 未保存の編集がある場合 ``True``。
        """
        return self._summary_edit.toPlainText() != self._baseline_summary

    def _refresh_header_meta(self) -> None:
        """DB から商談を再読み込みし、要約／文字起こしタブ上部のメタ表示を更新する。

        Returns:
            None
        """
        if self._meeting_id is None:
            return
        rec = meetings_db.get_meeting(self._project_root, self._meeting_id)
        if rec is not None:
            self._set_detail_meta_labels(meetings_db.header_meta_for_detail(rec))

    def _set_detail_meta_labels(self, text: str) -> None:
        """要約／文字起こしタブ上部の共通メタ行を更新する。

        Args:
            text: 両タブの中央メタ ``QLabel`` に表示するプレーンテキスト。

        Returns:
            None
        """
        self._summary_meta_label.setText(text)
        self._transcript_meta_label.setText(text)

    def _persist_summary(self) -> bool:
        """現在の要約を DB に書き込む。

        Returns:
            bool: 変更が無いか保存に成功した場合 ``True``。失敗時は ``False``。
        """
        if self._meeting_id is None:
            return True
        text = self._summary_edit.toPlainText()
        if text == self._baseline_summary:
            return True
        if not meetings_db.update_meeting_summary(
            self._project_root, self._meeting_id, text
        ):
            QMessageBox.warning(
                self,
                "要約を保存",
                "保存に失敗しました。商談が見つからない可能性があります。",
            )
            return False
        self._baseline_summary = text
        self._refresh_header_meta()
        return True

    def _toggle_summary_edit(self) -> None:
        """要約の閲覧／編集モードを切り替える（保存は編集終了時に確認のうえ実行）。

        Returns:
            None
        """
        if not self._summary_edit.isReadOnly():
            if self._summary_dirty():
                choice = _summary_save_discard_cancel_dialog(
                    self,
                    title="要約の保存",
                    text="変更を保存しますか？",
                )
                if choice == "cancel":
                    return
                if choice == "save":
                    if not self._persist_summary():
                        return
                else:
                    self._summary_edit.setPlainText(self._baseline_summary)
            self._summary_edit.setReadOnly(True)
            self._sync_edit_button_appearance()
            return

        self._summary_edit.setReadOnly(False)
        self._sync_edit_button_appearance()
        QTimer.singleShot(0, self._summary_edit.setFocus)

    def _on_summary_escape_shortcut(self) -> None:
        """要約タブ内で Esc が押されたとき、保存せず閲覧モードに戻す。

        Returns:
            None
        """
        if self._summary_edit.isReadOnly():
            return
        self._summary_edit.setPlainText(self._baseline_summary)
        self._summary_edit.setReadOnly(True)
        self._sync_edit_button_appearance()

    def _on_back_clicked(self) -> None:
        """「一覧に戻る」押下時。未保存があれば確認ダイアログを出す。

        Returns:
            None
        """
        if not self.confirm_ready_to_leave_detail():
            return
        self._on_back()

    def _build_transcript_tab_shell(self) -> tuple[QWidget, QVBoxLayout]:
        """文字起こしタブのスクロール可能な行ホストを組み立てる。

        Returns:
            tuple[QWidget, QVBoxLayout]: タブウィジェットと行を積む縦レイアウト。
        """
        w = QWidget()
        t = self._theme
        w.setStyleSheet(meeting_detail_shell_background_qss(t.transcript_shell_bg))
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 16, 0, 20)
        lay.setSpacing(12)

        self._transcript_meta_label = QLabel()
        self._transcript_meta_label.setTextFormat(Qt.TextFormat.PlainText)
        self._transcript_meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._transcript_meta_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._transcript_meta_label.setStyleSheet(
            meeting_detail_meta_label_qss(t.meta_color)
        )
        # 要約タブのツールバー行（メタ＋編集ボタン）と行高・上余白を揃え、本文（QScrollArea）の上端を一致させる
        transcript_tool = QHBoxLayout()
        transcript_tool.setSpacing(8)
        transcript_tool.setContentsMargins(0, 0, 0, 0)
        transcript_tool.addWidget(self._transcript_meta_label, stretch=1)
        self._transcript_toolbar_spacer = QWidget()
        self._transcript_toolbar_spacer.setFixedSize(
            _DETAIL_TOOLBAR_RIGHT_COLUMN_WIDTH_PX,
            _SUMMARY_EDIT_BUTTON_MIN_PX,
        )
        transcript_tool.addWidget(
            self._transcript_toolbar_spacer,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )
        lay.addLayout(transcript_tool)

        self._transcript_scroll = QScrollArea()
        self._transcript_scroll.setWidgetResizable(True)
        self._transcript_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._apply_transcript_scroll_style()

        host = QWidget()
        host.setStyleSheet(transparent_background_qss())
        vl = QVBoxLayout(host)
        vl.setSpacing(10)
        vl.setContentsMargins(0, 0, 4, 0)

        self._transcript_scroll.setWidget(host)
        lay.addWidget(self._transcript_scroll, stretch=1)
        return w, vl

    def _transcript_row_frame(self, ts: str, text: str) -> QFrame:
        """文字起こし 1 行分の ``QFrame`` を組み立てる。

        Args:
            ts: 時刻列に表示する文字列。
            text: 本文（折り返しラベル）。

        Returns:
            QFrame: 角丸枠・時刻＋本文の横並びを持つ 1 行ウィジェット。
        """
        t = self._theme
        row = QFrame()
        row.setStyleSheet(
            meeting_detail_transcript_row_frame_qss(
                t.transcript_row_bg, t.transcript_row_border
            )
        )
        rh = QHBoxLayout(row)
        rh.setContentsMargins(12, 10, 12, 10)
        tlab = QLabel(ts)
        tlab.setStyleSheet(
            meeting_detail_transcript_ts_label_qss(t.transcript_ts_color)
        )
        tlab.setAlignment(Qt.AlignmentFlag.AlignTop)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(
            meeting_detail_transcript_body_label_qss(t.transcript_body_color)
        )
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        rh.addWidget(tlab, alignment=Qt.AlignmentFlag.AlignTop)
        rh.addWidget(body, stretch=1)
        return row

    def _pop_transcript_bottom_stretch(self) -> None:
        """レイアウト末尾の stretch（``addStretch``）があれば取り除く。

        ライブ追記で行を足す前に、末尾の伸びるスペーサだけを外すために使う。

        Returns:
            None
        """
        vl = self._transcript_vl
        if vl.count() == 0:
            return
        last = vl.itemAt(vl.count() - 1)
        if last is not None and last.spacerItem() is not None:
            vl.takeAt(vl.count() - 1)

    def append_transcript_line(self, ts: str, text: str) -> None:
        """文字起こしタブに 1 行追加する（録音中の DB 追記と同期したライブ表示用）。

        Args:
            ts: 時刻列。
            text: 本文。空白のみの行は追加しない。

        Returns:
            None
        """
        body = text.strip()
        if not body:
            return
        self._pop_transcript_bottom_stretch()
        self._transcript_vl.addWidget(self._transcript_row_frame(ts, body))
        self._transcript_vl.addStretch()
        self._last_transcript_lines = self._last_transcript_lines + ((ts, body),)
        if self._meeting_id is not None:
            rec = meetings_db.get_meeting(self._project_root, self._meeting_id)
            if rec is not None:
                self._set_detail_meta_labels(meetings_db.header_meta_for_detail(rec))
        sb = self._transcript_scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    def _rebuild_transcript_rows(self, lines: tuple[tuple[str, str], ...]) -> None:
        """文字起こし行をクリアし、指定内容で再構築する。

        Args:
            lines: ``(時刻, 本文)`` のタプル列。

        Returns:
            None
        """
        vl = self._transcript_vl
        while vl.count():
            item = vl.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for ts, text in lines:
            vl.addWidget(self._transcript_row_frame(ts, text))
        vl.addStretch()
