"""Fenêtre principale de TrackLab Electronics."""

import queue
import threading
import bisect
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
from .deck import DeckButton, DeckLcd
from .recording import fmt_size
from .widgets import NavIcon, make_dot, set_dot


class App(TelemetryMixin, GraphMixin, EspMixin, FramesMixin, PlayerMixin, DecodingMixin, ConnectionMixin, RecordingMixin):
    """Fenêtre principale."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TrackLab Electronics · Diagnostic & Télémétrie CAN")
        self.root.geometry("1536x960")
        self.root.minsize(1280, 860)
        try:  # icône de la fenêtre et de la barre des tâches
            from .icon_data import ICON_PNG_B64

            self._icon = tk.PhotoImage(data=ICON_PNG_B64)
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass
        self.root.configure(bg=BG)
        self.frames = []
        self.idx = 0
        self.playing = False
        self.speed = tk.DoubleVar(value=1.0)
        self.status = tk.StringVar(value="Prêt · ouvrez une capture")
        self.file_name = tk.StringVar(value="Aucun fichier")
        self.clock = tk.StringVar(value="00:00 / 00:00")
        self.transport = tk.StringVar(value="Wi-Fi ESP32")
        self.port = tk.StringVar(value="COM7")
        self.baud = tk.StringVar(value="2000000")
        self.host = tk.StringVar(value="192.168.4.1")
        self.tcp_port = tk.StringVar(value="2323")
        self.experimental = tk.BooleanVar(value=True)
        self.filter_on = tk.BooleanVar(value=True)
        self._table_stale = False
        self.loading = False  # chargement de fichier en cours (barre de progression)
        self._prog = None
        self._scroll_on = False  # lecture d'une vue zoomée : curseur fixe, courbes qui défilent
        self.cur_frac = 0.3  # position (fraction de la largeur) du curseur fixe
        self._cursor_override = None  # curseur placé par un clic, avant que le saut soit fait
        self._last_draw = 0.0
        self._interact_until = 0.0
        self.card_state = {}  # cartes de la télémétrie : [valeur affichée, valeur reçue, décimales]
        self.tile_state = {}  # tuiles analogiques : idem
        self._anim_t = time.monotonic()
        self._anim_n = 0
        self.full_src = {}
        self.track_full, self.track_full_t = [], []
        self.table_paused = False  # affichage des trames figé (la réception continue en arrière-plan)
        self.span_ms = 30000.0  # durée de la fenêtre des courbes (ms) : 30 s par défaut
        self.yr_cache = {}  # échelles des courbes (fichier ouvert)
        self.yr_live = {}  # échelles des courbes (en direct : ne font que s'élargir)
        self._chart_sig = None
        self._cur_shown = None
        self.val_items = []
        self._sl_t = 0.0
        self.cur_spans = []
        self.stack = tk.BooleanVar(value=False)
        self.sel = set(DEFAULT_CURVES)
        self.dyn = {}  # voies d'un fichier RaceBox / RaceChrono… {identifiant: [(nom, unité, type), …]}
        self.color_map = {}
        self.geom = None
        self.zsel = None
        self.close_hits = []
        self.pan = None
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
        for _k in sorted(self.sel):
            self.assign_color(_k)
        self.build_esp_vars()
        self.set_styles()
        self.build_footer()
        self.build_main()
        self.apply_model("rsv4")
        self.show_page("tele")
        self.set_conn_ui(False, "Déconnecté")
        self.set_state("Prêt · ouvrez une capture", MUTED)
        self.root.after(40, self.tick)
        self.root.after(16, self.paint_chart)
        self.root.after(16, self.anim_tele)
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
            text="Décodage : définition can1.xml · valeurs à valider" if self.decoder else "Aucun décodage pour cette moto · voir « Trames Tracklab »"
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
        s.configure("Tracklab.Horizontal.TProgressbar", troughcolor=CARD2, background=RED, bordercolor=BORDER,
                    lightcolor=RED, darkcolor=RED, thickness=14)
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
        foot.pack(side="bottom", fill="x", padx=18, pady=(0, 8))
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
        self.area.pack(fill="both", expand=True, padx=0, pady=(0, 10))
        self.area.grid_rowconfigure(0, weight=1)
        self.area.grid_columnconfigure(0, weight=1)
        self.page_tele = tk.Frame(self.area, bg=BG)
        self.page_graph = tk.Frame(self.area, bg=BG)
        self.page_frames = tk.Frame(self.area, bg=BG)
        self.page_esp = tk.Frame(self.area, bg=BG)
        self.pages = {
            "tele": self.page_tele, "graph": self.page_graph, "frames": self.page_frames, "esp": self.page_esp
        }
        # marges : les cartes de chaque page s'alignent exactement sur les bords de la barre du haut et de la platine (18 px)
        margins = {"tele": 14, "graph": 18, "frames": 14, "esp": 18}
        for name, p in self.pages.items():
            p.grid(row=0, column=0, sticky="nsew", padx=margins[name])
        self.build_tele(self.page_tele)
        self.build_graph(self.page_graph)
        self.build_table(self.page_frames)
        self.build_esp(self.page_esp)

    def build_playbar(self, main):
        """Platine façon lecteur CD : touches, afficheur LCD avec bargraph, puis enregistrement et connexion."""
        bar = tk.Frame(main, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x", padx=18, pady=(4, 6))
        inner = tk.Frame(bar, bg=CARD)
        inner.pack(fill="x", padx=8, pady=3)

        def sep():
            tk.Frame(inner, bg=BORDER, width=1, height=28).pack(side="left", padx=6)

        self.key_open = DeckButton(inner, "eject", "OUVRIR", self.open_file, color=CYAN)
        self.key_open.pack(side="left", padx=2)
        sep()
        self.key_start = DeckButton(inner, "start", "DÉBUT", self.reset, color=CYAN)
        self.key_start.pack(side="left", padx=2)
        self.key_play = DeckButton(inner, "play", "LECTURE", self.play, color=GREEN)
        self.key_play.pack(side="left", padx=2)
        self.key_pause = DeckButton(inner, "pause", "PAUSE", self.pause, color=YELLOW)
        self.key_pause.pack(side="left", padx=2)
        self.key_speed = DeckButton(inner, "text", "VITESSE", self.cycle_speed, color=CYAN, text="x1")
        self.key_speed.pack(side="left", padx=2)
        sep()
        self.rec_btn = DeckButton(inner, "rec", "ENREG.", self.rec_toggle, color=RED)
        self.rec_btn.set_look(enabled=False)
        self.rec_btn.pack(side="left", padx=2)
        sep()
        # connexion à droite (réservée avant l'afficheur, qui prend toute la place restante)
        self.conn_btn = DeckButton(inner, "plug", "CONNEXION", self.on_conn_button, color=GREEN, width=72)
        self.conn_btn.pack(side="right", padx=2)
        tk.Frame(inner, bg=BORDER, width=1, height=28).pack(side="right", padx=6)
        self.lcd = DeckLcd(inner, on_seek=self.seek)
        self.lcd.pack(side="left", fill="x", expand=True, padx=2)

    def cycle_speed(self):
        names = list(SPEEDS)
        cur = min(names, key=lambda n: abs(SPEEDS[n] - self.speed.get()))
        nxt = names[(names.index(cur) + 1) % len(names)]
        self.speed.set(SPEEDS[nxt])
        self.key_speed.set_look(text=nxt)

    PAGE_NAMES = {"tele": "TÉLÉMÉTRIE", "graph": "COURBES", "frames": "TRAMES TRACKLAB", "esp": "PARAMÉTRAGE TRACKLAB"}

    def update_deck(self, now, rate, dur, link):
        """Afficheur et touches : ce qui est lu, en direct ou à l'arrêt, et la vue affichée."""
        view = self.PAGE_NAMES.get(self.current_page, "")
        rec = bool(self.esp and self.esp.get("rec") and link == "ok")
        if self.live:
            wifi = self.transport.get().startswith("Wi-Fi")
            mode_text, color = {
                "ok": ("● EN DIRECT", GREEN),
                "attente": ("◌ ATTENTE DES TRAMES", YELLOW),
            }.get(link, ("◌ LIAISON PERDUE", RED))
            name = self.model["label"]
            info = f"{rate} trames/s · {len(self.count)} ID · {self.ingested} reçues"
            if rec:  # enregistrement en cours : l'afficheur montre le fichier utilisé
                kind = "carte SD" if self.esp.get("sd") else "mémoire interne"
                mode_text, color = "● ENREGISTREMENT", RED
                name = f"Fichier {self.esp.get('rec_no', 0):04d}.trk"
                info = f"{fmt_size(self.esp.get('rec_bytes', 0))} · {kind} · {rate} trames/s"
            self.lcd.show(
                mode="live", mode_text=mode_text, mode_color=color, view=view,
                source="Wi-Fi ESP32" if wifi else "USB-CAN", cur=dur // 100 * 100, total=0,
                name=name, info=info, frac=min(1.0, rate / 1500), seekable=False, rec=rec,
            )
            self.key_play.set_look(lit=False)
            self.key_pause.set_look(lit=False)
            return
        if self.frames:
            n = len(self.frames)
            total = self.frames[-1][0]
            cur = int(self.cursor_ms()) if self.idx > 0 or self.playing else 0
            if self.playing:
                mode, text, color = "play", "▶ LECTURE", GREEN
            elif self.idx >= n:
                mode, text, color = "end", "■ FIN DU FICHIER", CYAN
            elif self.idx == 0:
                mode, text, color = "stop", "■ ARRÊT", SUB
            else:
                mode, text, color = "pause", "❚❚ PAUSE", YELLOW
            name, _, label = self.file_name.get().partition("  ·  ")
            self.lcd.show(
                mode=mode, mode_text=text, mode_color=color, view=view, source="FICHIER", cur=cur // 100 * 100, total=total,
                name=name, info=f"{label + ' · ' if label else ''}{n:,} trames".replace(",", " "),
                frac=round(cur / total, 3) if total else 0.0, seekable=True, rec=False,
            )
            self.key_play.set_look(lit=mode == "play")
            self.key_pause.set_look(lit=mode == "pause")
        else:
            self.lcd.show(
                mode="idle", mode_text="■ PRÊT", mode_color=MUTED, view=view, source="", cur=0, total=0,
                name="Aucun fichier", info="Ouvrez un fichier ou connectez-vous", frac=0.0, seekable=False, rec=False,
            )
            self.key_play.set_look(lit=False)
            self.key_pause.set_look(lit=False)

    def show_page(self, key):
        self.current_page = key
        for name, page in self.pages.items():  # une page masquée n'est plus mise en page à chaque redimensionnement
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        if key == "frames" and self._table_stale:
            self.rebuild_table()
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
        bar.pack(fill="x", padx=18, pady=(10, 4))  # même marge que tous les autres panneaux
        inner = tk.Frame(bar, bg=SIDE)
        inner.pack(fill="x", padx=14, pady=5)

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
            ("frames", "Trames Tracklab"),
            ("esp", "Paramétrage Tracklab"),
        ]:
            self.tab_item(tabs, key, label)

        gear = NavIcon(inner, "settings", SIDE)
        gear.pack(side="right", padx=(12, 0))
        gear.bind("<Button-1>", lambda e: self.settings())
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
            dur = cur
        else:
            dur = now - self.t0 if self.live else 0
        self.show_footer("dur", fmt_time(dur))
        self.update_deck(now, rate, dur, self.link_state(now))
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

    def anim_tele(self):
        """Animation de la page Télémétrie (60 images/s) : jauges, barres et nombres rejoignent leur valeur en douceur."""
        try:
            now = time.monotonic()
            dt, self._anim_t = min(0.1, now - self._anim_t), now
            if self.current_page == "tele":
                self._anim_n += 1
                self.smooth_cards(dt)
                self.smooth_tiles(dt)
                if self._anim_n % 2 == 0:  # jauges : 30 images/s suffisent (dessin plus lourd)
                    for widget in self.flushables:
                        widget.flush()
        finally:
            self.root.after(16, self.anim_tele)

    def progress_show(self, text, pct):
        """Barre de progression au centre de la fenêtre (chargement d'un fichier)."""
        if self._prog is None:
            f = tk.Frame(self.root, bg=CARD, highlightbackground=RED, highlightthickness=2)
            lbl = tk.Label(f, text="", fg=TEXT, bg=CARD, font=(FONT, 11, "bold"))
            lbl.pack(padx=34, pady=(20, 10))
            bar = ttk.Progressbar(f, length=380, mode="determinate", maximum=100, style="Tracklab.Horizontal.TProgressbar")
            bar.pack(padx=34)
            pc = tk.Label(f, text="", fg=SUB, bg=CARD, font=(FONT, 9))
            pc.pack(pady=(6, 18))
            f.place(relx=0.5, rely=0.4, anchor="center")
            self._prog = (f, lbl, bar, pc)
        f, lbl, bar, pc = self._prog
        f.lift()
        lbl.config(text=text)
        bar["value"] = pct
        pc.config(text=f"{int(pct)} %")
        self.root.update()

    def progress_hide(self):
        if self._prog is not None:
            self._prog[0].destroy()
            self._prog = None
            self.root.update_idletasks()

    def tick(self):
        """Boucle principale (25 fois par seconde) : lecture, réception, mise à jour de ce qui est visible."""
        if self.loading:  # pendant le chargement, l'affichage de la barre traite les évènements : on ne joue rien
            self.root.after(40, self.tick)
            return
        if self.playing and self.frames:
            elapsed = (time.monotonic() - self.start_wall) * 1000 * self.speed.get()
            limit = self.start_frame + elapsed
            batch = 0
            if self.full_t and self.current_page == "graph":
                # Courbes : tout vient des tableaux pré-calculés et de l'horloge de lecture, inutile de rejouer les trames
                # (c'est ce qui faisait saccader le curseur quand il y a beaucoup de courbes).
                self._skipped = True
                self.idx = bisect.bisect_right(self.frame_times, limit)
                n = bisect.bisect_right(self.track_full_t, limit)  # le tracé du circuit suit le curseur
                have = len(self.track)
                if have < 30000 and n != have:
                    if n < have:
                        self.track.clear()
                        have = 0
                    self.track.extend((p[1], p[2]) for p in self.track_full[have:n])
            else:
                if getattr(self, "_skipped", False):
                    self._skipped = False
                    self.resync()
                    limit = self.start_frame + (time.monotonic() - self.start_wall) * 1000 * self.speed.get()
                while self.idx < len(self.frames) and self.frames[self.idx][0] <= limit and (batch < 1200):
                    self.ingest(*self.frames[self.idx])
                    self.idx += 1
                    batch += 1
            if self.idx >= len(self.frames):
                if getattr(self, "_skipped", False):
                    self.resync()
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
        if self.current_page == "tele":  # les tuiles cachées se mettent à jour au retour sur la page
            self.refresh_tiles()
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
