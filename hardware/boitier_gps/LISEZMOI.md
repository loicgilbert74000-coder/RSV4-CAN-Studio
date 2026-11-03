# Boîtier GPS TrackLab (impression 3D)

Deux pièces : **coque** (dessus, gravure « TRACKLAB GPS », antenne sous le dessus) et **fond** (plaque avec plots pour la carte et gorge de joint).
Dimensions : 56,8 × 35,8 mm, hauteur 19 mm assemblé (14,5 coque + 4,5 fond), goulot de câble en plus (+8 mm). Pas d'oreilles : la fermeture se fait par 4 vis cachées sous le fond, collé ensuite sur la coque arrière.

## Hypothèses à vérifier (modifiables en tête de `generer_boitier.py`)
- Carte GPS 36 × 27 × 1,6 mm, antenne céramique 25 × 25 × 4 mm posée au-dessus de la carte. Les plots de 3 mm et les cales d'angle supposent une carte sans connecteur sur sa face inférieure.
- Câble de Ø 3 à 5 mm : trou de 5,2 mm.

## Assemblage
1. Coque : 4 inserts à chaud M3 (Ø 4,2 × 6 mm de profondeur) dans les colonnes intérieures ; fond : cordon silicone Ø 2 mm (ou joint TPU) dans la gorge.
2. Carte sur les plots, antenne collée sous le dessus entre les 4 cales ; câble passé dans le goulot, soudé à la carte.
3. Résine ou silicone dans le goulot, gaine thermorétractable à colle par-dessus (gorge pour un collier).
4. Coque posée sur le fond, 4 vis M3 × 8 serrées par le dessous (têtes dans les lamages du fond).
5. Fond collé sur la coque arrière avec du ruban double face 3M VHB (surface dégraissée et plane).

## Impression
PETG ou ASA, couche 0,2 mm, 4 parois, remplissage 40 % ou plus. Le STL de la coque est déjà retourné (dessus sur le plateau, gravure lisse) : support uniquement sous le goulot. Le fond s'imprime à plat. Pas de fibre de carbone ni de métal (brouille le GPS).

Étanchéité non testée : à valider (bain d'eau, test de pression) avant montage sur la moto.

Régénérer : `python3 generer_boitier.py sortie 0.35` (numpy, scipy, Pillow) ; aperçus : `python3 apercu.py sortie`.
