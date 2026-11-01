"""Décodage des trames CAN et des trames de l'ESP32."""

import tkinter as tk
from collections import deque

from .config import BY_CID, HAND_ALWAYS, HAND_EXPERIMENTAL
from .names import fr
from .protocol import ESP_IDS, extract_bits
from .util import disp_unit, fmt_ms, fmt_val, wifi_quality


class DecodingMixin:
    """Décodage des trames CAN et des trames de l'ESP32."""

    def put(self, cid, name, val, t, src):
        """Enregistre une valeur : valeur courante, historique pour les courbes, mise à jour de la tuile."""
        key = (cid, name)
        self.vals[key] = (val, src)
        h = self.hist.get(key)
        if h is None:
            h = self.hist[key] = deque(maxlen=self.hist_max)
        h.append((t, val))
        self.dirty.add(key)

    # ---------- décodage ----------
    def decode_aprilia(self, t, cid, data):
        """Décodages faits à la main (poignée, TPS, et décodages expérimentaux). Renvoie le texte affiché dans le tableau."""
        dec = "—"
        exp = self.experimental.get()
        if cid == 2034 and len(data) >= 5:
            a = int.from_bytes(data[1:3], "little") * 0.119
            b = int.from_bytes(data[3:5], "little") * 0.119
            self.tps_lbl.config(text=f"TPS1 {a:.1f}*  ·  TPS2 {b:.1f}*")
            self.put(cid, "RSV4_TPS1", a, t, "app")
            self.put(cid, "RSV4_TPS2", b, t, "app")
            dec = f"Papillon TPS1 {a:.1f} % | TPS2 {b:.1f} %  (hypothèse)"
        if cid == 1537 and data:
            self.show("throttle", data[0], text=f"{data[0]}")
            self.put(cid, "Hand_Throttle", data[0], t, "valid")
            dec = f"Position gaz : {data[0]} %"
        if exp:
            if cid == 256 and len(data) >= 5:
                rpm = data[3] << 8 | data[4]
                self.rpm.set(rpm)
                self.put(cid, "RPM", rpm, t, "app")
                parts = [f"Régime {rpm} tr/min*"]
                if len(data) >= 2:
                    gear = data[0] & 15
                    self.gear.set(gear)
                    self.gear_val.config(text=str(gear))
                    self.put(cid, "Gear", gear, t, "app")
                    parts.append(f"Rapport {gear}*")
                    if len(data) >= 3:
                        spd = round(((data[1] << 8 | data[2]) & 4095) * 0.25, 1)
                        self.speedg.set(spd)
                        self.put(cid, "Bike_Speed", spd, t, "app")
                        parts.append(f"Vitesse {spd} km/h*")
                dec = " | ".join(parts)
            if cid == 512 and len(data) >= 2:
                tmp = data[0] - 40
                oil = data[1] - 40
                self.show("temp", tmp)
                self.show("oil", oil)
                self.put(cid, "Engine_Temp", tmp, t, "app")
                self.put(cid, "Oil_Temp", oil, t, "app")
                parts = [f"Temp. moteur {tmp} °C*", f"Temp. huile {oil} °C*"]
                if len(data) >= 6:
                    v = data[5] / 10
                    self.show("battery", v, text=f"{v:.1f}")
                    self.put(cid, "Battery_Volt", v, t, "app")
                    parts.append(f"Batterie {v:.1f} V*")
                dec = " | ".join(parts)
            if cid == 608 and len(data) >= 5:
                f = round(int.from_bytes(data[1:3], "big") * 0.01, 1)
                r = round(int.from_bytes(data[3:5], "big") * 0.01, 1)
                self.show("front", f, text=f"{f:.1f}")
                self.show("rear", r, text=f"{r:.1f}")
                self.put(cid, "Speed_Front", f, t, "app")
                self.put(cid, "Speed_Rear", r, t, "app")
                dec = f"Roue AV {f:.1f} km/h | Roue AR {r:.1f} km/h*"
        return dec

    def decode_generic(self, t, cid, data):
        """Tous les autres signaux de la définition can1.xml. Renvoie la liste des textes affichés."""
        parts = []
        for _, name, sbit, blen, p0, p1, unit in BY_CID.get(cid, ()):
            if (cid, name) in HAND_ALWAYS or (self.experimental.get() and (cid, name) in HAND_EXPERIMENTAL):
                continue
            raw = extract_bits(data, sbit, blen)
            if raw is None:
                continue
            val = p0 + p1 * raw
            self.put(cid, name, val, t, "def")
            parts.append(f"{fr(name)} {fmt_val(val)}{(' ' + disp_unit(unit) if unit else '')}")
        return parts

    def decode_virtual(self, t, cid, data):
        """Trames de l'ESP32 : GPS (0x7F0, 0x7F8) et entrées/sorties (0x7F9). Renvoie le texte affiché, ou None."""
        if cid == 2032 and len(data) >= 8:
            lat = int.from_bytes(data[0:4], "little", signed=True) / 10000000.0
            lon = int.from_bytes(data[4:8], "little", signed=True) / 10000000.0
            self.put(cid, "GPS Latitude", lat, t, "esp")
            self.put(cid, "GPS Longitude", lon, t, "esp")
            if lat or lon:
                self.track.append((lat, lon))
            return f"GPS {lat:.6f} ; {lon:.6f}"
        if cid == 2040 and len(data) >= 6:
            sp = int.from_bytes(data[0:2], "little") / 100
            co = int.from_bytes(data[2:4], "little") / 100
            sats = data[4]
            fix = data[5]
            self.put(cid, "GPS Vitesse", sp, t, "esp")
            self.put(cid, "GPS Cap", co, t, "esp")
            self.put(cid, "Satellites", sats, t, "esp")
            self.put(cid, "Qualité fix", fix, t, "esp")
            return f"GPS {sp:.1f} km/h · cap {co:.0f}° · {sats} satellites · fix {fix}"
        if cid == 2042 and len(data) >= 6:
            rssi = int.from_bytes(data[1:2], "little", signed=True)
            self.esp = {
                "flags": data[0],
                "rssi": None if rssi == 127 else rssi,
                "stations": data[2],
                "can_rate": int.from_bytes(data[3:5], "little"),
                "can_err": data[5],
                "t": t,
                "rec": len(data) >= 7 and bool(data[6] & 1),
                "store": len(data) >= 7 and bool(data[6] & 2),
                "sd": len(data) >= 7 and bool(data[6] & 4),
                # les champs de la trame 0x7FB sont conservés d'une trame d'état à l'autre
                **{k: (self.esp or {}).get(k, 0) for k in ("rec_no", "rec_bytes", "free_mb")},
            }
            if rssi != 127:
                self.put(cid, "Signal Wi-Fi", rssi, t, "esp")
            q = f"{rssi} dBm · {wifi_quality(rssi)[1]}" if rssi != 127 else "aucun appareil"
            return f"État ESP32 · drapeaux {data[0]:06b} · Wi-Fi {q} · CAN {self.esp['can_rate']}/s"
        if cid == 2043 and len(data) >= 8:
            no = int.from_bytes(data[0:2], "little")
            free = int.from_bytes(data[6:8], "little")
            if self.esp is not None:
                self.esp.update(rec_no=no, rec_bytes=int.from_bytes(data[2:6], "little"), free_mb=free)
            return f"Enregistrement · fichier {no} · {free} Mo libres"
        if cid == 2041 and len(data) >= 7:
            mask = data[0]
            for n in range(8):
                self.put(cid, f"Entrée {n + 1}", mask >> n & 1, t, "esp")
            adc = [int.from_bytes(data[1 + 2 * j:3 + 2 * j], "little") for j in range(3)]
            for j in range(3):
                self.put(cid, f"ADC {j + 1}", adc[j], t, "esp")
            for j, nom in enumerate(("Débattement avant", "Débattement arrière")):
                self.put(cid, nom, round(adc[j] * 100 / 4095, 1), t, "esp")
            return f"E/S {mask:08b} · ADC {adc[0]} / {adc[1]} / {adc[2]}"
        return None

    def ingest(self, t, cid, data):
        self.t_now = t
        self.count[cid] += 1
        self.ingested += 1
        self.t_last = t
        if cid not in ESP_IDS:  # seules les vraies trames CAN comptent dans le débit affiché
            self.recent.append(t)
        if self.live:
            self.link_t = t
        self.first_t.setdefault(cid, t)
        self.last_t[cid] = t
        dec = "—"
        if self.decoder == "aprilia":
            dec = self.decode_aprilia(t, cid, data)
            parts = self.decode_generic(t, cid, data)
            if parts:
                dec = " | ".join(parts) if dec == "—" else dec + " | " + " | ".join(parts)
        v = self.decode_virtual(t, cid, data)
        if v:
            dec = v if dec == "—" else dec + " | " + v
        n = self.count[cid]
        freq = "—"
        if n > 1 and self.last_t[cid] > self.first_t[cid]:
            freq = f"{(n - 1) * 1000 / (self.last_t[cid] - self.first_t[cid]):.0f}"
        row = (
            self.ingested,
            fmt_ms(t),
            cid,
            len(data),
            data.hex(" ").upper(),
            " ".join((str(b) for b in data)),
            freq,
            dec,
        )
        self.rows.append(row)
        if not self.bulk and self.row_match(row):
            self.matched += 1
            try:
                if self.last_row is not None:
                    self.table.item(self.last_row, tags=())
            except tk.TclError:
                self.last_row = None
            self.last_row = self.table_insert(row, 0)
            kids = self.table.get_children()
            if len(kids) > 400:
                self.table.delete(kids[-1])
