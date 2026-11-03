"""TrackLab · prototype de la page Courbes en PySide6 + pyqtgraph.

Données : data/sim_courbes.zip (exportées par tools/export_courbes.py depuis l'application actuelle).
Lancement : python main.py            (fenêtre)
            python main.py --selftest [capture.png]   (test sans écran : chronométrages + capture)
"""
import json
import math
import os
import statistics
import sys
import time
import zipfile

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

# ---- palette (identique à l'application actuelle)
BG, SIDE, CARD, BORDER, HOVER = "#070d16", "#0b1220", "#111a2a", "#23314b", "#1f2e47"
TEXT, SUB, MUTED = "#eef3fb", "#9fb0c8", "#5d7090"
CYAN, YELLOW, ORANGE, GREEN, RED = "#3cc0ff", "#ffb938", "#ff8a3d", "#2fe39a", "#e52028"
PEN_W, DS_MODE, AA = 1, "peak", True  # réglages de tracé (comparés par --selftest)
PALETTE = [CYAN, GREEN, YELLOW, ORANGE, "#a98bff", "#ff5fa2", "#a3e635", "#e52028"]

QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 12px; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#h {{ color: {SUB}; font-size: 11px; letter-spacing: 1px; }}
QLineEdit, QComboBox {{ background: {SIDE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: {SIDE}; selection-background-color: {HOVER}; border: 1px solid {BORDER}; }}
QPushButton {{ background: {SIDE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: {HOVER}; border-color: {CYAN}; }}
QPushButton:checked {{ background: {CYAN}; color: {BG}; border-color: {CYAN}; }}
QListWidget, QTableWidget {{ background: {SIDE}; border: 1px solid {BORDER}; border-radius: 8px; outline: 0; }}
QListWidget::item {{ padding: 4px 6px; }}
QListWidget::item:hover {{ background: {HOVER}; }}
QHeaderView::section {{ background: {SIDE}; color: {SUB}; border: none; padding: 4px; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QScrollBar:vertical {{ background: {SIDE}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def resource(path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, path)


def load_data(path):
    """Renvoie (meta, T, V) : listes de dictionnaires, tableaux de temps (s) et de valeurs."""
    z = zipfile.ZipFile(path)
    meta = json.loads(z.read("meta.json"))
    T, V = [], []
    for i in range(len(meta)):
        T.append(np.frombuffer(z.read(f"t{i}.bin"), dtype=np.float64) / 1000.0)
        V.append(np.frombuffer(z.read(f"v{i}.bin"), dtype=np.float32).astype(np.float64))
    return meta, T, V


class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            m, s = divmod(max(0.0, v), 60)
            out.append(f"{int(m):02d}:{s:04.1f}" if spacing < 1 else f"{int(m):02d}:{int(s):02d}")
        return out


class Gauge(QtWidgets.QWidget):
    """Cadran : arc de 270° avec lueur, aiguille et valeur numérique (rendu vectoriel anti-crénelé)."""

    def __init__(self, title, unit, vmax):
        super().__init__()
        self.title, self.unit, self.vmax, self.value, self.color = title, unit, vmax, 0.0, QtGui.QColor(CYAN)
        self.setMinimumSize(150, 150)

    def set_value(self, v):
        self.value = v
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = min(w, h) - 16
        rect = QtCore.QRectF((w - s) / 2, (h - s) / 2 + 4, s, s)
        c = rect.center()
        frac = max(0.0, min(1.0, self.value / self.vmax)) if self.vmax else 0.0
        start, span = 225 * 16, -270 * 16
        # piste
        p.setPen(QtGui.QPen(QtGui.QColor(BORDER), 9, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawArc(rect.adjusted(8, 8, -8, -8), start, span)
        # lueur puis arc de valeur
        r2 = rect.adjusted(8, 8, -8, -8)
        for width, alpha in ((18, 28), (13, 55)):
            col = QtGui.QColor(self.color)
            col.setAlpha(alpha)
            p.setPen(QtGui.QPen(col, width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            p.drawArc(r2, start, int(span * frac))
        p.setPen(QtGui.QPen(self.color, 7, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawArc(r2, start, int(span * frac))
        # graduations
        p.setPen(QtGui.QPen(QtGui.QColor(MUTED), 1.5))
        rad = s / 2 - 22
        for i in range(0, 11):
            a = math.radians(225 - 270 * i / 10)
            r_in, r_out = rad - (9 if i % 5 == 0 else 5), rad
            p.drawLine(QtCore.QPointF(c.x() + r_in * math.cos(a), c.y() - r_in * math.sin(a)),
                       QtCore.QPointF(c.x() + r_out * math.cos(a), c.y() - r_out * math.sin(a)))
        # aiguille
        a = math.radians(225 - 270 * frac)
        tip = QtCore.QPointF(c.x() + (rad - 4) * math.cos(a), c.y() - (rad - 4) * math.sin(a))
        p.setPen(QtGui.QPen(QtGui.QColor(TEXT), 3, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawLine(c, tip)
        p.setBrush(QtGui.QColor(CARD))
        p.setPen(QtGui.QPen(QtGui.QColor(TEXT), 2))
        p.drawEllipse(c, 6, 6)
        # textes
        f = p.font()
        f.setPointSizeF(max(10, s / 9))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QRectF(rect.x(), c.y() + s * 0.12, s, s * 0.2), QtCore.Qt.AlignCenter,
                   f"{self.value:,.0f}".replace(",", " "))
        f.setPointSizeF(max(7, s / 16))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QtGui.QColor(SUB))
        p.drawText(QtCore.QRectF(rect.x(), c.y() + s * 0.30, s, s * 0.14), QtCore.Qt.AlignCenter,
                   f"{self.title} · {self.unit}" if self.unit else self.title)


class Window(QtWidgets.QMainWindow):
    def __init__(self, meta, T, V):
        super().__init__()
        self.setWindowTitle("TrackLab · Courbes (prototype Qt)")
        self.resize(1500, 900)
        self.meta, self.T, self.V = meta, T, V
        self.tmax = max(t[-1] for t in T)
        self.lo = [float(np.nanmin(v)) for v in V]
        self.hi = [float(np.nanmax(v)) for v in V]
        self.N = [(v - lo) / ((hi - lo) or 1.0) for v, lo, hi in zip(V, self.lo, self.hi)]  # normalisées 0..1
        self.cursor_t = 0.0
        self.mode = "over"
        self.playing = False
        self.speed = 1.0
        self.sel = []
        self.plots, self.lines = [], []
        self._guard = False

        root = QtWidgets.QWidget(objectName="root")
        self.setCentralWidget(root)
        grid = QtWidgets.QHBoxLayout(root)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setSpacing(12)

        # ---- colonne de gauche : signaux + cadrans
        left = QtWidgets.QVBoxLayout()
        self.search = QtWidgets.QLineEdit(placeholderText="Rechercher un signal…")
        self.search.textChanged.connect(self.filter_list)
        self.list = QtWidgets.QListWidget()
        for i, m in enumerate(meta):
            it = QtWidgets.QListWidgetItem(m["label"])
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            it.setData(QtCore.Qt.UserRole, i)
            self.list.addItem(it)
        self.list.itemChanged.connect(self.on_check)
        self.g1 = Gauge("Régime", "tr/min", 15000)
        self.g2 = Gauge("Vitesse", "km/h", 300)
        self.g2.color = QtGui.QColor(GREEN)
        gl = QtWidgets.QHBoxLayout()
        gl.addWidget(self.g1)
        gl.addWidget(self.g2)
        card = QtWidgets.QWidget(objectName="card")
        cl = QtWidgets.QVBoxLayout(card)
        cl.addLayout(gl)
        left.addWidget(card)
        left.addWidget(QtWidgets.QLabel("SIGNAUX", objectName="h"))
        left.addWidget(self.search)
        left.addWidget(self.list, 1)
        lw = QtWidgets.QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(330)
        grid.addWidget(lw)

        # ---- centre : barre d'outils + courbes
        centre = QtWidgets.QVBoxLayout()
        bar = QtWidgets.QHBoxLayout()
        self.b_over = QtWidgets.QPushButton("Superposées")
        self.b_stack = QtWidgets.QPushButton("Empilées")
        for b in (self.b_over, self.b_stack):
            b.setCheckable(True)
        self.b_over.setChecked(True)
        self.b_over.clicked.connect(lambda: self.set_mode("over"))
        self.b_stack.clicked.connect(lambda: self.set_mode("stack"))
        self.b_play = QtWidgets.QPushButton("▶  Lecture")
        self.b_play.clicked.connect(self.toggle_play)
        self.cb_speed = QtWidgets.QComboBox()
        self.cb_speed.addItems(["x0.5", "x1", "x2", "x4", "x8"])
        self.cb_speed.setCurrentText("x1")
        self.cb_speed.currentTextChanged.connect(lambda s: setattr(self, "speed", float(s[1:])))
        self.cb_win = QtWidgets.QComboBox()
        self.cb_win.addItems(["5 s", "10 s", "30 s", "60 s", "120 s"])
        self.cb_win.setCurrentText("30 s")
        self.cb_win.activated.connect(self.on_window)
        self.b_thick = QtWidgets.QPushButton("Traits épais")
        self.b_thick.setCheckable(True)
        self.b_thick.setToolTip("Plus joli mais nettement plus lent (limite du rendu logiciel de Qt)")
        self.b_thick.clicked.connect(self.set_thick)
        b_all = QtWidgets.QPushButton("Tout voir")
        b_all.clicked.connect(self.fit_all)
        self.l_time = QtWidgets.QLabel("00:00.0")
        self.l_time.setStyleSheet(f"color:{YELLOW}; font-size:16px; font-weight:600;")
        for w_ in (self.b_over, self.b_stack, self.b_play, self.cb_speed, self.cb_win, self.b_thick, b_all):
            bar.addWidget(w_)
        bar.addStretch(1)
        bar.addWidget(self.l_time)
        centre.addLayout(bar)
        pg.setConfigOptions(antialias=True, background=BG, foreground=SUB, useOpenGL=False)
        self.gl = pg.GraphicsLayoutWidget()
        self.gl.ci.layout.setSpacing(2)
        self.gl.scene().sigMouseClicked.connect(self.on_click)
        centre.addWidget(self.gl, 1)
        hint = QtWidgets.QLabel("Molette : zoom · glisser : déplacer · clic : placer le curseur · double-clic : tout voir")
        hint.setObjectName("h")
        centre.addWidget(hint)
        cw = QtWidgets.QWidget()
        cw.setLayout(centre)
        grid.addWidget(cw, 1)

        # ---- droite : légende avec valeurs au curseur
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Signal", "Valeur", "Unité"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFixedWidth(330)
        grid.addWidget(self.table)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self._last = time.perf_counter()
        # signaux proposés par défaut
        for key in ("Régime", "Vitesse moto", "Gaz poignée", "Rapport", "Papillon", "Accélération"):
            for i, m in enumerate(meta):
                if key.lower() in m["label"].lower():
                    self.list.item(i).setCheckState(QtCore.Qt.Checked)
                    break

    # ---------------------------------------------------------------- sélection
    def filter_list(self, text):
        t = text.lower()
        for i in range(self.list.count()):
            self.list.item(i).setHidden(t not in self.list.item(i).text().lower())

    def on_check(self, _it):
        self.sel = [self.list.item(i).data(QtCore.Qt.UserRole) for i in range(self.list.count())
                    if self.list.item(i).checkState() == QtCore.Qt.Checked]
        self.build()

    def color(self, k):
        return PALETTE[self.sel.index(k) % len(PALETTE)]

    def set_thick(self, on):
        global PEN_W
        PEN_W = 2 if on else 1
        self.build()

    def set_mode(self, mode):
        self.mode = mode
        self.b_over.setChecked(mode == "over")
        self.b_stack.setChecked(mode == "stack")
        self.build()

    # ---------------------------------------------------------------- tracé
    def view_range(self):
        return self.plots[0].vb.viewRange()[0] if self.plots else (0.0, 30.0)

    def build(self):
        xr = self.view_range() if self.plots else (0.0, min(30.0, self.tmax))
        self.gl.clear()
        self.plots, self.lines = [], []
        if not self.sel:
            self.refresh_legend()
            return
        n = 1 if self.mode == "over" else len(self.sel)
        for r in range(n):
            ax = TimeAxis("bottom")
            p = self.gl.addPlot(row=r, col=0, axisItems={"bottom": ax})
            p.showGrid(x=True, y=True, alpha=0.12)
            p.setMenuEnabled(False)
            p.hideButtons()
            p.setMouseEnabled(x=True, y=False)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode=DS_MODE)
            p.vb.setLimits(xMin=-1.0, xMax=self.tmax + 1.0, minXRange=0.05)
            p.vb.setDefaultPadding(0.0)
            if self.plots:
                p.setXLink(self.plots[0])
            if r < n - 1:
                p.getAxis("bottom").setStyle(showValues=False)
            p.getAxis("left").setWidth(56)
            self.plots.append(p)
        if self.mode == "over":
            p = self.plots[0]
            p.hideAxis("left")
            p.setYRange(-0.04, 1.04, padding=0)
            p.enableAutoRange(axis="y", enable=False)
            for k in self.sel:
                self.add_curve(p, k, self.N[k])
        else:
            for p, k in zip(self.plots, self.sel):
                lo, hi = self.lo[k], self.hi[k]
                pad = (hi - lo) * 0.08 or 1.0
                p.setYRange(lo - pad, hi + pad, padding=0)
                p.enableAutoRange(axis="y", enable=False)
                p.setLabel("left", self.meta[k]["label"].split("  ·")[0][:22])
                self.add_curve(p, k, self.V[k])
        for p in self.plots:
            ln = pg.InfiniteLine(pos=self.cursor_t, angle=90, movable=True, pen=pg.mkPen(YELLOW, width=2))
            ln.setZValue(100)
            ln.sigPositionChanged.connect(self.on_line)
            p.addItem(ln)
            self.lines.append(ln)
        self.plots[0].setXRange(xr[0], xr[1], padding=0)
        self.refresh_legend()
        self.set_cursor(self.cursor_t)

    def add_curve(self, p, k, y):
        c = p.plot(self.T[k], y, pen=pg.mkPen(self.color(k), width=PEN_W), skipFiniteCheck=True)
        c.setClipToView(True)
        c.setDownsampling(auto=True, method=DS_MODE)

    def fit_all(self):
        if self.plots:
            self.plots[0].setXRange(0, self.tmax, padding=0.01)

    def on_window(self, _i):
        span = float(self.cb_win.currentText().split()[0])
        a, _b = self.view_range()
        a = max(0.0, min(self.cursor_t - span * 0.1, self.tmax - span))
        if self.plots:
            self.plots[0].setXRange(a, a + span, padding=0)

    # ---------------------------------------------------------------- curseur
    def on_line(self, ln):
        if self._guard:
            return
        self.set_cursor(ln.value(), from_line=ln)

    def on_click(self, ev):
        if not self.plots or ev.button() != QtCore.Qt.LeftButton:
            return
        if ev.double():
            self.fit_all()
            return
        for p in self.plots:
            if p.vb.sceneBoundingRect().contains(ev.scenePos()):
                self.set_cursor(p.vb.mapSceneToView(ev.scenePos()).x())
                return

    def set_cursor(self, t, from_line=None):
        t = max(0.0, min(self.tmax, t))
        self.cursor_t = t
        self._guard = True
        for ln in self.lines:
            if ln is not from_line:
                ln.setValue(t)
        self._guard = False
        m, s = divmod(t, 60)
        self.l_time.setText(f"{int(m):02d}:{s:04.1f}")
        for r, k in enumerate(self.sel):
            i = max(0, int(np.searchsorted(self.T[k], t, side="right")) - 1)
            v = self.V[k][i]
            it = self.table.item(r, 1)
            if it:
                it.setText(f"{v:.2f}")
        self.update_gauges(t)

    def value_at(self, k, t):
        i = max(0, int(np.searchsorted(self.T[k], t, side="right")) - 1)
        return float(self.V[k][i])

    def update_gauges(self, t):
        for g, key in ((self.g1, "régime"), (self.g2, "vitesse moto")):
            for i, m in enumerate(self.meta):
                if key in m["label"].lower():
                    g.vmax = max(g.vmax, self.hi[i]) if key == "régime" else g.vmax
                    g.set_value(self.value_at(i, t))
                    break

    def refresh_legend(self):
        self.table.setRowCount(len(self.sel))
        for r, k in enumerate(self.sel):
            name = QtWidgets.QTableWidgetItem("●  " + self.meta[k]["label"].split("  ·")[0])
            name.setForeground(QtGui.QBrush(QtGui.QColor(self.color(k))))
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(self.meta[k]["unit"] or ""))

    # ---------------------------------------------------------------- lecture
    def toggle_play(self):
        self.playing = not self.playing
        self.b_play.setText("⏸  Pause" if self.playing else "▶  Lecture")
        self._last = time.perf_counter()
        self.timer.start() if self.playing else self.timer.stop()

    def tick(self):
        now = time.perf_counter()
        self.step((now - self._last) * self.speed)
        self._last = now

    def step(self, dt):
        t = self.cursor_t + dt
        if t >= self.tmax:
            t = self.tmax
            if self.playing:
                self.toggle_play()
        if self.plots:
            a, b = self.view_range()
            span = b - a
            if t > b or t < a:  # le curseur sort de la vue : on tourne la page
                a = math.floor((t - a) / span) * span + a
                self.plots[0].setXRange(a, a + span, padding=0)
        self.set_cursor(t)


def selftest(win, out):
    """Chronométrages sans écran : redessin complet de la fenêtre (grab) pour différents gestes."""
    app = QtWidgets.QApplication.instance()

    def grab_ms():
        app.processEvents()
        t0 = time.perf_counter()
        win.gl.grab()
        return (time.perf_counter() - t0) * 1000

    def bench(label, fn, n=20):
        ts = []
        for i in range(n):
            fn(i)
            ts.append(grab_ms())
        print(f"{label:<44} med {statistics.median(ts):6.1f} ms   max {max(ts):6.1f}", flush=True)

    for i in range(win.list.count()):
        if i < 10:
            win.list.item(i).setCheckState(QtCore.Qt.Checked)
    win.show()
    app.processEvents()
    print("signaux affichés :", len(win.sel), "· durée", round(win.tmax, 1), "s", flush=True)
    global PEN_W, DS_MODE
    for pen_w, ds, aa in ((2, "peak", True), (1, "peak", True), (1, "peak", False), (2, "mean", True), (1, "mean", True), (1, "subsample", False)):
        PEN_W, DS_MODE = pen_w, ds
        pg.setConfigOptions(antialias=aa)
        win.build()
        q = win.plots[0]
        for span in (win.tmax, 30):
            ts = []
            for i in range(6):
                q.setXRange(i * 0.3, i * 0.3 + span, padding=0)
                ts.append(grab_ms())
            print(f"variante largeur={pen_w} ds={ds:<9} aa={int(aa)} fenêtre {span:3.0f} s   med {statistics.median(ts):6.1f} ms", flush=True)
    PEN_W, DS_MODE = 1, "peak"
    pg.setConfigOptions(antialias=True)
    win.build()
    p = win.plots[0]
    for span in (win.tmax, 60, 30, 5):
        p.setXRange(0, span, padding=0)
        bench(f"superposées, fenêtre {span:.0f} s (redessin)", lambda i, s=span: p.setXRange(i * 0.3, i * 0.3 + s, padding=0))
    p.setXRange(0, 30, padding=0)
    bench("déplacement 0,2 s (fenêtre 30 s)", lambda i: p.setXRange(i * 0.2, 30 + i * 0.2, padding=0), 30)
    bench("zoom molette (x0.9)", lambda i: p.setXRange(10, 10 + 30 * (0.9 ** i), padding=0), 20)
    bench("curseur seul", lambda i: win.set_cursor(i * 0.5), 30)
    win.set_mode("stack")
    p = win.plots[0]
    p.setXRange(0, 30, padding=0)
    bench("empilées, 10 signaux, fenêtre 30 s", lambda i: p.setXRange(i * 0.2, 30 + i * 0.2, padding=0))
    win.set_mode("over")
    win.cursor_t = 0.0
    win.playing = True
    bench("lecture x1 (pas de 16 ms)", lambda i: win.step(0.016), 40)
    win.playing = False
    win.grab().save(out)
    print("capture :", out, flush=True)


def main():
    args = sys.argv[1:]
    test = "--selftest" in args
    if test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        args.remove("--selftest")
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(QSS)
    meta, T, V = load_data(resource(os.path.join("data", "sim_courbes.zip")))
    win = Window(meta, T, V)
    if test:
        selftest(win, args[0] if args else "capture_qt.png")
        return 0
    win.show()
    win.on_check(None)
    win.fit_all()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
