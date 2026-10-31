"""Page Courbes : circuit, sélection des signaux et graphique."""

import bisect
import math
import tkinter as tk
from tkinter import ttk

from .config import BAND_MAX, BAND_MIN, CURVE_INDEX, CURVE_KEYS, UNIT_OF, WINDOWS
from .names import fr
from .theme import BG, BORDER, CARD, CARD2, CYAN, FONT, GREEN, MUTED, PALETTE, SUB, TEXT, YELLOW
from .util import disp_unit, fmt_val, nice_ticks
from .widgets import SignalList


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
            selc, text="Signaux tracés · cliquer pour ajouter", fg=SUB, bg=CARD, font=(FONT, 9, "bold")
        ).pack(anchor="w", padx=10, pady=(8, 4))
        entries = [
            (
                key, f"{fr(key[1])}  ·  0x{key[0]:03X}", PALETTE[CURVE_INDEX[key] % len(PALETTE)]
            ) for key in CURVE_KEYS
        ]
        self.signal_list = SignalList(selc, entries, self.toggle_curve)
        self.signal_list.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.signal_list.refresh(self.sel)

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
        wc = ttk.Combobox(bar, values=[f"{w} s" for w in WINDOWS], state="readonly", width=7)
        wc.set(f"{self.window.get()} s")
        wc.pack(side="right")
        wc.bind(
            "<<ComboboxSelected>>", lambda e: (self.window.set(int(wc.get().split()[0])), self.draw_chart())
        )
        tk.Label(bar, text="Fenêtre", fg=SUB, bg=CARD, font=(FONT, 9)).pack(side="right", padx=(10, 6))
        self.button(bar, "Suivre le direct ▸▸", self.follow, GREEN, CARD2, font=9).pack(side="right", padx=6)
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
        def wheel(e):
            self.chart.yview_scroll(int(-e.delta / 120), "units")
        def hwheel(e):
            self.on_hscroll("scroll", str(int(-e.delta / 120)), "units")
        def enter(e):
            self.chart.bind_all("<MouseWheel>", wheel)
            self.chart.bind_all("<Shift-MouseWheel>", hwheel)
        def leave(e):
            self.chart.unbind_all("<MouseWheel>")
            self.chart.unbind_all("<Shift-MouseWheel>")
        self.chart.bind("<Enter>", enter)
        self.chart.bind("<Leave>", leave)
        self.chart.bind("<ButtonPress-1>", self.chart_press)
        self.chart.bind("<B1-Motion>", self.chart_drag)
        self.chart.bind("<ButtonRelease-1>", self.chart_release)
        self.chart.bind("<Motion>", self.chart_motion)
        self.chart.bind("<Configure>", lambda e: self.draw_chart())
        self.refresh_mode_buttons()

    def toggle_curve(self, key):
        if key in self.sel:
            self.sel.discard(key)
        else:
            self.sel.add(key)
        self.signal_list.refresh(self.sel)

    def set_stack(self, stacked):
        self.stack.set(stacked)
        self.refresh_mode_buttons()
        self.chart.yview_moveto(0)
        self.draw_chart()

    def follow(self):
        self.view_end = None
        self.draw_chart()

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
        half = self.window.get() * 500
        if self.full_t:
            return (-half, self.frames[-1][0] + half)
        ts = [self.hist[k][0][0] for k in self.sel if k in self.hist and self.hist[k]]
        return (min(ts + [0]) if ts else 0, self.t_now + half)

    def on_hscroll(self, *a):
        span = self.window.get() * 1000
        t0, tmax = self.scroll_range()
        if tmax - t0 <= span:
            return
        cur = self.view_end if self.view_end is not None else self.t_now + span / 2
        if a[0] == "moveto":
            end = t0 + float(a[1]) * (tmax - t0) + span
        else:
            step = span * (0.9 if a[2] == "pages" else 0.1)
            end = cur + int(a[1]) * step
        end = min(tmax, max(t0 + span, end))
        self.view_end = None if end >= tmax - 1 else end
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

    def tlabel(self, sec, step):
        sg = "-" if sec < -1e-09 else ""
        sec = abs(sec)
        if step < 1:
            m = int(sec // 60)
            return f"{sg}{m:02d}:{sec - 60 * m:04.1f}"
        sec = int(round(sec))
        return f"{sg}{sec // 60:02d}:{sec % 60:02d}"

    def draw_chart(self):
        c = self.chart
        ta = self.taxis
        c.delete("all")
        ta.delete("all")
        self.grips = []
        self.legend_hits = []
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 300 or h <= 100:
            return
        win = self.window.get()
        span = win * 1000
        tmax = self.t_now
        half = span / 2
        end = self.view_end if self.view_end is not None else tmax + half
        start = end - span
        sel = [k for k in CURVE_KEYS if k in self.sel]
        L, R, T = (70, 250, 10)
        pw = w - L - R
        # ascenseur horizontal
        t0, tmx = self.scroll_range()
        tot = tmx - t0
        if tot > span:
            self.chart_hsb.set(max(0, min(1, (start - t0) / tot)), max(0, min(1, (end - t0) / tot)))
        else:
            self.chart_hsb.set(0, 1)
        # axe du temps (fixe, sous la zone de courbes)
        ticks = nice_ticks(start / 1000, end / 1000, max(2, pw // 110))
        tstep = ticks[1] - ticks[0] if len(ticks) > 1 else 1
        xs = []
        ta.create_line(L, 0, L + pw, 0, fill=BORDER)
        for sec in ticks:
            x = L + pw * (sec * 1000 - start) / span
            xs.append(x)
            ta.create_line(x, 0, x, 5, fill=SUB)
            ta.create_text(x, 7, text=self.tlabel(sec, tstep), fill=SUB, font=(FONT, 8), anchor="n")
        if start <= tmax <= end:
            xn = L + pw * (tmax - start) / span
            ta.create_line(xn, 0, xn, 8, fill=GREEN, width=2)
        ta.create_text(
            L + pw + 16,
            7,
            text="◂ historique" if self.view_end is not None else "en direct",
            fill=YELLOW if self.view_end is not None else GREEN,
            font=(FONT, 8, "bold"),
            anchor="nw",
        )

        def window_pts(key):
            if self.full_t:
                ts = self.full_t.get(key)
                if not ts:
                    return []
                i = bisect.bisect_left(ts, start)
                j = bisect.bisect_right(ts, end)
                pts = list(zip(ts[i:j], self.full_v[key][i:j]))
                st = len(pts) // (2 * max(pw, 1)) + 1
                return pts[::st] if st > 1 else pts
            pts = []
            for tt, v in reversed(self.hist.get(key, ())):
                if tt > end:
                    continue
                if tt < start:
                    break
                pts.append((tt, v))
            pts.reverse()
            st = len(pts) // (2 * max(pw, 1)) + 1
            return pts[::st] if st > 1 else pts
        def poly(pts, ymap, color):
            co = []
            for tt, v in pts:
                co.extend((L + pw * (tt - start) / span, ymap(v)))
            if len(co) >= 4:
                c.create_line(*co, fill=color, width=2)
        def unit_of(key):
            return disp_unit(UNIT_OF.get(key, ""))
        def cur_of(key, pts):
            if self.full_t and self.full_t.get(key):
                i = bisect.bisect_right(self.full_t[key], tmax)
                return self.full_v[key][max(0, i - 1)]
            return pts[-1][1]
        xnow = L + pw * (tmax - start) / span
        def vgrid(y0, y1):
            for x in xs:
                c.create_line(x, y0, x, y1, fill=BORDER, dash=(2, 5))
            if start <= tmax <= end:
                c.create_line(xnow, y0, xnow, y1, fill=GREEN, dash=(4, 3))

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
            rcol = PALETTE[CURVE_INDEX[ref] % len(PALETTE)]
            c.create_rectangle(L, T, L + pw, T + ph, outline=BORDER)
            if ref in data:
                lo, hi, tks = self.axis_for(data[ref][1], data[ref][2])
                for v in tks:
                    y = T + ph * (1 - (v - lo) / (hi - lo))
                    c.create_line(L, y, L + pw, y, fill=BORDER)
                    c.create_text(L - 8, y, text=fmt_val(v), fill=rcol, font=(FONT, 8), anchor="e")
                u = unit_of(ref)
                if u:
                    c.create_text(L - 8, T - 1, text=u, fill=rcol, font=(FONT, 8, "bold"), anchor="se")
            else:
                for i in range(1, 4):
                    y = T + ph * i / 4
                    c.create_line(L, y, L + pw, y, fill=BORDER)
            vgrid(T, T + ph)
            for key in sel:
                if key not in data:
                    continue
                pts, mn, mx, _ = data[key]
                lo, hi, _t = self.axis_for(mn, mx)
                poly(
                    pts,
                    lambda v, lo=lo, hi=hi: T + ph * (1 - (v - lo) / (hi - lo)),
                    PALETTE[CURVE_INDEX[key] % len(PALETTE)],
                )
            lx = L + pw + 16
            c.create_text(
                lx, T, text="Signal · min · max · actuel", anchor="nw", fill=SUB, font=(FONT, 8, "bold")
            )
            for i, key in enumerate(sel):
                color = PALETTE[CURVE_INDEX[key] % len(PALETTE)]
                cid, name = key
                y0 = T + 22 + i * 48
                if key == ref:
                    c.create_rectangle(lx - 6, y0 - 4, w - 6, y0 + 42, outline=color)
                self.legend_hits.append((lx - 6, y0 - 4, w - 6, y0 + 42, key))
                c.create_line(lx, y0 + 7, lx + 18, y0 + 7, fill=color, width=3)
                c.create_text(
                    lx + 26,
                    y0,
                    text=f"{fr(name)} · 0x{cid:03X}",
                    anchor="nw",
                    fill=TEXT,
                    font=(FONT, 8, "bold"),
                )
                if key in data:
                    _p, mn, mx, cur = data[key]
                    c.create_text(
                        lx + 26,
                        y0 + 14,
                        text=f"{fmt_val(mn)} … {fmt_val(mx)} {unit_of(key)}",
                        anchor="nw",
                        fill=SUB,
                        font=(FONT, 8),
                    )
                    c.create_text(
                        lx + 26,
                        y0 + 27,
                        text=f"actuel {fmt_val(cur)}" + ("   ◂ axe de gauche" if key == ref else ""),
                        anchor="nw",
                        fill=color if key == ref else TEXT,
                        font=(FONT, 8, "bold"),
                    )
                else:
                    c.create_text(
                        lx + 26, y0 + 14, text="pas de donnée", anchor="nw", fill=MUTED, font=(FONT, 8)
                    )
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
            color = PALETTE[CURVE_INDEX[key] % len(PALETTE)]
            cid, name = key
            c.create_rectangle(L, y0, L + pw, y1, outline=BORDER, fill=BG)
            vgrid(y0, y1)
            lx = L + pw + 16
            c.create_text(
                lx, y0 + 2, text=f"{fr(name)} · 0x{cid:03X}", anchor="nw", fill=color, font=(FONT, 9, "bold")
            )
            pts = window_pts(key)
            if len(pts) < 2:
                c.create_text(L + pw / 2, (y0 + y1) / 2, text="pas de donnée", fill=MUTED, font=(FONT, 8))
            else:
                vals = [v for _, v in pts]
                mn = min(vals)
                mx = max(vals)
                lo, hi, tks = self.axis_for(mn, mx)
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
                    y0 + 17,
                    text=f"{fmt_val(mn)} … {fmt_val(mx)} {unit_of(key)}",
                    anchor="nw",
                    fill=SUB,
                    font=(FONT, 8),
                )
                c.create_text(
                    lx,
                    y0 + 30,
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

    def paint_chart(self):
        try:
            if self.current_page == "graph":
                self.draw_chart()
        finally:
            self.root.after(180, self.paint_chart)

    # ---- souris sur le graphique : séparateurs et légende
    def grip_at(self, e):
        if not self.stack.get():
            return None
        y = self.chart.canvasy(e.y)
        for i, gy in self.grips:
            if abs(y - gy) <= 6:
                return i
        return None

    def chart_motion(self, e):
        self.chart.config(cursor="sb_v_double_arrow" if self.grip_at(e) is not None else "")

    def chart_press(self, e):
        i = self.grip_at(e)
        if i is not None:
            self.drag = (i, self.chart.canvasy(e.y), dict(self.band_h))
            return
        x = self.chart.canvasx(e.x)
        y = self.chart.canvasy(e.y)
        for x0, y0, x1, y1, key in self.legend_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.ref_key = key
                self.draw_chart()
                return

    def chart_drag(self, e):
        if not self.drag:
            return
        i, y0, start = self.drag
        dy = self.chart.canvasy(e.y) - y0
        sel = [k for k in CURVE_KEYS if k in self.sel]
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
        self.drag = None
        self.draw_chart()
