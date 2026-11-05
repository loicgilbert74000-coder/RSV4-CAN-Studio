"""Onglets d'analyse moto de la page Analyse : freinage et reprise, régularité, évolution, adhérence, wheelie / patinage,
moteur et rapports. Tout est calculé à partir des fichiers (G, angle, gyroscope, vitesses de roues, CAN) ; les valeurs
« estimées » ne viennent pas du calculateur de la moto."""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from tracklab import analysis as an
from tracklab.theme import BG, CYAN, GREEN, MUTED, ORANGE, RED, SUB, TEXT, YELLOW

from .pages_qt import btn
from .widgets_qt import Label, Qt

WHEELIE_CAN = ("clip((([Speed_Rear] - [Speed_Front]) / max([Speed_Front], 20) * 100 - 2) / 6, 0, 1)"
               " * clip(([Lon_Acc] - 0.4) / 0.4, 0, 1)")
WHEELIE_GPS = "clip(abs([GyroY]) / 70, 0, 1) * clip(([G longitudinal] - 0.4) / 0.4, 0, 1)"
SLIP = "([Speed_Rear] - [Speed_Front]) / max([Speed_Front], 20) * 100"


def _fmt(v, nd=1, suffix=""):
    return "—" if v is None or v != v else f"{v:.{nd}f}{suffix}"


