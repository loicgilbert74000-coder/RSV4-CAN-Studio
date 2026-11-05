"""Page Analyse : tours et secteurs, comparaison de tours à la distance, écart de temps, virages, diagramme G-G,
marqueurs, voies calculées et exports (CSV, image, PDF)."""

import json
import os
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tracklab import analysis as an
from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, GREEN, MUTED, ORANGE, PINK, RED, SUB, TEXT, YELLOW

from .pages_qt import btn
from .widgets_qt import Card, Label, Qt, font, qc

CHANNELS = (("Vitesse (km/h)", "speed"), ("G longitudinal (g)", "glong"), ("G latéral (g)", "glat"), ("Angle (°)", "angle"))
BAD_COLOR = "#7a8aa5"


# ------------------------------------------------------------------ accès aux données du cœur
def core_get(core):
    """Fonction nom -> (temps ms, valeurs) ou None, d'après les tableaux complets du fichier chargé."""
    cache = getattr(core, "_an_names", None)
    if cache is None or cache[0] is not core.full_t or cache[1] != len(core.full_t):
        names = {}
        for k in core.full_t:
            names.setdefault(k[1], k)
        cache = core._an_names = (core.full_t, len(core.full_t), names, {})
    names, arrs = cache[2], cache[3]

    def get(name):
        k = names.get(name)
        if k is None:
            return None
        hit = arrs.get(k)
        if hit is None:
            t = np.asarray(core.full_t[k], float)
            v = np.asarray(core.full_v[k], float)
            n = min(len(t), len(v))
            hit = arrs[k] = (t[:n], v[:n])
        return hit

    return get


def lap_label(num, t):
    return f"Tour {num} · {an.fmt_time(t)}"


# ------------------------------------------------------------------ marqueurs
def marks_path(core):
    p = getattr(core, "primary_path", None)
    return (p + ".tracklab.json") if p else None


def marks_sync(core):
    """Recharge les marqueurs enregistrés à côté du fichier ouvert (quand le fichier change)."""
    key = id(core.full_t)
    if getattr(core, "_marks_key", None) == key:
        return
    core._marks_key = key
    core.markers = []
    p = marks_path(core)
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                core.markers = [m for m in json.load(f).get("markers", []) if "ms" in m]
        except Exception:
            core.markers = []


def marks_save(core):
    p = marks_path(core)
    if not p:
        return
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"markers": core.markers}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass  # dossier en lecture seule : les marqueurs restent en mémoire


def add_marker(core, parent=None):
    marks_sync(core)
    if not core.frames or core.live:
        return
    ms = float(core.cursor_ms())
    sec = ms / 1000.0
    text, ok = QtWidgets.QInputDialog.getText(parent, "Marqueur", f"Note à {int(sec // 60)}:{sec % 60:05.2f} :")
    if not ok:
        return
    core.markers.append({"ms": ms, "text": text.strip() or "Marqueur"})
    core.markers.sort(key=lambda m: m["ms"])
    marks_save(core)


# ------------------------------------------------------------------ voies calculées
def add_math_channel(core, name, unit, formula):
    """Calcule une voie à partir d'une formule et l'ajoute aux signaux (et à la sélection). Retourne la clé ou lève ValueError."""
    from tracklab.page_graph import TYPE_IMU

    get = core_get(core)
    base = get("GPS Vitesse") or next((get(k[1]) for k in core.full_t), None)
    if base is None:
        raise ValueError("aucun fichier chargé")
    t_ms = base[0]
    t = t_ms / 1000.0
    sig = {}
    for k in list(core.full_t):
        r = get(k[1])
        if r is not None and k[1] not in sig and len(r[0]) > 3 and not k[1].startswith("~"):
            v = an._interp(r[0] / 1000.0, r[1], t)
            if v is not None:
                sig[k[1]] = v
    v = an.eval_formula(formula, sig, t)
    cid = 0x3000 + sum(1 for c in core.dyn if 0x3000 <= c < 0x4000)
    core.dyn[cid] = [(name, unit, TYPE_IMU), None]
    key = (cid, name)
    core.full_t[key] = [float(x) for x in t_ms]
    core.full_v[key] = [float(x) for x in v]
    core._an_names = None
    core.assign_color(key)
    core.sel.add(key)
    core.ui.graph_selection_changed()
    return key


