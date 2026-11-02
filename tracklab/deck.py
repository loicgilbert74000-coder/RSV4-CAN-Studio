"""Platine de lecture façon lecteur CD : touches dessinées, afficheur LCD et bargraph de lecture cliquable."""

import time
import tkinter as tk

from .theme import BORDER, CARD, CARD2, CYAN, FONT, GREEN, HOVER, MUTED, RED, SUB, TEXT, YELLOW

KEY_W, KEY_H = 64, 56
LCD_BG = "#04101a"
LCD_DIM = "#0d2a3a"
LCD_EDGE = "#1d3d52"
MONO = "Consolas"


def fmt_lcd(ms):
    ms = max(0, int(ms))
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000 // 100}"


class DeckButton(tk.Canvas):
    """Touche de platine : pictogramme dessiné + petit libellé ; s'éclaire quand elle est active."""

    def __init__(self, parent, kind, caption, command, color=TEXT, bg=CARD, text=""):
        super().__init__(parent, width=KEY_W, height=KEY_H, bg=bg, highlightthickness=0, cursor="hand2")
        self.kind = kind
        self.caption = caption
        self.command = command
        self.color = color  # couleur quand la touche est allumée
        self.text = text  # texte central pour la touche « texte » (vitesse)
        self.lit = False
        self.enabled = True
        self.hover = False
        self.down = False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.render()

    # ---- état
    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.render()

    def _release(self, e):
        was = self.down
        self._set(down=False)
        if was and self.enabled and 0 <= e.x <= KEY_W and 0 <= e.y <= KEY_H:
            self.command()

    def set_look(self, lit=None, kind=None, caption=None, enabled=None, text=None, color=None):
        """Change l'allumage, le pictogramme, le libellé ou l'état de la touche (ne redessine que si besoin)."""
        new = (
            self.lit if lit is None else lit,
            self.kind if kind is None else kind,
            self.caption if caption is None else caption,
            self.enabled if enabled is None else enabled,
            self.text if text is None else text,
            self.color if color is None else color,
        )
        if new != (self.lit, self.kind, self.caption, self.enabled, self.text, self.color):
            self.lit, self.kind, self.caption, self.enabled, self.text, self.color = new
            self.config(cursor="hand2" if self.enabled else "arrow")
            self.render()

    # ---- dessin
    def render(self):
        self.delete("all")
        w, h = KEY_W, KEY_H
        off = 1 if self.down else 0
        face = HOVER if (self.hover and self.enabled) else CARD2
        if self.down:
            face = "#16223a"
        edge = self.color if self.lit else BORDER
        self.create_rectangle(3, 3 + off, w - 3, h - 3 + off, fill=face, outline=edge, width=2 if self.lit else 1)
        self.create_line(6, 5 + off, w - 6, 5 + off, fill="#2b3b57" if not self.lit else self.color)  # reflet
        if not self.enabled:
            col = "#34435c"
        elif self.kind == "rec" and not self.lit:
            col = "#c2282f"  # le point d'enregistrement reste rouge, comme sur une vraie platine
        else:
            col = self.color if self.lit else SUB
        cx, cy = w / 2, 22 + off
        self.icon(self.kind, cx, cy, col)
        self.create_text(
            w / 2, h - 11 + off, text=self.caption, fill=col if self.lit else (MUTED if self.enabled else "#34435c"),
            font=(FONT, 7, "bold"),
        )

    def icon(self, kind, cx, cy, col):
        c = self.create_polygon
        if kind == "play":
            c(cx - 6, cy - 9, cx - 6, cy + 9, cx + 9, cy, fill=col, outline="")
        elif kind == "pause":
            self.create_rectangle(cx - 8, cy - 9, cx - 2, cy + 9, fill=col, outline="")
            self.create_rectangle(cx + 2, cy - 9, cx + 8, cy + 9, fill=col, outline="")
        elif kind == "start":  # retour au début : barre + triangle
            self.create_rectangle(cx - 9, cy - 9, cx - 6, cy + 9, fill=col, outline="")
            c(cx + 9, cy - 9, cx + 9, cy + 9, cx - 4, cy, fill=col, outline="")
        elif kind == "eject":
            c(cx - 9, cy + 2, cx + 9, cy + 2, cx, cy - 9, fill=col, outline="")
            self.create_rectangle(cx - 9, cy + 5, cx + 9, cy + 9, fill=col, outline="")
        elif kind == "rec":
            self.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill=col, outline="")
        elif kind == "stop":
            self.create_rectangle(cx - 8, cy - 8, cx + 8, cy + 8, fill=col, outline="")
        elif kind == "plug":  # prise : on peut se connecter
            self.create_line(cx - 4, cy - 10, cx - 4, cy - 3, fill=col, width=3)
            self.create_line(cx + 4, cy - 10, cx + 4, cy - 3, fill=col, width=3)
            self.create_rectangle(cx - 8, cy - 3, cx + 8, cy + 5, fill=col, outline="")
            self.create_line(cx, cy + 5, cx, cy + 10, fill=col, width=3)
        elif kind == "unplug":  # prise coupée : liaison active, un clic la ferme
            self.create_line(cx - 4, cy - 10, cx - 4, cy - 3, fill=col, width=3)
            self.create_line(cx + 4, cy - 10, cx + 4, cy - 3, fill=col, width=3)
            self.create_rectangle(cx - 8, cy - 3, cx + 8, cy + 5, fill=col, outline="")
            self.create_line(cx, cy + 5, cx, cy + 10, fill=col, width=3)
            self.create_line(cx - 11, cy + 10, cx + 11, cy - 10, fill=RED, width=3)
        else:  # touche texte (vitesse)
            self.create_text(cx, cy, text=self.text, fill=col, font=(MONO, 13, "bold"))


