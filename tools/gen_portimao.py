"""Génère deux fichiers de télémétrie SIMULÉS sur le circuit de Portimão (Algarve) pour tester TrackLab.

Base réelle : la session RaceBox de démonstration (GPS, vitesse, G, angle, gyroscope, tours). Tout le reste (régime, rapport,
gaz, frein, vitesses de roues, températures, couple, patinage, TC, wheelie…) est SIMULÉ de façon plausible à partir de ces
mesures : ce n'est PAS une mesure de moto. Le fichier B est un second pilote un peu plus lent sur la même trajectoire.

Usage : python tools/gen_portimao.py  (écrit tracklab_qt/demo/portimao_A.csv et portimao_B.csv)
"""

import csv
import datetime as dt
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "tracklab_qt", "demo")
SRC = os.path.join(DEMO, "demo_racebox.csv")

TOP_SPEED_AT_14000 = [110.0, 147.0, 182.0, 214.0, 244.0, 282.0]  # km/h à 14 000 tr/min dans chaque rapport (RSV4 environ)


def load_source():
    rows = list(csv.reader(open(SRC, encoding="utf-8")))
    head, data = rows[0], rows[1:]
    col = {n: i for i, n in enumerate(head)}
    t = np.array([dt.datetime.fromisoformat(r[col["Time"]].replace("Z", "+00:00")).timestamp() for r in data])
    f = lambda n: np.array([float(r[col[n]]) for r in data])
    return {
        "t": t - t[0], "t0": t[0], "lat": f("Latitude"), "lon": f("Longitude"), "alt": f("Altitude"), "speed": f("Speed"),
        "gx": f("GForceX"), "gz": f("GForceZ"), "lap": f("Lap").astype(int), "lean": f("LeanAngle"),
        "gyx": f("GyroX"), "gyy": f("GyroY"), "gyz": f("GyroZ"),
    }


def smooth(x, n):
    n = max(1, int(n))
    if n == 1:
        return x
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, np.ones(n) / n, mode="valid")


def pulse(t, centre, width):
    """Bosse lisse (cloche) centrée en `centre`, de largeur à mi-hauteur ≈ width."""
    return np.exp(-0.5 * ((t - centre) / (width / 2.355)) ** 2)


