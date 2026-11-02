"""Enregistrements de l'ESP32 : commandes, liste, téléchargement et ouverture dans TrackLab."""

import os
import time
import tkinter as tk
from tkinter import messagebox

from .protocol import ID_FILE_CTL, ID_FILE_DATA, ID_FILE_LIST, REC_ERRORS
from .theme import BORDER, CARD, CARD2, FONT, GREEN, MUTED, RED, SUB, TEXT, YELLOW
from .widgets import make_dot, set_dot


def fmt_size(n):
    """Taille lisible : « 812 o », « 48,5 Ko », « 2,3 Mo »."""
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} Ko".replace(".", ",")
    return f"{n / 1048576:.1f} Mo".replace(".", ",")


class RecClient:
    """Décode les trames de gestion des fichiers envoyées par l'ESP32 (sans interface graphique)."""

    def __init__(self):
        self.files = []        # [(numéro, taille, en_cours)]
        self._pending = []
        self.dl = None         # transfert en cours : {"no", "size", "buf", "sum"}

    def feed(self, cid, data):
        """Traite une trame ; renvoie un évènement (nom, ...) ou None."""
        if cid == ID_FILE_LIST and len(data) >= 7:
            n = int.from_bytes(data[0:2], "little")
            size = int.from_bytes(data[2:6], "little")
            if n == 0xFFFF:
                self.files = sorted(self._pending)
                self._pending = []
                return ("list", data[6] & 0x80 != 0)
            self._pending.append((n, size, bool(data[6] & 1)))
            return None
        if cid == ID_FILE_DATA:
            if self.dl is not None:
                self.dl["buf"].extend(data)
                self.dl["sum"] = (self.dl["sum"] + sum(data)) & 0xFFFFFFFF
                return ("progress", self.dl["no"], len(self.dl["buf"]), self.dl["size"])
            return None
        if cid == ID_FILE_CTL and len(data) >= 7:
            kind = data[0]
            n = int.from_bytes(data[1:3], "little")
            value = int.from_bytes(data[3:7], "little")
            if kind == 1:
                self.dl = {"no": n, "size": value, "buf": bytearray(), "sum": 0}
                return ("start", n, value)
            if kind == 2 and self.dl is not None:
                dl, self.dl = self.dl, None
                ok = len(dl["buf"]) == dl["size"] and dl["sum"] == value
                return ("done", n, bytes(dl["buf"]), ok)
            if kind == 3:
                self.dl = None
                return ("error", n, value)
        return None


