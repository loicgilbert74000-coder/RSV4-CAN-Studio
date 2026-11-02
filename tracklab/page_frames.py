"""Page Trames CAN : tableau des trames avec filtres."""

import tkinter as tk
from tkinter import ttk

from .theme import BORDER, CARD, CARD2, CYAN, FONT, GREEN, MUTED, RED, SUB, TEXT, YELLOW
from .util import parse_ids


class FramesMixin:
    """Page Trames CAN : tableau des trames avec filtres."""

    # ---------- trames ----------
    def build_table(self, parent):
        card = self.card(parent)
        card.pack(fill="both", expand=True, padx=4, pady=4)
        hdr = tk.Frame(card, bg=CARD)
        hdr.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(
            hdr, text="Trames CAN en direct", fg=TEXT, bg=CARD, font=(FONT, 12, "bold")
        ).pack(side="left")
        self.button(hdr, "Vider", self.clear_table, SUB, CARD2, font=9).pack(side="right")
        self.pause_btn = self.button(hdr, "⏸  Arrêter le direct", self.toggle_table_pause, YELLOW, CARD2, font=9)
        self.pause_btn.pack(side="right", padx=8)
        self.pause_lbl = tk.Label(hdr, text="", fg=YELLOW, bg=CARD, font=(FONT, 9, "bold"))
        self.pause_lbl.pack(side="left", padx=12)
        tk.Checkbutton(
            hdr,
            text="Trames décodées seulement",
            variable=self.filter_on,
            command=self.rebuild_table,
            bg=CARD,
            fg=SUB,
            selectcolor=CARD2,
            activebackground=CARD,
            font=(FONT, 9),
            bd=0,
            highlightthickness=0,
        ).pack(side="right", padx=12)
        fl = tk.Frame(card, bg=CARD)
        fl.pack(fill="x", padx=14, pady=(0, 6))
        def field(label, var, width):
            tk.Label(fl, text=label, fg=SUB, bg=CARD, font=(FONT, 9)).pack(side="left", padx=(0, 4))
            e = tk.Entry(
                fl,
                textvariable=var,
                width=width,
                bg=CARD2,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=CYAN,
                font=(FONT, 9),
            )
            e.pack(side="left", padx=(0, 14), ipady=3)
            return e
        self.e_show = field("Afficher les ID (hex)", self.f_show, 18)
        self.e_hide = field("Masquer les ID", self.f_hide, 18)
        self.e_text = field("Contient", self.f_text, 18)
        self.button(fl, "Réinitialiser", self.reset_filters, SUB, CARD2, font=9).pack(side="left")
        self.count_lbl = tk.Label(fl, text="", fg=SUB, bg=CARD, font=(FONT, 9))
        self.count_lbl.pack(side="right")
        tk.Label(
            card,
            text="ID en hexadécimal, séparés par des virgules, plages avec un tiret : 100, 2A0-2FF.   « Contient » cherche dans l'ID, les octets et le décodage.",
            fg=MUTED,
            bg=CARD,
            font=(FONT, 8),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 6))
        for v in (self.f_show, self.f_hide, self.f_text):
            v.trace_add("write", lambda *a: self.schedule_filter())
        tw = tk.Frame(card, bg=CARD)
        tw.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        cols = [
            ("n", "#", 55, "e"),
            ("time", "Temps", 95, "w"),
            ("id", "ID", 75, "w"),
            ("dlc", "DLC", 45, "center"),
            ("hex", "Hex", 190, "w"),
            ("dec", "Décimal", 190, "w"),
            ("freq", "Fréq. (Hz)", 85, "e"),
            ("txt", "Décodage / signaux", 440, "w"),
        ]
        self.table = ttk.Treeview(tw, columns=[c[0] for c in cols], show="headings", height=6)
        for key, label, width, anchor in cols:
            self.table.heading(key, text=label, anchor=anchor)
            self.table.column(key, width=width, anchor=anchor, stretch=key == "txt")
        self.table.tag_configure("new", background="#174a36", foreground=TEXT)
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=sb.set)
        self.table.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def toggle_table_pause(self):
        """Fige ou reprend l'affichage du tableau ; les trames continuent d'être reçues et mémorisées."""
        self.table_paused = not self.table_paused
        if self.table_paused:
            self.pause_btn.config(text="▶  Reprendre le direct", fg=GREEN)
            self.pause_lbl.config(text="Affichage arrêté · la réception continue")
        else:
            self.pause_btn.config(text="⏸  Arrêter le direct", fg=YELLOW)
            self.pause_lbl.config(text="")
            self.rebuild_table()

    # filtrage : les trames récentes sont gardées en mémoire (self.rows), le tableau n'en montre que 400 qui correspondent
    def schedule_filter(self):
        if self._fid:
            try:
                self.root.after_cancel(self._fid)
            except Exception:
                pass
        self._fid = self.root.after(250, self.on_filter_change)

    def on_filter_change(self):
        self._fid = None
        self.id_show, ok1 = parse_ids(self.f_show.get())
        self.id_hide, ok2 = parse_ids(self.f_hide.get())
        self.ftext = self.f_text.get().strip().lower()
        self.e_show.config(fg=TEXT if ok1 else RED)
        self.e_hide.config(fg=TEXT if ok2 else RED)
        self.rebuild_table()

    def reset_filters(self):
        self.f_show.set("")
        self.f_hide.set("")
        self.f_text.set("")
        self.filter_on.set(False)
        self.on_filter_change()

    def row_match(self, row):
        cid = row[2]
        if self.id_show and (not any((a <= cid <= b for a, b in self.id_show))):
            return False
        if self.id_hide and any((a <= cid <= b for a, b in self.id_hide)):
            return False
        if self.filter_on.get() and self.decoder is not None and (row[7] == "—"):
            return False
        if self.ftext and self.ftext not in f"{cid:03x} 0x{cid:03x} {row[4]} {row[7]}".lower():
            return False
        return True

    def table_insert(self, row, where=0):
        vals = (row[0], row[1], f"0x{row[2]:03X}", row[3], row[4], row[5], row[6], row[7])
        return self.table.insert("", where, values=vals, tags=("new",) if where == 0 else ())

    def rebuild_table(self):
        for it in self.table.get_children():
            self.table.delete(it)
        shown = 0
        self.matched = 0
        for row in reversed(self.rows):
            if self.row_match(row):
                self.matched += 1
                if shown < 400:
                    self.table_insert(row, "end")
                    shown += 1
        self.last_row = None
        self.refresh_count()

    def refresh_count(self):
        self.count_lbl.config(
            text=f"{len(self.rows)} en mémoire" if self.table_paused else f"{self.matched} trames correspondent · {len(self.rows)} en mémoire"
        )

    def clear_table(self):
        for row in self.table.get_children():
            self.table.delete(row)
        self.rows.clear()
        self.matched = 0
        self.last_row = None
        self.refresh_count()
