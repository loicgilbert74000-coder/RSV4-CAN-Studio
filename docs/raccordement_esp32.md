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
| P (×2) | Potentiomètre linéaire 10 kΩ de débattement (fourche, amortisseur), alimenté en +3,3 V ; R3 1 kΩ + 100 nF sur chaque curseur |
| LED (×3) | Verte et rouge : 330 Ω ; bleue : 47 Ω (LED haute luminosité) |
| Q1 | MOSFET canal N niveau logique (IRLZ44N), R5 1 kΩ, R6 100 kΩ, D 1N4007 |

## Broches (réglage par défaut)
| Fonction | GPIO |
|---|---|
| CAN TXD / RXD | 5 / 4 |
| GPS (TX du module → ESP32) | 16 |
| GPS (RX du module ← ESP32) | 12 |
| ENT1–8 | 13, 14, 27, 26, 25, 33, 18, 19 |
| ADC1 = suspension avant | 32 |
| ADC2 = suspension arrière | 34 |
| ADC3 (libre) | 35 |
| SORTIE1–2 | 2, 23 |
| LED verte / rouge / bleue | 21 / 22 / 17 |

## Précautions
- Pas de terminaison 120 Ω ; masse commune ; fusible près de la batterie.
- Brochage de la prise CAN de la moto : à vérifier dans le manuel d'atelier.
- Strapping : GPIO2 (sortie) ne doit pas être tiré haut au démarrage ; GPIO5 est aussi une broche de strapping.
- Firmware non testé sur matériel.

## Potentiomètres de suspension
Chaque potentiomètre : une extrémité au +3,3 V, l'autre à la masse, curseur → 1 kΩ → GPIO (avec 100 nF vers la masse).
L'application affiche les valeurs brutes (0–4095) « Suspension avant / arrière » et le débattement en % (« Débattement avant / arrière »).

## Voyants (LED)
- Verte : clignote = Wi-Fi prêt sans PC ; fixe = application connectée.
- Bleue : éclat à chaque trame CAN reçue.
- Rouge : fixe = contrôleur CAN en défaut ; clignote = aucune trame CAN depuis 3 s.
- Test au démarrage : les trois s'allument à tour de rôle.

## ESP32-S3 : schéma rév. 4 (`schema_raccordement_ESP32-S3.*`)
| Fonction | GPIO (ESP32-S3 DevKitC-1) |
|---|---|
| CAN TXD / RXD | 5 / 4 |
| GPS (TX du module → ESP32) | 16 |
| GPS (RX du module ← ESP32) | 6 |
| ENT1–8 | 7, 8, 9, 14, 40, 41, 42, 47 |
| Suspension avant / arrière / ADC3 libre | 1 / 2 / 3 |
| SORTIE1–2 | 38, 39 |
| LED verte / rouge / bleue | 21 / 18 / 17 |
| Bouton d'enregistrement (vers GND) | 15 |
| Carte SD : CS / MOSI / SCK / MISO | 10 / 11 / 12 / 13 |

## Enregistrement
- Un appui sur le bouton (ou « ● Enreg. » dans TrackLab) démarre l'enregistrement, un autre l'arrête. La LED rouge fait un éclat par seconde pendant l'enregistrement.
- Fichiers `/rec/NNNN.trk` sur la carte SD (sinon mémoire interne, quelques minutes seulement) : trames CAN, GPS et E/S avec leur horodatage.
- TrackLab, page Paramétrage ESP32, carte « Enregistrement » : liste, « Récupérer et ouvrir », « Récupérer », « Supprimer ». Les fichiers sont sauvegardés dans `Documents\\TrackLab\\Enregistrements` ; le bouton « Ouvrir un fichier » de TrackLab lit aussi les `.trk`.

## GPS à 10 Hz : fil ESP32 → RX du GPS
Pour régler le GPS à 10 Hz, le firmware doit envoyer des commandes au module : il faut donc relier la broche GPS TX de l'ESP32 (S3 : GPIO6 ; ESP32 classique : GPIO12) à l'entrée RX du module GPS (logique 3,3 V). Sans ce fil, le GPS fonctionne mais reste à 1 Hz.
