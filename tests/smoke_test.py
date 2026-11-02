"""Test de fumée de l'interface (sans clic réel).

Usage : python tests/smoke_test.py CAPTURE.txt [dossier_captures_ecran]
Sous Linux sans écran : xvfb-run -a python tests/smoke_test.py CAPTURE.txt
"""

import os
import subprocess
import sys
import time
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracklab.app import App  # noqa: E402
from tracklab.config import CURVE_KEYS  # noqa: E402
from tracklab.names import fr  # noqa: E402


class Event:
    """Évènement souris minimal."""

    def __init__(self, x=0, y=0):
        self.x, self.y = x, y


def main(capture, shots=None):
    messagebox.showerror = messagebox.showinfo = messagebox.showwarning = lambda *a, **k: None
    app = App()

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.root.update()
            time.sleep(0.01)

    def shot(name):
        if shots:
            subprocess.run(["import", "-window", "root", os.path.join(shots, name + ".png")], timeout=30, check=False)

    pump(0.3)
    app.load(capture)
    assert app.frames and app.full_t, "capture non chargée ou non pré-décodée"

    # saut dans la capture
    app.seek(0.6)
    assert 0 < app.idx < len(app.frames)
    pump(0.2)
    bar = app.seekbar
    bar.press(Event(8 + int((bar.winfo_width() - 16) * 0.25)))
    bar.release(Event(8 + int((bar.winfo_width() - 16) * 0.25)))
    assert abs(app.idx / len(app.frames) - 0.25) < 0.1

    # changement de page
    timings = {}
    for page in ["graph", "tele", "frames", "esp", "tele", "graph", "tele"]:
        start = time.time()
        app.show_page(page)
        app.root.update()
        timings[page] = round((time.time() - start) * 1000)
    print("passage de page (ms) :", timings)

    # fenêtre de connexion
    app.open_connection_dialog()
    app.root.update()
    assert app._conn_win.winfo_exists()
    shot("connexion")
    app._conn_win.destroy()

    # courbes : superposées, empilées, séparateur, ascenseur horizontal
    app.show_page("graph")
    app.seek(1.0)
    pump(0.3)
    shot("courbes_superposees")
    app.sel |= {CURVE_KEYS[0]}
    app.set_stack(True)
    pump(0.3)
    shot("courbes_empilees")
    heights = [app.band_h[k] for k in CURVE_KEYS if k in app.sel and k in app.band_h]
    index, grip_y = app.grips[0]
    app.chart_press(Event(300, int(grip_y)))
    app.chart_drag(Event(300, int(grip_y) + 40))
    app.chart_release(Event())
    assert app.band_h[[k for k in CURVE_KEYS if k in app.sel][0]] != heights[0], "séparateur sans effet"
    app.set_view(0, 10000)
    pump(0.2)
    app.on_hscroll("scroll", "-3", "units")
    assert app.view_end is not None
    # molette : zoom avant puis arrière, centré sur le curseur
    sp = app.span_ms
    app.zoom_at(app.geom["L"] + app.geom["pw"] / 2, 0.8)
    assert app.span_ms < sp
    app.zoom_at(app.geom["L"] + app.geom["pw"] / 2, 1.25)
    # sélection d'une zone à la souris : le relâché zoome
    a = int(app.geom["L"] + app.geom["pw"] * 0.25)
    b = int(app.geom["L"] + app.geom["pw"] * 0.5)
    sp = app.span_ms
    app.chart_press(Event(a, 5))
    app.chart_drag(Event(b, 5))
    app.chart_release(Event(b, 5))
    pump(0.2)
    assert app.span_ms < sp * 0.5, "zoom sur zone sans effet"
    # petite croix : retire le signal
    n = len(app.sel)
    x0, y0, x1, y1, k = app.close_hits[0]
    app.chart_press(Event(int((x0 + x1) / 2), int((y0 + y1) / 2)))
    assert len(app.sel) == n - 1 and k not in app.sel
    shot("courbes_zoom")
    app.follow()
    app.set_stack(False)
    pump(0.2)

    # trames CAN : filtres
    app.show_page("frames")
    app.seek(1.0)
    pump(0.2)
    total = app.matched
    first_id = sorted({row[2] for row in app.rows})[0]
    app.f_show.set(f"{first_id:X}")
    app.on_filter_change()
    assert 0 < app.matched < total
    shot("trames_filtre")
    app.f_show.set("")
    app.f_hide.set("000-7FF")
    app.on_filter_change()
    assert app.matched == 0
    app.reset_filters()
    assert app.matched == len(app.rows)

    assert fr("Bike_Speed") == "Vitesse moto"
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
