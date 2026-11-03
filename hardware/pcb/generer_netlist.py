#!/usr/bin/env python3
"""Netlists KiCad (.net) et nomenclatures (.csv) des deux cartes TrackLab : étage 1 (ESP32-S3) et étage 2 (interface).

Importer dans Pcbnew : Fichier > Importer > Netlist... Toutes les broches viennent du firmware (rsv4_config_ESP32-S3.h)
et du brochage officiel de l'ESP32-S3-DevKitC-1 v1.1 (docs.espressif.com).
Usage : python3 generer_netlist.py [dossier_sortie]
"""
import csv
import os
import sys
import uuid
from collections import defaultdict

# empreintes de la bibliothèque standard de KiCad 7/8/9
FP = {
    "R": "Resistor_SMD:R_0805_2012Metric", "C": "Capacitor_SMD:C_0805_2012Metric",
    "CP": "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm", "LED": "LED_SMD:LED_0805_2012Metric",
    "SMA": "Diode_SMD:D_SMA", "SMB": "Diode_SMD:D_SMB", "DO41": "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    "FUSE": "Fuse:Fuse_1812_4532Metric", "SOIC8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "SOT23": "Package_TO_SOT_SMD:SOT-23",
    "TO220": "Package_TO_SOT_THT:TO-220-3_Vertical", "SW": "Button_Switch_THT:SW_PUSH_6mm",
    "JP": "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", "HOLE": "MountingHole:MountingHole_3.2mm_M3",
    "TB4": "TerminalBlock:TerminalBlock_bornier-4_P5.08mm",
}
def hdr(n, rows=1): return f"Connector_PinHeader_2.54mm:PinHeader_{rows}x{n:02d}_P2.54mm_Vertical"
def sock(n, rows=1): return f"Connector_PinSocket_2.54mm:PinSocket_{rows}x{n:02d}_P2.54mm_Vertical"

# ---- brochage de la liaison J_STACK (2 × 16) : numéro de broche -> réseau
STACK = {1: "+5V", 2: "+5V", 3: "GND", 4: "GND", 5: "+3V3", 6: "+3V3", 7: "CAN_TX", 8: "CAN_RX", 9: "GPS_RX", 10: "GPS_TX",
         11: "SD_CS", 12: "SD_MOSI", 13: "SD_SCK", 14: "SD_MISO", 15: "ENT1", 16: "ENT2", 17: "ENT3", 18: "ENT4", 19: "ENT5",
         20: "ENT6", 21: "ENT7", 22: "ENT8", 23: "ADC1", 24: "ADC2", 25: "ADC3", 26: "BTN_REC", 27: "OUT1", 28: "OUT2",
         29: "LED_G", 30: "LED_R", 31: "LED_B", 32: "GND"}

# ---- ESP32-S3-DevKitC-1 v1.1 : broches des deux rangées J1 et J3 -> réseau (absent = non raccordée)
J1 = {1: "+3V3", 2: "+3V3", 4: "CAN_RX", 5: "CAN_TX", 6: "GPS_TX", 7: "ENT1", 8: "BTN_REC", 9: "GPS_RX", 10: "LED_B", 11: "LED_R",
      12: "ENT2", 13: "ADC3", 15: "ENT3", 16: "SD_CS", 17: "SD_MOSI", 18: "SD_SCK", 19: "SD_MISO", 20: "ENT4", 21: "+5V", 22: "GND"}
J3 = {1: "GND", 4: "ADC1", 5: "ADC2", 6: "ENT7", 7: "ENT6", 8: "ENT5", 9: "OUT2", 10: "OUT1", 17: "ENT8", 18: "LED_G", 21: "GND", 22: "GND"}
J1_NAMES = ["3V3", "3V3", "RST", "GPIO4", "GPIO5", "GPIO6", "GPIO7", "GPIO15", "GPIO16", "GPIO17", "GPIO18", "GPIO8", "GPIO3",
            "GPIO46", "GPIO9", "GPIO10", "GPIO11", "GPIO12", "GPIO13", "GPIO14", "5V", "G"]
J3_NAMES = ["G", "TX", "RX", "GPIO1", "GPIO2", "GPIO42", "GPIO41", "GPIO40", "GPIO39", "GPIO38", "GPIO37", "GPIO36", "GPIO35",
            "GPIO0", "GPIO45", "GPIO48", "GPIO47", "GPIO21", "GPIO20", "GPIO19", "G", "G"]


