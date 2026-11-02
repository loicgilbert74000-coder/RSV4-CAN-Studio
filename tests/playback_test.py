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
    assert app.span_ms == 30000 and app.view_start() == 0 and app.geom["start"] == 0, (app.span_ms, app.geom)
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
    assert all(app.yr_cache.get(k) == v for k, v in axes0.items()), "échelle modifiée pendant la lecture"
    # clic dans la fenêtre : le curseur va à cet endroit
    g = app.geom
    x = int(g["L"] + g["pw"] * 0.5)
    app.chart_press(Event(x, 5))
    app.chart_release(Event(x, 5))
    want = g["start"] + g["span"] * 0.5
    assert abs(app.t_now - want) < max(400, want * 0.1), (app.t_now, want)
    print("OK : lecture", calls)


if __name__ == "__main__":
    main(sys.argv[1])
