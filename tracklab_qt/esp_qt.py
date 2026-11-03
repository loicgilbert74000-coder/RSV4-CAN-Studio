"""Page Paramétrage Tracklab (Qt) et liste des enregistrements."""

from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.espconfig import LED_DEFAULT
from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, GREEN, HOVER, LIME, MUTED, RED, SUB, TEXT, YELLOW

from .pages_qt import btn, btn_style
from .widgets_qt import Card, Dot, Label, Qt, font, painter, qc


# ------------------------------------------------------------------ champs liés aux variables du cœur
def bind(widget, var, kind="text"):
    """Relie un champ Qt à une variable du cœur (dans les deux sens)."""
    guard = {"on": False}

    def to_var(*_a):
        if guard["on"]:
            return
        if kind == "text":
            var.set(widget.text())
        elif kind == "check":
            var.set(widget.isChecked())
        else:
            var.set(widget.currentText())

    def to_widget():
        guard["on"] = True
        try:
            v = var.get()
            if kind == "text":
                widget.setText(str(v))
            elif kind == "check":
                widget.setChecked(bool(v))
            else:
                widget.setCurrentText(str(v))
        finally:
            guard["on"] = False

    to_widget()
    if kind == "text":
        widget.textChanged.connect(to_var)
    elif kind == "check":
        widget.toggled.connect(to_var)
    else:
        widget.currentTextChanged.connect(to_var)
    var.trace_add("write", to_widget)
    return widget


def entry(var, width=90):
    e = QtWidgets.QLineEdit()
    e.setFixedWidth(width)
    return bind(e, var)


class RecPanel(QtWidgets.QWidget):
    """Enregistrements de la carte Tracklab et copies du PC : liste, ouvrir, supprimer, actualiser."""

    COLS = ["N°", "Date", "Taille", "Où", "État"]

    def __init__(self, core, rows=7):
        super().__init__()
        self.core = core
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.table = QtWidgets.QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((56, 140, 80, 100)):
            self.table.setColumnWidth(i, w)
        self.table.setMinimumHeight(24 * rows + 30)
        self.table.setStyleSheet(f"QTableWidget{{background:{CARD};border:1px solid {BORDER};color:{TEXT};}}"
                                 f"QTableWidget::item:selected{{background:{HOVER};}}"
                                 f"QHeaderView::section{{background:{CARD2};color:{SUB};padding:4px;border:none;font-weight:700;}}")
        self.table.doubleClicked.connect(lambda *_: self.act(core.rec_open_entry))
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        for text, fn in (("Ouvrir", lambda: self.act(core.rec_open_entry)),
                         ("Supprimer", lambda: self.act(core.rec_delete_entry)), ("Actualiser", core.rec_list)):
            b = btn(text, TEXT, CARD2, 12)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.info = Label("", SUB, 12)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.entries = []
        self.refresh()

    def act(self, fn):
        sel = self.table.currentRow()
        if sel < 0 or sel >= len(self.entries):
            self.core.dlg.showinfo("Enregistrements Tracklab", "Choisissez d'abord un enregistrement dans la liste.")
            return
        fn(self.entries[sel])

    def refresh(self):
        c = self.core
        keep = self.entries[self.table.currentRow()]["n"] if 0 <= self.table.currentRow() < len(self.entries) else None
        self.entries = c.rec_entries()
        self.table.setRowCount(len(self.entries))
        for i, e in enumerate(self.entries):
            color = RED if e["cur"] else (GREEN if e["local"] else YELLOW)
            for j, text in enumerate(c.entry_row(e, c.live)):
                it = QtWidgets.QTableWidgetItem(text)
                it.setForeground(QtGui.QBrush(qc(color if j == 4 else TEXT)))
                if j in (0, 2):
                    it.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                self.table.setItem(i, j, it)
            if e["n"] == keep:
                self.table.selectRow(i)


class WifiBar(QtWidgets.QWidget):
    """Échelle du signal Wi-Fi (dBm) avec repère."""

    LO, HI = -90, -40

    def __init__(self):
        super().__init__()
        self.rssi = None
        self.setFixedSize(340, 40)

    def set(self, rssi):
        if rssi != self.rssi:
            self.rssi = rssi
            self.update()

    def paintEvent(self, _e):
        p = painter(self)
        x = lambda d: (d - self.LO) / (self.HI - self.LO) * 320 + 6
        for a, b, col in ((self.LO, -80, RED), (-80, -70, YELLOW), (-70, -60, LIME), (-60, self.HI, GREEN)):
            p.setPen(Qt.NoPen)
            p.setBrush(qc(col))
            p.drawRect(QtCore.QRectF(x(a), 6, x(b) - x(a), 12))
        p.setFont(font(10))
        for d in (-80, -70, -60):
            p.setPen(qc(BG))
            p.drawLine(QtCore.QPointF(x(d), 6), QtCore.QPointF(x(d), 22))
            p.setPen(qc(SUB))
            p.drawText(QtCore.QRectF(x(d) - 18, 24, 36, 14), Qt.AlignCenter, str(d))
        if self.rssi is not None:
            pos = x(max(self.LO, min(self.HI, self.rssi)))
            p.setPen(QtGui.QPen(qc(BG), 1))
            p.setBrush(qc(TEXT))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(pos - 5, 0), QtCore.QPointF(pos + 5, 0), QtCore.QPointF(pos, 9)]))