class MotoTabs:
    def __init__(self, page):
        from .analyse_qt import _cell, _table

        self.page = page
        self._cell, self._table = _cell, _table
        tabs = page.tabs

        # -- Freinage & reprise
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.t_brake = _table(["Virage", "Freinage (avant corde)", "Décélération max", "Durée", "Vitesse perdue",
                               "Trail braking", "Angle en freinant", "Reprise (après corde)", "Angle à la reprise",
                               "Vitesse à +100 m", "Δ dist. frein (cmp)", "Δ V +100 m (cmp)"])
        v.addWidget(self.t_brake, 1)
        v.addWidget(Label("Freinage = G longitudinal sous −0,25 g avant la corde. Trail braking = temps où l'on freine incliné de plus de 10°. "
                          "Reprise = première accélération soutenue (> 0,10 g) après la corde : d'après le G longitudinal, le TPS n'est pas "
                          "décodé. Δ : tour comparé moins référence.", MUTED, 11))
        tabs.addTab(w, "Freinage && reprise")

        # -- Régularité
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.l_loss = Label("", YELLOW, 13, True)
        v.addWidget(self.l_loss)
        self.t_line = self._table(["Virage", "Côté", "Distance", "Tours", "V corde moyenne", "Écart-type", "Meilleure V corde",
                                   "Meilleur passage", "Perte moyenne", "Perte maxi"])
        v.addWidget(self.t_line, 1)
        v.addWidget(Label("Classé par perte moyenne décroissante : le virage du haut est celui où tu perds le plus par rapport à ton meilleur "
                          "passage (tours valides uniquement).", MUTED, 11))
        tabs.addTab(w, "Régularité")

        # -- Évolution
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.l_trend = Label("", YELLOW, 13, True)
        v.addWidget(self.l_trend)
        self.p_time = pg.PlotWidget(background=BG)
        self.p_ang = pg.PlotWidget(background=BG)
        for pw, lab, col in ((self.p_time, "Temps au tour (s)", CYAN), (self.p_ang, "Angle max (°)", ORANGE)):
            pw.showGrid(x=True, y=True, alpha=0.15)
            pw.setLabel("left", lab)
            pw.setLabel("bottom", "Tour")
        self.cv_time = self.p_time.plot([], [], pen=pg.mkPen(CYAN, width=2), symbol="o", symbolSize=8, symbolBrush=CYAN)
        self.cv_ang = self.p_ang.plot([], [], pen=pg.mkPen(ORANGE, width=2), symbol="o", symbolSize=8, symbolBrush=ORANGE)
        self.fit_time = self.p_time.plot([], [], pen=pg.mkPen(MUTED, width=1, style=QtCore.Qt.DashLine))
        self.fit_ang = self.p_ang.plot([], [], pen=pg.mkPen(MUTED, width=1, style=QtCore.Qt.DashLine))
        v.addWidget(self.p_time, 1)
        v.addWidget(self.p_ang, 1)
        tabs.addTab(w, "Évolution")

        # -- Adhérence
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.l_grip = Label("", YELLOW, 13, True)
        v.addWidget(self.l_grip)
        self.t_grip = self._table(["Virage", "Côté", "G combiné (95e centile)", "Adhérence utilisée", "Marge"])
        v.addWidget(self.t_grip, 1)
        v.addWidget(Label("100 % = G combiné (latéral + longitudinal) dépassé seulement 2 % du temps sur toute la session : c'est TA limite "
                          "observée, pas celle des pneus. Vert : de la marge, rouge : à la limite.", MUTED, 11))
        tabs.addTab(w, "Adhérence")

        # -- Wheelie / patinage
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.l_slip = Label("", YELLOW, 12, True)
        v.addWidget(self.l_slip)
        self.t_ev = self._table(["Tour", "Wheelies", "Durée wheelie (s)", "Stoppies", "Durée stoppie (s)", "Patinage arrière max (%)"])
        v.addWidget(self.t_ev, 1)
        row = QtWidgets.QHBoxLayout()
        b1 = btn("Ajouter la voie « Patinage arrière % (calculé) »", CYAN)
        b1.clicked.connect(lambda: self.add_channel("Patinage arrière % (calculé)", "%", SLIP, need=("Speed_Front", "Speed_Rear")))
        b2 = btn("Ajouter la voie « Wheelie (calculé, estimé) »", CYAN)
        b2.clicked.connect(self.add_wheelie)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(Label("Voies ESTIMÉES à partir des mesures, pas lues dans le calculateur de la moto (TC / anti-wheeling). Patinage arrière = "
                          "(roue arrière − roue avant) / roue avant, vitesses de roues CAN, au-dessus de 20 km/h. Wheelie 0..1 : roue avant plus "
                          "lente que l'arrière ET accélération > 0,4 g (CAN), sinon vitesse de tangage au gyroscope ET accélération (fichier GPS). "
                          "Stoppie : freinage > 0,9 g avec roue arrière plus lente ou fort tangage. Seuils d'événement : 0,5.", MUTED, 11))
        tabs.addTab(w, "Wheelie / patinage")

        # -- Moteur & rapports
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.l_eng = Label("", YELLOW, 12, True)
        v.addWidget(self.l_eng)
        self.t_eng = self._table(["Tour", "Régime max", "Régime moyen", "Près du rupteur (s)", "Temp. moteur max", "Temp. huile max"])
        v.addWidget(self.t_eng, 1)
        self.t_gear = self._table(["Virage", "Rapport entrée", "Rapport corde", "Rapport sortie", "Régime entrée", "Régime corde",
                                   "Régime sortie"])
        v.addWidget(self.t_gear, 1)
        tabs.addTab(w, "Moteur && rapports")

    # ------------------------------------------------------------------ calculs
    def _ref(self):
        it = self.page.sel(self.page.c_ref)
        return it

    def fill(self):
        pg_ = self.page
        a, b = self._ref(), self.page.sel(self.page.c_cmp)
        S = pg_.A
        for t in (self.t_brake, self.t_line, self.t_grip, self.t_ev, self.t_eng, self.t_gear):
            t.setRowCount(0)
        for lab in (self.l_loss, self.l_trend, self.l_grip, self.l_slip, self.l_eng):
            lab.setText("")
        for cv in (self.cv_time, self.cv_ang, self.fit_time, self.fit_ang):
            cv.setData([], [])
        if S is None or not pg_.rows_a:
            return
        self.fill_brake(a, b)
        self.fill_line(S)
        self.fill_trend()
        self.fill_grip(a)
        self.fill_events(S)
        self.fill_engine(S, a)

    def _rows(self, table, rows):
        for vals, colors in rows:
            i = table.rowCount()
            table.insertRow(i)
            for j, x in enumerate(vals):
                table.setItem(i, j, self._cell(x, colors[j] if colors else None))

    def fill_brake(self, a, b):
        if a is None:
            return
        ca = an.detect_corners(a[1], a[2])
        ma = [an.corner_metrics(a[1], a[2], c) for c in ca]
        mb_by_n = {}
        if b is not None and b[2] is not a[2]:
            cb = an.detect_corners(b[1], b[2])
            for ca_, cb_ in an.compare_corners(ca, cb):
                if cb_ is not None:
                    mb_by_n[ca_["n"]] = an.corner_metrics(b[1], b[2], cb_)
        out = []
        for m in ma:
            o = mb_by_n.get(m["n"])
            d1 = d2 = "—"
            col = [None] * 12
            if o is not None:
                if "brake_dist" in m and "brake_dist" in o:
                    x = o["brake_dist"] - m["brake_dist"]
                    d1 = f"{x:+.0f} m"
                if "v_plus100" in m and "v_plus100" in o:
                    y = o["v_plus100"] - m["v_plus100"]
                    d2 = f"{y:+.1f}"
                    col[11] = GREEN if y > 1 else RED if y < -1 else None
            tr = "—" if "trail_dur" not in m else f"{m['trail_dur']:.1f} s ({100 * m['trail_ratio']:.0f} %)"
            out.append(([m["n"], _fmt(m.get("brake_dist"), 0, " m"), _fmt(m.get("brake_g"), 2, " g"),
                         _fmt(m.get("brake_dur"), 1, " s"), _fmt(m.get("brake_lost"), 0, " km/h"), tr,
                         _fmt(m.get("trail_angle"), 0, "°"), _fmt(m.get("reprise_dist"), 0, " m"), _fmt(m.get("reprise_angle"), 0, "°"),
                         _fmt(m.get("v_plus100"), 0, " km/h"), d1, d2], col))
        self._rows(self.t_brake, out)

    def fill_line(self, S):
        lq = an.line_quality(S, self.page.rows_a)
        self._rows(self.t_line, [([x["n"], x["side"], f"{x['dist']:.0f} m", x["laps"], f"{x['apex_mean']:.1f}", f"± {x['apex_std']:.1f}",
                                   f"{x['apex_best']:.0f}", f"{x['t_best']:.2f} s", f"{x['loss_mean']:.3f} s", f"{x['loss_max']:.3f} s"],
                                  [None] * 8 + [RED if x["loss_mean"] > 0.25 else YELLOW if x["loss_mean"] > 0.12 else GREEN, None])
                                 for x in lq])
        if lq:
            tot = sum(x["loss_mean"] for x in lq)
            self.l_loss.setText(f"Où tu perds le plus : virage {lq[0]['n']} ({lq[0]['loss_mean']:.2f} s en moyenne) · "
                                f"perte moyenne cumulée sur les virages : {tot:.2f} s par tour")
        else:
            self.l_loss.setText("Il faut au moins 2 tours valides pour mesurer la régularité")

    def fill_trend(self):
        tr = an.lap_trend(self.page.rows_a)
        if len(tr["laps"]) < 2:
            return
        x = np.array(tr["laps"], float)
        self.cv_time.setData(x, tr["time"])
        self.cv_ang.setData(x, [np.nan if q is None else q for q in tr["angle"]])
        txt = []
        for key, fit, y in (("time", self.fit_time, tr["time"]), ("angle", self.fit_ang, tr["angle"])):
            if key in tr["slope"]:
                yy = np.array(y, float)
                k = tr["slope"][key]
                c0 = np.polyfit(np.arange(len(x)), yy, 1)[1]
                fit.setData(x, c0 + k * np.arange(len(x)))
        if "time" in tr["slope"]:
            k = tr["slope"]["time"]
            verdict = "tu t'améliores" if k < -0.05 else "tu faiblis" if k > 0.05 else "stable"
            txt.append(f"temps : {k:+.2f} s par tour ({verdict})")
        if "angle" in tr["slope"]:
            txt.append(f"angle max : {tr['slope']['angle']:+.2f}° par tour")
        if "glat" in tr["slope"]:
            txt.append(f"G latéral max : {tr['slope']['glat']:+.3f} g par tour")
        self.l_trend.setText("Tendance sur les tours valides — " + " · ".join(txt) if txt else "")

    def fill_grip(self, a):
        S = self.page.A
        ref = an.grip_reference(S)
        if not ref or a is None:
            self.l_grip.setText("Il faut le G latéral et le G longitudinal pour mesurer l'adhérence utilisée")
            return
        mean = an.grip_usage(S, a[2], None, ref)
        self.l_grip.setText(f"G combiné de référence : {ref:.2f} g (100 %) · utilisation moyenne en virage sur ce tour : "
                            f"{_fmt(mean, 0, ' %')}")
        rows = []
        for c in an.detect_corners(S, a[2]):
            u = an.grip_usage(S, a[2], c, ref)
            g = u * ref / 100.0
            rows.append(([c["n"], c["side"], f"{g:.2f} g", f"{u:.0f} %", f"{100 - u:+.0f} %"],
                         [None, None, None, RED if u >= 100 else YELLOW if u >= 90 else GREEN, None]))
        self._rows(self.t_grip, rows)

    def fill_events(self, S):
        valid = [r for r in self.page.rows_a if r["valid"]] or self.page.rows_a
        w, st = an.wheelie_score(S), an.stoppie_score(S)
        ew, es = an.count_events(S, w, valid), an.count_events(S, st, valid)
        sl = an.slip_rear(S)
        rows = []
        for r in valid:
            n = r["num"]
            mx = None if sl is None else float(np.nanmax(sl[r["i0"]:r["i1"]]))
            rows.append(([n, ew.get(n, (None, None))[0] if w is not None else "—", _fmt(ew.get(n, (0, None))[1] if w is not None else None, 1),
                          es.get(n, (None, None))[0] if st is not None else "—", _fmt(es.get(n, (0, None))[1] if st is not None else None, 1),
                          _fmt(mx, 1)], None))
        self._rows(self.t_ev, rows)
        notes = []
        if sl is None:
            notes.append("pas de vitesses de roues dans ce fichier : patinage non calculable")
        if w is None:
            notes.append("ni gyroscope ni vitesses de roues : wheelie non estimable")
        self.l_slip.setText("Estimations — " + " · ".join(notes) if notes else "Estimations calculées (voir la note ci-dessous)")

    def fill_engine(self, S, a):
        eng = an.engine_by_lap(S, [r for r in self.page.rows_a if r["valid"]] or self.page.rows_a)
        if not eng:
            self.l_eng.setText("Aucune voie CAN (régime, rapport, températures) dans ce fichier : ouvre une capture CAN ou RaceChrono "
                               "avec CAN pour remplir cet onglet")
            return
        self._rows(self.t_eng, [([e["num"], f"{e['rpm_max']:.0f}", f"{e['rpm_mean']:.0f}", f"{e['limiter_s']:.1f}",
                                  _fmt(e["eng"], 0, " °C"), _fmt(e["oil"], 0, " °C")], None) for e in eng])
        gs = an.gear_shift_speeds(S)
        self.l_eng.setText("Passages de rapport (vitesse moyenne) : " + " · ".join(f"{a_}→{b_} à {v:.0f} km/h" for (a_, b_), v in gs.items())
                           if gs else "Pas de rapport engagé dans ce fichier")
        if a is not None:
            rows = []
            for c in an.detect_corners(S, a[2]):
                m = an.corner_gear_rpm(S, c)
                g = m.get("gear", (None,) * 3)
                r = m.get("rpm", (None,) * 3)
                rows.append(([c["n"], _fmt(g[0], 0), _fmt(g[1], 0), _fmt(g[2], 0), _fmt(r[0], 0), _fmt(r[1], 0), _fmt(r[2], 0)], None))
            self._rows(self.t_gear, rows)

    # ------------------------------------------------------------------ voies calculées
    def add_channel(self, name, unit, formula, need=()):
        from .analyse_qt import add_math_channel, core_get

        get = core_get(self.page.core)
        missing = [n for n in need if get(n) is None]
        if missing:
            QtWidgets.QMessageBox.information(self.page, "Voie calculée", "Signaux absents de ce fichier : " + ", ".join(missing))
            return None
        try:
            return add_math_channel(self.page.core, name, unit, formula)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self.page, "Voie calculée", str(exc))
            return None

    def add_wheelie(self):
        from .analyse_qt import core_get

        get = core_get(self.page.core)
        if all(get(n) is not None for n in ("Speed_Front", "Speed_Rear", "Lon_Acc")):
            self.add_channel("Wheelie 0-1 (calculé, estimé)", "", WHEELIE_CAN)
        else:
            self.add_channel("Wheelie 0-1 (calculé, estimé)", "", WHEELIE_GPS, need=("GyroY", "G longitudinal"))
