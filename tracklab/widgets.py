"""Widgets dessinés sur Canvas : jauges, barres, boîte de vitesses, icônes, barre de lecture."""

import math
import time
import tkinter as tk
from tkinter import ttk

from .theme import BG, BORDER, CARD, CARD2, FONT, MUTED, RED, SUB, TEXT


def ease_toward(cur, target, dt, tau=0.09):
    """Rapproche `cur` de `target` de façon exponentielle (lissage des valeurs affichées) ; renvoie la nouvelle valeur."""
    if cur is None or target is None:
        return target
    nv = cur + (target - cur) * (1 - math.exp(-dt / tau))
    return target if abs(target - nv) <= max(1e-6, abs(target) * 2e-4) else nv


def make_dot(parent, color, bg, size=10):
    c = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
    c.create_oval(1, 1, size - 1, size - 1, fill=color, outline="", tags="d")
    return c


def set_dot(c, color):
    c.itemconfig("d", fill=color)


class Gauge(tk.Canvas):
    """Jauge circulaire 270° : arc coloré par zone, graduations et valeur au centre."""

    def __init__(self, parent, maximum, unit, ticks, color_fn):
        super().__init__(parent, bg=CARD, highlightthickness=0, height=210)
        self.maximum = maximum
        self.unit = unit
        self.ticks = ticks
        self.color_fn = color_fn
        self.value = None  # valeur affichée (lissée)
        self.target = None  # valeur réelle
        self._t = time.monotonic()
        self.dirty = True
        self.bind("<Configure>", lambda e: self.render())

    def set(self, value):
        self.target = value
        if value is None or self.value is None:
            self.value = value
        self.dirty = True

    def set_scale(self, maximum, ticks):
        self.maximum = maximum
        self.ticks = ticks
        self.dirty = True

    def flush(self):
        now = time.monotonic()
        dt, self._t = min(0.2, now - self._t), now
        if self.value != self.target:
            self.value = ease_toward(self.value, self.target, dt)
            self.dirty = True
        if self.dirty:
            self.dirty = False
            self.render()

    def render(self):
        self.delete("all")
        w = max(160, self.winfo_width())
        h = max(140, self.winfo_height())
        r = min(w * 0.42, h * 0.62)
        cx = w / 2
        cy = h / 2 + r * 0.12
        th = max(8, int(r * 0.12))
        start = 225
        sweep = -270
        box = (cx - r, cy - r, cx + r, cy + r)
        self.create_arc(*box, start=start, extent=sweep, style="arc", outline=CARD2, width=th)
        if self.value is not None:
            frac = max(0, min(1, float(self.value) / self.maximum))
            n = int(frac * 60) + 1
            for i in range(n):
                f0 = i / 60
                f1 = min(frac, (i + 1) / 60)
                if f1 <= f0 + 1e-09:
                    continue
                self.create_arc(
                    *box,
                    start=start + sweep * f0,
                    extent=sweep * (f1 - f0),
                    style="arc",
                    outline=self.color_fn((f0 + f1) / 2),
                    width=th,
                )
        ri = r - th / 2 - 3
        for i in range(41):
            a = math.radians(start + sweep * i / 40)
            major = i % 5 == 0
            r2 = ri - (th * 0.9 if major else th * 0.4)
            self.create_line(
                cx + ri * math.cos(a),
                cy - ri * math.sin(a),
                cx + r2 * math.cos(a),
                cy - r2 * math.sin(a),
                fill=SUB if major else MUTED,
                width=2 if major else 1,
            )
        for frac, label in self.ticks:
            a = math.radians(start + sweep * frac)
            lr = ri - th * 2.2
            self.create_text(
                cx + lr * math.cos(a),
                cy - lr * math.sin(a),
                text=label,
                fill=SUB,
                font=(FONT, max(8, int(r * 0.08)), "bold"),
            )
        val = "—" if self.value is None else f"{self.value:,.0f}".replace(",", " ")
        self.create_text(cx, cy - r * 0.08, text=val, fill=TEXT, font=(FONT, max(14, int(r * 0.24)), "bold"))
        self.create_text(cx, cy + r * 0.22, text=self.unit, fill=SUB, font=(FONT, max(8, int(r * 0.1))))


