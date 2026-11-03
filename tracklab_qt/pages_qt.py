"""Pages Télémétrie et Trames, et boîtes de dialogue (Qt)."""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.config import GROUP_OF, GROUP_ORDER, TILE_DEFS
from tracklab.names import fr
from tracklab.theme import (BG, BORDER, CARD, CARD2, CYAN, GREEN, HOVER, LIME, MUTED, ORANGE, PINK, RED, SUB, TEXT,
                            YELLOW)
from tracklab.util import disp_unit

from .widgets_qt import Bar, Card, Dot, GearBox, Gauge, Label, Qt, TileBoard, font, qc


def btn_style(color=TEXT, bg=CARD2, size=12):
    return (f"QPushButton{{background:{bg};color:{color};border:none;border-radius:6px;padding:7px 12px;"
            f"font-size:{size}px;font-weight:700;}}QPushButton:hover{{background:{HOVER};}}"
            f"QPushButton:disabled{{color:#34435c;}}")


def btn(text, color=TEXT, bg=CARD2, size=12):
    b = QtWidgets.QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(btn_style(color, bg, size))
    return b


# ------------------------------------------------------------------ télémétrie
class TelemetryPage(QtWidgets.QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        core.badge = {}
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 0, 14, 0)
        root.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(8)
        for c in range(7):
            grid.setColumnStretch(c, 1)
        grid.setRowMinimumHeight(0, 230)
        grid.setRowMinimumHeight(1, 130)

        # régime
        g = Card()
        gl = QtWidgets.QVBoxLayout(g)
        gl.setContentsMargins(14, 10, 8, 6)
        gl.addWidget(Label("Régime moteur", SUB, 13, True))
        core.badge["rpm"] = Label("", YELLOW, 10, True)
        gl.addWidget(core.badge["rpm"])
        core.rpm = Gauge(16000, "tr/min", [], lambda f: GREEN if f < 0.5 else YELLOW if f < 0.8 else RED)
        gl.addWidget(core.rpm, 1)
        grid.addWidget(g, 0, 0, 2, 2)
        # vitesse
        s = Card()
        sl = QtWidgets.QVBoxLayout(s)
        sl.setContentsMargins(14, 10, 8, 6)
        sl.addWidget(Label("Vitesse moto", SUB, 13, True))
        core.badge["speed"] = Label("", YELLOW, 10, True)
        sl.addWidget(core.badge["speed"])
        core.speedg = Gauge(320, "km/h", [], lambda f: CYAN)
        sl.addWidget(core.speedg, 1)
        grid.addWidget(s, 0, 2, 1, 2)
        # rapport
        gc = Card()
        gcl = QtWidgets.QVBoxLayout(gc)
        gcl.setContentsMargins(12, 10, 12, 8)
        gcl.addWidget(Label("Rapport engagé", SUB, 12, True))
        row = QtWidgets.QHBoxLayout()
        core.gear_val = Label("—", TEXT, 40, True)
        core.badge["gear"] = Label("", YELLOW, 10, True)
        row.addWidget(core.gear_val)
        row.addWidget(core.badge["gear"], 0, Qt.AlignBottom)
        row.addStretch(1)
        gcl.addLayout(row)
        core.gear = GearBox(36)
        gcl.addWidget(core.gear)
        grid.addWidget(gc, 0, 4)
        # gaz
        gz = Card()
        gzl = QtWidgets.QVBoxLayout(gz)
        gzl.setContentsMargins(12, 10, 12, 8)
        zt = QtWidgets.QHBoxLayout()
        zt.addWidget(Label("Position gaz", SUB, 12, True))
        core.badge["throttle"] = Label("", GREEN, 10, True)
        zt.addStretch(1)
        zt.addWidget(core.badge["throttle"])
        gzl.addLayout(zt)
        core.throttle_val = Label("—", TEXT, 40, True)
        gzl.addWidget(core.throttle_val)
        core.gaz_bar = Bar(GREEN, 0, 100, 10)
        gzl.addWidget(core.gaz_bar)
        sc = QtWidgets.QHBoxLayout()
        for t in ("0", "50", "100"):
            lb = Label(t, MUTED, 10)
            sc.addWidget(lb, 1, Qt.AlignHCenter)
        gzl.addLayout(sc)
        core.tps_lbl = Label("TPS1 —  ·  TPS2 —", PINK, 11, True)
        gzl.addWidget(core.tps_lbl)
        grid.addWidget(gz, 0, 5, 1, 2)
        core.cards["throttle"] = (core.throttle_val, core.gaz_bar)
        for i, (key, label, unit, color, lo, hi) in enumerate([
            ("temp", "Temp. moteur", "°C", ORANGE, 50, 150), ("oil", "Temp. huile", "°C", YELLOW, 50, 150),
            ("battery", "Tension batterie", "V", LIME, 10, 16), ("front", "Roue AV", "km/h", CYAN, 0, 300),
            ("rear", "Roue AR", "km/h", CYAN, 0, 300)]):
            grid.addWidget(self.mcard(key, label, unit, color, lo, hi), 1, 2 + i)
        top.addLayout(grid, 1)

        # statut système
        st = Card()
        st.setFixedWidth(270)
        stl = QtWidgets.QVBoxLayout(st)
        stl.setContentsMargins(16, 14, 16, 10)
        stl.addWidget(Label("Statut système", TEXT, 15, True))
        stl.addSpacing(6)
        self.srow = {}
        for key, label in (("link", "Liaison"), ("can", "Bus CAN"), ("rx", "Trames CAN"), ("gps", "GPS"),
                           ("wifi", "Signal Wi-Fi"), ("rec", "Enregistrement Tracklab"), ("val", "Validation")):
            r = QtWidgets.QHBoxLayout()
            dot = Dot(MUTED, 9)
            r.addWidget(dot)
            r.addWidget(Label(label, SUB, 12))
            r.addStretch(1)
            v = Label("—", TEXT, 12, True)
            r.addWidget(v)
            stl.addLayout(r)
            self.srow[key] = (dot, v)
        stl.addStretch(1)
        stl.addWidget(Label("Les décodages marqués « à valider »\nsont des hypothèses non confirmées.", MUTED, 11))
        top.addWidget(st)
        root.addLayout(top)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(Label("Toutes les données de télémétrie", TEXT, 17, True))
        core.bus_note = Label("", SUB, 12)
        head.addWidget(core.bus_note)
        head.addStretch(1)
        root.addLayout(head)
        groups = {}
        for cid, name, *_x, unit in TILE_DEFS:
            groups.setdefault(GROUP_OF.get(cid, "Autres"), []).append(((cid, name), fr(name), disp_unit(unit)))
        ordered = [(g_, groups[g_]) for g_ in dict.fromkeys(GROUP_ORDER + list(groups)) if g_ in groups]
        core.tile_unit = {k: u for tiles in groups.values() for k, _l, u in tiles}
        core.board = TileBoard(ordered)
        root.addWidget(core.board, 1)

    def mcard(self, key, label, unit, color, lo, hi):
        core = self.core
        f = Card()
        lay = QtWidgets.QVBoxLayout(f)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        lay.addWidget(Label(label, SUB, 11, True))
        row = QtWidgets.QHBoxLayout()
        val = Label("—", TEXT, 25, True)
        row.addWidget(val)
        if unit:
            row.addWidget(Label(unit, MUTED, 13), 0, Qt.AlignBottom)
        row.addStretch(1)
        lay.addLayout(row)
        core.badge[key] = Label("", YELLOW, 10, True)
        lay.addWidget(core.badge[key])
        bar = Bar(color, lo, hi)
        lay.addWidget(bar)
        sc = QtWidgets.QHBoxLayout()
        sc.addWidget(Label(str(lo), MUTED, 10))
        sc.addStretch(1)
        sc.addWidget(Label(str(hi), MUTED, 10))
        lay.addLayout(sc)
        core.cards[key] = (val, bar)
        return f


