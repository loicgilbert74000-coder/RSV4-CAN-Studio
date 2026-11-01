"""Lecture des captures : chargement, lecture, saut dans le temps."""

import bisect
import os
import time
from tkinter import filedialog, messagebox

from .config import SEEK_BACK
from .protocol import load_capture
from .theme import GREEN, RED, SUB, YELLOW
from .util import fmt_time


class PlayerMixin:
    """Lecture des captures : chargement, lecture, saut dans le temps."""

    def open_file(self):
        p = filedialog.askopenfilename(
            title="Choisir une capture USB-CAN ou un enregistrement TrackLab (.trk)",
            filetypes=[("Captures et enregistrements", "*.txt *.log *.trk"), ("Tous fichiers", "*.*")],
        )
        if p:
            self.load(p)

    def clear_data(self):
        self.count.clear()
        self.first_t.clear()
        self.last_t.clear()
        self.recent.clear()
        self.esp = None
        self.link_t = None
        self._rec_listed = False
        self._rec_was_on = False
        self.rec_client.files = []
        self.rec_client.dl = None
        self.ingested = 0
        self.t_last = 0
        self.t_now = 0
        self.vals.clear()
        self.hist.clear()
        self.dirty.clear()
        self.flash_until.clear()
        self.track.clear()
        self.view_end = None
        self.clear_table()
        for key in self.cards:
            self.show(key, None)
        self.gear.set(None)
        self.gear_val.config(text="—")
        self.rpm.set(None)
        self.speedg.set(None)
        self.tps_lbl.config(text="TPS1 —  ·  TPS2 —")
        self.board.reset()

    def load(self, path):
        try:
            frames = load_capture(path)
        except Exception as exc:
            messagebox.showerror("Erreur de lecture", str(exc))
            return
        self.pause()
        self.frames = frames
        self.frame_times = [f[0] for f in frames]
        self.idx = 0
        self.full_t = {}
        self.full_v = {}
        self.clear_data()
        self.file_name.set(os.path.basename(path))
        if not frames:
            self.set_state("0 trame · format non reconnu", RED)
            messagebox.showwarning(
                "0 trame",
                "Le fichier ne contient pas de trames USB-CAN reconnaissables. Vérifiez qu'il s'agit d'un export TXT du logiciel USBCAN.",
            )
        else:
            self.set_state(f"{len(frames):,} trames chargées".replace(",", " "), SUB)
            self.prebuild()

    def play(self):
        if not self.frames:
            messagebox.showinfo("Capture", "Importez d'abord une capture TXT.")
            return
        self.playing = True
        self.start_wall = time.monotonic()
        self.start_frame = self.frames[self.idx][0] if self.idx < len(self.frames) else 0
        self.set_state("Lecture en cours", GREEN)

    def pause(self):
        was = self.playing
        self.playing = False
        if was and self.frames and (self.idx < len(self.frames)):
            self.set_state("En pause", YELLOW)

    def prebuild(self, keep=0):
        """Décode toute la capture une fois pour toutes : les courbes montrent alors la fenêtre entière autour de l'instant courant."""
        self.full_t = {}
        self.full_v = {}
        if not self.frames or self.decoder is None:
            return
        keep = keep or self.idx
        self.playing = False
        self.set_state("Analyse de la capture…", YELLOW)
        self.root.update_idletasks()
        self.clear_data()
        self.hist_max = None
        self.bulk = True
        try:
            for fr in self.frames[:300000]:
                self.ingest(*fr)
        finally:
            self.bulk = False
            self.hist_max = 20000
        for k, d in self.hist.items():
            self.full_t[k] = [p[0] for p in d]
            self.full_v[k] = [p[1] for p in d]
        self.clear_data()
        self.idx = 0
        if keep:
            self.seek(self.frames[keep - 1][0] / max(1, self.frames[-1][0]))
        else:
            self.set_state(f"{len(self.frames):,} trames chargées".replace(",", " "), SUB)

    def on_seek_drag(self, frac):
        if self.frames:
            total = self.frames[-1][0]
            self.clock.set(f"{fmt_time(frac * total)} / {fmt_time(total)}")

    def seek(self, frac):
        """Saute à un instant de la capture : on rejoue les trames qui précèdent pour reconstituer les valeurs et les courbes."""
        if not self.frames:
            return
        was = self.playing
        self.playing = False
        total = self.frames[-1][0]
        target = bisect.bisect_right(self.frame_times, frac * total)
        target = max(0, min(len(self.frames), target))
        begin = max(0, target - SEEK_BACK)
        self.clear_data()
        for fr in self.frames[:begin]:  # le tracé du circuit est reconstitué sur toute la partie sautée
            if fr[1] == 2032 and len(fr[2]) >= 8:
                la = int.from_bytes(fr[2][0:4], "little", signed=True) / 10000000.0
                lo = int.from_bytes(fr[2][4:8], "little", signed=True) / 10000000.0
                if la or lo:
                    self.track.append((la, lo))
        self.bulk = True
        try:
            for i in range(begin, target):
                self.ingest(*self.frames[i])
        finally:
            self.bulk = False
        self.idx = target
        self.ingested = target
        self.rebuild_table()
        if target > 0:
            self.t_now = self.frames[target - 1][0]
        if was and target < len(self.frames):
            self.start_wall = time.monotonic()
            self.start_frame = self.frames[target][0]
            self.playing = True
            self.set_state("Lecture en cours", GREEN)
        else:
            self.set_state(f"En pause · {fmt_time(self.t_now)}", YELLOW)

    def reset(self):
        self.pause()
        self.idx = 0
        self.clear_data()
        if self.frames:
            self.set_state("Début de capture", SUB)
