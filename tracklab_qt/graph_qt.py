"""Page Courbes (Qt + pyqtgraph) : superposées ou empilées, zoom à la molette, déplacement, curseur de lecture."""

import bisect
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.config import WINDOWS
from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, GREEN, HOVER, MUTED, SUB, TEXT, YELLOW
from tracklab.util import fmt_val

from .satmap import ATTRIBUTION, MAX_TILES, TileStore, choose_zoom, world_px
from .widgets_qt import Card, GroupedSignalList, Label, Qt, font, painter, qc

def painter_on(pm):
    q = QtGui.QPainter(pm)
    q.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing | QtGui.QPainter.SmoothPixmapTransform)
    return q


POOL = 16  # tracés construits une fois pour toutes à l'ouverture (en créer plus tard faisait planter pyqtgraph)
SPLIT_QSS = (f"QSplitter::handle{{background:{BORDER};}}"
             f"QSplitter::handle:horizontal{{image:none;margin:0 3px;border-radius:2px;}}"
             f"QSplitter::handle:vertical{{margin:3px 0;border-radius:2px;}}"
             f"QSplitter::handle:hover{{background:{CYAN};}}"
             f"QSplitter::handle:pressed{{background:{CYAN};}}")
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
            return super().tickValues(minVal, maxVal, size)  # mode empilé : graduations ordinaires
        lo, hi, ticks = self.ref
        span = (hi - lo) or 1.0
        return [(1.0, [(t - lo) / span for t in ticks])]

    def tickStrings(self, values, scale, spacing):
        if not self.ref:
            return super().tickStrings(values, scale, spacing)
        lo, hi, _t = self.ref
        return [f"{lo + v * (hi - lo):g}" for v in values]


