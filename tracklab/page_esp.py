"""Page de paramétrage de l'ESP32."""

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .widgets import make_dot, set_dot
from .espconfig import BOARDS, ANA_DEFAULT, DIG_DEFAULT, LED_DEFAULT, OUT_DEFAULT, REC_DEFAULT, make_header, validate_cfg
from .theme import BG, BORDER, CARD, CARD2, CYAN, FONT, GREEN, LIME, MUTED, RED, SUB, TEXT, YELLOW


class EspMixin:
    """Page de paramétrage de l'ESP32."""

    # ---------- page Paramétrage ESP32 ----------
    def build_esp_vars(self):
        sv = lambda k, v: self.cv.__setitem__(k, tk.StringVar(value=str(v)))
        bv = lambda k, v: self.cv.__setitem__(k, tk.BooleanVar(value=v))
        sv("ssid", "RSV4-CAN")
        sv("password", "rsv4-can-2026")
        sv("channel", 6)
        self.cv["tcp_port"] = self.tcp_port
        bv("can_on", True)
        sv("can_bitrate", 250)
        sv("can_tx", 5)
        sv("can_rx", 4)
        bv("gps_on", True)
        sv("gps_rx", 16)
        sv("gps_tx", -1)
        sv("gps_baud", 115200)
        for i, (pin, name, on) in enumerate(DIG_DEFAULT):
            sv(f"dig{i}_pin", pin)
            sv(f"dig{i}_name", name)
            bv(f"dig{i}_on", on)
        for i, (pin, name, on) in enumerate(ANA_DEFAULT):
            sv(f"ana{i}_pin", pin)
            sv(f"ana{i}_name", name)
            bv(f"ana{i}_on", on)
        for color, pin in LED_DEFAULT.items():
            sv(f"led_{color}", pin)
        for key, val in REC_DEFAULT.items():
            (bv if key == "sd" else sv)(f"rec_{key}", val)
        for i, (pin, name, level, on) in enumerate(OUT_DEFAULT):
            sv(f"out{i}_pin", pin)
            sv(f"out{i}_name", name)
            sv(f"out{i}_level", level)
            bv(f"out{i}_on", on)

    # ---------- état de la carte en direct ----------
    WIFI_SPAN = (-90, -40)  # plage affichée par la jauge du signal Wi-Fi (dBm)

    def build_esp_live(self, parent):
        c = self.esp_card(parent, "État de la carte (en direct)")
        self.live_rows, self._live_shown = {}, {}
        for key, label in (("link", "Liaison"), ("can", "Bus CAN"), ("gps", "GPS"), ("wifi", "Signal Wi-Fi")):
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", pady=3)
            dot = make_dot(row, MUTED, CARD, 9)
            dot.pack(side="left", padx=(0, 8))
            tk.Label(row, text=label, fg=SUB, bg=CARD, font=(FONT, 9), width=14, anchor="w").pack(side="left")
            val = tk.Label(row, text="—", fg=TEXT, bg=CARD, font=(FONT, 9, "bold"))
            val.pack(side="right")
            self.live_rows[key] = (dot, val)
        lo, hi = self.WIFI_SPAN
        width = 320
        x = lambda dbm: (dbm - lo) / (hi - lo) * width
        bar = tk.Canvas(c, width=width, height=34, bg=CARD, highlightthickness=0)
        bar.pack(anchor="w", pady=(4, 0))
        for a, b, color in ((lo, -80, RED), (-80, -70, YELLOW), (-70, -60, LIME), (-60, hi, GREEN)):
            bar.create_rectangle(x(a), 4, x(b), 16, fill=color, outline="")
        for dbm in (-80, -70, -60):
            bar.create_line(x(dbm), 4, x(dbm), 20, fill=BG)
            bar.create_text(x(dbm), 27, text=str(dbm), fill=SUB, font=(FONT, 8))
        self.wifi_marker = bar.create_polygon(0, 0, 0, 0, 0, 0, fill=TEXT, outline=BG, state="hidden")
        self.wifi_bar = (bar, x)
        tk.Label(
            c,
            text="Signal du PC mesuré par l'ESP32 (dBm) :\nBon ≥ −60 · Correct −60 à −70 · Faible −70 à −80 (coupures possibles) · Très faible < −80 (liaison instable)\nPlus la valeur est proche de 0, meilleur est le signal. Rapprocher la carte ou changer de canal Wi-Fi si « Faible ».",
            fg=MUTED, bg=CARD, font=(FONT, 8), justify="left", wraplength=460,
        ).pack(anchor="w", pady=(2, 0))

    def update_esp_live(self, now, rate):
        """Met à jour l'état de la carte (liaison, CAN, GPS, signal Wi-Fi) ; ne touche l'écran que si le contenu change."""
        states = self.module_states(now, rate)
        esp = self.esp if self.link_state(now) == "ok" else None
        if esp and esp["rssi"] is not None:
            states["wifi"] = (states["wifi"][0] + f" · {esp['stations']} appareil(s)", states["wifi"][1])
        for key, (dot, val) in self.live_rows.items():
            state = states[key]
            if self._live_shown.get(key) != state:
                self._live_shown[key] = state
                set_dot(dot, state[1])
                val.config(text=state[0])
        bar, x = self.wifi_bar
        if esp and esp["rssi"] is not None:
            pos = x(max(self.WIFI_SPAN[0], min(self.WIFI_SPAN[1], esp["rssi"])))
            bar.coords(self.wifi_marker, pos - 5, 0, pos + 5, 0, pos, 8)
            bar.itemconfigure(self.wifi_marker, state="normal")
        else:
            bar.itemconfigure(self.wifi_marker, state="hidden")

    def apply_board(self, name):
        """Remplit toutes les broches avec celles de la carte choisie."""
        b, v = BOARDS[name], self.cv
        v["can_tx"].set(b["can"][0])
        v["can_rx"].set(b["can"][1])
        v["gps_rx"].set(b["gps"])
        v["gps_tx"].set(b.get("gps_tx", -1))
        for n, pin in enumerate(b["dig"]):
            v[f"dig{n}_pin"].set(pin)
        for n, pin in enumerate(b["ana"]):
            v[f"ana{n}_pin"].set(pin)
        for n, pin in enumerate(b["out"]):
            v[f"out{n}_pin"].set(pin)
        for color, pin in b["leds"].items():
            v[f"led_{color}"].set(pin)
        for key, val in {**REC_DEFAULT, **b.get("rec", {})}.items():
            if key != "sd":
                v[f"rec_{key}"].set(val)

    def cfg_from_vars(self):
        """Construit la configuration ESP32 à partir des champs ; lève ValueError si un champ est invalide."""
        v = self.cv
        i = lambda k: int(str(v[k].get()).strip())
        return {
            "wifi": {
                "ssid": v["ssid"].get().strip(),
                "password": v["password"].get(),
                "channel": i("channel"),
                "tcp_port": int(self.tcp_port.get().strip()),
            },
            "can": {"enabled": v["can_on"].get(), "bitrate_kbps": i("can_bitrate"), "tx_pin": i("can_tx"), "rx_pin": i("can_rx")},
            "gps": {"enabled": v["gps_on"].get(), "rx_pin": i("gps_rx"), "tx_pin": i("gps_tx"), "baud": i("gps_baud")},
            "digital_inputs": [
                {
                    "pin": i(f"dig{n}_pin"), "name": v[f"dig{n}_name"].get(), "enabled": v[f"dig{n}_on"].get()
                } for n in range(8)
            ],
            "analog_inputs": [
                {
                    "pin": i(f"ana{n}_pin"), "name": v[f"ana{n}_name"].get(), "enabled": v[f"ana{n}_on"].get()
                } for n in range(3)
            ],
            "leds": {color: i(f"led_{color}") for color in LED_DEFAULT},
            "rec": {"button": i("rec_button"), "sd": v["rec_sd"].get(), **{k: i(f"rec_{k}") for k in ("cs", "mosi", "miso", "sck")}},
            "outputs": [
                {
                    "pin": i(f"out{n}_pin"),
                    "name": v[f"out{n}_name"].get(),
                    "level": v[f"out{n}_level"].get(),
                    "enabled": v[f"out{n}_on"].get(),
                } for n in range(2)
            ],
        }

    def cfg_to_vars(self, cfg):
        v = self.cv
        w, c, g = (cfg["wifi"], cfg["can"], cfg["gps"])
        v["ssid"].set(w["ssid"])
        v["password"].set(w["password"])
        v["channel"].set(w["channel"])
        self.tcp_port.set(str(w["tcp_port"]))
        v["can_on"].set(bool(c.get("enabled", True)))
        v["can_bitrate"].set(c["bitrate_kbps"])
        v["can_tx"].set(c["tx_pin"])
        v["can_rx"].set(c["rx_pin"])
        v["gps_on"].set(bool(g["enabled"]))
        v["gps_rx"].set(g["rx_pin"])
        v["gps_tx"].set(g.get("tx_pin", -1))
        v["gps_baud"].set(g["baud"])
        for n, e in enumerate(cfg["digital_inputs"]):
            v[f"dig{n}_pin"].set(e["pin"])
            v[f"dig{n}_name"].set(e["name"])
            v[f"dig{n}_on"].set(bool(e["enabled"]))
        for n, e in enumerate(cfg["analog_inputs"]):
            v[f"ana{n}_pin"].set(e["pin"])
            v[f"ana{n}_name"].set(e["name"])
            v[f"ana{n}_on"].set(bool(e["enabled"]))
        for color, pin in {**LED_DEFAULT, **cfg.get("leds", {})}.items():
            v[f"led_{color}"].set(pin)
        for key, val in {**REC_DEFAULT, **cfg.get("rec", {})}.items():
            v[f"rec_{key}"].set(bool(val) if key == "sd" else val)
        for n, e in enumerate(cfg["outputs"]):
            v[f"out{n}_pin"].set(e["pin"])
            v[f"out{n}_name"].set(e["name"])
            v[f"out{n}_level"].set(e["level"])
            v[f"out{n}_on"].set(bool(e["enabled"]))

    def esp_card(self, parent, title):
        c = self.card(parent)
        c.pack(fill="x", padx=6, pady=6)
        tk.Label(
            c, text=title, fg=TEXT, bg=CARD, font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=14, pady=(10, 6))
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="x", padx=14, pady=(0, 12))
        return inner

    def efield(self, parent, label, key, width=16):
        r = tk.Frame(parent, bg=CARD)
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label, bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", width=38).pack(side="left")
        tk.Entry(
            r,
            textvariable=self.cv[key],
            width=width,
            bg=CARD2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
        ).pack(side="left")

    def ecombo(self, parent, label, key, values):
        r = tk.Frame(parent, bg=CARD)
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label, bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", width=38).pack(side="left")
        ttk.Combobox(
            r, textvariable=self.cv[key], values=values, state="readonly", width=12
        ).pack(side="left")

    def echeck(self, parent, label, key):
        tk.Checkbutton(
            parent,
            text=label,
            variable=self.cv[key],
            bg=CARD,
            fg=TEXT,
            selectcolor=CARD2,
            activebackground=CARD,
            activeforeground=TEXT,
            font=(FONT, 9),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=2)

    def build_esp(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(
            bar, text="Paramétrage de l'ESP32", fg=TEXT, bg=BG, font=(FONT, 13, "bold")
        ).pack(side="left")
        tk.Label(
            bar, text="Réseau, bus CAN, GPS et entrées/sorties", fg=SUB, bg=BG, font=(FONT, 9)
        ).pack(side="left", padx=12)
        self.button(
            bar, "Appliquer à l'application", self.apply_esp, TEXT, CARD2, font=9
        ).pack(side="right", padx=3)
        self.button(
            bar, "Générer rsv4_config.h", self.export_header, TEXT, CARD2, font=9
        ).pack(side="right", padx=3)
        self.button(bar, "Enregistrer (JSON)", self.save_esp, TEXT, CARD2, font=9).pack(side="right", padx=3)
        self.button(bar, "Charger (JSON)", self.load_esp, TEXT, CARD2, font=9).pack(side="right", padx=3)
        wrap, inner = self.scroll_area(parent, BG)
        wrap.pack(fill="both", expand=True)
        left = tk.Frame(inner, bg=BG)
        left.pack(side="left", fill="y", anchor="n")
        right = tk.Frame(inner, bg=BG)
        right.pack(side="left", fill="both", expand=True, anchor="n")
        self.build_esp_live(left)
        self.build_rec_card(left)
        c = self.esp_card(left, "Carte")
        self.board_var = tk.StringVar(value=list(BOARDS)[0])
        r = tk.Frame(c, bg=CARD)
        r.pack(fill="x", pady=2)
        tk.Label(r, text="Modèle (applique les broches adaptées)", bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", width=38).pack(side="left")
        box = ttk.Combobox(r, textvariable=self.board_var, values=list(BOARDS), state="readonly", width=34)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self.apply_board(self.board_var.get()))
        c = self.esp_card(left, "Réseau Wi-Fi (point d'accès de l'ESP32)")
        self.efield(c, "Nom du réseau (SSID)", "ssid", 22)
        self.efield(c, "Mot de passe (8 caractères min.)", "password", 22)
        self.ecombo(c, "Canal Wi-Fi", "channel", [str(n) for n in range(1, 14)])
        self.efield(c, "Port TCP (applications)", "tcp_port", 10)
        c = self.esp_card(left, "Bus CAN")
        self.echeck(c, "Bus CAN activé (désactiver pour tester sans moto)", "can_on")
        self.ecombo(c, "Débit (kbit/s)", "can_bitrate", ["250", "500"])
        self.efield(c, "Broche TX (vers le transceiver)", "can_tx", 8)
        self.efield(c, "Broche RX (vers le transceiver)", "can_rx", 8)
        c = self.esp_card(left, "GPS (UART)")
        self.echeck(c, "GPS activé (trames 0x7F0 et 0x7F8)", "gps_on")
        self.efield(c, "Broche RX (depuis le module GPS)", "gps_rx", 8)
        self.efield(c, "Broche TX (vers le RX du GPS, -1 = non câblée)", "gps_tx", 8)
        self.ecombo(c, "Débit (bauds)", "gps_baud", ["9600", "38400", "115200"])
        c = self.esp_card(right, "Entrées numériques (trame 0x7F9, bit par entrée)")
        self.io_header(c, ["Entrée", "Broche", "Nom", "Active"])
        for n in range(8):
            r = tk.Frame(c, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(
                r, text=f"E{n + 1}", bg=CARD, fg=SUB, font=(FONT, 9), width=8, anchor="w"
            ).pack(side="left")
            self.io_entry(r, f"dig{n}_pin", 6)
            self.io_entry(r, f"dig{n}_name", 18)
            tk.Checkbutton(
                r,
                variable=self.cv[f"dig{n}_on"],
                bg=CARD,
                selectcolor=CARD2,
                activebackground=CARD,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=12)
        c = self.esp_card(right, "Entrées analogiques ADC (trame 0x7F9, 0 à 4095)")
        self.io_header(c, ["Entrée", "Broche", "Nom", "Active"])
        for n in range(3):
            r = tk.Frame(c, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(
                r, text=f"ADC{n + 1}", bg=CARD, fg=SUB, font=(FONT, 9), width=8, anchor="w"
            ).pack(side="left")
            self.io_entry(r, f"ana{n}_pin", 6)
            self.io_entry(r, f"ana{n}_name", 18)
            tk.Checkbutton(
                r,
                variable=self.cv[f"ana{n}_on"],
                bg=CARD,
                selectcolor=CARD2,
                activebackground=CARD,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=12)
        c = self.esp_card(right, "Sorties (niveau appliqué au démarrage)")
        self.io_header(c, ["Sortie", "Broche", "Nom", "Niveau", "Active"])
        for n in range(2):
            r = tk.Frame(c, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(
                r, text=f"S{n + 1}", bg=CARD, fg=SUB, font=(FONT, 9), width=8, anchor="w"
            ).pack(side="left")
            self.io_entry(r, f"out{n}_pin", 6)
            self.io_entry(r, f"out{n}_name", 18)
            ttk.Combobox(
                r, textvariable=self.cv[f"out{n}_level"], values=["Haut", "Bas"], state="readonly", width=6
            ).pack(side="left", padx=6)
            tk.Checkbutton(
                r,
                variable=self.cv[f"out{n}_on"],
                bg=CARD,
                selectcolor=CARD2,
                activebackground=CARD,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=12)
        c = self.esp_card(right, "Voyants du tableau de bord (LED)")
        for color, label in (("green", "Verte · liaison"), ("red", "Rouge · défaut CAN"), ("blue", "Bleue · activité CAN")):
            r = tk.Frame(c, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=CARD, fg=SUB, font=(FONT, 9), width=22, anchor="w").pack(side="left")
            self.io_entry(r, f"led_{color}", 6)
        c = self.esp_card(right, "Enregistrement : bouton et carte SD")
        self.efield(c, "Bouton poussoir (entre la broche et GND)", "rec_button", 8)
        self.echeck(c, "Module carte SD présent (sinon mémoire interne, durée limitée)", "rec_sd")
        for key, label in (("cs", "SD · CS"), ("mosi", "SD · MOSI"), ("miso", "SD · MISO"), ("sck", "SD · SCK")):
            self.efield(c, label, f"rec_{key}", 8)
        tk.Label(
            right,
            text="Les broches et réglages sont appliqués au firmware par « Générer rsv4_config.h » puis recompilation du firmware.\nLes entrées/sorties sont lues par le firmware ; les sorties ne sont pas pilotées depuis l'application.",
            fg=MUTED,
            bg=BG,
            font=(FONT, 8),
            justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 10))

    def io_header(self, parent, labels):
        r = tk.Frame(parent, bg=CARD)
        r.pack(fill="x", pady=(0, 4))
        widths = [8, 6, 18, 6, 6]
        for i, l in enumerate(labels):
            tk.Label(
                r,
                text=l,
                bg=CARD,
                fg=MUTED,
                font=(FONT, 8, "bold"),
                width=widths[i] if i < len(widths) else 8,
                anchor="w",
            ).pack(side="left")

    def io_entry(self, parent, key, width):
        tk.Entry(
            parent,
            textvariable=self.cv[key],
            width=width,
            bg=CARD2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
        ).pack(side="left", padx=(0, 6))

    def apply_esp(self):
        try:
            cfg = self.cfg_from_vars()
            validate_cfg(cfg)
        except ValueError as e:
            messagebox.showerror("Paramétrage ESP32", str(e))
            return
        names = {(2041, f"Entrée {n + 1}"): e["name"] for n, e in enumerate(cfg["digital_inputs"])}
        names.update({(2041, f"ADC {n + 1}"): e["name"] for n, e in enumerate(cfg["analog_inputs"])})
        for key, label in names.items():
            self.board.rename(key, label or key[1])
        self.set_state("Paramétrage appliqué · recompiler le firmware pour les broches", CYAN)

    def save_esp(self):
        try:
            cfg = self.cfg_from_vars()
            validate_cfg(cfg)
        except ValueError as e:
            messagebox.showerror("Paramétrage ESP32", str(e))
            return
        p = filedialog.asksaveasfilename(
            title="Enregistrer le paramétrage",
            defaultextension=".json",
            initialfile="rsv4_esp32.json",
            filetypes=[("Paramétrage JSON", "*.json")],
        )
        if p:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.set_state(f"Paramétrage enregistré : {os.path.basename(p)}", GREEN)

    def load_esp(self):
        p = filedialog.askopenfilename(
            title="Charger un paramétrage", filetypes=[("Paramétrage JSON", "*.json")]
        )
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            validate_cfg(cfg)
            self.cfg_to_vars(cfg)
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("Paramétrage ESP32", f"Fichier invalide : {e}")
            return
        self.set_state(f"Paramétrage chargé : {os.path.basename(p)}", SUB)

    def export_header(self):
        try:
            cfg = self.cfg_from_vars()
            validate_cfg(cfg)
        except ValueError as e:
            messagebox.showerror("Paramétrage ESP32", str(e))
            return
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_dir = os.path.join(root, "firmware", "esp32_can_wifi")
        p = filedialog.asksaveasfilename(
            title="Enregistrer rsv4_config.h dans le dossier du firmware",
            defaultextension=".h",
            initialfile="rsv4_config.h",
            initialdir=default_dir if os.path.isdir(default_dir) else None,
            filetypes=[("En-tête C", "*.h")],
        )
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(make_header(cfg))
            self.set_state(f"Fichier firmware généré : {os.path.basename(p)}", GREEN)
