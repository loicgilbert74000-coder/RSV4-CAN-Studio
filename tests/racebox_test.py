"""Export « RaceBox Track Session » (Record,Time,Latitude,Longitude,Altitude,KPH,X,Z,Lap,LeanAngle,Gyro…) : vitesse et cap raccordés."""
import os, struct, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tracklab import formats

rows = ["Record,Time,Latitude,Longitude,Altitude,KPH,X,Z,Lap,LeanAngle,GyroX,GyroY,GyroZ"]
for i in range(60):
    rows.append(f"{i+1},{i*0.04:.3f},{48.32 + i*0.0001:.7f},{6.07 + i*0.0001:.7f},334.3,{50+i},0.1,0.99,0,{i/10:.1f},0.3,0.4,0.5")
p = os.path.join(tempfile.mkdtemp(), "RaceBox_Track_Session.csv")
open(p, "w").write("\n".join(rows) + "\n")
r = formats.load_any(p)
assert r.label.startswith("RaceBox") or r.kind in ("racebox", "gpscsv"), r.kind
names = [c[0] for v in r.dyn.values() for c in v if c]
assert "KPH" not in names and "X" in names and "LeanAngle" in names, names
mot = [struct.unpack("<HHBB", f[2]) for f in r.frames if f[1] == formats.ID_GPS_MOT]
assert mot and mot[10][0] == 6000, mot[10]  # 60 km/h
assert any(m[1] for m in mot), "cap calculé"
print("OK : RaceBox")
