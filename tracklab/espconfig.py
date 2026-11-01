"""Paramétrage de l'ESP32 : valeurs par défaut, contrôle et génération de l'en-tête C du firmware."""

# Paramétrage ESP32 : valeurs par défaut (broches d'un ESP32 DevKit)
DIG_DEFAULT = [
    (13, "Entrée 1", False),
    (14, "Entrée 2", False),
    (27, "Entrée 3", False),
    (26, "Entrée 4", False),
    (25, "Entrée 5", False),
    (33, "Entrée 6", False),
    (18, "Entrée 7", False),
    (19, "Entrée 8", False),
]
ANA_DEFAULT = [(32, "Suspension avant", True), (34, "Suspension arrière", True), (35, "ADC 3", False)]
# Voyants à côté du tableau de bord : (broche, couleur)
LED_DEFAULT = {"green": 21, "red": 22, "blue": 17}
# Enregistrement : bouton poussoir (vers GND) et module carte SD (SPI)
REC_DEFAULT = {"button": 15, "sd": True, "cs": 10, "mosi": 11, "miso": 13, "sck": 12}
OUT_DEFAULT = [(2, "Sortie 1", "Bas", False), (23, "Sortie 2", "Bas", False)]


# Broches proposées selon la carte (les broches d'un ESP32 classique ne conviennent pas à un ESP32-S3)
BOARDS = {
    "ESP32 classique (DevKit 38 broches)": {
        "can": (5, 4), "gps": 16, "gps_tx": 12, "dig": [14, 27, 26, 25, 33, 36, 39, 0],
        "ana": [32, 34, 35], "out": [2, 0], "leds": {"green": 21, "red": 22, "blue": 17},
        "rec": {"button": 15, "sd": True, "cs": 13, "mosi": 23, "miso": 19, "sck": 18},
    },
    "ESP32-S3 (DevKitC-1)": {
        "can": (5, 4), "gps": 16, "gps_tx": 6, "dig": [7, 8, 9, 14, 40, 41, 42, 47],
        "ana": [1, 2, 3], "out": [38, 39], "leds": {"green": 21, "red": 18, "blue": 17},
        "rec": {"button": 15, "sd": True, "cs": 10, "mosi": 11, "miso": 13, "sck": 12},
    },
}


def rec_of(cfg):
    """Réglages de l'enregistrement (valeurs par défaut si l'ancien fichier n'en contient pas)."""
    return {**REC_DEFAULT, **cfg.get("rec", {})}


def leds_of(cfg):
    """Broches des voyants vert / rouge / bleu (valeurs par défaut si l'ancien fichier n'en contient pas)."""
    return {**LED_DEFAULT, **cfg.get("leds", {})}


def c_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def validate_cfg(cfg):
    """Vérifie la configuration ESP32 ; lève ValueError avec un message lisible."""
    w = cfg["wifi"]
    if not 1 <= len(w["ssid"]) <= 32:
        raise ValueError("Le nom du réseau (SSID) doit faire entre 1 et 32 caractères.")
    if w["password"] and (not 8 <= len(w["password"]) <= 63):
        raise ValueError("Le mot de passe Wi-Fi doit faire 8 à 63 caractères.")
    if not 1 <= w["channel"] <= 13:
        raise ValueError("Le canal Wi-Fi doit être compris entre 1 et 13.")
    if not 1 <= w["tcp_port"] <= 65535:
        raise ValueError("Le port TCP doit être compris entre 1 et 65535.")
    pins = [cfg["can"]["tx_pin"], cfg["can"]["rx_pin"]] if cfg["can"].get("enabled", True) else []
    if cfg["gps"]["enabled"]:
        pins.append(cfg["gps"]["rx_pin"])
        if cfg["gps"].get("tx_pin", -1) >= 0:
            pins.append(cfg["gps"]["tx_pin"])
    for grp in ("digital_inputs", "analog_inputs", "outputs"):
        for e in cfg[grp]:
            if e["enabled"]:
                pins.append(e["pin"])
    pins += list(leds_of(cfg).values())
    rec = rec_of(cfg)
    pins.append(rec["button"])
    if rec["sd"]:
        pins += [rec["cs"], rec["mosi"], rec["miso"], rec["sck"]]
    for p in pins:
        if not 0 <= p <= 48:
            raise ValueError(f"Broche {p} hors plage (0 à 48).")
    if cfg["can"]["bitrate_kbps"] not in (250, 500):
        raise ValueError("Le débit CAN doit être 250 ou 500 kbit/s.")


