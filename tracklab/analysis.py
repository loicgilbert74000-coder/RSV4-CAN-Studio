"""Analyse d'une session GPS : tours, secteurs, virages, écart entre deux tours, voies calculées, export.

Tout est en numpy pur (aucune dépendance à l'interface) : les fonctions reçoivent des tableaux, pas des widgets.
"""

import ast
import csv
import math
import re

import numpy as np

B_SUFFIX = " [B]"


# ------------------------------------------------------------------ session
class Session:
    """Une session (A ou B) sur une base de temps commune : t en secondes, vitesse en km/h, G, angle, tour, distance."""

    def __init__(self, t, speed, glat, glong, angle, lap, lap_starts, lap_nums, lat=None, lon=None):
        self.t = np.asarray(t, float)
        self.speed = np.asarray(speed, float)
        self.glat = glat
        self.glong = glong
        self.angle = angle
        self.lap = np.asarray(lap, int)
        self.lap_starts = np.asarray(lap_starts, float)  # secondes
        self.lap_nums = list(lap_nums)
        dt = np.diff(self.t, prepend=self.t[0] if len(self.t) else 0.0)
        self.dist = np.cumsum(np.nan_to_num(self.speed) / 3.6 * dt)  # mètres depuis le début
        self.lat, self.lon = lat, lon

    @property
    def n(self):
        return len(self.t)

    def runs(self):
        """Tours = suites contiguës d'échantillons de même numéro : [(numéro, i0, i1)] (i1 exclu)."""
        out = []
        if not self.n:
            return out
        a = 0
        for i in range(1, self.n + 1):
            if i == self.n or self.lap[i] != self.lap[a]:
                out.append((int(self.lap[a]), a, i))
                a = i
        return out


def _interp(t_src, v_src, t_dst):
    t_src, v_src = np.asarray(t_src, float), np.asarray(v_src, float)
    ok = ~np.isnan(v_src)
    if ok.sum() < 2:
        return None
    return np.interp(t_dst, t_src[ok], v_src[ok])


def build_session(get, suffix="", lap_table=None):
    """get(nom) -> (temps en ms, valeurs) ou None ; suffix « [B] » pour la 2e session.
    lap_table : ([débuts en ms], [numéros]) ou None."""
    sp = get("GPS Vitesse" + suffix)
    if sp is None or len(sp[0]) < 5:
        return None
    t_ms = np.asarray(sp[0], float)
    speed = np.asarray(sp[1], float)
    ok = ~np.isnan(speed)
    t_ms, speed = t_ms[ok], speed[ok]
    t = t_ms / 1000.0

    def chan(*names):
        for n in names:
            r = get(n + suffix)
            if r is not None and len(r[0]) > 3:
                v = _interp(np.asarray(r[0], float) / 1000.0, r[1], t)
                if v is not None:
                    return v
        return None

    glat = chan("G latéral", "G latéral (calculé)")
    glong = chan("G longitudinal", "G longitudinal (calculé)")
    angle = chan("Angle", "Angle (calculé)")
    if lap_table:
        starts = np.asarray(lap_table[0], float) / 1000.0
        nums = list(lap_table[1])
        idx = np.clip(np.searchsorted(starts, t, side="right") - 1, 0, max(0, len(nums) - 1))
        lap = np.asarray(nums)[idx] if nums else np.zeros(len(t), int)
    else:
        starts, nums, lap = np.array([]), [], np.zeros(len(t), int)
    return Session(t, speed, glat, glong, angle, lap, starts, nums)


