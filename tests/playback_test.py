"""Lecture des courbes : fenêtre de 30 s démarrant à 0, curseur qui avance sans tout redessiner, clic = curseur, échelles stables."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Event:
    def __init__(self, x=0, y=0):
        self.x, self.y = x, y


def main(capture):
    from tracklab.app import App

    app = App()
    app.root.update()
    app.load(capture)
    app.show_page("graph")
    app.speed.set(8)

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            app.root.update()
            time.sleep(0.01)

    pump(0.5)
    total = app.frames[-1][0]
    assert app.span_ms >= total * 0.98 and app.view_start() <= 0 and app.cursor_ms() == 0, (app.span_ms, total)
    assert app.geom["start"] <= 0
    calls = {"draw": 0, "cursor": 0}
    d0, m0 = app.draw_chart, app.move_cursor
    app.draw_chart = lambda: (calls.__setitem__("draw", calls["draw"] + 1), d0())[1]
    app.move_cursor = lambda: (calls.__setitem__("cursor", calls["cursor"] + 1), m0())[1]
    axes0 = dict(app.yr_cache)
    app.play()
    pump(2.0)
    app.pause()
    assert calls["cursor"] > 20, calls  # le curseur bouge à chaque image
    assert calls["draw"] <= 14, calls  # mais les courbes ne sont pas redessinées à chaque image
    assert not app._scroll_on, "fichier entier affiché : le curseur avance, pas de défilement"
    assert all(app.yr_cache.get(k) == v for k, v in axes0.items()), "échelle modifiée pendant la lecture"
    # clic dans la fenêtre : le curseur va à cet endroit
    g = app.geom
    x = int(g["L"] + g["pw"] * 0.5)
    app.chart_press(Event(x, 5))
    app.chart_release(Event(x, 5))
    pump(0.3)
    want = g["start"] + g["span"] * 0.5
    assert abs(app.t_now - want) < max(400, want * 0.1), (app.t_now, want)
    # zoom puis lecture : le curseur reste fixe, les courbes défilent
    app.span_ms = min(30000, total / 4)
    app.view_end = app.span_ms * 1.0
    app.seek(0.0)
    pump(0.3)
    app.draw_chart()
    starts = []
    app.play()
    for _ in range(8):
        pump(0.15)
        starts.append(app.geom["start"])
    assert app._scroll_on, "défilement attendu"
    assert starts[-1] > starts[0], starts
    app.pause()
    pump(0.2)
    assert app.view_end is not None
    # latence du clic : le curseur est déplacé avant le saut
    t0 = time.time()
    app.chart_press(Event(x, 5))
    app.chart_release(Event(x, 5))
    assert time.time() - t0 < 0.15, time.time() - t0
    print("OK : lecture", calls)


if __name__ == "__main__":
    main(sys.argv[1])