class MathDialog(QtWidgets.QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("Voie calculée")
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(Label("Écris une formule avec des voies entre crochets : [GPS Vitesse] / 3.6, abs([G latéral]), "
                            "deriv([GPS Vitesse]) / 3.6 / g, smooth([Angle], 5)", SUB, 12))
        form = QtWidgets.QFormLayout()
        self.e_name = QtWidgets.QLineEdit("Ma voie")
        self.e_unit = QtWidgets.QLineEdit("")
        self.e_formula = QtWidgets.QLineEdit("[GPS Vitesse] / 3.6")
        form.addRow("Nom", self.e_name)
        form.addRow("Unité", self.e_unit)
        form.addRow("Formule", self.e_formula)
        lay.addLayout(form)
        lay.addWidget(Label("Voies disponibles (double-clic pour insérer) :", SUB, 12))
        self.lst = QtWidgets.QListWidget()
        names = sorted({k[1] for k in core.full_t if not k[1].startswith("~")})
        self.lst.addItems(names)
        self.lst.itemDoubleClicked.connect(lambda it: self.e_formula.insert(f"[{it.text()}]"))
        lay.addWidget(self.lst, 1)
        self.err = Label("", RED, 12, True)
        lay.addWidget(self.err)
        row = QtWidgets.QHBoxLayout()
        ok = btn("Ajouter la voie", GREEN)
        ok.clicked.connect(self.accept_formula)
        cancel = btn("Fermer", TEXT)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

    def accept_formula(self):
        try:
            add_math_channel(self.core, self.e_name.text().strip() or "Ma voie", self.e_unit.text().strip(), self.e_formula.text())
        except Exception as exc:  # formule invalide : on l'affiche, la fenêtre reste ouverte
            self.err.setText(f"Formule refusée : {exc}")
            return
        self.accept()


# ------------------------------------------------------------------ page
def _table(headers):
    t = QtWidgets.QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
    t.setAlternatingRowColors(False)
    return t


def _cell(text, color=None, bold=False, align=Qt.AlignCenter):
    it = QtWidgets.QTableWidgetItem(str(text))
    it.setTextAlignment(align)
    if color:
        it.setForeground(QtGui.QBrush(qc(color)))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    return it


class AnalysePage(QtWidgets.QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.A = self.B = None
        self.rows_a = self.rows_b = []
        self.items = []  # [(étiquette, session, ligne de tour)]
        self._sig = None
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 0, 18, 0)
        root.setSpacing(6)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(Label("Analyse", SUB, 14, True))
        top.addSpacing(14)
        top.addWidget(Label("Tour de référence", CYAN, 12, True))
        self.c_ref = QtWidgets.QComboBox()
        self.c_ref.setMinimumWidth(190)
        top.addWidget(self.c_ref)
        top.addWidget(Label("comparé à", ORANGE, 12, True))
        self.c_cmp = QtWidgets.QComboBox()
        self.c_cmp.setMinimumWidth(190)
        top.addWidget(self.c_cmp)
        top.addStretch(1)
        self.l_info = Label("", YELLOW, 12, True)
        top.addWidget(self.l_info)
        self.b_export = btn("Exporter ▾", TEXT)
        menu = QtWidgets.QMenu(self.b_export)
        for text, fn in (("Tableau des tours (CSV)", self.export_laps), ("Virages du tour de référence (CSV)", self.export_corners),
                         ("Courbes sélectionnées (CSV)", self.export_curves), ("Image des courbes (PNG)", self.export_png),
                         ("Rapport de la session (PDF)", self.export_pdf)):
            menu.addAction(text).triggered.connect(fn)
        self.b_export.setMenu(menu)
        top.addWidget(self.b_export)
        root.addLayout(top)

        self.tabs = QtWidgets.QTabWidget()
        root.addWidget(self.tabs, 1)

        # -- Tours
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        sess = QtWidgets.QHBoxLayout()
        self.c_sess = QtWidgets.QComboBox()
        self.c_sess.addItems(["Session A", "Session B"])
        self.c_sess.activated.connect(lambda _i: self.fill_laps())
        sess.addWidget(self.c_sess)
        self.l_best = Label("", GREEN, 13, True)
        sess.addWidget(self.l_best)
        sess.addStretch(1)
        v.addLayout(sess)
        self.t_laps = _table(["Tour", "Temps", "Écart", "S1", "S2", "S3", "V max", "V moy", "G lat max", "Angle max", "Valide"])
        v.addWidget(self.t_laps, 1)
        v.addWidget(Label("Vert : meilleur tour / meilleur secteur · gris : tour de sortie, de rentrée ou incomplet (exclu du classement)",
                          MUTED, 11))
        self.tabs.addTab(w, "Tours")

        # -- Tours superposés
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(Label("Voie", SUB, 12, True))
        self.c_chan = QtWidgets.QComboBox()
        for label, _k in CHANNELS:
            self.c_chan.addItem(label)
        self.c_chan.activated.connect(lambda _i: self.fill_overlay())
        h.addWidget(self.c_chan)
        self.l_delta = Label("", YELLOW, 13, True)
        h.addStretch(1)
        h.addWidget(self.l_delta)
        v.addLayout(h)
        self.l_hover = QtWidgets.QLabel("")
        self.l_hover.setTextFormat(Qt.RichText)
        self.l_hover.setFixedHeight(26)
        self.l_hover.setStyleSheet(f"background:{CARD2};border-radius:6px;padding:0 8px;")
        self._hover_hint()
        v.addWidget(self.l_hover)
        self._ov = None
        self.p_over = pg.PlotWidget(background=BG)
        self.p_over.showGrid(x=True, y=True, alpha=0.15)
        self.p_over.setLabel("bottom", "Distance dans le tour", units="m")
        self.p_over.addLegend(offset=(10, 10))
        self.cv_ref = self.p_over.plot([], [], pen=pg.mkPen(CYAN, width=2), name="référence")
        self.cv_cmp = self.p_over.plot([], [], pen=pg.mkPen(ORANGE, width=2), name="comparé")
        self.p_delta = pg.PlotWidget(background=BG)
        self.p_delta.showGrid(x=True, y=True, alpha=0.15)
        self.p_delta.setLabel("bottom", "Distance dans le tour", units="m")
        self.p_delta.setLabel("left", "Écart de temps", units="s")
        self.p_delta.addLine(y=0, pen=pg.mkPen(MUTED, width=1))
        self.cv_delta = self.p_delta.plot([], [], pen=pg.mkPen(YELLOW, width=2))
        self.p_delta.setXLink(self.p_over)
        self.hv_over = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#dfe8f7", width=1, style=QtCore.Qt.DashLine))
        self.hv_delta = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#dfe8f7", width=1, style=QtCore.Qt.DashLine))
        for hv, pw in ((self.hv_over, self.p_over), (self.hv_delta, self.p_delta)):
            hv.setVisible(False)
            pw.addItem(hv)
        self.p_over.scene().sigMouseMoved.connect(lambda pos: self.on_hover(pos, self.p_over))
        self.p_delta.scene().sigMouseMoved.connect(lambda pos: self.on_hover(pos, self.p_delta))
        v.addWidget(self.p_over, 3)
        v.addWidget(Label("Écart de temps (s) : positif = le tour comparé est plus lent à cet endroit", MUTED, 11))
        v.addWidget(self.p_delta, 2)
        self.tabs.addTab(w, "Comparer deux tours")

        # -- Virages
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.t_corn = _table(["Virage", "Côté", "Distance", "V entrée", "V point de corde", "V sortie", "G lat max", "Angle max",
                              "Freinage (g)", "Δ corde (cmp)", "Δ sortie (cmp)"])
        v.addWidget(self.t_corn, 1)
        v.addWidget(Label("Virage = passage où le G latéral dépasse 0,30 g. Δ : tour comparé moins référence (vert = le comparé "
                          "passe plus vite).", MUTED, 11))
        self.tabs.addTab(w, "Virages")

        # -- G-G
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.p_gg = pg.PlotWidget(background=BG)
        self.p_gg.showGrid(x=True, y=True, alpha=0.15)
        self.p_gg.setAspectLocked(True)
        self.p_gg.setLabel("bottom", "G latéral (g)")
        self.p_gg.setLabel("left", "G longitudinal (g) : + accélération / − freinage")
        for r in (0.5, 1.0, 1.5):
            c = QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            c.setPen(pg.mkPen(MUTED, width=1, style=QtCore.Qt.DashLine))
            self.p_gg.addItem(c)
        self.sc_ref = pg.ScatterPlotItem(size=4, pen=None, brush=pg.mkBrush(qc(CYAN, 150)))
        self.sc_cmp = pg.ScatterPlotItem(size=4, pen=None, brush=pg.mkBrush(qc(ORANGE, 150)))
        self.p_gg.addItem(self.sc_ref)
        self.p_gg.addItem(self.sc_cmp)
        v.addWidget(self.p_gg, 1)
        self.l_gg = Label("", SUB, 12)
        v.addWidget(self.l_gg)
        self.tabs.addTab(w, "Diagramme G-G")

        from .moto_qt import MotoTabs

        self.moto = MotoTabs(self)

        # -- Marqueurs
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.t_marks = _table(["Instant", "Tour", "Note"])
        self.t_marks.cellDoubleClicked.connect(self.goto_mark)
        v.addWidget(self.t_marks, 1)
        row = QtWidgets.QHBoxLayout()
        b_add = btn("Ajouter un marqueur ici (touche M)", CYAN)
        b_add.clicked.connect(self.add_mark)
        b_del = btn("Supprimer", RED)
        b_del.clicked.connect(self.del_mark)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(Label("Double-clic : aller à l'instant · enregistrés à côté du fichier (.tracklab.json)", MUTED, 11))
        v.addLayout(row)
        self.tabs.addTab(w, "Marqueurs")

        self.c_ref.activated.connect(lambda _i: self.fill_selection())
        self.c_cmp.activated.connect(lambda _i: self.fill_selection())

    # ------------------------------------------------------------------ données
    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self.refresh)

    def refresh(self, force=False):
        c = self.core
        sig = (id(c.full_t), getattr(c, "compare_name", None), len(c.full_t))
        if sig == self._sig and not force:
            return
        self._sig = sig
        marks_sync(c)
        get = core_get(c)
        self.A = self.B = None
        self.rows_a = self.rows_b = []
        if not c.live and c.full_t:
            try:
                lt = c.lap_table("")
                self.A = an.build_session(get, "", lt and (lt[0], lt[1]))
                if getattr(c, "compare_name", None):
                    lb = c.lap_table(" [B]")
                    self.B = an.build_session(get, " [B]", lb and (lb[0], lb[1]))
            except Exception as exc:
                self.A = None
                self.l_info.setText(f"analyse impossible : {exc}")
        if self.A is not None:
            self.rows_a = an.lap_stats(self.A)
        if self.B is not None:
            self.rows_b = an.lap_stats(self.B)
        self.c_sess.model().item(1).setEnabled(self.B is not None)
        if self.B is None:
            self.c_sess.setCurrentIndex(0)
        self.items = []
        for tag, S, rows in (("A", self.A, self.rows_a), ("B", self.B, self.rows_b)):
            for r in rows:
                if r["complete"]:
                    ok = "" if r["valid"] else " (hors classement)"
                    self.items.append((f"{tag} · {lap_label(r['num'], r['time'])}{ok}", S, r))
        for cb in (self.c_ref, self.c_cmp):
            cb.clear()
            for lab, _S, _r in self.items:
                cb.addItem(lab)
        best = an.best_lap(self.rows_a)
        if best is not None:
            self.c_ref.setCurrentIndex(next(i for i, it in enumerate(self.items) if it[1] is self.A and it[2] is best))
        # comparé : le meilleur de B s'il y en a un, sinon le 2e meilleur tour de A
        if self.B is not None and an.best_lap(self.rows_b):
            bb = an.best_lap(self.rows_b)
            self.c_cmp.setCurrentIndex(next(i for i, it in enumerate(self.items) if it[1] is self.B and it[2] is bb))
        else:
            valid = sorted((r for r in self.rows_a if r["valid"] and r is not best), key=lambda r: r["time"])
            if valid:
                self.c_cmp.setCurrentIndex(next(i for i, it in enumerate(self.items) if it[2] is valid[0]))
        if not self.items:
            self.l_info.setText("Ouvrez une session GPS avec des tours (RaceBox, RaceChrono) pour analyser" if self.A is None
                                else "Aucun tour complet dans ce fichier")
        else:
            self.l_info.setText("")
        self.fill_laps()
        self.fill_selection()
        self.fill_marks()

    def sel(self, combo):
        i = combo.currentIndex()
        return self.items[i] if 0 <= i < len(self.items) else None

    def fill_selection(self):
        self.fill_overlay()
        self.fill_corners()
        self.fill_gg()
        self.moto.fill()

    # ------------------------------------------------------------------ onglets
    def fill_laps(self):
        use_b = self.c_sess.currentIndex() == 1 and self.B is not None
        S, rows = (self.B, self.rows_b) if use_b else (self.A, self.rows_a)
        t = self.t_laps
        t.setRowCount(0)
        self.l_best.setText("")
        if S is None:
            return
        best = an.best_lap(rows)
        sec, mins, theo = an.sector_times(S, rows)
        if best:
            self.l_best.setText(f"Meilleur tour {an.fmt_time(best['time'])}   ·   Tour théorique {an.fmt_time(theo)} "
                                f"({theo - best['time']:+.3f} s)")
        for r in rows:
            i = t.rowCount()
            t.insertRow(i)
            is_best = best is not None and r is best
            col = GREEN if is_best else (None if r["valid"] else BAD_COLOR)
            diff = (r["time"] - best["time"]) if (best and r["valid"]) else None
            s = sec.get(r["num"]) if r["valid"] else None
            vals = [r["num"], an.fmt_time(r["time"]), "—" if diff is None else f"{diff:+.3f}"]
            for k in range(3):
                vals.append("—" if not s else f"{s[k]:.3f}")
            vals += [f"{r['vmax']:.0f}", f"{r['vmean']:.0f}", "—" if r["glat"] is None else f"{r['glat']:.2f}",
                     "—" if r["angle"] is None else f"{r['angle']:.0f}°", "oui" if r["valid"] else "non"]
            for j, x in enumerate(vals):
                cc = col
                if s and 3 <= j <= 5 and abs(s[j - 3] - mins[j - 3]) < 1e-9:
                    cc = GREEN
                t.setItem(i, j, _cell(x, cc, bold=is_best or cc == GREEN))

    def _axis(self, item, key):
        _lab, S, r = item
        sl = slice(r["i0"], r["i1"])
        arr = getattr(S, key)
        if arr is None:
            return np.array([]), np.array([])
        d = S.dist[sl] - S.dist[r["i0"]]
        return d, np.asarray(arr[sl], float)

    def fill_overlay(self):
        a, b = self.sel(self.c_ref), self.sel(self.c_cmp)
        key = CHANNELS[max(0, self.c_chan.currentIndex())][1]
        data = {}
        for nm, cv, it in (("ref", self.cv_ref, a), ("cmp", self.cv_cmp, b)):
            if it is None:
                cv.setData([], [])
            else:
                d, v = self._axis(it, key)
                cv.setData(d, v)
                data[nm] = (d, v)
        self.l_delta.setText("")
        self._ov = data
        if a and b and a[2] is not b[2]:
            d, dl = an.delta_curve(a[1], a[2], b[1], b[2])
            self.cv_delta.setData(d, dl)
            data["delta"] = (d, dl)
            if len(dl):
                self.l_delta.setText(f"Écart final {dl[-1]:+.3f} s · maxi {dl.max():+.3f} s · mini {dl.min():+.3f} s")
        else:
            self.cv_delta.setData([], [])

    def _hover_hint(self):
        self.l_hover.setText(f"<span style='color:{MUTED}'>Survole les courbes : un curseur vertical affiche ici les valeurs</span>")

    def on_hover(self, pos, pw):
        """Curseur vertical sous la souris (sur les deux graphiques) et valeurs lues à cette distance."""
        inside = pw.getPlotItem().vb.sceneBoundingRect().contains(pos)
        if not self.isVisible() or self._ov is None or not inside:
            if self._ov is not None and self.hv_over.isVisible() and not inside:
                self.hv_over.setVisible(False)
                self.hv_delta.setVisible(False)
                self._hover_hint()
            return
        x = pw.getPlotItem().vb.mapSceneToView(pos).x()
        self.hv_over.setValue(x)
        self.hv_delta.setValue(x)
        self.hv_over.setVisible(True)
        self.hv_delta.setVisible(True)
        label = self.c_chan.currentText()
        unit = label[label.find("(") + 1:label.find(")")] if "(" in label else ""
        parts = [f"<b style='color:{TEXT}'>{x:.0f} m</b>"]
        for nm, col, lab in (("ref", CYAN, "Réf"), ("cmp", ORANGE, "Comparé")):
            if nm in self._ov and len(self._ov[nm][0]) > 1:
                d, v = self._ov[nm]
                parts.append(f"<span style='color:{col}'>{lab} <b>{np.interp(x, d, v):.2f}</b> {unit}</span>")
        if "delta" in self._ov and len(self._ov["delta"][0]) > 1:
            d, v = self._ov["delta"]
            parts.append(f"<span style='color:{YELLOW}'>Écart <b>{np.interp(x, d, v):+.3f}</b> s</span>")
        self.l_hover.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))

    def corners_of(self, item):
        return an.detect_corners(item[1], item[2]) if item else []

    def fill_corners(self):
        a, b = self.sel(self.c_ref), self.sel(self.c_cmp)
        ca = self.corners_of(a)
        cb = self.corners_of(b) if (b and a and b[2] is not a[2]) else []
        pairs = an.compare_corners(ca, cb) if cb else [(x, None) for x in ca]
        t = self.t_corn
        t.setRowCount(0)
        for ca_, cb_ in pairs:
            i = t.rowCount()
            t.insertRow(i)
            da = do = "—"
            ca_col = co_col = None
            if cb_ is not None:
                x, y = cb_["v_apex"] - ca_["v_apex"], cb_["v_out"] - ca_["v_out"]
                da, do = f"{x:+.1f}", f"{y:+.1f}"
                ca_col = GREEN if x > 0.5 else RED if x < -0.5 else None
                co_col = GREEN if y > 0.5 else RED if y < -0.5 else None
            vals = [ca_["n"], ca_["side"], f"{ca_['dist']:.0f} m", f"{ca_['v_in']:.0f}", f"{ca_['v_apex']:.0f}", f"{ca_['v_out']:.0f}",
                    f"{ca_['g_max']:.2f}", "—" if ca_["angle"] is None else f"{ca_['angle']:.0f}°",
                    "—" if ca_["brake_g"] is None else f"{max(0.0, ca_['brake_g']):.2f}", da, do]
            for j, xx in enumerate(vals):
                t.setItem(i, j, _cell(xx, ca_col if j == 9 else co_col if j == 10 else None))
        self._corners = ca

    def fill_gg(self):
        out = []
        for it, sc in ((self.sel(self.c_ref), self.sc_ref), (self.sel(self.c_cmp), self.sc_cmp)):
            if it is None:
                sc.setData([], [])
                continue
            gx, gy = an.gg_points(it[1], it[2])
            sc.setData(gx, gy)
            if len(gx):
                out.append(f"{len(gx)} points · G latéral max {np.nanmax(np.abs(gx)):.2f} · freinage max {-np.nanmin(gy):.2f} · "
                           f"accélération max {np.nanmax(gy):.2f}")
        self.l_gg.setText("   |   ".join(out))

    # ------------------------------------------------------------------ marqueurs
    def lap_of(self, ms):
        if self.A is None:
            return "—"
        i = int(np.searchsorted(self.A.t, ms / 1000.0))
        i = min(max(i, 0), self.A.n - 1)
        return str(self.A.lap[i])

    def fill_marks(self):
        t = self.t_marks
        t.setRowCount(0)
        for m in getattr(self.core, "markers", []):
            i = t.rowCount()
            t.insertRow(i)
            s = m["ms"] / 1000.0
            t.setItem(i, 0, _cell(f"{int(s // 60)}:{s % 60:05.2f}"))
            t.setItem(i, 1, _cell(self.lap_of(m["ms"])))
            t.setItem(i, 2, _cell(m["text"], align=Qt.AlignLeft | Qt.AlignVCenter))

    def add_mark(self):
        add_marker(self.core, self)
        self.fill_marks()

    def del_mark(self):
        r = self.t_marks.currentRow()
        if 0 <= r < len(self.core.markers):
            del self.core.markers[r]
            marks_save(self.core)
            self.fill_marks()

    def goto_mark(self, r, _c):
        if 0 <= r < len(self.core.markers) and self.core.frames:
            total = self.core.frames[-1][0]
            self.core.seek(self.core.markers[r]["ms"] / total if total else 0.0)

    # ------------------------------------------------------------------ exports
    def _ask(self, title, default, filt):
        d = os.path.dirname(getattr(self.core, "primary_path", "") or "") or os.path.expanduser("~")
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, os.path.join(d, default), filt)
        return p

    def _need(self):
        if self.A is None or not self.rows_a:
            QtWidgets.QMessageBox.information(self, "Export", "Ouvrez d'abord une session GPS avec des tours.")
            return False
        return True

    def export_laps(self):
        if not self._need():
            return
        p = self._ask("Tableau des tours", "tours.csv", "CSV (*.csv)")
        if not p:
            return
        sec, mins, theo = an.sector_times(self.A, self.rows_a)
        n = len(mins)
        head = ["Tour", "Temps (s)", "Valide", "Vmax (km/h)", "Vmoy (km/h)"] + [f"S{i + 1} (s)" for i in range(n)]
        an.export_csv(p, head, an.lap_rows_for_export(self.rows_a, sec))

    def export_corners(self):
        if not self._need():
            return
        it = self.sel(self.c_ref)
        if it is None:
            return
        p = self._ask("Virages", "virages.csv", "CSV (*.csv)")
        if not p:
            return
        rows = [[c["n"], c["side"], f"{c['dist']:.0f}", f"{c['v_in']:.1f}", f"{c['v_apex']:.1f}", f"{c['v_out']:.1f}",
                 f"{c['g_max']:.3f}", "" if c["angle"] is None else f"{c['angle']:.1f}"] for c in self.corners_of(it)]
        an.export_csv(p, ["Virage", "Côté", "Distance (m)", "V entrée", "V corde", "V sortie", "G lat max", "Angle max"], rows)

    def export_curves(self):
        c = self.core
        keys = sorted(c.sel, key=lambda k: k[1])
        if not keys or not c.full_t:
            QtWidgets.QMessageBox.information(self, "Export", "Aucune courbe sélectionnée dans la page Courbes.")
            return
        p = self._ask("Courbes sélectionnées", "courbes.csv", "CSV (*.csv)")
        if not p:
            return
        get = core_get(c)
        base = get(keys[0][1])
        t_ms = base[0]
        cols = []
        for k in keys:
            r = get(k[1])
            cols.append(an._interp(r[0], r[1], t_ms) if r is not None else np.full(len(t_ms), np.nan))
        rows = []
        for i in range(0, len(t_ms), max(1, len(t_ms) // 200000)):
            rows.append([f"{t_ms[i] / 1000.0:.3f}"] + ["" if col is None or col[i] != col[i] else f"{col[i]:.4f}" for col in cols])
        an.export_csv(p, ["Temps (s)"] + [c.legend_label(k) for k in keys], rows)

    def _page_pixmap(self):
        win = self.window()
        g = getattr(win, "graph", None)
        return g.grab() if g is not None else None

    def export_png(self):
        pm = self._page_pixmap()
        if pm is None:
            return
        p = self._ask("Image des courbes", "courbes.png", "Image PNG (*.png)")
        if p:
            pm.save(p, "PNG")

    def export_pdf(self):
        if not self._need():
            return
        p = self._ask("Rapport de la session", "rapport.pdf", "PDF (*.pdf)")
        if not p:
            return
        w = QtGui.QPdfWriter(p)
        w.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
        w.setResolution(120)
        w.setPageOrientation(QtGui.QPageLayout.Landscape)
        q = QtGui.QPainter(w)
        W, H = w.width(), w.height()
        name = os.path.basename(getattr(self.core, "primary_path", "") or "session")
        q.setPen(QtGui.QColor("#111111"))
        q.setFont(font(20, True))
        q.drawText(40, 60, f"TrackLab · rapport de session · {name}")
        q.setFont(font(11))
        best = an.best_lap(self.rows_a)
        sec, mins, theo = an.sector_times(self.A, self.rows_a)
        y = 100
        if best:
            q.drawText(40, y, f"Meilleur tour : {an.fmt_time(best['time'])} (tour {best['num']})   ·   "
                              f"Tour théorique : {an.fmt_time(theo)}   ·   {time.strftime('%d/%m/%Y')}")
        y += 40
        cols = [("Tour", 70), ("Temps", 130), ("Écart", 110), ("S1", 100), ("S2", 100), ("S3", 100), ("V max", 100), ("V moy", 100)]
        x = 40
        q.setFont(font(11, True))
        for lab, wd in cols:
            q.drawText(x, y, lab)
            x += wd
        q.setFont(font(11))
        for r in self.rows_a:
            y += 28
            s = sec.get(r["num"]) if r["valid"] else None
            diff = "" if not (best and r["valid"]) else f"{r['time'] - best['time']:+.3f}"
            vals = [r["num"], an.fmt_time(r["time"]), diff] + ([f"{v:.3f}" for v in s] if s else ["", "", ""]) + [f"{r['vmax']:.0f}", f"{r['vmean']:.0f}"]
            q.setPen(QtGui.QColor("#111111" if r["valid"] else "#888888"))
            x = 40
            for v, (_l, wd) in zip(vals, cols):
                q.drawText(x, y, str(v))
                x += wd
        q.setPen(QtGui.QColor("#111111"))
        pm = self._page_pixmap()
        if pm is not None:
            w.newPage()
            q.setFont(font(14, True))
            q.drawText(40, 50, "Courbes")
            sc = min((W - 80) / pm.width(), (H - 120) / pm.height())
            q.drawPixmap(QtCore.QRectF(40, 80, pm.width() * sc, pm.height() * sc), pm, QtCore.QRectF(pm.rect()))
        it = self.sel(self.c_ref)
        if it is not None:
            w.newPage()
            q.setFont(font(14, True))
            q.drawText(40, 50, f"Virages · {it[0]}")
            q.setFont(font(11))
            y = 100
            for c in self.corners_of(it):
                q.drawText(40, y, f"Virage {c['n']} ({c['side']}) à {c['dist']:.0f} m : entrée {c['v_in']:.0f}, corde {c['v_apex']:.0f}, "
                                  f"sortie {c['v_out']:.0f} km/h · {c['g_max']:.2f} g")
                y += 28
        q.end()
