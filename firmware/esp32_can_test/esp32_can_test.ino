/*
 * TrackLab Electronics - TEST CAN (moniteur série)
 * Affiche toutes les trames CAN reçues, sans Wi-Fi, sans TrackLab.
 * Le contrôleur est en ÉCOUTE SEULE : il n'émet jamais sur le bus.
 *
 * Réglage du moniteur série : 921600 bauds.
 *
 * Commandes (taper une lettre puis Entrée) :
 *   a  recherche automatique du débit (par défaut au démarrage)
 *   1  1 Mbit/s   2  800 kbit/s   3  500 kbit/s   4  250 kbit/s   5  125 kbit/s
 *   r  bascule : toutes les trames  <->  résumé par identifiant toutes les 3 s
 *
 * Carte : ESP32-S3 ou ESP32 classique. Broches par défaut : TXD=GPIO5, RXD=GPIO4
 * (comme le firmware principal). Modifiez CAN_TX_PIN / CAN_RX_PIN si besoin.
 */
#include <Arduino.h>
#include "driver/twai.h"

#define CAN_TX_PIN 5
#define CAN_RX_PIN 4

struct Rate { const char *name; twai_timing_config_t t; };
static const Rate RATES[] = {
  {"1 Mbit/s",   TWAI_TIMING_CONFIG_1MBITS()},
  {"800 kbit/s", TWAI_TIMING_CONFIG_800KBITS()},
  {"500 kbit/s", TWAI_TIMING_CONFIG_500KBITS()},
  {"250 kbit/s", TWAI_TIMING_CONFIG_250KBITS()},
  {"125 kbit/s", TWAI_TIMING_CONFIG_125KBITS()},
};
static const int NRATES = sizeof(RATES) / sizeof(RATES[0]);

static int rateIdx = -1;          // -1 = recherche automatique en cours
static bool installed = false;
static bool summary = false;
static uint32_t total = 0, perSec = 0, lastSec = 0;

// résumé par identifiant
struct IdStat { uint32_t id; bool ext; uint32_t n; uint8_t dlc; uint8_t d[8]; };
static IdStat ids[96];
static int nIds = 0;

static void stop() {
  if (installed) { twai_stop(); twai_driver_uninstall(); installed = false; }
}

static bool start(int idx) {
  stop();
  twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)CAN_TX_PIN, (gpio_num_t)CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
  g.rx_queue_len = 128;
  twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  if (twai_driver_install(&g, &RATES[idx].t, &f) != ESP_OK) return false;
  if (twai_start() != ESP_OK) { twai_driver_uninstall(); return false; }
  installed = true;
  return true;
}

static void printStatus() {
  twai_status_info_t s;
  if (twai_get_status_info(&s) != ESP_OK) return;
  const char *st = s.state == TWAI_STATE_RUNNING ? "actif" : s.state == TWAI_STATE_BUS_OFF ? "BUS-OFF" :
                   s.state == TWAI_STATE_RECOVERING ? "reprise" : "arrêté";
  Serial.printf("[état] contrôleur %s | erreurs réception=%u | erreurs de bus=%u | perdues=%u | file=%u\n",
                st, (unsigned)s.rx_error_counter, (unsigned)s.bus_error_count, (unsigned)s.rx_missed_count, (unsigned)s.msgs_to_rx);
}

// recherche automatique : le bon débit donne des trames et très peu d'erreurs
static void autoDetect() {
  Serial.println("\n=== Recherche automatique du débit (3 s par débit) ===");
  int best = -1; uint32_t bestScore = 0;
  for (int i = 0; i < NRATES; i++) {
    if (!start(i)) { Serial.printf("  %-11s : démarrage impossible\n", RATES[i].name); continue; }
    uint32_t ok = 0, t0 = millis();
    twai_message_t m;
    while (millis() - t0 < 3000) {
      if (twai_receive(&m, pdMS_TO_TICKS(20)) == ESP_OK) ok++;
    }
    twai_status_info_t s; twai_get_status_info(&s);
    Serial.printf("  %-11s : %5u trames, erreurs bus=%u\n", RATES[i].name, (unsigned)ok, (unsigned)s.bus_error_count);
    // score : trames valides, pénalisé par les erreurs
    uint32_t score = ok > s.bus_error_count ? ok - s.bus_error_count : 0;
    if (ok >= 5 && score > bestScore) { bestScore = score; best = i; }
  }
  stop();
  if (best < 0) {
    Serial.println("Aucun débit ne donne de trames lisibles. Vérifiez : contact mis, CAN H / CAN L, masse, module 3,3 V.");
    Serial.println("Tapez 1 à 5 pour forcer un débit, ou 'a' pour relancer la recherche.");
    rateIdx = -1;
    return;
  }
  Serial.printf(">>> Débit retenu : %s\n\n", RATES[best].name);
  rateIdx = best;
  start(best);
}