class Bar(tk.Canvas):
    """Barre fine proportionnelle à la valeur entre lo et hi."""

    def __init__(self, parent, color, lo, hi, height=8):
        super().__init__(parent, height=height, bg=CARD, highlightthickness=0)
        self.color = color
        self.lo = lo
        self.hi = hi
        self.frac = None  # position affichée (lissée)
        self.target = None
        self._t = time.monotonic()
        self.dirty = True
        self.bind("<Configure>", lambda e: self.render())

    def set(self, value):
        self.target = None if value is None else max(0, min(1, (float(value) - self.lo) / (self.hi - self.lo)))
        if self.target is None or self.frac is None:
            self.frac = self.target
        self.dirty = True

    def flush(self):
        now = time.monotonic()
        dt, self._t = min(0.2, now - self._t), now
        if self.frac != self.target:
            self.frac = ease_toward(self.frac, self.target, dt)
            self.dirty = True
        if self.dirty:
            self.dirty = False
            self.render()

    def render(self):
        self.delete("all")
        w = max(20, self.winfo_width())
        h = int(self.cget("height"))
        self.create_rectangle(0, 0, w, h, fill=CARD2, outline="")
        if self.frac is not None:
            self.create_rectangle(0, 0, w * self.frac, h, fill=self.color, outline="")


class GearBox(tk.Canvas):
    """Rangée N 1 2 3 4 5 6 avec le rapport engagé en surbrillance."""
    LABELS = ["N", "1", "2", "3", "4", "5", "6"]

    def __init__(self, parent, height=40):
        super().__init__(parent, height=height, bg=CARD, highlightthickness=0)
        self.gear = None
        self.dirty = True
        self.bind("<Configure>", lambda e: self.render())

    def set(self, gear):
        self.gear = gear
        self.dirty = True

    def flush(self):
        if self.dirty:
            self.dirty = False
            self.render()

    def render(self):
        self.delete("all")
        w = max(60, self.winfo_width())
        h = int(self.cget("height"))
        cw = w / len(self.LABELS)
        for i, label in enumerate(self.LABELS):
            x0 = i * cw + 2
            x1 = (i + 1) * cw - 2
            on = self.gear == i
            self.create_rectangle(x0, 3, x1, h - 3, fill=RED if on else CARD2, outline="")
            self.create_text(
                (x0 + x1) / 2, h / 2, text=label, fill=TEXT if on else MUTED, font=(FONT, 10, "bold")
            )


class NavIcon(tk.Canvas):
    """Petit symbole dessiné (indépendant des polices) à côté d'un bouton de menu."""

    def __init__(self, parent, kind, bg):
        super().__init__(parent, width=26, height=22, bg=bg, highlightthickness=0, cursor="hand2")
        self.kind = kind
        self.paint(bg, RED)

    def paint(self, bg, color):
        c = self
        c.delete("all")
        c.config(bg=bg)
        k = self.kind
        w = 2
        if k == "tele":  # cadran
            c.create_arc(3, 4, 23, 24, start=0, extent=180, style="arc", outline=color, width=w)
            c.create_line(13, 14, 19, 8, fill=color, width=w)
            c.create_oval(11, 12, 15, 16, fill=color, outline=color)
        elif k == "graph":
            c.create_line(3, 18, 3, 4, fill=color, width=1)
            c.create_line(3, 18, 23, 18, fill=color, width=1)
            c.create_line(4, 15, 9, 8, 13, 13, 18, 5, 23, 10, fill=color, width=w, smooth=True)
        elif k == "frames":
            for i, y in enumerate((5, 11, 17)):
                c.create_rectangle(3, y - 1, 7, y + 2, fill=color, outline=color)
                c.create_line(10, y, 23, y, fill=color, width=w)
        elif k == "esp":
            c.create_rectangle(7, 6, 19, 16, outline=color, width=w)
            for x in (10, 13, 16):
                c.create_line(x, 3, x, 6, fill=color, width=1)
                c.create_line(x, 16, x, 19, fill=color, width=1)
        else:
            c.create_oval(8, 6, 18, 16, outline=color, width=w)
            c.create_oval(11, 9, 15, 13, outline=color, width=1)
            for x0, y0, x1, y1 in (
                (13, 2, 13, 5),
                (13, 17, 13, 20),
                (3, 11, 7, 11),
                (19, 11, 23, 11),
                (6, 4, 8, 6),
                (18, 16, 20, 18),
                (6, 18, 8, 16),
                (18, 6, 20, 4),
            ):
                c.create_line(x0, y0, x1, y1, fill=color, width=w)


