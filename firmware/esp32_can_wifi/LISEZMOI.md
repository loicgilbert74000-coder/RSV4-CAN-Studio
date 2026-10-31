# Firmware ESP32 — TrackLab Electronics (v2.1)

Relais CAN (écoute seule) + GPS + entrées/sorties vers l'application, par Wi-Fi.

## Installation
1. Arduino IDE, carte **ESP32 Dev Module** (paquet « esp32 » d'Espressif, versions 2.x ou 3.x).
2. Placer `esp32_can_wifi.ino` et `rsv4_config.h` dans un même dossier `esp32_can_wifi/`.
3. (Facultatif) générer un `rsv4_config.h` personnalisé depuis la page **Paramétrage ESP32** de l'application.
4. Téléverser, ouvrir le moniteur série à 115200 bauds : bannière « TrackLab Electronics … v2.1 » et statistiques CAN toutes les 5 s.

## Utilisation
- L'ESP32 crée le réseau Wi-Fi `RSV4-CAN` (mot de passe par défaut `rsv4-can-2026` — à changer dans `rsv4_config.h`).
- Se connecter avec le PC, puis dans l'application : Connexion → Wi-Fi ESP32 → `192.168.4.1`, port `2323`.
- Trame émise : 20 octets `A5 5A | t(4) | id(4) | dlc | 8 données | XOR`.
- Broches par défaut : CAN TX=GPIO5, RX=GPIO4 ; GPS RX=GPIO16 ; voir `docs/raccordement_esp32.md`.

## Potentiomètres et voyants
- ADC1 (GPIO32) = suspension avant, ADC2 (GPIO34) = suspension arrière, activés par défaut (0–3,3 V).
- LED : verte GPIO21 (liaison), rouge GPIO22 (défaut CAN), bleue GPIO17 (activité CAN) ; broches modifiables dans la page Paramétrage ESP32.

## Remarques
- Contrôleur CAN en **écoute seule** : le boîtier n'émet jamais sur le bus.
- Débit GPS : beaucoup de modules NEO-M8N sortent d'usine à 9600 bauds ; la config par défaut est 115200 → régler `GPS_BAUD`.
- **Non testé sur matériel** : valider d'abord sur table.

## Carte ESP32-S3
Les broches par défaut sont celles d'un ESP32 classique. Avec une ESP32-S3 (carte « ESP32S3 Dev Module »), utiliser `rsv4_config_ESP32-S3.h` : le copier dans le dossier du firmware sous le nom `rsv4_config.h`.
Broches S3 : CAN TX 5 / RX 4, GPS RX 16, potentiomètres GPIO1 (avant) et GPIO2 (arrière), LED verte 21 / rouge 18 / bleue 17.
Le firmware ignore (et signale sur le port série) toute broche inexistante ou réservée (flash, PSRAM).
