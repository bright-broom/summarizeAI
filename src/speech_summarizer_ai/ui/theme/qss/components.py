"""一覧ウィンドウ・詳細タブ・録音 HUD・Record ボタンの QSS 断片。

テーマ依存の色は :class:`~speech_summarizer_ai.ui.theme.palette.MeetingListTheme` 等から
受け取り、共通のホバー色計算などは :mod:`~speech_summarizer_ai.ui.theme.theme_basics` と :mod:`.popups` を経由する。
"""

from __future__ import annotations

from speech_summarizer_ai.ui.theme.palette import (
    MeetingListTheme,
    meeting_list_ui_is_dark,
)
from speech_summarizer_ai.ui.theme.qss.popups import tooltip_chrome_qss_fragment
from speech_summarizer_ai.ui.theme.theme_basics import (
    card_delete_btn_hover_bg,
    list_card_detail_btn_hover_bg,
    summary_card_disabled_surface_bg,
)

# =============================================================================
# 一覧ウィンドウ共通
# =============================================================================


def meeting_list_page_background_qss(page_bg: str) -> str:
    """ページ／セントラル等の単色背景。

    Args:
        page_bg: CSS 色（例 ``#f5f5f5``）。

    Returns:
        str: ``background-color`` のみの QSS 断片。
    """
    return f"background-color: {page_bg};"


def meeting_list_header_title_qss(
    heading_color: str, *, left_padding_px: int = 0
) -> str:
    """一覧ウィンドウ見出し（例: 「音声要約一覧」）用 QSS。

    Args:
        heading_color: 見出し文字色。
        left_padding_px: 左インデント（ピクセル）。``0`` で付与しない。

    Returns:
        str: フォントサイズ・太字・色（＋任意の左パディング）の断片。
    """
    pad = f" padding-left: {left_padding_px}px;" if left_padding_px > 0 else ""
    return f"font-size: 22px; font-weight: 700; color: {heading_color};{pad}"


def meeting_list_voice_caption_qss(secondary_color: str) -> str:
    """「音声モデル選択」など補助キャプション用 QSS。

    Args:
        secondary_color: 文字色。

    Returns:
        str: 色と 13px フォントの断片。
    """
    return f"color: {secondary_color}; font-size: 13px;"


def meeting_list_header_theme_toggle_qss(lt: MeetingListTheme) -> str:
    """一覧ヘッダのダーク／ライト切替ボタン用 QSS（アイコン色は ``setIcon``）。

    Args:
        lt: 一覧テーマ（通常・ホバー背景に ``page_bg`` を使用）。

    Returns:
        str: 小さめ正方形の ``QPushButton`` 向けスタイル。
    """
    hover = list_card_detail_btn_hover_bg(lt.page_bg)
    return f"""
        QPushButton {{
            background-color: {lt.page_bg};
            border: none;
            border-radius: 6px;
            padding: 2px;
            min-width: 22px;
            min-height: 22px;
        }}
        QPushButton:hover {{
            background-color: {hover};
            border: none;
        }}
    """


def meeting_list_search_shell_qss(
    lt: MeetingListTheme, *, focused: bool = False
) -> str:
    """検索欄の外枠 ``QFrame#listSearchShell`` 用 QSS。

    Args:
        lt: 一覧テーマ（背景・枠色）。
        focused: ``True`` のとき選択時と同じ枠色を使う。

    Returns:
        str: 角丸フレームのスタイルシート。
    """
    bd = lt.card_border_selected if focused else lt.card_border
    return f"""
        QFrame#listSearchShell {{
            border: 1px solid {bd};
            border-radius: 12px;
            background-color: {lt.card_bg};
        }}
    """


def meeting_list_search_lineedit_qss(lt: MeetingListTheme) -> str:
    """検索 ``QLineEdit`` 本体（枠なし・外枠は ``meeting_list_search_shell_qss`` 側）。

    Args:
        lt: 一覧テーマ（文字色・カード背景と整合した透明背景）。

    Returns:
        str: 枠なし入力欄のスタイル。
    """
    return f"""
        QLineEdit {{
            border: none;
            background-color: transparent;
            color: {lt.card_text};
            padding: 2px 10px;
            font-size: 13px;
            min-height: 18px;
        }}
    """