def simulate_channels(t, v, gx, lean, gyy, rng, wheelie_laps=(), stoppie_laps=(), lap=None):
    """Voies moto simulées sur la base de temps t (s). v en km/h, gx = G longitudinal (+ accélération), lean en degrés.
    Retourne un dict de tableaux (et le gyroscope de tangage modifié par les wheelies / stoppies)."""
    n = len(t)
    dtm = float(np.median(np.diff(t)))
    ang = np.abs(lean)
    gyy = gyy.copy()

    # --- rapport et régime : passage à 13 000 tr/min, rétrogradage sous 5 000
    gear = np.ones(n, int)
    rpm = np.zeros(n)
    g, last_shift = 1, -9.0
    for i in range(n):
        r = v[i] / TOP_SPEED_AT_14000[g - 1] * 14000.0
        if t[i] - last_shift > 0.35:
            if r > 13000 and g < 6 and gx[i] > -0.1:
                g += 1
                last_shift = t[i]
            elif r < 5000 and g > 1:
                g -= 1
                last_shift = t[i]
        gear[i] = g
        rpm[i] = v[i] / TOP_SPEED_AT_14000[g - 1] * 14000.0
    rpm = np.maximum(rpm, 1300 + 300 * np.clip(v / 30.0, 0, 1))  # ralenti / embrayage à très basse vitesse
    rpm = np.minimum(rpm, 13600)
    # creux de couple à chaque montée de rapport, rattrapage au rétrogradage
    shifts = np.nonzero(np.diff(gear) != 0)[0]
    for i in shifts:
        up = gear[i + 1] > gear[i]
        rpm += (-550 if up else 700) * pulse(t, t[i], 0.18)
    rpm = np.clip(rpm + rng.normal(0, 25, n), 900, 13900)

    # --- gaz (TPS %)
    tps = np.where(gx > 0.05, 35 + gx * 110, np.where(gx > -0.05, 10 + 0.45 * ang, 0.0))
    tps = np.where(v > 255, 100.0, tps)
    tps = np.minimum(tps, np.where(ang > 30, 30 + (65 - np.minimum(ang, 55)) * 1.4, 100))  # incliné : gaz limités
    tps = np.clip(smooth(tps, 6), 0, 100)
    tps = np.where(tps > 92, 100.0, tps)

    # --- frein
    press = np.where(gx < -0.12, np.clip(-gx * 92 + 6, 0, 120), 0.0)
    press = smooth(press, 5) + rng.normal(0, 0.4, n) * (press > 1)
    press = np.clip(press, 0, 120)
    front_sw = (press > 5).astype(int)

    # --- patinage (TC), wheelie, stoppie
    slip = 0.15 + 0.5 * np.clip(gx, 0, 1.3) + rng.normal(0, 0.08, n)
    lapv = lap if lap is not None else np.zeros(n, int)
    # sorties de virage inclinées, gaz > 60 %, rapport ≤ 3 : bouffées de patinage sur ~40 % des virages
    cand = (tps > 60) & (ang > 22) & (gear <= 3) & (v > 40)
    start = None
    for i in range(n + 1):
        on = i < n and cand[i]
        if on and start is None:
            start = i
        elif not on and start is not None:
            if rng.random() < 0.4 and t[i - 1] - t[start] > 0.3:
                c = t[start] + 0.4 * (t[i - 1] - t[start])
                slip += rng.uniform(3.2, 7.0) * pulse(t, c, rng.uniform(0.35, 0.8))
            start = None
    pitch_ang = -gx * 2.0
    front_loss = np.zeros(n)
    awc_cut = np.zeros(n)
    for kind, laps in (("wheelie", wheelie_laps), ("stoppie", stoppie_laps)):
        for L in laps:
            m = lapv == L
            if not m.any():
                continue
            if kind == "wheelie":
                score = np.where(m & (gear <= 2) & (tps > 90), smooth(gx, 8), -9.0)
                i = int(np.argmax(score))
                if score[i] < 0.8:
                    continue
                c = t[i]
                b = pulse(t, c, 0.9)
                front_loss += 4.5 * b
                gyy += 45 * pulse(t, c - 0.35, 0.35) - 40 * pulse(t, c + 0.45, 0.4)
                pitch_ang += 17 * b
                awc_cut += 0.45 * pulse(t, c + 0.1, 0.8)
                slip += 1.2 * b
            else:
                score = np.where(m & (press > 0), press, -1.0)
                i = int(np.argmax(score))
                if score[i] < 70:
                    continue
                c = t[i]
                b = pulse(t, c, 0.7)
                front_loss -= 6.0 * b  # roue arrière plus lente
                gyy += -55 * pulse(t, c - 0.2, 0.3) + 40 * pulse(t, c + 0.3, 0.3)
                pitch_ang -= 6 * b
    slip = np.maximum(slip, -1.0)
    front = v * (1 + rng.normal(0, 0.0015, n)) * (1 - front_loss / 100.0)
    rear = v * (1 + rng.normal(0, 0.0015, n)) * (1 + slip / 100.0) * (1 + 0.012 * (press > 5) * -1)
    rear = np.maximum(rear, 0)
    front = np.maximum(front, 0)

    # --- couple, TC
    tq_max = np.maximum(60.0, 125.0 * (1 - ((rpm - 10500.0) / 7500.0) ** 2))
    tc_slip = np.clip((slip - 2.5) * 1.2, 0, 20)
    cut = np.clip((slip - 3.0) / 8.0, 0, 0.7) + awc_cut
    tq_fast = tq_max * (tps / 100.0) * (1 - np.clip(cut, 0, 0.8))
    tq_fast = np.where(tps < 3, -12.0 * (rpm / 10000.0), tq_fast)  # frein moteur

    # --- températures, tension
    te = 82 + 11 * (1 - np.exp(-t / 220.0)) + 3.0 * (1 - np.clip(v / 150.0, 0, 1)) + rng.normal(0, 0.15, n)
    to = 90 + 18 * (1 - np.exp(-t / 320.0)) + 1.2 * (rpm / 13000.0) + rng.normal(0, 0.15, n)
    batt = 13.7 + 0.5 * np.clip((rpm - 3000) / 8000.0, 0, 1) + rng.normal(0, 0.02, n)
    return {
        "RPM": rpm, "Gear": gear, "TPS": tps, "Brake_Press": press, "Brake_Front_Sw": front_sw,
        "Speed_Front": front, "Speed_Rear": rear, "Engine_Temp": te, "Oil_Temp": to, "Air_Temp": np.full(n, 24.0) + rng.normal(0, 0.05, n),
        "Battery_V": batt, "Pitch_Angle": smooth(pitch_ang, 3), "Max_Eng_Trq": tq_max, "Fast_Eng_Trq": tq_fast, "TC_Slip_Lp": tc_slip,
        "ATC_Level": np.full(n, 3), "AWC_Level": np.full(n, 2), "Engine_Brake": np.full(n, 2), "Engine_Map": np.full(n, 1),
        "_gyy": gyy,
    }


