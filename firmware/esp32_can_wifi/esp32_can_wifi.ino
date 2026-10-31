/*
 * TrackLab Electronics — relais CAN / GPS / E-S -> Wi-Fi pour ESP32
 * NON TESTÉ sur matériel : à valider avant emploi sur la moto.
 *
 * Paramétrage : fichier rsv4_config.h, généré par TrackLab Electronics (onglet « Paramétrage ESP32 »).
 *
 * Fonctionnement :
 *   - L'ESP32 crée son propre réseau Wi-Fi (point d'accès, SSID = AP_SSID).
 *   - Le PC se connecte à ce réseau, puis l'application se connecte à 192.168.4.1:TCP_PORT.
 *   - Le contrôleur CAN est en mode ÉCOUTE SEULE : il ne transmet jamais de trame.
 *
 * Protocole (une trame = 20 octets, champs multi-octets en little-endian) :
 *   octets 0-1   : 0xA5 0x5A  (marqueur de début)
 *   octets 2-5   : temps en millisecondes depuis le démarrage
 *   octets 6-9   : identifiant (CAN standard, ou trame de l'ESP32)
 *   octet 10     : DLC (0 à 8)
 *   octets 11-18 : données (complétées par des zéros)
 *   octet 19     : XOR des octets 2 à 18
 *
 * Trames propres à l'ESP32 (identifiants absents de la définition CAN de la moto) :
 *   0x7F0 : latitude et longitude, int32 chacune en 1e-7 degré (LE). Envoyée seulement si le fix est valide.
 *   0x7F8 : vitesse GPS (uint16, km/h x 100), cap (uint16, degrés x 100), satellites (uint8), qualité du fix (uint8).
 *   0x7F9 : octet 0 = entrées numériques (bit n = entrée n+1) ; octets 1-2, 3-4, 5-6 = ADC 1, 2, 3 (uint16, 0 à 4095).
 *           Par défaut : ADC 1 = potentiomètre de suspension avant, ADC 2 = suspension arrière (0 à 3,3 V).
 *
 * Voyants (LED_GREEN_PIN / LED_RED_PIN / LED_BLUE_PIN, résistance de 330 ohms en série) :
 *   verte  : clignote lentement = Wi-Fi prêt, pas de PC connecté ; fixe = application connectée.
 *   bleue  : bref éclat à chaque trame CAN reçue (activité du bus).
 *   rouge  : fixe = contrôleur CAN en défaut (non démarré, bus-off) ; clignote = aucune trame CAN depuis 3 s.
 *   Au démarrage : les trois voyants s'allument l'un après l'autre (test).
 */
#include <WiFi.h>
#include <string.h>
#include <math.h>
#include "driver/twai.h"
#include "rsv4_config.h"

#ifndef LED_GREEN_PIN
#define LED_GREEN_PIN 21
#endif
#ifndef LED_RED_PIN
#define LED_RED_PIN 22
#endif
#ifndef LED_BLUE_PIN
#define LED_BLUE_PIN 17
#endif

#ifndef CAN_STATS_PERIOD_MS
#define CAN_STATS_PERIOD_MS 5000   // 0 : pas de statistiques sur le port série
#endif

WiFiServer server(TCP_PORT);
WiFiClient client;
HardwareSerial gpsSerial(2);

// Les trames sont regroupées dans un tampon et envoyées en un seul paquet TCP à la fin de chaque tour de boucle.
static uint8_t txBuf[1400];
static size_t txLen = 0;

static void flushTx() {
  if (txLen && client && client.connected()) client.write(txBuf, txLen);
  txLen = 0;
}

// ---------- envoi de trames ----------
static void sendFrame(uint32_t id, const uint8_t* d, uint8_t dlc) {
  if (!client || !client.connected()) { txLen = 0; return; }
  if (txLen + 20 > sizeof(txBuf)) flushTx();
  uint8_t* p = txBuf + txLen;
  memset(p, 0, 20);
  p[0] = 0xA5; p[1] = 0x5A;
  uint32_t t = millis();
  memcpy(p + 2, &t, 4);
  memcpy(p + 6, &id, 4);
  if (dlc > 8) dlc = 8;
  p[10] = dlc;
  memcpy(p + 11, d, dlc);
  uint8_t x = 0;
  for (int i = 2; i < 19; i++) x ^= p[i];
  p[19] = x;
  txLen += 20;
}