# ------------------------------------------------------------------ tours
def fmt_time(sec):
    if sec is None or sec != sec:
        return "—"
    m = int(sec // 60)
    return f"{m}:{sec - 60 * m:06.3f}"


def lap_stats(S):
    """Un dict par tour : numéro, durée, complet (début et fin connus), valide, vitesses, G max."""
    rows = []
    runs = S.runs()
    for k, (num, a, b) in enumerate(runs):
        t0 = S.lap_starts[k] if len(S.lap_starts) == len(runs) else S.t[a]
        nxt = None
        if k + 1 < len(runs):
            nxt = S.t[runs[k + 1][1]]
        # un tour est complet s'il est précédé et suivi d'un autre tour
        complete = k > 0 and nxt is not None
        t_end = nxt if nxt is not None else S.t[b - 1]
        dur = t_end - (S.t[a] if k == 0 else t0)
        seg = slice(a, b)
        sp = S.speed[seg]
        rows.append({
            "num": num, "i0": a, "i1": b, "t0": float(S.t[a]), "time": float(dur), "complete": complete,
            "vmax": float(np.nanmax(sp)), "vmin": float(np.nanmin(sp)), "vmean": float(np.nanmean(sp)),
            "glat": float(np.nanmax(np.abs(S.glat[seg]))) if S.glat is not None else None,
            "glong_acc": float(np.nanmax(S.glong[seg])) if S.glong is not None else None,
            "glong_brk": float(-np.nanmin(S.glong[seg])) if S.glong is not None else None,
            "angle": float(np.nanmax(np.abs(S.angle[seg]))) if S.angle is not None else None,
        })
    comp = [r["time"] for r in rows if r["complete"]]
    med = float(np.median(comp)) if comp else None
    for r in rows:
        # tour de sortie / rentrée des stands ou tour coupé : trop long ou trop court par rapport à la médiane
        r["valid"] = bool(r["complete"] and med and 0.8 * med <= r["time"] <= 1.25 * med)
    return rows


def best_lap(rows):
    v = [r for r in rows if r["valid"]]
    return min(v, key=lambda r: r["time"]) if v else None


def _lap_axis(S, row):
    """Distance parcourue depuis le début du tour (m) et temps (s) pour un tour."""
    sl = slice(row["i0"], row["i1"])
    d = S.dist[sl] - S.dist[row["i0"]]
    t = S.t[sl] - S.t[row["i0"]]
    return d, t


def sector_times(S, rows, n_sectors=3):
    """Temps de chaque secteur (découpage en tronçons de même distance, d'après le meilleur tour) pour les tours valides.
    Retourne ({numéro: [temps secteur]}, [meilleur de chaque secteur], tour théorique)."""
    best = best_lap(rows)
    if not best:
        return {}, [], None
    db, _tb = _lap_axis(S, best)
    total = db[-1] or 1.0
    out = {}
    for r in rows:
        if not r["valid"]:
            continue
        d, t = _lap_axis(S, r)
        if d[-1] <= 0:
            continue
        frac = d / d[-1]
        cuts = np.interp(np.linspace(0, 1, n_sectors + 1), frac, t)
        cuts[-1] = r["time"]
        out[r["num"]] = list(np.diff(cuts))
    if not out:
        return {}, [], None
    mins = [min(v[i] for v in out.values()) for i in range(n_sectors)]
    return out, mins, float(sum(mins))


# ------------------------------------------------------------------ écart de temps
def delta_curve(Sa, ra, Sb, rb, points=400):
    """Écart de temps B - A (s) le long du tour, à même distance relative : positif = B plus lent à cet endroit.
    Retourne (distance en m selon A, écart en s)."""
    da, ta = _lap_axis(Sa, ra)
    db, tb = _lap_axis(Sb, rb)
    if da[-1] <= 0 or db[-1] <= 0:
        return np.array([]), np.array([])
    x = np.linspace(0, 1, points)
    tA = np.interp(x, da / da[-1], ta)
    tB = np.interp(x, db / db[-1], tb)
    return x * da[-1], tB - tA


# ------------------------------------------------------------------ virages
def detect_corners(S, row, g_min=0.30, v_min=30.0, gap_s=0.6, min_s=0.8):
    """Virages d'un tour : segments où le G latéral dépasse g_min. Pour chacun : vitesses d'entrée / point de corde / sortie."""
    if S.glat is None:
        return []
    sl = slice(row["i0"], row["i1"])
    g = np.abs(np.nan_to_num(S.glat[sl]))
    t = S.t[sl]
    sp = S.speed[sl]
    on = (g >= g_min) & (sp >= v_min)
    segs = []
    i, n = 0, len(g)
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1]:
                j += 1
            segs.append([i, j])
            i = j + 1
        else:
            i += 1
    merged = []
    for s in segs:  # deux segments très proches (même sens) = un seul virage
        if merged and t[s[0]] - t[merged[-1][1]] < gap_s and np.sign(np.mean(S.glat[sl][s[0]:s[1] + 1])) == merged[-1][2]:
            merged[-1][1] = s[1]
        else:
            merged.append([s[0], s[1], float(np.sign(np.mean(S.glat[sl][s[0]:s[1] + 1])))])
    d0 = S.dist[row["i0"]]
    out = []
    for a, b, sg in merged:
        if t[b] - t[a] < min_s:
            continue
        seg_sp = sp[a:b + 1]
        k = a + int(np.argmin(seg_sp))
        out.append({
            "n": len(out) + 1,
            "side": "droite" if sg > 0 else "gauche",
            "dist": float(S.dist[row["i0"] + a] - d0),
            "t_in": float(t[a] - t[0]),
            "dur": float(t[b] - t[a]),
            "v_in": float(sp[a]),
            "v_apex": float(sp[k]),
            "v_out": float(sp[b]),
            "g_max": float(np.max(g[a:b + 1])),
            "angle": float(np.nanmax(np.abs(S.angle[sl][a:b + 1]))) if S.angle is not None else None,
            "brake_g": float(-np.nanmin(S.glong[sl][max(0, a - 40):a + 1])) if S.glong is not None else None,
        })
    return out


