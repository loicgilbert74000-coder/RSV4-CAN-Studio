#!/usr/bin/env python3
"""Boîtier GPS TrackLab : génère les fichiers STL (coque + fond) et des images d'aperçu.

Aucune bibliothèque 3D n'est nécessaire (numpy, scipy, Pillow) : les formes sont décrites par des champs de distance
puis maillées par tétraèdres marchants. Toutes les cotes sont en millimètres ; modifier la section « PARAMÈTRES ».

Repère : z = 0 est le plan de contact entre la coque et le fond. La coque est au-dessus (z > 0), le fond en dessous.
Usage : python3 generer_boitier.py [dossier_sortie] [pas_de_maillage_mm]
"""

import math
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

# ------------------------------------------------------------------ PARAMÈTRES (mm)
PCB_L, PCB_W, PCB_T = 36.0, 25.0, 1.6      # carte GY-GPSV3 (NEO-M9N, Lobamop) : 36 × 25 mm, 4 trous Ø 3 mm
ANT = 25.0                                  # antenne céramique carrée : côté
ANT_H = 4.0                                 # et épaisseur
WALL = 2.4                                  # épaisseur des parois latérales
TOP = 2.0                                   # épaisseur du dessus (sous la gravure)
POST_H = 3.0                                # hauteur des plots sous la carte (soudures)
GAP_COMP = 3.5                              # espace au-dessus de la carte pour les composants
GAP_ANT = 0.2                               # jeu entre l'antenne et le dessus
H_IN = POST_H + PCB_T + GAP_COMP + ANT_H + GAP_ANT   # hauteur intérieure (12,3 -> arrondie ci-dessous)
H_IN = math.ceil(H_IN * 2) / 2
H = H_IN + TOP                              # hauteur de la coque
IX, IY = 26.0, 15.5                         # demi-dimensions intérieures (8 mm libres de chaque côté de la carte pour les vis)
OX, OY = IX + WALL, IY + WALL               # demi-dimensions extérieures
RC = 8.0                                    # rayon des angles verticaux (extérieur)
FIL = 4.0                                   # rayon d'arrondi du dessus
PCB_CX = 0.0                                # centre de la carte et de l'antenne en x
FOND_T = 4.5                                # épaisseur du fond
BOSS_X, BOSS_Y, BOSS_R = 22.5, 7.5, 3.2     # colonnes de vissage M3 à l'intérieur de la coque
SCREW_INS_D, SCREW_INS_DEPTH = 4.2, 6.5     # trou d'insert à chaud M3 (en haut des colonnes)
GROOVE_W, GROOVE_D = 2.4, 1.5               # gorge du joint sous la paroi (cordon silicone Ø 2 mm ou joint TPU imprimé)
NOZ_D, NOZ_HOLE, NOZ_Z, NOZ_LEN = 9.6, 5.2, 5.5, 8.0  # goulot de sortie du câble
TEXT = "TRACKLAB GPS"
TEXT_H, TEXT_DEPTH = 5.2, 0.6
TEXT_W_MAX = 40.0                           # largeur maximale de la gravure (le dessus plat fait 48 × 28)               # hauteur des capitales et profondeur de gravure
FONT = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"


