# Fichiers KiCad : cartes TrackLab à deux étages

| Fichier | Contenu |
|---|---|
| `TrackLab_etage1.net` | Netlist de l'étage 1 : supports du DevKit ESP32-S3 (J1, J3), support 2 × 16 (J_STACK), 4 trous M3 |
| `TrackLab_etage2.net` | Netlist de l'étage 2 : alimentation, CAN, entrées 12 V, potentiomètres, sorties, GPS, carte SD, LED, bouton |
| `nomenclature_etage1.csv`, `nomenclature_etage2.csv` | Liste des composants avec valeur et empreinte (ouvrables dans Excel) |
| `generer_netlist.py` | Génère tout ce qui précède ; les broches sont dans les tables en tête du fichier |

## Importer dans KiCad (version 7, 8 ou 9)
1. Créer un projet par carte (Fichier > Nouveau projet).
2. Ouvrir l'éditeur de circuit imprimé (Pcbnew), Fichier > Importer > **Netlist…**, choisir le `.net` de la carte.
3. Cliquer « Mettre à jour le circuit imprimé » : les empreintes arrivent empilées, avec leurs chevelus (lignes de liaison).
4. Si une empreinte n'est pas trouvée, Outils > Mettre à jour les empreintes, ou Éditer > Remplacer l'empreinte, et en choisir une équivalente.

La netlist remplace le schéma : pour garder un schéma lisible, redessiner dans Eeschema d'après le tableau ci-dessous et la page du plan, puis annoter. Vérifier avec ERC et DRC.

## Contour et trous (propositions, à valider)
- Étage 1 : 80 × 55 mm. DevKit à droite (bord USB-C au bord de la carte), antenne à gauche. Rien à moins de 15 mm de l'antenne.
- Étage 2 : 54 × 55 mm, aligné sur la droite de l'étage 1. Le module SD (environ 42 × 24 mm) et le module GPS sont encombrants : si l'implantation est trop serrée, allonger la carte vers le bas (par exemple 54 × 75 mm) sur les deux étages.
- 4 trous M3 aux coins de l'étage 2, mêmes positions sur l'étage 1. Sur l'étage 1, ne pas les placer sous le DevKit.
- Les supports J1 et J3 sont espacés de 22,86 mm (centre à centre). J_STACK de l'étage 2 doit tomber pile au-dessus de celui de l'étage 1 : le plus sûr est de placer le même J_STACK aux mêmes coordonnées sur les deux cartes.

## Ce qui reste à décider
- Empreintes réelles des connecteurs de la moto (J1 est un bornier 4 voies provisoire), du fusible F1 (1812 CMS) et du module abaisseur U1 (4 broches provisoires pour un module à souder).
- Brochage de la prise CAN de la moto (manuel d'atelier).
- Vérification du brochage du PESD2CAN et du SN65HVD230 sur la fiche du fabricant.
- La broche GPIO38 (OUT1) commande aussi la LED RGB du DevKit v1.1 ; elle clignote si le firmware la pilote. Sans effet sur la sortie.
- GPIO3 (ADC3, libre) est une broche de démarrage : ne rien brancher dessus.

Non testé : ni la netlist dans KiCad, ni la carte.
