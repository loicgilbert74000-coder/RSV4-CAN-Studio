"""Lecture des captures : chargement, lecture, saut dans le temps."""

import bisect
import os
import time
from tkinter import filedialog, messagebox

from .config import SEEK_BACK
from .formats import load_any
from .theme import GREEN, RED, SUB, YELLOW
from .util import fmt_time


class PlayerMixin:
    """Lecture des captures : chargement, lecture, saut dans le temps."""

    def open_file(self):
        p = filedialog.askopenfilename(
            title="Ouvrir un fichier (trames CAN, RaceBox, RaceChrono, TrackLab…) : le type est reconnu automatiquement",
            filetypes=[
                ("Tous les fichiers pris en charge", "*.txt *.log *.trk *.csv *.vbo *.tsv"),
                ("Tous fichiers", "*.*"),
            ],
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
        self.pan = None
        self.zsel = None
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
            res = load_any(path)
        except Exception as exc:
            messagebox.showerror("Fichier non lu", str(exc))
            return
        frames = res.frames
        self.pause()
        self.frames = frames
        self.frame_times = [f[0] for f in frames]
        self.idx = 0
        self.full_t = {}
        self.full_v = {}
        self.dyn = dict(res.dyn)
        self.clear_data()
        self.file_name.set(f"{os.path.basename(path)}  ·  {res.label}")
        if not frames:
            self.set_state("0 trame · fichier vide", RED)
            messagebox.showwarning("Fichier vide", f"Format reconnu ({res.label}) mais aucune donnée exploitable n'a été trouvée.")
        else:
            info = f" · {res.info}" if res.info else ""
            self.set_state(f"{res.label} · {len(frames):,} trames{info}".replace(",", " "), SUB)
            self.prebuild()
            self.choose_curves()
            self.fit_all()
            if res.dyn:
                self.seek(1.0)  # on montre tout de suite le fichier en entier
                self.fit_all()
                self.show_page("graph")

    def choose_curves(self):
        """Après l'ouverture : ne garde que les signaux présents dans le fichier ; à défaut, en propose quelques-uns."""
        present = set(self.full_t)
        keep = {k for k in self.sel if k in present}
        if not keep:
            pri = [k for k in present if k[0] == 2040 and k[1] == "GPS Vitesse"]
            skip = {"GPS Latitude", "GPS Longitude", "Satellites", "Qualité fix"}
            pri += sorted((k for k in present if k not in pri and k[1] not in skip), key=lambda k: (k[0], k[1]))
            keep = set(pri[:5])
        self.sel = keep
        for k in sorted(keep):
            self.assign_color(k)
        self.signal_list.set_groups(self.signal_groups(), self.sel)

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
        if not self.frames:
            return
        keep = keep or self.idx
        self.playing = False
        self.set_state("Analyse de la capture…", YELLOW)
        self.root.update_idletasks()
        self.clear_data()
        self.hist_max = None
        self.bulk = True
        try:
            for fr in self.frames[:1500000]:
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
