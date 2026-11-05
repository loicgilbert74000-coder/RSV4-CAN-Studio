"""Lecture des captures : chargement, lecture, saut dans le temps."""

import bisect
import os
import time
from tkinter import filedialog, messagebox

from .config import SEEK_BACK
from .formats import B_SUFFIX, load_any, merge_compare
from .theme import GREEN, RED, SUB, YELLOW
from .util import fmt_time


class PlayerMixin:
    """Lecture des captures : chargement, lecture, saut dans le temps."""

    def open_file(self):
        """Ouvrir : choix entre un fichier du PC et un enregistrement Tracklab."""
        self.open_choice()

    def open_pc_file(self):
        p = self.dlg.askopenfilename(
            title="Ouvrir un fichier (trames CAN, RaceBox, RaceChrono, Tracklab…) : le type est reconnu automatiquement",
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
        self.rec_reset_transfers()
        self.ingested = 0
        self.t_last = 0
        self.t_now = 0
        self.vals.clear()
        self.hist.clear()
        self.dirty.clear()
        self.flash_until.clear()
        self.card_state.clear()
        self.tile_state.clear()
        self.track.clear()
        self.yr_live = {}
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
        self.loading = True
        try:
            self.progress_show(f"Lecture de {os.path.basename(path)}…", 3)
            try:
                res = load_any(path)
            except Exception as exc:
                self.progress_hide()
                self.dlg.showerror("Fichier non lu", str(exc))
                return
            self.primary, self.primary_path, self.compare_name = res, path, None
            self._load_result(path, res)
        finally:
            self.progress_hide()
            self.loading = False

    def open_compare(self, *_a):
        p = self.dlg.askopenfilename(
            title="Fichier à comparer avec la session ouverte (RaceBox, RaceChrono, CSV GPS…)",
            filetypes=[("Sessions GPS", "*.csv *.vbo *.tsv *.txt"), ("Tous fichiers", "*.*")],
        )
        if p:
            self.load_compare(p)

    def load_compare(self, path, mode=None):
        """Ajoute un 2e fichier GPS à comparer avec le premier (voies suffixées « [B] », 2e tracé sur le circuit)."""
        a = getattr(self, "primary", None)
        if a is None or a.kind in ("trk", "usbcan", "serial"):
            self.dlg.showwarning("Comparaison", "Ouvrez d'abord une session GPS (RaceBox, RaceChrono, CSV…) : c'est elle qui sera comparée.")
            return
        self.loading = True
        try:
            self.progress_show(f"Lecture de {os.path.basename(path)}…", 3)
            try:
                sec = load_any(path)
                self.compare_mode = mode or getattr(self, "compare_mode", "time")
                merged = merge_compare(a, sec, self.compare_mode)
            except Exception as exc:
                self.progress_hide()
                self.dlg.showerror("Comparaison impossible", str(exc))
                return
            self.secondary = sec
            self.compare_name = os.path.basename(path)
            self._load_result(self.primary_path, merged)
        finally:
            self.progress_hide()
            self.loading = False

    def set_compare_mode(self, mode):
        """Bascule la comparaison entre « time » (temps) et « gps » (position GPS) sans rouvrir les fichiers."""
        a, sec = getattr(self, "primary", None), getattr(self, "secondary", None)
        if a is None or sec is None or not self.compare_name or mode == getattr(self, "compare_mode", "time"):
            return
        self.compare_mode = mode
        self.loading = True
        try:
            self.progress_show("Recalage des deux sessions…", 5)
            self._load_result(self.primary_path, merge_compare(a, sec, mode))
        finally:
            self.progress_hide()
            self.loading = False

    def end_compare(self):
        a = getattr(self, "primary", None)
        if a is not None and self.compare_name:
            self.compare_name = None
            self.secondary = None
            self.loading = True
            try:
                self._load_result(self.primary_path, a)
            finally:
                self.progress_hide()
                self.loading = False

    def _load_result(self, path, res):
        frames = res.frames
        self.pause()
        self.frames = frames
        self.frame_times = [f[0] for f in frames]
        self.idx = 0
        self.full_t = {}
        self.full_v = {}
        self.full_src = {}
        self.track_full, self.track_full_t = [], []
        self.dyn = dict(res.dyn)
        self.span_ms = 30000.0  # fenêtre par défaut : 30 s, à partir de 0
        self.yr_cache = {}
        self.clear_data()
        self.track_b = []
        name = os.path.basename(path)
        self.file_name.set(f"{name}  ·  {res.label}")
        if not frames:
            self.set_state("0 trame · fichier vide", RED)
            self.dlg.showwarning("Fichier vide", f"Format reconnu ({res.label}) mais aucune donnée exploitable n'a été trouvée.")
        else:
            info = f" · {res.info}" if res.info else ""
            self.set_state(f"{res.label} · {len(frames):,} trames{info}".replace(",", " "), SUB)
            self.view_end = None
            self.prebuild(own=False)
            self.build_track_b(res)
            self.progress_show("Choix des courbes…", 97)
            self.choose_curves()
            self.fit_all()  # le fichier entier, curseur à zéro
            self.progress_show("Terminé", 100)
            if res.dyn:
                self.show_page("graph")

    def build_track_b(self, res):
        """Tracé GPS de la 2e session (comparaison) : [(ms, lat, lon)], reconstruit depuis ses voies cachées."""
        self.track_b, self.track_b_t = [], []
        pid = res.extra.get("b_pos")
        if not pid:
            return
        ts = self.full_t.get((pid, "~lat B"))
        la, lo = self.full_v.get((pid, "~lat B")), self.full_v.get((pid, "~lon B"))
        if not ts or not la or not lo:
            return
        b0, b1 = res.extra["b_base"]
        self.track_b = [(t, a + b0, o + b1) for t, a, o in zip(ts, la, lo) if a == a and o == o]
        self.track_b_t = [p[0] for p in self.track_b]

    # ---------- tours ----------
    def lap_key(self, suffix=""):
        for cid, ents in self.dyn.items():
            for ent in ents:
                if ent and ent[0] == "Tour" + suffix:
                    return (cid, ent[0])
        return None

    def lap_table(self, suffix=""):
        """([débuts de tour en ms], [numéros], nombre de tours) ou None."""
        if self.lap_at(0.0, suffix) is None:
            return None
        _ts, starts, nums, top = self._lap_cache[self.lap_key(suffix)]
        return starts, nums, top

    def lap_at(self, ms, suffix=""):
        """(numéro de tour, début du tour en ms, nombre de tours) à l'instant ms, ou None sans voie « Tour »."""
        key = self.lap_key(suffix)
        ts, vs = self.full_t.get(key), self.full_v.get(key)
        if not ts or not vs:
            return None
        cache = getattr(self, "_lap_cache", {})
        hit = cache.get(key)
        if hit is None or hit[0] is not ts:
            starts, nums = [], []
            prev = None
            for t, v in zip(ts, vs):
                if v == v and v != prev:
                    starts.append(t)
                    nums.append(int(round(v)))
                    prev = v
            hit = cache[key] = (ts, starts, nums, max(nums) if nums else 0)
            self._lap_cache = cache
        _ts, starts, nums, top = hit
        i = bisect.bisect_right(starts, ms) - 1
        if i < 0:
            return (0, 0.0, top)
        return (nums[i], starts[i], top)

    # mots qui désignent en général une grandeur intéressante à regarder en premier
    KEY_WORDS = ("vitesse", "speed", "rpm", "régime", "regime", "gaz", "throttle", "tps", "inclin", "lean", "roll",
                 "acc", "g force", "gforce", "frein", "brake", "pression", "press", "suspension", "débattement",
                 "rapport", "gear", "temp", "lat", "volt")
    PRIME_WORDS = ("rpm", "speed", "vitesse", "hand_throttle", "gaz", "throttle", "gear", "temp", "brake",
                   "frein", "lean", "inclin", "tps", "press", "lat_acc", "lon_acc", "gforce", "suspension", "débattement")
    NOISE_WORDS = ("status", "statut", "stat", "sts", "count", "cnt", "lap", "satellit", "fix", "qualité", "elapsed",
                   "time", "temps", "record", "index", "numéro", "number", "checksum", "latitude", "longitude",
                   "source", "src", "enabled", "level")

    def scan_signals(self):
        """Parcourt rapidement les données chargées et note chaque signal : un signal qui varie beaucoup et souvent est
        « significatif » ; un signal constant, binaire figé ou de service ne l'est pas. Renvoie [(note, clé)] décroissantes."""
        scored = []
        for key, vals in self.full_v.items():
            n = len(vals)
            if n < 8:
                continue
            step = max(1, n // 4000)  # échantillonnage : l'analyse reste instantanée sur un gros fichier
            v = [x for x in vals[::step] if x == x]
            if len(v) < 8:
                continue
            lo, hi = min(v), max(v)
            rng = hi - lo
            if rng <= 0:
                continue
            mean = sum(v) / len(v)
            std = (sum((x - mean) ** 2 for x in v) / len(v)) ** 0.5
            changes = sum(1 for i in range(1, len(v)) if v[i] != v[i - 1]) / (len(v) - 1)
            distinct = len(set(round(x, 3) for x in v[:2000]))
            if distinct < 3 or changes < 0.002:
                continue  # figé, ou simple interrupteur qui ne bouge presque jamais
            score = (std / rng) * 0.5 + min(1.0, changes * 3) * 0.5
            steps = sum(abs(v[i] - v[i - 1]) for i in range(1, len(v))) / (len(v) - 1)
            if steps / rng > 0.25:
                score *= 0.3  # saute sans cesse d'un extrême à l'autre : bruit ou décodage douteux, pas une grandeur lisible
            low = key[1].lower()
            if any(w in low for w in self.NOISE_WORDS):
                score *= 0.25
            if any(w in low for w in self.PRIME_WORDS):
                score *= 2.5
            elif any(w in low for w in self.KEY_WORDS):
                score *= 1.4
            if key[0] in (2032,) or key[1] in ("GPS Latitude", "GPS Longitude"):
                score = 0  # position : sert à la carte, pas à une courbe
            if score > 0:
                scored.append((score, key))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return scored

    def default_signals(self):
        """Fichier GPS : vitesse, G longitudinal, G latéral et angle (ceux du fichier, sinon les valeurs recalculées)."""
        have = [k for k in self.full_t if not k[1].endswith(B_SUFFIX)]

        def pick(*names):
            for n in names:
                k = next((q for q in have if q[1] == n), None)
                if k:
                    return k
            return None

        out = [pick("GPS Vitesse"), pick("G longitudinal", "G longitudinal (calculé)"),
               pick("G latéral", "G latéral (calculé)"), pick("Angle", "Angle (calculé)")]
        out = [k for k in out if k]
        return out if len(out) >= 3 and out[0][1] == "GPS Vitesse" else []

    def choose_curves(self, limit=8):
        """À l'ouverture d'un fichier : active automatiquement les signaux qui semblent significatifs
        (au plus `limit`, en variant les types pour ne pas avoir que du GPS ou que du CAN)."""
        keep = self.default_signals()
        if keep:
            self.sel = set(keep)
            self.color_map = {}
            for k in keep:
                self.assign_color(k)
            for k in list(keep):  # comparaison : la même grandeur de la 2e session, de la même couleur
                kb = next((q for q in self.full_t if q[1] == k[1] + B_SUFFIX), None)
                if kb:
                    self.sel.add(kb)
                    self.color_map[kb] = self.color_map[k]
            self.band_h = {}
            self.ref_key = None
            self.signal_list.set_groups(self.signal_groups(), self.sel)
            return keep
        scored = self.scan_signals()
        keep, per_type = [], {}
        cap = limit if len({self.signal_type(k) for _s, k in scored}) < 2 else 5  # un seul type présent : pas de plafond par type
        for score, key in scored:
            t = self.signal_type(key)
            if per_type.get(t, 0) >= cap or score < 0.12:
                continue
            keep.append(key)
            per_type[t] = per_type.get(t, 0) + 1
            if len(keep) >= limit:
                break
        if not keep:  # rien de net : on garde la sélection existante si elle a des données, sinon quelques voies au hasard
            keep = [k for k in sorted(self.sel) if k in self.full_t] or [k for _s, k in scored[:5]]
        self.sel = set(keep)
        self.color_map = {}
        for k in keep:
            self.assign_color(k)
        self.band_h = {}
        self.ref_key = None
        self.signal_list.set_groups(self.signal_groups(), self.sel)
        return keep

    def play(self):
        if not self.frames:
            self.dlg.showinfo("Capture", "Importez d'abord une capture TXT.")
            return
        self.playing = True
        self.start_wall = time.monotonic()
        self.start_frame = self.frames[self.idx][0] if self.idx < len(self.frames) else 0
        self.set_state("Lecture en cours", GREEN)

    def resync(self):
        """Remet valeurs et tracé à l'instant de lecture (après une lecture sur les courbes qui n'a rien rejoué)."""
        self._skipped = False
        if self.frames and self.full_t:
            total = self.frames[-1][0]
            self.seek(min(1.0, max(0.0, self.cursor_ms() / total)) if total else 0.0)

    def pause(self):
        if getattr(self, "_skipped", False) and self.playing:
            self.resync()
            self.playing = False
            return
        was = self.playing
        self.playing = False
        if was and self.frames and (self.idx < len(self.frames)):
            self.set_state("En pause", YELLOW)

    def prebuild(self, keep=0, own=True):
        """Décode toute la capture une fois pour toutes : les courbes montrent alors la fenêtre entière autour de l'instant courant."""
        self.full_t = {}
        self.full_v = {}
        self.yr_cache = {}
        if not self.frames:
            return
        keep = keep or self.idx
        self.playing = False
        self.set_state("Analyse de la capture…", YELLOW)
        if own:
            self.loading = True
        self.clear_data()
        self.hist_max = None
        self.bulk = True
        frames = self.frames[:1500000]
        n = max(1, len(frames))
        try:
            for i in range(0, len(frames), 6000):
                for fr in frames[i:i + 6000]:
                    self.ingest(*fr)
                self.progress_show("Analyse des trames…", 5 + 85 * min(1.0, (i + 6000) / n))
        finally:
            self.bulk = False
            self.hist_max = 20000
        self.progress_show("Préparation des courbes…", 92)
        for k, d in self.hist.items():
            self.full_t[k] = [p[0] for p in d]
            self.full_v[k] = [p[1] for p in d]
        self.full_src = {k: v[1] for k, v in self.vals.items()}
        # tracé GPS complet (avec les instants) : un saut dans le fichier le retrouve sans rejouer les trames
        self.track_full = []
        for fr in self.frames:
            if fr[1] == 2032 and len(fr[2]) >= 8:
                la = int.from_bytes(fr[2][0:4], "little", signed=True) / 10000000.0
                lo = int.from_bytes(fr[2][4:8], "little", signed=True) / 10000000.0
                if la or lo:
                    self.track_full.append((fr[0], la, lo))
        self.track_full_t = [p[0] for p in self.track_full]
        self.clear_data()
        self.idx = 0
        if keep:
            self.seek(self.frames[keep - 1][0] / max(1, self.frames[-1][0]))
        else:
            self.set_state(f"{len(self.frames):,} trames chargées".replace(",", " "), SUB)
        if own:
            self.progress_hide()
            self.loading = False

    SEEK_REPLAY = 2500  # trames rejouées juste avant l'instant visé (remplit tableau et jauges) ; le reste vient des tableaux complets

    def seek(self, frac):
        """Saute à un instant de la capture. Les valeurs de tous les signaux et le tracé GPS viennent des tableaux
        pré-calculés (instantané, même sur un très gros fichier) ; on ne rejoue que les dernières trames."""
        if not self.frames:
            return
        was = self.playing
        self.playing = False
        total = self.frames[-1][0]
        target = bisect.bisect_right(self.frame_times, frac * total)
        target = max(0, min(len(self.frames), target))
        fast = bool(self.full_t)
        replay = 300 if self.current_page == "graph" else self.SEEK_REPLAY  # sur les courbes : seulement de quoi remplir les jauges
        begin = max(0, target - (replay if fast else SEEK_BACK))
        tt = self.frames[target - 1][0] if target > 0 else 0
        self.clear_data()
        if fast:
            for key, ts in self.full_t.items():  # dernière valeur connue de chaque signal à cet instant
                i = bisect.bisect_right(ts, tt) - 1
                if i >= 0:
                    self.vals[key] = (self.full_v[key][i], self.full_src.get(key, "def"))
                    self.dirty.add(key)
            n = bisect.bisect_right(self.track_full_t, self.frames[begin][0] if begin < len(self.frames) else tt)
            self.track.extend((p[1], p[2]) for p in self.track_full[:n])
        else:
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
        if self.current_page == "frames":
            self.rebuild_table()
        else:
            self._table_stale = True  # reconstruit à l'ouverture de la page (inutile de remplir un tableau caché)
        if target > 0:
            self.t_now = self.frames[target - 1][0]
        if was and target < len(self.frames):
            self.start_wall = time.monotonic()
            self.start_frame = self.frames[target][0]
            self.playing = True
            self.set_state("Lecture en cours", GREEN)
        else:
            self.set_state(f"En pause · {fmt_time(self.t_now)}", YELLOW)

    def step_frames(self, n):
        """Avance (n > 0) ou recule (n < 0) de n instants distincts du fichier, comme un pas à pas : flèches du clavier."""
        if not self.frames or self.live:
            return
        if self.playing:
            self.pause()
        times = self.frame_times
        cache = getattr(self, "_uniq", None)
        if cache is None or cache[0] is not times:
            cache = self._uniq = (times, sorted(set(times)))
        uniq = cache[1]
        i = max(0, bisect.bisect_right(uniq, self.cursor_ms() + 0.001) - 1)
        j = max(0, min(len(uniq) - 1, i + n))
        total = self.frames[-1][0]
        self.seek((uniq[j] + 0.5) / total if total else 0.0)
        hook = getattr(self.ui, "graph_ensure_cursor", None)
        if hook:
            hook()

    def reset(self):
        self.pause()
        self.idx = 0
        self.clear_data()
        if self.frames:
            self.set_state("Début de capture", SUB)
