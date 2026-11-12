"""一覧・詳細・HUD 用アイコン。Qt 標準／テーマアイコンは使わず、自前描画で見た目を統一する。"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

_SZ = 24
# 詳細アイコンだけ viewBox 周りの余白を詰め、同一 24×24 内でグリフを大きく見せる（ボタンサイズは変えない）
# 既定 _filled_paths_icon の 1.15 より小さいほど拡大（0 に近いほどキャンバスいっぱい）
_VIEW_DETAIL_ICON_EDGE_PAD = 0.08

# delete-icon.svg（viewBox 0 0 105.16 122.88）の単一路径
_DELETE_ICON_PATH_D = "M11.17,37.16H94.65a8.4,8.4,0,0,1,2,.16,5.93,5.93,0,0,1,2.88,1.56,5.43,5.43,0,0,1,1.64,3.34,7.65,7.65,0,0,1-.06,1.44L94,117.31v0l0,.13,0,.28v0a7.06,7.06,0,0,1-.2.9v0l0,.06v0a5.89,5.89,0,0,1-5.47,4.07H17.32a6.17,6.17,0,0,1-1.25-.19,6.17,6.17,0,0,1-1.16-.48h0a6.18,6.18,0,0,1-3.08-4.88l-7-73.49a7.69,7.69,0,0,1-.06-1.66,5.37,5.37,0,0,1,1.63-3.29,6,6,0,0,1,3-1.58,8.94,8.94,0,0,1,1.79-.13ZM5.65,8.8H37.12V6h0a2.44,2.44,0,0,1,0-.27,6,6,0,0,1,1.76-4h0A6,6,0,0,1,43.09,0H62.46l.3,0a6,6,0,0,1,5.7,6V6h0V8.8h32l.39,0a4.7,4.7,0,0,1,4.31,4.43c0,.18,0,.32,0,.5v9.86a2.59,2.59,0,0,1-2.59,2.59H2.59A2.59,2.59,0,0,1,0,23.62V13.53H0a1.56,1.56,0,0,1,0-.31v0A4.72,4.72,0,0,1,3.88,8.88,10.4,10.4,0,0,1,5.65,8.8Zm42.1,52.7a4.77,4.77,0,0,1,9.49,0v37a4.77,4.77,0,0,1-9.49,0v-37Zm23.73-.2a4.58,4.58,0,0,1,5-4.06,4.47,4.47,0,0,1,4.51,4.46l-2,37a4.57,4.57,0,0,1-5,4.06,4.47,4.47,0,0,1-4.51-4.46l2-37ZM25,61.7a4.46,4.46,0,0,1,4.5-4.46,4.58,4.58,0,0,1,5,4.06l2,37a4.47,4.47,0,0,1-4.51,4.46,4.57,4.57,0,0,1-5-4.06l-2-37Z"

# return-23.svg（viewBox 0 0 1024 1024）— ファイルに依存せず埋め込み
_BACK_RETURN_23_PATH_D = (
    "M143.248541 426.443415c-5.469572 5.469572-14.541181 18.715247-14.541181 31.422663 "
    "0 8.300037 3.391237 20.067035 14.326287 31.006178l270.0239 291.62487c5.469572 5.469572 "
    "17.599843 15.277962 33.701566 5.999644 10.505261-6.053879 10.044774-25.914206 "
    "10.044774-31.383778L456.803887 594.57467c180.453908 0 349.971743 131.241067 "
    "382.78201 300.755832 27.341718-27.339672 54.682413-103.896278 54.682413-164.048263 "
    "0-224.199225-213.265198-410.119635-437.464423-410.119635L456.803887 162.579819c0-10.93505 "
    "0.106424-21.11797-12.56313-29.986965-13.422707-9.397021-29.252231-4.396123-40.191374 "
    "6.538927L143.248541 426.443415z"
)

# curved-arrow-back-icon.svg（viewBox 0 0 500 511.61）
_BACK_CURVED_PATH_D = (
    "m234.04 148.39-15.5 101.27c45.53-4.54 96.06-15.77 138.72-45.89 47.72-33.69 "
    "86.31-91.72 98.25-191.8.87-7.43 7.62-12.75 15.06-11.87 5.73.68 10.21 4.85 "
    "11.55 10.13 10.87 32.61 16.46 63.43 17.63 92.35 3.27 79.4-26.39 144.21-70.18 "
    "193.61-43.36 48.92-100.66 82.64-153.32 100.33-20.18 6.79-39.8 11.27-57.77 "
    "13.36l15.44 85.83c1.31 7.33-3.57 14.37-10.91 15.69-4.07.72-8.04-.46-11-2.9"
    "L4.91 337.19c-5.76-4.76-6.57-13.32-1.8-19.08l1.54-1.58 207.06-180.39c5.64-4.92 "
    "14.22-4.32 19.14 1.32 2.72 3.12 3.75 7.13 3.19 10.93z"
)

# next-icon.svg（viewBox 0 0 122.88 122.88）。前へは同パスを viewBox 中心で 180° 回転。
_NEXT_NAV_ICON_PATH_D = (
    "M37.95,4.66C45.19,1.66,53.13,0,61.44,0c16.96,0,32.33,6.88,43.44,18c5.66,5.66,10.22,12.43,13.34,19.95 "
    "c3,7.24,4.66,15.18,4.66,23.49c0,16.96-6.88,32.33-18,43.44c-5.66,5.66-12.43,10.22-19.95,13.34c-7.24,3-15.18,4.66-23.49,4.66 "
    "c-8.31,0-16.25-1.66-23.49-4.66c-7.53-3.12-14.29-7.68-19.95-13.34C12.34,99.22,7.77,92.46,4.66,84.93C1.66,77.69,0,69.75,0,61.44 "
    "c0-8.31,1.66-16.25,4.66-23.49C7.77,30.42,12.34,23.66,18,18C23.65,12.34,30.42,7.77,37.95,4.66L37.95,4.66z M50,47.13 "
    "c-2.48-2.52-2.45-6.58,0.08-9.05c2.52-2.48,6.58-2.45,9.05,0.08L77.8,57.13c2.45,2.5,2.45,6.49,0,8.98L59.49,84.72 "
    "c-2.48,2.52-6.53,2.55-9.05,0.08c-2.52-2.48-2.55-6.53-0.08-9.05l13.9-14.13L50,47.13L50,47.13z M42.86,16.55 "
    "c-5.93,2.46-11.28,6.07-15.76,10.55c-4.48,4.48-8.09,9.83-10.55,15.76c-2.37,5.71-3.67,11.99-3.67,18.58 "
    "c0,6.59,1.31,12.86,3.67,18.58c2.46,5.93,6.07,11.28,10.55,15.76c4.48,4.48,9.83,8.09,15.76,10.55c5.72,2.37,11.99,3.67,18.58,3.67 "
    "c6.59,0,12.86-1.31,18.58-3.67c5.93-2.46,11.28-6.07,15.76-10.55c4.48-4.48,8.09-9.82,10.55-15.76c2.37-5.71,3.67-11.99,3.67-18.58 "
    "c0-6.59-1.31-12.86-3.67-18.58c-2.46-5.93-6.07-11.28-10.55-15.76c-4.48-4.48-9.83-8.09-15.76-10.55 "
    "c-5.71-2.37-11.99-3.67-18.58-3.67S48.58,14.19,42.86,16.55L42.86,16.55z"
)

# noun-detail-3883520.svg（元 viewBox 0 0 100 125）— クレジット text は除き viewBox は 100×100 で切り出し
_NOUN_DETAIL_3883520_PATHS = (
    "M66.8,55.5c1.2,0,2.3,0.1,3.5,0.3V23.1H52.4c-1.5,0-2.6-1.2-2.6-2.6V2.5H14.2c-1.5,0-2.6,1.2-2.6,2.6v70.3     c0,1.5,1.2,2.6,2.6,2.6h32.5c-0.1-0.7-0.1-1.4-0.1-2.2C46.5,64.7,55.6,55.5,66.8,55.5z M26.1,17.8h12.8c1.5,0,2.6,1.2,2.6,2.6     c0,1.5-1.2,2.6-2.6,2.6H26.1c-1.5,0-2.6-1.2-2.6-2.6C23.5,19,24.7,17.8,26.1,17.8z M26.1,31.8h29.6c1.5,0,2.6,1.2,2.6,2.6     S57.2,37,55.7,37H26.1c-1.5,0-2.6-1.2-2.6-2.6S24.7,31.8,26.1,31.8z M26.1,45.8h29.6c1.5,0,2.6,1.2,2.6,2.6S57.2,51,55.7,51H26.1     c-1.5,0-2.6-1.2-2.6-2.6S24.7,45.8,26.1,45.8z M40,65H26.1c-1.5,0-2.6-1.2-2.6-2.6c0-1.4,1.2-2.6,2.6-2.6H40     c1.5,0,2.6,1.2,2.6,2.6C42.6,63.8,41.5,65,40,65z"
    "M69.5,17.3l-14-14C55.4,3.1,55.2,3,55,2.9v15h15C69.8,17.6,69.7,17.4,69.5,17.3z",
    "M87.4,91.8l-8.1-7.5c1.6-2.4,2.6-5.3,2.6-8.5c0-8.3-6.7-15.1-15.1-15.1c-8.3,0-15.1,6.7-15.1,15.1s6.7,15.1,15.1,15.1     c3.1,0,6-1,8.5-2.6l7.5,8.1c0.1,0.1,0.1,0.1,0.2,0.2c1.3,1.2,3.4,1.1,4.6-0.2C88.8,95.1,88.7,93,87.4,91.8z M73.2,78.5h-3.8v3.8     c0,1.4-1.2,2.6-2.6,2.6s-2.6-1.2-2.6-2.6v-3.8h-3.8c-1.5,0-2.6-1.2-2.6-2.6s1.2-2.6,2.6-2.6h3.8v-3.8c0-1.4,1.2-2.6,2.6-2.6     s2.6,1.2,2.6,2.6v3.8h3.8c1.5,0,2.6,1.2,2.6,2.6S74.7,78.5,73.2,78.5z",
)
_LINE = 2.0


def _canvas_px(sz: int) -> QPixmap:
    """透明で正方形の ``QPixmap`` を生成する。

    Args:
        sz: 辺のピクセル数。

    Returns:
        QPixmap: 透明塗りの ``sz × sz``。
    """
    p = QPixmap(sz, sz)
    p.fill(Qt.GlobalColor.transparent)
    return p


def _canvas() -> QPixmap:
    """既定サイズ（``_SZ``）の透明キャンバスを返す。

    Returns:
        QPixmap: ``_SZ × _SZ`` の透明ピクスマップ。
    """
    return _canvas_px(_SZ)


def _pen(color: QColor, width: float = _LINE) -> QPen:
    """線端・接合を丸めた ``QPen`` を返す。

    Args:
        color: 線色。
        width: 線幅。

    Returns:
        QPen: ラウンドキャップ／ジョインのペン。
    """
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


# --- 一覧カード（明るい背景・線画） ---


def icon_view_detail(
    widget: QWidget | None = None, *, color: QColor | None = None
) -> QIcon:
    """「詳細を開く」用の塗りつぶしアイコン（文書＋虫眼鏡のシルエット）。

    埋め込み SVG パスは noun-detail 系。``_VIEW_DETAIL_ICON_EDGE_PAD`` で 24×24 内のグリフだけ拡大する。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略または無効時はスレート既定色。一覧カードではテキスト色を渡す。

    Returns:
        QIcon: ``_SZ`` ベースのラスタアイコン。
    """
    del widget  # API 互換のため受け取るのみ
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    return _filled_paths_icon(
        100.0,
        100.0,
        _NOUN_DETAIL_3883520_PATHS,
        c,
        edge_pad=_VIEW_DETAIL_ICON_EDGE_PAD,
    )


def icon_delete(widget: QWidget | None = None, *, color: QColor | None = None) -> QIcon:
    """「削除」用のゴミ箱シルエット（delete-icon.svg 相当）。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時はスレート既定色。

    Returns:
        QIcon: SVG レンダー、失敗時は簡易フォールバック描画。
    """
    del widget
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    fill = c.name(QColor.NameFormat.HexRgb)
    svg = QByteArray(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 105.16 122.88">'
            f'<path fill="{fill}" fill-rule="evenodd" d="{_DELETE_ICON_PATH_D}"/>'
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg)
    pix = _canvas()
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    vb_w, vb_h = 105.16, 122.88
    _pad = 1.15
    usable = _SZ - 2 * _pad
    s = usable / max(vb_w, vb_h)
    w_draw = vb_w * s
    h_draw = vb_h * s
    ox = (_SZ - w_draw) / 2
    oy = (_SZ - h_draw) / 2
    if renderer.isValid():
        renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    else:
        p.setPen(_pen(c, 1.85))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(6.5, 8.5, 11, 10), 1.8, 1.8)
        p.drawLine(QPointF(8, 11.5), QPointF(16, 11.5))
        p.drawLine(QPointF(9.5, 6), QPointF(9.5, 8.5))
        p.drawLine(QPointF(14.5, 6), QPointF(14.5, 8.5))
        lid = QPainterPath()
        lid.moveTo(QPointF(5, 8.5))
        lid.lineTo(QPointF(7.5, 6.5))
        lid.lineTo(QPointF(16.5, 6.5))
        lid.lineTo(QPointF(19, 8.5))
        p.drawPath(lid)
    p.end()
    return QIcon(pix)


# search-icon.svg（viewBox 0 0 122.879 119.799）
_SEARCH_ICON_PATH_D = (
    "M49.988,0h0.016v0.007C63.803,0.011,76.298,5.608,85.34,14.652c9.027,9.031,14.619,21.515,14.628,35.303h0.007v0.033v0.04 "
    "h-0.007c-0.005,5.557-0.917,10.905-2.594,15.892c-0.281,0.837-0.575,1.641-0.877,2.409v0.007c-1.446,3.66-3.315,7.12-5.547,10.307 "
    "l29.082,26.139l0.018,0.016l0.157,0.146l0.011,0.011c1.642,1.563,2.536,3.656,2.649,5.78c0.11,2.1-0.543,4.248-1.979,5.971 "
    "l-0.011,0.016l-0.175,0.203l-0.035,0.035l-0.146,0.16l-0.016,0.021c-1.565,1.642-3.654,2.534-5.78,2.646 "
    "c-2.097,0.111-4.247-0.54-5.971-1.978l-0.015-0.011l-0.204-0.175l-0.029-0.024L78.761,90.865c-0.88,0.62-1.778,1.209-2.687,1.765 "
    "c-1.233,0.755-2.51,1.466-3.813,2.115c-6.699,3.342-14.269,5.222-22.272,5.222v0.007h-0.016v-0.007 "
    "c-13.799-0.004-26.296-5.601-35.338-14.645C5.605,76.291,0.016,63.805,0.007,50.021H0v-0.033v-0.016h0.007 "
    "c0.004-13.799,5.601-26.296,14.645-35.338C23.683,5.608,36.167,0.016,49.955,0.007V0H49.988L49.988,0z "
    "M50.004,11.21v0.007h-0.016 h-0.033V11.21c-10.686,0.007-20.372,4.35-27.384,11.359C15.56,29.578,11.213,39.274,11.21,49.973h0.007v0.016v0.033H11.21 "
    "c0.007,10.686,4.347,20.367,11.359,27.381c7.009,7.012,16.705,11.359,27.403,11.361v-0.007h0.016h0.033v0.007 "
    "c10.686-0.007,20.368-4.348,27.382-11.359c7.011-7.009,11.358-16.702,11.36-27.4h-0.006v-0.016v-0.033h0.006 "
    "c-0.006-10.686-4.35-20.372-11.358-27.384C70.396,15.56,60.703,11.213,50.004,11.21L50.004,11.21z"
)


def icon_search(widget: QWidget | None = None, *, color: QColor | None = None) -> QIcon:
    """「検索」用の虫眼鏡シルエット（search-icon.svg 相当）。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時はスレート既定色。

    Returns:
        QIcon: SVG レンダー、失敗時は円＋斜線のフォールバック。
    """
    del widget
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    fill = c.name(QColor.NameFormat.HexRgb)
    svg = QByteArray(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 122.879 119.799">'
            f'<path fill="{fill}" d="{_SEARCH_ICON_PATH_D}"/>'
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg)
    pix = _canvas()
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    vb_w, vb_h = 122.879, 119.799
    _pad = 1.15
    usable = _SZ - 2 * _pad
    s = usable / max(vb_w, vb_h)
    w_draw = vb_w * s
    h_draw = vb_h * s
    ox = (_SZ - w_draw) / 2
    oy = (_SZ - h_draw) / 2
    if renderer.isValid():
        renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    else:
        pen = _pen(c, 1.75)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(3, 3, 9, 9)
        p.drawLine(12, 12, 17, 17)
    p.end()
    return QIcon(pix)


# dark-theme-svgrepo-com.svg（Fluent ic_fluent_dark_theme_24_regular、viewBox 0 0 24 24）
_DARK_THEME_ICON_PATH_D = (
    "M12,22 C17.5228475,22 22,17.5228475 22,12 C22,6.4771525 17.5228475,2 12,2 "
    "C6.4771525,2 2,6.4771525 2,12 C2,17.5228475 6.4771525,22 12,22 Z "
    "M12,20.5 L12,3.5 C16.6944204,3.5 20.5,7.30557963 20.5,12 "
    "C20.5,16.6944204 16.6944204,20.5 12,20.5 Z"
)


def icon_dark_theme_toggle(
    widget: QWidget | None = None, *, color: QColor | None = None
) -> QIcon:
    """テーマ（ダーク／ライト）切替用の半月マークアイコン。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時はスレート既定色。

    Returns:
        QIcon: SVG レンダー、失敗時は円のフォールバック。
    """
    del widget
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    fill = c.name(QColor.NameFormat.HexRgb)
    svg = QByteArray(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            f'<path fill="{fill}" fill-rule="evenodd" d="{_DARK_THEME_ICON_PATH_D}"/>'
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg)
    pix = _canvas()
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    vb_w, vb_h = 24.0, 24.0
    _pad = 1.25
    usable = _SZ - 2 * _pad
    s = usable / max(vb_w, vb_h)
    w_draw = vb_w * s
    h_draw = vb_h * s
    ox = (_SZ - w_draw) / 2
    oy = (_SZ - h_draw) / 2
    if renderer.isValid():
        renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(4, 4, 16, 16))
    p.end()
    return QIcon(pix)


def _icon_nav_round_next_from_svg(
    color: QColor, *, previous: bool, canvas_px: int = _SZ
) -> QIcon:
    """丸枠付き「次へ／前へ」ナビ矢印（next-icon.svg ベース）。

    Args:
        color: 塗り色。
        previous: True のとき 180° 回転で「前へ」。
        canvas_px: 生成するピクスマップの辺ピクセル。

    Returns:
        QIcon: SVG が無効ならシェブロンフォールバック。
    """
    fill = color.name(QColor.NameFormat.HexRgb)
    path_el = f'<path fill="{fill}" d="{_NEXT_NAV_ICON_PATH_D}"/>'
    inner = (
        f'<g transform="rotate(180 61.44 61.44)">{path_el}</g>' if previous else path_el
    )
    svg = QByteArray(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 122.88 122.88">'
            f"{inner}"
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg)
    if not renderer.isValid():
        return _chevron_left_icon(color) if previous else _chevron_right_icon(color)
    pix = _canvas_px(canvas_px)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    vb_w = vb_h = 122.88
    _pad = 1.15
    usable = float(canvas_px) - 2 * _pad
    s = usable / max(vb_w, vb_h)
    w_draw = vb_w * s
    h_draw = vb_h * s
    ox = (float(canvas_px) - w_draw) / 2
    oy = (float(canvas_px) - h_draw) / 2
    renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    p.end()
    return QIcon(pix)


def _chevron_left_icon(color: QColor) -> QIcon:
    """左向きシェブロンをベクタ風に描画したアイコン。

    Args:
        color: 線色。

    Returns:
        QIcon: ``_SZ`` キャンバス。
    """
    pix = _canvas()
    g = QPainter(pix)
    g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    g.setPen(_pen(color, 2.25))
    g.drawLine(QPointF(15, 6), QPointF(8, 12))
    g.drawLine(QPointF(15, 18), QPointF(8, 12))
    g.end()
    return QIcon(pix)


def _chevron_right_icon(color: QColor) -> QIcon:
    """右向きシェブロンをベクタ風に描画したアイコン。

    Args:
        color: 線色。

    Returns:
        QIcon: ``_SZ`` キャンバス。
    """
    pix = _canvas()
    g = QPainter(pix)
    g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    g.setPen(_pen(color, 2.25))
    g.drawLine(QPointF(9, 6), QPointF(16, 12))
    g.drawLine(QPointF(9, 18), QPointF(16, 12))
    g.end()
    return QIcon(pix)


def _chevron_left(white: bool = True) -> QIcon:
    """白またはスレートの左シェブロン。

    Args:
        white: True のとき白、False のときスレート。

    Returns:
        QIcon: :func:`_chevron_left_icon` の結果。
    """
    c = QColor(255, 255, 255) if white else QColor(55, 71, 96)
    return _chevron_left_icon(c)


def _chevron_right(white: bool = True) -> QIcon:
    """白またはスレートの右シェブロン。

    Args:
        white: True のとき白、False のときスレート。

    Returns:
        QIcon: :func:`_chevron_right_icon` の結果。
    """
    c = QColor(255, 255, 255) if white else QColor(55, 71, 96)
    return _chevron_right_icon(c)


def _icon_back_return_23_svg(color: QColor, *, canvas_px: int = _SZ) -> QIcon | None:
    """return-23 形状の「戻る」矢印を SVG で描画する。

    Args:
        color: 塗り色。
        canvas_px: ピクスマップの辺ピクセル。

    Returns:
        QIcon | None: レンダー成功時はアイコン。SVG が無効なら ``None``。
    """
    fill = color.name(QColor.NameFormat.HexRgb)
    svg_bytes = QByteArray(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            f'<path fill="{fill}" d="{_BACK_RETURN_23_PATH_D}"/>'
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        return None
    pix = _canvas_px(canvas_px)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    vb_w, vb_h = 1024.0, 1024.0
    _pad = 1.15
    usable = float(canvas_px) - 2 * _pad
    s = usable / max(vb_w, vb_h)
    w_draw = vb_w * s
    h_draw = vb_h * s
    ox = (float(canvas_px) - w_draw) / 2
    oy = (float(canvas_px) - h_draw) / 2
    renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    p.end()
    return QIcon(pix)


def icon_back_to_list(
    widget: QWidget | None = None,
    *,
    color: QColor | None = None,
    canvas_px: int = _SZ,
) -> QIcon:
    """一覧へ戻る用アイコン（曲がり矢印／左矢印）。

    return-23 埋め込みを優先し、失敗時は curved-arrow SVG、さらに失敗時は左シェブロン。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時は白（ヘッダ向け）。
        canvas_px: 高 DPI 向けにピクスマップ辺を大きくできる。

    Returns:
        QIcon: いずれかの経路で生成したアイコン。
    """
    del widget
    c = QColor(255, 255, 255) if color is None or not color.isValid() else QColor(color)
    from_svg = _icon_back_return_23_svg(c, canvas_px=canvas_px)
    if from_svg is not None:
        return from_svg
    fill = c.name(QColor.NameFormat.HexRgb)
    svg = QByteArray(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 511.61">'
            f'<path fill="{fill}" fill-rule="nonzero" d="{_BACK_CURVED_PATH_D}"/>'
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg)
    if not renderer.isValid():
        return _chevron_left_icon(c)
    pix = _canvas_px(canvas_px)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    vb_w, vb_h = 500.0, 511.61
    _pad = 1.15
    usable = float(canvas_px) - 2 * _pad
    s = usable / max(vb_w, vb_h)
    w_draw = vb_w * s
    h_draw = vb_h * s
    ox = (float(canvas_px) - w_draw) / 2
    oy = (float(canvas_px) - h_draw) / 2
    renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    p.end()
    return QIcon(pix)


def icon_nav_previous(
    widget: QWidget | None = None,
    *,
    color: QColor | None = None,
    canvas_px: int = _SZ,
) -> QIcon:
    """前の商談へ（丸＋矢印、next-icon を 180° 回転）。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時は白。
        canvas_px: ピクスマップ辺ピクセル。

    Returns:
        QIcon: :func:`_icon_nav_round_next_from_svg`（``previous=True``）。
    """
    del widget
    c = QColor(255, 255, 255) if color is None or not color.isValid() else QColor(color)
    return _icon_nav_round_next_from_svg(c, previous=True, canvas_px=canvas_px)


def icon_nav_next(
    widget: QWidget | None = None,
    *,
    color: QColor | None = None,
    canvas_px: int = _SZ,
) -> QIcon:
    """次の商談へ（丸＋矢印、next-icon）。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時は白。
        canvas_px: ピクスマップ辺ピクセル。

    Returns:
        QIcon: :func:`_icon_nav_round_next_from_svg`（``previous=False``）。
    """
    del widget
    c = QColor(255, 255, 255) if color is None or not color.isValid() else QColor(color)
    return _icon_nav_round_next_from_svg(c, previous=False, canvas_px=canvas_px)


def merge_icon_normal_and_disabled_pixmaps(
    normal_mode_icon: QIcon,
    disabled_appearance_icon: QIcon,
    logical_side_px: int,
) -> QIcon:
    """有効／無効で見た目の違うピクスマップを 1 つの ``QIcon`` にまとめる。

    Args:
        normal_mode_icon: ``Normal`` モード用の元アイコン。
        disabled_appearance_icon: ``Disabled`` モードで表示したい見た目のアイコン。
        logical_side_px: 取り出すピクスマップの論理辺（ピクセル）。

    Returns:
        QIcon: 通常ピクスマップが取れなければ ``normal_mode_icon`` をそのまま返す。
    """
    sz = QSize(logical_side_px, logical_side_px)
    out = QIcon()
    pn = normal_mode_icon.pixmap(sz, QIcon.Mode.Normal, QIcon.State.Off)
    pd = disabled_appearance_icon.pixmap(sz, QIcon.Mode.Normal, QIcon.State.Off)
    if pn.isNull():
        return normal_mode_icon
    out.addPixmap(pn, QIcon.Mode.Normal, QIcon.State.Off)
    if not pd.isNull():
        out.addPixmap(pd, QIcon.Mode.Disabled, QIcon.State.Off)
    return out


# --- 要約タブ（edit-button-svgrepo-com.svg / save.svg） ---

# edit-button-svgrepo-com.svg（viewBox 0 0 494.936 494.936）
_EDIT_SUMMARY_PATHS = (
    "M389.844,182.85c-6.743,0-12.21,5.467-12.21,12.21v222.968c0,23.562-19.174,42.735-42.736,42.735H67.157 "
    "c-23.562,0-42.736-19.174-42.736-42.735V150.285c0-23.562,19.174-42.735,42.736-42.735h267.741c6.743,0,12.21-5.467,12.21-12.21 "
    "s-5.467-12.21-12.21-12.21H67.157C30.126,83.13,0,113.255,0,150.285v267.743c0,37.029,30.126,67.155,67.157,67.155h267.741 "
    "c37.03,0,67.156-30.126,67.156-67.155V195.061C402.054,188.318,396.587,182.85,389.844,182.85z",
    "M483.876,20.791c-14.72-14.72-38.669-14.714-53.377,0L221.352,229.944c-0.28,0.28-3.434,3.559-4.251,5.396l-28.963,65.069 "
    "c-2.057,4.619-1.056,10.027,2.521,13.6c2.337,2.336,5.461,3.576,8.639,3.576c1.675,0,3.362-0.346,4.96-1.057l65.07-28.963 "
    "c1.83-0.815,5.114-3.97,5.396-4.25L483.876,74.169c7.131-7.131,11.06-16.61,11.06-26.692 "
    "C494.936,37.396,491.007,27.915,483.876,20.791z M466.61,56.897L257.457,266.05c-0.035,0.036-0.055,0.078-0.089,0.107 "
    "l-33.989,15.131L238.51,247.3c0.03-0.036,0.071-0.055,0.107-0.09L447.765,38.058c5.038-5.039,13.819-5.033,18.846,0.005 "
    "c2.518,2.51,3.905,5.855,3.905,9.414C470.516,51.036,469.127,54.38,466.61,56.897z",
)

# save.svg（viewBox 0 0 24 24）
_SAVE_SUMMARY_PATHS = (
    "M17,20.75H7A2.75,2.75,0,0,1,4.25,18V6A2.75,2.75,0,0,1,7,3.25h7.5a.75.75,0,0,1,.53.22L19.53,8a.75.75,0,0,1,.22.53V18A2.75,2.75,0,0,1,17,20.75ZM7,4.75A1.25,1.25,0,0,0,5.75,6V18A1.25,1.25,0,0,0,7,19.25H17A1.25,1.25,0,0,0,18.25,18V8.81L14.19,4.75Z",
    "M16.75,20h-1.5V13.75H8.75V20H7.25V13.5A1.25,1.25,0,0,1,8.5,12.25h7a1.25,1.25,0,0,1,1.25,1.25Z",
    "M12.47,8.75H8.53a1.29,1.29,0,0,1-1.28-1.3V4h1.5V7.25h3.5V4h1.5V7.45A1.29,1.29,0,0,1,12.47,8.75Z",
)


def _filled_paths_icon(
    view_w: float,
    view_h: float,
    path_ds: tuple[str, ...],
    color: QColor,
    *,
    edge_pad: float = 1.15,
    canvas_px: int = _SZ,
) -> QIcon:
    """複数の塗り ``path`` から SVG を組み立て、正方形アイコンとしてラスタ化する。

    Args:
        view_w: SVG viewBox の幅。
        view_h: SVG viewBox の高さ。
        path_ds: ``d`` 属性の文字列タプル（複数パス）。
        color: 塗り色。
        edge_pad: キャンバス周辺の余白（大きいほどグリフが小さい）。
        canvas_px: 出力ピクスマップの辺ピクセル。

    Returns:
        QIcon: SVG 無効時は楕円フォールバック。
    """
    fill = color.name(QColor.NameFormat.HexRgb)
    body = "".join(f'<path fill="{fill}" d="{d}"/>' for d in path_ds)
    svg = QByteArray(
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w} {view_h}">'
            f"{body}"
            "</svg>"
        ).encode("utf-8")
    )
    renderer = QSvgRenderer(svg)
    cp = float(canvas_px)
    if not renderer.isValid():
        pix = _canvas_px(canvas_px)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        scale = cp / float(_SZ)
        p.drawEllipse(QRectF(4 * scale, 4 * scale, 16 * scale, 16 * scale))
        p.end()
        return QIcon(pix)
    pix = _canvas_px(canvas_px)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    usable = cp - 2 * edge_pad
    s = usable / max(view_w, view_h)
    w_draw = view_w * s
    h_draw = view_h * s
    ox = (cp - w_draw) / 2
    oy = (cp - h_draw) / 2
    renderer.render(p, QRectF(ox, oy, w_draw, h_draw))
    p.end()
    return QIcon(pix)


def icon_edit_summary(
    widget: QWidget | None = None,
    *,
    color: QColor | None = None,
    canvas_px: int = _SZ,
) -> QIcon:
    """要約編集ボタン用アイコン（ペン／ノートのシルエット）。

    ``edge_pad`` を大きめにし、同一ボタンサイズでグリフだけやや小さく見せる。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時はスレート既定色。
        canvas_px: 高解像度用の辺ピクセル。

    Returns:
        QIcon: :func:`_filled_paths_icon` 経由。
    """
    del widget
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    return _filled_paths_icon(
        494.936,
        494.936,
        _EDIT_SUMMARY_PATHS,
        c,
        edge_pad=4.9,
        canvas_px=canvas_px,
    )


def icon_save_summary(
    widget: QWidget | None = None,
    *,
    color: QColor | None = None,
    canvas_px: int = _SZ,
) -> QIcon:
    """要約保存ボタン用アイコン（フロッピー／保存記号）。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時はスレート既定色。
        canvas_px: 高解像度用の辺ピクセル。

    Returns:
        QIcon: :func:`_filled_paths_icon` 経由（viewBox 24×24、やや広めの ``edge_pad``）。
    """
    del widget
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    return _filled_paths_icon(
        24.0, 24.0, _SAVE_SUMMARY_PATHS, c, edge_pad=1.2, canvas_px=canvas_px
    )


# 報告（メガホン）・viewBox 611.998×611.998
_REPORT_MEGAPHONE_PATH_D = (
    "M586.355,182.317c-11.802-11.42-26.394-18.577-41.949-20.772V23.857c0-6.541-3.828-12.479-9.787-15.179"
    "c-5.959-2.703-12.944-1.665-17.865,2.646C414.567,100.896,227.792,122.439,202.741,124.96c-0.364-0.025-0.724-0.056-1.096-0.056"
    "l-90.516-0.015h-0.003c-0.258,0-0.515,0.006-0.771,0.017c-0.151-0.001-0.304-0.001-0.456-0.001l-0.489,0.003"
    "C48.051,125.945-1.025,180.521,0.016,246.563c0.493,31.404,12.161,60.895,32.854,83.042"
    "c21.034,22.508,48.937,34.903,78.572,34.903c0.546,0,23.391-0.013,23.391-0.013l55.369,190.359"
    "c0.142,0.489,0.304,0.965,0.489,1.432c5.823,17.345,17.904,31.592,34.111,40.193c10.408,5.523,21.788,8.33,33.272,8.329"
    "c6.779,0,13.598-0.979,20.269-2.953c17.973-5.318,32.888-17.266,41.999-33.643c8.927-16.048,11.312-34.593,6.748-52.334"
    "c-0.089-0.422-0.193-0.843-0.315-1.261l-39.778-136.765c69.632,14.518,166.001,43.54,229.755,99.424"
    "c3.1,2.717,7.023,4.132,10.989,4.132c2.33,0,4.673-0.487,6.876-1.486c5.96-2.701,9.787-8.639,9.787-15.18V326.553"
    "c38.631-5.366,68.256-41.135,67.582-83.81C611.627,219.761,602.285,197.736,586.355,182.317z M268.888,569.892"
    "c-19.572,5.794-40.564-5.315-46.779-24.767c-0.051-0.164-0.106-0.325-0.162-0.485l-52.398-180.145h31.398"
    "c3.426,0.296,22.026,2.019,49.35,6.514l44.226,152.059c0.046,0.194,0.094,0.386,0.146,0.578"
    "C300.03,543.354,288.466,564.099,268.888,569.892z M123.023,158.223l61.952,0.011v172.93h-61.952V158.223z M89.691,327.691"
    "c-31.954-10.411-55.741-43.064-56.348-81.651c-0.629-39.91,23.353-73.991,56.348-84.478V327.691z M511.071,430.582"
    "c-47.283-33.111-109.453-59.344-185.378-78.172c-46.914-11.633-86.64-17.234-107.385-19.637V156.784"
    "c20.835-2.518,60.494-8.304,107.277-20.074c75.999-19.126,138.201-45.528,185.487-78.681V430.582z M544.405,292.656v-97.158"
    "c6.871,1.833,13.318,5.497,18.767,10.769c9.619,9.312,15.266,22.799,15.488,37C579.038,267.197,564.279,287.495,544.405,292.656z"
)
_REPORT_MEGAPHONE_VIEW = 611.998


def icon_report(
    widget: QWidget | None = None,
    *,
    color: QColor | None = None,
    canvas_px: int = _SZ,
) -> QIcon:
    """詳細ヘッダ報告ボタン用のメガホンシルエット。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時はスレート既定色。
        canvas_px: 高解像度用の辺ピクセル。

    Returns:
        QIcon: :func:`_filled_paths_icon` 経由。
    """
    del widget
    c = QColor(55, 71, 96) if color is None or not color.isValid() else QColor(color)
    v = float(_REPORT_MEGAPHONE_VIEW)
    return _filled_paths_icon(
        v,
        v,
        (_REPORT_MEGAPHONE_PATH_D,),
        c,
        edge_pad=1.2,
        canvas_px=canvas_px,
    )


# --- 一覧ヘッダ録音（赤背景の白アイコン） ---


def icon_record_start(
    widget: QWidget | None = None, *, color: QColor | None = None
) -> QIcon:
    """録音開始（右向き三角）。

    Args:
        widget: API 互換用（未使用）。
        color: 塗り色。省略時は白。

    Returns:
        QIcon: ベクタ描画の三角。
    """
    del widget
    c = QColor(255, 255, 255) if color is None or not color.isValid() else QColor(color)
    pix = _canvas()
    g = QPainter(pix)
    g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    g.setPen(Qt.PenStyle.NoPen)
    g.setBrush(c)
    tri = QPolygonF(
        [
            QPointF(9, 7.5),
            QPointF(9, 16.5),
            QPointF(17.5, 12),
        ]
    )
    g.drawPolygon(tri)
    g.end()
    return QIcon(pix)


def icon_record_stop(
    widget: QWidget | None = None, *, color: QColor | None = None
) -> QIcon:
    """録音停止（角丸四角の枠線）。

    Args:
        widget: API 互換用（未使用）。
        color: 線色。省略時は白。

    Returns:
        QIcon: ストロークのみの角丸矩形。
    """
    del widget
    c = QColor(255, 255, 255) if color is None or not color.isValid() else QColor(color)
    pix = _canvas()
    g = QPainter(pix)
    g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    g.setPen(_pen(c, 2.4))
    g.setBrush(Qt.BrushStyle.NoBrush)
    g.drawRoundedRect(QRectF(7.5, 7.5, 9, 9), 1.8, 1.8)
    g.end()
    return QIcon(pix)


# --- HUD 終了 ---


def icon_window_close(
    widget: QWidget | None = None, *, color: QColor | None = None
) -> QIcon:
    """ウィンドウ閉じる（×印）。

    Args:
        widget: API 互換用（未使用）。
        color: 線色。省略時は白（HUD 向け）。

    Returns:
        QIcon: 対角線 2 本。
    """
    del widget
    c = QColor(255, 255, 255) if color is None or not color.isValid() else QColor(color)
    pix = _canvas()
    g = QPainter(pix)
    g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    g.setPen(_pen(c, 2.35))
    inset = 6.5
    g.drawLine(QPointF(inset, inset), QPointF(_SZ - inset, _SZ - inset))
    g.drawLine(QPointF(_SZ - inset, inset), QPointF(inset, _SZ - inset))
    g.end()
    return QIcon(pix)