class Board:
    def __init__(self, name):
        self.name, self.comps, self.pins = name, {}, defaultdict(list)

    def add(self, ref, value, fp, desc=""):
        assert ref not in self.comps, ref
        self.comps[ref] = (value, fp, desc)

    def wire(self, ref, pin, net, func=""):
        assert ref in self.comps, ref
        self.pins[net].append((ref, str(pin), func))


def etage1():
    b = Board("etage1")
    b.add("J1", "ESP32-S3-DevKitC-1 rangée J1", sock(22), "Support femelle 1x22 ; le DevKit s'y enfiche")
    b.add("J3", "ESP32-S3-DevKitC-1 rangée J3", sock(22), "Support femelle 1x22, à 22,86 mm de J1")
    b.add("J_STACK", "Support 2x16 vers étage 2", sock(16, 2), "Liaison entre étages (support femelle)")
    for i in range(1, 5):
        b.add(f"H{i}", "M3", FP["HOLE"], "Trou de fixation")
    for pin, net in J1.items():
        b.wire("J1", pin, net, J1_NAMES[pin - 1])
    for pin, net in J3.items():
        b.wire("J3", pin, net, J3_NAMES[pin - 1])
    for pin, net in STACK.items():
        b.wire("J_STACK", pin, net)
    return b


