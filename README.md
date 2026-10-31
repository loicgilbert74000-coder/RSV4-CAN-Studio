# TrackLab Electronics

Application Windows (Python / tkinter) de télémétrie et de diagnostic CAN pour moto, avec relais Wi-Fi par ESP32.
Elle lit une capture USB-CAN (`.txt`), une liaison USB-CAN en direct ou le flux Wi-Fi de l'ESP32, et affiche
les données en direct, en courbes et en trames brutes.

## Lancer

```
pip install pyserial
python TrackLab_Electronics.py
```

## Organisation du code

| Fichier | Rôle |
|---|---|
| `TrackLab_Electronics.py` | point d'entrée |
| `tracklab/app.py` | fenêtre principale, menu, barre de lecture, boucle d'affichage |
| `tracklab/page_telemetry.py` | page Télémétrie (jauges et tuiles) |
| `tracklab/page_graph.py` | page Courbes (axes, empilement, séparateurs, ascenseurs) |
| `tracklab/page_frames.py` | page Trames CAN et filtres |
| `tracklab/page_esp.py` | paramétrage de l'ESP32 |
| `tracklab/player.py` | chargement, lecture, saut dans une capture |
| `tracklab/decoding.py` | décodage des trames |
| `tracklab/connection.py` | liaison série USB-CAN et Wi-Fi |
| `tracklab/widgets.py` | widgets dessinés sur Canvas (jauges, tuiles, listes, icônes) |
| `tracklab/config.py`, `theme.py`, `names.py`, `util.py`, `protocol.py`, `espconfig.py` | constantes, couleurs, noms français des signaux, outils, formats de trames, configuration ESP32 |
| `tracklab/signals.py` | signaux générés depuis la définition AiM (`can1.xml`) |
| `firmware/esp32_can_wifi/` | firmware de l'ESP32 (non testé sur matériel) |

Les pages sont des « mixins » assemblés par `App`. Les listes de plusieurs centaines d'éléments (tuiles, signaux)
sont dessinées sur un seul Canvas : le changement de page reste fluide.

## Test

```
python tests/smoke_test.py CAPTURE.txt            # sous Linux : xvfb-run -a python tests/smoke_test.py CAPTURE.txt
```

## Compilation Windows

Le workflow GitHub Actions `windows-exe.yml` produit l'exécutable et l'installateur (Inno Setup).