static void showFrame(const twai_message_t &m) {
  char line[96];
  int n = snprintf(line, sizeof line, "%10lu  %s  ID=0x%0*lX  %s  DLC=%u ",
                   (unsigned long)millis(), m.extd ? "EXT" : "STD", m.extd ? 8 : 3, (unsigned long)m.identifier,
                   m.rtr ? "RTR" : "DAT", m.data_length_code);
  if (!m.rtr)
    for (int i = 0; i < m.data_length_code && i < 8 && n < (int)sizeof line - 4; i++)
      n += snprintf(line + n, sizeof line - n, " %02X", m.data[i]);
  Serial.println(line);
}

static void collect(const twai_message_t &m) {
  for (int i = 0; i < nIds; i++)
    if (ids[i].id == m.identifier && ids[i].ext == (bool)m.extd) {
      ids[i].n++; ids[i].dlc = m.data_length_code; memcpy(ids[i].d, m.data, 8); return;
    }
  if (nIds < (int)(sizeof ids / sizeof ids[0])) {
    IdStat &s = ids[nIds++];
    s.id = m.identifier; s.ext = m.extd; s.n = 1; s.dlc = m.data_length_code; memcpy(s.d, m.data, 8);
  }
}

static void printSummary() {
  Serial.printf("--- résumé : %d identifiants, %lu trames au total ---\n", nIds, (unsigned long)total);
  for (int i = 0; i < nIds; i++) {
    Serial.printf("%s 0x%0*lX  x%-6lu  ", ids[i].ext ? "EXT" : "STD", ids[i].ext ? 8 : 3, (unsigned long)ids[i].id, (unsigned long)ids[i].n);
    for (int k = 0; k < ids[i].dlc && k < 8; k++) Serial.printf("%02X ", ids[i].d[k]);
    Serial.println();
    ids[i].n = 0;
  }
}

void setup() {
  Serial.begin(921600);
  delay(800);
  Serial.println("\nTrackLab Electronics - test CAN (écoute seule)");
  Serial.printf("TXD=GPIO%d  RXD=GPIO%d  - moniteur série à 921600 bauds\n", CAN_TX_PIN, CAN_RX_PIN);
  Serial.println("Commandes : a=auto  1=1M  2=800k  3=500k  4=250k  5=125k  r=résumé/trames");
  autoDetect();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'a') { autoDetect(); }
    else if (c >= '1' && c <= '5') {
      rateIdx = c - '1';
      if (start(rateIdx)) Serial.printf(">>> Débit forcé : %s\n", RATES[rateIdx].name);
      else Serial.println("Démarrage impossible");
    } else if (c == 'r') {
      summary = !summary; nIds = 0;
      Serial.println(summary ? ">>> Mode résumé par identifiant" : ">>> Mode toutes les trames");
    }
  }
  if (!installed) { delay(50); return; }

  twai_message_t m;
  uint8_t guard = 0;
  while (guard++ < 64 && twai_receive(&m, 0) == ESP_OK) {
    total++; perSec++;
    if (summary) collect(m); else showFrame(m);
  }

  uint32_t now = millis();
  static uint32_t lastSum = 0;
  if (summary && now - lastSum >= 3000) { lastSum = now; printSummary(); }
  if (now - lastSec >= 2000) {
    lastSec = now;
    Serial.printf("[%s] %lu trames/s\n", rateIdx >= 0 ? RATES[rateIdx].name : "?", (unsigned long)(perSec / 2));
    perSec = 0;
    printStatus();
  }
}