HEADER = ("Record,Time,Latitude,Longitude,Altitude,Speed,GForceX,GForceZ,Lap,LeanAngle,GyroX,GyroY,GyroZ,Heading,Satellites,Fix,"
          "RPM [rpm],Gear,TPS [%],Brake_Press [bar],Brake_Front_Sw,Speed_Front [km/h],Speed_Rear [km/h],Engine_Temp [°C],"
          "Oil_Temp [°C],Air_Temp [°C],Battery_V [V],Pitch_Angle [°],Max_Eng_Trq [Nm],Fast_Eng_Trq [Nm],TC_Slip_Lp [%],"
          "ATC_Level,AWC_Level,Engine_Brake,Engine_Map")


def heading_of(lat, lon):
    x = np.radians(lon - lon[0]) * math.cos(math.radians(lat[0]))
    y = np.radians(lat - lat[0])
    xs, ys = smooth(x, 5), smooth(y, 5)
    dx, dy = np.gradient(xs), np.gradient(ys)
    h = np.degrees(np.arctan2(dx, dy)) % 360.0
    return h


def write_csv(path, S, ch, t_iso):
    h = heading_of(S["lat"], S["lon"])
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(HEADER + "\n")
        n = len(S["t"])
        for i in range(n):
            f.write(",".join([
                str(i + 1), t_iso[i], f"{S['lat'][i]:.7f}", f"{S['lon'][i]:.7f}", f"{S['alt'][i]:.1f}", f"{S['speed'][i]:.2f}",
                f"{S['gx'][i]:.3f}", f"{S['gz'][i]:.3f}", str(int(S["lap"][i])), f"{S['lean'][i]:.1f}", f"{S['gyx'][i]:.2f}",
                f"{ch['_gyy'][i]:.2f}", f"{S['gyz'][i]:.2f}", f"{h[i]:.1f}", "14", "3",
                f"{ch['RPM'][i]:.0f}", str(int(ch["Gear"][i])), f"{ch['TPS'][i]:.1f}", f"{ch['Brake_Press'][i]:.1f}",
                str(int(ch["Brake_Front_Sw"][i])), f"{ch['Speed_Front'][i]:.2f}", f"{ch['Speed_Rear'][i]:.2f}",
                f"{ch['Engine_Temp'][i]:.1f}", f"{ch['Oil_Temp'][i]:.1f}", f"{ch['Air_Temp'][i]:.1f}", f"{ch['Battery_V'][i]:.2f}",
                f"{ch['Pitch_Angle'][i]:.1f}", f"{ch['Max_Eng_Trq'][i]:.1f}", f"{ch['Fast_Eng_Trq'][i]:.1f}",
                f"{ch['TC_Slip_Lp'][i]:.1f}", str(int(ch["ATC_Level"][i])), str(int(ch["AWC_Level"][i])),
                str(int(ch["Engine_Brake"][i])), str(int(ch["Engine_Map"][i])),
            ]) + "\n")


def iso(t0, t):
    return [dt.datetime.fromtimestamp(t0 + x, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(round((t0 + x) % 1 * 1000)) % 1000:03d}Z"
            for x in t]


