"""Ouverture de fichiers de plusieurs types : détection automatique du contenu, puis conversion en trames.

Types reconnus : capture USB-CAN (TXT), moniteur série du programme de test CAN, enregistrement TrackLab (.trk),
RaceBox (CSV), RaceChrono (CSV v3 et VBO), CSV GPS générique.

Les fichiers GPS (RaceBox, RaceChrono…) sont convertis en trames de l'application : position et vitesse reprennent les
trames GPS de l'ESP32 (0x7F0 et 0x7F8, pour le tracé du circuit) ; toutes les autres colonnes deviennent des « voies »
(trames d'identifiant DYN_BASE et plus, deux valeurs flottantes par trame).
"""

import csv
import io
import math
import os
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime

from .protocol import LINE, SERIAL_LINE, TRK_MAGIC, load_capture

DYN_BASE = 0x1000  # identifiants des voies issues d'un fichier (au-delà des identifiants CAN 11 bits)
ID_GPS_POS = 2032  # 0x7F0 : latitude / longitude (entiers 1e-7 °)
ID_GPS_MOT = 2040  # 0x7F8 : vitesse / cap / satellites / fix

# Types de signaux affichés dans la liste des courbes
TYPE_GPS, TYPE_CAN, TYPE_SENS, TYPE_IMU, TYPE_OTHER = "GPS", "CAN moto", "Capteurs", "Inertiel", "Autres"


@dataclass
class Loaded:
    """Résultat de l'ouverture d'un fichier."""

    kind: str  # identifiant interne du format
    label: str  # nom lisible du format, affiché à l'utilisateur
    frames: list = field(default_factory=list)  # [(ms, id, octets)]
    dyn: dict = field(default_factory=dict)  # {id: [(nom, unité, type), (nom, unité, type) ou None]}
    info: str = ""  # précision (nombre de voies, vitesse convertie…)
    extra: dict = field(default_factory=dict)  # comparaison de deux fichiers : voies de la 2e session


# ---------------------------------------------------------------- lecture et détection
def read_text(path, limit=None):
    """Texte du fichier, quel que soit son encodage courant (UTF-8 avec ou sans BOM, UTF-16, ANSI)."""
    with open(path, "rb") as f:
        raw = f.read() if limit is None else f.read(limit)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin1", errors="replace")


def _split(line, delim):
    return [c.strip().strip('"') for c in next(csv.reader([line], delimiter=delim))]


def _delimiter(lines):
    best = ","
    score = 0
    for d in (",", ";", "\t"):
        n = max((ln.count(d) for ln in lines[:40]), default=0)
        if n > score:
            best, score = d, n
    return best


def _num(s):
    try:
        return float(s.replace(",", ".")) if isinstance(s, str) else float(s)
    except (ValueError, AttributeError):
        return None


def _find_header(lines, delim):
    """Index de la ligne d'en-tête des colonnes : celle qui contient latitude et longitude."""
    for i, ln in enumerate(lines[:80]):
        low = ln.lower()
        if ("lat" in low and "lon" in low) or low.lstrip().startswith("timestamp"):
            cells = [c.lower() for c in _split(ln, delim)]
            if len(cells) >= 3 and any(c.startswith("lat") for c in cells) and any(c.startswith("lon") for c in cells):
                return i
    return None


def detect(path):
    """Reconnaît le contenu d'un fichier : renvoie (identifiant, libellé) ; identifiant None si inconnu."""
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:4] == TRK_MAGIC:
        return ("trk", "Enregistrement TrackLab (.trk)")
    text = read_text(path, 200000)
    lines = [ln for ln in text.splitlines() if ln.strip()][:400]
    low_all = "\n".join(lines[:60]).lower()
    if "racechrono" in low_all or re.search(r"^format,\s*[123]\b", low_all, re.M):
        return ("racechrono", "RaceChrono (CSV)")
    if "[column names]" in low_all and "[data]" in low_all or low_all.startswith("file created on"):
        return ("vbo", "RaceChrono / VBOX (VBO)")
    if sum(1 for ln in lines if SERIAL_LINE.match(ln)) >= 3:
        return ("serial", "Trames CAN · moniteur série de l'ESP32")
    if sum(1 for ln in lines if LINE.search(ln)) >= 3 or "frame id" in low_all and "frame type" in low_all:
        return ("usbcan", "Trames CAN · export USB-CAN (TXT)")
    delim = _delimiter(lines)
    hi = _find_header(lines, delim)
    if hi is not None:
        cells = [c.lower() for c in _split(lines[hi], delim)]
        joined = " ".join(cells)
        if "racebox" in low_all or "gforcex" in joined or "gforce" in joined or "leanangle" in joined:
            return ("racebox", "RaceBox (CSV)")
        if "lap_number" in joined or "elapsed_time" in joined or "x_acc" in joined:
            return ("racechrono", "RaceChrono (CSV)")
        return ("gpscsv", "CSV avec position GPS")
    return (None, "Format non reconnu")