// ---------- GPS (NMEA RMC et GGA) ----------
#if GPS_ENABLED
struct GpsState { double lat, lon; double speedKmh; double course; uint8_t sats; uint8_t fix; bool valid; } gps = {0, 0, 0, 0, 0, 0, false};
static char nmea[128];
static uint8_t nlen = 0;

static double nmeaToDeg(const char* s, char hemi) {       // format ddmm.mmmm
  double v = atof(s);
  if (v == 0) return 0;
  int deg = (int)(v / 100);
  double d = deg + (v - deg * 100) / 60.0;
  if (hemi == 'S' || hemi == 'W') d = -d;
  return d;
}

static int splitFields(char* line, char* f[], int maxf) {  // découpe sur les virgules (modifie la ligne)
  int n = 0;
  f[n++] = line;
  for (char* p = line; *p && n < maxf; p++) {
    if (*p == ',') { *p = 0; f[n++] = p + 1; }
  }
  return n;
}

static void parseNmea(char* line) {
  if (line[0] != '$' || strlen(line) < 6) return;
  char* f[16];
  int n = splitFields(line, f, 16);
  const char* type = f[0] + 3;                              // "$GNRMC" -> "RMC"
  if (strncmp(type, "RMC", 3) == 0 && n >= 9) {
    gps.valid = (f[2][0] == 'A');
    if (gps.valid) {
      gps.lat = nmeaToDeg(f[3], f[4][0]);
      gps.lon = nmeaToDeg(f[5], f[6][0]);
      gps.speedKmh = atof(f[7]) * 1.852;
      gps.course = atof(f[8]);
    }
  } else if (strncmp(type, "GGA", 3) == 0 && n >= 8) {
    gps.fix = (uint8_t)atoi(f[6]);
    gps.sats = (uint8_t)atoi(f[7]);
  }
}

static void pollGps() {
  while (gpsSerial.available()) {
    char c = gpsSerial.read();
    if (c == '\r') continue;
    if (c == '\n') { nmea[nlen] = 0; parseNmea(nmea); nlen = 0; }
    else if (nlen < sizeof(nmea) - 1) nmea[nlen++] = c;
  }
}

static void sendGps() {
  uint8_t d[8];
  if (gps.valid) {
    int32_t la = (int32_t)lround(gps.lat * 1e7), lo = (int32_t)lround(gps.lon * 1e7);
    memcpy(d, &la, 4); memcpy(d + 4, &lo, 4);
    sendFrame(0x7F0, d, 8);
  }
  uint16_t sp = (uint16_t)(gps.speedKmh * 100), co = (uint16_t)(gps.course * 100);
  memcpy(d, &sp, 2); memcpy(d + 2, &co, 2);
  d[4] = gps.sats; d[5] = gps.fix;
  sendFrame(0x7F8, d, 6);
}
#endif

// ---------- entrées / sorties ----------
static void setupIo() {
  for (int i = 0; i < DIG_COUNT; i++) if (DIG_ON[i]) pinMode(DIG_PIN[i], INPUT);
  for (int j = 0; j < ANA_COUNT; j++) if (ANA_ON[j]) pinMode(ANA_PIN[j], INPUT);
  for (int k = 0; k < OUT_COUNT; k++) if (OUT_ON[k]) {
    pinMode(OUT_PIN[k], OUTPUT);
    digitalWrite(OUT_PIN[k], OUT_HIGH[k] ? HIGH : LOW);
  }
}

static void sendIo() {
  uint8_t d[7];
  memset(d, 0, sizeof(d));
  for (int i = 0; i < DIG_COUNT && i < 8; i++)
    if (DIG_ON[i] && digitalRead(DIG_PIN[i])) d[0] |= (uint8_t)(1 << i);
  for (int j = 0; j < ANA_COUNT && j < 3; j++) {
    uint16_t v = ANA_ON[j] ? (uint16_t)analogRead(ANA_PIN[j]) : 0;
    memcpy(d + 1 + 2 * j, &v, 2);
  }
  sendFrame(0x7F9, d, 7);
}

// ---------- voyants ----------
static bool canOk = false;                // contrôleur CAN démarré
static uint32_t lastCanRx = 0;            // dernière trame CAN reçue (ms)
static bool canSeen = false;              // au moins une trame reçue depuis le démarrage

