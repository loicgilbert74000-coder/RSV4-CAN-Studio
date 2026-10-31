"""Lecture des captures USB-CAN, trames Wi-Fi de l'ESP32 et extraction de bits."""

import re

# Exports USB-CAN: NUL between columns; frame ID 8-digit hex, DLC, bytes.
LINE = re.compile(
    "Receive\\s+(\\d{2}:\\d{2}:\\d{2}:\\d{3}).*?(?:Standard|Extended)\\s+frame\\s+([0-9a-fA-F]{8})\\s+([0-8])\\s+((?:[0-9a-fA-F]{2}\\s*){1,8})",
    re.I,
)

# Trame Wi-Fi (ESP32) : 0xA5 0x5A | temps ms (4, LE) | identifiant (4, LE) | DLC (1) | 8 octets | XOR des octets 2 à 18
WIFI_MAGIC = b"\xa5Z"
WIFI_FRAME_LEN = 20


def load_capture(path):
    out = []
    with open(path, "r", encoding="latin1", errors="replace") as f:
        for line in f:
            m = LINE.search(line.replace("\x00", " "))
            if not m:
                continue
            try:
                hh, mm, ss, ms = map(int, m.group(1).split(":"))
                stamp = ((hh * 60 + mm) * 60 + ss) * 1000 + ms
                dlc = int(m.group(3))
                data = bytes.fromhex(m.group(4))[:dlc]
                if len(data) == dlc:
                    out.append((stamp, int(m.group(2), 16), data))
            except ValueError:
                pass
    if out:
        base = out[0][0]
        out = [((t - base) % 86400000, c, d) for t, c, d in out]
    return out


def extract_bits(data, sbit, blen):
    """Lit blen bits à partir de sbit (bit de poids fort en premier, comme la définition AiM)."""
    v = 0
    for k in range(blen):
        pos = sbit + k
        byte = pos // 8
        if byte >= len(data):
            return None
        v = v << 1 | data[byte] >> 7 - pos % 8 & 1
    return v


def xor_sum(b):
    x = 0
    for v in b:
        x ^= v
    return x
