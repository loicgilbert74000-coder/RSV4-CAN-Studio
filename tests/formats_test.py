"""Ouverture de fichiers de types différents : reconnaissance automatique + chargement dans l'appli (fichiers synthétiques)."""
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracklab.formats import detect, load_any


def make_racebox(path):
    rows = ["Record,Time,Latitude,Longitude,Altitude,Speed,GForceX,GForceY,GForceZ,Lap,GyroX,GyroY,GyroZ,NumSats,Fix status"]
    for i in range(600):
        t = i * 0.04
        la = 45.0 + 0.002 * math.cos(t / 3)
        lo = 6.0 + 0.003 * math.sin(t / 3)
        rows.append(f"{i},2026-10-31T10:00:{t:06.3f}Z,{la:.7f},{lo:.7f},300,{90 + 30 * math.sin(t):.1f},{0.3 * math.sin(t):.3f},{0.8 * math.cos(t):.3f},1.0,1,1,2,3,12,3")
    open(path, "w").write("\n".join(rows))


def make_racechrono(path):
    rows = ["This file is created using RaceChrono v9.1", "Format,3", "", "timestamp,elapsed_time,latitude,longitude,speed,bearing,x_acc,y_acc,rpm", "s,s,deg,deg,m/s,deg,G,G,rpm"]
    for i in range(400):
        t = i * 0.1
        rows.append(f"{1700000000 + t:.2f},{t:.2f},{45 + 0.002 * math.cos(t / 3):.7f},{6 + 0.003 * math.sin(t / 3):.7f},{25 + 8 * math.sin(t):.2f},{(t * 20) % 360:.1f},{0.3 * math.sin(t):.3f},{0.8 * math.cos(t):.3f},{9000 + 2000 * math.sin(t):.0f}")
    open(path, "w").write("\n".join(rows))


def main(shots=None):
    from tracklab.app import App

    d = tempfile.mkdtemp()
    rb, rc = os.path.join(d, "racebox.csv"), os.path.join(d, "racechrono.csv")
    make_racebox(rb)
    make_racechrono(rc)
    assert detect(rb)[0] == "racebox", detect(rb)
    assert detect(rc)[0] == "racechrono", detect(rc)
    bad = os.path.join(d, "x.txt")
    open(bad, "w").write("bonjour\nrien à voir\n")
    assert detect(bad)[0] is None
    for p in (rb, rc):
        r = load_any(p)
        assert r.frames and r.dyn, p
    app = App()
    app.root.update()
    app.load(rb)
    app.root.update()
    keys = [k for k in app.full_t]
    assert len(keys) >= 4, keys
    app.seek(1.0)
    assert app.track, "tracé GPS absent"
    app.load(rc)
    app.root.update()
    app.seek(1.0)
    app.root.update()
    assert any(k[1].lower().startswith("rpm") for k in app.full_t), list(app.full_t)
    assert app.sel and all(k in app.full_t for k in app.sel), app.sel
    print("types :", sorted({app.signal_type(k) for k in app.full_t}))
    if shots:
        app.root.update()
        subprocess.run(["import", "-window", "root", os.path.join(shots, "fichier_racechrono.png")], timeout=30, check=False)
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
