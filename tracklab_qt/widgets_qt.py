"""Contrôles Qt de TrackLab : jauges, barres, tuiles, platine de lecture… (rendu vectoriel anti-crénelé).

Ils reprennent l'API des anciens contrôles tkinter (set, set_scale, update_tile, set_look, show…) pour que la logique
de `tracklab` fonctionne sans changement."""

import math
import time

from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, GREEN, HOVER, LIME, MUTED, PINK, RED, SIDE, SUB, TEXT, YELLOW  # noqa: F401
from tracklab.widgets import ease_toward

Qt = QtCore.Qt
FONT = "Segoe UI"
MONO = "Consolas"
LCD_BG, LCD_DIM, LCD_EDGE = "#04101a", "#0d2a3a", "#1d3d52"


def qc(color, alpha=None):
    c = QtGui.QColor(color)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def font(size, bold=False, family=FONT, italic=False):
    f = QtGui.QFont(family)
    f.setPixelSize(int(size))
    f.setBold(bold)
    f.setItalic(italic)
    return f


def painter(widget):
    p = QtGui.QPainter(widget)
    p.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing | QtGui.QPainter.SmoothPixmapTransform)
    return p


class Animated(QtWidgets.QWidget):
    """Base : une valeur affichée qui rejoint en douceur la valeur reçue (60 images/s tant qu'elle bouge)."""

    def __init__(self):
        super().__init__()
        self.value = None
        self.target = None
        self._t = time.monotonic()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

    def _go(self, target, snap):
        self.target = target
        if snap or self.value is None or target is None:
            self.value = target
            self._timer.stop()
            self.update()
        elif not self._timer.isActive():
            self._t = time.monotonic()
            self._timer.start()

    def _step(self):
        now = time.monotonic()
        dt, self._t = min(0.2, now - self._t), now
        self.value = ease_toward(self.value, self.target, dt)
        if self.value == self.target:
            self._timer.stop()
        self.update()

    def flush(self):  # compatibilité avec l'API tkinter
        pass


