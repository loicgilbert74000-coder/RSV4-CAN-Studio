"""Fenêtre principale TrackLab (Qt) : barre du haut, platine de lecture, pages et pied de page."""

from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.config import MODELS, SPEEDS  # noqa: F401
from tracklab.theme import BG, BORDER, CARD, CARD2, GREEN, MUTED, RED, SIDE, SUB, TEXT, YELLOW

from .core import Core
from .esp_qt import EspPage, RecPanel, bind
from .graph_qt import GraphPage
from .pages_qt import FramesPage, QtDialogs, TelemetryPage, btn
from .widgets_qt import (Card, DeckButton, DeckLcd, Dot, GearButton, Label, NavTab, ProgressOverlay, Qt, _LcdProxy,
                         font)

PAGES = [("tele", "Télémétrie"), ("graph", "Courbes"), ("frames", "Trames Tracklab"), ("esp", "Paramétrage Tracklab")]


class _StepKeyFilter(QtCore.QObject):
    """Flèches du clavier = pas à pas dans la capture chargée (sauf pendant une saisie de texte)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, ev):
        try:
            if ev.type() == QtCore.QEvent.KeyPress and self.win.isActiveWindow():
                return bool(self.win.handle_step_key(ev))
        except Exception:
            pass
        return False


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TrackLab Electronics · Diagnostic & Télémétrie CAN")
        self._key_filter = _StepKeyFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self._key_filter)
        self.resize(1536, 960)
        self.setMinimumSize(1180, 760)
        try:
            from tracklab.icon_data import ICON_PNG_B64
            import base64

            pm = QtGui.QPixmap()
            pm.loadFromData(base64.b64decode(ICON_PNG_B64))
            self.setWindowIcon(QtGui.QIcon(pm))
        except Exception:
            pass
        self.core = core = Core(self, QtDialogs(lambda: self))
        self.conn_dlg = self.open_dlg = None
        self.rec_panels = []

        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        col = QtWidgets.QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.build_header())
        col.addWidget(self.build_deck())
        self.stack = QtWidgets.QStackedWidget()
        self.tele = TelemetryPage(core)
        self.graph = GraphPage(core)
        self.frames = FramesPage(core)
        self.esp_page = EspPage(core)
        for p in (self.tele, self.graph, self.frames, self.esp_page):
            self.stack.addWidget(p)
        col.addWidget(self.stack, 1)
        col.addWidget(self.build_footer())
        self.progress = ProgressOverlay(root)

        core.apply_model("rsv4")
        core.set_conn_ui(False, "Déconnecté")
        core.set_state("Prêt · ouvrez une capture", MUTED)
        core.show_page("tele")
        core.root.after(40, core.tick)
        core.root.after(16, core.anim_tele)

    # ------------------------------------------------------------------ construction
    def build_header(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("hdr")
        bar.setStyleSheet(f"QFrame#hdr{{background:{SIDE};border:1px solid {BORDER};border-radius:10px;}}")
        outer = QtWidgets.QHBoxLayout(bar)
        outer.setContentsMargins(14, 6, 14, 6)
        logo = QtWidgets.QVBoxLayout()
        logo.setSpacing(0)
        t = Label("TrackLab", RED, 27, True)
        t.setStyleSheet(t.styleSheet() + "font-style:italic;")
        logo.addWidget(t)
        logo.addWidget(Label("ELECTRONICS", TEXT, 11, True))
        outer.addLayout(logo)
        outer.addSpacing(24)
        moto = QtWidgets.QVBoxLayout()
        moto.setSpacing(1)
        moto.addWidget(Label("MOTO", MUTED, 10, True))
        self.model_cb = QtWidgets.QComboBox()
        self.model_cb.addItems([m["label"] for m in MODELS.values()])
        self.model_cb.setMinimumWidth(250)
        self.model_cb.activated.connect(lambda i: self.core.on_model(list(MODELS)[i]))
        moto.addWidget(self.model_cb)
        outer.addLayout(moto)
        outer.addSpacing(28)
        self.tabs = {}
        for key, label in PAGES:
            tab = NavTab(key, label)
            tab.clicked.connect(lambda k: self.core.show_page(k))
            outer.addWidget(tab)
            self.tabs[key] = tab
        outer.addStretch(1)
        self.conn_dot = Dot(MUTED, 10)
        self.conn_lbl = Label("Déconnecté", SUB, 13, True)
        outer.addWidget(self.conn_dot)
        outer.addWidget(self.conn_lbl)
        gear = GearButton()
        gear.clicked.connect(self.core.settings)
        outer.addWidget(gear)
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(wrap)
        lay.setContentsMargins(18, 10, 18, 4)
        lay.addWidget(bar)
        self.core.model_cb = self.model_cb
        return wrap

    def build_deck(self):
        core = self.core
        bar = Card()
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(4)

        def sep():
            f = QtWidgets.QFrame()
            f.setFixedSize(1, 28)
            f.setStyleSheet(f"background:{BORDER};")
            lay.addSpacing(4)
            lay.addWidget(f)
            lay.addSpacing(4)

        core.key_open = DeckButton("eject", "OUVRIR A", core.open_file, color="#3cc0ff", width=64)
        core.key_open_b = DeckButton("eject", "OUVRIR B", core.open_compare, color="#ff8a3d", width=64)
        lay.addWidget(core.key_open)
        lay.addWidget(core.key_open_b)
        sep()
        core.key_start = DeckButton("start", "DÉBUT", core.reset, color="#3cc0ff")
        core.key_play = DeckButton("play", "LECTURE", core.play, color=GREEN)
        core.key_pause = DeckButton("pause", "PAUSE", core.pause, color=YELLOW)
        core.key_speed = DeckButton("text", "VITESSE", core.cycle_speed, color="#3cc0ff", text="x1")
        for k in (core.key_start, core.key_play, core.key_pause, core.key_speed):
            lay.addWidget(k)
        sep()
        core.rec_btn = DeckButton("rec", "ENREG.", core.rec_toggle, color=RED)
        core.rec_btn.set_look(enabled=False)
        lay.addWidget(core.rec_btn)
        sep()
        self.lcd_widget = DeckLcd(core.seek)
        core.lcd = _LcdProxy(self.lcd_widget)
        lay.addWidget(self.lcd_widget, 1)
        sep()
        core.conn_btn = DeckButton("plug", "CONNEXION", core.on_conn_button, color=GREEN, width=72)
        lay.addWidget(core.conn_btn)
        wrap = QtWidgets.QWidget()
        wl = QtWidgets.QHBoxLayout(wrap)
        wl.setContentsMargins(18, 4, 18, 6)
        wl.addWidget(bar)
        return wrap

    def build_footer(self):
        foot = QtWidgets.QFrame()
        foot.setObjectName("foot")
        foot.setStyleSheet(f"QFrame#foot{{background:{SIDE};border:1px solid {BORDER};border-radius:8px;}}")
        lay = QtWidgets.QHBoxLayout(foot)
        lay.setContentsMargins(16, 4, 14, 4)
        self.dot = Dot(MUTED, 10)
        lay.addWidget(self.dot)
        self.status = Label("", SUB, 12, True)
        lay.addWidget(self.status)
        self.footnote = Label("", YELLOW, 12)
        lay.addWidget(self.footnote)
        lay.addStretch(1)
        lay.addWidget(Dot(MUTED, 10))
        lay.addWidget(Label("Enregistrement : non disponible", MUTED, 12, True))
        lay.addSpacing(30)
        self.fl = {}
        for key, label, value in (("frames", "Trames reçues", "0"), ("rate", "Trames/s", "—"), ("ids", "ID actifs", "0"),
                                  ("dur", "Durée", "00:00")):
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(Label(label.upper(), MUTED, 9, True), 0, Qt.AlignRight)
            v = Label(value, TEXT, 13, True)
            box.addWidget(v, 0, Qt.AlignRight)
            lay.addLayout(box)
            lay.addSpacing(10)
            self.fl[key] = v
        wrap = QtWidgets.QWidget()
        wl = QtWidgets.QHBoxLayout(wrap)
        wl.setContentsMargins(18, 0, 18, 8)
        wl.addWidget(foot)
        return wrap

    # ------------------------------------------------------------------ services pour le cœur
    def single_shot(self, ms, fn):
        QtCore.QTimer.singleShot(ms, fn)

    def process_events(self):
        QtWidgets.QApplication.processEvents()

    def on_state(self, text, color):
        self.status.setText(text)
        self.dot.set(color)

    def progress_show(self, text, pct):
        self.progress.show_progress(text, pct)
        QtWidgets.QApplication.processEvents()

    def progress_hide(self):
        self.progress.hide()
        QtWidgets.QApplication.processEvents()

    def show_page(self, key):
        idx = [k for k, _l in PAGES].index(key)
        self.stack.setCurrentIndex(idx)
        for k, tab in self.tabs.items():
            tab.set_on(k == key)
        if key == "frames":
            self.frames.rebuild()

    def apply_model_ui(self, key):
        core = self.core
        m = MODELS[key]
        self.footnote.setText("   " + m["note"])
        n = m["rpm_max"] // 1000
        core.rpm.set_scale(m["rpm_max"], [(k / n, str(k)) for k in range(0, n + 1, 2)])
        core.speedg.set_scale(m["speed_max"], [(i / 4, str(int(m["speed_max"] * i / 4))) for i in range(5)])
        for k in ("front", "rear"):
            core.cards[k][1].hi = m["speed_max"]
        for k in core.badge:
            state, color = core.badge_state(k)
            core.badge[k].config(text=state, fg=color)
        self.model_cb.setCurrentIndex(list(MODELS).index(key))
        core.bus_note.config(text="Décodage : définition can1.xml · valeurs à valider" if core.decoder
                             else "Aucun décodage pour cette moto · voir « Trames Tracklab »")

    def set_conn_ui(self, live, text):
        core = self.core
        self.conn_dot.set(GREEN if live else MUTED)
        self.conn_lbl.config(text=text, fg=GREEN if live else SUB)
        core.conn_btn.set_look(lit=live, kind="unplug" if live else "plug", caption="DÉCONNEXION" if live else "CONNEXION")
        if live and self.conn_dlg is not None:
            self.conn_dlg.close()

    def set_link_label(self, text, dot, fg):
        self.conn_dot.set(dot)
        self.conn_lbl.config(text=text, fg=fg)

    def show_footer(self, key, text):
        self.fl[key].setText(text)

    def set_status_row(self, key, text, color):
        dot, label = self.tele.srow[key]
        dot.set(color)
        label.config(text=text)

    # ---- tableau des trames
    def table_new_row(self, row):
        if self.core.current_page == "frames":
            self.frames.model.fresh = True
            self.frames.model.push(row)

    def table_clear(self):
        self.frames.model.reset([])
        self.frames.update_count()

    def table_rebuild(self):
        self.frames.rebuild()

    def table_count(self):
        self.frames.update_count()

    def table_pause_changed(self, paused):
        self.frames.pause_changed(paused)
        if not paused:
            self.frames.rebuild()

    def table_filter_changed(self):
        self.frames.filter_changed()

    # ---- enregistrements
    def rec_info(self, text):
        for p in self.rec_panels_alive():
            if p.info.text() != text:
                p.info.setText(text)

    def rec_panels_alive(self):
        return [self.esp_page.rec_panel] + [p for p in self.rec_panels if p.isVisible()]

    def rec_refresh(self):
        for p in self.rec_panels_alive():
            p.refresh()

    def set_rec_state(self, text, color, label, enabled, on):
        core = self.core
        self.esp_page.set_rec_state(text, color, label, enabled, on)
        core.rec_btn.set_look(lit=on, kind="stop" if on else "rec", caption="STOP" if on else "ENREG.", enabled=enabled)

    def update_esp_live(self, now, rate):
        self.esp_page.update_live(now, rate)

    # ---- pas à pas au clavier
    STEP_KEYS = {QtCore.Qt.Key_Right: 1, QtCore.Qt.Key_Left: -1, QtCore.Qt.Key_Down: 1, QtCore.Qt.Key_Up: -1}


    def handle_step_key(self, ev):
        core = self.core
        fw = QtWidgets.QApplication.focusWidget()
        if isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            return False
        if isinstance(fw, QtWidgets.QComboBox) and fw.view().isVisible():
            return False
        if not core.frames or core.live or core.current_page not in ("graph", "frames", "tele"):
            return False
        k = ev.key()
        mods = ev.modifiers()
        if k in self.STEP_KEYS:
            n = self.STEP_KEYS[k]
            if mods & QtCore.Qt.ShiftModifier:
                n *= 10
            if mods & QtCore.Qt.ControlModifier:
                n *= 100
            if core.current_page == "frames" and k in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down) and not (mods & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier)):
                return False  # dans le tableau, haut/bas défilent normalement
            core.step_frames(n)
            return True
        if k == QtCore.Qt.Key_Home:
            core.reset()
            return True
        if k == QtCore.Qt.Key_End:
            core.seek(1.0)
            return True
        return False

    def graph_ensure_cursor(self):
        self.graph.ensure_cursor()

    # ---- courbes
    def graph_fit_all(self):
        self.graph.request_fit()

    def graph_changed(self):
        pass

    def graph_selection_changed(self):
        self.graph._sig = None

    # ------------------------------------------------------------------ boîtes de dialogue
    def open_connection_dialog(self):
        if self.conn_dlg is not None and self.conn_dlg.isVisible():
            self.conn_dlg.raise_()
            return
        core = self.core
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Connexion")
        d.setModal(False)
        lay = QtWidgets.QVBoxLayout(d)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(Label("Connexion", TEXT, 20, True))
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(18)
        source = QtWidgets.QComboBox()
        source.addItems(["Wi-Fi ESP32", "USB-CAN (série)"])
        bind(source, core.transport, "combo")
        form.addRow("Source", source)
        port = QtWidgets.QComboBox()
        port.setEditable(True)
        port.addItems([f"COM{i}" for i in range(1, 21)])
        bind(port, core.port, "combo")
        baud = QtWidgets.QComboBox()
        baud.addItems(["2000000", "1000000", "500000", "250000"])
        bind(baud, core.baud, "combo")
        bit = QtWidgets.QComboBox()
        bit.addItems(core.model["bitrates"])
        host = QtWidgets.QLineEdit()
        bind(host, core.host)
        tcp = QtWidgets.QLineEdit()
        bind(tcp, core.tcp_port)
        rows = {"serial": [("Port COM", port), ("Vitesse série", baud), ("Débit CAN", bit)],
                "wifi": [("Adresse ESP32", host), ("Port TCP", tcp)]}
        labels = {}
        for grp, items in rows.items():
            for text, w in items:
                lb = Label(text, SUB, 12)
                form.addRow(lb, w)
                labels[w] = (lb, grp)

        def show_rows():
            wifi = core.transport.get().startswith("Wi-Fi")
            for w, (lb, grp) in labels.items():
                on = (grp == "wifi") == wifi
                w.setVisible(on)
                lb.setVisible(on)

        source.currentTextChanged.connect(lambda _t: show_rows())
        show_rows()
        lay.addLayout(form)
        b = btn("Connecter", "#ffffff", RED, 13)
        b.clicked.connect(core.toggle_connect)
        lay.addWidget(b)
        self.conn_dlg = d
        d.show()

    def open_choice(self):
        core = self.core
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Ouvrir")
        d.resize(560, 420)
        lay = QtWidgets.QVBoxLayout(d)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(Label("Ouvrir", TEXT, 20, True))
        b = btn("Un fichier du PC…  (trames CAN, RaceBox, RaceChrono, Tracklab)", TEXT, CARD2, 13)
        b.clicked.connect(lambda: (d.close(), core.open_pc_file()))
        lay.addWidget(b)
        lay.addWidget(Label("Enregistrements Tracklab (carte et copies du PC)", SUB, 13, True))
        panel = RecPanel(core, 8)
        lay.addWidget(panel, 1)
        self.rec_panels = [p for p in self.rec_panels if p.isVisible()] + [panel]
        if core.live:
            core.rec_list()
        self.open_dlg = d
        d.show()

    def close_dialogs(self):
        if self.open_dlg is not None:
            self.open_dlg.close()
            self.open_dlg = None

    def open_settings(self):
        core = self.core
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Paramètres")
        d.setMinimumWidth(460)
        lay = QtWidgets.QVBoxLayout(d)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.addWidget(Label("Paramètres", TEXT, 20, True))
        form = QtWidgets.QFormLayout()
        port = QtWidgets.QLineEdit()
        bind(port, core.port)
        baud = QtWidgets.QLineEdit()
        bind(baud, core.baud)
        form.addRow("Port série", port)
        form.addRow("Vitesse série (bauds)", baud)
        lay.addLayout(form)
        ck = QtWidgets.QCheckBox("Afficher les décodages expérimentaux (non validés)")
        bind(ck, core.experimental, "check")
        ck.toggled.connect(lambda _v: core.prebuild())
        lay.addWidget(ck)
        lay.addWidget(Label(f"Moto sélectionnée : {core.model['label']}", SUB, 12, True))
        lay.addWidget(Label("Connexion USB-CAN : réception uniquement.\nMode Silent à configurer avec le logiciel officiel.",
                            YELLOW, 12))
        d.show()
        self._settings = d

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.progress.isVisible():
            self.progress.show_progress(self.progress.lbl.text(), self.progress.bar.value())
