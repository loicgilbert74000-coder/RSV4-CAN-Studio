"""Page Courbes : circuit, sélection des signaux et graphique."""

import bisect
import math
import time
import tkinter as tk
from tkinter import ttk

from .config import BAND_MAX, BAND_MIN, CURVE_INDEX, CURVE_KEYS, UNIT_OF, WINDOWS
from .formats import TYPE_CAN, TYPE_GPS, TYPE_IMU, TYPE_OTHER, TYPE_SENS
from .names import fr
from .theme import BG, BORDER, CARD, CARD2, CYAN, FONT, GREEN, MUTED, PALETTE, SUB, TEXT, YELLOW
from .util import disp_unit, fmt_val, nice_ticks
from .widgets import GroupedSignalList

TYPE_ORDER = (TYPE_GPS, TYPE_CAN, TYPE_SENS, TYPE_IMU, TYPE_OTHER)
MIN_SPAN = 20.0  # fenêtre de temps la plus petite (ms)
MAX_SPAN = 6 * 3600 * 1000.0  # la plus grande (ms)
TIME_STEPS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)


def time_ticks(lo, hi, n):
    """Graduations de temps (secondes) tombant sur des valeurs « rondes » : 0,05 s … 1 s … 1 min."""
    span = max(hi - lo, 1e-9)
    step = next((st for st in TIME_STEPS if span / st <= max(n, 2)), TIME_STEPS[-1])
    first = math.ceil(lo / step - 1e-9)
    out, i = [], 0
    while True:
        v = (first + i) * step
        if v > hi + 1e-9:
            break
        out.append(round(v, 6))
        i += 1
    return out