class EspPage(QtWidgets.QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 0, 18, 0)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(Label("Paramétrage Tracklab", TEXT, 17, True))
        bar.addSpacing(10)
        bar.addWidget(Label("Enregistrements, bus CAN, GPS et entrées/sorties (ESP32-S3 DevKitC-1)", SUB, 12))
        bar.addStretch(1)
        for text, fn in (("Charger (JSON)", core.load_esp), ("Enregistrer (JSON)", core.save_esp),
                         ("Générer rsv4_config.h", core.export_header), ("Appliquer à l'application", core.apply_esp)):
            b = btn(text, TEXT, CARD2, 12)
            b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        cols = QtWidgets.QHBoxLayout(inner)
        cols.setContentsMargins(0, 0, 6, 0)
        cols.setSpacing(12)
        left, right = QtWidgets.QVBoxLayout(), QtWidgets.QVBoxLayout()
        left.setSpacing(10)
        right.setSpacing(10)
        lw, rw = QtWidgets.QWidget(), QtWidgets.QWidget()
        lw.setLayout(left)
        rw.setLayout(right)
        lw.setFixedWidth(500)
        cols.addWidget(lw)
        cols.addWidget(rw, 1)
        cv = core.cv

        # ---- enregistrements
        c = self.card(left, "Enregistrements Tracklab (bouton physique ou TrackLab)")
        top = QtWidgets.QHBoxLayout()
        self.rec_dot = Dot(MUTED, 10)
        top.addWidget(self.rec_dot)
        self.rec_state = Label("—", TEXT, 12, True)
        top.addWidget(self.rec_state)
        top.addStretch(1)
        self.rec_btn2 = btn("Démarrer", "#ffffff", RED)
        self.rec_btn2.clicked.connect(core.rec_toggle)
        top.addWidget(self.rec_btn2)
        c.addLayout(top)
        self.rec_panel = RecPanel(core)
        c.addWidget(self.rec_panel)
        fo = QtWidgets.QHBoxLayout()
        lab = Label("Téléchargés automatiquement dans : " + core.REC_DIR, MUTED, 11)
        lab.setWordWrap(True)
        fo.addWidget(lab, 1)
        ob = btn("Ouvrir le dossier", TEXT, CARD2, 11)
        ob.clicked.connect(core.rec_open_folder)
        fo.addWidget(ob)
        c.addLayout(fo)

        # ---- état en direct
        c = self.card(left, "État de la carte (en direct)")
        self.live_rows = {}
        for key, label in (("link", "Liaison"), ("can", "Bus CAN"), ("gps", "GPS"), ("wifi", "Signal Wi-Fi")):
            r = QtWidgets.QHBoxLayout()
            dot = Dot(MUTED, 9)
            r.addWidget(dot)
            r.addWidget(Label(label, SUB, 12))
            r.addStretch(1)
            val = Label("—", TEXT, 12, True)
            r.addWidget(val)
            c.addLayout(r)
            self.live_rows[key] = (dot, val)
        self.wifi_bar = WifiBar()
        c.addWidget(self.wifi_bar)
        hint = Label("Signal du PC mesuré par l'ESP32 (dBm) :\nBon ≥ −60 · Correct −60 à −70 · Faible −70 à −80 "
                     "(coupures possibles) · Très faible < −80 (liaison instable)\nPlus la valeur est proche de 0, "
                     "meilleur est le signal. Rapprocher la carte ou changer de canal Wi-Fi si « Faible ».", MUTED, 11)
        hint.setWordWrap(True)
        c.addWidget(hint)
        self._live_shown = {}

        # ---- CAN / GPS
        c = self.card(left, "Bus CAN")
        c.addWidget(self.check("Bus CAN activé (désactiver pour tester sans moto)", cv["can_on"]))
        c.addLayout(self.field("Débit (kbit/s)", cv["can_bitrate"], ["250", "500"]))
        c.addLayout(self.field("Broche TX (vers le transceiver)", cv["can_tx"]))
        c.addLayout(self.field("Broche RX (vers le transceiver)", cv["can_rx"]))
        c = self.card(left, "GPS (UART)")
        c.addWidget(self.check("GPS activé (trames 0x7F0 et 0x7F8)", cv["gps_on"]))
        c.addLayout(self.field("Broche RX (depuis le module GPS)", cv["gps_rx"]))
        c.addLayout(self.field("Broche TX (vers le RX du GPS, -1 = non câblée)", cv["gps_tx"]))
        c.addLayout(self.field("Débit (bauds)", cv["gps_baud"], ["9600", "38400", "115200"]))
        left.addStretch(1)

        # ---- entrées / sorties
        c = self.card(right, "Entrées numériques (trame 0x7F9, bit par entrée)")
        self.io_grid(c, ["Entrée", "Broche", "Nom", "Active"], [(f"E{n + 1}", cv[f"dig{n}_pin"], cv[f"dig{n}_name"], None,
                                                                  cv[f"dig{n}_on"]) for n in range(8)])
        c = self.card(right, "Entrées analogiques ADC (trame 0x7F9, 0 à 4095)")
        self.io_grid(c, ["Entrée", "Broche", "Nom", "Active"], [(f"ADC{n + 1}", cv[f"ana{n}_pin"], cv[f"ana{n}_name"], None,
                                                                  cv[f"ana{n}_on"]) for n in range(3)])
        c = self.card(right, "Sorties (niveau appliqué au démarrage)")
        self.io_grid(c, ["Sortie", "Broche", "Nom", "Niveau", "Active"],
                     [(f"S{n + 1}", cv[f"out{n}_pin"], cv[f"out{n}_name"], cv[f"out{n}_level"], cv[f"out{n}_on"])
                      for n in range(2)])
        c = self.card(right, "Voyants du tableau de bord (LED)")
        for color, label in (("green", "Verte · liaison"), ("red", "Rouge · défaut CAN"), ("blue", "Bleue · activité CAN")):
            c.addLayout(self.field(label, cv[f"led_{color}"]))
        c = self.card(right, "Enregistrement : bouton et carte SD")
        c.addLayout(self.field("Bouton poussoir (entre la broche et GND)", cv["rec_button"]))
        c.addWidget(self.check("Module carte SD présent (sinon mémoire interne, durée limitée)", cv["rec_sd"]))
        for key, label in (("cs", "SD · CS"), ("mosi", "SD · MOSI"), ("miso", "SD · MISO"), ("sck", "SD · SCK")):
            c.addLayout(self.field(label, cv[f"rec_{key}"]))
        note = Label("Les broches et réglages sont appliqués au firmware par « Générer rsv4_config.h » puis recompilation "
                     "du firmware.\nLes entrées/sorties sont lues par le firmware ; les sorties ne sont pas pilotées "
                     "depuis l'application.", MUTED, 11)
        note.setWordWrap(True)
        right.addWidget(note)
        right.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    # ---- fabrication des cartes et champs
    def card(self, col, title):
        card = Card()
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(5)
        lay.addWidget(Label(title, TEXT, 13, True))
        col.addWidget(card)
        return lay

    def field(self, label, var, values=None):
        r = QtWidgets.QHBoxLayout()
        r.addWidget(Label(label, SUB, 12), 1)
        if values:
            cb = QtWidgets.QComboBox()
            cb.addItems(values)
            cb.setFixedWidth(100)
            bind(cb, var, "combo")
            r.addWidget(cb)
        else:
            r.addWidget(entry(var, 90))
        return r

    @staticmethod
    def check(label, var):
        ck = QtWidgets.QCheckBox(label)
        return bind(ck, var, "check")

    def io_grid(self, lay, heads, rows):
        g = QtWidgets.QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(3)
        for j, h in enumerate(heads):
            g.addWidget(Label(h, MUTED, 11, True), 0, j)
        for i, (name, pin, label, level, on) in enumerate(rows, start=1):
            g.addWidget(Label(name, SUB, 12), i, 0)
            g.addWidget(entry(pin, 60), i, 1)
            g.addWidget(entry(label, 190), i, 2)
            col = 3
            if level is not None:
                cb = QtWidgets.QComboBox()
                cb.addItems(["Haut", "Bas"])
                cb.setFixedWidth(70)
                bind(cb, level, "combo")
                g.addWidget(cb, i, col)
                col += 1
            ck = QtWidgets.QCheckBox()
            bind(ck, on, "check")
            g.addWidget(ck, i, col)
        g.setColumnStretch(len(heads), 1)
        lay.addLayout(g)

    # ---- mises à jour depuis le cœur
    def update_live(self, now, rate):
        c = self.core
        states = c.module_states(now, rate)
        esp = c.esp if c.link_state(now) == "ok" else None
        if esp and esp["rssi"] is not None:
            states["wifi"] = (states["wifi"][0] + f" · {esp['stations']} appareil(s)", states["wifi"][1])
        for key, (dot, val) in self.live_rows.items():
            state = states[key]
            if self._live_shown.get(key) != state:
                self._live_shown[key] = state
                dot.set(state[1])
                val.config(text=state[0])
        self.wifi_bar.set(esp["rssi"] if esp and esp["rssi"] is not None else None)

    def set_rec_state(self, text, color, label, enabled, on):
        self.rec_dot.set(color)
        self.rec_state.config(text=text)
        self.rec_btn2.setText(label)
        self.rec_btn2.setEnabled(enabled)
        self.rec_btn2.setStyleSheet(btn_style("#ffffff", CARD2 if on else RED))