def etage2():
    b = Board("etage2")
    b.add("J_STACK", "Broches mâles 2x16 vers étage 1", hdr(16, 2), "Liaison entre étages (mâle, vers le bas)")
    for pin, net in STACK.items():
        b.wire("J_STACK", pin, net)
    for i in range(1, 5):
        b.add(f"H{i}", "M3", FP["HOLE"], "Trou de fixation")
    # ---- alimentation
    b.add("J1", "Moto : +12 V, GND, CAN H, CAN L", FP["TB4"], "Bornier 4 voies (à remplacer par un connecteur verrouillable)")
    for p, n, f in ((1, "+12V_RAW", "+12 V après contact"), (2, "GND", "masse"), (3, "CAN_H", "CAN H"), (4, "CAN_L", "CAN L")):
        b.wire("J1", p, n, f)
    b.add("F1", "2 A", FP["FUSE"], "Fusible 2 A, au plus près de l'entrée")
    b.wire("F1", 1, "+12V_RAW"); b.wire("F1", 2, "+12V_F")
    b.add("D1", "SS34", FP["SMA"], "Anti-inversion : anode sur +12V_F, cathode sur +12V_P")
    b.wire("D1", 2, "+12V_F", "A"); b.wire("D1", 1, "+12V_P", "K")
    b.add("D2", "SMBJ18A", FP["SMB"], "TVS unidirectionnelle")
    b.wire("D2", 1, "+12V_P", "K"); b.wire("D2", 2, "GND", "A")
    b.add("C1", "470uF 35V", FP["CP"], "Réservoir en entrée du régulateur")
    b.wire("C1", 1, "+12V_P", "+"); b.wire("C1", 2, "GND", "-")
    b.add("U1", "Module abaisseur 12V->5V (>= 2 A, entrée >= 30 V)", hdr(4), "Module à souder : 1 IN+, 2 IN-, 3 OUT+, 4 OUT-")
    b.wire("U1", 1, "+12V_P", "IN+"); b.wire("U1", 2, "GND", "IN-"); b.wire("U1", 3, "+5V_BUCK", "OUT+"); b.wire("U1", 4, "GND", "OUT-")
    b.add("D4", "SS34", FP["SMA"], "Évite le retour du 5 V USB du DevKit vers le régulateur")
    b.wire("D4", 2, "+5V_BUCK", "A"); b.wire("D4", 1, "+5V", "K")
    b.add("C2", "100nF", FP["C"], "Découplage 3,3 V du transceiver CAN")
    b.wire("C2", 1, "+3V3"); b.wire("C2", 2, "GND")
    # ---- CAN
    b.add("D3", "PESD2CAN", FP["SOT23"], "Protection CAN H / CAN L")
    b.wire("D3", 1, "CAN_H"); b.wire("D3", 2, "CAN_L"); b.wire("D3", 3, "GND")
    b.add("U2", "SN65HVD230", FP["SOIC8"], "Transceiver CAN 3,3 V (écoute seule côté firmware)")
    for p, n, f in ((1, "CAN_TX", "D"), (2, "GND", "GND"), (3, "+3V3", "VCC"), (4, "CAN_RX", "R"), (6, "CAN_L", "CANL"), (7, "CAN_H", "CANH"), (8, "GND", "Rs")):
        b.wire("U2", p, n, f)
    b.add("JP1", "Terminaison 120 ohm", FP["JP"], "Ouvert par défaut : la moto termine déjà le bus")
    b.wire("JP1", 1, "CAN_H"); b.wire("JP1", 2, "CAN_TERM")
    b.add("R_T", "120", FP["R"], "Résistance de terminaison (utile seulement sur banc)")
    b.wire("R_T", 1, "CAN_TERM"); b.wire("R_T", 2, "CAN_L")
    # ---- entrées 12 V (diviseur 10 k / 2,7 k + 100 nF)
    b.add("J_ENT", "Entrées 12 V : ENT1 à ENT8, GND, GND", hdr(10), "Broches 1 à 8 = ENT1 à ENT8, 9 et 10 = masse")
    for n in range(1, 9):
        b.wire("J_ENT", n, f"ENT{n}_RAW", f"ENT{n}")
        b.add(f"R{100 + n}", "10k", FP["R"], f"ENT{n} : haut du diviseur")
        b.wire(f"R{100 + n}", 1, f"ENT{n}_RAW"); b.wire(f"R{100 + n}", 2, f"ENT{n}")
        b.add(f"R{110 + n}", "2k7", FP["R"], f"ENT{n} : bas du diviseur")
        b.wire(f"R{110 + n}", 1, f"ENT{n}"); b.wire(f"R{110 + n}", 2, "GND")
        b.add(f"C{100 + n}", "100nF", FP["C"], f"ENT{n} : filtre")
        b.wire(f"C{100 + n}", 1, f"ENT{n}"); b.wire(f"C{100 + n}", 2, "GND")
    b.wire("J_ENT", 9, "GND"); b.wire("J_ENT", 10, "GND")
    # ---- potentiomètres de suspension
    b.add("J_POT", "Potentiomètres : (3V3, curseur, GND) x2", hdr(6), "1 3V3, 2 curseur AV, 3 GND, 4 3V3, 5 curseur AR, 6 GND")
    for p, n in ((1, "+3V3"), (2, "POT1_W"), (3, "GND"), (4, "+3V3"), (5, "POT2_W"), (6, "GND")):
        b.wire("J_POT", p, n)
    for k, adc in ((1, "ADC1"), (2, "ADC2")):
        b.add(f"R{200 + k}", "1k", FP["R"], f"Filtre curseur {k}")
        b.wire(f"R{200 + k}", 1, f"POT{k}_W"); b.wire(f"R{200 + k}", 2, adc)
        b.add(f"C{200 + k}", "100nF", FP["C"], f"Filtre curseur {k}")
        b.wire(f"C{200 + k}", 1, adc); b.wire(f"C{200 + k}", 2, "GND")
    # ---- sorties à MOSFET
    b.add("J_OUT", "Sorties : +12V, OUT1, +12V, OUT2", hdr(4), "1 +12V, 2 OUT1 (drain), 3 +12V, 4 OUT2 (drain)")
    b.wire("J_OUT", 1, "+12V_P"); b.wire("J_OUT", 3, "+12V_P")
    for k in (1, 2):
        b.wire("J_OUT", 2 * k, f"OUT{k}_D")
        b.add(f"Q{k}", "IRLZ44N", FP["TO220"], f"Sortie {k} (côté bas)")
        b.wire(f"Q{k}", 1, f"OUT{k}_G", "G"); b.wire(f"Q{k}", 2, f"OUT{k}_D", "D"); b.wire(f"Q{k}", 3, "GND", "S")
        b.add(f"R{300 + k}", "1k", FP["R"], f"Grille Q{k}")
        b.wire(f"R{300 + k}", 1, f"OUT{k}"); b.wire(f"R{300 + k}", 2, f"OUT{k}_G")
        b.add(f"R{310 + k}", "100k", FP["R"], f"Rappel grille Q{k}")
        b.wire(f"R{310 + k}", 1, f"OUT{k}_G"); b.wire(f"R{310 + k}", 2, "GND")
        b.add(f"D{10 + k}", "1N4007", FP["DO41"], f"Roue libre charge {k}")
        b.wire(f"D{10 + k}", 2, f"OUT{k}_D", "A"); b.wire(f"D{10 + k}", 1, "+12V_P", "K")
    # ---- GPS et carte SD (modules sur connecteurs)
    b.add("J_GPS", "GPS : VCC, RX module, TX module, GND", hdr(4), "Ordre du module GY-GPSV3 : 1 VCC (3,3 V), 2 RX du module, 3 TX du module, 4 GND")
    b.wire("J_GPS", 1, "+3V3", "VCC"); b.wire("J_GPS", 2, "GPS_TX", "RX module"); b.wire("J_GPS", 3, "GPS_RX", "TX module"); b.wire("J_GPS", 4, "GND", "GND")
    b.add("J_SD", "Module microSD SPI : GND, VCC, MISO, MOSI, SCK, CS", hdr(6), "Ordre du module : GND, VCC (5 V), MISO, MOSI, SCK, CS")
    for p, n, f in ((1, "GND", "GND"), (2, "+5V", "VCC"), (3, "SD_MISO", "MISO"), (4, "SD_MOSI", "MOSI"), (5, "SD_SCK", "SCK"), (6, "SD_CS", "CS")):
        b.wire("J_SD", p, n, f)
    # ---- LED et bouton
    for ref, col, net, r in (("G", "verte", "LED_G", "330"), ("R", "rouge", "LED_R", "330"), ("B", "bleue", "LED_B", "47")):
        b.add(f"R_{ref}", r, FP["R"], f"LED {col} : résistance série")
        b.wire(f"R_{ref}", 1, net); b.wire(f"R_{ref}", 2, f"{net}_A")
        b.add(f"LED_{ref}", f"LED {col}", FP["LED"], f"LED {col}")
        b.wire(f"LED_{ref}", 2, f"{net}_A", "A"); b.wire(f"LED_{ref}", 1, "GND", "K")
    b.add("SW1", "Bouton REC", FP["SW"], "Poussoir vers GND (appui = niveau bas)")
    b.wire("SW1", 1, "BTN_REC"); b.wire("SW1", 4, "GND")
    return b