# ---------------------------------------------------------------- tableau de voies
_UNIT_RE = re.compile(r"[\[(]([^\])]*)[\])]\s*$")
_SPEED_UNITS = {"m/s": 3.6, "ms": 3.6, "kph": 1.0, "km/h": 1.0, "kmh": 1.0, "mph": 1.609344, "kn": 1.852, "kt": 1.852, "knots": 1.852}


def _clean_name(raw):
    """Sépare « Vitesse [km/h] » en (« Vitesse », « km/h »)."""
    raw = raw.strip()
    m = _UNIT_RE.search(raw)
    if m:
        return raw[: m.start()].strip(), m.group(1).strip()
    return raw, ""


def _parse_time(values):
    """Convertit la colonne de temps en secondes (flottants) ; renvoie None si illisible."""
    nums = [_num(v) for v in values]
    if sum(n is not None for n in nums) >= 0.9 * len(values):
        out = [n if n is not None else float("nan") for n in nums]
        good = [out[i + 1] - out[i] for i in range(min(len(out) - 1, 200)) if out[i + 1] > out[i]]
        if good:
            good.sort()
            dt = good[len(good) // 2]
            if dt >= 5 and out[0] < 1e11:  # millisecondes
                out = [v / 1000 for v in out]
            elif out[0] > 1e11:  # horodatage unix en millisecondes
                out = [v / 1000 for v in out]
        return out
    out = []
    for v in values:
        t = None
        s = v.strip().replace("Z", "")
        try:
            t = datetime.fromisoformat(s).timestamp()
        except ValueError:
            m = re.match(r"^(?:\d{4}[-/]\d{2}[-/]\d{2}[ T])?(\d{1,2}):(\d{2}):(\d{2}(?:[.,]\d+)?)$", s)
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3).replace(",", "."))
        out.append(t if t is not None else float("nan"))
    return out if sum(not math.isnan(x) for x in out) >= 0.9 * len(out) else None


def _haversine_kmh(lat1, lon1, lat2, lon2, dt):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a)) / dt * 3.6


