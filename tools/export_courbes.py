"""Décode une capture avec l'application actuelle et exporte les courbes (zip) pour le prototype Qt.
Usage : python3 tools/export_courbes.py capture.trk sortie.npz   (nécessite un affichage, p. ex. Xvfb)"""
import json, sys, time, zipfile
from array import array
sys.path.insert(0, __file__.rsplit("/", 2)[0])
from tracklab.app import App

app = App()
def pump(t):
    e = time.time() + t
    while time.time() < e:
        app.root.update(); time.sleep(0.01)
pump(0.4); app.load(sys.argv[1])
while app.loading or not app.full_t:
    pump(0.2)
pump(0.5)
meta = []
zf = zipfile.ZipFile(sys.argv[2], "w", zipfile.ZIP_DEFLATED, compresslevel=9)
for k in sorted(app.full_t, key=lambda k: -len(app.full_t[k])):
    t, v = app.full_t[k], app.full_v[k]
    if len(t) < 50: continue
    n = len(meta)
    zf.writestr(f"t{n}.bin", array("d", t).tobytes()); zf.writestr(f"v{n}.bin", array("f", v).tobytes())
    meta.append({"label": app.label_of(k), "unit": app.unit_of(k), "color": app.color_of(k)})
zf.writestr("meta.json", json.dumps(meta)); zf.close()
print(len(meta), "signaux exportés")
app.root.destroy()
