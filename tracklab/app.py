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
from .recording import RecordingMixin
from .player import PlayerMixin
from .theme import BG, BORDER, CARD, CARD2, CYAN, FONT, GREEN, HOVER, LIME, MUTED, RED, SIDE, SUB, TEXT, YELLOW
from .util import fmt_time, wifi_quality
from .widgets import NavIcon, SeekBar, make_dot, set_dot


class App(TelemetryMixin, GraphMixin, EspMixin, FramesMixin, PlayerMixin, DecodingMixin, ConnectionMixin, RecordingMixin):
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
        self.esp = None  # dernier état reçu de l'ESP32 (trames 0x7FA et 0x7FB)
        self.wifi_sock = None
        self.rec_init()
        self.link_t = None  # instant de la dernière trame reçue en direct
        self._conn_shown = None
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
        self._conn_win = None
        self.cv = {}
        self.build_esp_vars()
        self.set_styles()
        self.build_footer()
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

    def build_main(self):
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.main = main
        self.build_header(main)
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
            inner, "Ouvrir un fichier", self.open_file, TEXT, CARD2, font=9
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
        for name, page in self.pages.items():  # une page masquée n'est plus mise en page à chaque redimensionnement
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        for name, (row, underline, label, icon) in self.nav.items():
            on = name == key
            bg = HOVER if on else SIDE
            row.config(bg=bg)
            underline.config(bg=RED if on else SIDE)
            label.config(bg=bg, fg=TEXT if on else SUB)
            icon.paint(bg, RED if on else SUB)
        self._map_state = None

    def build_header(self, parent):
        """Barre du haut : logo, choix de la moto, pages, état de la connexion, paramètres."""
        bar = tk.Frame(parent, bg=SIDE, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=SIDE)
        inner.pack(fill="x", padx=18, pady=6)

        logo = tk.Frame(inner, bg=SIDE)
        logo.pack(side="left")
        tk.Label(logo, text="TrackLab", fg=RED, bg=SIDE, font=(FONT, 18, "bold italic")).pack(anchor="w")
        tk.Label(logo, text="ELECTRONICS", fg=TEXT, bg=SIDE, font=(FONT, 8, "bold")).pack(anchor="w")

        moto = tk.Frame(inner, bg=SIDE)
        moto.pack(side="left", padx=(24, 0))
        tk.Label(moto, text="MOTO", fg=MUTED, bg=SIDE, font=(FONT, 7, "bold")).pack(anchor="w")
        self.model_cb = ttk.Combobox(
            moto, values=[m["label"] for m in MODELS.values()], state="readonly", width=32, font=(FONT, 9)
        )
        self.model_cb.pack()
        self.model_cb.bind("<<ComboboxSelected>>", self.on_model)

        tabs = tk.Frame(inner, bg=SIDE)
        tabs.pack(side="left", padx=(28, 0))
        for key, label in [
            ("tele", "Télémétrie"),
            ("graph", "Courbes"),
            ("frames", "Trames CAN"),
            ("esp", "Paramétrage ESP32"),
        ]:
            self.tab_item(tabs, key, label)

        gear = NavIcon(inner, "settings", SIDE)
        gear.pack(side="right", padx=(12, 0))
        gear.bind("<Button-1>", lambda e: self.settings())
        self.conn_btn = self.button(inner, "Connexion", self.on_conn_button, "#ffffff", RED, font=9)
        self.conn_btn.pack(side="right", padx=(12, 0))
        self.rec_btn = self.button(inner, "● Enreg.", self.rec_toggle, TEXT, CARD2, font=9)
        self.rec_btn.config(state="disabled")
        self.rec_btn.pack(side="right", padx=(12, 0))
        self.conn_lbl = tk.Label(inner, text="Déconnecté", bg=SIDE, fg=SUB, font=(FONT, 9, "bold"))
        self.conn_lbl.pack(side="right")
        self.conn_dot = make_dot(inner, MUTED, SIDE, 10)
        self.conn_dot.pack(side="right", padx=(0, 6))

    def tab_item(self, parent, key, label):
        """Onglet de page : pictogramme, texte et soulignement de la page active."""
        row = tk.Frame(parent, bg=SIDE, cursor="hand2")
        row.pack(side="left", padx=2)
        underline = tk.Frame(row, bg=SIDE, height=3)
        underline.pack(side="bottom", fill="x")
        icon = NavIcon(row, key, SIDE)
        icon.pack(side="left", padx=(8, 0), pady=4)
        text = tk.Label(
            row, text=label, bg=SIDE, fg=TEXT, font=(FONT, 10, "bold"), padx=6, pady=6, cursor="hand2"
        )
        text.pack(side="left", padx=(0, 6))
        for widget in (row, underline, icon, text):
            widget.bind("<Button-1>", lambda e, k=key: self.show_page(k))
        self.nav[key] = (row, underline, text, icon)

    # ---------- état ----------
    def set_state(self, text, color):
        self.status.set(text)
        set_dot(self.fl["dot"], color)

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
        self.update_conn_label(now)
        link = self.link_state(now)
        self.update_rec_live(self.esp if link == "ok" else None, link == "ok")
        if self.current_page == "esp":
            self.update_esp_live(now, rate)
        if self.current_page != "tele":
            return  # le panneau « Statut système » n'existe que sur la page Télémétrie
        for key, (text, color) in self.module_states(now, rate).items():
            self.set_srow(key, text, color)
        self.set_srow("val", self.model["short"], YELLOW if self.decoder else MUTED)

    def link_state(self, now):
        """État de la liaison en direct : « attente », « ok » ou « muet » (None hors connexion)."""
        if not self.live:
            return None
        if self.link_t is None:
            return "attente"
        return "ok" if now - self.link_t < 2500 else "muet"

    def module_states(self, now, rate):
        """Texte et couleur de chaque ligne du panneau d'état (liaison, CAN, GPS, Wi-Fi)."""
        wifi = self.transport.get().startswith("Wi-Fi")
        link = self.link_state(now)
        esp = self.esp if (self.live and wifi and link == "ok") else None
        flags = esp["flags"] if esp else 0
        out = {}
        if link is None:
            out["link"] = ("Fichier" if self.frames else "Déconnecté", MUTED)
        elif link == "attente":
            out["link"] = ("En attente…", YELLOW)
        elif link == "muet":
            out["link"] = ("Aucune donnée", RED)
        else:
            out["link"] = (("ESP32 · connectée" if wifi else "USB-CAN · connecté"), GREEN)
        # bus CAN
        if link is None:
            out["can"] = ("Fichier chargé" if self.frames else "—", MUTED)
            out["rx"] = ("Fichier · %d IDs" % len(self.count) if self.frames else "Aucune", MUTED)
        elif link != "ok":
            out["can"] = ("—", MUTED)
            out["rx"] = ("—", MUTED)
        else:
            if esp and not flags & 1:
                out["can"] = ("Désactivé", MUTED)
            elif esp and not flags & 2:
                out["can"] = ("Défaut contrôleur", RED)
            elif rate:
                out["can"] = ("Actif", GREEN)
            else:
                out["can"] = ("Aucune trame", YELLOW)
            if esp and not flags & 1:
                out["rx"] = ("—", MUTED)
            else:
                out["rx"] = (f"OK · {rate}/s", GREEN) if rate else ("Aucune trame", YELLOW)
        # GPS
        sats = self.vals.get((2040, "Satellites"), (0,))[0]
        if esp:
            if not flags & 8:
                out["gps"] = ("Désactivé", MUTED)
            elif not flags & 16 and flags & 64:
                out["gps"] = ("Données illisibles · débit ?", YELLOW)
            elif not flags & 16:
                out["gps"] = ("Aucune donnée du module", YELLOW)
            elif flags & 32:
                out["gps"] = (f"Position valide · {int(sats)} sat.", GREEN)
            else:
                out["gps"] = (f"Recherche · {int(sats)} sat.", YELLOW)
        elif self.track:
            out["gps"] = (f"{len(self.track)} points", GREEN)
        else:
            out["gps"] = ("—" if link is None else "Aucune donnée", MUTED)
        # Wi-Fi
        if esp and esp["rssi"] is not None:
            level, label = wifi_quality(esp["rssi"])
            out["wifi"] = (f"{esp['rssi']} dBm · {label}", (GREEN, LIME, YELLOW, RED)[level])
        else:
            out["wifi"] = ("—", MUTED)
        # enregistrement sur l'ESP32
        if esp and esp.get("rec"):
            out["rec"] = (f"En cours · {esp.get('rec_bytes', 0) // 1024} Ko", RED)
        elif esp and not esp.get("store"):
            out["rec"] = ("Pas de stockage", YELLOW)
        elif esp:
            out["rec"] = ("Arrêté", MUTED)
        else:
            out["rec"] = ("—", MUTED)
        return out

    def update_conn_label(self, now):
        """Voyant et texte de la barre du haut : reflètent la réception réelle, pas seulement la connexion TCP."""
        link = self.link_state(now)
        shown = {None: ("Déconnecté", MUTED, SUB), "attente": ("Connexion…", YELLOW, YELLOW),
                 "ok": ("Connecté", GREEN, GREEN), "muet": ("Aucune donnée", RED, RED)}[link]
        if shown != self._conn_shown:
            self._conn_shown = shown
            text, dot, fg = shown
            set_dot(self.conn_dot, dot)
            self.conn_lbl.config(text=text, fg=fg)

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
        budget, started = 400, time.monotonic()
        while budget > 0 and time.monotonic() - started < 0.03:
            try:
                cid, data = self.q.get_nowait()
            except queue.Empty:
                break
            if cid == "error":
                self.disconnect()
                messagebox.showerror("Connexion", data)
            elif cid == "file":  # liste et téléchargement des enregistrements : peu coûteux, ne compte pas dans le budget
                self.on_file_frame(*data)
            else:
                budget -= 1
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