def guess_speed_factor(t, lat, lon, speed):
    """Facteur vers des km/h, déduit en comparant la vitesse du fichier à celle calculée sur le tracé."""
    ratios = []
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        if not 0.04 <= dt <= 2 or speed[i] is None or speed[i] < 2:
            continue
        if None in (lat[i], lon[i], lat[i - 1], lon[i - 1]):
            continue
        d = _haversine_kmh(lat[i - 1], lon[i - 1], lat[i], lon[i], dt)
        if d > 5:
            ratios.append(d / speed[i])
    if len(ratios) < 20:
        return 1.0, False
    ratios.sort()
    med = ratios[len(ratios) // 2]
    best = min((1.0, 3.6, 1.609344, 1.852), key=lambda f: abs(math.log(med / f)))
    return best, True


_ROLES = {
    "lat": ("latitude", "lat", "gps latitude", "latitude (deg)"),
    "lon": ("longitude", "lon", "long", "lng", "gps longitude", "longitude (deg)"),
    "speed": ("kph", "speed", "gps speed", "vitesse", "velocity", "ground speed", "speed (gps)"),
    "head": ("bearing", "heading", "course", "cap", "heading (deg)"),
    "sats": ("satellites", "sats", "satellite count", "num sats", "numsats"),
    "fix": ("fix_type", "fix", "fix type", "gnss fix"),
}
_TIME_NAMES = ("timestamp", "time", "time (s)", "gps time", "utc time", "datetime", "date/time", "elapsed_time", "elapsed time", "t")


# unités des colonnes connues quand l'en-tête n'en donne pas (export « RaceBox Track Session » : Record,Time,Latitude,…)
_KNOWN_UNITS = {
    "kph": "km/h", "altitude": "m", "x": "g", "y": "g", "z": "g", "leanangle": "°", "lean angle": "°",
    "gyrox": "°/s", "gyroy": "°/s", "gyroz": "°/s", "gforcex": "g", "gforcey": "g", "gforcez": "g",
}


def _bearing(la1, lo1, la2, lo2):
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def _channel_type(name):
    """Type de signal (GPS, inertiel, capteur…) deviné d'après le nom de la colonne."""
    n = name.lower()
    if n in ("x", "y", "z", "leanangle", "lean angle", "lean") or n.startswith(("g ", "angle")):
        return TYPE_IMU
    if any(k in n for k in ("accuracy", "update_rate", "update rate", "alt", "height", "elevation", "satell", "distance", "hdop", "pdop", "bearing", "heading", "course")):
        return TYPE_GPS
    if any(k in n for k in ("gyro", "pitch", "roll", "yaw")) or n.endswith("rate"):
        return TYPE_IMU
    if any(k in n for k in ("acc", "gforce", "g-force", "g_force", "lateral", "longitudinal", "vertical")):
        return TYPE_IMU
    if any(k in n for k in ("rpm", "throttle", "brake", "temp", "press", "afr", "lambda", "gear", "volt", "boost", "fuel", "oil")):
        return TYPE_SENS
    return TYPE_OTHER


# ---------------------------------------------------------------- grandeurs recalculées (G, angle, tours)
G0 = 9.80665
_RENAME = {  # noms lisibles des colonnes inertielles d'un fichier RaceBox
    "gforcex": "G longitudinal", "gforcey": "G latéral", "gforcez": "G vertical",
    "leanangle": "Angle", "lean angle": "Angle", "lap": "Tour",
}


def _avg(v, n):
    """Moyenne glissante centrée sur n points (n impair), bords compris."""
    if n <= 1 or len(v) < 3:
        return list(v)
    h = n // 2
    out, acc = [], [0.0]
    for x in v:
        acc.append(acc[-1] + x)
    for i in range(len(v)):
        a, b = max(0, i - h), min(len(v), i + h + 1)
        out.append((acc[b] - acc[a]) / (b - a))
    return out


def derive_motion(tt, lat, lon, kmh):
    """Recalcule, depuis le seul GPS (temps en s, degrés, km/h), les trois grandeurs d'un fichier brut :
    accélération longitudinale (G, + accélération / - freinage), accélération latérale (G, + virage à droite)
    et angle d'inclinaison (degrés, + à droite), avec l'angle = atan(accélération latérale / g) (moto en équilibre)."""
    n = len(tt)
    if n < 8:
        return None
    r = 6371000.0
    la0, lo0 = lat[0], lon[0]
    c = math.cos(math.radians(la0))
    x = [math.radians(lo - lo0) * c * r for lo in lon]
    y = [math.radians(la - la0) * r for la in lat]
    v = _avg([max(0.0, s) / 3.6 for s in kmh], 3)
    xs, ys = _avg(x, 5), _avg(y, 5)
    k = 3
    head, prev = [], 0.0
    for i in range(n):
        a, b = max(0, i - k), min(n - 1, i + k)
        dx, dy = xs[b] - xs[a], ys[b] - ys[a]
        h = math.atan2(dx, dy) if (dx * dx + dy * dy) > 0.04 else prev
        while h - prev > math.pi:
            h -= 2 * math.pi
        while h - prev < -math.pi:
            h += 2 * math.pi
        head.append(h)
        prev = h
    yaw, glo = [], []
    for i in range(n):
        a, b = max(0, i - k), min(n - 1, i + k)
        dt = tt[b] - tt[a]
        if dt <= 0:
            yaw.append(0.0)
            glo.append(0.0)
            continue
        yaw.append((head[b] - head[a]) / dt if v[i] > 3.0 else 0.0)
        glo.append((v[b] - v[a]) / dt / G0)
    yaw = _avg(yaw, 5)
    glat = [max(-3.0, min(3.0, v[i] * yaw[i] / G0)) for i in range(n)]
    glo = [max(-3.0, min(3.0, g)) for g in _avg(glo, 3)]
    lean = [math.degrees(math.atan(g)) for g in glat]
    return glo, glat, lean


def detect_laps(tt, lat, lon, kmh):
    """Numéro de tour pour chaque point, quand le fichier n'en donne pas : un tour est compté à chaque retour près
    du point de départ (premier passage au-dessus de 30 km/h), après s'en être éloigné d'au moins 200 m."""
    n = len(tt)
    start = next((i for i in range(n) if kmh[i] > 30), None)
    if start is None:
        return None
    r = 6371000.0
    c = math.cos(math.radians(lat[start]))

    def dist(i):
        return math.hypot(math.radians(lon[i] - lon[start]) * c * r, math.radians(lat[i] - lat[start]) * r)

    out, lap, far = [0] * n, 0, False
    for i in range(start, n):
        d = dist(i)
        if d > 200:
            far = True
        elif d < 30 and far and kmh[i] > 20:
            lap += 1
            far = False
        out[i] = lap
    return out if max(out) >= 1 else None


def _table_to_loaded(kind, label, names, units, rows):
    """Convertit un tableau (en-têtes, unités, lignes de textes) en trames de l'application."""
    cols = list(zip(*rows)) if rows else []
    if not cols or len(cols) != len(names):
        return None
    low = [re.sub(r"\s+", " ", n.lower()) for n in names]
    units = [u or _KNOWN_UNITS.get(low[i], "") for i, u in enumerate(units)]
    # colonne de temps
    ti = next((i for n in _TIME_NAMES for i, c in enumerate(low) if c == n), None)
    if ti is None:
        ti = next((i for i, c in enumerate(low) if "time" in c and "lap" not in c), None)
    if ti is None:
        return None
    t = _parse_time(list(cols[ti]))
    if t is None:
        return None
    roles = {}
    for role, aliases in _ROLES.items():
        for a in aliases:
            idx = next((i for i, c in enumerate(low) if c == a and i != ti), None)
            if idx is not None:
                roles[role] = idx
                break
    if "lat" not in roles or "lon" not in roles:
        return None
    vals = [[_num(x) for x in col] for col in cols]
    lat, lon = vals[roles["lat"]], vals[roles["lon"]]
    # temps : on garde les lignes dont le temps est valide, en ordre croissant
    keep = [i for i in range(len(rows)) if not math.isnan(t[i])]
    if len(keep) < 2:
        return None
    keep.sort(key=lambda i: t[i])
    t0 = t[keep[0]]
    # vitesse en km/h : unité de l'en-tête, sinon déduite du tracé
    note = []
    factor = 1.0
    if "speed" in roles:
        u = units[roles["speed"]].lower().replace(" ", "")
        if u in _SPEED_UNITS:
            factor = _SPEED_UNITS[u]
        else:
            factor, certain = guess_speed_factor([t[i] for i in keep], [lat[i] for i in keep], [lon[i] for i in keep], [vals[roles["speed"]][i] for i in keep])
            if factor != 1.0:
                note.append(f"vitesse convertie (× {factor:g}) d'après le tracé")
    # noms lisibles, puis grandeurs absentes du fichier recalculées depuis le GPS (G, angle, tours)
    names = [_RENAME.get(low[i], names[i]) for i in range(len(names))]
    low = [re.sub(r"\s+", " ", n.lower()) for n in names]
    notes_calc = []
    if "speed" in roles and len(keep) > 20:
        ok = [i for i in keep if lat[i] is not None and lon[i] is not None and vals[roles["speed"]][i] is not None]
        if len(ok) > 20:
            tt = [t[i] - t0 for i in ok]
            la_ = [lat[i] for i in ok]
            lo_ = [lon[i] for i in ok]
            kmh = [vals[roles["speed"]][i] * factor for i in ok]
            wanted = [("g longitudinal", "G longitudinal (calculé)", "g"), ("g latéral", "G latéral (calculé)", "g"),
                      ("angle", "Angle (calculé)", "°")]
            have = {w[0]: w[0] in low for w in wanted}
            if have["angle"] and not have["g latéral"]:
                # l'angle est dans le fichier : on ne le recalcule pas ; seule la force G latérale manquante en est déduite
                ai = low.index("angle")
                col = [None] * len(rows)
                for i in keep:
                    v = vals[ai][i]
                    if v is not None:
                        col[i] = round(max(-3.0, min(3.0, math.tan(math.radians(v)))), 4)
                names.append("G latéral (calculé)")
                units.append("g")
                vals.append(col)
                low.append("g latéral (calculé)")
                notes_calc.append("G latéral (déduit de l'angle du fichier)")
                have["g latéral"] = True
            if not all(have.values()):
                res = derive_motion(tt, la_, lo_, kmh)
                if res:
                    for (key, label, unit), serie in zip(wanted, res):
                        if have[key]:
                            continue
                        col = [None] * len(rows)
                        for i, x in zip(ok, serie):
                            col[i] = round(x, 4)
                        names.append(label)
                        units.append(unit)
                        vals.append(col)
                        low.append(label.lower())
                        notes_calc.append(label.split(" (")[0])
            if "tour" not in low:
                laps = detect_laps(tt, la_, lo_, kmh)
                if laps:
                    col = [None] * len(rows)
                    for i, x in zip(ok, laps):
                        col[i] = x
                    names.append("Tour")
                    units.append("")
                    vals.append(col)
                    low.append("tour")
                    notes_calc.append("tours détectés d'après le tracé")
    if notes_calc:
        note.append("recalculé : " + ", ".join(notes_calc))
    skip = {"record", "index", "no", "nr", "#", "n°", "id"}
    other = [
        i for i in range(len(names))
        if i != ti and i not in roles.values() and low[i] not in skip and any(v is not None for v in vals[i])
    ]
    # voies : deux par trame
    dyn, pairs = {}, [other[k:k + 2] for k in range(0, len(other), 2)]
    for k, grp in enumerate(pairs):
        dyn[DYN_BASE + k] = [(names[i], units[i], _channel_type(names[i])) for i in grp] + [None] * (2 - len(grp))
    frames = []
    nan = float("nan")
    last_fix = 3
    calc_head, ref = {}, None
    if "head" not in roles:  # pas de cap dans le fichier : on le déduit du tracé (utile pour la carte)
        cur_h = 0.0
        for r in keep:
            la, lo = lat[r], lon[r]
            if la is None or lo is None:
                continue
            if ref is None:
                ref = (la, lo)
            elif _haversine_kmh(ref[0], ref[1], la, lo, 1.0) / 3.6 >= 1.5:  # au moins 1,5 m parcourus
                cur_h = _bearing(ref[0], ref[1], la, lo)
                ref = (la, lo)
            calc_head[r] = cur_h
    for r in keep:
        ms = int(round((t[r] - t0) * 1000))
        la, lo = lat[r], lon[r]
        if la is not None and lo is not None and (la or lo) and abs(la) <= 90 and abs(lo) <= 180:
            frames.append((ms, ID_GPS_POS, struct.pack("<ii", int(round(la * 1e7)), int(round(lo * 1e7)))))
        sp = vals[roles["speed"]][r] if "speed" in roles else None
        hd = vals[roles["head"]][r] if "head" in roles else calc_head.get(r)
        sa = vals[roles["sats"]][r] if "sats" in roles else None
        fx = vals[roles["fix"]][r] if "fix" in roles else None
        if sp is not None or hd is not None:
            frames.append((ms, ID_GPS_MOT, struct.pack(
                "<HHBB",
                max(0, min(65535, int(round((sp or 0) * factor * 100)))),
                max(0, min(65535, int(round((hd or 0) % 360 * 100)))),
                int(sa) if sa is not None and 0 <= sa < 256 else 0,
                int(fx) if fx is not None and 0 <= fx < 256 else last_fix,
            )))
        for k, grp in enumerate(pairs):
            v = [vals[i][r] if vals[i][r] is not None else nan for i in grp] + [nan] * (2 - len(grp))
            if any(not math.isnan(x) for x in v):
                frames.append((ms, DYN_BASE + k, struct.pack("<ff", *v)))
    if not frames:
        return None
    info = f"{len(keep):,} points · {len(other)} voies".replace(",", " ")
    if note:
        info += " · " + " · ".join(note)
    return Loaded(kind, label, frames, dyn, info)


def _load_csv(path, kind, label):
    text = read_text(path)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    delim = _delimiter(lines)
    hi = _find_header(lines, delim)
    if hi is None:
        return None
    raw_names = _split(lines[hi], delim)
    names, units = [], []
    for n in raw_names:
        nm, u = _clean_name(n)
        names.append(nm or n)
        units.append(u)
    rows = []
    units_done = any(units)
    for ln in lines[hi + 1:]:
        cells = _split(ln, delim)
        if len(cells) < len(names):
            continue
        cells = cells[: len(names)]
        if _num(cells[0]) is None and not re.match(r"^\d{4}[-/]\d{2}|^\d{1,2}:\d{2}", cells[0]):
            # ligne d'unités ou de sources (RaceChrono) : on retient les unités si la colonne n'en a pas
            if not units_done:  # la première de ces lignes porte les unités, la suivante les sources
                for i, c in enumerate(cells):
                    if not units[i] and c and len(c) <= 8:
                        units[i] = c
                units_done = True
            continue
        rows.append(cells)
    return _table_to_loaded(kind, label, names, units, rows)


def _load_vbo(path):
    """Fichier VBO (VBOX / RaceChrono) : latitude et longitude en minutes, longitude positive à l'ouest."""
    text = read_text(path)
    section = None
    names, rows = [], []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("["):
            section = s.lower()
            continue
        if section == "[column names]":
            names = s.split()
        elif section == "[data]":
            rows.append(s.split())
    if not names or not rows:
        return None
    low = [n.lower() for n in names]
    def col(*cands):
        return next((low.index(c) for c in cands if c in low), None)
    it, ila, ilo = col("time"), col("lat", "latitude"), col("long", "lon", "longitude")
    isp, ihd, ial, isa = col("velocity", "speed"), col("heading"), col("height", "altitude"), col("sats", "satellites")
    if None in (it, ila, ilo):
        return None
    t, lat, lon, spd, hdg, alt, sat = [], [], [], [], [], [], []
    other_idx = [i for i in range(len(names)) if i not in (it, ila, ilo, isp, ihd, ial, isa)]
    other = [[] for _ in other_idx]
    for r in rows:
        if len(r) < len(names):
            continue
        tv = r[it]
        try:
            hh, mm, ss = int(tv[:2]), int(tv[2:4]), float(tv[4:])
        except ValueError:
            continue
        t.append(hh * 3600 + mm * 60 + ss)
        lat.append((_num(r[ila]) or 0) / 60.0)
        lon.append(-(_num(r[ilo]) or 0) / 60.0)
        spd.append(_num(r[isp]) if isp is not None else None)
        hdg.append(_num(r[ihd]) if ihd is not None else None)
        alt.append(_num(r[ial]) if ial is not None else None)
        sat.append(_num(r[isa]) if isa is not None else None)
        for k, i in enumerate(other_idx):
            other[k].append(_num(r[i]))
    all_names = ["time", "latitude", "longitude", "speed", "heading", "altitude", "satellites"] + [names[i] for i in other_idx]
    cols = [t, lat, lon, spd, hdg, alt, sat] + other
    rows2 = [[("" if c[i] is None else repr(c[i])) for c in cols] for i in range(len(t))]
    units = ["s", "deg", "deg", "km/h", "deg", "m", ""] + [""] * len(other_idx)
    return _table_to_loaded("vbo", "RaceChrono / VBOX (VBO)", all_names, units, rows2)


# ---------------------------------------------------------------- point d'entrée
def load_any(path):
    """Détecte le contenu du fichier et le charge. Lève ValueError avec un message lisible si c'est impossible."""
    kind, label = detect(path)
    if kind is None:
        first = next((ln.strip() for ln in read_text(path, 4000).splitlines() if ln.strip()), "")[:90]
        raise ValueError(
            "Format de fichier non reconnu.\n\nFormats acceptés : capture USB-CAN (TXT), moniteur série ESP32, "
            "enregistrement TrackLab (.trk), RaceBox (CSV), RaceChrono (CSV ou VBO), CSV avec latitude et longitude."
            + (f"\n\nDébut du fichier : « {first} »" if first else "")
        )
    if kind in ("trk", "usbcan", "serial"):
        frames = load_capture(path)
        if not frames:
            raise ValueError(f"Fichier reconnu comme « {label} » mais il ne contient aucune trame lisible.")
        return Loaded(kind, label, frames, {}, f"{len(frames):,} trames".replace(",", " "))
    loaded = _load_vbo(path) if kind == "vbo" else _load_csv(path, kind, label)
    if loaded is None:
        raise ValueError(
            f"Fichier reconnu comme « {label} » mais ses colonnes sont illisibles (temps, latitude ou longitude introuvables)."
        )
    return loaded


# ---------------------------------------------------------------- comparaison de deux fichiers
B_BASE = DYN_BASE + 0x100  # identifiants des voies de la 2e session
B_SUFFIX = " [B]"


def _lap_start_ms(res, lap=1):
    """Instant (ms) où le fichier passe au tour `lap`, ou None s'il n'a pas de voie « Tour »."""
    for cid, ents in res.dyn.items():
        for j, ent in enumerate(ents):
            if ent and ent[0] == "Tour":
                for ms, c, data in res.frames:
                    if c == cid and len(data) >= 8:
                        v = struct.unpack("<ff", bytes(data[:8]))[j]
                        if v == v and int(round(v)) == lap:
                            return ms
    return None


def _dyn_series(res, name):
    """(temps en ms, valeurs) d'une voie nommée d'un fichier GPS chargé, ou None."""
    for cid, ents in res.dyn.items():
        for j, ent in enumerate(ents):
            if ent and ent[0] == name:
                ts, vs = [], []
                for ms, c, data in res.frames:
                    if c == cid and len(data) >= 8:
                        ts.append(ms)
                        vs.append(struct.unpack("<ff", bytes(data[:8]))[j])
                return ts, vs
    return None


def _gps_xy(res):
    """(temps ms, x, y) du tracé GPS d'un fichier, en mètres autour de sa première position."""
    t, la, lo = [], [], []
    for ms, c, data in res.frames:
        if c == ID_GPS_POS and len(data) >= 8:
            a, o = struct.unpack("<ii", bytes(data[:8]))
            t.append(ms)
            la.append(a / 1e7)
            lo.append(o / 1e7)
    return t, la, lo


def gps_warp(a, b):
    """Met la 2e session en regard de la 1re POSITION par POSITION : pour chaque point GPS de b, instant de a où la moto
    était au même endroit (dans le même tour, en avançant seulement). Renvoie (temps de b, instants de a correspondants)."""
    import bisect

    ta, la_a, lo_a = _gps_xy(a)
    tb, la_b, lo_b = _gps_xy(b)
    if len(ta) < 10 or len(tb) < 10:
        return None
    r = 6371000.0
    c = math.cos(math.radians(la_a[0]))
    xa = [math.radians(o - lo_a[0]) * c * r for o in lo_a]
    ya = [math.radians(v - la_a[0]) * r for v in la_a]
    xb = [math.radians(o - lo_a[0]) * c * r for o in lo_b]
    yb = [math.radians(v - la_a[0]) * r for v in la_b]

    def laps(res, times):
        ser = _dyn_series(res, "Tour")
        if not ser:
            return [0] * len(times)
        st, sv = ser
        out = []
        for t in times:
            i = bisect.bisect_right(st, t) - 1
            v = sv[max(i, 0)]
            out.append(int(round(v)) if v == v else 0)
        return out

    lap_a, lap_b = laps(a, ta), laps(b, tb)

    def runs(seq):
        """Tronçons consécutifs de même numéro de tour : [(tour, début, fin, n° d'occurrence de ce tour)]."""
        out, seen = [], {}
        for i, L in enumerate(seq):
            if out and out[-1][0] == L:
                out[-1][2] = i
            else:
                seen[L] = seen.get(L, 0) + 1
                out.append([L, i, i, seen[L]])
        return out

    runs_a = runs(lap_a)
    import numpy as np

    XA, YA = np.asarray(xa), np.asarray(ya)

    def target(L, occ):
        same = [r for r in runs_a if r[0] == L]
        if not same:
            near = min({r[0] for r in runs_a}, key=lambda q: abs(q - L))
            same = [r for r in runs_a if r[0] == near]
        return next((r for r in same if r[3] == occ), same[-1])

    match, last = [], 0
    for rb in runs(lap_b):
        _L, j0, j1, occ = rb
        _l, i0, i1, _o = target(rb[0], occ)
        p = last = i0
        for j in range(j0, j1 + 1):
            s0, s1 = max(i0, p - 30), min(i1, p + 500) + 1
            d = (XA[s0:s1] - xb[j]) ** 2 + (YA[s0:s1] - yb[j]) ** 2
            k = max(last, s0 + int(np.argmin(d)))
            match.append(k)
            p = last = k
    return tb, [ta[k] for k in match]


def merge_compare(a, b, mode="time"):
    """Réunit deux sessions GPS dans un même jeu de trames : les voies de b prennent le suffixe « [B] » et son tracé
    devient des voies cachées. Mode « time » : alignées sur le début du tour 1 (comparaison temporelle). Mode « gps » :
    le temps de b est recalé pour que les deux motos soient au même endroit au même instant de l'axe (comparaison par
    position GPS : freinages et relances se superposent)."""
    if b.kind in ("trk", "usbcan", "serial") or not b.frames:
        raise ValueError("Le fichier à comparer doit être une session GPS (RaceBox, RaceChrono, CSV…), pas une capture CAN.")
    warp = gps_warp(a, b) if mode == "gps" else None
    ta, tb = _lap_start_ms(a), _lap_start_ms(b)
    d = (ta - tb) if (ta is not None and tb is not None and warp is None) else 0
    sh_a, sh_b = max(0, -d), max(0, d)
    dyn = dict(a.dyn)
    remap = {}
    for k, (cid, ents) in enumerate(sorted(b.dyn.items())):
        remap[cid] = B_BASE + k
        dyn[B_BASE + k] = [(e[0] + B_SUFFIX, e[1], e[2]) if e else None for e in ents]
    pos_id, mot_id = B_BASE + len(b.dyn), B_BASE + len(b.dyn) + 1
    dyn[pos_id] = [("~lat B", "°", TYPE_GPS), ("~lon B", "°", TYPE_GPS)]
    dyn[mot_id] = [("GPS Vitesse" + B_SUFFIX, "km/h", TYPE_GPS), ("GPS Cap" + B_SUFFIX, "°", TYPE_GPS)]
    frames = [(ms + sh_a, cid, data) for ms, cid, data in a.frames]
    if warp:
        import numpy as np

        w_src, w_dst = np.asarray(warp[0], dtype=np.float64), np.asarray(warp[1], dtype=np.float64)

        def tmap(ms):
            return int(round(float(np.interp(ms, w_src, w_dst))))
    else:
        def tmap(ms):
            return ms + sh_b
    base = None
    for ms, cid, data in b.frames:
        if cid == ID_GPS_POS and len(data) >= 8:
            la, lo = struct.unpack("<ii", bytes(data[:8]))
            if base is None:
                base = (round(la / 1e7), round(lo / 1e7))
            frames.append((tmap(ms), pos_id, struct.pack("<ff", la / 1e7 - base[0], lo / 1e7 - base[1])))
        elif cid == ID_GPS_MOT and len(data) >= 4:
            sp, hd = struct.unpack("<HH", bytes(data[:4]))
            frames.append((tmap(ms), mot_id, struct.pack("<ff", sp / 100.0, hd / 100.0)))
        elif cid in remap:
            frames.append((tmap(ms), remap[cid], data))
    frames.sort(key=lambda f: f[0])
    if warp:
        how = "par position GPS"
    elif ta is not None and tb is not None:
        how = "dans le temps (début du tour 1 aligné)"
    else:
        how = "dans le temps (début des fichiers aligné)"
    out = Loaded(a.kind, a.label + " · comparaison", frames, dyn, f"{a.info} · comparaison {how}")
    out.extra = {"b_pos": pos_id, "b_base": base or (0, 0), "mode": "gps" if warp else "time"}
    return out
