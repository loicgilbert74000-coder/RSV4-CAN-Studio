# Test CAN (moniteur série)

Petit programme d'essai : l'ESP32 écoute le bus CAN et affiche **toutes** les trames dans le moniteur série.
Il n'émet jamais sur le bus (écoute seule). Il remplace l'USBCAN pour vérifier la moto ou le module.

1. Arduino IDE : ouvrir `esp32_can_test.ino`, carte « ESP32S3 Dev Module » (ou ESP32 Dev Module), téléverser.
2. Moniteur série à **921600 bauds**, fin de ligne « Nouvelle ligne » ou « Aucune ».
3. Au démarrage, il cherche seul le débit (1 Mbit/s, 800, 500, 250, 125 kbit/s, 3 s chacun) et garde celui qui donne des trames lisibles.
4. Commandes : `a` recherche automatique · `1` à `5` forcer le débit · `r` résumé par identifiant / toutes les trames.

Branchement : TXD du module → GPIO5, RXD → GPIO4, 3,3 V, GND commun. Module sans résistance de 120 Ω sur la moto.
Les lignes `[état]` donnent les erreurs de bus : beaucoup d'erreurs = mauvais débit ou mauvaise liaison.