class SeekBar(tk.Canvas):
    """Barre de progression cliquable : un clic ou un glissement choisit l'instant de lecture."""

    def __init__(self, parent, on_seek, on_drag=None, width=300, height=22):
        super().__init__(parent, width=width, height=height, bg=CARD, highlightthickness=0, cursor="hand2")
        self.frac = 0
        self.on_seek = on_seek
        self.on_drag = on_drag
        self.dragging = False
        self.bind("<Configure>", lambda e: self.render())
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", self.release)

    def set(self, frac):
        if not self.dragging:
            self.frac = max(0, min(1, frac))
            self.render()

    def _f(self, e):
        return max(0, min(1, (e.x - 8) / max(1, self.winfo_width() - 16)))

    def press(self, e):
        self.dragging = True
        self.frac = self._f(e)
        self.render()
        if self.on_drag:
            self.on_drag(self.frac)

    def move(self, e):
        if self.dragging:
            self.frac = self._f(e)
            self.render()
            if self.on_drag:
                self.on_drag(self.frac)

    def release(self, e):
        if self.dragging:
            self.dragging = False
            self.frac = self._f(e)
            self.render()
            self.on_seek(self.frac)

    def render(self):
        self.delete("all")
        w = max(40, self.winfo_width())
        h = max(10, self.winfo_height())
        cy = h / 2
        x0 = 8
        x1 = w - 8
        xf = x0 + (x1 - x0) * self.frac
        self.create_rectangle(x0, cy - 3, x1, cy + 3, fill=CARD2, outline="")
        self.create_rectangle(x0, cy - 3, xf, cy + 3, fill=RED, outline="")
        self.create_oval(xf - 7, cy - 7, xf + 7, cy + 7, fill=TEXT, outline=RED, width=2)


