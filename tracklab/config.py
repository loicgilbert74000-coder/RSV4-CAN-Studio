"""Constantes de l'application : modèles de moto, tables de signaux, groupes d'affichage, réglages."""

from .signals import SIGNALS as _TOUS

# Équipements de moto de route : sans objet sur une moto de piste, ils ne sont ni décodés ni proposés.
ROUTE_SEULEMENT = {
    "HiBeam", "Fuel_Low", "Fuel_Res_St", "Fuel_Level", "Fuel_Cons", "Right_Dir", "Left_Dir", "226B0", "226B1", "226B2",
    "SideStand_Sw", "Odometer", "Urg_serv", "MIL", "TC_menu_set_butt", "Dir_Conn_Buttons", "Joystick", "Joystick_Pushed",
}
SIGNALS = [s for s in _TOUS if s[1] not in ROUTE_SEULEMENT]

SPEEDS = {"x0.25": 0.25, "x0.5": 0.5, "x1": 1, "x2": 2, "x4": 4, "x8": 8}
BAND_MIN = 56  # hauteur mini et maxi d'une bande en mode empilé (px)
BAND_MAX = 700
WINDOWS = [10, 30, 60, 120, 300, 600]  # fenêtres temporelles des courbes (s)
SEEK_BACK = 20000  # trames rejouées avant l'instant visé quand on clique dans la barre de progression

# Profils de moto. "decoder" : décodages CAN définis pour ce modèle (None = trames brutes seulement).
MODELS = {
    "rsv4": {
        "label": "Aprilia RSV4 Factory 2024",
        "decoder": "aprilia",
        "rpm_max": 16000,
        "speed_max": 320,
        "validated": ("throttle",),
        "bitrates": ["250 kbit/s"],
        "bitrate": "250 kbit/s",
        "short": "Poignée seule",
        "note": "Seule la poignée de gaz est validée · TPS1 / TPS2 non identifiés dans vos captures",
    },
    "cbr1000rr_r_2021": {
        "label": "Honda CBR1000RR-R Fireblade 2021",
        "decoder": None,
        "rpm_max": 15000,
        "speed_max": 300,
        "validated": (),
        "bitrates": ["Non défini"],
        "bitrate": None,
        "short": "Trames brutes",
        "note": "Aucun décodage CAN défini pour ce modèle · trames brutes uniquement, valeurs non interprétées",
    },
}

# Signaux générés depuis can1.xml, plus les données de l'ESP32 (GPS et entrées/sorties).
# Les identifiants 0x7F0, 0x7F8 et 0x7F9 ne sont pas dans la définition : ce sont des trames de l'ESP32.
VIRTUAL = [
    (2032, "GPS Latitude", 0, 0, 0, 0, "°"),
    (2032, "GPS Longitude", 0, 0, 0, 0, "°"),
    (2040, "GPS Vitesse", 0, 0, 0, 0, "km/h"),
    (2040, "GPS Cap", 0, 0, 0, 0, "°"),
    (2040, "Satellites", 0, 0, 0, 0, ""),
    (2040, "Qualité fix", 0, 0, 0, 0, ""),
] + [
    (2041, f"Entrée {i + 1}", 0, 0, 0, 0, "") for i in range(8)
] + [(2041, f"ADC {j + 1}", 0, 0, 0, 0, "") for j in range(3)]
TILE_DEFS = list(SIGNALS) + VIRTUAL
BY_CID = {}
for _s in SIGNALS:
    BY_CID.setdefault(_s[0], []).append(_s)
CURVE_KEYS = list(dict.fromkeys(((s[0], s[1]) for s in TILE_DEFS)))
CURVE_INDEX = {k: i for i, k in enumerate(CURVE_KEYS)}
UNIT_OF = {(s[0], s[1]): s[6] for s in TILE_DEFS}

# Groupes d'affichage sur la page Télémétrie
GROUP_OF = {
    256: "Moteur",
    276: "Moteur",
    1537: "Gaz",
    2034: "Gaz",
    2038: "Gaz",
    608: "Roues",
    258: "Freins & sécurité",
    609: "Freins & sécurité",
    260: "Modes & aides",
    560: "Modes & aides",
    262: "Couple",
    264: "Commandes",
    768: "Commandes",
    372: "IMU · centrale inertielle",
    376: "IMU · centrale inertielle",
    610: "IMU · centrale inertielle",
    512: "Températures & électrique",
    546: "Carburant & air",
    550: "Clignotants",
    544: "Divers",
    548: "Divers",
    552: "Divers",
    898: "Non identifié",
    2032: "GPS",
    2040: "GPS",
    2041: "E/S ESP32",
}
GROUP_ORDER = [
    "Moteur",
    "Gaz",
    "Roues",
    "Freins & sécurité",
    "Modes & aides",
    "Couple",
    "IMU · centrale inertielle",
    "GPS",
    "E/S ESP32",
    "Températures & électrique",
    "Carburant & air",
    "Clignotants",
    "Commandes",
    "Divers",
    "Non identifié",
    "Autres",
]

# Signaux décodés à la main (décodage de l'appli). Ils remplacent la définition pour ces trames.
HAND_ALWAYS = {(1537, "Hand_Throttle"), (2034, "RSV4_TPS1"), (2034, "RSV4_TPS2")}
HAND_EXPERIMENTAL = {
    (256, "RPM"),
    (256, "Gear"),
    (256, "Bike_Speed"),
    (512, "Engine_Temp"),
    (512, "Oil_Temp"),
    (512, "Battery_Volt"),
    (608, "Speed_Front"),
    (608, "Speed_Rear"),
}
DEFAULT_CURVES = [
    (256, "RPM"),
    (256, "Bike_Speed"),
    (1537, "Hand_Throttle"),
    (512, "Engine_Temp"),
    (608, "Speed_Front"),
    (608, "Speed_Rear"),
]