# ------------------------------------------------------------------ champs de distance
def box2(x, y, hx, hy, r):
    """Rectangle arrondi 2D (négatif à l'intérieur)."""
    qx, qy = np.abs(x) - (hx - r), np.abs(y) - (hy - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def prism(d2, z, z0, z1, f0=0.0, f1=0.0):
    """Extrusion de la forme 2D `d2` entre z0 et z1, arêtes arrondies de f0 (bas) et f1 (haut) ; f0 et f1 sont soit nuls, soit égaux."""
    f = max(f0, f1)
    a = d2 + f
    zq = np.maximum((z0 + f0) - z, z - (z1 - f1))
    return np.hypot(np.maximum(a, 0), np.maximum(zq, 0)) + np.minimum(np.maximum(a, zq), 0) - f


def cyl_x(x, y, z, y0, z0, r, x0, x1, f=0.0):
    """Cylindre d'axe x (centre y0, z0, rayon r) entre x0 et x1, bord extérieur arrondi de f en x1."""
    rr = np.hypot(y - y0, z - z0)
    a = rr - (r - f)
    xq = np.maximum(x0 - x, x - (x1 - f))
    return np.hypot(np.maximum(a, 0), np.maximum(xq, 0)) + np.minimum(np.maximum(a, xq), 0) - f


def cyl_z(x, y, z, cx, cy, r, z0, z1):
    a = np.hypot(x - cx, y - cy) - r
    zq = np.maximum(z0 - z, z - z1)
    return np.hypot(np.maximum(a, 0), np.maximum(zq, 0)) + np.minimum(np.maximum(a, zq), 0)


def rect3(x, y, z, x0, x1, y0, y1, z0, z1):
    q = np.stack(np.broadcast_arrays(np.maximum(x0 - x, x - x1), np.maximum(y0 - y, y - y1), np.maximum(z0 - z, z - z1)))
    return np.linalg.norm(np.maximum(q, 0), axis=0) + np.minimum(q.max(axis=0), 0)


def smin(a, b, k):
    h = np.maximum(k - np.abs(a - b), 0) / k
    return np.minimum(a, b) - h * h * k / 4


def union(*ds):
    out = ds[0]
    for d in ds[1:]:
        out = np.minimum(out, d)
    return out


def diff(a, *bs):
    for b in bs:
        a = np.maximum(a, -b)
    return a


def text_mask(res=0.05):
    """Gravure : champ de distance 2D de TRACKLAB GPS, centré en (0, 0) ; renvoie (sdf, x0, y0, pas)."""
    px = 20  # pixels par mm
    size = 40
    font = ImageFont.truetype(FONT, int(TEXT_H * px / 0.7))
    # hauteur de capitale mesurée sur la police pour obtenir TEXT_H exact
    cap = font.getbbox("H")
    scale = TEXT_H * px / (cap[3] - cap[1])
    font = ImageFont.truetype(FONT, int(round(font.size * scale)))
    bb = font.getbbox(TEXT)
    if (bb[2] - bb[0]) / px > TEXT_W_MAX:  # trop large pour le dessus plat : on réduit la taille des lettres
        font = ImageFont.truetype(FONT, int(font.size * TEXT_W_MAX * px / (bb[2] - bb[0])))
        bb = font.getbbox(TEXT)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    img = Image.new("L", (int(size * px * 1.6), int(12 * px)), 0)
    ImageDraw.Draw(img).text(((img.width - w) // 2 - bb[0], (img.height - h) // 2 - bb[1]), TEXT, font=font, fill=255)
    m = np.array(img) > 127
    out = ndimage.distance_transform_edt(~m)
    ins = ndimage.distance_transform_edt(m)
    sdf = (out - ins) / px  # négatif dans les lettres
    return sdf.astype(np.float32), img.width / px, img.height / px, 1.0 / px, w / px


# ------------------------------------------------------------------ maillage : tétraèdres marchants
def mesh(f, lo, hi, h):
    """Maille f(x, y, z) < 0 sur la boîte [lo, hi] avec un pas h ; renvoie les triangles (n, 3, 3), normales vers l'extérieur."""
    # grille légèrement décalée : aucun nœud ne tombe exactement sur une face plane du modèle
    xs = np.arange(lo[0] + 0.0137, hi[0] + h, h, dtype=np.float32)
    ys = np.arange(lo[1] + 0.0291, hi[1] + h, h, dtype=np.float32)
    zs = np.arange(lo[2] + 0.0173, hi[2] + h, h, dtype=np.float32)
    nx, ny, nz = len(xs), len(ys), len(zs)
    V = f(xs[:, None, None], ys[None, :, None], zs[None, None, :]).astype(np.float32)
    V = np.broadcast_to(V, (nx, ny, nz))
    # numéro de chaque sommet : sert à orienter l'arête de la même façon dans tous les tétraèdres voisins
    ids = np.arange(nx * ny * nz, dtype=np.int64).reshape(nx, ny, nz)
    perms = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
    tris = []
    step = 24
    for i0 in range(0, nx - 1, step):
        i1 = min(nx - 1, i0 + step)
        sl = (slice(i0, i1), slice(0, ny - 1), slice(0, nz - 1))
        for perm in perms:
            offs = [(0, 0, 0)]
            cur = [0, 0, 0]
            for ax in perm[:2]:
                cur[ax] = 1
                offs.append(tuple(cur))
            offs.append((1, 1, 1))
            P, D, I = [], [], []
            for o in offs:
                s = (slice(i0 + o[0], i1 + o[0]), slice(o[1], ny - 1 + o[1]), slice(o[2], nz - 1 + o[2]))
                d = V[s]
                D.append(d)
                I.append(ids[s])
                gx, gy, gz = np.meshgrid(xs[s[0]], ys[s[1]], zs[s[2]], indexing="ij")
                P.append(np.stack([gx, gy, gz], -1))
            S = [d < 0 for d in D]
            cnt = S[0].astype(np.int8) + S[1] + S[2] + S[3]
            act = (cnt > 0) & (cnt < 4)
            if not act.any():
                continue
            Pa = [p[act] for p in P]
            Da = [d[act] for d in D]
            Ia = [i[act] for i in I]
            Sa = [s[act] for s in S]
            ca = cnt[act]

            def edge(a, b, sel):
                da, db = Da[a][sel], Da[b][sel]
                pa, pb = Pa[a][sel], Pa[b][sel]
                ia, ib = Ia[a][sel], Ia[b][sel]
                swap = ia > ib
                da, db = np.where(swap, db, da), np.where(swap, da, db)
                pa, pb = np.where(swap[:, None], pb, pa), np.where(swap[:, None], pa, pb)
                t = (da / (da - db))[:, None]
                return pa + t * (pb - pa)

            def emit(p, q, r, ref, sel):
                n = np.cross(q - p, r - p)
                flip = (n * ref).sum(1) < 0
                q2 = np.where(flip[:, None], r, q)
                r2 = np.where(flip[:, None], q, r)
                tris.append(np.stack([p, q2, r2], 1))

            for a in range(4):  # un seul sommet dedans
                sel = (ca == 1) & Sa[a]
                if sel.any():
                    others = [b for b in range(4) if b != a]
                    e = [edge(a, b, sel) for b in others]
                    ref = sum(Pa[b][sel] for b in others) / 3 - Pa[a][sel]
                    emit(e[0], e[1], e[2], ref, sel)
            for a in range(4):  # un seul sommet dehors
                sel = (ca == 3) & ~Sa[a]
                if sel.any():
                    others = [b for b in range(4) if b != a]
                    e = [edge(a, b, sel) for b in others]
                    ref = Pa[a][sel] - sum(Pa[b][sel] for b in others) / 3
                    emit(e[0], e[1], e[2], ref, sel)
            for a in range(4):  # deux dedans, deux dehors
                for b in range(a + 1, 4):
                    c, d_ = [k for k in range(4) if k not in (a, b)]
                    sel = (ca == 2) & Sa[a] & Sa[b]
                    if sel.any():
                        ac, ad, bd, bc = edge(a, c, sel), edge(a, d_, sel), edge(b, d_, sel), edge(b, c, sel)
                        ref = (Pa[c][sel] + Pa[d_][sel]) / 2 - (Pa[a][sel] + Pa[b][sel]) / 2
                        emit(ac, ad, bd, ref, sel)
                        emit(ac, bd, bc, ref, sel)
    m = np.concatenate(tris) if tris else np.zeros((0, 3, 3), np.float32)
    # triangles dont deux sommets coïncident exactement : surface nulle, on les retire sans créer de trou
    same = (m[:, 0] == m[:, 1]).all(1) | (m[:, 1] == m[:, 2]).all(1) | (m[:, 0] == m[:, 2]).all(1)
    return m[~same]


def write_stl(path, tris, name="TrackLab"):
    t = tris.astype(np.float32)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 0, n / np.maximum(ln, 1e-12), 0).astype(np.float32)
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, t
    with open(path, "wb") as f:
        f.write(name.encode().ljust(80, b" "))
        f.write(struct.pack("<I", len(t)))
        f.write(rec.tobytes())


def check(tris):
    """Volume (mm³) et nombre d'arêtes non partagées par exactement deux triangles (0 = maillage étanche)."""
    t = tris.astype(np.float64)
    vol = np.einsum("ij,ij->", t[:, 0], np.cross(t[:, 1], t[:, 2])) / 6
    q = np.ascontiguousarray(tris.astype(np.float32)).reshape(-1, 3).view(np.int32)  # soudure exacte des sommets
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    inv = inv.reshape(-1, 3)
    e = np.concatenate([inv[:, [0, 1]], inv[:, [1, 2]], inv[:, [2, 0]]])
    e = np.sort(e, axis=1)
    _, c = np.unique(e, axis=0, return_counts=True)
    return vol, int((c != 2).sum()), int(len(c))


# ------------------------------------------------------------------ pièces
def shell_sdf(txt):
    sdf, tw, th, tp, _ = txt

    def f(x, y, z):
        d_out2 = box2(x, y, OX, OY, RC)
        outer = prism(d_out2, z, 0.0, H, 0.0, FIL)
        outer = np.maximum(outer, -z)  # base nette sur le plan de contact
        body = outer
        # goulot de câble (côté +x)
        noz = cyl_x(x, y, z, 0.0, NOZ_Z, NOZ_D / 2, OX - 3.0, OX + NOZ_LEN, 1.2)
        body = smin(body, noz, 1.5)
        # cavité
        cav2 = box2(x, y, IX, IY, RC - WALL)
        cav = prism(cav2, z, -1.0, H_IN, 0.0, 1.0)
        # corps plein sans les oreilles intérieures : on évide la cavité
        d = np.maximum(np.maximum(body, -cav), -z)  # rien sous le plan de contact
        # colonnes de vissage : cylindre + voile vers la paroi, du dessus jusqu'au plan de contact
        for sx in (-1, 1):
            for sy in (-1, 1):
                col = cyl_z(x, y, z, sx * BOSS_X, sy * BOSS_Y, BOSS_R, 0.0, H_IN + 0.5)
                web = rect3(x, y, z, min(sx * BOSS_X, sx * (IX + 0.5)), max(sx * BOSS_X, sx * (IX + 0.5)),
                            sy * BOSS_Y - BOSS_R, sy * BOSS_Y + BOSS_R, 0.0, H_IN + 0.5)
                d = np.minimum(d, np.minimum(col, web))
        # plots de verrouillage de l'antenne, suspendus sous le dessus
        ax = PCB_CX
        for sx in (-1, 1):
            for sy in (-1, 1):
                blk = rect3(x, y, z, ax + sx * (ANT / 2 + 0.3) - 1.3 + (0 if sx > 0 else 0), ax + sx * (ANT / 2 + 0.3) + 1.3,
                            sy * (ANT / 2 + 0.3) - 1.3, sy * (ANT / 2 + 0.3) + 1.3, H_IN - 5.0, H_IN + 0.5)
                d = np.minimum(d, blk)
        # trous d'insert M3 en bas des colonnes
        for sx in (-1, 1):
            for sy in (-1, 1):
                d = np.maximum(d, -cyl_z(x, y, z, sx * BOSS_X, sy * BOSS_Y, SCREW_INS_D / 2, -1.0, SCREW_INS_DEPTH))
        # passage du câble
        hole = cyl_x(x, y, z, 0.0, NOZ_Z, NOZ_HOLE / 2, IX - 4.0, OX + NOZ_LEN + 1.0, 0.0)
        d = np.maximum(d, -hole)
        # gorge du collier / de la gaine thermorétractable
        gr = np.maximum(np.abs(x - (OX + NOZ_LEN - 2.5)) - 0.8, -(np.hypot(y, z - NOZ_Z) - (NOZ_D / 2 - 0.7)))
        d = np.maximum(d, -gr)
        # gravure
        if txt is not None:
            u = (x / 1.0 + tw / 2) / tp
            v = (th / 2 - y) / tp
            ii = np.clip(np.rint(v).astype(np.int64), 0, sdf.shape[0] - 1)
            jj = np.clip(np.rint(u).astype(np.int64), 0, sdf.shape[1] - 1)
            t2 = sdf[ii, jj]
            pocket = np.maximum(t2, (H - TEXT_DEPTH) - z)
            d = np.maximum(d, -pocket)
        return d

    return f


def plate_sdf():
    def f(x, y, z):
        body2 = box2(x, y, OX, OY, RC)
        d = prism(body2, z, -FOND_T, 0.0, 1.2, 1.2)
        # gorge du joint, sous le milieu de la paroi
        wall_mid = np.abs(body2 + WALL / 2) - GROOVE_W / 2
        gz = np.maximum(-GROOVE_D - z, z - 1.0)       # négatif pour z dans [-GROOVE_D, 1]
        groove = np.maximum(wall_mid, gz)
        d = np.maximum(d, -groove)
        # vis M3 par le dessous : passage Ø 3,4 et lamage Ø 6 pour la tête (le ruban double face recouvre le tout)
        for sx in (-1, 1):
            for sy in (-1, 1):
                d = np.maximum(d, -cyl_z(x, y, z, sx * BOSS_X, sy * BOSS_Y, 1.7, -FOND_T - 1.0, 1.0))
                d = np.maximum(d, -cyl_z(x, y, z, sx * BOSS_X, sy * BOSS_Y, 3.0, -FOND_T - 1.0, -FOND_T + 2.5))
        # plots sous la carte et cales d'angle
        px, hw, hl = PCB_CX, PCB_L / 2, PCB_W / 2
        for sx in (-1, 1):
            for sy in (-1, 1):
                post = cyl_z(x, y, z, px + sx * (hw - 3.0), sy * (hl - 3.0), 2.6, -0.2, POST_H)
                d = np.minimum(d, post)
                cx_, cy_ = px + sx * (hw + 0.3), sy * (hl + 0.3)
                zt = POST_H + PCB_T + 0.6
                xa, xb = sorted((cx_ - sx * 3.0, cx_ + sx * 1.2))
                ya, yb = sorted((cy_, cy_ + sy * 1.2))
                d = np.minimum(d, rect3(x, y, z, xa, xb, ya, yb, -0.2, zt))
                xa, xb = sorted((cx_, cx_ + sx * 1.2))
                ya, yb = sorted((cy_ - sy * 3.0, cy_ + sy * 1.2))
                d = np.minimum(d, rect3(x, y, z, xa, xb, ya, yb, -0.2, zt))
        return d

    return f


# ------------------------------------------------------------------ aperçu (rasteriseur simple)
def render(parts, path, view=(35, -28), size=(1400, 900), cut=False):
    """parts : liste de (triangles, couleur RGB). Projection orthographique, tri par profondeur, éclairage simple."""
    ay, az = math.radians(view[0]), math.radians(view[1])
    Rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(ay), -math.sin(ay)], [0, math.sin(ay), math.cos(ay)]])
    R = Rx @ Rz
    items = []
    for tri, col in parts:
        t = tri @ R.T
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        items.append((t, n, col))
    allv = np.concatenate([t.reshape(-1, 3) for t, _, _ in items])
    mn, mx = allv.min(0), allv.max(0)
    sc = 0.9 * min(size[0] / (mx[0] - mn[0]), size[1] / (mx[1] - mn[1]))
    ox = size[0] / 2 - sc * (mn[0] + mx[0]) / 2
    oy = size[1] / 2 + sc * (mn[1] + mx[1]) / 2
    img = Image.new("RGB", (size[0] * 2, size[1] * 2), (244, 245, 242))
    dr = ImageDraw.Draw(img)
    polys = []
    light = np.array([-0.35, 0.45, 0.82])
    light /= np.linalg.norm(light)
    for t, n, col in items:
        depth = t[:, :, 2].mean(1)
        vis = n[:, 2] > -0.05
        shade = np.clip(0.28 + 0.72 * np.clip(n @ light, 0, 1), 0, 1)
        for k in np.nonzero(vis)[0]:
            polys.append((depth[k], k, t, shade[k], col))
    polys.sort(key=lambda p: p[0])
    for _, k, t, s, col in polys:
        pts = [((sc * v[0] + ox) * 2, (oy - sc * v[1]) * 2) for v in t[k]]
        c = tuple(int(ch * s) for ch in col)
        dr.polygon(pts, fill=c)
    img = img.resize(size, Image.LANCZOS)
    img.save(path)