def compare_corners(ca, cb, tol_m=60.0):
    """Appaire les virages de deux tours d'après leur distance dans le tour : [(virage A, virage B ou None)]."""
    out, used = [], set()
    for a in ca:
        best, bd = None, tol_m
        for k, b in enumerate(cb):
            if k in used:
                continue
            d = abs(a["dist"] - b["dist"])
            if d < bd:
                best, bd = k, d
        if best is not None:
            used.add(best)
        out.append((a, cb[best] if best is not None else None))
    return out


# ------------------------------------------------------------------ G-G
def gg_points(S, row=None):
    if S.glat is None or S.glong is None:
        return np.array([]), np.array([])
    sl = slice(row["i0"], row["i1"]) if row else slice(None)
    return S.glat[sl], S.glong[sl]


# ------------------------------------------------------------------ voies calculées
_FUNCS = {
    "abs": np.abs, "sqrt": np.sqrt, "sin": lambda x: np.sin(np.radians(x)), "cos": lambda x: np.cos(np.radians(x)),
    "tan": lambda x: np.tan(np.radians(x)), "atan": lambda x: np.degrees(np.arctan(x)), "log": np.log,
    "min": np.minimum, "max": np.maximum, "sign": np.sign,
}
_OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide, ast.Pow: np.power,
        ast.Mod: np.mod}


def deriv(t, v):
    return np.gradient(v, t)


def smooth(v, n):
    n = max(1, int(n))
    if n <= 1:
        return v
    k = np.ones(n) / n
    pad = np.pad(v, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


def eval_formula(expr, signals, t):
    """Évalue une formule : [GPS Vitesse] * 2, abs([G latéral]), deriv([GPS Vitesse]) / 3.6 / 9.81, smooth([Angle], 5)…
    signals : {nom: tableau} sur la base de temps t (secondes). Retourne un tableau. Seules les opérations
    arithmétiques, les fonctions ci-dessus et les voies entre crochets sont acceptées."""
    names = {}

    def sub(m):
        nm = m.group(1)
        if nm not in signals:
            raise ValueError(f"voie inconnue : {nm}")
        var = f"v{len(names)}"
        names[var] = signals[nm]
        return var

    src = re.sub(r"\[([^\]]+)\]", sub, expr)
    tree = ast.parse(src.strip(), mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in names:
                return names[node.id]
            if node.id == "g":
                return 9.81
            if node.id == "pi":
                return math.pi
            raise ValueError(f"nom inconnu : {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            f = node.func.id
            a = [ev(x) for x in node.args]
            if f == "deriv" and len(a) == 1:
                return deriv(t, np.asarray(a[0], float) * np.ones(len(t)))
            if f == "smooth" and len(a) == 2:
                return smooth(np.asarray(a[0], float) * np.ones(len(t)), a[1])
            if f in _FUNCS:
                return _FUNCS[f](*a)
        raise ValueError("formule non autorisée")

    out = ev(tree)
    out = np.asarray(out, float) * np.ones(len(t))
    return out


# ------------------------------------------------------------------ export
def export_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


def lap_rows_for_export(rows, sectors=None):
    out = []
    for r in rows:
        line = [r["num"], f"{r['time']:.3f}", "oui" if r["valid"] else "non", f"{r['vmax']:.1f}", f"{r['vmean']:.1f}"]
        if sectors:
            line += [f"{x:.3f}" for x in sectors.get(r["num"], [])]
        out.append(line)
    return out
