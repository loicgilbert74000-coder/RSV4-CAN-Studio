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
 *   0x7FA : état de la carte, envoyé chaque seconde.
 *           octet 0 = drapeaux : bit0 CAN activé, bit1 contrôleur CAN en marche, bit2 trames CAN reçues depuis moins de 3 s,
 *                     bit3 GPS activé, bit4 phrases NMEA reçues depuis moins de 2 s (module alimenté et relié), bit5 position valide ;
 *           octet 1 = signal Wi-Fi du PC vu par l'ESP32 (int8, dBm ; 127 = inconnu) ; octet 2 = appareils Wi-Fi connectés ;
 *           octets 3-4 = trames CAN par seconde (uint16) ; octet 5 = compteur d'erreurs de réception CAN (limité à 255).
 *           Bit 6 des drapeaux : des octets arrivent du GPS (même illisibles : débit incorrect).
 *           Par défaut : ADC 1 = potentiomètre de suspension avant, ADC 2 = suspension arrière (0 à 3,3 V).
 *
 *   0x7FB : enregistrement, chaque seconde : octets 0-1 = numéro du fichier en cours (0 = pas d'enregistrement),
 *           octets 2-5 = octets enregistrés (uint32), octets 6-7 = espace libre en Mo (uint16, plafonné).
 *           La trame 0x7FA porte en plus (octet 6) : bit0 enregistrement en cours, bit1 stockage disponible, bit2 carte SD.
 *   0x7FC, 0x7FD, 0x7FE : liste et téléchargement des enregistrements (voir « Commandes »).
 *
 * Enregistrement (bouton REC_BTN_PIN vers GND, ou commande de l'application) :
 *   les trames CAN, GPS et E/S sont écrites dans /rec/NNNN.trk (carte SD, sinon mémoire interne) ; un enregistrement
 *   = 16 octets d'en-tête « TRK1 » puis des enregistrements de 16 octets : temps (uint32, ms depuis le début), identifiant (uint16),
 *   DLC (1), données (8), contrôle XOR des 15 premiers octets. La LED rouge clignote une fois par seconde pendant l'enregistrement.
 *
 * Commandes envoyées par l'application (texte, terminées par un saut de ligne) :
 *   REC 1 / REC 0 : démarrer / arrêter ; LIST : liste des fichiers (0x7FC : n° uint16, taille uint32, drapeaux ; n° 0xFFFF = fin) ;
 *   GET n : envoie le fichier n (0x7FE type 1 = début avec la taille, 0x7FD = 8 octets de données, 0x7FE type 2 = fin avec la somme
 *   des octets, type 3 = erreur) ; DEL n : supprime le fichier n.
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
#include <FS.h>
#include <SD.h>
#include <SPI.h>
#include <LittleFS.h>
#include "esp_wifi.h"
#include "driver/twai.h"
#include "rsv4_config.h"

// Une broche inexistante ou réservée (mémoire flash, PSRAM) fait planter la carte : on l'ignore et on le signale.
static bool pinOk(int p) {
  if (p < 0 || !GPIO_IS_VALID_GPIO(p)) return false;
#if CONFIG_IDF_TARGET_ESP32S3
  if (p >= 26 && p <= 37) return false;                     // flash et PSRAM
#elif CONFIG_IDF_TARGET_ESP32
  if (p >= 6 && p <= 11) return false;                      // flash
#endif
  return true;
}
static bool checkPin(const char* what, int p) {
  if (pinOk(p)) return true;
  Serial.printf("Attention : broche %d inutilisable (%s), ignorée\n", p, what);
  return false;
}

#ifndef GPS_RATE_HZ
#define GPS_RATE_HZ 10                    // cadence de mesure du GPS (1, 5 ou 10) ; les trames GPS sont envoyées à la même cadence
#endif
#define GPS_SEND_MS (1000 / GPS_RATE_HZ)

#ifndef REC_BTN_PIN
#define REC_BTN_PIN 15                    // bouton poussoir d'enregistrement (entre la broche et GND)
#endif
#ifndef REC_SD_ENABLED
#define REC_SD_ENABLED 1
#endif
#ifndef SD_CS_PIN
#define SD_CS_PIN 10
#define SD_MOSI_PIN 11
#define SD_SCK_PIN 12
#define SD_MISO_PIN 13
#endif

#ifndef CAN_ENABLED
#define CAN_ENABLED 1
#endif

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
static void recordFrame(uint32_t id, const uint8_t* d, uint8_t dlc);

static void sendFrame(uint32_t id, const uint8_t* d, uint8_t dlc, bool rec = true) {
  if (rec) recordFrame(id, d, dlc);                         // enregistré même sans application connectée
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

static uint32_t gpsRmc = 0;                                // phrases RMC reçues (mesure de la cadence)

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
    gpsRmc++;
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

static uint32_t lastNmeaMs = 0;                            // dernière phrase NMEA valide
static uint32_t lastGpsByteMs = 0;                         // dernier octet reçu du module (bon ou illisible)
static uint32_t gpsBytes = 0, gpsSentences = 0;            // compteurs pour le port série

// Configuration du module u-blox (NEO-M8N / M9N) : cadence de mesure et phrases NMEA envoyées.
static void ubxSend(uint8_t cls, uint8_t id, const uint8_t* payload, uint16_t len) {
  uint8_t head[6] = {0xB5, 0x62, cls, id, (uint8_t)(len & 0xFF), (uint8_t)(len >> 8)};
  uint8_t a = 0, b = 0;
  for (int i = 2; i < 6; i++) { a += head[i]; b += a; }
  for (uint16_t i = 0; i < len; i++) { a += payload[i]; b += a; }
  gpsSerial.write(head, 6);
  gpsSerial.write(payload, len);
  gpsSerial.write(a);
  gpsSerial.write(b);
  gpsSerial.flush();
  delay(30);
}

static void gpsConfigure() {
  const uint16_t ms = 1000 / GPS_RATE_HZ;
  // M8 : UBX-CFG-RATE (mesure en ms, navigation 1, référence GPS)
  const uint8_t rate[6] = {(uint8_t)(ms & 0xFF), (uint8_t)(ms >> 8), 1, 0, 1, 0};
  ubxSend(0x06, 0x08, rate, sizeof(rate));
  // M9 : UBX-CFG-VALSET (mémoire vive), clé CFG-RATE-MEAS = 0x30210001
  const uint8_t valset[10] = {0, 1, 0, 0, 0x01, 0x00, 0x21, 0x30, (uint8_t)(ms & 0xFF), (uint8_t)(ms >> 8)};
  ubxSend(0x06, 0x8A, valset, sizeof(valset));
  // Phrases inutiles coupées (GLL, GSA, GSV, VTG) : seules RMC et GGA sont lues, et le débit série reste suffisant à 10 Hz
  const uint8_t ids[4] = {0x01, 0x02, 0x03, 0x05};
  for (int i = 0; i < 4; i++) {
    const uint8_t msg[8] = {0xF0, ids[i], 0, 0, 0, 0, 0, 0};
    ubxSend(0x06, 0x01, msg, sizeof(msg));
  }
  Serial.printf("GPS : cadence réglée à %d Hz (RMC et GGA seulement)\n", GPS_RATE_HZ);
}

// Détection automatique du débit : si rien de lisible n'arrive, on essaie les débits usuels l'un après l'autre.
static const uint32_t GPS_BAUDS[] = {GPS_BAUD, 9600, 38400, 115200, 4800};
static const int GPS_BAUD_COUNT = sizeof(GPS_BAUDS) / sizeof(GPS_BAUDS[0]);
static int gpsBaudIdx = 0;
static uint32_t gpsBaudSince = 0;                          // instant du dernier changement de débit

static void autoBaud(uint32_t now) {
  if (lastNmeaMs && now - lastNmeaMs < 5000) return;       // un débit fonctionne : on le garde
  if (now - gpsBaudSince < 4000) return;                   // laisser le temps de recevoir une phrase complète
  gpsBaudIdx = (gpsBaudIdx + 1) % GPS_BAUD_COUNT;
  gpsBaudSince = now;
  gpsSerial.updateBaudRate(GPS_BAUDS[gpsBaudIdx]);
  Serial.printf("GPS : aucune phrase lisible, essai à %lu bauds\n", (unsigned long)GPS_BAUDS[gpsBaudIdx]);
}

static void pollGps() {
  while (gpsSerial.available()) {
    char c = gpsSerial.read();
    lastGpsByteMs = millis();
    gpsBytes++;
    if (c == '\r') continue;
    if (c == '\n') {
      nmea[nlen] = 0;
      if (nlen >= 6 && nmea[0] == '$') {
        if (!lastNmeaMs || millis() - lastNmeaMs > 5000) Serial.printf("GPS : phrases lisibles à %lu bauds\n", (unsigned long)GPS_BAUDS[gpsBaudIdx]);
        bool relock = !lastNmeaMs || millis() - lastNmeaMs > 5000;
        lastNmeaMs = millis();
        gpsSentences++;
        if (relock) gpsConfigure();
      }
      parseNmea(nmea);
      nlen = 0;
    }
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

// ---------- stockage et enregistrement ----------
static fs::FS* store = nullptr;                            // carte SD ou mémoire interne
static bool storeSd = false;
static int64_t storeFree = 0;                              // octets libres (estimation, mise à jour à l'écriture)
static File recFile;
static bool recording = false;
static uint16_t recNo = 0;
static uint32_t recStartMs = 0, recBytes = 0;
static uint8_t recBuf[1024];
static size_t recLen = 0;
static bool statusNow = false;                             // envoyer l'état tout de suite (changement d'enregistrement)
#if REC_SD_ENABLED
static SPIClass sdSpi(HSPI);
#endif

static void sendCtl(uint8_t type, uint16_t n, uint32_t v) {  // 0x7FE : début (1), fin (2) ou erreur (3) d'un transfert
  uint8_t d[8] = {0};
  d[0] = type; memcpy(d + 1, &n, 2); memcpy(d + 3, &v, 4);
  sendFrame(0x7FE, d, 7, false);
}

static int fileNumber(const char* name) {                  // « /rec/0012.trk » ou « 0012.trk » -> 12 (0 si autre fichier)
  const char* b = strrchr(name, '/');
  b = b ? b + 1 : name;
  int n = atoi(b);
  size_t l = strlen(b);
  if (n <= 0 || l < 5 || strcmp(b + l - 4, ".trk") != 0) return 0;
  return n;
}

static void setupStorage() {
#if REC_SD_ENABLED
  if (checkPin("SD CS", SD_CS_PIN) && checkPin("SD MOSI", SD_MOSI_PIN) && checkPin("SD MISO", SD_MISO_PIN) && checkPin("SD SCK", SD_SCK_PIN)) {
    sdSpi.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);
    if (SD.begin(SD_CS_PIN, sdSpi, 20000000) && SD.cardType() != CARD_NONE) {
      Serial.println("Carte SD détectée, calcul de l'espace libre…");
      store = &SD; storeSd = true;
      storeFree = (int64_t)SD.totalBytes() - (int64_t)SD.usedBytes();
    } else {
      Serial.println("Carte SD absente ou illisible : mémoire interne utilisée (durée d'enregistrement limitée)");
    }
  }
#endif
  if (!store) {
    if (LittleFS.begin(true)) { store = &LittleFS; storeFree = (int64_t)LittleFS.totalBytes() - (int64_t)LittleFS.usedBytes(); }
    else Serial.println("Aucun stockage disponible : enregistrement impossible");
  }
  if (store) {
    if (!store->exists("/rec")) store->mkdir("/rec");
    Serial.printf("Stockage : %s · %lld Mo libres\n", storeSd ? "carte SD" : "mémoire interne", (long long)(storeFree / 1048576));
  }
}

static uint16_t nextRecNo() {
  int best = 0;
  File dir = store->open("/rec");
  if (dir) {
    File f = dir.openNextFile();
    while (f) {
      int n = fileNumber(f.name());
      if (n > best) best = n;
      f = dir.openNextFile();
    }
    dir.close();
  }
  return (uint16_t)(best + 1);
}

static void flushRec() {
  if (recLen) { recFile.write(recBuf, recLen); recBytes += recLen; storeFree -= (int64_t)recLen; recLen = 0; }
}

static void recordFrame(uint32_t id, const uint8_t* d, uint8_t dlc) {
  if (!recording) return;
  if (recLen + 16 > sizeof(recBuf)) flushRec();
  uint8_t* p = recBuf + recLen;
  uint32_t t = millis() - recStartMs;
  if (dlc > 8) dlc = 8;
  memcpy(p, &t, 4);
  p[4] = (uint8_t)(id & 0xFF); p[5] = (uint8_t)(id >> 8); p[6] = dlc;
  memset(p + 7, 0, 8);
  memcpy(p + 7, d, dlc);
  uint8_t x = 0;
  for (int i = 0; i < 15; i++) x ^= p[i];
  p[15] = x;
  recLen += 16;
}

static void startRecording() {
  if (recording) return;
  if (!store) { Serial.println("Enregistrement impossible : aucun stockage"); sendCtl(3, 0, 1); return; }
  recNo = nextRecNo();
  char path[24];
  snprintf(path, sizeof(path), "/rec/%04u.trk", (unsigned)recNo);
  recFile = store->open(path, FILE_WRITE);
  if (!recFile) { Serial.printf("Enregistrement impossible : %s non créé\n", path); sendCtl(3, recNo, 4); return; }
  uint8_t h[16] = {'T', 'R', 'K', '1'};
  h[4] = (uint8_t)(recNo & 0xFF); h[5] = (uint8_t)(recNo >> 8);
  uint32_t boot = millis(); memcpy(h + 6, &boot, 4);
  h[10] = GPS_RATE_HZ; h[11] = CAN_BITRATE_KBPS / 50;
  recFile.write(h, 16);
  recBytes = 16; recLen = 0; recStartMs = millis();
  recording = true; statusNow = true;
  Serial.printf("Enregistrement démarré : %s\n", path);
}

static void stopRecording() {
  if (!recording) return;
  recording = false; statusNow = true;
  flushRec();
  recFile.close();
  Serial.printf("Enregistrement arrêté : fichier %04u, %lu Ko\n", (unsigned)recNo, (unsigned long)(recBytes / 1024));
}

static void toggleRecording() { if (recording) stopRecording(); else startRecording(); }

static void tickRecording(uint32_t now) {                  // une fois par seconde : écriture sur le support, contrôle de l'espace libre
  static uint32_t last = 0;
  if (!recording || now - last < 1000) return;
  last = now;
  flushRec();
  recFile.flush();
  if (storeFree < 65536) { Serial.println("Stockage plein : enregistrement arrêté"); sendCtl(3, recNo, 5); stopRecording(); }
}

static bool btnOk = false;
static void setupButton() {
  btnOk = checkPin("bouton", REC_BTN_PIN);
  if (btnOk) pinMode(REC_BTN_PIN, INPUT_PULLUP);
}

static void pollButton(uint32_t now) {                     // un appui = démarrer ou arrêter (anti-rebond 40 ms)
  static bool last = true;
  static uint32_t changed = 0;
  if (!btnOk) return;
  bool level = digitalRead(REC_BTN_PIN);
  if (level != last && now - changed > 40) {
    changed = now; last = level;
    if (!level) toggleRecording();
  }
}

// ---------- liste, téléchargement et suppression des fichiers ----------
static void sendListEntry(uint16_t n, uint32_t size, uint8_t flags) {
  uint8_t d[8] = {0};
  memcpy(d, &n, 2); memcpy(d + 2, &size, 4); d[6] = flags;
  sendFrame(0x7FC, d, 8, false);
}

static void listFiles() {
  if (!store) { sendListEntry(0xFFFF, 0, 0x80); return; }
  int count = 0;
  File dir = store->open("/rec");
  if (dir) {
    File f = dir.openNextFile();
    while (f && count < 400) {
      int n = fileNumber(f.name());
      if (n > 0) {
        bool cur = recording && n == recNo;
        sendListEntry((uint16_t)n, cur ? recBytes + recLen : (uint32_t)f.size(), cur ? 1 : 0);
        count++;
      }
      f = dir.openNextFile();
    }
    dir.close();
  }
  sendListEntry(0xFFFF, count, 0);
}

static File dlFile;
static bool dlActive = false;
static uint32_t dlRemaining = 0, dlSum = 0;
static uint16_t dlNo = 0;

static void startDownload(uint16_t n) {
  if (dlActive) { dlFile.close(); dlActive = false; }
  if (!store) { sendCtl(3, n, 1); return; }
  if (recording && n == recNo) { sendCtl(3, n, 3); return; }
  char path[24];
  snprintf(path, sizeof(path), "/rec/%04u.trk", (unsigned)n);
  dlFile = store->open(path, FILE_READ);
  if (!dlFile) { sendCtl(3, n, 2); return; }
  dlRemaining = dlFile.size(); dlSum = 0; dlNo = n; dlActive = true;
  sendCtl(1, n, dlRemaining);
}

static void pumpDownload() {                               // quelques centaines d'octets par tour de boucle : le CAN continue d'être lu
  if (!dlActive) return;
  if (!client || !client.connected()) { dlFile.close(); dlActive = false; return; }
  uint8_t blk[320];
  size_t want = dlRemaining < sizeof(blk) ? dlRemaining : sizeof(blk);
  size_t got = want ? dlFile.read(blk, want) : 0;
  if (want && got == 0) { sendCtl(3, dlNo, 4); dlFile.close(); dlActive = false; return; }
  for (size_t i = 0; i < got; i += 8) {
    size_t n = got - i < 8 ? got - i : 8;
    for (size_t k = 0; k < n; k++) dlSum += blk[i + k];
    sendFrame(0x7FD, blk + i, (uint8_t)n, false);
  }
  dlRemaining -= got;
  if (dlRemaining == 0) { sendCtl(2, dlNo, dlSum); dlFile.close(); dlActive = false; }
}

static void deleteFile(uint16_t n) {
  if (!store) { sendCtl(3, n, 1); return; }
  if (recording && n == recNo) { sendCtl(3, n, 3); return; }
  char path[24];
  snprintf(path, sizeof(path), "/rec/%04u.trk", (unsigned)n);
  File f = store->open(path, FILE_READ);
  int64_t size = f ? (int64_t)f.size() : 0;
  if (f) f.close();
  if (store->remove(path)) storeFree += size; else sendCtl(3, n, 2);
}

// ---------- commandes de l'application ----------
static void handleCommand(const char* line) {
  int n = 0;
  if (strcmp(line, "REC 1") == 0) startRecording();
  else if (strcmp(line, "REC 0") == 0) stopRecording();
  else if (strcmp(line, "LIST") == 0) listFiles();
  else if (sscanf(line, "GET %d", &n) == 1 && n > 0) startDownload((uint16_t)n);
  else if (sscanf(line, "DEL %d", &n) == 1 && n > 0) { deleteFile((uint16_t)n); listFiles(); }
  statusNow = true;
}

static void pollCommands() {
  static char cmd[32];
  static uint8_t len = 0;
  while (client && client.connected() && client.available()) {
    char c = client.read();
    if (c == '\r') continue;
    if (c == '\n') { cmd[len] = 0; handleCommand(cmd); len = 0; }
    else if (len < sizeof(cmd) - 1) cmd[len++] = c;
  }
}

// ---------- état de la carte ----------
static bool canOk = false;                // contrôleur CAN démarré
static uint32_t lastCanRx = 0;            // dernière trame CAN reçue (ms)
static bool canSeen = false;              // au moins une trame reçue depuis le démarrage
static uint32_t canTotal = 0;                              // trames CAN reçues depuis le démarrage
static uint16_t canCount = 0;                              // trames CAN reçues pendant la seconde en cours

static int8_t wifiRssi(uint8_t* stations) {
  wifi_sta_list_t list;
  *stations = 0;
  if (esp_wifi_ap_get_sta_list(&list) != ESP_OK || list.num == 0) return 127;
  *stations = (uint8_t)list.num;
  int best = -127;
  for (int i = 0; i < list.num; i++) if (list.sta[i].rssi > best) best = list.sta[i].rssi;
  return (int8_t)best;
}

static void sendStatus(uint32_t now) {
  uint8_t d[7] = {0};
  if (CAN_ENABLED) d[0] |= 1;
  if (CAN_ENABLED && canOk) d[0] |= 2;
  if (CAN_ENABLED && canSeen && now - lastCanRx < 3000) d[0] |= 4;
#if GPS_ENABLED
  d[0] |= 8;
  if (lastNmeaMs && now - lastNmeaMs < 2000) d[0] |= 16;
  if (gps.valid) d[0] |= 32;
  if (lastGpsByteMs && now - lastGpsByteMs < 2000) d[0] |= 64;
#endif
  uint8_t st;
  d[1] = (uint8_t)wifiRssi(&st);
  d[2] = st;
  memcpy(d + 3, &canCount, 2);
  canCount = 0;
  twai_status_info_t info = {};
  if (CAN_ENABLED && twai_get_status_info(&info) == ESP_OK) d[5] = info.rx_error_counter > 255 ? 255 : (uint8_t)info.rx_error_counter;
  d[6] = (recording ? 1 : 0) | (store ? 2 : 0) | (storeSd ? 4 : 0);
  sendFrame(0x7FA, d, 7, false);
  uint8_t r[8] = {0};
  uint16_t no = recording ? recNo : 0;
  uint32_t bytes = recBytes + recLen;
  int64_t mb = storeFree / 1048576;
  uint16_t mbs = mb < 0 ? 0 : mb > 65535 ? 65535 : (uint16_t)mb;
  memcpy(r, &no, 2); memcpy(r + 2, &bytes, 4); memcpy(r + 6, &mbs, 2);
  sendFrame(0x7FB, r, 8, false);
}

// ---------- entrées / sorties ----------
static bool digOk[DIG_COUNT], anaOk[ANA_COUNT], outOk[OUT_COUNT];

static void setupIo() {
  for (int i = 0; i < DIG_COUNT; i++) {
    digOk[i] = DIG_ON[i] && checkPin("entrée", DIG_PIN[i]);
    if (digOk[i]) pinMode(DIG_PIN[i], INPUT);
  }
  for (int j = 0; j < ANA_COUNT; j++) {
    anaOk[j] = ANA_ON[j] && checkPin("analogique", ANA_PIN[j]);
    if (anaOk[j]) pinMode(ANA_PIN[j], INPUT);
  }
  for (int k = 0; k < OUT_COUNT; k++) outOk[k] = OUT_ON[k] && checkPin("sortie", OUT_PIN[k]);
  for (int k = 0; k < OUT_COUNT; k++) if (outOk[k]) {
    pinMode(OUT_PIN[k], OUTPUT);
    digitalWrite(OUT_PIN[k], OUT_HIGH[k] ? HIGH : LOW);
  }
}

static void sendIo() {
  uint8_t d[7];
  memset(d, 0, sizeof(d));
  for (int i = 0; i < DIG_COUNT && i < 8; i++)
    if (digOk[i] && digitalRead(DIG_PIN[i])) d[0] |= (uint8_t)(1 << i);
  for (int j = 0; j < ANA_COUNT && j < 3; j++) {
    uint16_t v = anaOk[j] ? (uint16_t)analogRead(ANA_PIN[j]) : 0;
    memcpy(d + 1 + 2 * j, &v, 2);
  }
  sendFrame(0x7F9, d, 7);
}

// ---------- voyants ----------

static bool ledOk[3];
static void ledSet(int i, int pin, bool on) { if (ledOk[i]) digitalWrite(pin, on ? HIGH : LOW); }

static void setupLeds() {
  const int pins[3] = {LED_GREEN_PIN, LED_RED_PIN, LED_BLUE_PIN};
  for (int i = 0; i < 3; i++) {
    ledOk[i] = checkPin("LED", pins[i]);
    if (ledOk[i]) { pinMode(pins[i], OUTPUT); digitalWrite(pins[i], LOW); }
  }
  for (int i = 0; i < 3; i++) {           // test : chaque voyant s'allume brièvement
    ledSet(i, pins[i], true); delay(250); ledSet(i, pins[i], false);
  }
}

static void updateLeds(uint32_t now) {
  bool linked = client && client.connected();
  ledSet(0, LED_GREEN_PIN, linked || ((now / 500) % 2));
  ledSet(2, LED_BLUE_PIN, canSeen && now - lastCanRx < 40);
  bool silent = canOk && canSeen && now - lastCanRx > 3000;
  bool fault = CAN_ENABLED && !canOk;                       // défaut du contrôleur CAN : rouge fixe
  bool flash = (now % 1000) < 150;                          // enregistrement : un éclat par seconde
  bool red = fault || (recording ? flash : (CAN_ENABLED && silent && ((now / 250) % 2)));
  ledSet(1, LED_RED_PIN, red);
}

// ---------- rapport d'état sur le port série ----------
static const char* wifiQuality(int rssi) {
  return rssi >= -60 ? "bon" : rssi >= -70 ? "correct" : rssi >= -80 ? "faible" : "très faible";
}

static void printReport(uint32_t now) {
  static uint32_t lastTotal = 0, lastTime = 0;
  uint32_t dt = now - lastTime ? now - lastTime : 1;
  uint32_t rate = (canTotal - lastTotal) * 1000UL / dt;
  lastTotal = canTotal; lastTime = now;
  Serial.printf("----- État à %lus -----\n", (unsigned long)(now / 1000));
  // Wi-Fi
  uint8_t stations;
  int8_t rssi = wifiRssi(&stations);
  Serial.printf("Wi-Fi  : réseau %s · appareils=%u", AP_SSID, stations);
  if (rssi != 127) Serial.printf(" · signal=%d dBm (%s)", rssi, wifiQuality(rssi));
  Serial.printf(" · application=%s\n", (client && client.connected()) ? "connectée" : "non connectée");
  // CAN
  if (!CAN_ENABLED) {
    Serial.println("CAN    : désactivé dans la configuration");
  } else {
    twai_status_info_t st = {};
    bool ok = twai_get_status_info(&st) == ESP_OK;
    const char* etat = !ok ? "inconnu" : st.state == TWAI_STATE_BUS_OFF ? "BUS-OFF" : st.state == TWAI_STATE_STOPPED ? "ARRÊTÉ" : "en marche";
    Serial.printf("CAN    : contrôleur %s · trames/s=%lu · total=%lu · erreurs_rx=%u · perdues=%u · %s\n", etat,
                  (unsigned long)rate, (unsigned long)canTotal, (unsigned)st.rx_error_counter, (unsigned)st.rx_missed_count,
                  (canSeen && now - lastCanRx < 3000) ? "bus actif" : "aucune trame (bus non raccordé ?)");
  }
  // GPS
#if GPS_ENABLED
  const char* module = (lastNmeaMs && now - lastNmeaMs < 2000) ? "détecté"
                       : (lastGpsByteMs && now - lastGpsByteMs < 2000) ? "données illisibles (débit ?)" : "aucune donnée";
  static uint32_t lastRmc = 0;
  float hz = (gpsRmc - lastRmc) * 1000.0f / dt;
  lastRmc = gpsRmc;
  Serial.printf("GPS    : module %s · cadence=%.1f Hz · débit=%lu · octets=%lu · phrases=%lu · position=%s · satellites=%u\n", module, hz,
                (unsigned long)GPS_BAUDS[gpsBaudIdx], (unsigned long)gpsBytes, (unsigned long)gpsSentences,
                gps.valid ? "valide" : "non", gps.sats);
  if (gps.valid) Serial.printf("         lat=%.6f lon=%.6f vitesse=%.1f km/h\n", gps.lat, gps.lon, gps.speedKmh);
#else
  Serial.println("GPS    : désactivé dans la configuration");
#endif
  // enregistrement
  Serial.printf("Enreg. : %s · stockage=%s · libre=%lld Mo", recording ? "EN COURS" : "arrêté",
                store ? (storeSd ? "carte SD" : "mémoire interne") : "aucun", (long long)(storeFree / 1048576));
  if (recording) Serial.printf(" · fichier %04u · %lu Ko", (unsigned)recNo, (unsigned long)((recBytes + recLen) / 1024));
  Serial.println();
  // entrées / potentiomètres
  Serial.print("Entrées: ");
  bool any = false;
  for (int i = 0; i < DIG_COUNT; i++) if (digOk[i]) { Serial.printf("E%d=%d ", i + 1, digitalRead(DIG_PIN[i])); any = true; }
  if (!any) Serial.print("aucune active");
  Serial.println();
  Serial.print("Analog.: ");
  any = false;
  for (int j = 0; j < ANA_COUNT; j++) if (anaOk[j]) {
    int v = analogRead(ANA_PIN[j]);
    Serial.printf("ADC%d=%d (%d%%) ", j + 1, v, v * 100 / 4095);
    any = true;
  }
  if (!any) Serial.print("aucune active");
  Serial.println();
}

// ---------- CAN ----------
static void setupCan() {
  if (!CAN_ENABLED) { Serial.println("Bus CAN désactivé dans la configuration"); return; }
#if CAN_BITRATE_KBPS == 500
  twai_timing_config_t timing = TWAI_TIMING_CONFIG_500KBITS();
#else
  twai_timing_config_t timing = TWAI_TIMING_CONFIG_250KBITS();
#endif
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)CAN_TX_PIN, (gpio_num_t)CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
  general.rx_queue_len = 128;                               // évite de perdre des trames entre deux tours de boucle
  twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  canOk = twai_driver_install(&general, &timing, &filter) == ESP_OK && twai_start() == ESP_OK;
  if (!canOk) Serial.println("Erreur : contrôleur CAN non démarré");
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS, AP_CHANNEL);
  server.begin();
  Serial.println("TrackLab Electronics - relais CAN/GPS/E-S v2.2");
  Serial.print("Wi-Fi "); Serial.print(AP_SSID); Serial.print(" prêt, adresse "); Serial.println(WiFi.softAPIP());
  setupLeds();
  setupButton();
  setupStorage();
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
  while (CAN_ENABLED && twai_receive(&msg, 0) == ESP_OK) {
    lastCanRx = millis(); canSeen = true; canCount++; canTotal++;
    if (msg.extd || msg.rtr) continue;                    // trames standard uniquement
    sendFrame(msg.identifier, msg.data, msg.data_length_code);
  }

#if GPS_ENABLED
  pollGps();
  autoBaud(millis());
#endif
  pollCommands();
  pollButton(millis());

#if GPS_ENABLED
  static uint32_t lastGps = 0;
#endif
  static uint32_t lastIo = 0, lastStatus = 0;
  uint32_t now = millis();
#if GPS_ENABLED
  if (now - lastGps >= GPS_SEND_MS) { lastGps = now; sendGps(); }
#endif
  if (now - lastIo >= 100) { lastIo = now; sendIo(); }
  if (statusNow || now - lastStatus >= 1000) { lastStatus = now; statusNow = false; sendStatus(now); }
  tickRecording(now);
  pumpDownload();

  flushTx();
  updateLeds(now);

  // Surveillance du contrôleur CAN (une fois par seconde) : reprise automatique après un bus-off.
  static uint32_t lastCheck = 0;
  if (CAN_ENABLED && now - lastCheck >= 1000) {
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
  if (now - lastStats >= CAN_STATS_PERIOD_MS) { lastStats = now; printReport(now); }
#endif

  // Messages d'évènement : connexion / déconnexion de l'application
  static bool wasLinked = false;
  bool linked = client && client.connected();
  if (linked != wasLinked) {
    wasLinked = linked;
    if (linked) Serial.printf("[%lus] Application connectée (%s)\n", (unsigned long)(now / 1000), client.remoteIP().toString().c_str());
    else Serial.printf("[%lus] Application déconnectée\n", (unsigned long)(now / 1000));
  }
}
