"""Fenêtre principale de TrackLab Electronics."""

import queue
import threading
import time
import tkinter as tk
from collections import Counter, deque
from tkinter import messagebox, ttk

from .config import DEFAULT_CURVES, MODELS, SPEEDS
from .connection import ConnectionMixin
from .decoding import DecodingMixin
from .page_esp import EspMixin
from .page_frames import FramesMixin
from .page_graph import GraphMixin
from .page_telemetry import TelemetryMixin
from .player import PlayerMixin
from .theme import BG, BORDER, CARD, CARD2, CYAN, FONT, GREEN, HOVER, MUTED, RED, SIDE, SUB, TEXT, YELLOW
from .util import fmt_time
from .widgets import NavIcon, SeekBar, make_dot, set_dot


class App(TelemetryMixin, GraphMixin, EspMixin, FramesMixin, PlayerMixin, DecodingMixin, ConnectionMixin):
    """Fenêtre principale."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TrackLab Electronics · Diagnostic & Télémétrie CAN")
        self.root.geometry("1536x960")
        self.root.minsize(1280, 860)
        self.root.configure(bg=BG)
        self.frames = []
        self.idx = 0
        self.playing = False
        self.speed = tk.DoubleVar(value=1.0)
        self.status = tk.StringVar(value="Prêt · ouvrez une capture")
        self.file_name = tk.StringVar(value="Aucun fichier")
        self.clock = tk.StringVar(value="00:00 / 00:00")
        self.transport = tk.StringVar(value="USB-CAN (série)")
        self.port = tk.StringVar(value="COM7")
        self.baud = tk.StringVar(value="2000000")
        self.host = tk.StringVar(value="192.168.4.1")
        self.tcp_port = tk.StringVar(value="2323")
        self.experimental = tk.BooleanVar(value=True)
        self.filter_on = tk.BooleanVar(value=True)
        self.window = tk.IntVar(value=60)
        self.stack = tk.BooleanVar(value=False)
        self.sel = set(DEFAULT_CURVES)
        self._srow_shown = {}
        self._footer_shown = {}
        self._map_state = None
        self.count = Counter()
        self.first_t = {}
        self.last_t = {}
        self.vals = {}
        self.hist = {}
        self.dirty = set()
        self.flash_until = {}
        self.track = deque(maxlen=30000)
        self.t_now = 0
        self.recent = deque()
        self.ingested = 0
        self.t_last = 0
        self.t0 = 0
        self.last_row = None
        self.start_wall = 0
        self.start_frame = 0
        self.q = queue.Queue()
        self.live = False
        self.stop_event = threading.Event()
        self.cards = {}
        self.pages = {}
        self.nav = {}
        self.flushables = []
        self.srow = {}
        self.fl = {}
        self.badge = {}
        self.decoder = None
        self.model_key = "rsv4"
        self.hist_max = 20000
        self.full_t = {}
        self.full_v = {}
        self.rows = deque(maxlen=8000)
        self.matched = 0
        self.bulk = False
        self.f_show = tk.StringVar()
        self.f_hide = tk.StringVar()
        self.f_text = tk.StringVar()
        self.id_show = None
        self.id_hide = None
        self.ftext = ""
        self._fid = None
        self.count_text = ""
        self.frame_times = []
        self.seek_target = None
        self.seek_resume = False
        self.view_end = None
        self.ref_key = None
        self.band_h = {}
        self.grips = []
        self.layout = []
        self.legend_hits = []
        self.drag = None
        self.default_band = 120
        self.current_page = "tele"
        self.side_collapsed = False
        self.auto_collapsed = False
        self.cv = {}
        self.build_esp_vars()
        self.set_styles()
        self.build_footer()
        self.build_sidebar()
        self.build_main()
        self.apply_model("rsv4")
        self.show_page("tele")
        self.set_conn_ui(False, "Déconnecté")
        self.set_state("Prêt · ouvrez une capture", MUTED)
        self.root.after(40, self.tick)
        self.root.after(180, self.paint_chart)
        self.root.after(400, self.paint_map)

    # ---------- modèle ----------
    @property
    def model(self):
        return MODELS[self.model_key]

    def apply_model(self, key):
        self.model_key = key
        m = MODELS[key]
        self.decoder = m["decoder"]
        self.subtitle.config(text=m["subtitle"])
        self.footnote.config(text="   " + m["note"])
        n = m["rpm_max"] // 1000
        self.rpm.set_scale(m["rpm_max"], [(k / n, str(k)) for k in range(0, n + 1, 2)])
        self.speedg.set_scale(m["speed_max"], [(i / 4, str(int(m["speed_max"] * i / 4))) for i in range(5)])
        for k in ("front", "rear"):
            self.cards[k][1].hi = m["speed_max"]
            self.cards[k][1].dirty = True
        for k in self.badge:
            state, color = self.badge_state(k)
            self.badge[k].config(text=state, fg=color)
        self.bitrate_cb.config(values=m["bitrates"])
        self.bitrate_cb.current(0)
        self.model_cb.current(list(MODELS).index(key))
        self.bus_note.config(
            text="Décodage : définition can1.xml · valeurs à valider" if self.decoder else "Aucun décodage pour cette moto · voir « Trames CAN »"
        )
        self.clear_data()

    def badge_state(self, key):
        if self.decoder is None:
            return ("NON DÉCODÉ", MUTED)
        if key in self.model["validated"]:
            return ("VALIDÉ", GREEN)
        return ("À VALIDER", YELLOW)

    def on_model(self, e=None):
        key = list(MODELS)[self.model_cb.current()]
        if self.live:
            self.disconnect()
        self.pause()
        self.apply_model(key)
        if self.frames:
            self.set_state(f"Modèle : {self.model['label']}", SUB)
            self.prebuild()

    # ---------- style & widgets ----------
    def set_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(
            "Treeview",
            background=CARD,
            foreground=TEXT,
            fieldbackground=CARD,
            rowheight=24,
            borderwidth=0,
            relief="flat",
            bordercolor=CARD,
            lightcolor=CARD,
            darkcolor=CARD,
            font=(FONT, 9),
        )
        s.configure(
            "Treeview.Heading",
            background=CARD2,
            foreground=SUB,
            relief="flat",
            font=(FONT, 8, "bold"),
            padding=5,
        )
        s.map("Treeview", background=[("selected", HOVER)], foreground=[("selected", TEXT)])
        s.map("Treeview.Heading", background=[("active", HOVER)])
        s.configure(
            "Vertical.TScrollbar",
            background="#45567a",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=TEXT,
            lightcolor="#45567a",
            darkcolor="#45567a",
            gripcount=0,
            arrowsize=15,
        )
        s.map("Vertical.TScrollbar", background=[("active", "#6a80ad")])
        s.configure(
            "Horizontal.TScrollbar",
            background="#45567a",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=TEXT,
            lightcolor="#45567a",
            darkcolor="#45567a",
            gripcount=0,
            arrowsize=15,
        )
        s.map("Horizontal.TScrollbar", background=[("active", "#6a80ad")])
        s.configure(
            "TCombobox",
            fieldbackground=CARD2,
            background=CARD2,
            foreground=TEXT,
            arrowcolor=SUB,
            bordercolor=BORDER,
            lightcolor=CARD2,
            darkcolor=CARD2,
            padding=3,
        )
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", CARD2)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", CARD2)],
            selectforeground=[("readonly", TEXT)],
        )

    def card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1, bd=0)

    def reg(self, widget):
        self.flushables.append(widget)
        return widget

    def button(self, parent, text, command, color=TEXT, bg=CARD2, anchor="center", font=10):
        b = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=color,
            activebackground=HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=7,
            font=(FONT, font, "bold"),
            cursor="hand2",
            anchor=anchor,
        )
        b.bind("<Enter>", lambda e: b.config(bg=HOVER))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def section(self, parent, text):
        tk.Label(
            parent, text=text, fg=MUTED, bg=SIDE, font=(FONT, 8, "bold")
        ).pack(anchor="w", padx=20, pady=(14, 4))

    def nav_item(self, parent, key, label):
        row = tk.Frame(parent, bg=SIDE, cursor="hand2")
        row.pack(fill="x", padx=10, pady=1)
        bar = tk.Frame(row, bg=SIDE, width=4)
        bar.pack(side="left", fill="y")
        ico = NavIcon(row, key, SIDE)
        ico.pack(side="left", padx=(12, 0))
        lbl = tk.Label(
            row,
            text=label,
            bg=SIDE,
            fg=TEXT,
            font=(FONT, 11, "bold"),
            anchor="w",
            padx=4,
            pady=9,
            cursor="hand2",
        )
        lbl.pack(side="left", fill="x", expand=True)
        def go(e=None, k=key):
            if k == "settings":
                self.settings()
            else:
                self.show_page(k)
        for w in (row, bar, ico, lbl):
            w.bind("<Button-1>", go)
        self.nav[key] = (row, bar, lbl, ico)

    def scroll_area(self, parent, bg, width=None):
        """Zone défilable verticalement : renvoie (conteneur à placer, cadre intérieur à remplir)."""
        wrap = tk.Frame(parent, bg=bg)
        canvas = tk.Canvas(wrap, bg=bg, highlightthickness=0, width=width or 300)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=bg)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        def wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return (wrap, inner)

    # ---------- structure ----------
    def build_footer(self):
        foot = tk.Frame(self.root, bg=SIDE, highlightbackground=BORDER, highlightthickness=1)
        foot.pack(side="bottom", fill="x")
        self.fl["dot"] = make_dot(foot, MUTED, SIDE, 10)
        self.fl["dot"].pack(side="left", padx=(16, 8), pady=10)
        tk.Label(foot, textvariable=self.status, fg=SUB, bg=SIDE, font=(FONT, 9, "bold")).pack(side="left")
        self.footnote = tk.Label(foot, text="", fg=YELLOW, bg=SIDE, font=(FONT, 9))
        self.footnote.pack(side="left")
        self.fl["dur"] = self.stat(foot, "Durée", "00:00")
        self.fl["ids"] = self.stat(foot, "ID actifs", "0")
        self.fl["rate"] = self.stat(foot, "Trames/s", "—")
        self.fl["frames"] = self.stat(foot, "Trames reçues", "0")
        rec = tk.Frame(foot, bg=SIDE)
        rec.pack(side="right", padx=14)
        make_dot(rec, MUTED, SIDE, 10).pack(side="left", padx=(0, 6))
        tk.Label(
            rec, text="Enregistrement : non disponible", fg=MUTED, bg=SIDE, font=(FONT, 9, "bold")
        ).pack(side="left")

    def stat(self, parent, label, value):
        box = tk.Frame(parent, bg=SIDE)
        box.pack(side="right", padx=14, pady=6)
        tk.Label(box, text=label.upper(), fg=MUTED, bg=SIDE, font=(FONT, 7, "bold")).pack(anchor="e")
        lbl = tk.Label(box, text=value, fg=TEXT, bg=SIDE, font=(FONT, 10, "bold"))
        lbl.pack(anchor="e")
        return lbl

    def build_sidebar(self):
        side = tk.Frame(self.root, bg=SIDE, width=250, highlightbackground=BORDER, highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.side = side
        strip = tk.Frame(self.root, bg=SIDE, width=36, highlightbackground=BORDER, highlightthickness=1)
        strip.pack_propagate(False)
        tk.Button(
            strip,
            text="»",
            command=self.toggle_side,
            bg=SIDE,
            fg=TEXT,
            activebackground=HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(FONT, 14, "bold"),
            cursor="hand2",
        ).pack(pady=(12, 0), fill="x")
        self.side_strip = strip
        tk.Button(
            side,
            text="«",
            command=self.toggle_side,
            bg=SIDE,
            fg=SUB,
            activebackground=HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(FONT, 13, "bold"),
            cursor="hand2",
        ).place(relx=1.0, x=-8, y=10, anchor="ne")
        logo = tk.Frame(side, bg=SIDE)
        logo.pack(fill="x", padx=20, pady=(20, 6))
        tk.Label(logo, text="TrackLab", fg=RED, bg=SIDE, font=(FONT, 24, "bold italic")).pack(anchor="w")
        tk.Label(logo, text="ELECTRONICS", fg=TEXT, bg=SIDE, font=(FONT, 11, "bold")).pack(anchor="w")

        self.section(side, "MOTO")
        mc = tk.Frame(side, bg=SIDE)
        mc.pack(fill="x", padx=14, pady=2)
        self.model_cb = ttk.Combobox(
            mc, values=[m["label"] for m in MODELS.values()], state="readonly", font=(FONT, 9)
        )
        self.model_cb.pack(fill="x")
        self.model_cb.bind("<<ComboboxSelected>>", self.on_model)

        self.section(side, "NAVIGATION")
        self.nav_item(side, "tele", "Télémétrie")
        self.nav_item(side, "graph", "Courbes")
        self.nav_item(side, "frames", "Trames CAN")
        self.nav_item(side, "esp", "Paramétrage ESP32")
        self.nav_item(side, "settings", "Paramètres")

        self.section(side, "CONNEXION")
        card = self.card(side)
        card.pack(fill="x", padx=14, pady=2)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=12, pady=8)
        def row(label, widget):
            r = tk.Frame(inner, bg=CARD)
            tk.Label(r, text=label, bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", width=12).pack(side="left")
            widget(r).pack(side="right")
            return r
        tr = tk.Frame(inner, bg=CARD)
        tr.pack(fill="x", pady=2)
        tk.Label(tr, text="Source", bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", width=12).pack(side="left")
        self.transport_cb = ttk.Combobox(
            tr,
            textvariable=self.transport,
            values=["USB-CAN (série)", "Wi-Fi ESP32"],
            state="readonly",
            width=15,
        )
        self.transport_cb.pack(side="right")
        self.transport_cb.bind("<<ComboboxSelected>>", self.on_transport)
        row("Mode CAN", lambda p: self.ro_combo(p, ["Silent (écoute)"])).pack(fill="x", pady=2)
        row("Type trame", lambda p: self.ro_combo(p, ["Standard 11 bits"])).pack(fill="x", pady=2)
        r_port = row(
            "Port COM",
            lambda p: ttk.Combobox(
                p, textvariable=self.port, values=[f"COM{i}" for i in range(1, 21)], width=13
            ),
        )
        r_baud = row(
            "Vitesse",
            lambda p: ttk.Combobox(
                p, textvariable=self.baud, values=["2000000", "1000000", "500000", "250000"], width=13
            ),
        )
        r_br = tk.Frame(inner, bg=CARD)
        tk.Label(
            r_br, text="CAN bitrate", bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", width=12
        ).pack(side="left")
        self.bitrate_cb = ttk.Combobox(r_br, state="readonly", width=13)
        self.bitrate_cb.pack(side="right")
        self.serial_rows = [r_port, r_baud, r_br]
        entry = lambda p, var: tk.Entry(
            p,
            textvariable=var,
            width=14,
            bg=CARD2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        r_host = row("Adresse ESP32", lambda p: entry(p, self.host))
        r_tcp = row("Port TCP", lambda p: entry(p, self.tcp_port))
        self.wifi_rows = [r_host, r_tcp]
        st = tk.Frame(inner, bg=CARD)
        st.pack(fill="x", pady=(8, 6))
        self.conn_status = st
        self.conn_dot = make_dot(st, MUTED, CARD, 10)
        self.conn_dot.pack(side="left", padx=(2, 6))
        self.conn_lbl = tk.Label(st, text="Déconnecté", bg=CARD, fg=SUB, font=(FONT, 10, "bold"))
        self.conn_lbl.pack(side="left")
        self.conn_btn = tk.Button(
            inner,
            text="Connecter",
            command=self.toggle_connect,
            bg=RED,
            fg="#ffffff",
            activebackground="#ff3b44",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(FONT, 10, "bold"),
            cursor="hand2",
            pady=6,
        )
        self.conn_btn.pack(fill="x")
        self.on_transport()

    def on_transport(self, e=None):
        wifi = self.transport.get().startswith("Wi-Fi")
        for r in self.serial_rows + self.wifi_rows:
            r.pack_forget()
        for r in self.wifi_rows if wifi else self.serial_rows:
            r.pack(fill="x", pady=2, before=self.conn_status)

    def ro_combo(self, parent, values):
        c = ttk.Combobox(parent, values=values, state="readonly", width=15)
        c.current(0)
        return c

    def build_main(self):
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.main = main
        head = tk.Frame(main, bg=BG)
        head.pack(fill="x", padx=22, pady=(14, 4))
        tabs = tk.Frame(head, bg=BG)
        tabs.pack(side="right")
        self.tabs = {}
        for key, label in [
            ("tele", "Télémétrie"), ("graph", "Courbes"), ("frames", "Trames CAN"), ("esp", "ESP32")
        ]:
            b = tk.Button(
                tabs,
                text=label,
                command=lambda k=key: self.show_page(k),
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=12,
                pady=6,
                font=(FONT, 9, "bold"),
                cursor="hand2",
            )
            b.pack(side="left", padx=2)
            self.tabs[key] = b
        tk.Label(
            head, text="Diagnostic & Télémétrie CAN", fg=TEXT, bg=BG, font=(FONT, 18, "bold")
        ).pack(side="left")
        self.subtitle = tk.Label(head, text="", fg=SUB, bg=BG, font=(FONT, 11))
        self.subtitle.pack(side="left", padx=(14, 0), pady=(6, 0))
        self.build_playbar(main)
        self.area = tk.Frame(main, bg=BG)
        self.area.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.area.grid_rowconfigure(0, weight=1)
        self.area.grid_columnconfigure(0, weight=1)
        self.page_tele = tk.Frame(self.area, bg=BG)
        self.page_graph = tk.Frame(self.area, bg=BG)
        self.page_frames = tk.Frame(self.area, bg=BG)
        self.page_esp = tk.Frame(self.area, bg=BG)
        self.pages = {
            "tele": self.page_tele, "graph": self.page_graph, "frames": self.page_frames, "esp": self.page_esp
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self.build_tele(self.page_tele)
        self.build_graph(self.page_graph)
        self.build_table(self.page_frames)
        self.build_esp(self.page_esp)

    def build_playbar(self, main):
        bar = tk.Frame(main, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x", padx=18, pady=(4, 8))
        inner = tk.Frame(bar, bg=CARD)
        inner.pack(fill="x", padx=12, pady=8)
        self.button(
            inner, "Ouvrir un fichier .txt", self.open_file, TEXT, CARD2, font=9
        ).pack(side="left", padx=2)
        self.button(inner, "Lecture", self.play, GREEN, CARD2, font=9).pack(side="left", padx=2)
        self.button(inner, "Pause", self.pause, YELLOW, CARD2, font=9).pack(side="left", padx=2)
        self.button(inner, "Début", self.reset, SUB, CARD2, font=9).pack(side="left", padx=2)
        tk.Label(inner, text="Vitesse", bg=CARD, fg=SUB, font=(FONT, 9)).pack(side="left", padx=(14, 4))
        cb = ttk.Combobox(inner, values=list(SPEEDS), state="readonly", width=6)
        cb.set("x1")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.speed.set(SPEEDS[cb.get()]))
        tk.Label(
            inner, textvariable=self.file_name, bg=CARD, fg=SUB, font=(FONT, 9), anchor="w"
        ).pack(side="left", padx=(14, 0))
        tk.Label(
            inner, textvariable=self.clock, bg=CARD, fg=TEXT, font=(FONT, 9, "bold")
        ).pack(side="right", padx=(8, 0))
        self.seekbar = SeekBar(inner, on_seek=self.seek, on_drag=self.on_seek_drag, width=360)
        self.seekbar.pack(side="right", padx=8)

    def show_page(self, key):
        self.current_page = key
        # la barre latérale change AVANT d'afficher la page, et la mise en page est calculée page cachée
        if key == "graph":
            self.collapse_side(auto=True)
        elif self.auto_collapsed:
            self.expand_side()
        self.root.update_idletasks()
        for name, page in self.pages.items():  # une page masquée n'est plus mise en page à chaque redimensionnement
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        for k, (row, bar, lbl, ico) in self.nav.items():
            on = k == key
            row.config(bg=HOVER if on else SIDE)
            bar.config(bg=RED if on else SIDE)
            lbl.config(bg=HOVER if on else SIDE, fg=TEXT if on else SUB)
            ico.paint(HOVER if on else SIDE, RED if on else SUB)
        for k, b in self.tabs.items():
            b.config(
                bg=RED if k == key else CARD2,
                fg="#ffffff" if k == key else SUB,
                activebackground=HOVER,
                activeforeground=TEXT,
            )

    def collapse_side(self, auto=False):
        if self.side_collapsed:
            return
        self.side.pack_forget()
        self.side_strip.pack(side="left", fill="y", before=self.main)
        self.side_collapsed = True
        self.auto_collapsed = auto

    def expand_side(self):
        if not self.side_collapsed:
            return
        self.side_strip.pack_forget()
        self.side.pack(side="left", fill="y", before=self.main)
        self.side_collapsed = False
        self.auto_collapsed = False

    def toggle_side(self):
        if self.side_collapsed:
            self.expand_side()
        else:
            self.collapse_side(auto=False)

    # ---------- état ----------
    def set_state(self, text, color):
        self.status.set(text)
        set_dot(self.fl["dot"], color)

    def set_conn_ui(self, live, text):
        set_dot(self.conn_dot, GREEN if live else MUTED)
        self.conn_lbl.config(text=text, fg=GREEN if live else SUB)
        self.conn_btn.config(
            text="Déconnecter" if live else "Connecter",
            bg=CARD2 if live else RED,
            activebackground=HOVER if live else "#ff3b44",
        )

    # ---------- boucle ----------
    def update_status(self):
        now = int(time.monotonic() * 1000) if self.live else self.t_last
        while self.recent and self.recent[0] < now - 1000:
            self.recent.popleft()
        rate = len(self.recent) if self.live or self.frames else 0
        if self.frames:
            total = self.frames[-1][0]
            cur = self.frames[self.idx - 1][0] if self.idx > 0 else 0
            self.seekbar.set(cur / total if total else 0)
            self.clock.set(f"{fmt_time(cur)} / {fmt_time(total)}")
            dur = cur
        else:
            dur = now - self.t0 if self.live else 0
        self.show_footer("dur", fmt_time(dur))
        self.show_footer("ids", str(len(self.count)))
        self.show_footer("rate", str(rate) if rate else "—")
        self.show_footer("frames", f"{self.ingested:,}".replace(",", " "))
        if self.current_page == "frames":
            self.refresh_count()
        if self.current_page != "tele":
            return  # le panneau « Statut système » n'existe que sur la page Télémétrie
        if self.live:
            self.set_srow("can", "Connecté", GREEN)
            if rate:
                self.set_srow("rx", f"OK · {rate}/s", GREEN)
            else:
                self.set_srow("rx", "Aucune trame", RED)
            self.set_srow("qual", "Bonne" if rate else "—", GREEN if rate else MUTED)
        else:
            self.set_srow("can", "Déconnecté", MUTED)
            self.set_srow("rx", "Aucune" if not self.frames else f"Fichier · {len(self.count)} IDs", MUTED)
            self.set_srow("qual", "—", MUTED)
        if self.track:
            self.set_srow("gps", f"{len(self.track)} points", GREEN)
        else:
            self.set_srow("gps", "Aucun fix" if self.live else "Non disponible", MUTED)
        self.set_srow("rec", "Non disponible", MUTED)
        self.set_srow("val", self.model["short"], YELLOW if self.decoder else MUTED)

    def show_footer(self, key, text):
        """Texte du pied de page ; ne touche l'écran que s'il a changé."""
        if self._footer_shown.get(key) != text:
            self._footer_shown[key] = text
            self.fl[key].config(text=text)

    def tick(self):
        """Boucle principale (25 fois par seconde) : lecture, réception, mise à jour de ce qui est visible."""
        if self.playing and self.frames:
            elapsed = (time.monotonic() - self.start_wall) * 1000 * self.speed.get()
            limit = self.start_frame + elapsed
            batch = 0
            while self.idx < len(self.frames) and self.frames[self.idx][0] <= limit and (batch < 1200):
                self.ingest(*self.frames[self.idx])
                self.idx += 1
                batch += 1
            if self.idx >= len(self.frames):
                self.playing = False
                self.set_state("Lecture terminée", CYAN)
        for _ in range(400):
            try:
                cid, data = self.q.get_nowait()
            except queue.Empty:
                break
            if cid == "error":
                self.disconnect()
                messagebox.showerror("Connexion", data)
            else:
                self.ingest(int(time.monotonic() * 1000), cid, data)
        if self.current_page == "tele":  # les jauges et tuiles cachées se mettent à jour au retour sur la page
            self.refresh_tiles()
            for widget in self.flushables:
                widget.flush()
        self.update_status()
        self.root.after(40, self.tick)

    def settings(self):
        win = tk.Toplevel(self.root)
        win.title("Paramètres")
        win.configure(bg=CARD)
        win.geometry("460x330")
        win.resizable(False, False)
        tk.Label(
            win, text="Paramètres", fg=TEXT, bg=CARD, font=(FONT, 14, "bold")
        ).pack(anchor="w", padx=24, pady=(18, 6))
        for label, var in [("Port série", self.port), ("Vitesse série (bauds)", self.baud)]:
            tk.Label(
                win, text=label, bg=CARD, fg=SUB, font=(FONT, 9, "bold")
            ).pack(anchor="w", padx=24, pady=(10, 3))
            tk.Entry(
                win,
                textvariable=var,
                width=28,
                bg=CARD2,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                highlightbackground=BORDER,
                highlightthickness=1,
            ).pack(anchor="w", padx=24, ipady=4)
        tk.Checkbutton(
            win,
            text="Afficher les décodages expérimentaux (non validés)",
            variable=self.experimental,
            command=self.prebuild,
            bg=CARD,
            fg=TEXT,
            selectcolor=CARD2,
            activebackground=CARD,
            activeforeground=TEXT,
        ).pack(anchor="w", padx=20, pady=(14, 6))
        tk.Label(
            win, text=f"Moto sélectionnée : {self.model['label']}", bg=CARD, fg=SUB, font=(FONT, 9, "bold")
        ).pack(anchor="w", padx=24, pady=(4, 2))
        tk.Label(
            win,
            text="Connexion USB-CAN : réception uniquement.\nMode Silent à configurer avec le logiciel officiel.",
            bg=CARD,
            fg=YELLOW,
            justify="left",
            font=(FONT, 9),
        ).pack(anchor="w", padx=24)

    def run(self):
        self.root.mainloop()
