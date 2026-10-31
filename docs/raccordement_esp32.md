# Raccordement du boîtier ESP32

Schéma : `schema_raccordement.svg` (aussi `.png` et `.pdf`).

## Matériel
| Repère | Composant |
|---|---|
| ESP32 | DevKit ESP32-WROOM-32 (38 broches) |
| U2 | Transceiver CAN 3,3 V SN65HVD230 (module, résistance 120 Ω retirée) |
| U3 | Module GPS type NEO-M8N (UART) |
| F1 | Fusible 2 A |
| D1 | Diode SS34 (anti-inversion) |
| D2 | TVS SMBJ18A |
| C1 | 470 µF / 35 V |
| – | Convertisseur 12 V → 5 V, ≥ 2 A, entrée ≥ 30 V |
| D3 | PESD2CAN (option) |
| R1/R2 | 10 kΩ / 2,7 kΩ par entrée 12 V (+100 nF, Zener 3,3 V option) |
| R3/R4 | 10 kΩ / 20 kΩ par entrée analogique 0–5 V (+100 nF) |
| Q1 | MOSFET canal N niveau logique (IRLZ44N), R5 1 kΩ, R6 100 kΩ, D 1N4007 |

## Broches (réglage par défaut)
| Fonction | GPIO |
|---|---|
| CAN TXD / RXD | 5 / 4 |
| GPS (TX du module) | 16 |
| ENT1–8 | 13, 14, 27, 26, 25, 33, 18, 19 |
| ADC1–3 | 32, 34, 35 |
| SORTIE1–2 | 2, 23 |

## Précautions
- Pas de terminaison 120 Ω ; masse commune ; fusible près de la batterie.
- Brochage de la prise CAN de la moto : à vérifier dans le manuel d'atelier.
- Strapping : GPIO2 (sortie) ne doit pas être tiré haut au démarrage ; GPIO5 est aussi une broche de strapping.
- Firmware non testé sur matériel.
