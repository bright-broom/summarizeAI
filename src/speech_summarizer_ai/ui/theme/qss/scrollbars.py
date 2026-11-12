"""オーバーレイ風（ボタン無し・角丸グリップ）のスクロールバー QSS。

一覧 ``MeetingSummaryListWindow`` のカード列用 ``QScrollArea`` と、詳細タブ内の
``QTextEdit`` など、複数の ``QScrollBar`` に対して同系統のルックを適用する。
"""

from __future__ import annotations


def _handle_colors(*, dark: bool) -> tuple[str, str, str]:
    """オーバーレイ風スクロールバーのグリップ色（通常・ホバー・押下）。

    Args:
        dark: ダーク面（明るい半透明グリップ）なら ``True``。ライト面では暗い半透明。

    Returns:
        tuple[str, str, str]: ``(handle, handle_hover, handle_pressed)`` の CSS 色文字列。
    """
    if dark:
        return (
            "rgba(255, 255, 255, 0.26)",
            "rgba(255, 255, 255, 0.40)",
            "rgba(255, 255, 255, 0.52)",
        )
    return (
        "rgba(0, 0, 0, 0.20)",
        "rgba(0, 0, 0, 0.32)",
        "rgba(0, 0, 0, 0.44)",
    )


def list_scroll_area_qss(scroll_bg: str, *, dark: bool) -> str:
    """一覧用 ``QScrollArea`` とオーバーレイ風スクロールバーの QSS を生成する。

    Args:
        scroll_bg: スクロールエリア背景色。
        dark: ダークテーマかどうか（グリップのコントラストに使用）。

    Returns:
        str: 適用するスタイルシート文字列。
    """
    handle, handle_hover, handle_pressed = _handle_colors(dark=dark)
    return f"""
    QScrollArea {{
        background-color: {scroll_bg};
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 16px;
        margin: 6px 2px 6px 0;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background-color: {handle};
        border-radius: 8px;
        min-height: 40px;
        margin: 3px 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {handle_hover};
    }}
    QScrollBar::handle:vertical:pressed {{
        background-color: {handle_pressed};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: transparent;
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 16px;
        margin: 0 6px 2px 6px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {handle};
        border-radius: 8px;
        min-width: 40px;
        margin: 4px 3px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {handle_hover};
    }}
    QScrollBar::handle:horizontal:pressed {{
        background-color: {handle_pressed};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        border: none;
        background: transparent;
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    """


def scroll_area_overlay_qss(scroll_bg: str, *, dark: bool) -> str:
    """一覧 ``MeetingSummaryListWindow`` のカード列と同型のスクロール領域＋スクロールバー用 QSS。

    Args:
        scroll_bg: ``QScrollArea`` 背景色。
        dark: グリップのトーン（一覧のダーク／ライトと一致）。

    Returns:
        str: ``list_scroll_area_qss`` と同じ構造のスタイルシート。
    """
    return list_scroll_area_qss(scroll_bg, dark=dark)


def nested_scrollbar_overlay_qss(container_selector: str, *, dark: bool) -> str:
    """``container_selector`` 配下の ``QScrollBar`` を一覧と同型のオーバーレイ風にする。

    例: ``"QTextEdit"`` で要約 ``QTextEdit`` のスクロールバーに連結して使う。

    Args:
        container_selector: 子孫セレクタの親（例 ``QTextEdit``）。
        dark: グリップのトーン。

    Returns:
        str: 連結用のスクロールバー QSS 断片。
    """
    handle, handle_hover, handle_pressed = _handle_colors(dark=dark)
    p = container_selector
    return f"""
    {p} QScrollBar:vertical {{
        background: transparent;
        width: 16px;
        margin: 6px 2px 6px 0;
        border: none;
    }}
    {p} QScrollBar::handle:vertical {{
        background-color: {handle};
        border-radius: 8px;
        min-height: 40px;
        margin: 3px 4px;
    }}
    {p} QScrollBar::handle:vertical:hover {{
        background-color: {handle_hover};
    }}
    {p} QScrollBar::handle:vertical:pressed {{
        background-color: {handle_pressed};
    }}
    {p} QScrollBar::add-line:vertical, {p} QScrollBar::sub-line:vertical {{
        border: none;
        background: transparent;
        height: 0px;
    }}
    {p} QScrollBar::add-page:vertical, {p} QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    {p} QScrollBar:horizontal {{
        background: transparent;
        height: 16px;
        margin: 0 6px 2px 6px;
        border: none;
    }}
    {p} QScrollBar::handle:horizontal {{
        background-color: {handle};
        border-radius: 8px;
        min-width: 40px;
        margin: 4px 3px;
    }}
    {p} QScrollBar::handle:horizontal:hover {{
        background-color: {handle_hover};
    }}
    {p} QScrollBar::handle:horizontal:pressed {{
        background-color: {handle_pressed};
    }}
    {p} QScrollBar::add-line:horizontal, {p} QScrollBar::sub-line:horizontal {{
        border: none;
        background: transparent;
        width: 0px;
    }}
    {p} QScrollBar::add-page:horizontal, {p} QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    """
