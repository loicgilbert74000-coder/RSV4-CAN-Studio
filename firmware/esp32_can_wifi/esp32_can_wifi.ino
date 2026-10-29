/*
 * RSV4 CAN Studio — relais CAN -> Wi-Fi pour ESP32 (NON TESTÉ sur matériel)
 *
 * Fonctionnement :
 *   - L'ESP32 crée son propre réseau Wi-Fi (point d'accès) : SSID "RSV4-CAN".
 *   - Le PC se connecte à ce réseau, puis l'application se connecte à 192.168.4.1:2323.
 *   - Le contrôleur CAN de l'ESP32 est en mode ÉCOUTE SEULE (listen-only) :
 *     il ne transmet jamais de trame et n'acquitte pas le bus.
 *
 * Protocole (une trame = 20 octets, tous les champs multi-octets en little-endian) :
 *   octets 0-1   : 0xA5 0x5A  (marqueur de début)
 *   octets 2-5   : temps en millisecondes depuis le démarrage de l'ESP32
 *   octets 6-9   : identifiant CAN (11 bits)
 *   octet 10     : DLC (longueur des données, 0 à 8)
 *   octets 11-18 : données (complétées par des zéros)
 *   octet 19     : XOR des octets 2 à 18
 *
 * Matériel : un transceiver CAN (ex. SN65HVD230) relié à TX_PIN / RX_PIN ci-dessous.
 * Le débit par défaut est 250 kbit/s (RSV4). Changer BITRATE_250K si nécessaire.
 * Alimentation : la moto doit passer par un régulateur 5 V avant l'ESP32.
 *
 * Bibliothèque : cœur Arduino pour ESP32 (driver TWAI intégré).
 */
#include <WiFi.h>
#include <string.h>
#include "driver/twai.h"

const char* AP_SSID = "RSV4-CAN";
const char* AP_PASS = "rsv4-can-2026";   // 8 caractères minimum
const uint16_t TCP_PORT = 2323;

const gpio_num_t TX_PIN = GPIO_NUM_5;    // vers le transceiver CAN
const gpio_num_t RX_PIN = GPIO_NUM_4;    // vers le transceiver CAN
#define BITRATE_250K 1                   // 1 = 250 kbit/s, 0 = 500 kbit/s

WiFiServer server(TCP_PORT);
WiFiClient client;

static void sendFrame(const twai_message_t& m) {
  uint8_t p[20];
  memset(p, 0, sizeof(p));
  p[0] = 0xA5; p[1] = 0x5A;
  uint32_t t = millis();
  memcpy(p + 2, &t, 4);
  uint32_t id = m.identifier;
  memcpy(p + 6, &id, 4);
  uint8_t dlc = m.data_length_code > 8 ? 8 : m.data_length_code;
  p[10] = dlc;
  memcpy(p + 11, m.data, dlc);
  uint8_t x = 0;
  for (int i = 2; i < 19; i++) x ^= p[i];
  p[19] = x;
  client.write(p, sizeof(p));
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  server.begin();
  Serial.print("Wi-Fi RSV4-CAN prêt, adresse "); Serial.println(WiFi.softAPIP());

#if BITRATE_250K
  twai_timing_config_t timing = TWAI_TIMING_CONFIG_250KBITS();
#else
  twai_timing_config_t timing = TWAI_TIMING_CONFIG_500KBITS();
#endif
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(TX_PIN, RX_PIN, TWAI_MODE_LISTEN_ONLY);
  twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  if (twai_driver_install(&general, &timing, &filter) != ESP_OK || twai_start() != ESP_OK) {
    Serial.println("Erreur : contrôleur CAN non démarré");
  }
}

void loop() {
  // Une seule connexion à la fois : on accepte un nouveau client si le précédent est parti.
  if (!client || !client.connected()) {
    WiFiClient incoming = server.available();
    if (incoming) {
      client.stop();
      client = incoming;
    }
  }

  twai_message_t msg;
  while (twai_receive(&msg, 0) == ESP_OK) {
    if (msg.extd || msg.rtr) continue;     // trames standard uniquement
    if (client && client.connected()) sendFrame(msg);
  }
}