class Gauge(Animated):
    """Jauge circulaire 270° : arc coloré par zone, graduations, aiguille lumineuse et valeur au centre."""

    def __init__(self, maximum, unit, ticks, color_fn):
        super().__init__()
        self.maximum, self.unit, self.ticks, self.color_fn = maximum, unit, ticks, color_fn
        self.setMinimumHeight(190)

    def set(self, value):
        self._go(value, False)

    def set_scale(self, maximum, ticks):
        self.maximum, self.ticks = maximum, ticks
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        w, h = self.width(), self.height()
        r = min(w * 0.44, h * 0.50)  # l'arc, sa lueur et le disque de fond doivent tenir en hauteur (sinon le haut est coupé)
        cx, cy = w / 2, h / 2 + r * 0.14
        th = max(7.0, r * 0.085)
        ra = r - th / 2  # rayon de l'arc (milieu du trait)
        box = QtCore.QRectF(cx - ra, cy - ra, 2 * ra, 2 * ra)
        start, sweep = 225.0, -270.0
        frac = None if self.value is None else max(0.0, min(1.0, float(self.value) / self.maximum))
        # disque de fond : léger dégradé radial, donne du relief
        rg = QtGui.QRadialGradient(QtCore.QPointF(cx, cy - r * 0.25), r * 1.15)
        rg.setColorAt(0.0, qc("#17283d"))
        rg.setColorAt(0.75, qc(CARD))
        rg.setColorAt(1.0, qc(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        p.drawEllipse(QtCore.QPointF(cx, cy), r + th * 0.35, r + th * 0.35)
        # piste de l'arc
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(qc("#223249"), th, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(box, int(start * 16), int(sweep * 16))
        # zones : fine bande colorée sous la piste (rouge de la zone rouge, etc.)
        zr = ra - th * 0.95
        zbox = QtCore.QRectF(cx - zr, cy - zr, 2 * zr, 2 * zr)
        nz = 90
        for i in range(nz):
            f0, f1 = i / nz, (i + 1) / nz
            p.setPen(QtGui.QPen(qc(self.color_fn((f0 + f1) / 2), 150), max(2.0, th * 0.22), Qt.SolidLine, Qt.FlatCap))
            p.drawArc(zbox, int((start + sweep * f0) * 16), int(sweep * (f1 - f0) * 16 - 1))
        # arc de valeur : lueur puis trait net, couleur par zone
        if frac is not None and frac > 0:
            nseg = max(2, int(frac * 90))
            for glow, wd, al in ((1, th * 2.1, 40), (0, th, 255)):
                for i in range(nseg):
                    f0, f1 = frac * i / nseg, frac * (i + 1) / nseg
                    col = qc(self.color_fn((f0 + f1) / 2), al)
                    cap = Qt.RoundCap if (i == 0 or i == nseg - 1) and not glow else Qt.FlatCap
                    p.setPen(QtGui.QPen(col, wd, Qt.SolidLine, cap))
                    p.drawArc(box, int((start + sweep * f0) * 16), int(sweep * (f1 - f0) * 16 - (0 if i == nseg - 1 else 1)))
        # graduations fines (grandes tous les 5) à l'intérieur de la bande de zones
        ri = zr - th * 0.55
        for i in range(51):
            a = math.radians(start + sweep * i / 50)
            major = i % 5 == 0
            r2 = ri - (th * 0.75 if major else th * 0.32)
            on = frac is not None and i / 50 <= frac + 1e-9
            p.setPen(QtGui.QPen(qc(TEXT if (major and on) else SUB if major else MUTED, 230 if major else 140), 1.6 if major else 1))
            p.drawLine(QtCore.QPointF(cx + ri * math.cos(a), cy - ri * math.sin(a)),
                       QtCore.QPointF(cx + r2 * math.cos(a), cy - r2 * math.sin(a)))
        p.setFont(font(max(9, r * 0.095), True))
        for f, label in self.ticks:
            a = math.radians(start + sweep * f)
            lr = ri - th * 2.0
            p.setPen(qc(SUB))
            p.drawText(QtCore.QRectF(cx + lr * math.cos(a) - 30, cy - lr * math.sin(a) - 10, 60, 20), Qt.AlignCenter, label)
        # pastille lumineuse en bout d'arc
        if frac is not None:
            a = math.radians(start + sweep * frac)
            tip = QtCore.QPointF(cx + ra * math.cos(a), cy - ra * math.sin(a))
            col = self.color_fn(frac)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(col, 70))
            p.drawEllipse(tip, th * 1.35, th * 1.35)
            p.setBrush(qc("#ffffff"))
            p.drawEllipse(tip, th * 0.5, th * 0.5)
        # valeur : grande, chiffres nets ; unité en petit dessous
        val = "—" if self.value is None else f"{self.value:,.0f}".replace(",", " ")
        p.setFont(font(max(18, r * 0.36), True))
        p.setPen(qc(TEXT))
        p.drawText(QtCore.QRectF(cx - r, cy - r * 0.34, 2 * r, r * 0.52), Qt.AlignCenter, val)
        p.setFont(font(max(9, r * 0.115), True))
        p.setPen(qc(self.color_fn(frac) if frac is not None else SUB))
        p.drawText(QtCore.QRectF(cx - r, cy + r * 0.20, 2 * r, r * 0.22), Qt.AlignCenter, self.unit.upper())


class Bar(Animated):
    """Barre fine proportionnelle à la valeur entre lo et hi."""

    def __init__(self, color, lo, hi, height=8):
        super().__init__()
        self.color, self.lo, self.hi = color, lo, hi
        self.setFixedHeight(height)

    def set(self, value):
        self._go(None if value is None else max(0.0, min(1.0, (float(value) - self.lo) / (self.hi - self.lo))), False)

    def paintEvent(self, _e):
        p = painter(self)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(qc(CARD2))
        p.drawRoundedRect(r, 3, 3)
        if self.value is not None:
            p.setBrush(qc(self.color))
            p.drawRoundedRect(QtCore.QRectF(0, 0, r.width() * self.value, r.height()), 3, 3)


class GearBox(QtWidgets.QWidget):
    """Rangée N 1 2 3 4 5 6 avec le rapport engagé en surbrillance."""

    LABELS = ["N", "1", "2", "3", "4", "5", "6"]

    def __init__(self, height=36):
        super().__init__()
        self.gear = None
        self.setFixedHeight(height)

    def set(self, gear):
        self.gear = gear
        self.update()

    def flush(self):
        pass

    def paintEvent(self, _e):
        p = painter(self)
        cw = self.width() / len(self.LABELS)
        p.setFont(font(13, True))
        for i, label in enumerate(self.LABELS):
            on = self.gear == i
            r = QtCore.QRectF(i * cw + 2, 3, cw - 4, self.height() - 6)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(RED if on else CARD2))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(qc(TEXT if on else MUTED))
            p.drawText(r, Qt.AlignCenter, label)


class Dot(QtWidgets.QWidget):
    """Petit voyant rond."""

    def __init__(self, color=MUTED, size=10):
        super().__init__()
        self.color = color
        self.setFixedSize(size, size)

    def set(self, color):
        if color != self.color:
            self.color = color
            self.update()

    def paintEvent(self, _e):
        p = painter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(self.color))
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class Label(QtWidgets.QLabel):
    """QLabel avec l'API de configuration de tkinter (config(text=…, fg=…), cget)."""

    def __init__(self, text="", color=TEXT, size=12, bold=False, family=FONT):
        super().__init__(text)
        self._fg, self._size, self._bold, self._family = color, size, bold, family
        self._style()

    def _style(self):
        self.setStyleSheet(
            f"color:{self._fg}; font-size:{self._size}px; font-weight:{'700' if self._bold else '400'};"
            f" font-family:'{self._family}'; background:transparent;")

    def config(self, text=None, fg=None, **_kw):
        if text is not None:
            self.setText(text)
        if fg is not None and fg != self._fg:
            self._fg = fg
            self._style()

    def cget(self, key):
        return self.text() if key == "text" else ""


