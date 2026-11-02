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
| `tracklab/app.py` | fenêtre principale, barre du haut (logo, moto, pages, connexion), barre de lecture, boucle d'affichage |
| `tracklab/page_telemetry.py` | page Télémétrie (jauges et tuiles) |
| `tracklab/page_graph.py` | page Courbes (axes, empilement, séparateurs, ascenseurs) |
| `tracklab/page_frames.py` | page Trames Tracklab et filtres |
| `tracklab/page_esp.py` | paramétrage de l'ESP32 |
| `tracklab/player.py` | chargement, lecture, saut dans une capture |
| `tracklab/decoding.py` | décodage des trames |
| `tracklab/connection.py` | fenêtre de connexion, liaison série USB-CAN et Wi-Fi |
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

## Fichiers ouverts, courbes et enregistrements Tracklab

- **Ouvrir** propose un fichier du PC ou un enregistrement Tracklab (ouvrir ou supprimer). Pour un fichier du PC, le type est reconnu tout seul : capture USB-CAN (TXT), moniteur série de l'ESP32, `.trk`, RaceChrono (CSV/VBO), RaceBox (CSV) ou tout CSV avec GPS.
- **Enregistrements Tracklab** : dès la connexion, les fichiers de la carte absents du PC sont téléchargés automatiquement dans `Documents/TrackLab/Enregistrements`. La liste (page Paramétrage Tracklab) indique date, taille, emplacement (carte / PC) et état.
- **Courbes** : tous les signaux sont listés par type (grisés quand le fichier n'en contient pas) ; à l'ouverture d'un fichier, les signaux significatifs sont activés automatiquement. Croix pour retirer un signal, abscisse en mm:ss:ms. Molette : zoom ; clic molette + glisser : déplacement ; clic gauche + glisser : zoom sur la zone ; double-clic : tout voir.
- **Platine** : touches façon lecteur CD, afficheur (mode, source, vue, temps, fichier) avec bargraph cliquable, touches Enreg. et Connexion.
- **Trames Tracklab** : bouton « Arrêter le direct » / « Reprendre le direct » (la réception continue).
