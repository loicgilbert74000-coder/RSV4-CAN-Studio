"""Page Télémétrie : jauges et tuiles de toutes les données."""

import time
import tkinter as tk

from .config import GROUP_OF, GROUP_ORDER, TILE_DEFS
from .names import fr
from .theme import BG, CARD, CYAN, FONT, GREEN, LIME, MUTED, ORANGE, PINK, RED, SUB, TEXT, YELLOW
from .util import disp_unit, fmt_val
from .widgets import Bar, Gauge, GearBox, TileBoard, make_dot, set_dot


class TelemetryMixin:
    """Page Télémétrie : jauges et tuiles de toutes les données."""

    # ---------- page Télémétrie ----------
    def build_tele(self, parent):
        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x")
        self.build_top(top)
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(10, 2))
        tk.Label(
            head, text="Toutes les données de télémétrie", fg=TEXT, bg=BG, font=(FONT, 13, "bold")
        ).pack(side="left")
        self.bus_note = tk.Label(head, text="", fg=SUB, bg=BG, font=(FONT, 9))
        self.bus_note.pack(side="left", padx=12)
        groups = {}
        for cid, name, *_, unit in TILE_DEFS:
            groups.setdefault(GROUP_OF.get(cid, "Autres"), []).append(
                ((cid, name), fr(name), disp_unit(unit))
            )
        ordered = [(g, groups[g]) for g in dict.fromkeys(GROUP_ORDER + list(groups)) if g in groups]
        self.board = TileBoard(parent, ordered)
        self.board.pack(fill="both", expand=True, pady=(2, 0))

    def refresh_tile(self, key):
        val, src = self.vals[key]
        label, color = {
            "def": ("définition", MUTED), "valid": ("validé", GREEN), "esp": ("ESP32", CYAN)
        }.get(src, ("app · à valider", YELLOW))
        self.board.update_tile(key, fmt_val(val), f"0x{key[0]:03X} · {label}", color)
        self.board.set_value_color(key, CYAN)
        self.flash_until[key] = time.monotonic() + 0.3

    def refresh_tiles(self):
        """Met à jour les tuiles modifiées depuis le dernier passage et éteint les surbrillances terminées."""
        if self.dirty:
            keys, self.dirty = (self.dirty, set())
            for key in keys:
                if key in self.board.items:
                    self.refresh_tile(key)
        now = time.monotonic()
        for key, until in list(self.flash_until.items()):
            if now >= until:
                self.board.set_value_color(key, TEXT)
                del self.flash_until[key]

    def mcard(self, parent, key, label, unit, color, lo, hi):
        f = self.card(parent)
        tk.Label(
            f, text=label, fg=SUB, bg=CARD, font=(FONT, 8, "bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(10, 0))
        row = tk.Frame(f, bg=CARD)
        row.pack(anchor="w", padx=12, pady=(2, 4))
        val = tk.Label(row, text="—", fg=TEXT, bg=CARD, font=(FONT, 18, "bold"))
        val.pack(side="left")
        if unit:
            tk.Label(
                row, text=unit, fg=MUTED, bg=CARD, font=(FONT, 10)
            ).pack(side="left", padx=(4, 0), pady=(8, 0))
        self.badge[key] = tk.Label(f, text="", fg=YELLOW, bg=CARD, font=(FONT, 7, "bold"), anchor="w")
        self.badge[key].pack(fill="x", padx=12)
        bar = self.reg(Bar(f, color, lo, hi))
        bar.pack(fill="x", padx=12)
        sc = tk.Frame(f, bg=CARD)
        sc.pack(fill="x", padx=12, pady=(3, 8))
        tk.Label(sc, text=str(lo), fg=MUTED, bg=CARD, font=(FONT, 7)).pack(side="left")
        tk.Label(sc, text=str(hi), fg=MUTED, bg=CARD, font=(FONT, 7)).pack(side="right")
        self.cards[key] = (val, bar)
        return f

    def show(self, key, num, text=None):
        val, bar = self.cards[key]
        if num is None:
            val.config(text="—")
        else:
            val.config(text=text if text is not None else f"{num:.0f}")
        bar.set(num)

    def build_top(self, parent):
        right = tk.Frame(parent, bg=BG, width=270)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)
        left = tk.Frame(parent, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        for c in range(7):
            left.columnconfigure(c, weight=1, uniform="c")
        left.rowconfigure(0, minsize=240)
        left.rowconfigure(1, minsize=150)

        g = self.card(left)
        g.grid(row=0, column=0, columnspan=2, rowspan=2, sticky="nsew", padx=4, pady=4)
        tk.Label(
            g, text="Régime moteur", fg=SUB, bg=CARD, font=(FONT, 9, "bold")
        ).pack(anchor="w", padx=14, pady=(10, 0))
        self.badge["rpm"] = tk.Label(g, text="", fg=YELLOW, bg=CARD, font=(FONT, 7, "bold"))
        self.badge["rpm"].pack(anchor="w", padx=14)
        self.rpm = self.reg(
            Gauge(g, 16000, "tr/min", [], lambda f: GREEN if f < 0.5 else YELLOW if f < 0.8 else RED)
        )
        self.rpm.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        s = self.card(left)
        s.grid(row=0, column=2, columnspan=2, sticky="nsew", padx=4, pady=4)
        tk.Label(
            s, text="Vitesse moto", fg=SUB, bg=CARD, font=(FONT, 9, "bold")
        ).pack(anchor="w", padx=14, pady=(10, 0))
        self.badge["speed"] = tk.Label(s, text="", fg=YELLOW, bg=CARD, font=(FONT, 7, "bold"))
        self.badge["speed"].pack(anchor="w", padx=14)
        self.speedg = self.reg(Gauge(s, 320, "km/h", [], lambda f: CYAN))
        self.speedg.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        gc = self.card(left)
        gc.grid(row=0, column=4, sticky="nsew", padx=4, pady=4)
        tk.Label(
            gc, text="Rapport engagé", fg=SUB, bg=CARD, font=(FONT, 8, "bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(10, 0))
        gt = tk.Frame(gc, bg=CARD)
        gt.pack(fill="x", padx=12, pady=(0, 4))
        self.gear_val = tk.Label(gt, text="—", fg=TEXT, bg=CARD, font=(FONT, 30, "bold"))
        self.gear_val.pack(side="left")
        self.badge["gear"] = tk.Label(gt, text="", fg=YELLOW, bg=CARD, font=(FONT, 7, "bold"))
        self.badge["gear"].pack(side="left", anchor="s", padx=(8, 0), pady=(0, 10))
        self.gear = self.reg(GearBox(gc, height=36))
        self.gear.pack(fill="x", padx=8, pady=(0, 10))

        gz = self.card(left)
        gz.grid(row=0, column=5, columnspan=2, sticky="nsew", padx=4, pady=4)
        zt = tk.Frame(gz, bg=CARD)
        zt.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(zt, text="Position gaz", fg=SUB, bg=CARD, font=(FONT, 8, "bold")).pack(side="left")
        self.badge["throttle"] = tk.Label(zt, text="", fg=GREEN, bg=CARD, font=(FONT, 7, "bold"))
        self.badge["throttle"].pack(side="right")
        self.throttle_val = tk.Label(gz, text="—", fg=TEXT, bg=CARD, font=(FONT, 30, "bold"))
        self.throttle_val.pack(anchor="w", padx=12, pady=(0, 2))
        self.gaz_bar = self.reg(Bar(gz, GREEN, 0, 100, height=10))
        self.gaz_bar.pack(fill="x", padx=12)
        sc = tk.Frame(gz, bg=CARD)
        sc.pack(fill="x", padx=12, pady=(2, 0))
        for t in ["0", "50", "100"]:
            tk.Label(sc, text=t, fg=MUTED, bg=CARD, font=(FONT, 7)).pack(side="left", expand=True)
        self.tps_lbl = tk.Label(gz, text="TPS1 —  ·  TPS2 —", fg=PINK, bg=CARD, font=(FONT, 8, "bold"))
        self.tps_lbl.pack(anchor="w", padx=12, pady=(6, 8))
        self.cards["throttle"] = (self.throttle_val, self.gaz_bar)

        small = [
            ("temp", "Temp. moteur", "°C", ORANGE, 50, 150),
            ("oil", "Temp. huile", "°C", YELLOW, 50, 150),
            ("battery", "Tension batterie", "V", LIME, 10, 16),
            ("front", "Roue AV", "km/h", CYAN, 0, 300),
            ("rear", "Roue AR", "km/h", CYAN, 0, 300),
        ]
        for i, (key, label, unit, color, lo, hi) in enumerate(small):
            self.mcard(left, key, label, unit, color, lo, hi).grid(
                row=1, column=2 + i, sticky="nsew", padx=4, pady=4
            )

        st = self.card(right)
        st.pack(fill="both", expand=True, padx=4, pady=4)
        tk.Label(
            st, text="Statut système", fg=TEXT, bg=CARD, font=(FONT, 11, "bold")
        ).pack(anchor="w", padx=16, pady=(14, 8))
        for key, label in [
            ("link", "Liaison"),
            ("can", "Bus CAN"),
            ("rx", "Trames CAN"),
            ("gps", "GPS"),
            ("wifi", "Signal Wi-Fi"),
            ("rec", "Enregistrement ESP32"),
            ("val", "Validation"),
        ]:
            row = tk.Frame(st, bg=CARD)
            row.pack(fill="x", padx=16, pady=5)
            dot = make_dot(row, MUTED, CARD, 9)
            dot.pack(side="left", padx=(0, 8))
            tk.Label(row, text=label, fg=SUB, bg=CARD, font=(FONT, 9)).pack(side="left")
            v = tk.Label(row, text="—", fg=TEXT, bg=CARD, font=(FONT, 9, "bold"))
            v.pack(side="right")
            self.srow[key] = (dot, v)
        tk.Label(
            st,
            text="Les décodages marqués « à valider »\nsont des hypothèses non confirmées.",
            fg=MUTED,
            bg=CARD,
            font=(FONT, 8),
            justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 10))

    def set_srow(self, key, text, color):
        """Ligne du panneau « Statut système » ; ne touche l'écran que si le contenu change."""
        if self._srow_shown.get(key) == (text, color):
            return
        self._srow_shown[key] = (text, color)
        dot, label = self.srow[key]
        set_dot(dot, color)
        label.config(text=text)