class RecordingMixin:
    """Boutons et état de l'enregistrement de l'ESP32 (page Paramétrage ESP32 et barre du haut)."""

    REC_DIR = os.path.join(os.path.expanduser("~"), "Documents", "TrackLab", "Enregistrements")

    def rec_init(self):
        self.rec_client = RecClient()
        self.rec_open_after = False
        self._rec_listed = False
        self._rec_was_on = False
        self._rec_shown = None

    # ---------- commandes ----------
    def send_cmd(self, text):
        """Envoie une commande à l'ESP32 (liaison Wi-Fi uniquement) ; renvoie False si impossible."""
        sock = getattr(self, "wifi_sock", None)
        if not self.live or sock is None:
            messagebox.showinfo(
                "Enregistrement ESP32", "Connectez-vous d'abord à l'ESP32 en Wi-Fi (bouton Connexion)."
            )
            return False
        try:
            sock.sendall((text + "\n").encode())
        except OSError as exc:
            messagebox.showerror("Enregistrement ESP32", f"Commande non envoyée : {exc}")
            return False
        return True

    def rec_active(self):
        esp = self.esp or {}
        return bool(esp.get("rec"))

    def rec_toggle(self):
        self.send_cmd("REC 0" if self.rec_active() else "REC 1")

    def rec_list(self):
        if self.send_cmd("LIST"):
            self._rec_listed = True

    def rec_selected(self):
        sel = self.rec_box.curselection()
        if not sel or sel[0] >= len(self.rec_client.files):
            messagebox.showinfo("Enregistrement ESP32", "Choisissez d'abord un enregistrement dans la liste, puis cliquez sur Télécharger.")
            return None
        return self.rec_client.files[sel[0]]

    def rec_download(self, open_after):
        item = self.rec_selected()
        if item is None:
            return
        if item[2]:
            messagebox.showinfo("Enregistrement ESP32", "Cet enregistrement est en cours : arrêtez-le d'abord.")
            return
        if self.rec_client.dl is not None:
            return
        self.rec_open_after = open_after
        self.rec_set_info(f"Téléchargement de l'enregistrement {item[0]:04d}…")
        self.send_cmd(f"GET {item[0]}")

    def rec_delete(self):
        item = self.rec_selected()
        if item is None or item[2]:
            return
        if messagebox.askyesno("Supprimer", f"Supprimer l'enregistrement {item[0]:04d} de l'ESP32 ?"):
            self.send_cmd(f"DEL {item[0]}")

    def rec_open_folder(self):
        os.makedirs(self.REC_DIR, exist_ok=True)
        try:
            os.startfile(self.REC_DIR)  # Windows
        except AttributeError:
            messagebox.showinfo("Dossier des enregistrements", self.REC_DIR)

    # ---------- trames reçues ----------
    def on_file_frame(self, cid, data):
        event = self.rec_client.feed(cid, data)
        if not event:
            return
        kind = event[0]
        if kind == "list":
            self.refresh_rec_list(error=event[1])
        elif kind == "progress":
            _, n, got, size = event
            self.rec_set_info(f"Téléchargement {n:04d} : {fmt_size(got)} / {fmt_size(size)}")
        elif kind == "done":
            self.on_download_done(*event[1:])
        elif kind == "error":
            _, n, code = event
            self.rec_set_info("")
            messagebox.showwarning("Enregistrement ESP32", REC_ERRORS.get(code, f"erreur {code}").capitalize() + ".")

    def on_download_done(self, n, payload, ok):
        if not ok:
            self.rec_set_info("")
            messagebox.showerror(
                "Enregistrement ESP32", f"Le fichier {n:04d} est incomplet ou corrompu. Réessayez le téléchargement."
            )
            return
        os.makedirs(self.REC_DIR, exist_ok=True)
        path = os.path.join(self.REC_DIR, f"Enregistrement_{n:04d}_{time.strftime('%Y%m%d_%H%M%S')}.trk")
        with open(path, "wb") as f:
            f.write(payload)
        self.rec_set_info(f"Enregistré : {os.path.basename(path)} ({fmt_size(len(payload))})")
        if self.rec_open_after:
            self.disconnect()  # la liaison en direct et la lecture d'un fichier ne se mélangent pas
            self.load(path)
            self.show_page("tele")
        else:
            self.set_state(f"Enregistrement sauvegardé : {path}", GREEN)

    # ---------- interface ----------
    def rec_set_info(self, text):
        if self.rec_info.cget("text") != text:
            self.rec_info.config(text=text)

    def build_rec_card(self, parent):
        c = self.esp_card(parent, "Enregistrements de l'ESP32 (bouton physique ou TrackLab)")
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x", pady=(0, 6))
        self.rec_dot = make_dot(top, MUTED, CARD, 10)
        self.rec_dot.pack(side="left", padx=(0, 8))
        self.rec_state = tk.Label(top, text="—", fg=TEXT, bg=CARD, font=(FONT, 9, "bold"))
        self.rec_state.pack(side="left")
        self.rec_btn2 = self.button(top, "Démarrer", self.rec_toggle, "#ffffff", RED, font=9)
        self.rec_btn2.pack(side="right")
        self.rec_box = tk.Listbox(
            c, height=6, bg=CARD2, fg=TEXT, selectbackground=RED, selectforeground="#ffffff", bd=0,
            highlightthickness=1, highlightbackground=BORDER, font=("Consolas", 10), exportselection=False,
        )
        self.rec_box.pack(fill="x")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        for text, cmd in (
            ("Télécharger et ouvrir", lambda: self.rec_download(True)),
            ("Télécharger", lambda: self.rec_download(False)),
            ("Supprimer", self.rec_delete),
            ("Actualiser", self.rec_list),
        ):
            self.button(row, text, cmd, TEXT, CARD2, font=9).pack(side="left", padx=(0, 4))
        self.rec_info = tk.Label(c, text="", fg=SUB, bg=CARD, font=(FONT, 9), anchor="w")
        self.rec_info.pack(fill="x", pady=(6, 0))
        folder = tk.Frame(c, bg=CARD)
        folder.pack(fill="x", pady=(4, 0))
        tk.Label(folder, text="Dossier : " + self.REC_DIR, fg=MUTED, bg=CARD, font=(FONT, 8), anchor="w").pack(side="left")
        self.button(folder, "Ouvrir le dossier", self.rec_open_folder, TEXT, CARD2, font=8).pack(side="right")
        self.refresh_rec_list()

    def refresh_rec_list(self, error=False):
        sel = self.rec_box.curselection()
        self.rec_box.delete(0, "end")
        for n, size, cur in self.rec_client.files:
            self.rec_box.insert("end", f"{n:04d}   {fmt_size(size):>9}   {'en cours' if cur else ''}")
        if sel and sel[0] < self.rec_box.size():
            self.rec_box.selection_set(sel[0])
        if error:
            self.rec_set_info("Aucun stockage sur l'ESP32 (carte SD absente ?)")
        elif not self.rec_client.files:
            self.rec_set_info("Aucun enregistrement sur l'ESP32.")
        else:
            self.rec_set_info(f"{len(self.rec_client.files)} enregistrement(s) sur l'ESP32 · sélectionnez-en un.")

    def update_rec_live(self, esp, link_ok):
        """État de l'enregistrement dans la page Paramétrage ESP32 et dans la barre du haut."""
        on = bool(esp and esp.get("rec"))
        if esp and link_ok:
            if not esp.get("store"):
                shown = ("Aucun stockage (carte SD absente ?)", YELLOW, "Démarrer", False)
            elif on:
                shown = (
                    f"EN COURS · fichier {esp['rec_no']:04d} · {fmt_size(esp['rec_bytes'])}", RED, "Arrêter", True
                )
            else:
                free = esp.get("free_mb", 0)
                kind = "carte SD" if esp.get("sd") else "mémoire interne"
                shown = (f"Arrêté · {kind} · {free} Mo libres", GREEN, "Démarrer", True)
        else:
            shown = ("—", MUTED, "Démarrer", False)
        if shown != self._rec_shown:
            self._rec_shown = shown
            text, color, label, enabled = shown
            set_dot(self.rec_dot, color)
            self.rec_state.config(text=text)
            self.rec_btn2.config(text=label, bg=CARD2 if on else RED, state="normal" if enabled else "disabled")
            self.rec_btn.set_look(lit=on, kind="stop" if on else "rec", caption="STOP" if on else "ENREG.",
                                  enabled=enabled)
        # la liste se met à jour toute seule : à la connexion et quand un enregistrement se termine
        if link_ok and esp:
            if not self._rec_listed or (self._rec_was_on and not on):
                self._rec_listed = True  # une seule tentative : pas de boîte de dialogue en boucle
                try:
                    self.wifi_sock.sendall(b"LIST\n")
                except (OSError, AttributeError):
                    pass
        self._rec_was_on = on
