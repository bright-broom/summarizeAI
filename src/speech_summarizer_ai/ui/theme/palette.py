"""商談一覧・詳細・録音 HUD の配色データクラスと、ライト／ダーク切替のテーマ factory。

``theme_basics`` から色計算ヘルパを、``qss.scrollbars`` からスクロールバー断片を取り込んで
合成する。UI 実装側はここで返される :class:`MeetingListTheme` 等をそのまま受け取る。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

from speech_summarizer_ai.ui.theme.qss.scrollbars import (
    list_scroll_area_qss,
    nested_scrollbar_overlay_qss,
)
from speech_summarizer_ai.ui.theme.theme_basics import (
    blend_icon_fg_toward_surface_for_disabled,
    dark_mode_preferred,
)


@dataclass(frozen=True)
class MeetingListTheme:
    """商談一覧 UI 用の色および QSS 断片。

    Attributes:
        page_bg: ページ背景色。
        scroll_bg: スクロール領域背景色。
        heading: 見出し文字色。
        secondary: 補助テキスト色。
        card_bg: カード背景色。
        card_border: カード枠線色。
        card_border_selected: 選択時カード枠線色。
        card_text: カード内ラベル共通の前景色。
        card_datetime_color: カード先頭の日時ラベル色（詳細の文字起こしタイムスタンプ列と同じ）。
        combo_qss: コンボボックス用スタイルシート。
        list_scroll_area_qss: 一覧スクロールエリア用スタイルシート。
    """

    page_bg: str
    scroll_bg: str
    heading: str
    secondary: str
    card_bg: str
    card_border: str
    card_border_selected: str
    card_text: str
    card_datetime_color: str
    combo_qss: str
    list_scroll_area_qss: str


@dataclass(frozen=True)
class RecordingHudTheme:
    """録音オーバーレイ（フレームレス HUD）の配色。

    Attributes:
        panel_fill: 角丸パネルの塗り。
        panel_border: パネル縁の線色。
        panel_border_width: パネル縁の線幅（ライトではやや太くして視認性を上げる）。
        time_label_color: 経過時刻ラベルの文字色（QSS）。
        close_button_qss: 閉じるボタン用スタイルシート。
        close_icon_color: 閉じるアイコン（×）の線色。
        rec_led_idle_stylesheet: 待機中の録音 LED 用 QSS。
    """

    panel_fill: QColor
    panel_border: QColor
    panel_border_width: float
    time_label_color: str
    close_button_qss: str
    close_icon_color: QColor
    rec_led_idle_stylesheet: str


@dataclass(frozen=True)
class MeetingDetailTheme:
    """商談詳細タブ UI 用の QSS 断片と色。

    Attributes:
        header_frame_qss: ヘッダーフレーム用スタイル。
        back_btn_qss: 戻るボタン用スタイル。
        meta_color: メタ情報ラベルの文字色（要約 ``QTextEdit`` の本文色と同じ）。
        tabs_qss: タブウィジェット用スタイル。
        summary_shell_bg: 要約タブシェル背景色。
        edit_btn_qss: 編集ボタン用スタイル。
        summary_edit_qss: 要約エディタ用スタイル。
        transcript_shell_bg: 文字起こしタブシェル背景色。
        transcript_hint_color: ヒント文の色。
        transcript_row_bg: 各行の背景色。
        transcript_row_border: 各行の枠色。
        transcript_ts_color: タイムスタンプ列の色。
        transcript_body_color: 本文の色。
    """

    header_frame_qss: str
    back_btn_qss: str
    meta_color: str
    tabs_qss: str
    summary_shell_bg: str
    edit_btn_qss: str
    summary_edit_qss: str
    transcript_shell_bg: str
    transcript_hint_color: str
    transcript_row_bg: str
    transcript_row_border: str
    transcript_ts_color: str
    transcript_body_color: str


def meeting_list_ui_is_dark(lt: MeetingListTheme) -> bool:
    """一覧テーマがダーク系か（カード背景の明度で判定）。

    Args:
        lt: 商談一覧テーマ。

    Returns:
        bool: カード背景の明度がしきい値未満なら ``True``。
    """
    return QColor(lt.card_bg).lightness() < 140


def list_icon_disabled_muted_on_list_card(
    lt: MeetingListTheme,
    *,
    base_fg: QColor,
    card_surface_hex: str | None = None,
) -> QColor:
    """一覧カード上アイコンの ``Disabled`` 用色。

    Args:
        lt: 一覧テーマ（``card_surface_hex`` 未指定時の面色に ``card_bg`` を使う）。
        base_fg: 有効時のアイコン前景色。
        card_surface_hex: ブレンド先の面色。``None`` のとき ``lt.card_bg``。

    Returns:
        QColor: :func:`~speech_summarizer_ai.ui.theme.theme_basics.blend_icon_fg_toward_surface_for_disabled` の結果。
    """
    surf = lt.card_bg if card_surface_hex is None else card_surface_hex
    return blend_icon_fg_toward_surface_for_disabled(base_fg, QColor(surf))


def list_icon_disabled_muted_on_list_page(
    lt: MeetingListTheme,
    *,
    base_fg: QColor,
) -> QColor:
    """一覧 ``page_bg`` 上アイコン（ヘッダ切替等）の ``Disabled`` 用色。

    Args:
        lt: 一覧テーマ（面は ``page_bg``）。
        base_fg: 有効時のアイコン前景色。

    Returns:
        QColor: ページ背景へ寄せた無効色。
    """
    return blend_icon_fg_toward_surface_for_disabled(base_fg, QColor(lt.page_bg))


def recording_hud_close_icon_disabled_muted(ht: RecordingHudTheme) -> QColor:
    """録音 HUD 閉じるボタン ``QIcon.Mode.Disabled`` 用色（パネル面へ寄せる）。

    Args:
        ht: 録音 HUD テーマ（閉じるアイコン色とパネル塗りを使用）。

    Returns:
        QColor: パネル面へブレンドした無効時アイコン色。
    """
    surf = QColor(ht.panel_fill.red(), ht.panel_fill.green(), ht.panel_fill.blue())
    return blend_icon_fg_toward_surface_for_disabled(
        QColor(ht.close_icon_color), surf, mix=0.5
    )


def meeting_list_theme(*, dark: bool | None = None) -> MeetingListTheme:
    """商談一覧用テーマを返す。

    Args:
        dark: 強制ダーク／ライト。``None`` のとき :func:`dark_mode_preferred` を使用。

    Returns:
        MeetingListTheme: 一覧ウィンドウ向けテーマ。
    """
    if dark is None:
        dark = dark_mode_preferred()
    if dark:
        return MeetingListTheme(
            page_bg="#1a1a1c",
            scroll_bg="#141416",
            heading="#f2f2f5",
            secondary="#b0b0b8",
            card_bg="#252528",
            card_border="#3d3d44",
            card_border_selected="#42a5f5",
            card_text="#ececf0",
            card_datetime_color="#90caf9",
            combo_qss="""
            QComboBox {
                padding: 4px 10px;
                border: 1px solid #4a4a52;
                border-radius: 4px;
                background-color: #2e2e32;
                color: #e8e8ec;
            }
            QComboBox:hover { border-color: #5c5c66; }
            QComboBox::drop-down { border: none; width: 22px; }
            QComboBox QAbstractItemView {
                background-color: #2e2e32;
                color: #e8e8ec;
                selection-background-color: #3949ab;
                selection-color: #ffffff;
                outline: 0;
                border: 1px solid #4a4a52;
            }
            """,
            list_scroll_area_qss=list_scroll_area_qss("#141416", dark=True),
        )
    return MeetingListTheme(
        page_bg="#f5f5f5",
        scroll_bg="#e4e6eb",
        heading="#222222",
        secondary="#333333",
        card_bg="#ffffff",
        card_border="#d8d8d8",
        card_border_selected="#2196f3",
        card_text="#333333",
        card_datetime_color="#1976d2",
        combo_qss="""
        QComboBox {
            padding: 4px 10px;
            border: 1px solid #d8d8d8;
            border-radius: 4px;
            background-color: #ffffff;
            color: #333333;
        }
        QComboBox:hover { border-color: #b0b0b0; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #333333;
            selection-background-color: #bbdefb;
            selection-color: #0d47a1;
            outline: 0;
            border: 1px solid #d8d8d8;
        }
        """,
        list_scroll_area_qss=list_scroll_area_qss("#e4e6eb", dark=False),
    )


def recording_hud_theme(*, dark: bool | None = None) -> RecordingHudTheme:
    """録音 HUD のライト／ダーク配色を返す（一覧の ``ui/dark`` と整合）。

    Args:
        dark: 強制ダーク／ライト。``None`` のとき :func:`dark_mode_preferred` を使用。

    Returns:
        RecordingHudTheme: オーバーレイ描画・子ウィジェット用。
    """
    if dark is None:
        dark = dark_mode_preferred()
    if dark:
        return RecordingHudTheme(
            panel_fill=QColor(0x1A, 0x1A, 0x1C, 240),
            panel_border=QColor(255, 255, 255, 242),
            panel_border_width=0.5,
            time_label_color="#ffffff",
            close_button_qss="""
            QPushButton {
                background: transparent;
                border: none;
                padding: 4px;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.22); border-radius: 14px; }
            QPushButton:pressed { background-color: rgba(255, 255, 255, 0.32); }
            """,
            close_icon_color=QColor(255, 255, 255),
            rec_led_idle_stylesheet="""
            QLabel {
                background-color: rgba(64, 64, 66, 0.9);
                border-radius: 6px;
            }
            """,
        )
    return RecordingHudTheme(
        panel_fill=QColor(250, 250, 252, 248),
        panel_border=QColor(52, 56, 66, 240),
        panel_border_width=1.15,
        time_label_color="#1a1a1e",
        close_button_qss="""
        QPushButton {
            background: transparent;
            border: none;
            padding: 4px;
        }
        QPushButton:hover { background-color: rgba(0, 0, 0, 0.14); border-radius: 14px; }
        QPushButton:pressed { background-color: rgba(0, 0, 0, 0.22); }
        """,
        close_icon_color=QColor(55, 55, 60),
        rec_led_idle_stylesheet="""
        QLabel {
            background-color: rgba(78, 82, 94, 0.98);
            border-radius: 6px;
        }
        """,
    )


def meeting_detail_theme(*, dark: bool | None = None) -> MeetingDetailTheme:
    """商談詳細用テーマを返す。

    Args:
        dark: 強制ダーク／ライト。``None`` のとき :func:`dark_mode_preferred` を使用。

    Returns:
        MeetingDetailTheme: 詳細ウィジェット向けテーマ。
    """
    if dark is None:
        dark = dark_mode_preferred()
    if dark:
        summary_body_fg = "#e8e8ec"
        return MeetingDetailTheme(
            header_frame_qss="""
            QFrame {
                background-color: #252528;
                border: none;
                border-bottom: 1px solid #3d3d44;
            }
            """,
            back_btn_qss="""
            QPushButton {
                color: #e8eaf6;
                background-color: #3949ab;
                border: none;
                border-radius: 8px;
                padding: 8px;
                min-width: 36px;
                min-height: 36px;
            }
            QPushButton:hover { background-color: #7986cb; }
            """,
            meta_color=summary_body_fg,
            tabs_qss="""
            QTabWidget {
                border: none;
                background-color: #1e1e22;
            }
            QTabBar {
                border: none;
                background-color: #1e1e22;
            }
            QTabWidget::pane {
                border: none;
                background: #1e1e22;
            }
            QTabBar::tab {
                background: transparent;
                color: #9e9ea8;
                padding: 4px 14px;
                margin: 2px 4px 4px 0;
                font-size: 15px;
                font-weight: bold;
                border: none;
                border-radius: 12px;
            }
            QTabBar::tab:selected {
                background-color: rgba(100, 181, 246, 0.32);
                color: #90caf9;
                border: none;
                border-radius: 12px;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                color: #e8e8ec;
                background-color: rgba(255, 255, 255, 0.14);
                border: none;
                border-radius: 12px;
            }
            """,
            summary_shell_bg="#1e1e22",
            edit_btn_qss="""
            QPushButton {
                background-color: #1976d2;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px;
                min-width: 36px;
                min-height: 36px;
            }
            QPushButton:hover { background-color: #42a5f5; }
            """,
            summary_edit_qss=(f"""
            QTextEdit {{
                background-color: #2a2a2e;
                border: 1px solid #45454e;
                border-radius: 10px;
                padding: 16px;
                color: {summary_body_fg};
                font-size: 15px;
            }}
            """ + nested_scrollbar_overlay_qss("QTextEdit", dark=True)),
            transcript_shell_bg="#1e1e22",
            transcript_hint_color="#a0a0a8",
            transcript_row_bg="#2a2a2e",
            transcript_row_border="#45454e",
            transcript_ts_color="#90caf9",
            transcript_body_color="#d8d8e0",
        )
    summary_body_fg = "#333333"
    return MeetingDetailTheme(
        header_frame_qss="""
        QFrame {
            background-color: #ffffff;
            border: none;
            border-bottom: 1px solid rgba(0, 0, 0, 0.09);
        }
        """,
        back_btn_qss="""
        QPushButton {
            color: #e8eaf6;
            background-color: #3949ab;
            border: none;
            border-radius: 8px;
            padding: 8px;
            min-width: 36px;
            min-height: 36px;
        }
        QPushButton:hover { background-color: #7986cb; }
        """,
        meta_color=summary_body_fg,
        tabs_qss="""
        QTabWidget {
            border: none;
            background-color: #fafafa;
        }
        QTabBar {
            border: none;
            background-color: #fafafa;
        }
        QTabWidget::pane {
            border: none;
            background: #fafafa;
        }
        QTabBar::tab {
            background: transparent;
            color: #757575;
            padding: 4px 14px;
            margin: 2px 4px 4px 0;
            font-size: 15px;
            font-weight: bold;
            border: none;
            border-radius: 12px;
        }
        QTabBar::tab:selected {
            background-color: #bbdefb;
            color: #1565c0;
            border: none;
            border-radius: 12px;
            font-weight: bold;
        }
        QTabBar::tab:hover:!selected {
            color: #212121;
            background-color: rgba(0, 0, 0, 0.09);
            border: none;
            border-radius: 12px;
        }
        """,
        summary_shell_bg="#fafafa",
        edit_btn_qss="""
        QPushButton {
            background-color: #1976d2;
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 8px;
            min-width: 36px;
            min-height: 36px;
        }
        QPushButton:hover { background-color: #42a5f5; }
        """,
        summary_edit_qss=(f"""
        QTextEdit {{
            background-color: #ffffff;
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            padding: 16px;
            color: {summary_body_fg};
            font-size: 15px;
        }}
        """ + nested_scrollbar_overlay_qss("QTextEdit", dark=False)),
        transcript_shell_bg="#fafafa",
        transcript_hint_color="#555555",
        transcript_row_bg="#ffffff",
        transcript_row_border="#e8e8e8",
        transcript_ts_color="#1976d2",
        transcript_body_color="#333333",
    )