def meeting_list_card_datetime_label_qss(datetime_color: str) -> str:
    """カード先頭の日時ラベル用 QSS。

    Args:
        datetime_color: 日時文字色。

    Returns:
        str: 小さめ太字・透明背景の ``QLabel`` 向け断片。
    """
    return (
        f"color: {datetime_color}; font-size: 13px; font-weight: 600; "
        "background: transparent;"
    )


def meeting_list_card_title_label_qss(card_text_color: str) -> str:
    """カードタイトル（折り返しラベル）用 QSS。

    Args:
        card_text_color: タイトル文字色。

    Returns:
        str: 13px・透明背景の断片。
    """
    return f"color: {card_text_color}; font-size: 13px; background: transparent;"


def meeting_list_card_preview_label_qss(secondary_color: str) -> str:
    """カード要約プレビュー（補助テキスト）用 QSS。

    Args:
        secondary_color: プレビュー文字色。

    Returns:
        str: 12px・透明背景の断片。
    """
    return f"color: {secondary_color}; font-size: 12px; background: transparent;"


def meeting_list_card_badge_label_qss(surface_bg: str, fg: str, border: str) -> str:
    """カード状態バッジ ``QLabel`` 用 QSS（ピル型）。

    Args:
        surface_bg: バッジ背景色。
        fg: 文字色。
        border: 枠線色。

    Returns:
        str: 角丸・小さめ太字のラベルスタイル。
    """
    return f"""
            QLabel {{
                background-color: {surface_bg};
                color: {fg};
                border: 1px solid {border};
                font-size: 11px;
                font-weight: 600;
                padding: 3px 10px;
                border-radius: 10px;
            }}
            """


def summary_card_frame_qss(
    lt: MeetingListTheme,
    *,
    interaction_enabled: bool,
    selected: bool,
) -> str:
    """``QFrame#summaryCard`` の枠・背景（選択／無効）。

    Args:
        lt: 一覧テーマ。
        interaction_enabled: ``False`` のとき操作不可の薄い面色。
        selected: ``True`` のとき選択枠（太線）。

    Returns:
        str: カードフレーム用スタイルシート。
    """
    if not interaction_enabled:
        dis = summary_card_disabled_surface_bg(lt.card_bg)
        return f"""
                QFrame#summaryCard {{
                    background-color: {dis};
                    border: 1px solid {lt.card_border};
                    border-radius: 8px;
                }}
                """
    if selected:
        border = lt.card_border_selected
        width = 2
    else:
        border = lt.card_border
        width = 1
    return f"""
            QFrame#summaryCard {{
                background-color: {lt.card_bg};
                border: {width}px solid {border};
                border-radius: 8px;
            }}
            """