# ------------------------------------------------------------------ icônes des onglets
def paint_nav_icon(p, kind, rect, color):
    """Pictogrammes vectoriels des onglets (cadran, courbe, liste, carte, engrenage)."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    pen = QtGui.QPen(qc(color), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    sx, sy = w / 26.0, h / 22.0

    def P(a, b):
        return QtCore.QPointF(x + a * sx, y + b * sy)

    if kind == "tele":
        p.drawArc(QtCore.QRectF(x + 3 * sx, y + 4 * sy, 20 * sx, 20 * sy), 0, 180 * 16)
        p.drawLine(P(13, 14), P(19, 8))
        p.setBrush(qc(color))
        p.drawEllipse(P(13, 14), 2 * sx, 2 * sx)
    elif kind == "graph":
        p.setPen(QtGui.QPen(qc(color), 1))
        p.drawLine(P(3, 18), P(3, 4))
        p.drawLine(P(3, 18), P(23, 18))
        p.setPen(pen)
        path = QtGui.QPainterPath(P(4, 15))
        path.lineTo(P(9, 8))
        path.lineTo(P(13, 13))
        path.lineTo(P(18, 5))
        path.lineTo(P(23, 10))
        p.drawPath(path)
    elif kind == "frames":
        for yy in (5, 11, 17):
            p.setBrush(qc(color))
            p.drawRect(QtCore.QRectF(x + 3 * sx, y + (yy - 1) * sy, 4 * sx, 3 * sy))
            p.drawLine(P(10, yy), P(23, yy))
    elif kind == "esp":
        p.drawRect(QtCore.QRectF(x + 7 * sx, y + 6 * sy, 12 * sx, 10 * sy))
        p.setPen(QtGui.QPen(qc(color), 1))
        for xx in (10, 13, 16):
            p.drawLine(P(xx, 3), P(xx, 6))
            p.drawLine(P(xx, 16), P(xx, 19))
    else:  # engrenage
        p.drawEllipse(QtCore.QRectF(x + 8 * sx, y + 6 * sy, 10 * sx, 10 * sy))
        p.setPen(QtGui.QPen(qc(color), 1))
        p.drawEllipse(QtCore.QRectF(x + 11 * sx, y + 9 * sy, 4 * sx, 4 * sy))
        p.setPen(pen)
        for a, b, c_, d in ((13, 2, 13, 5), (13, 17, 13, 20), (3, 11, 7, 11), (19, 11, 23, 11),
                            (6, 4, 8, 6), (18, 16, 20, 18), (6, 18, 8, 16), (18, 6, 20, 4)):
            p.drawLine(P(a, b), P(c_, d))


class NavTab(QtWidgets.QWidget):
    """Onglet de page : pictogramme, texte et soulignement de la page active."""

    clicked = QtCore.Signal(str)

    def __init__(self, key, label):
        super().__init__()
        self.key, self.label, self.on, self.hover = key, label, False, False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setMouseTracking(True)
        fm = QtGui.QFontMetrics(font(13, True))
        self.setFixedWidth(46 + fm.horizontalAdvance(label) + 14)

    def set_on(self, on):
        self.on = on
        self.update()

    def enterEvent(self, _e):
        self.hover = True
        self.update()

    def leaveEvent(self, _e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.key)

    def paintEvent(self, _e):
        p = painter(self)
        r = self.rect()
        if self.on or self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(qc(HOVER if self.on else "#101a2c"))
            p.drawRoundedRect(r.adjusted(0, 2, 0, -1), 6, 6)
        col = RED if self.on else SUB
        paint_nav_icon(p, self.key, QtCore.QRectF(10, 9, 26, 22), col)
        p.setFont(font(13, True))
        p.setPen(qc(TEXT if self.on else SUB))
        p.drawText(QtCore.QRectF(44, 0, r.width() - 44, r.height() - 3), Qt.AlignVCenter | Qt.AlignLeft, self.label)
        if self.on:
            p.setPen(Qt.NoPen)
            p.setBrush(qc(RED))
            p.drawRoundedRect(QtCore.QRectF(6, r.height() - 4, r.width() - 12, 3), 1.5, 1.5)


class GearButton(QtWidgets.QWidget):
    """Engrenage des paramètres (en haut à droite)."""

    clicked = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.hover = False
        self.setFixedSize(40, 36)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, _e):
        self.hover = True
        self.update()

    def leaveEvent(self, _e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _e):
        p = painter(self)
        paint_nav_icon(p, "settings", QtCore.QRectF(7, 7, 26, 22), TEXT if self.hover else SUB)


# ------------------------------------------------------------------ platine de lecture
KEY_W, KEY_H = 54, 38


class DeckButton(QtWidgets.QWidget):
    """Touche de platine : pictogramme dessiné + petit libellé ; s'éclaire quand elle est active."""

    def __init__(self, kind, caption, command, color=TEXT, text="", width=KEY_W):
        super().__init__()
        self.kind, self.caption, self.command, self.color, self.text = kind, caption, command, color, text
        self.lit, self.enabled, self.hover, self.down = False, True, False, False
        self.setFixedSize(width, KEY_H)
        self.setCursor(Qt.PointingHandCursor)

    def set_look(self, lit=None, kind=None, caption=None, enabled=None, text=None, color=None):
        new = (self.lit if lit is None else lit, self.kind if kind is None else kind,
               self.caption if caption is None else caption, self.enabled if enabled is None else enabled,
               self.text if text is None else text, self.color if color is None else color)
        if new != (self.lit, self.kind, self.caption, self.enabled, self.text, self.color):
            self.lit, self.kind, self.caption, self.enabled, self.text, self.color = new
            self.setCursor(Qt.PointingHandCursor if self.enabled else Qt.ArrowCursor)
            self.update()

    def enterEvent(self, _e):
        self.hover = True
        self.update()

    def leaveEvent(self, _e):
        self.hover = self.down = False
        self.update()

    def mousePressEvent(self, _e):
        self.down = True
        self.update()

    def mouseReleaseEvent(self, e):
        was = self.down
        self.down = False
        self.update()
        if was and self.enabled and self.rect().contains(e.position().toPoint()):
            self.command()

    def paintEvent(self, _e):
        p = painter(self)
        w, h = self.width(), KEY_H
        off = 1 if self.down else 0
        face = "#16223a" if self.down else (HOVER if (self.hover and self.enabled) else CARD2)
        edge = self.color if self.lit else BORDER
        p.setPen(QtGui.QPen(qc(edge), 2 if self.lit else 1))
        p.setBrush(qc(face))
        p.drawRoundedRect(QtCore.QRectF(3, 3 + off, w - 6, h - 6), 5, 5)
        p.setPen(qc("#2b3b57" if not self.lit else self.color))
        p.drawLine(QtCore.QPointF(7, 5 + off), QtCore.QPointF(w - 7, 5 + off))
        if not self.enabled:
            col = "#34435c"
        elif self.kind == "rec" and not self.lit:
            col = "#c2282f"
        else:
            col = self.color if self.lit else SUB
        self._icon(p, self.kind, w / 2, 13 + off, col)
        p.setFont(font(8, True))
        p.setPen(qc(col if self.lit else (MUTED if self.enabled else "#34435c")))
        p.drawText(QtCore.QRectF(0, h - 14 + off, w, 12), Qt.AlignCenter, self.caption)

    def _icon(self, p, kind, cx, cy, col):
        s = 0.78
        p.save()
        p.translate(cx, cy)
        p.scale(s, s)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(col))
        poly = lambda *pts: p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(a, b) for a, b in pts]))
        rect = lambda a, b, c_, d: p.drawRect(QtCore.QRectF(a, b, c_ - a, d - b))
        line = lambda a, b, c_, d, colr=col, wd=3: (p.setPen(QtGui.QPen(qc(colr), wd, Qt.SolidLine, Qt.FlatCap)),
                                                   p.drawLine(QtCore.QPointF(a, b), QtCore.QPointF(c_, d)),
                                                   p.setPen(Qt.NoPen))
        if kind == "play":
            poly((-6, -9), (-6, 9), (9, 0))
        elif kind == "pause":
            rect(-8, -9, -2, 9)
            rect(2, -9, 8, 9)
        elif kind == "start":
            rect(-9, -9, -6, 9)
            poly((9, -9), (9, 9), (-4, 0))
        elif kind == "eject":
            poly((-9, 2), (9, 2), (0, -9))
            rect(-9, 5, 9, 9)
        elif kind == "rec":
            p.drawEllipse(QtCore.QPointF(0, 0), 8, 8)
        elif kind == "stop":
            rect(-8, -8, 8, 8)
        elif kind in ("plug", "unplug"):
            line(-4, -10, -4, -3)
            line(4, -10, 4, -3)
            rect(-8, -3, 8, 5)
            line(0, 5, 0, 10)
            if kind == "unplug":
                line(-11, 10, 11, -10, RED)
        else:
            p.setFont(font(17, True, MONO))
            p.setPen(qc(col))
            p.drawText(QtCore.QRectF(-24, -12, 48, 24), Qt.AlignCenter, self.text)
        p.restore()


