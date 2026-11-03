#!/usr/bin/env python3
"""Génère un enregistrement .trk de simulation, comme si l'ESP32 avait tout enregistré sur un circuit :
trames CAN de la moto (toutes celles de la définition can1.xml, encodées bit à bit), GPS (0x7F0, 0x7F8),
entrées/sorties (0x7F9) et état de l'ESP32 (0x7FA).

Usage : python3 tools/simulate_trk.py [sortie.trk] [durée_s]
"""

import math
import os
import random
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tracklab.protocol import TRK_MAGIC, xor_sum  # noqa: E402
from tracklab.signals import SIGNALS  # noqa: E402

DT = 0.005  # pas de simulation : 5 ms
G = 9.81
rnd = random.Random(74)


# ---------------------------------------------------------------- circuit
def build_track():
    """Circuit fermé d'environ 2,6 km : courbe lissée passant par des points de contrôle ; renvoie x, y (m), longueur."""
    ctrl = [(0, 0), (420, 0), (700, 60), (820, 230), (700, 380), (480, 330), (380, 460), (480, 640),
            (330, 760), (80, 700), (-120, 560), (-90, 380), (-250, 250), (-200, 80)]
    n = len(ctrl)
    pts = []
    for i in range(n):  # spline de Catmull-Rom fermée
        p0, p1, p2, p3 = ctrl[i - 1], ctrl[i], ctrl[(i + 1) % n], ctrl[(i + 2) % n]
        for k in range(60):
            t = k / 60
            pts.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t * t
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t ** 3) for j in (0, 1)))
    # ré-échantillonnage tous les 2 m
    res, acc, step = [pts[0]], 0.0, 2.0
    for i in range(1, len(pts) + 1):
        a, b = pts[i - 1], pts[i % len(pts)]
        d = math.dist(a, b)
        while acc + d >= step:
            f = (step - acc) / d
            a = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            res.append(a)
            d = math.dist(a, b)
            acc = 0.0
        acc += d
    return res, step


def curvature(track, step):
    n = len(track)
    k = []
    for i in range(n):
        a, b, c = track[i - 5], track[i], track[(i + 5) % n]
        ang = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(b[1] - a[1], b[0] - a[0])
        ang = (ang + math.pi) % (2 * math.pi) - math.pi
        k.append(ang / (10 * step))
    sm = []
    for i in range(n):  # lissage
        sm.append(sum(k[(i + j) % n] for j in range(-8, 9)) / 17)
    return sm


def speed_profile(kappa, step, vmax=62.0, a_lat=0.95 * G, a_acc=6.0, a_brk=9.0):
    """Vitesse (m/s) en chaque point : limitée par l'adhérence en courbe, puis passes avant / arrière (freinage, accélération)."""
    n = len(kappa)
    v = [min(vmax, math.sqrt(a_lat / max(abs(k), 1e-4))) for k in kappa]
    for _ in range(3):
        for i in range(2 * n):
            j, nx = i % n, (i + 1) % n
            v[nx] = min(v[nx], math.sqrt(v[j] ** 2 + 2 * a_acc * step))
        for i in range(2 * n, 0, -1):
            j, nx = i % n, (i - 1) % n
            v[nx] = min(v[nx], math.sqrt(v[j] ** 2 + 2 * a_brk * step))
    return v


# ---------------------------------------------------------------- encodage CAN
SIGS = {}
for cid, name, sbit, blen, p0, p1, unit in SIGNALS:
    SIGS.setdefault(cid, {})[name] = (sbit, blen, p0, p1)