def slice_session(S, pre=12.0, post=15.0):
    """Du dernier instant avant le tour 1 (− pre s) jusqu'à post s après le début du tour 5 : tours 1 à 4 complets."""
    lap = S["lap"]
    i1 = int(np.argmax(lap == 1))
    i5 = int(np.argmax(lap == 5))
    a = max(0, int(np.searchsorted(S["t"], S["t"][i1] - pre)))
    b = int(np.searchsorted(S["t"], S["t"][i5] + post))
    out = {k: (v[a:b] if isinstance(v, np.ndarray) else v) for k, v in S.items()}
    out["t0"] = S["t0"] + S["t"][a]
    out["t"] = out["t"] - out["t"][0]
    return out


def make_B(A, rng):
    """Second pilote : même trajectoire, ≈ 2,5 % plus lent, plus prudent en virage (vitesses de corde plus basses)."""
    t, v = A["t"], np.maximum(A["speed"], 0.0)
    dtm = np.diff(t, prepend=t[0])
    s = np.cumsum(v / 3.6 * dtm)
    s = np.maximum.accumulate(s + np.arange(len(s)) * 1e-6)  # strictement croissante
    # facteur de vitesse lisse en fonction de la distance : plus lent surtout là où l'on est incliné
    ph = rng.uniform(0, 2 * math.pi, 4)
    smooth_n = sum(0.012 * np.sin(2 * math.pi * s / p + q) for p, q in zip((310, 520, 770, 1100), ph))
    ang = smooth(np.abs(A["lean"]), 25)
    f = np.clip(0.985 - 0.035 * np.clip(ang / 45.0, 0, 1) + smooth_n, 0.9, 1.0)
    vb = v * f
    vb_ms = np.maximum(vb / 3.6, 1.2)
    tb = np.concatenate([[0.0], np.cumsum(np.diff(s) / vb_ms[1:])])
    tb = np.maximum.accumulate(tb + np.arange(len(tb)) * 1e-6)
    tn = np.arange(0.0, tb[-1], 0.04)
    sB = np.interp(tn, tb, s)

    def at(x):
        return np.interp(sB, s, x)

    vB = at(vb)
    ratio = np.where(at(v) > 3, vB / np.maximum(at(v), 3), 1.0)
    glat = np.tan(np.radians(at(A["lean"]))) * ratio ** 2
    lean = np.degrees(np.arctan(glat))
    gx = np.clip(smooth(np.gradient(vB / 3.6, tn) / 9.80665, 6), -1.6, 2.0)
    lapB = np.interp(sB, s, A["lap"].astype(float))
    lapB = np.round(lapB).astype(int)
    B = {
        "t": tn, "t0": A["t0"] + 30 * 60, "lat": at(A["lat"]), "lon": at(A["lon"]), "alt": at(A["alt"]), "speed": vB, "gx": gx,
        "gz": at(A["gz"]), "lap": lapB, "lean": lean, "gyx": np.gradient(lean, tn), "gyy": at(A["gyy"]) * ratio,
        "gyz": at(A["gyz"]) * ratio,
    }
    return B


def main():
    S = load_source()
    A = slice_session(S)
    rngA = np.random.default_rng(74)
    chA = simulate_channels(A["t"], A["speed"], A["gx"], A["lean"], A["gyy"], rngA, wheelie_laps=(2, 3), stoppie_laps=(4,), lap=A["lap"])
    write_csv(os.path.join(DEMO, "portimao_A.csv"), A, chA, iso(A["t0"], A["t"]))
    B = make_B(A, np.random.default_rng(75))
    chB = simulate_channels(B["t"], B["speed"], B["gx"], B["lean"], B["gyy"], np.random.default_rng(76), wheelie_laps=(3,), stoppie_laps=(),
                            lap=B["lap"])
    write_csv(os.path.join(DEMO, "portimao_B.csv"), B, chB, iso(B["t0"], B["t"]))
    for nm in ("portimao_A.csv", "portimao_B.csv"):
        p = os.path.join(DEMO, nm)
        print(nm, os.path.getsize(p) // 1024, "ko")


if __name__ == "__main__":
    main()
