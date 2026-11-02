"""Enregistrements de l'ESP32 : commandes, liste, téléchargement et ouverture dans TrackLab."""

import os
import re
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .protocol import ID_FILE_CTL, ID_FILE_DATA, ID_FILE_LIST, REC_ERRORS
from .theme import BG, BORDER, CARD, CARD2, CYAN, FONT, GREEN, MUTED, RED, SUB, TEXT, YELLOW
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


LOCAL_RE = re.compile(r"^Enregistrement_(\d+)_.*\.trk$", re.I)
TREE_COLS = [("n", "N°", 56, "center"), ("date", "Date", 140, "w"), ("size", "Taille", 80, "e"),
             ("where", "Où", 100, "w"), ("state", "État", 110, "w")]


class RecordingMixin:
    """Enregistrements de l'ESP32 : liste, téléchargement automatique à la connexion, ouverture et suppression."""

    REC_DIR = os.path.join(os.path.expanduser("~"), "Documents", "TrackLab", "Enregistrements")

    def rec_init(self):
        self.rec_client = RecClient()
        self.rec_open_after = None  # numéro du fichier à ouvrir dès qu'il est téléchargé
        self.rec_queue = []  # [(numéro, taille)] à télécharger
        self.rec_req = None  # (numéro, taille, instant) du transfert demandé
        self.rec_failed = set()
        self.rec_trees = []  # tableaux à tenir à jour (carte de la page Paramétrage, fenêtre « Ouvrir »)
        self.rec_dialog = None
        self._rec_listed = False
        self._rec_was_on = False
        self._rec_shown = None

    def rec_reset_transfers(self):
        self.rec_queue = []
        self.rec_req = None
        self.rec_open_after = None
        self.rec_failed = set()

    # ---------- commandes ----------
    def send_quiet(self, text):
        """Envoie une commande à l'ESP32 sans boîte de dialogue ; renvoie False si la liaison Wi-Fi n'est pas là."""
        sock = getattr(self, "wifi_sock", None)
        if not self.live or sock is None:
            return False
        try:
            sock.sendall((text + "\n").encode())
        except OSError:
            return False
        return True

    def send_cmd(self, text):
        """Envoie une commande à l'ESP32 (liaison Wi-Fi uniquement) ; renvoie False si impossible."""
        if not self.live or getattr(self, "wifi_sock", None) is None:
            messagebox.showinfo(
                "Enregistrement Tracklab", "Connectez-vous d'abord à Tracklab en Wi-Fi (bouton Connexion)."
            )
            return False
        if not self.send_quiet(text):
            messagebox.showerror("Enregistrement Tracklab", "Commande non envoyée : liaison perdue.")
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

    # ---------- fichiers : carte Tracklab + copies sur le PC ----------
    def local_files(self):
        out = []
        try:
            names = os.listdir(self.REC_DIR)
        except OSError:
            return out
        for name in names:
            m = LOCAL_RE.match(name)
            if m:
                path = os.path.join(self.REC_DIR, name)
                try:
                    out.append({"n": int(m.group(1)), "size": os.path.getsize(path), "path": path,
                                "mtime": os.path.getmtime(path)})
                except OSError:
                    pass
        return out

    def rec_entries(self):
        """Liste fusionnée : fichiers de la carte Tracklab (avec leur copie PC si elle existe), puis copies PC seules."""
        local = self.local_files()
        used, entries = set(), []
        for n, size, cur in self.rec_client.files:
            loc = next((f for f in local if f["n"] == n and f["size"] == size), None)
            if loc:
                used.add(loc["path"])
            entries.append({"n": n, "size": size, "cur": cur, "card": True, "local": loc})
        for f in local:
            if f["path"] not in used:
                entries.append({"n": f["n"], "size": f["size"], "cur": False, "card": False, "local": f})
        entries.sort(key=lambda e: (-e["n"], -(e["local"]["mtime"] if e["local"] else 0)))
        return entries

    @staticmethod
    def entry_row(e, linked):
        loc = e["local"]
        date = time.strftime("%d/%m/%Y %H:%M", time.localtime(loc["mtime"])) if loc else "—"
        if e["card"] and loc:
            where = "Carte + PC"
        elif e["card"]:
            where = "Carte"
        else:
            where = "PC"
        if e["cur"]:
            state = "● en cours"
        elif e["card"] and not loc:
            state = "à télécharger" if linked else "sur la carte"
        else:
            state = "✓ disponible"
        return (f"{e['n']:04d}", date, fmt_size(e["size"]), where, state)

    def make_rec_tree(self, parent, height):
        """Tableau des enregistrements (mêmes colonnes dans la page Paramétrage et dans la fenêtre « Ouvrir »)."""
        box = tk.Frame(parent, bg=CARD)
        tree = ttk.Treeview(box, columns=[c[0] for c in TREE_COLS], show="headings", height=height, selectmode="browse")
        for key, label, width, anchor in TREE_COLS:
            tree.heading(key, text=label, anchor=anchor)
            tree.column(key, width=width, anchor=anchor, stretch=key == "state")
        tree.tag_configure("cur", foreground=RED)
        tree.tag_configure("ready", foreground=GREEN)
        tree.tag_configure("todo", foreground=YELLOW)
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.entries = []
        self.rec_trees.append(tree)
        return box, tree

    def fill_rec_tree(self, tree):
        keep = tree.selection()
        keep_n = tree.entries[int(keep[0])]["n"] if keep and tree.entries else None
        for it in tree.get_children():
            tree.delete(it)
        tree.entries = self.rec_entries()
        for i, e in enumerate(tree.entries):
            tag = "cur" if e["cur"] else ("ready" if e["local"] else "todo")
            tree.insert("", "end", iid=str(i), values=self.entry_row(e, self.live), tags=(tag,))
            if e["n"] == keep_n:
                tree.selection_set(str(i))

    def refresh_rec_trees(self):
        alive = []
        for tree in self.rec_trees:
            try:
                if tree.winfo_exists():
                    self.fill_rec_tree(tree)
                    alive.append(tree)
            except tk.TclError:
                pass
        self.rec_trees = alive

    @staticmethod
    def tree_entry(tree):
        sel = tree.selection()
        if not sel or int(sel[0]) >= len(tree.entries):
            messagebox.showinfo("Enregistrements Tracklab", "Choisissez d'abord un enregistrement dans la liste.")
            return None
        return tree.entries[int(sel[0])]

    # ---------- téléchargement (automatique à la connexion) ----------
    def rec_autodownload(self):
        """Dès que la liste de la carte est connue : télécharge tout ce qui n'est pas déjà sur le PC."""
        if not self.live:
            return
        local = self.local_files()
        self.rec_queue = [
            (n, size) for n, size, cur in self.rec_client.files
            if not cur and (n, size) not in self.rec_failed and not any(f["n"] == n and f["size"] == size for f in local)
        ]
        self.rec_next()

    def rec_next(self):
        if self.rec_client.dl is not None or self.rec_req is not None or not self.rec_queue or not self.live:
            return
        n, size = self.rec_queue.pop(0)
        left = len(self.rec_queue)
        self.rec_set_info(f"Téléchargement de l'enregistrement {n:04d}…" + (f" ({left} autre(s) ensuite)" if left else ""))
        if self.send_quiet(f"GET {n}"):
            self.rec_req = (n, size, time.monotonic())
        else:
            self.rec_queue = []

    def rec_fail(self, n, why=""):
        if self.rec_req and self.rec_req[0] == n:
            self.rec_failed.add((self.rec_req[0], self.rec_req[1]))
            self.rec_req = None
        if self.rec_open_after == n:
            self.rec_open_after = None
            if why:
                messagebox.showwarning("Enregistrement Tracklab", why)
        self.rec_set_info(why)
        self.rec_next()

    def rec_open_entry(self, e):
        """Ouvre un enregistrement : la copie du PC si elle existe, sinon on la télécharge d'abord."""
        if e["cur"]:
            messagebox.showinfo("Enregistrements Tracklab", "Cet enregistrement est en cours : arrêtez-le d'abord.")
            return False
        if e["local"]:
            self.open_recording(e["local"]["path"])
            return True
        if not (e["card"] and self.live):
            messagebox.showinfo("Enregistrements Tracklab", "Ce fichier est sur la carte Tracklab : connectez-vous pour le récupérer.")
            return False
        self.rec_open_after = e["n"]
        self.rec_queue = [q for q in self.rec_queue if q[0] != e["n"]]
        self.rec_queue.insert(0, (e["n"], e["size"]))
        self.rec_next()
        return True

    def open_recording(self, path):
        self.rec_open_after = None
        if self.live:
            self.disconnect()  # la liaison en direct et la lecture d'un fichier ne se mélangent pas
        self.load(path)
        if self.rec_dialog is not None:
            try:
                self.rec_dialog.destroy()
            except tk.TclError:
                pass
            self.rec_dialog = None

    def rec_delete_entry(self, e):
        if e["cur"]:
            messagebox.showinfo("Enregistrements Tracklab", "Cet enregistrement est en cours : arrêtez-le d'abord.")
            return
        on_card = e["card"] and self.live
        lines = []
        if on_card:
            lines.append("• la copie sur la carte Tracklab")
        if e["local"]:
            lines.append("• la copie sur ce PC")
        note = ""
        if e["card"] and not self.live:
            note = "\n\nLa copie sur la carte Tracklab restera : connectez-vous pour la supprimer aussi (sinon elle sera de nouveau téléchargée)."
        if not lines:
            messagebox.showinfo("Enregistrements Tracklab", "Connectez-vous à Tracklab pour supprimer ce fichier de la carte.")
            return
        if not messagebox.askyesno(
            "Supprimer", f"Supprimer définitivement l'enregistrement {e['n']:04d} ?\n\n" + "\n".join(lines) + note
        ):
            return
        if e["local"]:
            try:
                os.remove(e["local"]["path"])
            except OSError as exc:
                messagebox.showerror("Enregistrements Tracklab", f"Copie du PC non supprimée : {exc}")
        if on_card:
            self.send_quiet(f"DEL {e['n']}")
            self.send_quiet("LIST")
        self.refresh_rec_trees()

    def rec_open_folder(self):
        os.makedirs(self.REC_DIR, exist_ok=True)
        try:
            os.startfile(self.REC_DIR)  # Windows
        except AttributeError:
            messagebox.showinfo("Dossier des enregistrements", self.REC_DIR)

    # ---------- fenêtre « Ouvrir » ----------
    def open_choice(self):
        """Ouvrir : un fichier du PC ou un enregistrement Tracklab."""
        win = tk.Toplevel(self.root)
        win.title("Ouvrir")
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        card = tk.Frame(win, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(padx=18, pady=18)
        tk.Label(card, text="Ouvrir…", fg=TEXT, bg=CARD, font=(FONT, 13, "bold")).pack(anchor="w", padx=22, pady=(16, 10))
        def pick(cmd):
            win.destroy()
            cmd()
        for title, sub, cmd in (
            ("Un fichier sur ce PC", "Trames CAN, RaceBox, RaceChrono, enregistrement .trk… (type reconnu automatiquement)", self.open_pc_file),
            ("Un enregistrement Tracklab", "Fichiers enregistrés par Tracklab : ouvrir ou supprimer", self.open_tracklab_dialog),
        ):
            b = tk.Frame(card, bg=CARD2, cursor="hand2")
            b.pack(fill="x", padx=22, pady=5)
            t1 = tk.Label(b, text=title, fg=TEXT, bg=CARD2, font=(FONT, 11, "bold"), anchor="w", cursor="hand2")
            t1.pack(fill="x", padx=14, pady=(10, 0))
            t2 = tk.Label(b, text=sub, fg=SUB, bg=CARD2, font=(FONT, 8), anchor="w", cursor="hand2")
            t2.pack(fill="x", padx=14, pady=(0, 10))
            for w in (b, t1, t2):
                w.bind("<Button-1>", lambda e, c=cmd: pick(c))
                w.bind("<Enter>", lambda e, bb=b, a=t1, c2=t2: [x.config(bg="#1f2e47") for x in (bb, a, c2)])
                w.bind("<Leave>", lambda e, bb=b, a=t1, c2=t2: [x.config(bg=CARD2) for x in (bb, a, c2)])
        self.button(card, "Annuler", win.destroy, SUB, CARD2, font=9).pack(anchor="e", padx=22, pady=(8, 16))
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 120
        win.geometry(f"+{x}+{y}")
        win.grab_set()

    def open_tracklab_dialog(self):
        """Liste des enregistrements Tracklab (carte + copies PC) : ouvrir ou supprimer."""
        if self.rec_dialog is not None:
            try:
                self.rec_dialog.lift()
                return
            except tk.TclError:
                self.rec_dialog = None
        win = tk.Toplevel(self.root)
        win.title("Enregistrements Tracklab")
        win.configure(bg=BG)
        win.transient(self.root)
        self.rec_dialog = win
        card = tk.Frame(win, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(card, text="Enregistrements Tracklab", fg=TEXT, bg=CARD, font=(FONT, 13, "bold")).pack(anchor="w", padx=18, pady=(14, 2))
        info = tk.Label(card, text="", fg=SUB, bg=CARD, font=(FONT, 9), anchor="w")
        info.pack(fill="x", padx=18, pady=(0, 8))
        box, tree = self.make_rec_tree(card, 12)
        box.pack(fill="both", expand=True, padx=18)
        tree.bind("<Double-1>", lambda e: self.tree_entry_do(tree, self.rec_open_entry))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=18, pady=12)
        self.button(row, "Ouvrir", lambda: self.tree_entry_do(tree, self.rec_open_entry), "#ffffff", RED, font=9).pack(side="left")
        self.button(row, "Supprimer", lambda: self.tree_entry_do(tree, self.rec_delete_entry), TEXT, CARD2, font=9).pack(side="left", padx=6)
        self.button(row, "Actualiser", lambda: (self.live and self.send_quiet("LIST"), self.refresh_rec_trees()), TEXT, CARD2, font=9).pack(side="left")
        self.button(row, "Ouvrir le dossier", self.rec_open_folder, SUB, CARD2, font=9).pack(side="left", padx=6)
        self.button(row, "Fermer", win.destroy, SUB, CARD2, font=9).pack(side="right")
        info.config(text=("Connecté : les enregistrements de la carte sont téléchargés automatiquement." if self.live
                          else "Non connecté : seules les copies déjà téléchargées sur ce PC sont listées."))
        if self.live:
            self.send_quiet("LIST")
        self.fill_rec_tree(tree)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        win.geometry(f"+{max(0, x)}+{self.root.winfo_rooty() + 90}")

    def tree_entry_do(self, tree, action):
        e = self.tree_entry(tree)
        if e is not None:
            action(e)

    # ---------- trames reçues ----------
    def on_file_frame(self, cid, data):
        event = self.rec_client.feed(cid, data)
        if not event:
            return
        kind = event[0]
        if kind == "list":
            self.refresh_rec_list(error=event[1])
            self.rec_autodownload()
        elif kind == "progress":
            _, n, got, size = event
            if self.rec_req:
                self.rec_req = (self.rec_req[0], self.rec_req[1], time.monotonic())
            self.rec_set_info(f"Téléchargement {n:04d} : {fmt_size(got)} / {fmt_size(size)}")
        elif kind == "done":
            self.on_download_done(*event[1:])
        elif kind == "error":
            _, n, code = event
            self.rec_fail(n, REC_ERRORS.get(code, f"erreur {code}").capitalize() + ".")

    def on_download_done(self, n, payload, ok):
        if not ok:
            self.rec_fail(n, f"Le fichier {n:04d} est incomplet ou corrompu : il sera réessayé à la prochaine connexion.")
            return
        os.makedirs(self.REC_DIR, exist_ok=True)
        path = os.path.join(self.REC_DIR, f"Enregistrement_{n:04d}_{time.strftime('%Y%m%d_%H%M%S')}.trk")
        with open(path, "wb") as f:
            f.write(payload)
        self.rec_req = None
        self.rec_set_info(f"Enregistré : {os.path.basename(path)} ({fmt_size(len(payload))})")
        self.refresh_rec_trees()
        if self.rec_open_after == n:
            self.open_recording(path)
            return
        if self.rec_queue:
            self.rec_next()
        else:
            self.set_state(f"Enregistrement {n:04d} sauvegardé sur le PC", GREEN)

    # ---------- interface ----------
    def rec_set_info(self, text):
        if self.rec_info.cget("text") != text:
            self.rec_info.config(text=text)

    def build_rec_card(self, parent):
        c = self.esp_card(parent, "Enregistrements Tracklab (bouton physique ou TrackLab)")
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x", pady=(0, 6))
        self.rec_dot = make_dot(top, MUTED, CARD, 10)
        self.rec_dot.pack(side="left", padx=(0, 8))
        self.rec_state = tk.Label(top, text="—", fg=TEXT, bg=CARD, font=(FONT, 9, "bold"))
        self.rec_state.pack(side="left")
        self.rec_btn2 = self.button(top, "Démarrer", self.rec_toggle, "#ffffff", RED, font=9)
        self.rec_btn2.pack(side="right")
        box, self.rec_tree = self.make_rec_tree(c, 7)
        box.pack(fill="x")
        self.rec_tree.bind("<Double-1>", lambda e: self.tree_entry_do(self.rec_tree, self.rec_open_entry))
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        for text, cmd in (
            ("Ouvrir", lambda: self.tree_entry_do(self.rec_tree, self.rec_open_entry)),
            ("Supprimer", lambda: self.tree_entry_do(self.rec_tree, self.rec_delete_entry)),
            ("Actualiser", self.rec_list),
        ):
            self.button(row, text, cmd, TEXT, CARD2, font=9).pack(side="left", padx=(0, 4))
        self.rec_info = tk.Label(c, text="", fg=SUB, bg=CARD, font=(FONT, 9), anchor="w", justify="left", wraplength=430)
        self.rec_info.pack(fill="x", pady=(6, 0))
        folder = tk.Frame(c, bg=CARD)
        folder.pack(fill="x", pady=(4, 0))
        tk.Label(folder, text="Téléchargés automatiquement dans : " + self.REC_DIR, fg=MUTED, bg=CARD, font=(FONT, 8),
                 anchor="w", justify="left", wraplength=330).pack(side="left")
        self.button(folder, "Ouvrir le dossier", self.rec_open_folder, TEXT, CARD2, font=8).pack(side="right")
        self.refresh_rec_list()

    def refresh_rec_list(self, error=False):
        self.refresh_rec_trees()
        n = len(self.rec_client.files)
        if error:
            self.rec_set_info("Aucun stockage sur Tracklab (carte SD absente ?)")
        elif not n:
            self.rec_set_info("Aucun enregistrement sur Tracklab." if self.live else "Connectez-vous pour voir les enregistrements de la carte.")
        elif self.rec_req is None and not self.rec_queue:
            self.rec_set_info(f"{n} enregistrement(s) sur la carte Tracklab.")

    def update_rec_live(self, esp, link_ok):
        """État de l'enregistrement dans la page Paramétrage Tracklab et sur la platine."""
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
        if on and not self._rec_was_on and self.table_paused:
            self.toggle_table_pause()  # au démarrage d'un enregistrement, les trames reçues défilent dans le moniteur
        # la liste se met à jour toute seule : à la connexion et quand un enregistrement se termine
        if link_ok and esp:
            if not self._rec_listed or (self._rec_was_on and not on):
                self._rec_listed = True  # une seule tentative : pas de boîte de dialogue en boucle
                self.send_quiet("LIST")
        # transfert sans réponse depuis trop longtemps : on passe au suivant
        if self.rec_req and time.monotonic() - self.rec_req[2] > 20:
            self.rec_fail(self.rec_req[0], "Pas de réponse de Tracklab pour ce fichier.")
        self._rec_was_on = on