def slice_y(tri, y0=0.0):
    """Garde les triangles du côté y >= y0 (aperçu en coupe)."""
    keep = tri[:, :, 1].mean(1) >= y0
    return tri[keep]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    h = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
    os.makedirs(out, exist_ok=True)
    txt = text_mask()
    print(f"hauteur intérieure {H_IN} mm, hauteur de coque {H} mm, boîtier {2 * OX:.1f} × {2 * OY:.1f} mm, goulot jusqu'à x = {OX + NOZ_LEN:.1f}")
    shell_lo, shell_hi = (-OX - 3, -OY - 3, -0.6), (OX + NOZ_LEN + 1.0, OY + 3, H + 0.6)
    plate_lo, plate_hi = (-OX - 3, -OY - 3, -FOND_T - 0.6), (OX + 3, OY + 3, POST_H + PCB_T + 1.8)
    shell = mesh(shell_sdf(txt), shell_lo, shell_hi, h)
    plate = mesh(plate_sdf(), plate_lo, plate_hi, h)
    for name, m in (("coque", shell), ("fond", plate)):
        vol, bad, ne = check(m)
        print(f"{name} : {len(m)} triangles, volume {vol / 1000:.2f} cm³, arêtes non fermées : {bad}/{ne}")
    # orientation d'impression : coque face du dessus sur le plateau, fond à plat
    s_print = shell.copy()
    s_print[:, :, 2] = H - s_print[:, :, 2]
    s_print[:, :, 0] = -s_print[:, :, 0]  # retournement de 180° autour de y (rotation propre)
    p_print = plate.copy()
    p_print[:, :, 2] += FOND_T
    write_stl(os.path.join(out, "Boitier_GPS_coque.stl"), s_print)
    write_stl(os.path.join(out, "Boitier_GPS_fond.stl"), p_print)
    np.save(os.path.join(out, "_shell.npy"), shell)
    np.save(os.path.join(out, "_plate.npy"), plate)


if __name__ == "__main__":
    main()
