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

# Identifiants des trames propres à l'ESP32 (ce ne sont pas des trames du bus CAN de la moto)
ESP_IDS = frozenset({0x7F0, 0x7F8, 0x7F9, 0x7FA})
ID_ESP_STATUS = 0x7FA
ID_ESP_REC = 0x7FB  # état de l'enregistrement
ID_FILE_LIST, ID_FILE_DATA, ID_FILE_CTL = 0x7FC, 0x7FD, 0x7FE  # liste et téléchargement des enregistrements
FILE_IDS = frozenset({ID_FILE_LIST, ID_FILE_DATA, ID_FILE_CTL})
ESP_IDS = ESP_IDS | {ID_ESP_REC} | FILE_IDS

# Fichier d'enregistrement de l'ESP32 (.trk) : en-tête « TRK1 » (16 octets) puis des enregistrements de 16 octets :
# temps ms (4, LE) | identifiant (2, LE) | DLC (1) | données (8) | XOR des 15 premiers octets
TRK_MAGIC = b"TRK1"
TRK_RECORD = 16
REC_ERRORS = {
    1: "aucun stockage disponible sur l'ESP32 (carte SD absente ?)",
    2: "fichier introuvable",
    3: "ce fichier est en cours d'enregistrement : arrêtez d'abord l'enregistrement",
    4: "erreur de lecture ou d'écriture sur le stockage de l'ESP32",
    5: "stockage plein : l'enregistrement a été arrêté",
}


def parse_trk(data):
    """Décode un fichier .trk : liste (temps_ms, identifiant, octets) ; les enregistrements corrompus sont ignorés."""
    if data[:4] != TRK_MAGIC:
        raise ValueError("ce n'est pas un enregistrement TrackLab (.trk)")
    out = []
    for i in range(16, len(data) - TRK_RECORD + 1, TRK_RECORD):
        r = data[i:i + TRK_RECORD]
        if xor_sum(r[:15]) != r[15]:
            continue
        dlc = min(r[6], 8)
        out.append((int.from_bytes(r[0:4], "little"), int.from_bytes(r[4:6], "little"), bytes(r[7:7 + dlc])))
    return out


def load_capture(path):
    with open(path, "rb") as f:
        if f.read(4) == TRK_MAGIC:
            f.seek(0)
            return parse_trk(f.read())
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