class DeckLcd(tk.Canvas):
    """Afficheur : mode, vue, temps, nom du fichier, et bargraph de lecture sur lequel on clique pour se déplacer."""

    BAR_Y0, BAR_Y1 = 66, 78
    SEG, GAP = 5, 2

    def __init__(self, parent, on_seek, height=88):
        super().__init__(parent, height=height, bg=CARD, highlightthickness=0)
        self.on_seek = on_seek
        self.s = dict(mode="idle", mode_text="PRÊT", mode_color=MUTED, view="", source="", cur=0, total=0,
                      name="Aucun fichier", info="", frac=0.0, seekable=False, rec=False)
        self.dragging = False
        self.drag_frac = 0.0
        self.bind("<Configure>", lambda e: self.render())
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", self.release)

    def show(self, **kw):
        """Met à jour l'afficheur ; redessine seulement si quelque chose a changé (ou pour faire clignoter REC)."""
        blink = bool(self.s.get("rec")) and int(time.monotonic() * 2) % 2 == 0
        old = (dict(self.s), getattr(self, "_blink", None))
        self.s.update(kw)
        self._blink = blink
        if old != (self.s, blink) and not self.dragging:
            self.render()

    # ---- souris : clic ou glissé sur la zone du bargraph
    def _frac(self, e):
        w = self.winfo_width()
        return max(0.0, min(1.0, (e.x - 12) / max(1, w - 24)))

    def press(self, e):
        if self.s["seekable"] and e.y >= self.BAR_Y0 - 10:
            self.dragging = True
            self.drag_frac = self._frac(e)
            self.render()

    def move(self, e):
        if self.dragging:
            self.drag_frac = self._frac(e)
            self.render()

    def release(self, e):
        if self.dragging:
            self.dragging = False
            self.drag_frac = self._frac(e)
            self.s["frac"] = self.drag_frac
            self.render()
            self.on_seek(self.drag_frac)

    # ---- dessin
    def render(self):
        self.delete("all")
        w = max(300, self.winfo_width())
        h = int(self.cget("height"))
        s = self.s
        self.create_rectangle(1, 1, w - 2, h - 2, fill=LCD_BG, outline=LCD_EDGE, width=2)
        self.create_rectangle(5, 5, w - 6, h - 6, outline="#08202e")
        frac = self.drag_frac if self.dragging else s["frac"]
        cur = frac * s["total"] if self.dragging else s["cur"]
        # ligne du haut : mode à gauche, vue et source à droite
        self.create_text(14, 17, text=s["mode_text"], anchor="w", fill=s["mode_color"], font=(MONO, 10, "bold"))
        if s["rec"]:
            col = RED if getattr(self, "_blink", False) else "#5a1216"
            self.create_oval(w - 22, 11, w - 12, 21, fill=col, outline="")
            self.create_text(w - 28, 17, text="REC", anchor="e", fill=col, font=(MONO, 10, "bold"))
            right = w - 70
        else:
            right = w - 14
        tag = "  ·  ".join(t for t in (s["source"], s["view"]) if t)
        self.create_text(right, 17, text=tag, anchor="e", fill="#3f8aa8", font=(MONO, 9, "bold"))
        # temps
        self.create_text(14, 45, text=fmt_lcd(cur), anchor="w", fill=CYAN, font=(MONO, 26, "bold"))
        if s["total"]:
            self.create_text(186, 51, text="/ " + fmt_lcd(s["total"]), anchor="w", fill="#2b7a99", font=(MONO, 11, "bold"))
        # nom et informations
        maxc = max(10, int((w - 330) / 7.5))
        name = s["name"] if len(s["name"]) <= maxc else s["name"][: maxc - 1] + "…"
        info = s["info"] if len(s["info"]) <= maxc else s["info"][: maxc - 1] + "…"
        self.create_text(318, 38, text=name, anchor="w", fill=TEXT, font=(MONO, 11, "bold"))
        self.create_text(318, 55, text=info, anchor="w", fill="#3f8aa8", font=(MONO, 9))
        # bargraph : segments allumés jusqu'à la position
        x0, x1 = 12, w - 12
        n = max(10, int((x1 - x0) / (self.SEG + self.GAP)))
        lit = int(round(frac * n))
        y0, y1 = self.BAR_Y0, self.BAR_Y1
        for i in range(n):
            x = x0 + i * (self.SEG + self.GAP)
            if i < lit:
                col = GREEN if s["mode"] == "live" else CYAN
                if s["mode"] != "live" and i >= n * 0.92:
                    col = YELLOW
                if s["mode"] == "live" and i >= n * 0.8:
                    col = YELLOW if i < n * 0.92 else RED
            else:
                col = LCD_DIM
            self.create_rectangle(x, y0, x + self.SEG, y1, fill=col, outline="")
        if s["seekable"] and lit > 0:
            x = x0 + min(n - 1, lit - 1) * (self.SEG + self.GAP)
            self.create_rectangle(x, y0 - 3, x + self.SEG, y1 + 3, fill=TEXT, outline="")
