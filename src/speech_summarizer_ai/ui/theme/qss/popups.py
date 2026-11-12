"""``QToolTip`` / ``QMessageBox`` / STT モデル取得ダイアログ用の QSS 断片と
アプリ全体パレット適用のためのヘルパ。

システム配色だけではツールチップや確認ダイアログの文字が薄いグレーのまま
残ってしまうため、役割ごとに前景・背景を明示する。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def tooltip_chrome_qss_fragment(*, dark: bool) -> str:
    """``QToolTip`` 向けの QSS 断片を返す（アプリ／ボタン末尾で共有）。

    ``!important`` で、親子の ``QStyleSheetStyle`` マージ時に前景・背景だけが
    食い違う経路を抑える。

    Args:
        dark (bool): ダーク配色なら ``True``。

    Returns:
        str: ``QToolTip`` セレクタのみのスタイル断片。
    """
    if dark:
        return """
        QToolTip {
            color: #f2f2f5 !important;
            background-color: #2d2d32 !important;
            border: 1px solid #5a5a62;
            padding: 6px 8px;
        }
        """
    return """
        QToolTip {
            color: #1a1a1e !important;
            background-color: #ffffe8 !important;
            border: 1px solid #c8c8b8;
            padding: 6px 8px;
        }
        """


def _message_box_chrome_qss_fragment(*, dark: bool) -> str:
    """``QMessageBox`` 向けの QSS 断片を返す。

    ダイアログ本体・ラベル・ボタンの背景・前景・ホバー／押下をライト／ダークで切り替える。

    Args:
        dark (bool): ダーク配色なら ``True``。

    Returns:
        str: ``QMessageBox`` 系セレクタのスタイル断片。
    """
    if dark:
        return """
        QMessageBox {
            background-color: #2d2d32;
        }
        QMessageBox QLabel {
            color: #f2f2f5;
            background-color: transparent;
        }
        QMessageBox QPushButton {
            color: #f2f2f5;
            background-color: #3d3d44;
            border: 1px solid #6a6a72;
            border-radius: 4px;
            padding: 5px 18px;
            min-width: 72px;
        }
        QMessageBox QPushButton:hover {
            background-color: #5c5c66;
        }
        QMessageBox QPushButton:pressed {
            background-color: #35353a;
        }
        """
    return """
        QMessageBox {
            background-color: #ffffff;
        }
        QMessageBox QLabel {
            color: #1a1a1e;
            background-color: transparent;
        }
        QMessageBox QPushButton {
            color: #1a1a1e;
            background-color: #f5f5f5;
            border: 1px solid #c0c0c0;
            border-radius: 4px;
            padding: 5px 18px;
            min-width: 72px;
        }
        QMessageBox QPushButton:hover {
            background-color: #dcdcdc;
        }
        QMessageBox QPushButton:pressed {
            background-color: #e0e0e0;
        }
        """


def stt_model_setup_dialog_qss(*, dark: bool) -> str:
    """初回 STT モデル取得ダイアログ向けの QSS を返す（ライト／ダーク）。

    ``apply_application_popup_chrome`` と同系の文字色・背景色で揃える。

    Args:
        dark (bool): ダーク配色なら ``True``。

    Returns:
        str: ``QDialog``・``QLabel``・``QProgressBar`` 向けスタイル。
    """
    if dark:
        return """
        QDialog {
            background-color: #2d2d32;
        }
        QDialog QLabel {
            color: #f2f2f5;
            background-color: transparent;
        }
        QProgressBar {
            color: #f2f2f5;
            background-color: #3d3d44;
            border: 1px solid #5a5a62;
            border-radius: 4px;
            text-align: center;
            min-height: 20px;
        }
        QProgressBar::chunk {
            background-color: #4a90d9;
            border-radius: 3px;
        }
        """
    return """
        QDialog {
            background-color: #ffffff;
        }
        QDialog QLabel {
            color: #1a1a1e;
            background-color: transparent;
        }
        QProgressBar {
            color: #1a1a1e;
            background-color: #f0f0f0;
            border: 1px solid #c0c0c0;
            border-radius: 4px;
            text-align: center;
            min-height: 20px;
        }
        QProgressBar::chunk {
            background-color: #0078d4;
            border-radius: 3px;
        }
        """


def application_popup_chrome_qss(*, dark: bool) -> str:
    """``QApplication.setStyleSheet`` 向けに、ツールチップと ``QMessageBox`` を統一する QSS。

    OS がダークでもアプリをライトにした場合など、システム配色だけでは
    ツールチップ／確認ダイアログの文字が薄いグレーのままになることがあるため、
    役割ごとに前景・背景を明示する。

    Args:
        dark (bool): アプリのライト／ダークに合わせた配色を選ぶ。

    Returns:
        str: ``tooltip_chrome_qss_fragment`` と ``_message_box_chrome_qss_fragment`` を連結した文字列。
    """
    return tooltip_chrome_qss_fragment(dark=dark) + _message_box_chrome_qss_fragment(
        dark=dark
    )


def _apply_application_tooltip_palette(app: QApplication, *, dark: bool) -> None:
    """ネイティブ／パレット参照のツールチップ向けに ``ToolTipBase`` / ``ToolTipText`` を揃える。

    Args:
        app (QApplication): 実行中のアプリケーション。
        dark (bool): ダーク配色なら ``True``。

    Returns:
        None: 副作用として ``app`` のパレットを更新する。
    """
    p = app.palette()
    if dark:
        base = QColor(0x2D, 0x2D, 0x32)
        text = QColor(0xF2, 0xF2, 0xF5)
    else:
        base = QColor(0xFF, 0xFF, 0xE8)
        text = QColor(0x1A, 0x1A, 0x1E)
    for grp in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        p.setColor(grp, QPalette.ColorRole.ToolTipBase, base)
        p.setColor(grp, QPalette.ColorRole.ToolTipText, text)
    app.setPalette(p)


def apply_application_popup_chrome(*, dark: bool) -> None:
    """ツールチップとメッセージボックスを、指定のライト／ダークに合わせる（QSS ＋ アプリパレット）。

    ``QApplication`` が無い場合は何もしない。

    Args:
        dark (bool): アプリ UI のダークモードに合わせるなら ``True``。

    Returns:
        None: スタイルシートとツールチップ用パレットを適用する。
    """
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(application_popup_chrome_qss(dark=dark))
    _apply_application_tooltip_palette(app, dark=dark)
