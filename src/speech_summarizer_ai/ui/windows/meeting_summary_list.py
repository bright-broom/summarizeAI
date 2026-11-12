"""会議一覧メインウィンドウ。

カード・検索・STT モデル選択・詳細（スタック）を持ち、`recording_host`（通常 `RecordingOverlay`）と
録音・テーマ・ライブ文字起こしを同期する。
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QSettings, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QMouseEvent,
    QFontMetrics,
    QWindowStateChangeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.data import meetings_repository as meetings_db
from speech_summarizer_ai.domain.meeting import (
    MeetingListRow,
    ProgressStatus,
    format_created_at_for_display,
)
from speech_summarizer_ai.ui.icons import action_icons
from speech_summarizer_ai.ui.theme import (
    DEFAULT_UI_DARK_UNSAVED,
    MeetingListTheme,
    apply_application_popup_chrome,
    card_delete_btn_fg,
    list_summary_card_delete_button_qss,
    list_summary_card_view_button_qss,
    meeting_detail_theme,
    meeting_list_card_badge_label_qss,
    meeting_list_card_datetime_label_qss,
    meeting_list_card_preview_label_qss,
    meeting_list_card_title_label_qss,
    meeting_list_header_theme_toggle_qss,
    meeting_list_header_title_qss,
    meeting_list_page_background_qss,
    meeting_list_search_lineedit_qss,
    meeting_list_search_shell_qss,
    meeting_list_theme,
    meeting_list_voice_caption_qss,
    list_icon_disabled_muted_on_list_card,
    list_icon_disabled_muted_on_list_page,
    record_action_button_qss,
    record_action_white_glyph_disabled_muted,
    summary_card_disabled_surface_bg,
    summary_card_frame_qss,
    transparent_background_qss,
)
from speech_summarizer_ai.ui.windows.meeting_detail import MeetingDetailWidget


def _summary_card_shadow_effect(
    parent: QWidget, lt: MeetingListTheme
) -> QGraphicsDropShadowEffect:
    """一覧カード用のドロップシャドウを構築する。

    Args:
        parent (QWidget): エフェクトの親ウィジェット。
        lt (MeetingListTheme): カード背景色から影の濃さを推定する。

    Returns:
        QGraphicsDropShadowEffect: ブラー半径・オフセット・色を設定済みのエフェクト。
    """
    eff = QGraphicsDropShadowEffect(parent)
    eff.setBlurRadius(16)
    eff.setOffset(4, 5)
    card = QColor(lt.card_bg)
    if not card.isValid():
        eff.setColor(QColor(0, 0, 0, 50))
        return eff
    if card.lightness() < 140:
        eff.setColor(QColor(0, 0, 0, 105))
    else:
        eff.setColor(QColor(0, 0, 0, 42))
    return eff


def _search_trailing_icon(lt: MeetingListTheme) -> QIcon:
    """検索欄末尾用の虫眼鏡アイコンを返す（通常／無効の合成 pixmap）。

    Args:
        lt (MeetingListTheme): 一覧テーマ。

    Returns:
        QIcon: 24px 想定の合成アイコン。
    """
    c = QColor(lt.secondary)
    c_dis = list_icon_disabled_muted_on_list_card(lt, base_fg=c)
    return action_icons.merge_icon_normal_and_disabled_pixmaps(
        action_icons.icon_search(None, color=c),
        action_icons.icon_search(None, color=c_dis),
        24,
    )


def _merged_header_theme_toggle_icon(
    lt: MeetingListTheme, widget: QWidget | None
) -> QIcon:
    """ヘッダのライト／ダーク切替アイコンを返す。

    Args:
        lt (MeetingListTheme): 一覧テーマ。
        widget (QWidget | None): アイコン描画の親（配色参照用）。``None`` でも可。

    Returns:
        QIcon: 24px 想定の合成アイコン。
    """
    h = QColor(lt.heading)
    h_dis = list_icon_disabled_muted_on_list_page(lt, base_fg=h)
    return action_icons.merge_icon_normal_and_disabled_pixmaps(
        action_icons.icon_dark_theme_toggle(widget, color=h),
        action_icons.icon_dark_theme_toggle(widget, color=h_dis),
        24,
    )


def _merged_record_header_icon(widget: QWidget, *, recording: bool) -> QIcon:
    """一覧ヘッダの録音開始／停止アイコンを返す（白グリフ、無効時は赤面へ寄せた色）。

    Args:
        widget (QWidget): 親ウィジェット。
        recording (bool): 録音中なら停止用グリフ。

    Returns:
        QIcon: 24px 想定の合成アイコン。
    """
    w = QColor(255, 255, 255)
    w_dis = record_action_white_glyph_disabled_muted()
    if recording:
        return action_icons.merge_icon_normal_and_disabled_pixmaps(
            action_icons.icon_record_stop(widget, color=w),
            action_icons.icon_record_stop(widget, color=w_dis),
            24,
        )
    return action_icons.merge_icon_normal_and_disabled_pixmaps(
        action_icons.icon_record_start(widget, color=w),
        action_icons.icon_record_start(widget, color=w_dis),
        24,
    )


def _progress_status_badge_ja(status: ProgressStatus) -> str:
    """進捗状態をバッジ用の短い日本語ラベルに変換する。

    Args:
        status (ProgressStatus): DB 上の進捗。

    Returns:
        str: バッジに表示する文言。
    """
    if status == ProgressStatus.RECORDING:
        return "録音中"
    if status == ProgressStatus.SUMMARIZING:
        return "要約中"
    if status == ProgressStatus.SUCCESS:
        return "要約済み"
    return "失敗"


def _progress_status_badge_colors(
    status: ProgressStatus, lt: MeetingListTheme
) -> tuple[str, str]:
    """バッジの文字色と枠線色を返す（カード面の明暗でトーンを変える）。

    Args:
        status (ProgressStatus): 進捗。
        lt (MeetingListTheme): 一覧テーマ。

    Returns:
        tuple[str, str]: ``(前景 #hex, 枠 #hex)`` のタプル。
    """
    dark = QColor(lt.card_bg).lightness() < 140
    if status == ProgressStatus.RECORDING:
        return ("#b71c1c", "#ff8a80") if not dark else ("#ffcdd2", "#c62828")
    if status == ProgressStatus.SUMMARIZING:
        return ("#0d47a1", "#64b5f6") if not dark else ("#bbdefb", "#1565c0")
    if status == ProgressStatus.SUCCESS:
        return ("#1b5e20", "#81c784") if not dark else ("#c8e6c9", "#2e7d32")
    # FAILED
    return ("#4a148c", "#ba68c8") if not dark else ("#e1bee7", "#6a1b9a")


def _progress_status_disables_card(_status: ProgressStatus) -> bool:
    """カード操作を無効にすべき進捗かを返す（現状は常に操作可能）。

    Args:
        _status (ProgressStatus): 進捗（将来の分岐用。現状未使用）。

    Returns:
        bool: 無効化すべきなら ``True``。現状は常に ``False``。
    """
    return False


class _CappedTitleLabel(QLabel):
    """タイトルを幅に応じて折り返し、最大行数で高さを抑える。"""

    def __init__(
        self, text: str, max_lines: int, style_sheet: str, parent: QWidget | None = None
    ) -> None:
        """タイトル用ラベルを初期化する。折り返し高さを ``max_lines`` で上限する。

        Args:
            text (str): 表示する全文。
            max_lines (int): 最大表示行数。
            style_sheet (str): ``QLabel`` 用 QSS。
            parent (QWidget | None): 親ウィジェット。

        Returns:
            None: 折り返し・スタイル・サイズポリシーを設定する。
        """
        super().__init__(text, parent)
        self._full = text
        self._max_lines = max(1, max_lines)
        self.setWordWrap(True)
        self.setStyleSheet(style_sheet)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """リサイズ時に折り返し高さを再計算する。

        Args:
            event (QResizeEvent): Qt が渡すリサイズイベント。

        Returns:
            None: 基底処理の後に :meth:`_reflow_height` を呼ぶ。
        """
        super().resizeEvent(event)
        self._reflow_height()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """表示時に折り返し高さを再計算する。

        Args:
            event (QShowEvent): Qt が渡す表示イベント。

        Returns:
            None: 基底処理の後に :meth:`_reflow_height` を呼ぶ。
        """
        super().showEvent(event)
        self._reflow_height()

    def _reflow_height(self) -> None:
        """現在の幅に合わせて ``maximumHeight`` を更新する。

        Returns:
            None: フォントメトリクスから折り返し後の高さを求め、上限を適用する。
        """
        w = max(self.width(), 1)
        fm = QFontMetrics(self.font())
        line = max(fm.lineSpacing(), fm.height())
        cap_px = int(self._max_lines * line + 6)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
        br = fm.boundingRect(QRect(0, 0, w, cap_px * 4), flags, self._full)
        self.setMaximumHeight(min(br.height() + 6, cap_px))


class _SummaryPreviewLabel(QLabel):
    """要約プレビュー: 幅が広いとき 1 行（省略）、狭いとき最大 2 行に収める。"""

    _WIDE_WIDTH_PX = 520

    def __init__(
        self, preview_text: str, style_sheet: str, parent: QWidget | None = None
    ) -> None:
        """要約プレビュー用ラベルを初期化する。幅に応じて 1 行省略または 2 行折り返し。

        Args:
            preview_text (str): 表示する全文。
            style_sheet (str): ``QLabel`` 用 QSS。
            parent (QWidget | None): 親ウィジェット。

        Returns:
            None: ツールチップ・サイズポリシーを設定する。
        """
        super().__init__(parent)
        self._full = preview_text
        self.setStyleSheet(style_sheet)
        self.setToolTip(preview_text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """リサイズ時に 1 行／2 行レイアウトを再適用する。

        Args:
            event (QResizeEvent): Qt が渡すリサイズイベント。

        Returns:
            None: 基底処理の後に :meth:`_apply_layout` を呼ぶ。
        """
        super().resizeEvent(event)
        self._apply_layout()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """表示時に 1 行／2 行レイアウトを再適用する。

        Args:
            event (QShowEvent): Qt が渡す表示イベント。

        Returns:
            None: 基底処理の後に :meth:`_apply_layout` を呼ぶ。
        """
        super().showEvent(event)
        self._apply_layout()

    def _apply_layout(self) -> None:
        """現在幅に応じて 1 行省略／2 行折り返しと高さを切り替える。

        Returns:
            None: ``_WIDE_WIDTH_PX`` を境に ``wordWrap`` と ``elidedText`` を切り替える。
        """
        w = max(self.width(), 1)
        fm = QFontMetrics(self.font())
        line = max(fm.lineSpacing(), fm.height())
        pad = 4
        one_h = int(line + pad)
        two_cap = int(2 * line + pad * 2)
        if w >= self._WIDE_WIDTH_PX:
            self.setWordWrap(False)
            self.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, w))
            self.setMaximumHeight(one_h)
            self.setMinimumHeight(0)
        else:
            self.setWordWrap(True)
            self.setText(self._full)
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
            br = fm.boundingRect(QRect(0, 0, w, two_cap * 3), flags, self._full)
            self.setMaximumHeight(min(br.height() + pad, two_cap))
            self.setMinimumHeight(0)


class _SummaryCard(QFrame):
    """商談一覧の 1 件分カード（クリック選択・ダブルクリックで詳細）。"""

    def __init__(
        self,
        index: int,
        item: MeetingListRow,
        on_select: Callable[[int], None],
        on_double_click: Callable[[int], None],
        on_delete: Callable[[int], None],
        list_theme: MeetingListTheme,
        parent: QWidget | None = None,
    ) -> None:
        """商談 1 件分のカード UI を構築する。

        Args:
            index (int): 表示中リスト内のカードインデックス。
            item (MeetingListRow): 行データ。
            on_select (Callable[[int], None]): 単一クリック時のコールバック。
            on_double_click (Callable[[int], None]): ダブルクリックまたは詳細ボタン時のコールバック。
            on_delete (Callable[[int], None]): 削除ボタン時のコールバック。
            list_theme (MeetingListTheme): 一覧テーマ。
            parent (QWidget | None): 親ウィジェット。

        Returns:
            None: レイアウト・スタイル・シグナル接続を行う。
        """
        super().__init__(parent)
        self._index = index
        self._on_select = on_select
        self._on_double_click = on_double_click
        self._list_theme = list_theme
        self._interaction_enabled = not _progress_status_disables_card(
            item.progress_status
        )
        self.setObjectName("summaryCard")
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if not self._interaction_enabled
            else Qt.CursorShape.PointingHandCursor
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if not self._interaction_enabled:
            self.setEnabled(False)

        card_surface = (
            list_theme.card_bg
            if self._interaction_enabled
            else summary_card_disabled_surface_bg(list_theme.card_bg)
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        tc = list_theme.card_text
        date_label = QLabel(format_created_at_for_display(item.created_at))
        date_label.setStyleSheet(
            meeting_list_card_datetime_label_qss(list_theme.card_datetime_color)
        )

        # 左右 2 列（左=日時＋タイトル＋要約プレビューを縦積み、右=状態バッジ＋ボタン行を縦積み）
        main_row = QHBoxLayout()
        main_row.setSpacing(16)
        main_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        left_col = QWidget()
        left_col.setStyleSheet(transparent_background_qss())
        lv = QVBoxLayout(left_col)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.addWidget(date_label)

        title_body = _CappedTitleLabel(
            item.title,
            3,
            meeting_list_card_title_label_qss(tc),
        )
        lv.addWidget(title_body)
        if item.summary_preview:
            summary_body = _SummaryPreviewLabel(
                item.summary_preview,
                meeting_list_card_preview_label_qss(list_theme.secondary),
            )
            lv.addWidget(summary_body)

        main_row.addWidget(left_col, stretch=1)

        right_col = QWidget()
        right_col.setStyleSheet(transparent_background_qss())
        rv = QVBoxLayout(right_col)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)
        rv.setAlignment(Qt.AlignmentFlag.AlignTop)

        badge = QLabel(_progress_status_badge_ja(item.progress_status))
        fg_badge, bd_badge = _progress_status_badge_colors(
            item.progress_status, list_theme
        )
        badge.setStyleSheet(
            meeting_list_card_badge_label_qss(card_surface, fg_badge, bd_badge)
        )
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rv.addWidget(badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)
        btn_row.setContentsMargins(0, 0, 0, 0)
        view_btn = QPushButton()
        view_btn.setText("")
        v_fg = QColor(list_theme.card_text)
        v_dis = list_icon_disabled_muted_on_list_card(
            list_theme, base_fg=v_fg, card_surface_hex=card_surface
        )
        view_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_view_detail(self, color=v_fg),
                action_icons.icon_view_detail(self, color=v_dis),
                24,
            )
        )
        view_btn.setIconSize(QSize(22, 22))
        view_btn.setToolTip("詳細を開く")
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.setStyleSheet(
            list_summary_card_view_button_qss(list_theme, card_bg=card_surface)
        )
        view_btn.clicked.connect(partial(on_double_click, index))
        btn_row.addWidget(view_btn)
        delete_btn = QPushButton()
        delete_btn.setText("")
        d_fg = card_delete_btn_fg(list_theme.card_text)
        d_dis = list_icon_disabled_muted_on_list_card(
            list_theme, base_fg=d_fg, card_surface_hex=card_surface
        )
        delete_btn.setIcon(
            action_icons.merge_icon_normal_and_disabled_pixmaps(
                action_icons.icon_delete(self, color=d_fg),
                action_icons.icon_delete(self, color=d_dis),
                24,
            )
        )
        delete_btn.setIconSize(QSize(22, 22))
        delete_btn.setToolTip("この商談を削除")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setStyleSheet(
            list_summary_card_delete_button_qss(list_theme, card_bg=card_surface)
        )
        delete_btn.clicked.connect(partial(on_delete, index))
        btn_row.addWidget(delete_btn)
        rv.addLayout(btn_row)

        main_row.addWidget(right_col, stretch=0)
        root.addLayout(main_row)

        self.setGraphicsEffect(_summary_card_shadow_effect(self, list_theme))

    def interaction_enabled(self) -> bool:
        """クリック・詳細・削除が有効かを返す。

        Returns:
            bool: 操作可能なら ``True``。
        """
        return self._interaction_enabled

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """左クリックでカード選択を親へ通知する。

        Args:
            event (QMouseEvent): マウスイベント。

        Returns:
            None: 基底の ``mousePressEvent`` に委譲する。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_select(self._index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """左ダブルクリックで詳細オープンを親へ通知する。

        Args:
            event (QMouseEvent): マウスイベント。

        Returns:
            None: 基底の ``mouseDoubleClickEvent`` に委譲する。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_double_click(self._index)
        super().mouseDoubleClickEvent(event)

    def apply_selected(self, selected: bool) -> None:
        """選択状態に応じてカード枠の QSS を更新する。

        Args:
            selected (bool): 選択中なら ``True``。

        Returns:
            None: ``summary_card_frame_qss`` でスタイルシートを設定する。
        """
        self.setStyleSheet(
            summary_card_frame_qss(
                self._list_theme,
                interaction_enabled=self._interaction_enabled,
                selected=selected,
            )
        )


class _SearchBarRow(QWidget):
    """検索欄の幅を親に追従しつつ最大幅で抑え、中央に置く。"""

    _MAX_WIDTH = 680
    _H_MARGIN = 24

    def __init__(self, shell: QFrame, parent: QWidget | None = None) -> None:
        """検索枠を中央寄せし、親幅に応じて最大幅を制限する行ウィジェットを初期化する。

        Args:
            shell (QFrame): 検索 UI を包む ``QFrame``。
            parent (QWidget | None): 親ウィジェット。

        Returns:
            None: レイアウトとサイズポリシーを設定する。
        """
        super().__init__(parent)
        self._shell = shell
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        lay.addWidget(shell, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """リサイズ時に検索枠の幅を再計算する。

        Args:
            event (QResizeEvent): Qt が渡すリサイズイベント。

        Returns:
            None: 基底処理の後に :meth:`_apply_shell_width` を呼ぶ。
        """
        super().resizeEvent(event)
        self._apply_shell_width()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """表示時に検索枠の幅を再計算する。

        Args:
            event (QShowEvent): Qt が渡す表示イベント。

        Returns:
            None: 基底処理の後に :meth:`_apply_shell_width` を呼ぶ。
        """
        super().showEvent(event)
        self._apply_shell_width()

    def _apply_shell_width(self) -> None:
        """検索 ``shell`` の固定幅をウィンドウ幅と ``_MAX_WIDTH`` に合わせる。

        Returns:
            None: 幅が正でない場合は何もしない。
        """
        aw = self.width()
        if aw <= 0:
            return
        w = min(self._MAX_WIDTH, max(260, aw - self._H_MARGIN))
        self._shell.setFixedWidth(w)


class MeetingSummaryListWindow(QMainWindow):
    """会議一覧のメインウィンドウ。`WA_DeleteOnClose` で閉じたら破棄。"""

    _WINDOW_TITLE = "Speech Summarizer AI"

    _SELECTED_INDEX_INITIAL = 0

    _WINDOW_FLAGS = (
        Qt.WindowType.Window
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowMaximizeButtonHint
    )

    def __init__(self, recording_host: QObject) -> None:
        """会議一覧のメインウィンドウを構築する。

        Args:
            recording_host (QObject): 録音トグルを委譲するホスト（通常 ``RecordingOverlay`` Facade）。
                必要な属性・メソッド・シグナルはすべて ``getattr`` で参照するため、
                実装上は ``QObject`` を満たせば足りる。

        Returns:
            None: UI・設定・DB・ホストとのシグナル接続を初期化する。
        """
        super().__init__(None)
        self._host = recording_host
        root_dir = getattr(recording_host, "_save_dir", None)
        self._project_root: Path = (
            root_dir if isinstance(root_dir, Path) else Path.cwd()
        )

        self.setWindowFlags(self._WINDOW_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 既定では「アクティブなウィンドウ」だけツールチップが出る。他アプリ操作中でも一覧上のヒントを出す。
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setWindowTitle(self._WINDOW_TITLE)
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        self.setMinimumSize(320, 240)

        self._settings = QSettings("WEEL", "SpeechSummarizerAI")
        self._ui_dark = bool(
            self._settings.value("ui/dark", DEFAULT_UI_DARK_UNSAVED, type=bool)
        )
        self._list_theme = meeting_list_theme(dark=self._ui_dark)
        self._detail_theme = meeting_detail_theme(dark=self._ui_dark)
        self._cards: list[_SummaryCard] = []
        self._meeting_ids: list[int] = []
        self._detail_list_index: int | None = None

        meetings_db.ensure_database(self._project_root)
        self._selected_index = self._SELECTED_INDEX_INITIAL
        self._was_maximized_before_minimize: bool = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        lt = self._list_theme
        central.setStyleSheet(meeting_list_page_background_qss(lt.page_bg))

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._list_page = QWidget()
        self._list_page.setStyleSheet(meeting_list_page_background_qss(lt.page_bg))
        list_outer = QVBoxLayout(self._list_page)
        list_outer.setContentsMargins(20, 16, 20, 16)
        list_outer.setSpacing(12)

        header = QHBoxLayout()
        self._header_title = QLabel("音声要約一覧")
        self._header_title.setStyleSheet(
            meeting_list_header_title_qss(lt.heading, left_padding_px=12)
        )
        header.addWidget(self._header_title)
        header.addStretch()

        self._record_btn = QPushButton()
        self._record_btn.setText("")
        self._record_btn.setIcon(
            _merged_record_header_icon(self._record_btn, recording=False)
        )
        self._record_btn.setIconSize(QSize(18, 18))
        self._record_btn.setFixedSize(36, 32)
        self._record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._record_btn.setToolTip("録音を開始 / 停止")
        self._record_btn.setStyleSheet(record_action_button_qss(recording=False))
        self._record_btn.clicked.connect(self._on_record_clicked)
        header.addWidget(self._record_btn)

        self._voice_label = QLabel("音声モデル選択")
        self._voice_label.setStyleSheet(meeting_list_voice_caption_qss(lt.secondary))
        header.addWidget(self._voice_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._voice_combo = QComboBox()
        for folder, label in config.STT_MODEL_OPTIONS:
            self._voice_combo.addItem(label, folder)
        _folders = [f for f, _ in config.STT_MODEL_OPTIONS]
        try:
            _default_idx = _folders.index(config.STT_DEFAULT_MODEL)
        except ValueError:
            _default_idx = 0
        self._voice_combo.setCurrentIndex(_default_idx)
        self._voice_combo.setMinimumWidth(140)
        self._voice_combo.setStyleSheet(lt.combo_qss)
        self._voice_combo.currentIndexChanged.connect(self._on_stt_model_combo_changed)
        header.addWidget(self._voice_combo)
        self._sync_stt_folder_to_host()

        self._theme_toggle_btn = QPushButton()
        self._theme_toggle_btn.setText("")
        self._theme_toggle_btn.setIcon(
            _merged_header_theme_toggle_icon(lt, self._theme_toggle_btn)
        )
        self._theme_toggle_btn.setIconSize(QSize(22, 22))
        self._theme_toggle_btn.setFixedSize(26, 26)
        self._theme_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_toggle_btn.setToolTip(
            "ダークテーマに切り替え" if not self._ui_dark else "ライトテーマに切り替え"
        )
        self._theme_toggle_btn.setStyleSheet(meeting_list_header_theme_toggle_qss(lt))
        self._theme_toggle_btn.clicked.connect(self._on_theme_toggle_clicked)
        header.addWidget(self._theme_toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        list_outer.addLayout(header)

        self._search_shell = QFrame()
        self._search_shell.setObjectName("listSearchShell")
        self._search_shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._search_shell.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._search_shell.setStyleSheet(
            meeting_list_search_shell_qss(lt, focused=False)
        )
        _search_lay = QVBoxLayout(self._search_shell)
        _search_lay.setContentsMargins(2, 2, 2, 2)
        _search_lay.setSpacing(0)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("タイトル・要約（一覧表示分）で検索")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setMinimumHeight(24)
        self._search_edit.setMinimumWidth(120)
        self._search_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._search_edit.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._search_edit.setStyleSheet(meeting_list_search_lineedit_qss(lt))
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._search_edit.installEventFilter(self)
        self._search_trailing_act = QAction(
            _search_trailing_icon(lt), "", self._search_edit
        )
        self._search_trailing_act.setToolTip("検索")
        self._search_trailing_act.triggered.connect(
            lambda: self._search_edit.setFocus()
        )
        self._search_edit.addAction(
            self._search_trailing_act, QLineEdit.ActionPosition.TrailingPosition
        )
        _search_lay.addWidget(self._search_edit)
        self._search_row = _SearchBarRow(self._search_shell)
        list_outer.addWidget(self._search_row)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._cards_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._cards_scroll.setStyleSheet(lt.list_scroll_area_qss)

        self._list_host = QWidget()
        self._list_host.setStyleSheet(meeting_list_page_background_qss(lt.scroll_bg))
        self._cards_list_layout = QVBoxLayout(self._list_host)
        # 左右と同じ 8px で上下も揃え、カード列の周囲に均一な余白を取る
        self._cards_list_layout.setContentsMargins(8, 8, 8, 8)
        self._cards_list_layout.setSpacing(12)

        self._populate_meeting_cards()

        self._cards_scroll.setWidget(self._list_host)
        list_outer.addWidget(self._cards_scroll, stretch=1)

        self._detail_widget = MeetingDetailWidget(
            self,
            self._show_list_page,
            project_root=self._project_root,
            theme=self._detail_theme,
            list_header_theme=lt,
            on_nav_prev=self._on_detail_nav_prev,
            on_nav_next=self._on_detail_nav_next,
        )
        self._stack.addWidget(self._list_page)
        self._stack.addWidget(self._detail_widget)

        self._apply_selection_styles()
        self.hide_header_record_button()
        host_theme = getattr(self._host, "set_ui_dark", None)
        if callable(host_theme):
            host_theme(self._ui_dark)

        rc = getattr(self._host, "recording_meeting_created", None)
        if rc is not None:
            rc.connect(self._on_recording_meeting_created)
        tx_saved = getattr(self._host, "live_transcript_line_saved", None)
        if tx_saved is not None:
            tx_saved.connect(self._on_live_transcript_line_saved)
        sm_start = getattr(self._host, "meeting_summarization_started", None)
        if sm_start is not None:
            sm_start.connect(self._on_meeting_summarization_started)
        sm_done = getattr(self._host, "meeting_summarization_finished", None)
        if sm_done is not None:
            sm_done.connect(self._on_meeting_summarization_finished)

    def _on_meeting_summarization_started(self, _meeting_id: int) -> None:
        """要約開始時にカード一覧を再構築する（バッジを「要約中」に合わせる）。

        Args:
            _meeting_id (int): 対象商談 ID（現状は全件再描画のため未使用）。

        Returns:
            None: :meth:`_populate_meeting_cards` を呼ぶ。
        """
        self._populate_meeting_cards()

    def _on_meeting_summarization_finished(self, meeting_id: int) -> None:
        """要約完了後に一覧を更新し、該当詳細を表示中なら DB から再表示する。

        Args:
            meeting_id (int): 商談 ID。

        Returns:
            None: 一覧の再構築と :meth:`_refresh_detail_if_showing` を行う。
        """
        self._populate_meeting_cards()
        self._refresh_detail_if_showing(meeting_id)

    def _refresh_detail_if_showing(self, meeting_id: int) -> None:
        """詳細ページが ``meeting_id`` を表示中なら ``populate`` で内容を更新する。

        Args:
            meeting_id (int): 商談 ID。

        Returns:
            None: 条件を満たさない場合や DB に行が無い場合は何もしない。
        """
        if self._stack.currentWidget() != self._detail_widget:
            return
        if self._detail_widget.current_meeting_id() != meeting_id:
            return
        full_i = self._full_list_index_for_meeting_id(meeting_id)
        if full_i is None:
            return
        rec = meetings_db.get_meeting(self._project_root, meeting_id)
        if rec is None:
            return
        self._detail_widget.populate(
            meeting_id=meeting_id,
            header_meta=meetings_db.header_meta_for_detail(rec),
            summary_text=rec.summary,
            transcript_lines=rec.transcript_lines,
            preserve_tab=True,
        )
        self._detail_widget.set_navigation_enabled(
            self._find_navigable_neighbor_index(full_i, 1) is not None,
            self._find_navigable_neighbor_index(full_i, -1) is not None,
        )

    def _on_recording_meeting_created(self, _meeting_id: int) -> None:
        """新規録音行作成後にカード一覧を再構築する。

        Args:
            _meeting_id (int): 追加された商談 ID（全件再描画のため未使用可）。

        Returns:
            None: :meth:`_populate_meeting_cards` を呼ぶ。
        """
        self._populate_meeting_cards()

    def _on_live_transcript_line_saved(
        self, meeting_id: int, ts: str, text: str
    ) -> None:
        """ライブ文字起こしの 1 行を詳細の文字起こしタブへ追加する。

        Args:
            meeting_id (int): 商談 ID。
            ts (str): 時刻文字列。
            text (str): 本文。

        Returns:
            None: 該当詳細を表示中でない場合は何もしない。
        """
        if self._stack.currentWidget() != self._detail_widget:
            return
        if self._detail_widget.current_meeting_id() != meeting_id:
            return
        self._detail_widget.focus_transcript_tab()
        self._detail_widget.append_transcript_line(ts, text)

    def _sync_stt_folder_to_host(self) -> None:
        """STT モデルコンボの現在値をホストの ``set_live_stt_folder_name`` に渡す。

        Returns:
            None: データが文字列でない、またはセッターが無い場合は何もしない。
        """
        folder = self._voice_combo.currentData()
        if not isinstance(folder, str):
            return
        setter = getattr(self._host, "set_live_stt_folder_name", None)
        if callable(setter):
            setter(folder)

    def _on_stt_model_combo_changed(self, _index: int) -> None:
        """STT モデルコンボ変更時にホストへ選択フォルダ名を同期する。

        Args:
            _index (int): 新しいコンボインデックス（現状は :meth:`_sync_stt_folder_to_host` のみ）。

        Returns:
            None: :meth:`_sync_stt_folder_to_host` を呼ぶ。
        """
        self._sync_stt_folder_to_host()

    def hide_header_record_button(self) -> None:
        """一覧ヘッダの録音ボタンを非表示にする。

        Returns:
            None: ``_record_btn`` の可視フラグを落とす。
        """
        self._record_btn.setVisible(False)

    def _on_theme_toggle_clicked(self) -> None:
        """設定キー ``ui/dark`` を反転し、テーマを再適用する。

        Returns:
            None: 設定の保存と :meth:`_apply_ui_theme` を行う。
        """
        self._ui_dark = not self._ui_dark
        self._settings.setValue("ui/dark", self._ui_dark)
        self._apply_ui_theme()

    def _apply_ui_theme(self) -> None:
        """``_ui_dark`` に合わせ、一覧・詳細・ポップアップ類のスタイルを更新する。

        Returns:
            None: テーマオブジェクトの再生成、QSS の再適用、カード再構築、ホスト通知を行う。
        """
        self._list_theme = meeting_list_theme(dark=self._ui_dark)
        self._detail_theme = meeting_detail_theme(dark=self._ui_dark)
        apply_application_popup_chrome(dark=self._ui_dark)
        lt = self._list_theme
        cw = self.centralWidget()
        if cw is not None:
            cw.setStyleSheet(meeting_list_page_background_qss(lt.page_bg))
        self._list_page.setStyleSheet(meeting_list_page_background_qss(lt.page_bg))
        self._header_title.setStyleSheet(
            meeting_list_header_title_qss(lt.heading, left_padding_px=12)
        )
        self._voice_label.setStyleSheet(meeting_list_voice_caption_qss(lt.secondary))
        self._voice_combo.setStyleSheet(lt.combo_qss)
        self._theme_toggle_btn.setStyleSheet(meeting_list_header_theme_toggle_qss(lt))
        self._theme_toggle_btn.setIcon(
            _merged_header_theme_toggle_icon(lt, self._theme_toggle_btn)
        )
        self._theme_toggle_btn.setToolTip(
            "ダークテーマに切り替え" if not self._ui_dark else "ライトテーマに切り替え"
        )
        self._search_shell.setStyleSheet(
            meeting_list_search_shell_qss(lt, focused=self._search_edit.hasFocus())
        )
        self._search_edit.setStyleSheet(meeting_list_search_lineedit_qss(lt))
        self._search_trailing_act.setIcon(_search_trailing_icon(lt))
        self._cards_scroll.setStyleSheet(lt.list_scroll_area_qss)
        self._list_host.setStyleSheet(meeting_list_page_background_qss(lt.scroll_bg))
        self._detail_widget.apply_theme(
            self._detail_theme, list_header_lt=self._list_theme
        )
        self._populate_meeting_cards()
        host_theme = getattr(self._host, "set_ui_dark", None)
        if callable(host_theme):
            host_theme(self._ui_dark)

    def _on_search_text_changed(self, _text: str) -> None:
        """検索語が変わったときフィルタ済みカードを再構築する。

        Args:
            _text (str): 新しい検索文字列（現状は :meth:`_populate_meeting_cards` 内で再取得）。

        Returns:
            None: :meth:`_populate_meeting_cards` を呼ぶ。
        """
        self._populate_meeting_cards()

    def _rows_matching_search(self, rows: list[MeetingListRow]) -> list[MeetingListRow]:
        """検索欄の文字列でタイトルおよび要約プレビューを部分一致フィルタする。

        Args:
            rows (list[MeetingListRow]): 全件の行リスト。

        Returns:
            list[MeetingListRow]: 一致した行。検索語が空なら ``rows`` の浅いコピーに相当。
        """
        q = self._search_edit.text().strip()
        if not q:
            return list(rows)
        needle = q.casefold()
        out: list[MeetingListRow] = []
        for r in rows:
            if needle in r.title.casefold():
                out.append(r)
                continue
            if needle in r.summary_preview.casefold():
                out.append(r)
        return out

    def _full_list_index_for_meeting_id(self, meeting_id: int) -> int | None:
        """全件リスト ``self._rows`` 内で ``meeting_id`` に一致する行のインデックスを返す。

        Args:
            meeting_id (int): 商談 ID。

        Returns:
            int | None: 見つかればインデックス。無ければ ``None``。
        """
        for i, r in enumerate(self._rows):
            if r.id == meeting_id:
                return i
        return None

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        """最小化前の最大化状態を ``_was_maximized_before_minimize`` に記録する。

        Args:
            event (QEvent): ウィンドウ状態変更などのイベント（``QWindowStateChangeEvent`` を特別扱い）。

        Returns:
            None: 基底の ``changeEvent`` に委譲する。
        """
        if isinstance(event, QWindowStateChangeEvent):
            old = event.oldState()
            new = self.windowState()
            if (new & Qt.WindowState.WindowMinimized) and not (
                old & Qt.WindowState.WindowMinimized
            ):
                self._was_maximized_before_minimize = bool(
                    old & Qt.WindowState.WindowMaximized
                )
            elif not (new & Qt.WindowState.WindowMinimized) and (
                old & Qt.WindowState.WindowMinimized
            ):
                self._was_maximized_before_minimize = False
        super().changeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        """検索 ``QLineEdit`` のフォーカスに合わせ、外枠 ``QFrame`` の QSS を切り替える。

        Args:
            watched (QObject): 監視対象オブジェクト。
            event (QEvent): Qt イベント。

        Returns:
            bool: 基底 ``eventFilter`` の戻り値。
        """
        if watched is self._search_edit:
            if event.type() == QEvent.Type.FocusIn:
                self._search_shell.setStyleSheet(
                    meeting_list_search_shell_qss(self._list_theme, focused=True)
                )
            elif event.type() == QEvent.Type.FocusOut:
                self._search_shell.setStyleSheet(
                    meeting_list_search_shell_qss(self._list_theme, focused=False)
                )
        return super().eventFilter(watched, event)

    def restore_from_minimized_preserving_window_state(self) -> None:
        """最小化を解除し、直前が最大化なら ``showMaximized``、そうでなければ ``showNormal`` する。

        Returns:
            None: 最小化中でない場合は何もしない。前面化・活性化も行う。
        """
        if not self.isMinimized():
            return
        if self._was_maximized_before_minimize:
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _populate_meeting_cards(self) -> None:
        """DB から一覧を読み込み、検索フィルタ後のカード行を再構築する。

        Returns:
            None: 既存カードを破棄し、選択補正・スタイル・スクロール位置を更新する。
        """
        lay = self._cards_list_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()
        self._meeting_ids.clear()
        self._rows = meetings_db.list_meetings(self._project_root)
        visible_rows = self._rows_matching_search(self._rows)
        n = len(visible_rows)
        self._selected_index = min(self._selected_index, max(0, n - 1))
        for i, row in enumerate(visible_rows):
            self._meeting_ids.append(row.id)
            card = _SummaryCard(
                i,
                row,
                self._on_card_selected,
                self._on_card_double_clicked,
                self._on_card_delete,
                self._list_theme,
                self._list_host,
            )
            self._cards.append(card)
            lay.addWidget(card)
        lay.addStretch()
        self._adjust_selected_index_to_interactive_card()
        self._apply_selection_styles()
        self._scroll_meeting_list_to_top()

    def _scroll_meeting_list_to_top(self) -> None:
        """カード再構築後、縦スクロールを先頭（新しい行側）へ戻す。

        Returns:
            None: 次イベントループでスクロールバーを最小値に設定する。
        """
        sb = self._cards_scroll.verticalScrollBar()

        def _go_top() -> None:
            """スクロールバーを最上部へ移動する（``QTimer.singleShot`` コールバック）。

            Returns:
                None: 縦スクロールバーを最小値に設定する。
            """
            sb.setValue(sb.minimum())

        QTimer.singleShot(0, _go_top)

    def _adjust_selected_index_to_interactive_card(self) -> None:
        """選択インデックスを、操作可能なカード上に収まるよう補正する。

        Returns:
            None: 操作可能なカードが無い場合は範囲内にクリップするのみ。
        """
        n = len(self._cards)
        if n == 0:
            self._selected_index = 0
            return
        self._selected_index = min(self._selected_index, n - 1)
        if self._cards[self._selected_index].interaction_enabled():
            return
        for i, card in enumerate(self._cards):
            if card.interaction_enabled():
                self._selected_index = i
                return

    def _on_card_selected(self, index: int) -> None:
        """カードがクリックされたとき選択インデックスを更新する。

        Args:
            index (int): カードインデックス。

        Returns:
            None: 範囲外または非操作カードなら何もしない。
        """
        if not (0 <= index < len(self._cards)):
            return
        if not self._cards[index].interaction_enabled():
            return
        self._selected_index = index
        self._apply_selection_styles()

    def _on_card_double_clicked(self, index: int) -> None:
        """カードのダブルクリックで商談詳細を開く。

        Args:
            index (int): カードインデックス。

        Returns:
            None: 条件を満たさない場合や全件インデックス解決に失敗した場合は何もしない。
        """
        if not (0 <= index < len(self._cards)):
            return
        if not self._cards[index].interaction_enabled():
            return
        mid = self._meeting_ids[index]
        full_i = self._full_list_index_for_meeting_id(mid)
        if full_i is None:
            return
        self._open_meeting_detail(full_i)

    def _on_card_delete(self, index: int) -> None:
        """削除確認後、商談を DB から削除し一覧を更新する。

        Args:
            index (int): カードインデックス。

        Returns:
            None: ユーザーがキャンセルした場合や DB 削除に失敗した場合は何もしない。
        """
        if not (0 <= index < len(self._meeting_ids)):
            return
        if (
            0 <= index < len(self._cards)
            and not self._cards[index].interaction_enabled()
        ):
            return
        mid = self._meeting_ids[index]
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Question)
        mb.setWindowTitle("削除の確認")
        mb.setText("この商談を削除しますか？")
        btn_delete = mb.addButton("削除", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = mb.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(btn_cancel)
        mb.exec()
        if mb.clickedButton() is not btn_delete:
            return
        if not meetings_db.delete_meeting(self._project_root, mid):
            return
        n = len(self._meeting_ids)
        sel = self._selected_index
        if sel > index:
            self._selected_index = sel - 1
        elif sel == index:
            self._selected_index = min(index, max(0, n - 2))
        self._selected_index = max(0, self._selected_index)
        self._populate_meeting_cards()

    def _find_navigable_neighbor_index(self, from_idx: int, delta: int) -> int | None:
        """一覧インデックスから、操作可能な隣の商談インデックスを返す。

        一覧は新しい順（インデックス 0 が最新）なので、
        ``delta=1`` はより古い行方向、``delta=-1`` はより新しい行方向。

        Args:
            from_idx (int): 基準となる ``self._rows`` のインデックス。
            delta (int): 走査方向（``1`` または ``-1``）。

        Returns:
            int | None: 操作可能な行が見つかればそのインデックス。なければ ``None``。
        """
        if not self._rows or not (0 <= from_idx < len(self._rows)):
            return None
        i = from_idx + delta
        while 0 <= i < len(self._rows):
            if not _progress_status_disables_card(self._rows[i].progress_status):
                return i
            i += delta
        return None

    def _on_detail_nav_prev(self) -> None:
        """詳細で「前の商談」へ移動する（一覧ではより古いインデックス方向）。

        Returns:
            None: 遷移不可や確認キャンセル時は何もしない。
        """
        if self._detail_list_index is None:
            return
        if not self._detail_widget.confirm_ready_to_leave_detail():
            return
        # 一覧は新しい順（上が最新）なので「前」はより古い行（インデックス +1）
        t = self._find_navigable_neighbor_index(self._detail_list_index, 1)
        if t is None:
            return
        self._open_meeting_detail(t)

    def _on_detail_nav_next(self) -> None:
        """詳細で「次の商談」へ移動する（一覧ではより新しいインデックス方向）。

        Returns:
            None: 遷移不可や確認キャンセル時は何もしない。
        """
        if self._detail_list_index is None:
            return
        if not self._detail_widget.confirm_ready_to_leave_detail():
            return
        # 「次」はより新しい行（インデックス -1）
        t = self._find_navigable_neighbor_index(self._detail_list_index, -1)
        if t is None:
            return
        self._open_meeting_detail(t)

    def _open_meeting_detail(
        self, full_row_index: int, *, start_summary_editing: bool = False
    ) -> None:
        """``self._rows``（全件・新しい順）上のインデックスで商談詳細をスタックに表示する。

        Args:
            full_row_index (int): ``meetings_db.list_meetings`` の並び（更新が新しい順）における行インデックス。
            start_summary_editing (bool): ``True`` のとき開いた直後から要約を編集モードにする。

        Returns:
            None: スタックを詳細へ切り替え、ナビゲーション可否とウィンドウタイトルを更新する。
        """
        if not (0 <= full_row_index < len(self._rows)):
            return
        row = self._rows[full_row_index]
        if _progress_status_disables_card(row.progress_status):
            return
        mid = row.id
        rec = meetings_db.get_meeting(self._project_root, mid)
        if rec is None:
            return
        self._detail_list_index = full_row_index
        self._detail_widget.populate(
            meeting_id=mid,
            header_meta=meetings_db.header_meta_for_detail(rec),
            summary_text=rec.summary,
            transcript_lines=rec.transcript_lines,
            start_summary_editing=start_summary_editing,
            start_on_transcript_tab=(row.progress_status == ProgressStatus.RECORDING),
        )
        self._detail_widget.set_navigation_enabled(
            self._find_navigable_neighbor_index(full_row_index, 1) is not None,
            self._find_navigable_neighbor_index(full_row_index, -1) is not None,
        )
        self._stack.setCurrentWidget(self._detail_widget)
        self.setWindowTitle(self._window_title_for_detail(row.title))

    def _window_title_for_detail(self, meeting_title: str) -> str:
        """詳細表示中のウィンドウタイトル文字列を返す。

        Args:
            meeting_title (str): 商談タイトル。

        Returns:
            str: 空ならアプリ名＋「詳細」、それ以外は ``アプリ名 - タイトル`` 形式。
        """
        t = meeting_title.strip()
        if not t:
            return f"{self._WINDOW_TITLE} — 詳細"
        return f"{self._WINDOW_TITLE} - {t}"

    def _show_list_page(self) -> None:
        """詳細から一覧ページへ戻し、ウィンドウタイトルとカード一覧を更新する。

        Returns:
            None: スタックを一覧へ戻し :meth:`_populate_meeting_cards` を呼ぶ。
        """
        self._detail_list_index = None
        self._stack.setCurrentWidget(self._list_page)
        self.setWindowTitle(self._WINDOW_TITLE)
        self._populate_meeting_cards()

    def _apply_selection_styles(self) -> None:
        """全カードに現在の選択インデックスに応じた枠スタイルを反映する。

        Returns:
            None: 各カードへ :meth:`_SummaryCard.apply_selected` を渡す。
        """
        for i, card in enumerate(self._cards):
            card.apply_selected(i == self._selected_index)

    def _on_record_clicked(self) -> None:
        """ヘッダの録音ボタンからホストの ``toggle_recording`` を呼ぶ。

        Returns:
            None: ホストにトグルが無い場合は何もしない。
        """
        toggle = getattr(self._host, "toggle_recording", None)
        if callable(toggle):
            toggle()

    def sync_record_button(
        self, *, recording: bool, interaction_enabled: bool = True
    ) -> None:
        """録音状態に合わせてヘッダ録音ボタンのアイコン・ツールチップ・QSS を更新する。

        Args:
            recording (bool): 録音中なら ``True``。
            interaction_enabled (bool): ``False`` のときクリック不可（音声認識〜要約の待機中など）。

        Returns:
            None: アイコン・有効状態・ツールチップ・スタイルシートを設定する。
        """
        self._record_btn.setText("")
        self._record_btn.setIcon(
            _merged_record_header_icon(self._record_btn, recording=recording)
        )
        self._record_btn.setEnabled(interaction_enabled)
        if interaction_enabled:
            self._record_btn.setToolTip(
                "録音を停止する" if recording else "録音を開始する"
            )
        else:
            self._record_btn.setToolTip(
                "音声認識および要約が完了するまでお待ちください"
            )
        self._record_btn.setStyleSheet(record_action_button_qss(recording=recording))

    def center_on_primary_screen(self) -> None:
        """プライマリスクリーンの利用可能領域の中央へウィンドウを移動する。

        Returns:
            None: スクリーンが取得できない場合は何もしない。
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        ag = screen.availableGeometry()
        g = self.frameGeometry()
        g.moveCenter(ag.center())
        self.move(g.topLeft())