class ScrollCanvas(tk.Frame):
    """Canvas à ascenseur vertical, molette comprise : base des listes dessinées d'un seul bloc."""

    def __init__(self, parent, bg, width=10):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=width, yscrollincrement=30)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class TileBoard(ScrollCanvas):
    """Toutes les tuiles de télémétrie sur un seul Canvas (quelques centaines d'objets graphiques, aucun widget).

    groups : liste de (titre, [(clé, libellé, unité), ...]). La clé est (identifiant CAN, nom du signal).
    """

    TILE_W, TILE_H, GAP = (186, 96, 10)

    def __init__(self, parent, groups):
        super().__init__(parent, BG)
        c = self.canvas
        self.cols = 0
        self.groups = []  # (objet titre, [clés])
        self.items = {}  # clé -> (cadre, nom, valeur, unité, source)
        for title, tiles in groups:
            heading = c.create_text(0, 0, text=title.upper(), anchor="nw", fill=MUTED, font=(FONT, 8, "bold"))
            keys = []
            for key, label, unit in tiles:
                self.items[key] = (
                    c.create_rectangle(0, 0, 1, 1, fill=CARD, outline=BORDER),
                    c.create_text(0, 0, text=label, anchor="nw", fill=SUB, font=(FONT, 8, "bold")),
                    c.create_text(0, 0, text="—", anchor="nw", fill=TEXT, font=(FONT, 18, "bold")),
                    c.create_text(0, 0, text=unit, anchor="ne", fill=MUTED, font=(FONT, 9)),
                    c.create_text(
                        0, 0, text=self.default_source(key), anchor="sw", fill=MUTED, font=(FONT, 7, "bold")
                    ),
                )
                keys.append(key)
            self.groups.append((heading, keys))
        c.bind("<Configure>", self._on_configure)

    @staticmethod
    def default_source(key):
        return f"0x{key[0]:03X}"

    def _on_configure(self, event):
        cols = max(1, (event.width - 8) // (self.TILE_W + self.GAP))
        if cols != self.cols:
            self.cols = cols
            self.layout()

    def layout(self):
        """Place les tuiles en grille ; ne recrée rien, déplace seulement les objets existants."""
        c, W, H, G = (self.canvas, self.TILE_W, self.TILE_H, self.GAP)
        y = 0
        for heading, keys in self.groups:
            y += 12
            c.coords(heading, 5, y)
            y += 20
            for i, key in enumerate(keys):
                x = 5 + i % self.cols * (W + G)
                top = y + i // self.cols * (H + G)
                frame, name, value, unit, source = self.items[key]
                c.coords(frame, x, top, x + W, top + H)
                c.coords(name, x + 10, top + 8)
                c.coords(value, x + 10, top + 26)
                c.coords(unit, x + W - 10, top + 38)
                c.coords(source, x + 10, top + H - 6)
            y += -(-len(keys) // self.cols) * (H + G)
        c.configure(scrollregion=(0, 0, 1, y + 10))

    def update_tile(self, key, text, source, source_color):
        _, _, value, _, src = self.items[key]
        if text is not None:
            self.canvas.itemconfig(value, text=text)
        self.canvas.itemconfig(src, text=source, fill=source_color)

    def set_text(self, key, text):
        item = self.items[key][2]
        if self.canvas.itemcget(item, "text") != text:
            self.canvas.itemconfig(item, text=text)

    def set_value_color(self, key, color):
        self.canvas.itemconfig(self.items[key][2], fill=color)

    def rename(self, key, label):
        self.canvas.itemconfig(self.items[key][1], text=label)

    def reset(self):
        for key, (_, _, value, _, source) in self.items.items():
            self.canvas.itemconfig(value, text="—", fill=TEXT)
            self.canvas.itemconfig(source, text=self.default_source(key), fill=MUTED)


class SignalList(ScrollCanvas):
    """Liste de signaux cliquables (un clic ajoute ou retire la courbe)."""

    ROW = 26

    def __init__(self, parent, entries, on_toggle):
        """entries : liste de (clé, libellé, couleur)."""
        super().__init__(parent, CARD, width=190)
        c = self.canvas
        c.configure(cursor="hand2")
        self.rows = {}
        for i, (key, label, color) in enumerate(entries):
            y = i * self.ROW
            tag = f"row{i}"
            rect = c.create_rectangle(0, y + 1, 1, y + self.ROW - 1, fill=CARD2, outline="", tags=tag)
            text = c.create_text(
                8, y + self.ROW // 2, text=label, anchor="w", fill=SUB, font=(FONT, 9, "bold"), tags=tag
            )
            c.tag_bind(tag, "<Button-1>", lambda e, k=key: on_toggle(k))
            self.rows[key] = (rect, text, color, y)
        c.configure(scrollregion=(0, 0, 1, len(entries) * self.ROW))
        c.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        for rect, _, _, y in self.rows.values():
            self.canvas.coords(rect, 0, y + 1, event.width, y + self.ROW - 1)

    def refresh(self, selected):
        for key, (rect, text, color, _) in self.rows.items():
            on = key in selected
            self.canvas.itemconfig(rect, fill=color if on else CARD2)
            self.canvas.itemconfig(text, fill=BG if on else (MUTED if key in self.nodata else SUB))


class GroupedSignalList(ScrollCanvas):
    """Liste de signaux classés par type (GPS, CAN, capteurs…) ; un clic sur un signal ajoute ou retire sa courbe,
    un clic sur un titre replie ou déplie son type."""

    ROW, HEAD = 26, 28

    def __init__(self, parent, on_toggle, color_of):
        super().__init__(parent, CARD, width=190)
        self.on_toggle = on_toggle
        self.color_of = color_of
        self.collapsed = set()
        self.groups = []  # [(titre, [(clé, libellé)])]
        self.selected = set()
        self._sig = None
        self.rows = {}  # clé -> (rectangle, texte)
        self.nodata = set()  # signaux sans donnée dans la source courante : affichés en grisé
        self.hits = []  # (y0, y1, "head" | "row", titre ou clé)
        self.canvas.configure(cursor="hand2")
        self.canvas.bind("<Configure>", lambda e: self._layout(e.width))
        self.canvas.bind("<Button-1>", self._click)

    def set_groups(self, groups, selected):
        """Met à jour la liste (reconstruite seulement si son contenu a changé) et l'état de sélection."""
        sig = (tuple((t, tuple((it[0], len(it) < 3 or it[2]) for it in items)) for t, items in groups),
               tuple(sorted(self.collapsed)))
        self.selected = set(selected)
        if sig != self._sig:
            self._sig = sig
            self.groups = groups
            self._draw()
        else:
            self.refresh(selected)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        self.rows, self.hits = {}, []
        self.nodata = {it[0] for _t, items in self.groups for it in items if len(it) > 2 and not it[2]}
        y = 0
        w = max(c.winfo_width(), 190)
        for title, items in self.groups:
            n_sel = sum(1 for it in items if it[0] in self.selected)
            arrow = "▸" if title in self.collapsed else "▾"
            c.create_rectangle(0, y + 1, w, y + self.HEAD - 1, fill=BG, outline="", tags="bg")
            c.create_text(
                8, y + self.HEAD // 2, text=f"{arrow}  {title.upper()}", anchor="w", fill=MUTED, font=(FONT, 8, "bold")
            )
            c.create_text(
                w - 10, y + self.HEAD // 2, text=f"{n_sel}/{len(items)}" if n_sel else str(len(items)),
                anchor="e", fill=SUB if n_sel else MUTED, font=(FONT, 8), tags="count"
            )
            self.hits.append((y, y + self.HEAD, "head", title))
            y += self.HEAD
            if title in self.collapsed:
                continue
            for it in items:
                key, label = it[0], it[1]
                rect = c.create_rectangle(0, y + 1, w, y + self.ROW - 1, fill=CARD2, outline="", tags="row")
                text = c.create_text(14, y + self.ROW // 2, text=label, anchor="w", fill=SUB, font=(FONT, 9, "bold"))
                self.rows[key] = (rect, text)
                self.hits.append((y, y + self.ROW, "row", key))
                y += self.ROW
        c.configure(scrollregion=(0, 0, 1, y))
        self.refresh(self.selected)

    def _layout(self, width):
        for item in self.canvas.find_withtag("row") + self.canvas.find_withtag("bg"):
            x0, y0, _x1, y1 = self.canvas.coords(item)
            self.canvas.coords(item, 0, y0, width, y1)
        for item in self.canvas.find_withtag("count"):
            _x, y = self.canvas.coords(item)
            self.canvas.coords(item, width - 10, y)

    def refresh(self, selected):
        self.selected = set(selected)
        for key, (rect, text) in self.rows.items():
            on = key in self.selected
            self.canvas.itemconfig(rect, fill=self.color_of(key) if on else CARD2)
            self.canvas.itemconfig(text, fill=BG if on else (MUTED if key in self.nodata else SUB))

    def _click(self, event):
        y = self.canvas.canvasy(event.y)
        for y0, y1, kind, ref in self.hits:
            if y0 <= y < y1:
                if kind == "head":
                    self.collapsed.symmetric_difference_update({ref})
                    self._sig = None
                    self.set_groups(self.groups, self.selected)
                else:
                    self.on_toggle(ref)
                return