class GraphMixin:
    """Page Courbes : circuit, sélection des signaux et graphique."""

    # ---------- page Courbes ----------
    def build_graph(self, parent):
        left = tk.Frame(parent, bg=BG, width=260)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)
        mapc = self.card(left)
        mapc.pack(fill="x", pady=(0, 6))
        self.map = tk.Canvas(mapc, bg=CARD, height=210, highlightthickness=0)
        self.map.pack(fill="x", padx=6, pady=6)
        selc = self.card(left)
        selc.pack(fill="both", expand=True)
        tk.Label(
            selc, text="Signaux · cliquer pour tracer ou retirer", fg=SUB, bg=CARD, font=(FONT, 9, "bold")
        ).pack(anchor="w", padx=10, pady=(8, 4))
        self.signal_list = GroupedSignalList(selc, self.toggle_curve, self.color_of)
        self.signal_list.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.signal_list.set_groups(self.signal_groups(), self.sel)

        right = self.card(parent)
        right.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(right, bg=CARD)
        bar.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(
            bar, text="Courbes", fg=TEXT, bg=CARD, font=(FONT, 12, "bold")
        ).pack(side="left", padx=(0, 14))
        self.btn_ov = self.button(bar, "Superposées", lambda: self.set_stack(False), SUB, CARD2, font=9)
        self.btn_ov.pack(side="left", padx=2)
        self.btn_st = self.button(bar, "Empilées", lambda: self.set_stack(True), SUB, CARD2, font=9)
        self.btn_st.pack(side="left", padx=2)
        self.hint = tk.Label(bar, text="", fg=MUTED, bg=CARD, font=(FONT, 8))
        self.hint.pack(side="left", padx=12)
        self.span_cb = ttk.Combobox(bar, values=[f"{w} s" for w in WINDOWS], state="readonly", width=9)
        self.span_cb.pack(side="right")
        self.span_cb.bind("<<ComboboxSelected>>", self.on_span_choice)
        self._span_shown = None
        tk.Label(bar, text="Fenêtre", fg=SUB, bg=CARD, font=(FONT, 9)).pack(side="right", padx=(10, 6))
        self.button(bar, "Suivre ▸▸", self.follow, GREEN, CARD2, font=9).pack(side="right", padx=6)
        self.button(bar, "Tout voir", self.fit_all, CYAN, CARD2, font=9).pack(side="right", padx=2)
        cw = tk.Frame(right, bg=CARD)
        cw.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        cw.rowconfigure(0, weight=1)
        cw.columnconfigure(0, weight=1)
        self.chart = tk.Canvas(cw, bg=CARD, highlightthickness=0)
        self.chart_sb = ttk.Scrollbar(cw, orient="vertical", command=self.chart.yview)
        self.chart.configure(yscrollcommand=self.chart_sb.set)
        self.chart.grid(row=0, column=0, sticky="nsew")
        self.chart_sb.grid(row=0, column=1, sticky="ns")
        self.taxis = tk.Canvas(cw, bg=CARD, height=26, highlightthickness=0)
        self.taxis.grid(row=1, column=0, sticky="ew")
        self.chart_hsb = ttk.Scrollbar(cw, orient="horizontal", command=self.on_hscroll)
        self.chart_hsb.grid(row=2, column=0, sticky="ew")
        def zoom_wheel(e):
            # molette vers le haut : zoom avant ; vers le bas : zoom arrière (centré sur le curseur)
            up = e.delta > 0 if getattr(e, "num", None) not in (4, 5) else e.num == 4
            self.zoom_at(e.x, 0.8 if up else 1.25)
        def vwheel(e):
            self.chart.yview_scroll(int(-e.delta / 120), "units")
        def hwheel(e):
            self.pan_by(-self.span_ms * 0.1 if e.delta > 0 else self.span_ms * 0.1)
        def enter(e):
            self.chart.bind_all("<MouseWheel>", zoom_wheel)
            self.chart.bind_all("<Control-MouseWheel>", vwheel)
            self.chart.bind_all("<Shift-MouseWheel>", hwheel)
        def leave(e):
            self.chart.unbind_all("<MouseWheel>")
            self.chart.unbind_all("<Control-MouseWheel>")
            self.chart.unbind_all("<Shift-MouseWheel>")
        self.chart.bind("<Enter>", enter)
        self.chart.bind("<Leave>", leave)
        self.chart.bind("<Button-4>", zoom_wheel)  # Linux
        self.chart.bind("<Button-5>", zoom_wheel)
        self.chart.bind("<ButtonPress-1>", self.chart_press)
        self.chart.bind("<B1-Motion>", self.chart_drag)
        self.chart.bind("<ButtonRelease-1>", self.chart_release)
        self.chart.bind("<Double-Button-1>", lambda e: self.fit_all() if self.in_plot(e.x) else None)
        self.chart.bind("<ButtonPress-2>", self.pan_press)
        self.chart.bind("<B2-Motion>", self.pan_drag)
        self.chart.bind("<ButtonRelease-2>", self.pan_release)
        self.chart.bind("<Motion>", self.chart_motion)
        self.chart.bind("<Configure>", lambda e: self.draw_chart())
        self.refresh_mode_buttons()

    # ---------- signaux : types, noms, couleurs ----------
    def dyn_keys(self):
        """Voies issues d'un fichier RaceBox / RaceChrono… : [(identifiant, nom)]."""
        return [(cid, ent[0]) for cid, ents in self.dyn.items() for ent in ents if ent]

    def curve_keys(self):
        return CURVE_KEYS + self.dyn_keys()

    def dyn_entry(self, key):
        for ent in self.dyn.get(key[0], ()):
            if ent and ent[0] == key[1]:
                return ent
        return None

    def signal_type(self, key):
        """Type d'un signal : GPS, CAN moto, Capteurs (ESP32), Inertiel ou Autres."""
        cid = key[0]
        if cid in (2032, 2040):
            return TYPE_GPS
        if cid in (2041, 2042):
            return TYPE_SENS
        ent = self.dyn_entry(key)
        if ent:
            return ent[2]
        return TYPE_CAN

    def unit_of(self, key):
        ent = self.dyn_entry(key)
        return disp_unit(ent[1]) if ent else disp_unit(UNIT_OF.get(key, ""))

    def legend_label(self, key):
        """Nom court pour la légende de droite (sans l'identifiant CAN, qui reste dans la liste de gauche)."""
        return fr(key[1])

    def label_of(self, key):
        cid, name = key
        if self.dyn_entry(key) or cid in (2032, 2040, 2041, 2042):
            return fr(name)
        return f"{fr(name)}  ·  0x{cid:03X}"

    def color_of(self, key):
        return self.color_map.get(key) or PALETTE[CURVE_INDEX.get(key, 0) % len(PALETTE)]

    def assign_color(self, key):
        used = {self.color_map[k] for k in self.sel if k in self.color_map}
        free = [c for c in PALETTE if c not in used]
        self.color_map[key] = free[0] if free else PALETTE[len(self.color_map) % len(PALETTE)]

    def signal_groups(self):
        """Tous les signaux connus, classés par type ; ceux sans donnée dans la source courante sont grisés (jamais masqués)."""
        have = set(self.full_t) | set(self.hist)
        groups = {t: [] for t in TYPE_ORDER}
        for k in self.curve_keys():
            groups[self.signal_type(k)].append((k, self.label_of(k), (k in have) or not have or k in self.sel))
        return [(t, groups[t]) for t in TYPE_ORDER if groups[t]]

    def toggle_curve(self, key):
        if key in self.sel:
            self.remove_curve(key)
            return
        self.assign_color(key)
        self.sel.add(key)
        self.signal_list.refresh(self.sel)
        self.draw_chart()

    def remove_curve(self, key):
        """Retire une courbe du graphique (petite croix de la légende ou clic dans la liste)."""
        self.sel.discard(key)
        self.color_map.pop(key, None)
        self.band_h.pop(key, None)
        if self.ref_key == key:
            self.ref_key = None
        self.signal_list.refresh(self.sel)
        self.draw_chart()

    def set_stack(self, stacked):
        self.stack.set(stacked)
        self.refresh_mode_buttons()
        self.chart.yview_moveto(0)
        self.draw_chart()

    def follow(self):
        self.view_end = None
        self.draw_chart()

    # ---------- fenêtre de temps : zoom, déplacement, sélection ----------
    def data_bounds(self):
        """(début, fin) en ms des données disponibles."""
        if self.full_t and self.frames:
            return (0, self.frames[-1][0])
        ts = [self.hist[k][0][0] for k in self.sel if k in self.hist and self.hist[k]]
        return (min(ts) if ts else 0, max(self.t_now, 1))

    def max_span(self):
        lo, hi = self.data_bounds()
        return max(WINDOWS[-1] * 1000.0, (hi - lo) * 1.2) if hi > lo else WINDOWS[-1] * 1000.0

    def set_view(self, start, span):
        """Fixe la fenêtre affichée (début et durée en ms) : la vue ne suit plus la lecture."""
        span = max(MIN_SPAN, min(min(MAX_SPAN, self.max_span()), span))
        lo, hi = self.data_bounds()
        start = max(lo - span * 0.25, min(hi + span * 0.25 - span, start)) if hi + span * 0.5 > lo else start
        self.span_ms = span
        self.view_end = start + span
        self.draw_chart()

    def in_plot(self, x):
        g = self.geom
        return bool(g) and g["L"] <= x <= g["L"] + g["pw"]

    def time_at(self, x):
        g = self.geom
        return g["start"] + (x - g["L"]) / g["pw"] * g["span"]

    def zoom_at(self, x, factor):
        """Zoom centré sur la position x du curseur : le point sous le curseur ne bouge pas."""
        g = self.geom
        if not g:
            return
        frac = min(1.0, max(0.0, (x - g["L"]) / g["pw"]))
        centre = g["start"] + frac * g["span"]
        new = max(MIN_SPAN, min(min(MAX_SPAN, self.max_span()), g["span"] * factor))
        self.set_view(centre - frac * new, new)

    def pan_by(self, dt):
        g = self.geom
        if g:
            self.set_view(g["start"] + dt, g["span"])

    def pan_press(self, e):
        g = self.geom
        if g and self.in_plot(e.x):
            self.pan = (e.x, g["start"], g["span"])
            self.chart.config(cursor="fleur")

    def pan_drag(self, e):
        if self.pan and self.geom:
            x0, start0, span0 = self.pan
            self.set_view(start0 - (e.x - x0) / self.geom["pw"] * span0, span0)

    def pan_release(self, e):
        self.pan = None
        self.chart.config(cursor="")

    def fit_all(self):
        lo, hi = self.data_bounds()
        span = max(MIN_SPAN * 5, (hi - lo) * 1.04)
        self.set_view(lo - (span - (hi - lo)) / 2, span)

    def on_span_choice(self, e=None):
        sec = float(self.span_cb.get().split()[0].replace(",", "."))
        g = self.geom
        centre = g["start"] + g["span"] / 2 if g else self.t_now
        self.set_view(centre - sec * 500, sec * 1000.0)

    def refresh_mode_buttons(self):
        for b, on in ((self.btn_ov, not self.stack.get()), (self.btn_st, self.stack.get())):
            b.config(bg=CYAN if on else CARD2, fg=BG if on else SUB)
        self.hint.config(
            text="Glisser les séparateurs entre fenêtres pour régler leur hauteur" if self.stack.get() else "Cliquer un signal de la légende pour en faire l'axe de gauche"
        )

    def paint_map(self):
        """Redessine le circuit seulement quand la page est visible et que le tracé ou la taille a changé."""
        if self.current_page == "graph":
            c = self.map
            state = (
                len(self.track), self.track[-1] if self.track else None, c.winfo_width(), c.winfo_height()
            )
            if state != self._map_state:
                self._map_state = state
                self.draw_map()
        self.root.after(400, self.paint_map)

    def draw_map(self):
        c = self.map
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 60 or h <= 60:
            return
        c.create_text(10, 8, text="Circuit", anchor="nw", fill=SUB, font=(FONT, 9, "bold"))
        pts = list(self.track)
        if len(pts) < 2:
            c.create_text(
                w / 2, h / 2, text="Pas de données GPS dans cette source", fill=MUTED, font=(FONT, 9)
            )
            return
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        mnla, mxla, mnlo, mxlo = (min(lats), max(lats), min(lons), max(lons))
        kx = math.cos(math.radians((mnla + mxla) / 2))
        dx = max((mxlo - mnlo) * kx, 1e-07)
        dy = max(mxla - mnla, 1e-07)
        scale = min((w - 30) / dx, (h - 40) / dy)
        ox = (w - dx * scale) / 2
        oy = 20 + (h - 40 - dy * scale) / 2

        def xy(la, lo):
            return (ox + (lo - mnlo) * kx * scale, oy + (mxla - la) * scale)

        step = max(1, len(pts) // 1500)
        sample = pts[::step]
        if sample[-1] != pts[-1]:
            sample.append(pts[-1])
        coords = []
        for la, lo in sample:
            coords.extend(xy(la, lo))
        c.create_line(*coords, fill=CYAN, width=2)
        x, y = xy(*pts[-1])
        c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=GREEN, outline="")

    # ---- gestion de la fenêtre temporelle (ascenseur horizontal)
    def scroll_range(self):
        """Bornes (début, fin) de ce que l'ascenseur horizontal peut atteindre."""
        lo, hi = self.data_bounds()
        half = self.span_ms / 2
        return (lo - half, hi + half)

    def on_hscroll(self, *a):
        span = self.span_ms
        t0, tmax = self.scroll_range()
        if tmax - t0 <= span:
            return
        cur = self.view_start() + span
        if a[0] == "moveto":
            end = t0 + float(a[1]) * (tmax - t0) + span
        else:
            step = span * (0.9 if a[2] == "pages" else 0.1)
            end = cur + int(a[1]) * step
        end = min(tmax, max(t0 + span, end))
        self.view_end = None if end >= tmax - 1 and not self.full_t else end
        self.draw_chart()

    def axis_for(self, mn, mx):
        """Bornes « rondes » et graduations pour un signal."""
        if mx - mn < 1e-09:
            mn -= 1
            mx += 1
        tks = nice_ticks(mn, mx, 4)
        step = tks[1] - tks[0] if len(tks) > 1 else mx - mn
        lo = math.floor(mn / step + 1e-09) * step
        hi = math.ceil(mx / step - 1e-09) * step
        if hi <= lo:
            hi = lo + step
        n = int(round((hi - lo) / step))
        return (lo, hi, [round(lo + i * step, 10) for i in range(n + 1)])

    @staticmethod
    def smooth_curve(pts, pw):
        """Léger lissage d'une courbe continue (moyenne pondérée sur 5 points, puis tracé arrondi) pour supprimer les
        à-coups ; les signaux « en marches » (rapport, interrupteurs…) restent tels quels. Renvoie (points, arrondi)."""
        n = len(pts)
        if n < 6:
            return pts, False
        stride = max(1, n // max(60, int(pw * 0.8)))
        if stride > 1:
            pts = pts[::stride]
            n = len(pts)
        sample = pts[:: max(1, n // 200)]
        if len({round(v, 6) for _t, v in sample}) <= 12:
            return pts, False
        vals = [v for _t, v in pts]
        w = (1, 2, 3, 2, 1)
        out = []
        for i in range(n):
            tot = acc = 0.0
            for j, wj in enumerate(w):
                k = i + j - 2
                if 0 <= k < n:
                    acc += wj * vals[k]
                    tot += wj
            out.append((pts[i][0], acc / tot))
        return out, n <= 700

    def axis_key(self, key, mn, mx):
        """Échelle d'un signal, stable : d'après l'étendue de tout le fichier ; en direct, d'après le maximum déjà vu
        (elle ne peut que s'élargir, par paliers « ronds »), donc elle ne bouge pas à chaque image."""
        if self.full_v and key in self.full_v and self.full_v[key]:
            r = self.yr_cache.get(key)
            if r is None:
                v = self.full_v[key]
                r = self.yr_cache[key] = (min(v), max(v))
            mn, mx = r
        else:
            r = self.yr_live.get(key)
            if r:
                mn, mx = min(mn, r[0]), max(mx, r[1])
            self.yr_live[key] = (mn, mx)
        return self.axis_for(mn, mx)

    def tlabel(self, sec, step):
        """Temps au format mm:ss:ms (minutes, secondes, millisecondes)."""
        sg = "-" if sec < -1e-9 else ""
        total = int(round(abs(sec) * 1000))
        return f"{sg}{total // 60000:02d}:{total // 1000 % 60:02d}:{total % 1000:03d}"

    def cursor_ms(self):
        """Instant du curseur, continu : horloge de lecture (fichier) ou horloge réelle (direct), pas la date de la dernière trame
        traitée, qui avance par à-coups."""
        if self.playing and self.frames:
            t = self.start_frame + (time.monotonic() - self.start_wall) * 1000 * self.speed.get()
            return min(t, float(self.frames[-1][0]))
        if self.live and self.link_t is not None:
            return float(int(time.monotonic() * 1000))
        return float(self.t_now)

    def view_start(self):
        """Début de la fenêtre affichée : vue libre, ou page de `span` ms qui contient le curseur (la 1re page commence à 0)."""
        if self.view_end is not None:
            return self.view_end - self.span_ms
        return math.floor(max(0.0, self.cursor_ms()) / self.span_ms) * self.span_ms

    def chart_sig(self):
        c = self.chart
        tick = 0
        if self.live:
            tick = int(time.monotonic() * 6)  # en direct : les courbes grandissent, redessin ~6 fois par seconde
        elif self.playing:
            tick = int(time.monotonic() * 4)  # en lecture : seules les valeurs « actuel » changent
        return (
            round(self.view_start(), 3), round(self.span_ms, 3), c.winfo_width(), c.winfo_height(),
            tuple(sorted(self.sel)), self.stack.get(), tuple(sorted(self.band_h.items())), self.ref_key,
            id(self.full_t), len(self.dyn), tick,
        )

    def draw_chart(self):
        """Redessine les courbes puis replace le curseur."""
        self._draw_chart_body()
        self._chart_sig = self.chart_sig()
        self.move_cursor()

    def move_cursor(self):
        """Curseur de lecture : seul élément qui bouge pendant la lecture (déplacé sans tout redessiner)."""
        g = self.geom
        if not g:
            return
        c, ta = self.chart, self.taxis
        c.delete("cur")
        ta.delete("cur")
        t = self.cursor_ms()
        self._cur_shown = t
        if g["start"] <= t <= g["start"] + g["span"]:
            x = g["L"] + g["pw"] * (t - g["start"]) / g["span"]
            for y0, y1 in self.cur_spans:
                c.create_line(x, y0, x, y1, fill=YELLOW, width=2, tags="cur")
            ta.create_line(x, 0, x, 8, fill=YELLOW, width=3, tags="cur")

    def _draw_chart_body(self):
        c = self.chart
        ta = self.taxis
        c.delete("all")
        ta.delete("all")
        self.grips = []
        self.legend_hits = []
        self.close_hits = []
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 300 or h <= 100:
            return
        span = self.span_ms
        tmax = self.cursor_ms()
        start = self.view_start()
        end = start + span
        self.cur_spans = []
        sel = [k for k in self.curve_keys() if k in self.sel]
        L, R, T = (70, 212, 22)
        pw = w - L - R
        self.geom = {"L": L, "pw": pw, "start": start, "span": span}
        shown = f"{round(span / 1000, 2):g} s"
        if shown != self._span_shown:  # la liste « Fenêtre » reflète la fenêtre réelle, même après un zoom à la souris
            self._span_shown = shown
            self.span_cb.set(shown)
        # ascenseur horizontal
        t0, tmx = self.scroll_range()
        tot = tmx - t0
        if tot > span:
            self.chart_hsb.set(max(0, min(1, (start - t0) / tot)), max(0, min(1, (end - t0) / tot)))
        else:
            self.chart_hsb.set(0, 1)
        # axe du temps (fixe, sous la zone de courbes)
        ticks = time_ticks(start / 1000, end / 1000, max(2, pw // 115))
        tstep = ticks[1] - ticks[0] if len(ticks) > 1 else 1
        xs = []
        ta.create_line(L, 0, L + pw, 0, fill=BORDER)
        for sec in ticks:
            x = L + pw * (sec * 1000 - start) / span
            xs.append(x)
            ta.create_line(x, 0, x, 5, fill=SUB)
            ta.create_text(x, 7, text=self.tlabel(sec, tstep), fill=SUB, font=(FONT, 8), anchor="n")
        ta.create_text(
            L + pw + 48,
            7,
            text="◂ vue libre" if self.view_end is not None else ("en direct" if self.live else "suivi"),
            fill=YELLOW if self.view_end is not None else GREEN,
            font=(FONT, 8, "bold"),
            anchor="nw",
        )

        def clip(pts):
            """Prolonge la courbe jusqu'aux bords de la fenêtre (interpolation), pour que l'échelle existe même sans point dedans."""
            if len(pts) < 2:
                return pts
            out = list(pts)
            if out[0][0] < start < out[1][0]:
                (t0_, v0), (t1_, v1) = out[0], out[1]
                out[0] = (start, v0 + (v1 - v0) * (start - t0_) / (t1_ - t0_))
            if out[-2][0] < end < out[-1][0]:
                (t0_, v0), (t1_, v1) = out[-2], out[-1]
                out[-1] = (end, v0 + (v1 - v0) * (end - t0_) / (t1_ - t0_))
            return [p for p in out if start <= p[0] <= end]

        def window_pts(key):
            if self.full_t:
                ts = self.full_t.get(key)
                if not ts:
                    return []
                i = max(0, bisect.bisect_left(ts, start) - 1)
                j = min(len(ts), bisect.bisect_right(ts, end) + 1)
                pts = clip(list(zip(ts[i:j], self.full_v[key][i:j])))
                st = len(pts) // (2 * max(pw, 1)) + 1
                return pts[::st] if st > 1 else pts
            pts = []
            hist = self.hist.get(key, ())
            for tt, v in reversed(hist):
                if tt > end:
                    continue
                pts.append((tt, v))
                if tt < start:
                    break
            pts.reverse()
            pts = clip(pts)
            st = len(pts) // (2 * max(pw, 1)) + 1
            return pts[::st] if st > 1 else pts
        def poly(pts, ymap, color):
            pts, soft = self.smooth_curve(pts, pw)
            co = []
            for tt, v in pts:
                co.extend((L + pw * (tt - start) / span, ymap(v)))
            if len(co) >= 4:
                c.create_line(*co, fill=color, width=2, smooth=soft, splinesteps=3)
        unit_of = self.unit_of
        def cur_of(key, pts):
            if self.full_t and self.full_t.get(key):
                i = bisect.bisect_right(self.full_t[key], tmax)
                return self.full_v[key][max(0, i - 1)]
            return pts[-1][1]
        def vgrid(y0, y1):
            for x in xs:
                c.create_line(x, y0, x, y1, fill=BORDER, dash=(2, 5))
            self.cur_spans.append((y0, y1))

        if not sel:
            c.configure(scrollregion=(0, 0, w, h))
            c.create_text(
                L + pw / 2,
                h / 2,
                text="Choisissez des signaux dans la liste de gauche",
                fill=MUTED,
                font=(FONT, 11),
            )
            return

        if not self.stack.get():
            total = max(h, T + 34 + len(sel) * 48 + 10)
            c.configure(scrollregion=(0, 0, w, total))
            ph = max(80, h - T - 10)
            data = {}
            for key in sel:
                pts = window_pts(key)
                if len(pts) >= 2:
                    vals = [v for _, v in pts]
                    data[key] = (pts, min(vals), max(vals), cur_of(key, pts))
            ref = self.ref_key if self.ref_key in sel else next(
                (k for k in sel if k in data and data[k][2] > data[k][1]), sel[0]
            )
            self.ref_key = ref
            rcol = self.color_of(ref)
            c.create_rectangle(L, T, L + pw, T + ph, outline=BORDER)
            if ref in data:
                lo, hi, tks = self.axis_key(ref, data[ref][1], data[ref][2])
                for v in tks:
                    y = T + ph * (1 - (v - lo) / (hi - lo))
                    c.create_line(L, y, L + pw, y, fill=BORDER)
                    c.create_text(L - 8, y, text=fmt_val(v), fill=rcol, font=(FONT, 8), anchor="e")
                u = unit_of(ref)
                if u:
                    c.create_text(L - 8, T - 11, text=u, fill=rcol, font=(FONT, 8, "bold"), anchor="e")
            else:
                for i in range(1, 4):
                    y = T + ph * i / 4
                    c.create_line(L, y, L + pw, y, fill=BORDER)
            vgrid(T, T + ph)
            for key in sel:
                if key not in data:
                    continue
                pts, mn, mx, _ = data[key]
                lo, hi, _t = self.axis_key(key, mn, mx)
                poly(
                    pts,
                    lambda v, lo=lo, hi=hi: T + ph * (1 - (v - lo) / (hi - lo)),
                    self.color_of(key),
                )
            lx = L + pw + 14
            c.create_text(lx, T, text="Signal · min · max · actuel", anchor="nw", fill=SUB, font=(FONT, 8, "bold"))
            wrap = max(60, w - lx - 34)
            y0 = T + 22
            for key in sel:
                color = self.color_of(key)
                c.create_line(lx, y0 + 7, lx + 14, y0 + 7, fill=color, width=3)
                item = c.create_text(
                    lx + 20, y0, text=self.legend_label(key), anchor="nw", fill=TEXT, font=(FONT, 8, "bold"), width=wrap
                )
                ly = c.bbox(item)[3] + 1
                if key in data:
                    _p, mn, mx, cur = data[key]
                    c.create_text(lx + 20, ly, text=f"{fmt_val(mn)} … {fmt_val(mx)} {unit_of(key)}",
                                  anchor="nw", fill=SUB, font=(FONT, 8))
                    c.create_text(lx + 20, ly + 13, text=f"actuel {fmt_val(cur)}" + ("  ◂ axe" if key == ref else ""),
                                  anchor="nw", fill=color if key == ref else TEXT, font=(FONT, 8, "bold"))
                    bottom = ly + 28
                else:
                    c.create_text(lx + 20, ly, text="pas de donnée", anchor="nw", fill=MUTED, font=(FONT, 8))
                    bottom = ly + 15
                if key == ref:
                    c.create_rectangle(lx - 6, y0 - 4, w - 6, bottom + 2, outline=color)
                self.legend_hits.append((lx - 6, y0 - 4, w - 6, bottom + 2, key))
                self.draw_close(w - 18, y0 + 4, key)
                y0 = bottom + 10
            total = max(total, int(y0 + 10))
            c.configure(scrollregion=(0, 0, w, total))
            self.draw_zsel()
            return

        # ---- empilées
        dflt = int(max(90, min(400, (h - T - 8) / len(sel))))
        for key in sel:
            self.band_h.setdefault(key, dflt)
        total = max(h, T + sum((self.band_h[k] for k in sel)) + 8)
        c.configure(scrollregion=(0, 0, w, total))
        y = T
        for i, key in enumerate(sel):
            bh = self.band_h[key]
            y0 = y
            y1 = y + bh - 8
            color = self.color_of(key)
            c.create_rectangle(L, y0, L + pw, y1, outline=BORDER, fill=BG)
            vgrid(y0, y1)
            lx = L + pw + 14
            self.draw_close(w - 18, y0 + 4, key)
            lab = c.create_text(
                lx, y0 + 2, text=self.legend_label(key), anchor="nw", fill=color, font=(FONT, 9, "bold"),
                width=max(60, w - lx - 34),
            )
            ly = c.bbox(lab)[3] + 1
            pts = window_pts(key)
            if len(pts) < 2:
                c.create_text(L + pw / 2, (y0 + y1) / 2, text="pas de donnée", fill=MUTED, font=(FONT, 8))
            else:
                vals = [v for _, v in pts]
                mn = min(vals)
                mx = max(vals)
                lo, hi, tks = self.axis_key(key, mn, mx)
                top = y0 + 6
                bot = y1 - 6
                ym = lambda v, lo=lo, hi=hi, top=top, bot=bot: bot - (bot - top) * (v - lo) / (hi - lo)
                for v in tks:
                    yy = ym(v)
                    c.create_line(L, yy, L + pw, yy, fill=BORDER)
                    c.create_text(L - 8, yy, text=fmt_val(v), fill=SUB, font=(FONT, 8), anchor="e")
                poly(pts, ym, color)
                c.create_text(
                    lx,
                    ly,
                    text=f"{fmt_val(mn)} … {fmt_val(mx)} {unit_of(key)}",
                    anchor="nw",
                    fill=SUB,
                    font=(FONT, 8),
                )
                c.create_text(
                    lx,
                    ly + 13,
                    text=f"actuel {fmt_val(cur_of(key, pts))}",
                    anchor="nw",
                    fill=TEXT,
                    font=(FONT, 8, "bold"),
                )
            gy = y1 + 4
            self.grips.append((i, gy))
            active = self.drag is not None and self.drag[0] == i
            c.create_rectangle(L, gy - 3, L + pw, gy + 3, fill=CYAN if active else CARD2, outline="")
            cx = L + pw / 2
            c.create_line(cx - 16, gy, cx + 16, gy, fill=BG if active else SUB, width=2)
            y += bh
        self.draw_zsel()

    def draw_close(self, x, y, key):
        """Petite croix de suppression d'un signal, dans la légende de droite."""
        c = self.chart
        c.create_rectangle(x - 2, y - 2, x + 12, y + 12, fill=CARD2, outline="")
        c.create_line(x + 1, y + 1, x + 9, y + 9, fill=SUB, width=2)
        c.create_line(x + 9, y + 1, x + 1, y + 9, fill=SUB, width=2)
        self.close_hits.append((x - 3, y - 3, x + 13, y + 13, key))

    def draw_zsel(self):
        """Rectangle de sélection d'une zone à agrandir (glisser avec le bouton gauche)."""
        c = self.chart
        c.delete("zsel")
        if self.zsel and self.geom:
            x0, x1 = sorted(self.zsel)
            g = self.geom
            x0, x1 = max(g["L"], x0), min(g["L"] + g["pw"], x1)
            if x1 - x0 >= 1:
                h = max(c.winfo_height(), int(float(str(c.cget("scrollregion")).split()[3])) if c.cget("scrollregion") else 0)
                c.create_rectangle(x0, 0, x1, h, fill=CYAN, outline=CYAN, stipple="gray25", tags="zsel")

    def paint_chart(self):
        """Boucle d'affichage (30 images/s) : redessine seulement si la vue a changé, sinon déplace juste le curseur."""
        try:
            if self.current_page == "graph":
                now = time.monotonic()
                if now - self._sl_t > 0.5:
                    self._sl_t = now
                    self.signal_list.set_groups(self.signal_groups(), self.sel)
                if self.chart_sig() != self._chart_sig:
                    self.draw_chart()
                elif self.cursor_ms() != self._cur_shown:
                    self.move_cursor()
        finally:
            self.root.after(33, self.paint_chart)

    # ---- souris sur le graphique : séparateurs, légende, croix, sélection d'une zone
    def grip_at(self, e):
        if not self.stack.get():
            return None
        y = self.chart.canvasy(e.y)
        for i, gy in self.grips:
            if abs(y - gy) <= 6:
                return i
        return None

    def chart_motion(self, e):
        if self.grip_at(e) is not None:
            self.chart.config(cursor="sb_v_double_arrow")
        elif self.pan:
            self.chart.config(cursor="fleur")
        else:
            x, y = self.chart.canvasx(e.x), self.chart.canvasy(e.y)
            on_x = any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1, _k in self.close_hits)
            self.chart.config(cursor="hand2" if on_x else ("crosshair" if self.in_plot(e.x) else ""))

    def chart_press(self, e):
        i = self.grip_at(e)
        if i is not None:
            self.drag = (i, self.chart.canvasy(e.y), dict(self.band_h))
            return
        x = self.chart.canvasx(e.x)
        y = self.chart.canvasy(e.y)
        for x0, y0, x1, y1, key in self.close_hits:  # petite croix : retire le signal
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.remove_curve(key)
                return
        for x0, y0, x1, y1, key in self.legend_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.ref_key = key
                self.draw_chart()
                return
        if self.in_plot(e.x):
            self.zsel = [e.x, e.x]

    def chart_drag(self, e):
        if self.zsel is not None:
            self.zsel[1] = e.x
            self.draw_zsel()
            return
        if not self.drag:
            return
        i, y0, start = self.drag
        dy = self.chart.canvasy(e.y) - y0
        sel = [k for k in self.curve_keys() if k in self.sel]
        if i >= len(sel):
            return
        k = sel[i]
        hh = start[k]
        if i < len(sel) - 1:
            k2 = sel[i + 1]
            h2 = start[k2]
            dy = max(BAND_MIN - hh, h2 - BAND_MAX, min(h2 - BAND_MIN, BAND_MAX - hh, dy))
            self.band_h[k] = int(hh + dy)
            self.band_h[k2] = int(h2 - dy)
        else:
            self.band_h[k] = int(max(BAND_MIN, min(BAND_MAX, hh + dy)))
        self.draw_chart()

    def chart_release(self, e):
        if self.zsel is not None:
            a, b = sorted(self.zsel)
            self.zsel = None
            self.chart.delete("zsel")
            if b - a >= 6 and self.geom:  # zone assez large : on zoome dessus
                ta, tb = self.time_at(a), self.time_at(b)
                self.set_view(ta, tb - ta)
            elif self.geom and self.frames and not self.live:  # simple clic : le curseur de lecture va à cet endroit
                total = self.frames[-1][0]
                t = max(0.0, min(float(total), self.time_at((a + b) / 2)))
                keep = self.view_end
                self.seek(t / total if total else 0.0)
                self.view_end = keep  # la vue ne saute pas
                self.draw_chart()
            return
        self.drag = None
        self.draw_chart()