def list_card_detail_icon_button_qss(
    lt: MeetingListTheme,
    *,
    card_bg: str | None = None,
    transparent: bool = False,
    padding_px: int = 5,
    min_side_px: int = 32,
) -> str:
    """一覧カード「詳細」と同型の小さなアイコンボタン用 QSS。

    アイコン色は ``setIcon`` で指定する。``QPushButton`` に ``color`` を付けない。

    Args:
        lt: 一覧テーマ。
        card_bg: ボタン背景。``transparent=True`` のとき無視。
        transparent: ``True`` のとき通常背景は透明、ホバー／押下は一覧「詳細」と同じ
            :func:`list_card_detail_btn_hover_bg`（詳細ヘッダの戻る等）。
        padding_px: 内側余白。大きいアイコンを同じ ``min-width`` / ``min-height`` に
            収めるとき小さくする。
        min_side_px: ``min-width`` / ``min-height`` の値（正方形のターゲット）。

    Returns:
        str: ``QPushButton`` 向けスタイル（通常・ホバー・押下）。
    """
    bg = lt.card_bg if card_bg is None else card_bg
    hover_bg = list_card_detail_btn_hover_bg(bg)
    if transparent:
        return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 8px;
            padding: {padding_px}px;
            min-width: {min_side_px}px;
            min-height: {min_side_px}px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            border: none;
        }}
        QPushButton:pressed {{
            background-color: {hover_bg};
            border: none;
        }}
    """
    return f"""
        QPushButton {{
            background-color: {bg};
            border: none;
            border-radius: 8px;
            padding: {padding_px}px;
            min-width: {min_side_px}px;
            min-height: {min_side_px}px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            border: none;
        }}
    """


def list_summary_card_view_button_qss(
    lt: MeetingListTheme, *, card_bg: str | None = None
) -> str:
    """一覧カード「詳細」アイコンボタン用 QSS。

    ネイティブツールチップ経路向けに ``QToolTip`` 断片を連結する。

    Args:
        lt: 一覧テーマ。
        card_bg: ボタン背景。``None`` のとき ``lt.card_bg``。

    Returns:
        str: アイコンボタン＋ツールチップ色の連結スタイル。
    """
    return list_card_detail_icon_button_qss(
        lt, card_bg=card_bg
    ) + tooltip_chrome_qss_fragment(dark=meeting_list_ui_is_dark(lt))


def list_summary_card_delete_button_qss(
    lt: MeetingListTheme, *, card_bg: str | None = None
) -> str:
    """一覧カード「削除」ボタン用 QSS ＋ツールチップ断片。

    Args:
        lt: 一覧テーマ（ホバー色計算・ダーク判定に使用）。
        card_bg: ボタン背景。``None`` のとき ``lt.card_bg``。

    Returns:
        str: 削除ボタン＋ツールチップ色の連結スタイル。
    """
    bg = lt.card_bg if card_bg is None else card_bg
    hover_bg = card_delete_btn_hover_bg(bg)
    base = f"""
        QPushButton {{
            background-color: {bg};
            border: none;
            border-radius: 8px;
            padding: 5px;
            min-width: 32px;
            min-height: 32px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            border: none;
        }}
    """
    return base + tooltip_chrome_qss_fragment(dark=meeting_list_ui_is_dark(lt))


def transparent_background_qss() -> str:
    """汎用透明背景（プレースホルダ ``QWidget`` 等）。

    Returns:
        str: ``background: transparent;`` のみ。
    """
    return "background: transparent;"


# =============================================================================
# 商談詳細タブ
# =============================================================================


def meeting_detail_tab_hint_label_qss(
    hint_color: str, *, left_inset_px: int = 10
) -> str:
    """要約／文字起こしタブ先頭のヒント ``QLabel`` 用 QSS。

    Args:
        hint_color: ヒント文字色。
        left_inset_px: 左インデント（ピクセル）。

    Returns:
        str: 15px・左パディング付きの断片。
    """
    return f"color: {hint_color}; font-size: 15px; " f"padding-left: {left_inset_px}px;"


def meeting_detail_shell_background_qss(background: str) -> str:
    """タブシェル ``QWidget`` の単色背景。

    Args:
        background: CSS 背景色。

    Returns:
        str: ``background-color`` のみの断片。
    """
    return f"background-color: {background};"


def meeting_detail_meta_label_qss(meta_color: str) -> str:
    """詳細ヘッダ中央のメタ ``QLabel`` 用 QSS。

    Args:
        meta_color: メタ文字色。

    Returns:
        str: 17px の断片。
    """
    return f"color: {meta_color}; font-size: 17px;"


def meeting_detail_transcript_row_frame_qss(row_bg: str, row_border: str) -> str:
    """文字起こし 1 行の ``QFrame`` 用 QSS。

    Args:
        row_bg: 行背景色。
        row_border: 行枠色。

    Returns:
        str: 角丸 8px のフレームスタイル。
    """
    return f"""
            QFrame {{
                background-color: {row_bg};
                border: 1px solid {row_border};
                border-radius: 8px;
            }}
            """


def meeting_detail_transcript_ts_label_qss(ts_color: str) -> str:
    """文字起こし行の時刻 ``QLabel`` 用 QSS。

    Args:
        ts_color: 時刻文字色。

    Returns:
        str: 太字・最小幅付きの断片。
    """
    return f"color: {ts_color}; font-size: 15px; font-weight: 700; min-width: 72px;"


def meeting_detail_transcript_body_label_qss(body_color: str) -> str:
    """文字起こし行の本文 ``QLabel`` 用 QSS。

    Args:
        body_color: 本文文字色。

    Returns:
        str: 15px の断片。
    """
    return f"color: {body_color}; font-size: 15px;"


# =============================================================================
# 録音 HUD
# =============================================================================


def recording_control_glyph_button_qss() -> str:
    """録音 HUD の円／角丸グリフ ``QPushButton``（枠なし透明）。

    Returns:
        str: パディング 0・フォーカスリング無効化を含む断片。
    """
    return """
            QPushButton { border: none; background: transparent; padding: 0px; }
            QPushButton:focus { outline: none; }
            """


def recording_hud_time_label_qss(color: str) -> str:
    """録音 HUD の経過時刻 ``QLabel`` 用 QSS。

    Args:
        color: 文字色。

    Returns:
        str: ``color`` のみ指定した断片。
    """
    return f"color: {color};"


def recording_hud_rec_led_on_qss() -> str:
    """録音 LED 点灯（強い赤）。

    Returns:
        str: 小型角丸の赤塗り ``QLabel`` 向け断片。
    """
    return """
            QLabel {
                background-color: #e53935;
                border-radius: 6px;
            }
            """


def recording_hud_rec_led_dim_qss() -> str:
    """録音 LED 点滅用の弱い赤（半透明）。

    Returns:
        str: 小型角丸の薄い赤 ``QLabel`` 向け断片。
    """
    return """
            QLabel {
                background-color: rgba(180, 40, 40, 0.55);
                border-radius: 6px;
            }
            """


# =============================================================================
# Record / Stop アクションボタン
# =============================================================================


def _record_action_button_disabled_qss() -> str:
    """Record/Stop ボタン無効時のグレー塗り（録音不可・処理待ちなど）。

    Returns:
        str: ``:disabled`` および無効時ホバー／押下を固定する断片。
    """
    return """
    QPushButton:disabled {
        background-color: #9e9e9e;
        border: 2px solid #bdbdbd;
    }
    QPushButton:disabled:hover, QPushButton:disabled:pressed {
        background-color: #9e9e9e;
        border: 2px solid #bdbdbd;
    }
    """


def record_action_button_qss(*, recording: bool) -> str:
    """録音 HUD／一覧共通の Record / Stop ボタン用 QSS を返す。

    ダーク HUD とライト一覧の両方で視認性の高い赤塗り＋縁取りにする。
    グリフは ``setIcon`` の白アイコンに任せ、``color`` は付けない
    （ツールチップ色の伝播を避ける）。

    Args:
        recording: 録音中（Stop 表示）なら ``True``。

    Returns:
        str: ``QPushButton`` 向けスタイルシート。
    """
    base = """
    QPushButton {
        padding: 6px;
        min-width: 34px;
        min-height: 30px;
        max-height: 32px;
        border-radius: 8px;
    }
    QPushButton:focus {
        outline: none;
    }
    """
    disabled = _record_action_button_disabled_qss()
    if recording:
        return base + """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #ff5252, stop:1 #c62828);
        border: 2px solid rgba(255, 255, 255, 0.95);
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #ff9e94, stop:1 #e53935);
        border: 2px solid #ffffff;
    }
    QPushButton:pressed {
        background: #b71c1c;
        border: 2px solid #ffcdd2;
    }
    """ + disabled
    return base + """
    QPushButton {
        background-color: #d32f2f;
        border: 2px solid rgba(255, 255, 255, 0.9);
    }
    QPushButton:hover {
        background-color: #ff7043;
        border: 2px solid #ffffff;
    }
    QPushButton:pressed {
        background-color: #b71c1c;
        border: 2px solid #ffecb3;
    }
    """ + disabled


# 後方互換: 待機時（未録音）の Record ボタン QSS のみ。
RECORD_BUTTON_QSS: str = record_action_button_qss(recording=False)