def fmt_lcd(ms):
    ms = max(0, int(ms))
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000 // 100}"


class DeckLcd(QtWidgets.QWidget):
    """Afficheur : mode, vue, temps, nom du fichier, et bargraph de lecture sur lequel on clique pour se déplacer."""

    BAR_Y0, BAR_Y1, SEG, GAP = 37, 43, 5, 2

    def __init__(self, on_seek, height=48):
        super().__init__()
        self.on_seek = on_seek
        self.s = dict(mode="idle", mode_text="PRÊT", mode_color=MUTED, view="", source="", cur=0, total=0,
                      name="Aucun fichier", info="", frac=0.0, seekable=False, rec=False)
        self.dragging, self.drag_frac, self._blink = False, 0.0, False
        self.setFixedHeight(height)
        self.setMinimumWidth(300)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def show_(self, **kw):
        blink = bool(self.s.get("rec")) and int(time.monotonic() * 2) % 2 == 0
        old = (dict(self.s), self._blink)
        self.s.update(kw)
        self._blink = blink
        if old != (self.s, blink) and not self.dragging:
            self.update()

    def _frac(self, e):
        return max(0.0, min(1.0, (e.position().x() - 12) / max(1, self.width() - 24)))

    def mousePressEvent(self, e):
        if self.s["seekable"] and e.position().y() >= self.BAR_Y0 - 14:
            self.dragging, self.drag_frac = True, self._frac(e)
            self.update()

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.drag_frac = self._frac(e)
            self.update()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.drag_frac = self._frac(e)
            self.s["frac"] = self.drag_frac
            self.update()
            self.on_seek(self.drag_frac)

    def paintEvent(self, _e):
        p = painter(self)
        w, h, s = self.width(), self.height(), self.s
        p.setPen(QtGui.QPen(qc(LCD_EDGE), 2))
        p.setBrush(qc(LCD_BG))
        p.drawRoundedRect(QtCore.QRectF(1, 1, w - 3, h - 3), 6, 6)
        frac = self.drag_frac if self.dragging else s["frac"]
        cur = frac * s["total"] if self.dragging else s["cur"]
        p.setFont(font(11, True, MONO))
        p.setPen(qc(s["mode_color"]))
        p.drawText(QtCore.QRectF(12, 2, 300, 16), Qt.AlignVCenter | Qt.AlignLeft, s["mode_text"])
        right = w - 12
        if s["rec"]:
            col = RED if self._blink else "#5a1216"
            p.setPen(Qt.NoPen)
            p.setBrush(qc(col))
            p.drawEllipse(QtCore.QRectF(w - 22, 4, 9, 9))
            p.setPen(qc(col))
            p.drawText(QtCore.QRectF(w - 70, 2, 44, 16), Qt.AlignVCenter | Qt.AlignRight, "REC")
            right = w - 62
        p.setFont(font(10, True, MONO))
        p.setPen(qc("#3f8aa8"))
        tag = "  ·  ".join(t for t in (s["source"], s["view"]) if t)
        p.drawText(QtCore.QRectF(right - 420, 2, 420, 16), Qt.AlignVCenter | Qt.AlignRight, tag)
        p.setFont(font(19, True, MONO))
        p.setPen(qc(CYAN))
        p.drawText(QtCore.QRectF(12, 14, 100, 24), Qt.AlignVCenter | Qt.AlignLeft, fmt_lcd(cur))
        if s["total"]:
            p.setFont(font(11, True, MONO))
            p.setPen(qc("#2b7a99"))
            p.drawText(QtCore.QRectF(98, 20, 90, 18), Qt.AlignVCenter | Qt.AlignLeft, "/ " + fmt_lcd(s["total"]))
        maxc = max(10, int((w - 210) / 7.5))
        name = s["name"] if len(s["name"]) <= maxc else s["name"][: maxc - 1] + "…"
        info = s["info"] if len(s["info"]) <= maxc else s["info"][: maxc - 1] + "…"
        p.setFont(font(12, True, MONO))
        p.setPen(qc(TEXT))
        p.drawText(QtCore.QRectF(190, 12, w - 200, 16), Qt.AlignVCenter | Qt.AlignLeft, name)
        p.setFont(font(10, False, MONO))
        p.setPen(qc("#3f8aa8"))
        p.drawText(QtCore.QRectF(190, 25, w - 200, 14), Qt.AlignVCenter | Qt.AlignLeft, info)
        x0, x1 = 12, w - 12
        n = max(10, int((x1 - x0) / (self.SEG + self.GAP)))
        lit = int(round(frac * n))
        p.setPen(Qt.NoPen)
        for i in range(n):
            x = x0 + i * (self.SEG + self.GAP)
            if i < lit:
                col = GREEN if s["mode"] == "live" else CYAN
                if s["mode"] != "live" and i >= n * 0.92:
                    col = YELLOW
                if s["mode"] == "live" and i >= n * 0.8:
                    col = YELLOW if i < n * 0.92 else RED
            else:
                col = LCD_DIM
            p.setBrush(qc(col))
            p.drawRect(QtCore.QRectF(x, self.BAR_Y0, self.SEG, self.BAR_Y1 - self.BAR_Y0))
        if s["seekable"] and lit > 0:
            x = x0 + min(n - 1, lit - 1) * (self.SEG + self.GAP)
            p.setBrush(qc(TEXT))
            p.drawRect(QtCore.QRectF(x, self.BAR_Y0 - 2, self.SEG, self.BAR_Y1 - self.BAR_Y0 + 4))