static void setupLeds() {
  const int pins[3] = {LED_GREEN_PIN, LED_RED_PIN, LED_BLUE_PIN};
  for (int i = 0; i < 3; i++) { pinMode(pins[i], OUTPUT); digitalWrite(pins[i], LOW); }
  for (int i = 0; i < 3; i++) {           // test : chaque voyant s'allume brièvement
    digitalWrite(pins[i], HIGH); delay(250); digitalWrite(pins[i], LOW);
  }
}

static void updateLeds(uint32_t now) {
  bool linked = client && client.connected();
  digitalWrite(LED_GREEN_PIN, linked ? HIGH : ((now / 500) % 2 ? HIGH : LOW));
  digitalWrite(LED_BLUE_PIN, (canSeen && now - lastCanRx < 40) ? HIGH : LOW);
  bool silent = canOk && canSeen && now - lastCanRx > 3000;
  bool red = !canOk || (silent && ((now / 250) % 2));
  digitalWrite(LED_RED_PIN, red ? HIGH : LOW);
}

// ---------- CAN ----------
static void setupCan() {
#if CAN_BITRATE_KBPS == 500
  twai_timing_config_t timing = TWAI_TIMING_CONFIG_500KBITS();
#else
  twai_timing_config_t timing = TWAI_TIMING_CONFIG_250KBITS();
#endif
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)CAN_TX_PIN, (gpio_num_t)CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
  general.rx_queue_len = 64;                                // évite de perdre des trames entre deux tours de boucle
  twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  canOk = twai_driver_install(&general, &timing, &filter) == ESP_OK && twai_start() == ESP_OK;
  if (!canOk) Serial.println("Erreur : contrôleur CAN non démarré");
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS, AP_CHANNEL);
  server.begin();
  Serial.println("TrackLab Electronics - relais CAN/GPS/E-S v2.1");
  Serial.print("Wi-Fi "); Serial.print(AP_SSID); Serial.print(" prêt, adresse "); Serial.println(WiFi.softAPIP());
  setupLeds();
  setupCan();
  setupIo();
#if GPS_ENABLED
  gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, -1);
#endif
}

void loop() {
  // Une seule connexion à la fois : on accepte un nouveau client si le précédent est parti.
  if (!client || !client.connected()) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    WiFiClient incoming = server.accept();
#else
    WiFiClient incoming = server.available();
#endif
    if (incoming) {
      client.stop();
      client = incoming;
      client.setNoDelay(true);                              // latence minimale
      txLen = 0;
    }
  }

  twai_message_t msg;
  while (twai_receive(&msg, 0) == ESP_OK) {
    lastCanRx = millis(); canSeen = true;
    if (msg.extd || msg.rtr) continue;                    // trames standard uniquement
    sendFrame(msg.identifier, msg.data, msg.data_length_code);
  }

#if GPS_ENABLED
  pollGps();
#endif

#if GPS_ENABLED
  static uint32_t lastGps = 0;
#endif
  static uint32_t lastIo = 0;
  uint32_t now = millis();
#if GPS_ENABLED
  if (now - lastGps >= 200) { lastGps = now; sendGps(); }
#endif
  if (now - lastIo >= 100) { lastIo = now; sendIo(); }

  flushTx();
  updateLeds(now);

  // Surveillance du contrôleur CAN (une fois par seconde) : reprise automatique après un bus-off.
  static uint32_t lastCheck = 0;
  if (now - lastCheck >= 1000) {
    lastCheck = now;
    twai_status_info_t st;
    if (twai_get_status_info(&st) == ESP_OK) {
      if (st.state == TWAI_STATE_BUS_OFF) { canOk = false; twai_initiate_recovery(); }
      else if (st.state == TWAI_STATE_STOPPED) { canOk = false; twai_start(); }
      else canOk = true;
    }
  }

#if CAN_STATS_PERIOD_MS > 0
  static uint32_t lastStats = 0;
  if (now - lastStats >= CAN_STATS_PERIOD_MS) {
    lastStats = now;
    twai_status_info_t st;
    if (twai_get_status_info(&st) == ESP_OK)
      Serial.printf("CAN: file=%u perdues=%u erreurs_rx=%u client=%s\n", (unsigned)st.msgs_to_rx,
                    (unsigned)st.rx_missed_count, (unsigned)st.rx_error_counter, client.connected() ? "oui" : "non");
  }
#endif
}
