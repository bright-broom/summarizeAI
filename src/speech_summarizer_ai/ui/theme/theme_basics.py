"""テーマのプリミティブ値（検出・色計算ユーティリティ）。

``palette`` と ``qss`` の両方から参照される最下層のモジュール。
循環参照を避けるため、このモジュールは他のテーマモジュールに依存しない。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

# ``QSettings("ui/dark")`` 未保存時（初回起動）の既定ダークモード。
DEFAULT_UI_DARK_UNSAVED: bool = True


def dark_mode_preferred() -> bool:
    """ダークモード表示が望ましいかを判定する。

    Qt のカラースキームが設定されていればそれを優先し、未設定ならウィンドウパレットの明度から推測する。

    Returns:
        bool: ダークモード向けスタイルを使う場合 ``True``。
    """
    app = QGuiApplication.instance()
    if app is None:
        return False
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    bg = app.palette().color(QPalette.ColorRole.Window)
    return bg.lightness() < 128


def blend_icon_fg_toward_surface_for_disabled(
    base_fg: QColor,
    surface_bg: QColor,
    *,
    mix: float = 0.52,
) -> QColor:
    """アイコンボタン ``QIcon.Mode.Disabled`` 用に、前景を面の色へ寄せる。

    有効時とのコントラスト差をはっきりさせる。

    Args:
        base_fg: 有効時のアイコン前景色。
        surface_bg: ボタンまたはカードの背景色。
        mix: 背景色側の混合比 ``0``〜``1``。大きいほど無効時は面に近づく。

    Returns:
        QColor: ブレンド後の色（無効状態用）。
    """
    fg = QColor(base_fg)
    bg = QColor(surface_bg)
    if not fg.isValid():
        fg = QColor("#888888")
    if not bg.isValid():
        bg = QColor("#ffffff")
    m = max(0.0, min(1.0, mix))
    return QColor(
        round(fg.red() * (1 - m) + bg.red() * m),
        round(fg.green() * (1 - m) + bg.green() * m),
        round(fg.blue() * (1 - m) + bg.blue() * m),
    )


def summary_card_disabled_surface_bg(card_bg: str) -> str:
    """録音中・要約中など操作不可カードの面色（通常カードより判別しやすく）。

    Args:
        card_bg: 通常時のカード背景（CSS 文字列）。

    Returns:
        str: 無効時用の背景色（``#`` 形式）。入力が無効な色なら ``card_bg`` をそのまま返す。
    """
    c = QColor(card_bg)
    if not c.isValid():
        return card_bg
    if c.lightness() >= 245:
        return "#e6e8ed"
    if c.lightness() < 140:
        return c.darker(168).name(QColor.NameFormat.HexRgb)
    return c.darker(118).name(QColor.NameFormat.HexRgb)


def card_delete_btn_hover_bg(card_bg: str) -> str:
    """削除ボタン：ホバー時に背景へわずかに赤を混ぜる。

    Args:
        card_bg: 通常時のボタン背景に使うカード面色。

    Returns:
        str: ホバー時の背景色（``#`` 形式）。入力が無効な色なら ``card_bg``。
    """
    c = QColor(card_bg)
    if not c.isValid():
        return card_bg
    red = QColor(229, 57, 53)
    t = 0.28
    return QColor(
        round(c.red() * (1 - t) + red.red() * t),
        round(c.green() * (1 - t) + red.green() * t),
        round(c.blue() * (1 - t) + red.blue() * t),
    ).name(QColor.NameFormat.HexRgb)


def card_delete_btn_fg(card_text: str) -> QColor:
    """削除ボタンアイコン色：テキスト色にアクセント赤を混ぜる。

    Args:
        card_text: カード内の基準テキスト色（CSS 文字列）。

    Returns:
        QColor: アイコン用の混色。入力が無効なら濃いグレーを基準にする。
    """
    c = QColor(card_text)
    if not c.isValid():
        c = QColor("#333333")
    red = QColor(229, 57, 53)
    t = 0.34
    return QColor(
        round(c.red() * (1 - t) + red.red() * t),
        round(c.green() * (1 - t) + red.green() * t),
        round(c.blue() * (1 - t) + red.blue() * t),
    )


def list_card_detail_btn_hover_bg(card_bg: str) -> str:
    """一覧カード「詳細」と同系のホバー背景（詳細ヘッダの戻る等でも使用）。

    ライト面ではやや濃いグレー、ダーク面では白へ寄せたトーンにしてホバーをはっきり見せる。

    Args:
        card_bg: 通常時のボタン背景（カード面色など）。

    Returns:
        str: ホバー／押下に使う背景色（``#`` 形式）。入力が無効な色なら ``card_bg``。
    """
    c = QColor(card_bg)
    if not c.isValid():
        return card_bg
    lightness = c.lightness()
    w = QColor(255, 255, 255)
    if lightness >= 245:
        return "#c4cad6"
    t = 0.24 if lightness < 140 else 0.14
    return QColor(
        round(c.red() * (1 - t) + w.red() * t),
        round(c.green() * (1 - t) + w.green() * t),
        round(c.blue() * (1 - t) + w.blue() * t),
    ).name(QColor.NameFormat.HexRgb)


# 一覧ヘッダ録音ボタンの待機時（未録音）の赤面。
RECORD_ACTION_IDLE_FILL: QColor = QColor(0xD3, 0x2F, 0x2F)


def record_action_white_glyph_disabled_muted() -> QColor:
    """一覧ヘッダ録音ボタンの白グリフ ``Disabled`` 用。

    待機時の赤面 :data:`RECORD_ACTION_IDLE_FILL` へ寄せて、無効でも赤系に馴染ませる。

    Returns:
        QColor: 無効時アイコン色。
    """
    return blend_icon_fg_toward_surface_for_disabled(
        QColor(255, 255, 255), RECORD_ACTION_IDLE_FILL, mix=0.42
    )
