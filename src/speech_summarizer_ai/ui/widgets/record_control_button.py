"""録音開始（円）／停止（角丸）を描画するテキスト無しの ``QPushButton``。

録音 HUD のパネル右側に、閉じるボタンと同じ 28px のヒット領域で並ぶ。円・角丸は
内側に縮めて描画し、外周のスペースはホバー／押下ハイライト用に使う。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QPushButton, QWidget

from speech_summarizer_ai.ui.theme import recording_control_glyph_button_qss


class RecordControlButton(QPushButton):
    """録音開始（円）／停止（角丸）を描画するテキスト無しボタン。

    閉じるボタンと同じ 28px ヒット領域。円／角丸は内側に縮めて描画し、周囲は
    ホバー／押下ハイライトの余白として使う。``set_recording`` で表示を切り替え、
    ``set_hud_dark`` で外周の明色／暗色を切り替える。
    """

    _RED = QColor(0xE5, 0x39, 0x35)
    _BUTTON_SIZE = 28
    _GLYPH_MARGIN = 4.0
    _RED_CIRCLE_RADIUS_RATIO = 0.94
    _STOP_OUTER_CORNER_RATIO = 0.22
    _STOP_RED_INSET_RATIO = 0.03
    _HOVER_ROUNDRECT_CORNER_RATIO = 0.22

    def __init__(self, parent: QWidget | None = None) -> None:
        """ボタンを初期化する。

        Args:
            parent (QWidget | None): 親ウィジェット。省略時は ``None``。

        Returns:
            None: 固定サイズ・カーソル・スタイル・ホバー属性を設定する。
        """
        super().__init__(parent)
        self._recording = False
        self.setFixedSize(self._BUTTON_SIZE, self._BUTTON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(recording_control_glyph_button_qss())
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hud_dark = True

    def set_hud_dark(self, dark: bool) -> None:
        """HUD がダークかライトかに合わせ、グリフの外周色（白系／灰系）を切り替える。

        状態が変わったときだけ ``update`` する。

        Args:
            dark (bool): HUD がダークなら ``True``。

        Returns:
            None: 必要なら再描画をスケジュールする。
        """
        if self._hud_dark != dark:
            self._hud_dark = dark
            self.update()

    def set_recording(self, active: bool) -> None:
        """録音中 UI（停止アイコン）と待機 UI（録音アイコン）を切り替える。

        Args:
            active (bool): 録音中なら ``True``（停止アイコンを表示）。

        Returns:
            None: 状態が変わったときだけ再描画をスケジュールする。
        """
        if self._recording != active:
            self._recording = active
            self.update()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        """マウスが入ったときホバー表示のため再描画する。

        Args:
            event (QEnterEvent): Qt が渡す入域イベント。

        Returns:
            None: 基底の ``enterEvent`` に委譲する。
        """
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        """マウスが出たときホバー解除のため再描画する。

        Args:
            event (QEvent): Qt が渡す離脱イベント。

        Returns:
            None: 基底の ``leaveEvent`` に委譲する。
        """
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """録音／停止のグリフと、有効時のホバー／押下ハイライトを描画する。

        無効時は :meth:`_paint_glyph_disabled` に任せ、ハイライトは描かない。

        Args:
            event (QPaintEvent): Qt が渡すペイントイベント。

        Returns:
            None: ``QPainter`` でウィジェット全体を描画する。
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        full = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        side = min(full.width(), full.height())

        if not self.isEnabled():
            self._paint_glyph_disabled(p, full)
            return

        if self._hud_dark:
            hover_hi = QColor(255, 255, 255, 51)
            hover_lo = QColor(255, 255, 255, 31)
        else:
            hover_hi = QColor(0, 0, 0, 40)
            hover_lo = QColor(0, 0, 0, 26)
        if self._recording:
            hover_corner = side * self._HOVER_ROUNDRECT_CORNER_RATIO
            if self.isDown():
                p.setBrush(hover_hi)
                p.drawRoundedRect(full, hover_corner, hover_corner)
            elif self.underMouse():
                p.setBrush(hover_lo)
                p.drawRoundedRect(full, hover_corner, hover_corner)
        else:
            hit_r = side * 0.5
            if self.isDown():
                p.setBrush(hover_hi)
                p.drawRoundedRect(full, hit_r, hit_r)
            elif self.underMouse():
                p.setBrush(hover_lo)
                p.drawRoundedRect(full, hit_r, hit_r)

        r = full.adjusted(
            self._GLYPH_MARGIN,
            self._GLYPH_MARGIN,
            -self._GLYPH_MARGIN,
            -self._GLYPH_MARGIN,
        )
        if r.width() <= 0 or r.height() <= 0:
            return
        cx = r.center().x()
        cy = r.center().y()
        outer_r = min(r.width(), r.height()) * 0.5

        outer_idle = QColor(255, 255, 255) if self._hud_dark else QColor(38, 42, 50)
        outer_stop = QColor(255, 255, 255) if self._hud_dark else QColor(88, 92, 100)
        if not self._recording:
            p.setBrush(outer_idle)
            p.drawEllipse(QRectF(cx - outer_r, cy - outer_r, 2 * outer_r, 2 * outer_r))
            p.setBrush(self._RED)
            inner_r = outer_r * self._RED_CIRCLE_RADIUS_RATIO
            p.drawEllipse(QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r))
        else:
            w, h = r.width(), r.height()
            corner = min(w, h) * self._STOP_OUTER_CORNER_RATIO
            p.setBrush(outer_stop)
            p.drawRoundedRect(r, corner, corner)
            inset = min(w, h) * self._STOP_RED_INSET_RATIO
            inner = r.adjusted(inset, inset, -inset, -inset)
            if inner.width() > 0 and inner.height() > 0:
                inner_corner = max(1.0, corner - inset)
                p.setBrush(self._RED)
                p.drawRoundedRect(inner, inner_corner, inner_corner)

    def _paint_glyph_disabled(self, p: QPainter, full: QRectF) -> None:
        """無効時用にグレー系のグリフだけを描画する（ホバー／押下のハイライトなし）。

        Args:
            p (QPainter): このウィジェット向けに開始済みのペインタ。
            full (QRectF): ウィジェット全体の矩形（論理座標）。

        Returns:
            None: ``p`` に対して円または角丸矩形のグリフを描く。
        """
        r = full.adjusted(
            self._GLYPH_MARGIN,
            self._GLYPH_MARGIN,
            -self._GLYPH_MARGIN,
            -self._GLYPH_MARGIN,
        )
        if r.width() <= 0 or r.height() <= 0:
            return
        cx = r.center().x()
        cy = r.center().y()
        outer_r = min(r.width(), r.height()) * 0.5
        if self._hud_dark:
            ring = QColor(140, 140, 145)
            fill = QColor(110, 110, 115)
        else:
            ring = QColor(189, 189, 189)
            fill = QColor(158, 158, 158)
        if not self._recording:
            p.setBrush(ring)
            p.drawEllipse(QRectF(cx - outer_r, cy - outer_r, 2 * outer_r, 2 * outer_r))
            inner_r = outer_r * self._RED_CIRCLE_RADIUS_RATIO
            p.setBrush(fill)
            p.drawEllipse(QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r))
        else:
            w, h = r.width(), r.height()
            corner = min(w, h) * self._STOP_OUTER_CORNER_RATIO
            p.setBrush(ring)
            p.drawRoundedRect(r, corner, corner)
            inset = min(w, h) * self._STOP_RED_INSET_RATIO
            inner = r.adjusted(inset, inset, -inset, -inset)
            if inner.width() > 0 and inner.height() > 0:
                inner_corner = max(1.0, corner - inset)
                p.setBrush(fill)
                p.drawRoundedRect(inner, inner_corner, inner_corner)