def make_header(cfg):
    """Fichier rsv4_config.h lu par le firmware ESP32 à la compilation."""
    w, c, g = (cfg["wifi"], cfg["can"], cfg["gps"])
    dig, ana, out = (cfg["digital_inputs"], cfg["analog_inputs"], cfg["outputs"])
    leds = leds_of(cfg)
    rec = rec_of(cfg)
    def arr(vals, ctype):
        return "{" + ", ".join((str(v) for v in vals)) + "}"
    lines = [
        "// Fichier généré par TrackLab Electronics (Paramétrage ESP32). Ne pas modifier à la main.",
        "#pragma once",
        f"#define AP_SSID {c_str(w['ssid'])}",
        f"#define AP_PASS {c_str(w['password'])}",
        f"#define AP_CHANNEL {int(w['channel'])}",
        f"#define TCP_PORT {int(w['tcp_port'])}",
        f"#define CAN_ENABLED {(1 if c.get('enabled', True) else 0)}",
        f"#define CAN_TX_PIN {int(c['tx_pin'])}",
        f"#define CAN_RX_PIN {int(c['rx_pin'])}",
        f"#define CAN_BITRATE_KBPS {int(c['bitrate_kbps'])}",
        f"#define GPS_ENABLED {(1 if g['enabled'] else 0)}",
        f"#define GPS_RX_PIN {int(g['rx_pin'])}",
        f"#define GPS_TX_PIN {int(g.get('tx_pin', -1))}",
        f"#define GPS_BAUD {int(g['baud'])}",
        f"#define DIG_COUNT {len(dig)}",
        f"static const int DIG_PIN[DIG_COUNT] = {arr([e['pin'] for e in dig], 'int')};",
        f"static const bool DIG_ON[DIG_COUNT] = {arr([1 if e['enabled'] else 0 for e in dig], 'bool')};",
        f"#define ANA_COUNT {len(ana)}",
        f"static const int ANA_PIN[ANA_COUNT] = {arr([e['pin'] for e in ana], 'int')};",
        f"static const bool ANA_ON[ANA_COUNT] = {arr([1 if e['enabled'] else 0 for e in ana], 'bool')};",
        f"#define OUT_COUNT {len(out)}",
        f"static const int OUT_PIN[OUT_COUNT] = {arr([e['pin'] for e in out], 'int')};",
        f"static const bool OUT_ON[OUT_COUNT] = {arr([1 if e['enabled'] else 0 for e in out], 'bool')};",
        f"static const bool OUT_HIGH[OUT_COUNT] = {arr([1 if e['level'] == 'Haut' else 0 for e in out], 'bool')};",
        f"#define REC_BTN_PIN {int(rec['button'])}",
        f"#define REC_SD_ENABLED {(1 if rec['sd'] else 0)}",
        f"#define SD_CS_PIN {int(rec['cs'])}",
        f"#define SD_MOSI_PIN {int(rec['mosi'])}",
        f"#define SD_MISO_PIN {int(rec['miso'])}",
        f"#define SD_SCK_PIN {int(rec['sck'])}",
        f"#define LED_GREEN_PIN {int(leds['green'])}",
        f"#define LED_RED_PIN {int(leds['red'])}",
        f"#define LED_BLUE_PIN {int(leds['blue'])}",
    ]
    return "\n".join(lines) + "\n"