class CircuitMap(QtWidgets.QWidget):
    """Circuit GPS : tracé complet dès l'ouverture du fichier, sur fond satellite, avec un point qui suit le curseur."""

    def __init__(self, core):
        super().__init__()
        self.core = core
        self.store = TileStore(self)
        self.store.changed.connect(self._tiles_changed)
        self._base = None
        self._base_key = None
        self._geo = None  # (points, bbox, zoom) du dernier calcul
        self._geo_key = None
        self._shown = None
        self._last_geo = 0.0
        self._pts, self._pts_key, self._pts_t = None, None, 0.0
        self.setMinimumHeight(110)

    def _tiles_changed(self):
        self._base_key = None
        self.update()

    # ---------------------------------------------------------------- données
    def points(self):
        c = self.core
        file_mode = not c.live and c.frames and c.track_full
        key = (id(c.track_full), len(c.track_full), bool(file_mode), None if file_mode else len(c.track))
        now = time.monotonic()
        if key != self._pts_key and not (not file_mode and self._pts is not None and now - self._pts_t < 0.6):
            pts = [(la, lo) for _t, la, lo in c.track_full] if file_mode else list(c.track)
            self._pts = [q for q in pts if abs(q[0]) > 1e-6 or abs(q[1]) > 1e-6]
            self._pts_key, self._pts_t = key, now
        return self._pts or []

    def position(self):
        c = self.core
        if not c.live and c.frames and c.track_full:
            ts = c.track_full_t
            t = c.cursor_ms()
            i = bisect.bisect_right(ts, t)
            if i <= 0:
                q = c.track_full[0]
                return q[1], q[2]
            if i >= len(ts):
                q = c.track_full[-1]
                return q[1], q[2]
            a, b = c.track_full[i - 1], c.track_full[i]
            f = (t - a[0]) / ((b[0] - a[0]) or 1)
            return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f
        return (c.track[-1][0], c.track[-1][1]) if c.track else None

    def tick(self):
        c = self.core
        pos = self.position()
        st = (pos, len(c.track), len(c.track_full), c.live, self.width(), self.height())
        if st != self._shown:
            self._shown = st
            self.update()

    # ---------------------------------------------------------------- dessin
    def _geometry(self, pts, w, h):
        lats, lons = [q[0] for q in pts], [q[1] for q in pts]
        la0, la1, lo0, lo1 = min(lats), max(lats), min(lons), max(lons)
        top, pad = 26, 14
        aw, ah = w - 2 * pad, h - top - pad
        z = choose_zoom(la0, la1, lo0, lo1, max(aw, 40), max(ah, 40))
        x0, y1 = world_px(la0, lo0, z)
        x1, y0 = world_px(la1, lo1, z)
        bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        k = min(aw / bw, ah / bh)
        cxw, cyw = (x0 + x1) / 2, (y0 + y1) / 2
        ox, oy = w / 2 - cxw * k, top + ah / 2 - cyw * k + pad / 2
        return z, k, ox, oy

    def _xy(self, geo, la, lo):
        z, k, ox, oy = geo
        x, y = world_px(la, lo, z)
        return QtCore.QPointF(ox + x * k, oy + y * k)

    def _render_base(self, pts, w, h):
        dpr = self.devicePixelRatioF()
        pm = QtGui.QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(qc(CARD))
        q = painter_on(pm)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(0.5, 0.5, w - 1, h - 1), 10, 10)
        q.setClipPath(clip)
        geo = self._geometry(pts, w, h)
        z, k, ox, oy = geo
        missing = 0
        n = 2 ** z
        tx0, tx1 = int(math.floor((0 - ox) / k / 256)), int(math.floor((w - ox) / k / 256))
        ty0, ty1 = int(math.floor((0 - oy) / k / 256)), int(math.floor((h - oy) / k / 256))
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES:
            for ty in range(max(ty0, 0), min(ty1, n - 1) + 1):
                for tx in range(max(tx0, 0), min(tx1, n - 1) + 1):
                    tile = self.store.get(z, tx, ty)
                    if tile is None:
                        missing += 1
                        continue
                    q.drawPixmap(QtCore.QRectF(ox + tx * 256 * k, oy + ty * 256 * k, 256 * k + 0.6, 256 * k + 0.6), tile,
                                 QtCore.QRectF(tile.rect()))
        sat = len(self.store.mem) > 0 and missing < (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if sat:
            q.fillRect(QtCore.QRectF(0, 0, w, h), qc("#000000", 70))
        step = max(1, len(pts) // 2000)
        sample = pts[::step]
        if sample[-1] != pts[-1]:
            sample.append(pts[-1])
        path = QtGui.QPainterPath(self._xy(geo, *sample[0]))
        for pt in sample[1:]:
            path.lineTo(self._xy(geo, *pt))
        q.setBrush(Qt.NoBrush)
        q.setPen(QtGui.QPen(qc("#000000", 170), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))  # liseré sombre : lisible sur l'image
        q.drawPath(path)
        q.setPen(QtGui.QPen(qc(CYAN), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        q.drawPath(path)
        # départ
        q.setPen(QtGui.QPen(qc("#ffffff"), 2))
        q.setBrush(qc(BG))
        q.drawEllipse(self._xy(geo, *pts[0]), 4, 4)
        if sat:
            q.setFont(font(9))
            q.setPen(qc("#ffffff", 190))
            q.drawText(QtCore.QRectF(0, h - 16, w - 8, 14), Qt.AlignRight | Qt.AlignVCenter, ATTRIBUTION)
        q.end()
        return pm, geo

    def paintEvent(self, _e):
        p = painter(self)
        w, h = self.width(), self.height()
        pts = self.points()
        if len(pts) < 2:
            self._base = None
            p.setFont(font(12, True))
            p.setPen(qc(SUB))
            p.drawText(QtCore.QPointF(10, 18), "Circuit")
            p.setFont(font(12))
            p.setPen(qc(MUTED))
            p.drawText(QtCore.QRectF(0, 0, w, h), Qt.AlignCenter, "Pas de données GPS dans cette source")
            return
        c = self.core
        key = (w, h, len(pts), pts[-1], pts[0], len(self.store.mem))
        if key != self._base_key or self._base is None:
            now = time.monotonic()
            if c.live and self._base is not None and now - self._last_geo < 0.6:
                pass  # en direct, le fond n'est recalculé que de temps en temps
            else:
                self._base, self._geo = self._render_base(pts, w, h)
                self._base_key = key
                self._last_geo = now
        p.drawPixmap(0, 0, self._base)
        p.setFont(font(12, True))
        p.setPen(qc("#000000", 160))
        p.drawText(QtCore.QPointF(11, 19), "Circuit")
        p.setPen(qc(TEXT))
        p.drawText(QtCore.QPointF(10, 18), "Circuit")
        pos = self.position()
        if pos and self._geo:
            pt = self._xy(self._geo, *pos)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(GREEN, 60))
            p.drawEllipse(pt, 11, 11)
            p.setBrush(qc("#ffffff"))
            p.drawEllipse(pt, 6.5, 6.5)
            p.setBrush(qc(GREEN))
            p.drawEllipse(pt, 4.5, 4.5)


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
        self._pool_plots, self._pool_lines, self._pool_curves = [], [], {}
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

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(18, 0, 18, 0)
        # trois volets séparés par des poignées qu'on glisse : (circuit + signaux) | courbes | légende
        self.split = QtWidgets.QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(8)
        self.split.setChildrenCollapsible(False)
        self.split.setStyleSheet(SPLIT_QSS)
        outer.addWidget(self.split)

        # ---- gauche : circuit + liste des signaux (séparés verticalement)
        self.lsplit = QtWidgets.QSplitter(Qt.Vertical)
        self.lsplit.setHandleWidth(8)
        self.lsplit.setChildrenCollapsible(False)
        self.lsplit.setStyleSheet(SPLIT_QSS)
        card = Card()
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        self.map = CircuitMap(core)
        cl.addWidget(self.map)
        self.lsplit.addWidget(card)
        lbox = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(lbox)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        head = Label("Signaux · cliquer pour tracer ou retirer", SUB, 12, True)
        left.addWidget(head)
        self.list = GroupedSignalList(core.toggle_curve, core.color_of)
        core.signal_list = self.list
        left.addWidget(self.list, 1)
        lbox.setMinimumHeight(140)
        self.lsplit.addWidget(lbox)
        self.lsplit.setStretchFactor(0, 0)
        self.lsplit.setStretchFactor(1, 1)
        self.lsplit.setSizes([260, 500])
        self.lsplit.setMinimumWidth(190)
        self.split.addWidget(self.lsplit)

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
        for r in range(POOL):
            self._make_plot(r).setVisible(False)
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
        cw.setMinimumWidth(360)
        self.split.addWidget(cw)

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
        rw.setMinimumWidth(170)
        self.split.addWidget(rw)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([300, 900, 250])
        self._restore_layout()
        self.split.splitterMoved.connect(self._save_layout)
        self.lsplit.splitterMoved.connect(self._save_layout)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ------------------------------------------------------------------ petits composants
    def _restore_layout(self):
        try:
            st = QtCore.QSettings("TrackLab", "TrackLabQt")
            for name, sp in (("split", self.split), ("lsplit", self.lsplit)):
                v = st.value("courbes/" + name)
                if v:
                    sp.restoreState(v)
        except Exception:
            pass

    def _save_layout(self, *_a):
        try:
            st = QtCore.QSettings("TrackLab", "TrackLabQt")
            st.setValue("courbes/split", self.split.saveState())
            st.setValue("courbes/lsplit", self.lsplit.saveState())
        except Exception:
            pass

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
        return c.t0 / 1000.0 if c.live else 0.0

    def arrays(self, key):
        """(temps en s, valeurs) d'un signal : tableaux complets du fichier, ou historique récent en direct."""
        c = self.core
        if c.full_t.get(key) and not c.live:  # en direct, l'historique remplace la capture chargée
            ts = c.full_t[key]
            hit = self._np.get(key)
            if hit is None or hit[0] is not ts:
                t = np.asarray(ts, dtype=np.float64) / 1000.0
                v = np.asarray(c.full_v[key], dtype=np.float64)
                n = min(len(t), len(v))
                t, v = t[:n], v[:n]
                # NaN, infinis et valeurs absurdes (décodage expérimental) corrompent le tracé : on les écarte
                ok = np.isfinite(t) & np.isfinite(v) & (np.abs(v) < 1e12)
                if not ok.all():
                    t, v = t[ok], v[ok]
                hit = self._np[key] = (ts, t, v)
            return hit[1], hit[2]
        h = c.hist.get(key)
        if not h:
            return np.empty(0), np.empty(0)
        a = np.asarray(h, dtype=np.float64)
        ok = np.isfinite(a[:, 0]) & np.isfinite(a[:, 1]) & (np.abs(a[:, 1]) < 1e12)
        if not ok.all():
            a = a[ok]
        return a[:, 0] / 1000.0 - self.t_off(), a[:, 1]

    def bounds(self):
        c = self.core
        if c.full_t and c.frames and not c.live:
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

    def _make_plot(self, r):
        """Crée (une seule fois) le tracé n° r : il est ensuite réutilisé, jamais détruit (la destruction répétée de
        PlotItem faisait planter pyqtgraph/PySide)."""
        p = self.gl.addPlot(row=r, col=0, axisItems={"bottom": TimeAxis("bottom"), "left": RefAxis("left")})
        p.showGrid(x=True, y=True, alpha=0.12)
        p.setMenuEnabled(False)
        p.hideButtons()
        p.setMouseEnabled(x=True, y=False)
        p.setClipToView(True)
        p.setDownsampling(auto=True, mode="peak")
        p.vb.setDefaultPadding(0.0)
        p.vb.sigRangeChangedManually.connect(self.on_manual)
        p.getAxis("left").setWidth(66)
        p.getAxis("bottom").setStyle(tickTextOffset=4)
        if self._pool_plots:
            p.setXLink(self._pool_plots[0])
        ln = pg.InfiniteLine(pos=0.0, angle=90, movable=True, pen=pg.mkPen(YELLOW, width=2))
        ln.setZValue(100)
        ln.sigPositionChangeFinished.connect(self.on_line_done)
        ln.sigPositionChanged.connect(self.on_line_move)
        p.addItem(ln)
        self._pool_plots.append(p)
        self._pool_lines.append(ln)
        return p

    @staticmethod
    def _two_points(t, v):
        """Une courbe d'un seul point fait planter le tracé : on la prolonge en un segment plat."""
        if len(t) == 1:
            return np.array([t[0], t[0] + 1e-3]), np.array([v[0], v[0]])
        return t, v

    def _curve_item(self, r, i):
        """Courbe n° i du tracé r : créée une fois, rattachée à ce tracé pour toujours (changer un objet de tracé
        déstabilise pyqtgraph), simplement masquée quand elle ne sert pas."""
        lst = self._pool_curves.setdefault(r, [])
        while len(lst) <= i:
            cv = pg.PlotDataItem(pen=pg.mkPen(CYAN, width=PEN_W), skipFiniteCheck=True)
            self._pool_plots[r].addItem(cv)
            lst.append(cv)
        cv = lst[i]
        cv.setVisible(True)
        return cv

    def build(self):
        c = self.core
        keys = self.selected()
        self.b_over.setChecked(not c.stack.get())
        self.b_stack.setChecked(c.stack.get())
        view = self.view_range() if self.plots else None
        live = bool(c.live)
        if live != getattr(self, "_was_live", False):  # passage fichier <-> direct : la vue repart sur la fenêtre courante
            self._was_live = live
            view = None
        self._building = True
        empty = np.empty(0)
        for lst in self._pool_curves.values():  # toutes les courbes sont masquées et vidées ; celles utilisées réapparaissent
            for cv in lst:
                if cv.isVisible():
                    cv.setVisible(False)
                    cv.setData(empty, empty)
        self.curves = {}
        lo_t, hi_t = self.bounds()
        self._tmax = hi_t
        stacked = bool(c.stack.get())
        n = 1 if (not stacked or not keys) else min(len(keys), POOL)
        self.gl.setMinimumHeight(max(300, 150 * n) if stacked else 300)
        for i, pl in enumerate(self._pool_plots):
            pl.setVisible(i < n)
        self.plots = self._pool_plots[:n]
        self.lines = self._pool_lines[:n]
        for r, p in enumerate(self.plots):
            p.vb.setLimits(xMin=-1.0, xMax=max(hi_t, 5.0) * 1.3 + 5, minXRange=0.05)
            p.getAxis("bottom").setStyle(showValues=(r == n - 1))
            ax = p.getAxis("left")
            ax.set_ref(None, None)
            ax.showLabel(False)
        if keys and not stacked:
            p = self.plots[0]
            p.setYRange(-0.04, 1.04, padding=0)
            p.enableAutoRange(axis="y", enable=False)
            for i, k in enumerate(keys):
                lo, hi, _t = self.axis(k)
                t, v = self.arrays(k)
                span = (hi - lo) or 1.0
                cv = self._curve_item(0, i)
                cv.setPen(pg.mkPen(c.color_of(k), width=PEN_W))
                t2, v2 = self._two_points(t, (v - lo) / span)
                cv.setData(t2, v2)
                self.curves[k] = cv
        elif keys:
            if len(keys) > POOL:
                self.l_mode.setText(f"empilé : {POOL} premières courbes (les autres : mode Superposées)")
            for i, (p, k) in enumerate(zip(self.plots, keys)):
                lo, hi, _t = self.axis(k)
                pad = (hi - lo) * 0.06 or 1.0
                p.setYRange(lo - pad, hi + pad, padding=0)
                p.enableAutoRange(axis="y", enable=False)
                ax = p.getAxis("left")
                ax.setLabel(c.legend_label(k)[:24], color=c.color_of(k))
                ax.showLabel(True)
                ax.set_ref(None, c.color_of(k))
                t, v = self.arrays(k)
                cv = self._curve_item(i, 0)
                cv.setPen(pg.mkPen(c.color_of(k), width=PEN_W))
                t2, v2 = self._two_points(t, v)
                cv.setData(t2, v2)
                self.curves[k] = cv
        cur = self.cursor_s()
        for ln in self.lines:
            ln.setValue(cur)
        self.build_legend(keys)
        if keys:
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
                w.hide()
                w.deleteLater()  # destruction différée : la ligne cliquée peut encore être en train de traiter son événement
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
        sig = (tuple(sorted(c.sel)), c.stack.get(), id(c.full_t), bool(c.live), len(c.dyn), tuple(sorted(c.color_map.items())))
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
