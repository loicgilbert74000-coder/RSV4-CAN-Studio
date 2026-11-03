"""Cœur Qt sans interface : charge une capture et compare avec l'application tkinter (mêmes courbes)."""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracklab_qt.core import Core


class FakeUi:
    def __init__(self): self.log = []
    def single_shot(self, ms, fn): self.log.append(("after", ms))
    def process_events(self): pass
    def __getattr__(self, name):
        def f(*a, **k): self.log.append((name, a))
        return f


class Dlg:
    def __getattr__(self, name):
        def f(*a, **k): print("DLG", name, a); return True
        return f


def main(path):
    ui = FakeUi(); c = Core(ui, Dlg())
    t0 = time.time(); c.load(path); dt = time.time() - t0
    print("chargé en %.1f s : %d trames, %d signaux, sel %d" % (dt, len(c.frames), len(c.full_t), len(c.sel)))
    assert c.frames and c.full_t
    c.seek(0.5)
    assert c.vals, "valeurs au curseur vides"
    c.apply_model("rsv4")
    print("OK : cœur Qt")
    return c


if __name__ == "__main__":
    main(sys.argv[1])