def put_bits(buf, sbit, blen, raw):
    raw = max(0, min((1 << blen) - 1, int(round(raw))))
    for k in range(blen):
        pos = sbit + k
        bit = raw >> (blen - 1 - k) & 1
        if bit:
            buf[pos // 8] |= 1 << (7 - pos % 8)
        else:
            buf[pos // 8] &= ~(1 << (7 - pos % 8)) & 0xFF


def encode(cid, values, dlc=8):
    """Construit la trame `cid` : `values` donne la valeur physique de chaque signal (les autres valent 0)."""
    buf = bytearray(8)
    for name, (sbit, blen, p0, p1) in SIGS[cid].items():
        if sbit + blen > 8 * len(buf):  # signal hors d'une trame de 8 octets (définition incomplète) : ignoré
            continue
        val = values.get(name, 0)
        raw = (val - p0) / p1 if p1 else 0
        put_bits(buf, sbit, blen, raw)
    return bytes(buf[:dlc])


def frame100(gear, kmh, rpm):
    """Trame 0x100 telle que la lit l'application (décodage de la page Télémétrie) : rapport = quartet bas de l'octet 0,
    vitesse = 12 bits bas des octets 1-2 (× 0,25 km/h), régime = octets 3-4 (grand-boutiste)."""
    b = bytearray(encode(0x100, {"RSV4_SEL_MAP": 1}))
    b[0] = gear & 15
    sp = int(kmh * 4) & 4095
    b[1], b[2] = sp >> 8, sp & 255
    b[3], b[4] = int(rpm) >> 8, int(rpm) & 255
    return bytes(b)


GEAR_RATIO = [0, 0.0075, 0.0097, 0.0118, 0.0138, 0.0157, 0.0175]  # km/h par tr/min (approximatif, 1re à 6e)


def gear_for(kmh):
    return 1 if kmh < 70 else 2 if kmh < 105 else 3 if kmh < 135 else 4 if kmh < 165 else 5 if kmh < 195 else 6


# ---------------------------------------------------------------- simulation
def simulate(duration):
    track, step = build_track()
    n = len(track)
    kappa = curvature(track, step)
    vprof = speed_profile(kappa, step)
    lat0, lon0 = 48.3204, 6.0786
    mlat = 111320.0
    mlon = 111320.0 * math.cos(math.radians(lat0))

    frames = []  # (ms, id, data)
    add = lambda t, cid, d: frames.append((int(round(t * 1000)), cid, bytes(d)))
    # périodes d'émission (s) des trames
    period = {0x100: .02, 0x102: .05, 0x104: .1, 0x106: .02, 0x108: .05, 0x114: .02, 0x174: .02, 0x178: .02, 0x200: .2,
              0x220: .2, 0x222: .2, 0x224: .2, 0x226: .2, 0x230: .1, 0x260: .02, 0x261: .02, 0x262: .02, 0x274: .02,
              0x275: .02, 0x276: .02, 0x277: .02, 0x300: .1, 0x382: .1, 0x601: .02, 0x7F1: .02, 0x7F2: .02, 0x7F3: .05,
              0x7F4: .05, 0x7F5: .05, 0x7F6: .02, 0x7F0: .1, 0x7F8: .1, 0x7F9: .05, 0x7FA: 1.0}
    nxt = {cid: rnd.random() * p for cid, p in period.items()}

    pos, v, t = 0.0, 8.0, 0.0  # abscisse curviligne (m), vitesse (m/s)
    lean_prev, odo = 0.0, 12000.0
    gear, shift_until, clutch_until, last_gear = 1, 0.0, 0.0, 1
    eng_t, oil_t, fuel = 84.0, 78.0, 12.0
    throttle_f, brake_f, lean_f = 0.0, 0.0, 0.0
    can_count = 0
    sig_prev = {}

    while t < duration:
        i = int(pos / step) % n
        target = vprof[i]
        # commande : on suit le profil (accélération / freinage) avec un peu de bruit de pilote
        err = target - v
        acc_cmd = max(-9.0, min(6.0, err * 1.8))
        a_long = acc_cmd * (1 + rnd.gauss(0, 0.01))
        v = max(2.0, v + a_long * DT)
        pos += v * DT
        k = kappa[i]
        j = (i + 1) % n
        kk = k  # courbure locale
        a_lat = v * v * kk  # accélération latérale (m/s²), signée
        lean = math.degrees(math.atan(a_lat / G)) * (1.0)  # angle d'inclinaison
        lean_f += (lean - lean_f) * min(1, DT / 0.08)
        roll_rate = (lean_f - lean_prev) / DT
        lean_prev = lean_f
        yaw_rate = math.degrees(v * kk)
        kmh = v * 3.6
        # boîte de vitesses : passage avec embrayage court (quickshifter)
        g = gear_for(kmh)
        if a_long < -5:  # fort freinage : rétrogradage à l'embrayage
            g = max(1, min(g, gear))
        if g != gear and t > shift_until:
            gear = g
            shift_until = t + 0.25
            clutch_until = t + 0.15
        ratio = GEAR_RATIO[gear]
        rpm = max(1300.0, kmh / ratio) if t > clutch_until else max(1300.0, kmh / ratio) * 0.92
        rpm = min(rpm, 15200.0)
        thr_target = 100 if a_long > 4.5 else max(0.0, min(100.0, 12 + a_long * 18)) if a_long >= 0 else 0.0
        if a_long > 0 and abs(a_lat) > 8:
            thr_target = min(thr_target, 45)
        throttle_f += (thr_target - throttle_f) * min(1, DT / 0.05)
        brk = max(0.0, -a_long) / 9.0 * 70.0  # pression de frein (bar)
        brake_f += (brk - brake_f) * min(1, DT / 0.04)
        eng_t += (92.0 + rpm / 15000 * 8 - eng_t) * DT / 90 + math.sin(t / 15) * 0.0005
        oil_t += (100.0 + rpm / 15000 * 10 - oil_t) * DT / 120
        fuel -= (rpm / 15000 * 0.0009 + 0.0003) * DT * 20
        odo += v * DT
        pitch = max(-6.0, min(6.0, -a_long / G * 14.0))
        batt = 13.7 + 0.5 * (rpm / 15000) + rnd.gauss(0, 0.03)
        abs_active = brk > 55 and rnd.random() < 0.5

        # position GPS
        px, py = track[int(pos / step) % n]
        px += rnd.gauss(0, 0.15)
        py += rnd.gauss(0, 0.15)
        lat = lat0 + py / mlat
        lon = lon0 + px / mlon
        qx, qy = track[(int(pos / step) + 3) % n]
        heading = (math.degrees(math.atan2(qx - track[int(pos / step) % n][0], qy - track[int(pos / step) % n][1]))) % 360

        base = {
            0x100: lambda: frame100(gear, kmh, rpm),
            0x102: lambda: encode(0x102, {"Clutch_Sw": 1 if t < clutch_until else 0, "Brake_Rear_Sw_": 1 if brk > 3 else 0,
                                          "Brake_Front_Sw": 1 if brk > 1.5 else 0}),
            0x104: lambda: encode(0x104, {"AWC_Level": 2, "ATC_Level": 3, "APRC_Lamp_Status": 1, "ALC_Level": 2, "Engine_Brake": 2,
                                          "Engine_Map": 1, "Pit_Speed": 60, "QS_Ready": 1 if t > shift_until else 0}),
            0x106: lambda: encode(0x106, {"Max_Eng_Trq": 125, "Fast_Eng_Trq": throttle_f * 1.1 * rpm / 15000 + 8,
                                          "Cmels_Trq": throttle_f * 1.0 * rpm / 15000 + 6, "Cplsdwderat_Trq": 125}),
            0x108: lambda: encode(0x108, {"CME_User_Norm": throttle_f * 0.9}),
            0x114: lambda: encode(0x114, {"TInj_Prog1": 2.0 + throttle_f * 0.07 + rpm / 4000, "TC_Slip_Lp": max(0, (a_long - 6) * 1.5) if throttle_f > 90 else 0}),
            0x174: lambda: encode(0x174, {"Yaw_Rate": yaw_rate, "Lon_Acc": a_long / G}),
            0x178: lambda: encode(0x178, {"Roll_Rate": roll_rate, "Lat_Acc": a_lat / G}),
            0x200: lambda: encode(0x200, {"Engine_Temp": eng_t, "Oil_Temp": oil_t, "Battery_Volt": batt * 1000}),
            0x220: lambda: encode(0x220, {"Odometer": odo, "TC_menu_set_butt": 0}),
            0x222: lambda: encode(0x222, {"Fuel_Level": max(0, min(15, fuel / 17 * 15)), "Air_Temp": 21 + eng_t * 0.05 + kmh * 0.01}),
            0x224: lambda: encode(0x224, {"224B6": 0x20, "224B7": 0x04}),
            0x226: lambda: encode(0x226, {"226B0": 0x00, "226B1": 0x40, "226B2": 0x00}),
            0x230: lambda: encode(0x230, {"ATC": 3, "ABS": 2, "ALC": 2, "AWC": 2, "AEB": 1, "AEM": 2, "Riding_Mode": 1}),
            0x260: lambda: encode(0x260, {"Speed_Front": kmh * (1 + rnd.gauss(0, 0.001)), "Speed_Rear": kmh * (1.004 if throttle_f > 85 else 1.0)}),
            0x261: lambda: encode(0x261, {"ABS_Level_St": 1, "ABS_Lamp_St": 1 if abs_active else 0, "Level_ABS": 2, "Brake_Press": brake_f}),
            0x262: lambda: encode(0x262, {"Pitch_Angle": abs(pitch) + 0.0, "Roll_Angle_001": 0}),
            0x274: lambda: encode(0x274, {"Lean_Angle_2": lean_f}),
            0x275: lambda: encode(0x275, {"Roll_Rate_2": roll_rate, "Pitch_Rate_2": (pitch - sig_prev.get("pitch", 0)) / DT * 0.0 + rnd.gauss(0, 0.4),
                                          "Yaw_Rate_2": yaw_rate}),
            0x276: lambda: encode(0x276, {"LongAcc_2": a_long / G, "LatAcc_2": a_lat / G, "VertAcc_2": 1.0 + rnd.gauss(0, 0.02)}),
            0x277: lambda: encode(0x277, {"277W0": 2048 + a_long * 20, "277W1": 2048 + a_lat * 20, "277W2": 2048}),
            0x300: lambda: encode(0x300, {"Dir_Conn_Buttons": 0, "AWC_selector": 2, "Joystick": 0}),
            0x382: lambda: encode(0x382, {"SRC_382B1": 0x10, "SRC_382B2": 0x00, "SRC_382B3": 0x80}),
            0x601: lambda: encode(0x601, {"Hand_Throttle": throttle_f, "Roll_Angle": lean_f, "Torque_Red": 0, "V4MP_Speed": kmh}),
            0x7F1: lambda: encode(0x7F1, {"RSV4_Advance": 8 + rpm / 15000 * 24 - throttle_f * 0.05, "7F1W01": 0,
                                          "RSV4_MAP1": 0.3 + throttle_f * 0.007, "RSV4_MAP2": 0.3 + throttle_f * 0.0072,
                                          "RSV4_THRT_HAND": throttle_f, "RSV4_MAP1_Target": 0.3 + throttle_f * 0.007,
                                          "RSV4_MAP2_Target": 0.3 + throttle_f * 0.0072}),
            0x7F3: lambda: encode(0x7F3, {"7F3B0": 0, "RSV4_Baro": 1.0, "RSV4_Tipover": 0, "RSV4_Sistfas": 1, "7F3W23": 0, "7F3B5": 0, "RSV4_Cntlostsync": 0}),
            0x7F4: lambda: encode(0x7F4, {"7F4W0": 1500 + rpm * 0.1, "7F4W1": 800 + throttle_f * 3, "7F4B4": 0x40, "7F4B5": 0, "7F4B6": 0, "7F4B7": 0}),
            0x7F5: lambda: encode(0x7F5, {"7F5W0": 3000, "7F5W1": 2900 + throttle_f, "7F5W2": 0}),
            0x7F6: lambda: encode(0x7F6, {"TPS": 600 + throttle_f * 8.3, "TPS2": 4000 - throttle_f * 8.3, "RSV4_PFANGCOR_1": 0, "RSV4_PFANGCOR_2": 0}),
        }
        for cid, per in period.items():
            if t < nxt[cid]:
                continue
            nxt[cid] += per
            tt = t + rnd.uniform(0, 0.002)
            if cid in base:
                add(tt, cid, base[cid]())
                can_count += 1
            elif cid == 0x7F2:  # papillon : TPS1 / TPS2 en petits-boutistes aux octets 1-2 et 3-4 (lecture de l'application)
                tps = 4 + throttle_f * 0.9
                a = int(tps / 0.119)
                b = int((tps * 0.99 + 0.3) / 0.119)
                add(tt, cid, struct.pack("<BHHHH", 0, a, b, 0, 0)[:8])
                can_count += 1
            elif cid == 0x7F0:
                add(tt, cid, struct.pack("<ii", int(round(lat * 1e7)), int(round(lon * 1e7))))
            elif cid == 0x7F8:
                add(tt, cid, struct.pack("<HHBB", int(kmh * 100 * (1 + rnd.gauss(0, 0.002))), int(heading * 100), 16, 3))
            elif cid == 0x7F9:
                # entrées : bit 0 frein, 1 embrayage, 2 clignotant G, 3 clignotant D, 4 feu de route ; ADC : suspensions + tension
                mask = (1 if brk > 1.5 else 0) | (2 if t < clutch_until else 0)
                susp_f = 1300 + brake_f * 18 + rnd.gauss(0, 10) + a_long * -25
                susp_r = 1900 + throttle_f * 5 + abs(a_lat) * 15 + rnd.gauss(0, 10)
                add(tt, cid, struct.pack("<BHHH", mask, int(max(0, min(4095, susp_f))), int(max(0, min(4095, susp_r))), int(batt / 16.5 * 4095)))
            elif cid == 0x7FA:
                rssi = int(-52 + 6 * math.sin(t / 7) + rnd.gauss(0, 1))
                add(tt, cid, struct.pack("<BbBHBB", 0b000111, rssi, 1, int(can_count / max(t, 1)) if t > 1 else 0, 0, 0b011)[:7])
        t += DT
        sig_prev["pitch"] = pitch
    frames.sort(key=lambda f: f[0])
    return frames


def write_trk(path, frames):
    out = bytearray(TRK_MAGIC + bytes(12))
    for ms, cid, data in frames:
        r = ms.to_bytes(4, "little") + cid.to_bytes(2, "little") + bytes([len(data)]) + data.ljust(8, b"\0")
        out += r + bytes([xor_sum(r)])
    with open(path, "wb") as f:
        f.write(out)


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else "Simulation_ESP32_circuit.trk"
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0
    fr = simulate(dur)
    write_trk(dest, fr)
    print(f"{dest} : {len(fr)} trames, {dur:.0f} s, {os.path.getsize(dest) / 1e6:.1f} Mo")