def check(b):
    seen = set()
    for net, nodes in b.pins.items():
        for ref, pin, _ in nodes:
            assert (ref, pin) not in seen, f"{b.name}: {ref}.{pin} sur deux réseaux"
            seen.add((ref, pin))
    alone = [n for n, nodes in b.pins.items() if len(nodes) < 2]
    return alone


def write_net(b, path):
    ns = uuid.UUID("5c8a0d7e-0b6a-4f3e-9a52-7c0d2f6d1a11")
    out = ['(export (version "E")', '  (design', f'    (source "TrackLab_{b.name}.kicad_sch")', '    (date "2026-11-03")',
           '    (tool "generer_netlist.py"))', '  (components']
    q = lambda s: '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'
    for ref, (val, fp, desc) in b.comps.items():
        u = uuid.uuid5(ns, f"{b.name}/{ref}")
        out += [f"    (comp (ref {q(ref)})", f"      (value {q(val)})", f"      (footprint {q(fp)})",
                f'      (fields (field (name "Description") {q(desc)}))',
                '      (sheetpath (names "/") (tstamps "/"))', f"      (tstamps {q(u)}))"]
    out.append("  )")
    out.append("  (nets")
    for code, (net, nodes) in enumerate(sorted(b.pins.items()), 1):
        out.append(f"    (net (code {q(code)}) (name {q(net)})")
        for ref, pin, func in nodes:
            f = f" (pinfunction {q(func)})" if func else ""
            out.append(f"      (node (ref {q(ref)}) (pin {q(pin)}){f})")
        out[-1] += ")"
    out.append("  ))")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def write_bom(b, path):
    groups = defaultdict(list)
    for ref, (val, fp, desc) in b.comps.items():
        groups[(val, fp)].append((ref, desc))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Repères", "Quantité", "Valeur", "Empreinte KiCad", "Rôle"])
        for (val, fp), items in sorted(groups.items(), key=lambda kv: kv[1][0][0]):
            w.writerow([", ".join(r for r, _ in items), len(items), val, fp, items[0][1]])


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    for b in (etage1(), etage2()):
        alone = check(b)
        write_net(b, os.path.join(out, f"TrackLab_{b.name}.net"))
        write_bom(b, os.path.join(out, f"nomenclature_{b.name}.csv"))
        print(f"{b.name} : {len(b.comps)} composants, {len(b.pins)} réseaux ; réseaux à un seul nœud : {alone}")