# Le cœur appelle `lcd.show(**kw)` : on expose ce nom sans écraser QWidget.show().
class _LcdProxy:
    def __init__(self, lcd):
        self._lcd = lcd

    def show(self, **kw):
        self._lcd.show_(**kw)

    def __getattr__(self, name):
        return getattr(self._lcd, name)


# ------------------------------------------------------------------ tuiles de télémétrie
class TileBoard(QtWidgets.QScrollArea):
    """Toutes les tuiles de télémétrie, peintes d'un seul bloc (rapide) ; défile avec la molette."""

    TILE_W, TILE_H, GAP = 186, 96, 10

    class _Canvas(QtWidgets.QWidget):
        def __init__(self, board):
            super().__init__()
            self.b = board

        def paintEvent(self, ev):
            self.b._paint(self, ev)

        def resizeEvent(self, ev):
            self.b._relayout(ev.size().width())

    def __init__(self, groups):
        super().__init__()
        self.setWidgetResizable(False)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = self._Canvas(self)
        self.setWidget(self.canvas)
        self.groups, self.items, self.cols, self.rects = [], {}, 0, []
        for title, tiles in groups:
            keys = []
            for key, label, unit in tiles:
                self.items[key] = {"label": label, "unit": unit, "text": "—", "source": self.default_source(key),
                                   "scolor": MUTED, "vcolor": TEXT}
                keys.append(key)
            self.groups.append((title, keys))
        self.canvas.setMinimumHeight(100)
        self.setStyleSheet(f"QScrollArea{{background:{BG};border:none;}}")

    @staticmethod
    def default_source(key):
        return f"0x{key[0]:03X}"

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        w = self.viewport().width()
        self.canvas.setFixedWidth(w)
        self._relayout(w)

    def _relayout(self, width):
        W, H, G = self.TILE_W, self.TILE_H, self.GAP
        cols = max(1, (width - 8) // (W + G))
        self.cols = cols
        y, self.rects = 0, []
        for title, keys in self.groups:
            y += 12
            self.rects.append(("h", title, 5, y))
            y += 20
            for i, key in enumerate(keys):
                self.rects.append(("t", key, 5 + i % cols * (W + G), y + i // cols * (H + G)))
            y += -(-len(keys) // cols) * (H + G)
        self.canvas.setFixedHeight(y + 10)

    def _paint(self, w, ev):
        p = painter(w)
        W, H = self.TILE_W, self.TILE_H
        clip = ev.rect()
        for kind, ref, x, y in self.rects:
            if y > clip.bottom() or y + H < clip.top() - 30:
                continue
            if kind == "h":
                p.setFont(font(11, True))
                p.setPen(qc(MUTED))
                p.drawText(QtCore.QPointF(x, y + 12), ref.upper())
                continue
            it = self.items[ref]
            p.setPen(QtGui.QPen(qc(BORDER), 1))
            p.setBrush(qc(CARD))
            p.drawRoundedRect(QtCore.QRectF(x, y, W, H), 8, 8)
            p.setFont(font(11, True))
            p.setPen(qc(SUB))
            p.drawText(QtCore.QRectF(x + 10, y + 6, W - 20, 16), Qt.AlignLeft | Qt.AlignVCenter, it["label"])
            p.setFont(font(25, True))
            p.setPen(qc(it["vcolor"]))
            p.drawText(QtCore.QRectF(x + 10, y + 26, W - 20, 36), Qt.AlignLeft | Qt.AlignVCenter, it["text"])
            p.setFont(font(12))
            p.setPen(qc(MUTED))
            p.drawText(QtCore.QRectF(x + 10, y + 62, W - 20, 16), Qt.AlignRight | Qt.AlignVCenter, it["unit"])
            p.setFont(font(10, True))
            p.setPen(qc(it["scolor"]))
            p.drawText(QtCore.QRectF(x + 10, y + H - 20, W - 20, 14), Qt.AlignLeft | Qt.AlignVCenter, it["source"])

    def update_tile(self, key, text, source, source_color):
        it = self.items[key]
        if text is not None:
            it["text"] = text
        it["source"], it["scolor"] = source, source_color
        self.canvas.update()

    def set_text(self, key, text):
        it = self.items[key]
        if it["text"] != text:
            it["text"] = text
            self.canvas.update()

    def set_value_color(self, key, color):
        it = self.items[key]
        if it["vcolor"] != color:
            it["vcolor"] = color
            self.canvas.update()

    def rename(self, key, label):
        self.items[key]["label"] = label
        self.canvas.update()

    def reset(self):
        for key, it in self.items.items():
            it.update(text="—", vcolor=TEXT, source=self.default_source(key), scolor=MUTED)
        self.canvas.update()

    def pack(self, *a, **k):  # compatibilité tkinter (inutile en Qt)
        pass


# ------------------------------------------------------------------ liste des signaux
class _SignalDelegate(QtWidgets.QStyledItemDelegate):
    """Peint chaque signal en pastille : la couleur de sa courbe quand il est tracé (le style QSS ignorait la couleur d'élément)."""

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), 28)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(option.rect).adjusted(2, 1, -2, -1)
        is_group = not index.parent().isValid()
        if not is_group:
            bg = index.data(Qt.BackgroundRole)
            on = bool(index.data(Qt.UserRole + 1))
            col = bg.color() if isinstance(bg, QtGui.QBrush) else qc(CARD2)
            if not on and option.state & QtWidgets.QStyle.State_MouseOver:
                col = qc(HOVER)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(r, 5, 5)
            if on:  # liseré clair : la sélection se voit même si la couleur est proche du fond
                p.setPen(QtGui.QPen(qc("#ffffff", 120), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        fg = index.data(Qt.ForegroundRole)
        p.setPen(fg.color() if isinstance(fg, QtGui.QBrush) else qc(TEXT))
        f = index.data(Qt.FontRole)
        p.setFont(f if isinstance(f, QtGui.QFont) else font(12, True))
        p.drawText(r.adjusted(10 if not is_group else 2, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   str(index.data(Qt.DisplayRole) or ""))
        p.restore()


class GroupedSignalList(QtWidgets.QTreeWidget):
    """Signaux classés par type (GPS, CAN, capteurs…) ; un clic ajoute ou retire la courbe, un clic sur un titre replie."""

    def __init__(self, on_toggle, color_of):
        super().__init__()
        self.on_toggle, self.color_of = on_toggle, color_of
        self.setHeaderHidden(True)
        self.setIndentation(10)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(f"QTreeWidget{{background:{CARD};border:1px solid {BORDER};border-radius:8px;outline:0;}}")
        self.setItemDelegate(_SignalDelegate(self))
        self.setMouseTracking(True)
        self.items, self.sel, self._sig, self.groups = {}, set(), None, []
        self.itemClicked.connect(self._click)

    def set_groups(self, groups, selected):
        sig = tuple((t, tuple((it[0], len(it) < 3 or it[2]) for it in items)) for t, items in groups)
        self.sel = set(selected)
        if sig != self._sig:
            self._sig, self.groups = sig, groups
            expanded = {self.topLevelItem(i).text(0).split("  ")[0] for i in range(self.topLevelItemCount())
                        if self.topLevelItem(i).isExpanded()}
            self.clear()
            self.items = {}
            for title, items in groups:
                top = QtWidgets.QTreeWidgetItem([title.upper()])
                top.setData(0, Qt.UserRole, None)
                top.setFont(0, font(11, True))
                top.setForeground(0, QtGui.QBrush(qc(MUTED)))
                self.addTopLevelItem(top)
                for it in items:
                    child = QtWidgets.QTreeWidgetItem([it[1]])
                    child.setData(0, Qt.UserRole, it[0])
                    child.setFont(0, font(12, True))
                    top.addChild(child)
                    self.items[it[0]] = (child, len(it) < 3 or it[2])
                top.setExpanded(title.upper() in expanded or not expanded)
        self.refresh(selected)

    def refresh(self, selected):
        self.sel = set(selected)
        for key, (child, has_data) in self.items.items():
            on = key in self.sel
            child.setData(0, Qt.UserRole + 1, on)
            child.setBackground(0, QtGui.QBrush(qc(self.color_of(key)) if on else qc(CARD2)))
            child.setForeground(0, QtGui.QBrush(qc(BG if on else (SUB if has_data else MUTED))))
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            n = sum(1 for j in range(top.childCount()) if top.child(j).data(0, Qt.UserRole) in self.sel)
            base = top.text(0).split("  ")[0]
            top.setText(0, f"{base}  ·  {n}/{top.childCount()}" if n else f"{base}")

    def _click(self, item, _col):
        key = item.data(0, Qt.UserRole)
        if key is None:
            item.setExpanded(not item.isExpanded())
        else:
            self.on_toggle(key)


class Card(QtWidgets.QFrame):
    """Panneau à fond de carte (bordure fine, coins arrondis)."""

    def __init__(self, fill=CARD):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(f"QFrame#card{{background:{fill};border:1px solid {BORDER};border-radius:10px;}}")


class ProgressOverlay(QtWidgets.QFrame):
    """Fenêtre de progression au centre (chargement d'un fichier)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("prog")
        self.setStyleSheet(f"QFrame#prog{{background:{CARD};border:2px solid {RED};border-radius:12px;}}")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(34, 20, 34, 18)
        self.lbl = Label("", TEXT, 15, True)
        self.lbl.setAlignment(Qt.AlignCenter)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(380, 14)
        self.bar.setStyleSheet(f"QProgressBar{{background:{CARD2};border:1px solid {BORDER};border-radius:7px;}}"
                               f"QProgressBar::chunk{{background:{RED};border-radius:6px;}}")
        self.pc = Label("", SUB, 12)
        self.pc.setAlignment(Qt.AlignCenter)
        for w in (self.lbl, self.bar, self.pc):
            lay.addWidget(w, 0, Qt.AlignCenter)
        self.hide()

    def show_progress(self, text, pct):
        self.lbl.setText(text)
        self.bar.setValue(int(pct))
        self.pc.setText(f"{int(pct)} %")
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, int(par.height() * 0.35))
        self.raise_()
        self.show()