# ------------------------------------------------------------------ trames
class FramesModel(QtCore.QAbstractTableModel):
    HEAD = ["#", "Temps", "ID", "DLC", "Hex", "Décimal", "Fréq. (Hz)", "Décodage / signaux"]
    MAXROWS = 400

    def __init__(self):
        super().__init__()
        self.rows = []  # le plus récent en premier
        self.fresh = False

    def rowCount(self, _p=QtCore.QModelIndex()):
        return len(self.rows)

    def columnCount(self, _p=QtCore.QModelIndex()):
        return len(self.HEAD)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEAD[s]
        return None

    def data(self, idx, role=Qt.DisplayRole):
        r = self.rows[idx.row()]
        c = idx.column()
        if role == Qt.DisplayRole:
            return f"0x{r[2]:03X}" if c == 2 else str(r[c])
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if c in (0, 6) else int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.BackgroundRole and self.fresh and idx.row() == 0:
            return QtGui.QBrush(qc("#174a36"))
        return None

    def push(self, row):
        self.beginInsertRows(QtCore.QModelIndex(), 0, 0)
        self.rows.insert(0, row)
        self.endInsertRows()
        if len(self.rows) > self.MAXROWS:
            self.beginRemoveRows(QtCore.QModelIndex(), len(self.rows) - 1, len(self.rows) - 1)
            self.rows.pop()
            self.endRemoveRows()

    def reset(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class FramesPage(QtWidgets.QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 0, 14, 0)
        card = Card()
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        hdr = QtWidgets.QHBoxLayout()
        hdr.addWidget(Label("Trames Tracklab en direct", TEXT, 16, True))
        self.pause_lbl = Label("", YELLOW, 12, True)
        hdr.addWidget(self.pause_lbl)
        hdr.addStretch(1)
        self.chk = QtWidgets.QCheckBox("Trames décodées seulement")
        self.chk.setChecked(core.filter_on.get())
        self.chk.toggled.connect(lambda v: (core.filter_on.set(bool(v)), core.rebuild_table()))
        hdr.addWidget(self.chk)
        self.pause_btn = btn("⏸  Arrêter le direct", YELLOW)
        self.pause_btn.clicked.connect(core.toggle_table_pause)
        hdr.addWidget(self.pause_btn)
        b = btn("Vider", SUB)
        b.clicked.connect(core.clear_table)
        hdr.addWidget(b)
        lay.addLayout(hdr)
        fl = QtWidgets.QHBoxLayout()
        self.ed = {}
        for label, var in (("Afficher les ID (hex)", core.f_show), ("Masquer les ID", core.f_hide), ("Contient", core.f_text)):
            fl.addWidget(Label(label, SUB, 12))
            e = QtWidgets.QLineEdit()
            e.setFixedWidth(170)
            e.textChanged.connect(lambda t, v=var: (v.set(t), core.schedule_filter()))
            fl.addWidget(e)
            fl.addSpacing(8)
            self.ed[label] = e
        class _Fg:  # même API que le champ tk : config(fg=couleur)
            def __init__(self, e):
                self.e = e

            def config(self, fg=None, **_k):
                if fg:
                    self.e.setStyleSheet(f"color:{fg};")

        core.e_show = _Fg(self.ed["Afficher les ID (hex)"])
        core.e_hide = _Fg(self.ed["Masquer les ID"])
        rb = btn("Réinitialiser", SUB)
        rb.clicked.connect(self.reset_filters)
        fl.addWidget(rb)
        fl.addStretch(1)
        self.count = Label("", SUB, 12)
        fl.addWidget(self.count)
        lay.addLayout(fl)
        lay.addWidget(Label("ID en hexadécimal, séparés par des virgules, plages avec un tiret : 100, 2A0-2FF.   "
                            "« Contient » cherche dans l'ID, les octets et le décodage.", MUTED, 11))
        self.model = FramesModel()
        self.view = QtWidgets.QTableView()
        self.view.setModel(self.model)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.setShowGrid(False)
        self.view.setAlternatingRowColors(False)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.view.setFont(font(12, False, "Consolas"))
        hh = self.view.horizontalHeader()
        for i, wd in enumerate((60, 95, 75, 45, 190, 190, 85)):
            self.view.setColumnWidth(i, wd)
        hh.setStretchLastSection(True)
        self.view.setStyleSheet(f"QTableView{{background:{CARD};border:none;color:{TEXT};}}"
                                f"QTableView::item:selected{{background:{HOVER};}}"
                                f"QHeaderView::section{{background:{CARD2};color:{SUB};padding:5px;border:none;font-weight:700;}}")
        lay.addWidget(self.view, 1)
        root.addWidget(card)
        self._ft = QtCore.QTimer(self)
        self._ft.setSingleShot(True)
        self._ft.timeout.connect(core.on_filter_change)

    def reset_filters(self):
        for e in self.ed.values():
            e.setText("")
        self.chk.setChecked(False)
        self.core.reset_filters()

    def filter_changed(self):
        self._ft.start(250)

    def pause_changed(self, paused):
        if paused:
            self.pause_btn.setText("▶  Reprendre le direct")
            self.pause_btn.setStyleSheet(btn_style(GREEN))
            self.pause_lbl.setText("Affichage arrêté · la réception continue")
        else:
            self.pause_btn.setText("⏸  Arrêter le direct")
            self.pause_btn.setStyleSheet(btn_style(YELLOW))
            self.pause_lbl.setText("")

    def rebuild(self):
        c = self.core
        rows, shown = [], 0
        for row in reversed(c.rows):
            if c.row_match(row):
                if shown < FramesModel.MAXROWS:
                    rows.append(row)
                    shown += 1
        self.model.fresh = False
        self.model.reset(rows)
        self.update_count()

    def update_count(self):
        c = self.core
        self.count.setText(f"{len(c.rows)} en mémoire" if c.table_paused
                           else f"{c.matched} trames correspondent · {len(c.rows)} en mémoire")


# ------------------------------------------------------------------ dialogues
class QtDialogs:
    """Mêmes méthodes que tkinter.messagebox / filedialog."""

    def __init__(self, parent_getter):
        self.parent = parent_getter

    def _box(self, icon, title, text, buttons=QtWidgets.QMessageBox.Ok):
        box = QtWidgets.QMessageBox(self.parent())
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        return box.exec()

    def showinfo(self, title, text, **_k):
        self._box(QtWidgets.QMessageBox.Information, title, text)

    def showwarning(self, title, text, **_k):
        self._box(QtWidgets.QMessageBox.Warning, title, text)

    def showerror(self, title, text, **_k):
        self._box(QtWidgets.QMessageBox.Critical, title, text)

    def askokcancel(self, title, text, **_k):
        return self._box(QtWidgets.QMessageBox.Question, title, text,
                         QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel) == QtWidgets.QMessageBox.Ok

    def askyesno(self, title, text, **_k):
        return self._box(QtWidgets.QMessageBox.Question, title, text,
                         QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes

    @staticmethod
    def _filter(filetypes):
        if not filetypes:
            return ""
        return ";;".join(f"{label} ({' '.join(p.split())})" for label, p in filetypes)

    def askopenfilename(self, title="", filetypes=None, **_k):
        p, _f = QtWidgets.QFileDialog.getOpenFileName(self.parent(), title, "", self._filter(filetypes))
        return p

    def asksaveasfilename(self, title="", filetypes=None, defaultextension="", initialfile="", **_k):
        p, _f = QtWidgets.QFileDialog.getSaveFileName(self.parent(), title, initialfile, self._filter(filetypes))
        if p and defaultextension and not os.path.splitext(p)[1]:
            p += defaultextension
        return p
