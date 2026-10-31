"""Fonctions de mise en forme et de calcul sans dépendance à l'interface."""

import math
import re


def fmt_val(v):
    if v is None:
        return "—"
    if isinstance(v, int) or float(v).is_integer():
        return f"{int(round(v)):,}".replace(",", " ")
    return f"{v:.2f}".rstrip("0").rstrip(".")


def disp_unit(u):
    return {"C": "°C", "gear": ""}.get(u, u)


def fmt_time(ms):
    s = max(0, int(ms / 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


def fmt_ms(ms):
    ms = max(0, int(ms))
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def parse_ids(text):
    """Filtre d'identifiants en hexadécimal : '100, 200-20F'. Renvoie (liste de bornes ou None, valide)."""
    text = text.strip()
    if not text:
        return (None, True)
    out = []
    ok = True
    for tok in re.split("[,;\\s]+", text):
        if not tok:
            continue
        tok = tok.lower().replace("0x", "")
        try:
            if "-" in tok:
                a, b = tok.split("-", 1)
                a = int(a, 16)
                b = int(b, 16)
                out.append((min(a, b), max(a, b)))
            else:
                v = int(tok, 16)
                out.append((v, v))
        except ValueError:
            ok = False
    return (out or None, ok)


def nice_ticks(lo, hi, n):
    """Graduations « rondes » entre lo et hi (environ n)."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw))
    first = math.ceil(lo / step - 1e-09)
    out = []
    i = 0
    while True:
        v = (first + i) * step
        if v > hi + step * 1e-09:
            break
        out.append(round(v, 10))
        i += 1
    return out
