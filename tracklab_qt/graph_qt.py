"""Page Courbes (Qt + pyqtgraph) : superposées ou empilées, zoom à la molette, déplacement, curseur de lecture."""

import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.config import WINDOWS
from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, GREEN, HOVER, MUTED, SUB, TEXT, YELLOW
from tracklab.util import fmt_val

from .widgets_qt import Card, GroupedSignalList, Label, Qt, font, painter, qc

PEN_W = 1  # trait fin : le rendu logiciel de Qt est ~40 fois plus lent avec des traits épais


class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            m, s = divmod(max(0.0, v), 60)
            out.append(f"{int(m):02d}:{s:04.1f}" if spacing < 1 else f"{int(m):02d}:{int(s):02d}")
        return out


class RefAxis(pg.AxisItem):
    """Axe de gauche en mode superposé : les courbes sont normalisées (0..1), l'axe affiche l'échelle réelle de la
    courbe de référence."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ref = None  # (lo, hi, [graduations réelles])

    def set_ref(self, ref, color):
        self.ref = ref
        self.setPen(qc(color or MUTED))
        self.setTextPen(qc(color or SUB))
        self.picture = None
        self.update()

    def tickValues(self, minVal, maxVal, size):
        if not self.ref:
            return []
        lo, hi, ticks = self.ref
        span = (hi - lo) or 1.0
        return [(1.0, [(t - lo) / span for t in ticks])]

    def tickStrings(self, values, scale, spacing):
        if not self.ref:
            return [""] * len(values)
        lo, hi, _t = self.ref
        return [f"{lo + v * (hi - lo):g}" for v in values]


class CircuitMap(QtWidgets.QWidget):
    """Tracé GPS du circuit avec la position courante."""

    def __init__(self, core):
        super().__init__()
        self.core = core
        self._state = None
        self.setMinimumHeight(170)

    def tick(self):
        c = self.core
        st = (len(c.track), c.track[-1] if c.track else None, self.width(), self.height())
        if st != self._state:
            self._state = st
            self.update()

    def paintEvent(self, _e):
        p = painter(self)
        w, h = self.width(), self.height()
        p.setFont(font(12, True))
        p.setPen(qc(SUB))
        p.drawText(QtCore.QPointF(10, 18), "Circuit")
        pts = list(self.core.track)
        if len(pts) < 2:
            p.setFont(font(12))
            p.setPen(qc(MUTED))
            p.drawText(QtCore.QRectF(0, 0, w, h), Qt.AlignCenter, "Pas de données GPS dans cette source")
            return
        lats, lons = [q[0] for q in pts], [q[1] for q in pts]
        mnla, mxla, mnlo, mxlo = min(lats), max(lats), min(lons), max(lons)
        kx = math.cos(math.radians((mnla + mxla) / 2))
        dx, dy = max((mxlo - mnlo) * kx, 1e-7), max(mxla - mnla, 1e-7)
        scale = min((w - 30) / dx, (h - 44) / dy)
        ox, oy = (w - dx * scale) / 2, 26 + (h - 44 - dy * scale) / 2

        def xy(la, lo):
            return QtCore.QPointF(ox + (lo - mnlo) * kx * scale, oy + (mxla - la) * scale)

        step = max(1, len(pts) // 1500)
        sample = pts[::step]
        if sample[-1] != pts[-1]:
            sample.append(pts[-1])
        path = QtGui.QPainterPath(xy(*sample[0]))
        for q in sample[1:]:
            path.lineTo(xy(*q))
        p.setPen(QtGui.QPen(qc(CYAN), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(GREEN, 70))
        p.drawEllipse(xy(*pts[-1]), 9, 9)
        p.setBrush(qc(GREEN))
        p.drawEllipse(xy(*pts[-1]), 5, 5)


class LegendRow(QtWidgets.QFrame):
    """Une ligne de la légende : nom, min … max, valeur au curseur, croix de suppression ; clic = axe de gauche."""

    def __init__(self, page, key, color):
        super().__init__()
        self.page, self.key, self.color = page, key, color
        self.setCursor(Qt.PointingHandCursor)
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(1)
        core = page.core
        self.name = Label(core.legend_label(key), TEXT, 13, True)
        self.rng = Label("", MUTED, 11)
        self.cur = Label("", color, 13, True)
        self.x = QtWidgets.QToolButton()
        self.x.setText("✕")
        self.x.setCursor(Qt.PointingHandCursor)
        self.x.setStyleSheet(f"QToolButton{{background:{CARD2};color:{SUB};border:none;border-radius:4px;padding:1px 5px;}}"
                             f"QToolButton:hover{{color:{TEXT};background:{HOVER};}}")
        self.x.clicked.connect(lambda: core.remove_curve(key))
        for lb in (self.name, self.rng, self.cur):  # le texte long est coupé au lieu d'élargir la légende
            lb.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            lb.setMinimumWidth(0)
        lay.addWidget(self.name, 0, 0)
        lay.addWidget(self.x, 0, 1)
        lay.addWidget(self.rng, 1, 0, 1, 2)
        lay.addWidget(self.cur, 2, 0, 1, 2)
        self.set_ref(False)

    def set_ref(self, on):
        self.setStyleSheet(
            f"LegendRow{{background:{CARD};border:1px solid {self.color if on else BORDER};border-left:4px solid {self.color};"
            f"border-radius:6px;}}")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self.x.underMouse():
            self.page.core.ref_key = self.key
            self.page.refresh_ref()


class GraphPage(QtWidgets.QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.plots, self.lines, self.curves = [], [], {}
        self.follow = True
        self._np = {}
        self._guard = False
        self._sig = None
        self._cur_shown = None
        self._last_legend = 0.0
        self._last_live = 0.0
        self._rows = {}
        self._tmax = 1.0
        self._fit = False
        core.signal_list = None

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(18, 0, 18, 0)
        root.setSpacing(10)

        # ---- gauche : circuit + liste des signaux
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(8)
        card = Card()
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        self.map = CircuitMap(core)
        cl.addWidget(self.map)
        left.addWidget(card)
        head = Label("Signaux · cliquer pour tracer ou retirer", SUB, 12, True)
        left.addWidget(head)
        self.list = GroupedSignalList(core.toggle_curve, core.color_of)
        core.signal_list = self.list
        left.addWidget(self.list, 1)
        lw = QtWidgets.QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(300)
        root.addWidget(lw)

        # ---- centre : barre d'outils + courbes
        centre = QtWidgets.QVBoxLayout()
        centre.setSpacing(6)
        bar = QtWidgets.QHBoxLayout()
        self.b_over, self.b_stack = self._tab("Superposées"), self._tab("Empilées")
        self.b_over.clicked.connect(lambda: self.set_stack(False))
        self.b_stack.clicked.connect(lambda: self.set_stack(True))
        bar.addWidget(self.b_over)
        bar.addWidget(self.b_stack)
        hint = Label("Molette : zoom · glisser : déplacer · clic : curseur · double-clic : tout voir", MUTED, 12)
        bar.addSpacing(10)
        bar.addWidget(hint)
        bar.addStretch(1)
        self.b_all = self._btn("Tout voir", CYAN)
        self.b_all.clicked.connect(self.fit_all)
        self.b_follow = self._btn("Suivre", GREEN)
        self.b_follow.clicked.connect(self.set_follow)
        bar.addWidget(self.b_all)
        bar.addWidget(self.b_follow)
        bar.addSpacing(10)
        bar.addWidget(Label("Fenêtre", SUB, 12, True))
        self.win = QtWidgets.QComboBox()
        self.win.setEditable(True)  # la zone de texte affiche la durée réelle de la fenêtre (zoom à la molette compris)
        self.win.lineEdit().setReadOnly(True)
        self.win.setFixedWidth(100)
        self.win.addItems([f"{w} s" for w in WINDOWS])
        self.win.setCurrentText("30 s")
        self.win.activated.connect(self.on_window)
        bar.addWidget(self.win)
        centre.addLayout(bar)
        pg.setConfigOptions(antialias=True, background=BG, foreground=SUB)
        self.gl = pg.GraphicsLayoutWidget()
        self.gl.setBackground(BG)
        self.gl.ci.layout.setSpacing(2)
        self.gl.scene().sigMouseClicked.connect(self.on_click)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setWidget(self.gl)
        centre.addWidget(self.scroll, 1)
        foot = QtWidgets.QHBoxLayout()
        self.l_mode = Label("vue libre", YELLOW, 12, True)
        foot.addStretch(1)
        foot.addWidget(self.l_mode)
        centre.addLayout(foot)
        cw = QtWidgets.QWidget()
        cw.setLayout(centre)
        root.addWidget(cw, 1)

        # ---- droite : légende
        right = QtWidgets.QVBoxLayout()
        right.addWidget(Label("Signal · min … max · actuel", MUTED, 12, True))
        self.legend_host = QtWidgets.QWidget()
        self.legend_lay = QtWidgets.QVBoxLayout(self.legend_host)
        self.legend_lay.setContentsMargins(0, 0, 0, 0)
        self.legend_lay.setSpacing(6)
        self.legend_lay.addStretch(1)
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(self.legend_host)
        right.addWidget(sc, 1)
        rw = QtWidgets.QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(250)
        root.addWidget(rw)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ------------------------------------------------------------------ petits composants
    @staticmethod
    def _tab(text):
        b = QtWidgets.QPushButton(text)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{CARD2};border:none;border-radius:6px;padding:7px 14px;color:{SUB};font-weight:700;}}"
            f"QPushButton:checked{{background:{CYAN};color:{BG};}}")
        return b

    @staticmethod
    def _btn(text, color):
        b = QtWidgets.QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:{CARD2};border:none;border-radius:6px;padding:7px 14px;color:{color};font-weight:700;}}"
                        f"QPushButton:hover{{background:{HOVER};}}")
        return b

    # ------------------------------------------------------------------ données
    def t_off(self):
        """Décalage du temps (s) : en direct, l'axe compte depuis la connexion (les horodatages sont ceux de l'horloge du PC)."""
        c = self.core
        return c.t0 / 1000.0 if (c.live and not c.full_t) else 0.0

    def arrays(self, key):
        """(temps en s, valeurs) d'un signal : tableaux complets du fichier, ou historique récent en direct."""
        c = self.core
        if c.full_t.get(key):
            ts = c.full_t[key]
            hit = self._np.get(key)
            if hit is None or hit[0] is not ts:
                hit = self._np[key] = (ts, np.asarray(ts, dtype=np.float64) / 1000.0, np.asarray(c.full_v[key], dtype=np.float64))
            return hit[1], hit[2]
        h = c.hist.get(key)
        if not h:
            return np.empty(0), np.empty(0)
        a = np.asarray(h, dtype=np.float64)
        return a[:, 0] / 1000.0 - self.t_off(), a[:, 1]

    def bounds(self):
        c = self.core
        if c.full_t and c.frames:
            return 0.0, c.frames[-1][0] / 1000.0
        return 0.0, max(c.t_now - c.t0, 1000) / 1000.0 if c.live else max(c.t_now, 1000) / 1000.0

    def cursor_s(self):
        return self.core.cursor_ms() / 1000.0 - self.t_off()

    def selected(self):
        c = self.core
        return [k for k in c.curve_keys() if k in c.sel]

    def axis(self, key):
        """(lo, hi, graduations) d'un signal : échelle stable (fichier entier, ou élargie par paliers en direct)."""
        t, v = self.arrays(key)
        mn = float(np.nanmin(v)) if len(v) else 0.0
        mx = float(np.nanmax(v)) if len(v) else 1.0
        return self.core.axis_key(key, mn, mx)

    # ------------------------------------------------------------------ construction du tracé
    def set_stack(self, stacked):
        self.core.stack.set(stacked)
        self.build()

    def build(self):
        c = self.core
        keys = self.selected()
        self.b_over.setChecked(not c.stack.get())
        self.b_stack.setChecked(c.stack.get())
        view = self.view_range() if self.plots else None
        live = bool(c.live and not c.full_t)
        if live != getattr(self, "_was_live", False):  # passage fichier <-> direct : la vue repart sur la fenêtre courante
            self._was_live = live
            view = None
        self._building = True
        old = self.plots
        for op in old:  # coupe les liens de vue avant de détruire les tracés (évite un accès à un ViewBox détruit)
            try:
                op.setXLink(None)
            except Exception:
                pass
        self._graveyard = (old, self.lines, self.curves)  # garde les objets Python vivants jusqu'à la prochaine reconstruction
        self.plots, self.lines, self.curves = [], [], {}
        self.gl.clear()
        lo_t, hi_t = self.bounds()
        self._tmax = hi_t
        n = 1 if (not c.stack.get() or not keys) else len(keys)
        self.gl.setMinimumHeight(max(300, 150 * n) if c.stack.get() else 300)
        for r in range(n):
            left = RefAxis("left") if not c.stack.get() else pg.AxisItem("left")
            p = self.gl.addPlot(row=r, col=0, axisItems={"bottom": TimeAxis("bottom"), "left": left})
            p.showGrid(x=True, y=True, alpha=0.12)
            p.setMenuEnabled(False)
            p.hideButtons()
            p.setMouseEnabled(x=True, y=False)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            p.vb.setDefaultPadding(0.0)
            p.vb.setLimits(xMin=-1.0, xMax=max(hi_t, 5.0) * 1.3 + 5, minXRange=0.05)
            p.vb.sigRangeChangedManually.connect(self.on_manual)
            p.getAxis("left").setWidth(66)
            p.getAxis("bottom").setStyle(tickTextOffset=4)
            if self.plots:
                p.setXLink(self.plots[0])
            if r < n - 1:
                p.getAxis("bottom").setStyle(showValues=False)
            self.plots.append(p)
        if not keys:
            self.build_legend(keys)
            self._building = False
            return
        if not c.stack.get():
            p = self.plots[0]
            p.setYRange(-0.04, 1.04, padding=0)
            p.enableAutoRange(axis="y", enable=False)
            for k in keys:
                lo, hi, _t = self.axis(k)
                t, v = self.arrays(k)
                span = (hi - lo) or 1.0
                self.curves[k] = p.plot(t, (v - lo) / span, pen=pg.mkPen(c.color_of(k), width=PEN_W), skipFiniteCheck=True)
        else:
            for p, k in zip(self.plots, keys):
                lo, hi, _t = self.axis(k)
                pad = (hi - lo) * 0.06 or 1.0
                p.setYRange(lo - pad, hi + pad, padding=0)
                p.enableAutoRange(axis="y", enable=False)
                p.getAxis("left").setLabel(c.legend_label(k)[:24], color=c.color_of(k))
                t, v = self.arrays(k)
                self.curves[k] = p.plot(t, v, pen=pg.mkPen(c.color_of(k), width=PEN_W), skipFiniteCheck=True)
        for p in self.plots:
            ln = pg.InfiniteLine(pos=self.cursor_s(), angle=90, movable=True, pen=pg.mkPen(YELLOW, width=2))
            ln.setZValue(100)
            ln.sigPositionChangeFinished.connect(self.on_line_done)
            ln.sigPositionChanged.connect(self.on_line_move)
            p.addItem(ln)
            self.lines.append(ln)
        self.build_legend(keys)
        self.refresh_ref()
        self._building = False
        if self._fit:
            self._fit = False
            lo_t, hi_t = self.bounds()
            view = (lo_t - (hi_t - lo_t) * 0.01, hi_t + (hi_t - lo_t) * 0.01)
            self.follow = False
            self.l_mode.setText("vue libre")
        elif view is None:
            view = self.page_range(30.0)
        self.plots[0].setXRange(view[0], view[1], padding=0)
        self.on_cursor(force=True)

    def build_legend(self, keys):
        for i in reversed(range(self.legend_lay.count() - 1)):
            w = self.legend_lay.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._rows = {}
        for k in keys:
            row = LegendRow(self, k, self.core.color_of(k))
            self.legend_lay.insertWidget(self.legend_lay.count() - 1, row)
            self._rows[k] = row
        self.update_legend(force=True)

    def refresh_ref(self):
        c = self.core
        keys = self.selected()
        if c.ref_key not in keys:
            c.ref_key = keys[0] if keys else None
        for k, row in self._rows.items():
            row.set_ref(k == c.ref_key)
        if self.plots and not c.stack.get() and isinstance(self.plots[0].getAxis("left"), RefAxis):
            ax = self.plots[0].getAxis("left")
            if c.ref_key is not None:
                ax.set_ref(self.axis(c.ref_key), c.color_of(c.ref_key))
            else:
                ax.set_ref(None, None)

    # ------------------------------------------------------------------ fenêtre de temps
    def view_range(self):
        return tuple(self.plots[0].vb.viewRange()[0]) if self.plots else (0.0, 30.0)

    def span(self):
        a, b = self.view_range()
        return max(0.05, b - a)

    def page_range(self, span):
        cur = max(0.0, self.cursor_s())
        a = math.floor(cur / span) * span
        return a, a + span

    def set_view(self, a, b):
        if self.plots:
            self.plots[0].setXRange(a, b, padding=0)

    def fit_all(self):
        lo, hi = self.bounds()
        self.set_view(lo - (hi - lo) * 0.01, hi + (hi - lo) * 0.01)
        self.set_follow(False)

    def request_fit(self):
        """Le fichier vient d'être chargé : la prochaine construction montre tout, curseur à zéro."""
        self._fit = True
        self._sig = None
        self._np = {}

    def on_window(self, _i=None):
        span = float(self.win.currentText().split()[0])
        self.set_view(*self.page_range(span))
        self.follow = True
        self.l_mode.setText("suit la lecture")

    def set_follow(self, on=True):
        self.follow = bool(on)
        self.l_mode.setText("suit la lecture" if self.follow else "vue libre")
        if self.follow:
            self.set_view(*self.page_range(self.span()))

    def show_span(self):
        """La zone « Fenêtre » indique la durée réellement affichée (zoom à la molette compris)."""
        if not self.plots:
            return
        r = self.view_range()
        if r != getattr(self, "_rng_shown", None):
            self._rng_shown = r
            sp = r[1] - r[0]
            txt = f"{sp:.1f} s" if sp < 100 else f"{sp:.0f} s"
            if self.win.currentText() != txt:
                self.win.setCurrentText(txt)

    def on_manual(self, *_a):
        self.follow = False
        self.l_mode.setText("vue libre")

    # ------------------------------------------------------------------ curseur
    def on_cursor(self, force=False):
        t = self.cursor_s()
        if not force and self._cur_shown is not None and abs(t - self._cur_shown) < 1e-4:
            return
        self._cur_shown = t
        self._guard = True
        for ln in self.lines:
            ln.setValue(t)
        self._guard = False
        if self.plots and (self.core.playing or self.core.live):
            a, b = self.view_range()
            if t > b or t < a:  # le curseur sort de la vue : on tourne la page
                span = b - a
                na = a + math.floor((t - a) / span) * span
                self.set_view(na, na + span)
        self.update_legend()

    def on_line_move(self, ln):
        if self._guard:
            return
        self._guard = True
        for other in self.lines:
            if other is not ln:
                other.setValue(ln.value())
        self._guard = False
        self._cur_shown = ln.value()
        self.update_legend(at=ln.value())

    def on_line_done(self):
        if self._guard or not self.lines:
            return
        self.seek_to(self.lines[0].value())

    def seek_to(self, t):
        c = self.core
        if not c.frames or c.live:
            return
        total = c.frames[-1][0]
        t = max(0.0, min(total / 1000.0, t))
        c._cursor_override = t * 1000.0
        self._cur_shown = t
        self._guard = True
        for ln in self.lines:
            ln.setValue(t)
        self._guard = False
        self.update_legend(at=t)

        def do():
            try:
                c.seek(t * 1000.0 / total if total else 0.0)
            finally:
                c._cursor_override = None
            self._cur_shown = None

        QtCore.QTimer.singleShot(0, do)

    def on_click(self, ev):
        if not self.plots or ev.button() != Qt.LeftButton:
            return
        if ev.double():
            self.fit_all()
            ev.accept()
            return
        for p in self.plots:
            if p.vb.sceneBoundingRect().contains(ev.scenePos()):
                self.seek_to(p.vb.mapSceneToView(ev.scenePos()).x())
                ev.accept()
                return

    # ------------------------------------------------------------------ légende : valeurs au curseur
    def value_at(self, key, t):
        ts, vs = self.arrays(key)
        if not len(ts):
            return None
        i = int(np.searchsorted(ts, t, side="right")) - 1
        return float(vs[max(0, i)])

    def update_legend(self, force=False, at=None):
        now = time.monotonic()
        if not force and now - self._last_legend < 0.03:
            return
        self._last_legend = now
        t = self.cursor_s() if at is None else at
        for k, row in self._rows.items():
            v = self.value_at(k, t)
            unit = self.core.unit_of(k)
            row.cur.setText("—" if v is None else f"{fmt_val(v)} {unit}".strip())
            if force:
                ts, vs = self.arrays(k)
                if len(vs):
                    row.rng.setText(f"{fmt_val(float(np.nanmin(vs)))} … {fmt_val(float(np.nanmax(vs)))} {unit}".strip())

    # ------------------------------------------------------------------ boucle d'affichage
    def tick(self):
        c = self.core
        if not self.isVisible():
            return
        sig = (tuple(sorted(c.sel)), c.stack.get(), id(c.full_t), len(c.dyn), tuple(sorted(c.color_map.items())))
        if sig != self._sig:
            self._sig = sig
            self.list.set_groups(c.signal_groups(), c.sel)
            self.build()
        now = time.monotonic()
        if c.live and now - self._last_live > 0.17:  # en direct : les courbes grandissent
            self._last_live = now
            self.refresh_live()
        self.on_cursor()
        self.show_span()
        self.map.tick()

    def refresh_live(self):
        c = self.core
        lo_t, hi_t = self.bounds()
        for k, curve in self.curves.items():
            t, v = self.arrays(k)
            if c.stack.get():
                curve.setData(t, v)
            else:
                lo, hi, _t = self.axis(k)
                curve.setData(t, (v - lo) / ((hi - lo) or 1.0))
        if self.plots:
            self.plots[0].vb.setLimits(xMax=max(hi_t, 5.0) * 1.3 + 5)
            self.refresh_ref()
