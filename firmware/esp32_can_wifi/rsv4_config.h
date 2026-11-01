// Fichier généré par TrackLab Electronics (Paramétrage ESP32). Ne pas modifier à la main.
#pragma once
#define AP_SSID "RSV4-CAN"
#define AP_PASS "rsv4-can-2026"
#define AP_CHANNEL 6
#define TCP_PORT 2323
#define CAN_ENABLED 1
#define CAN_TX_PIN 5
#define CAN_RX_PIN 4
#define CAN_BITRATE_KBPS 250
#define GPS_ENABLED 1
#define GPS_RX_PIN 16
#define GPS_BAUD 115200
#define DIG_COUNT 8
static const int DIG_PIN[DIG_COUNT] = {14, 27, 26, 25, 33, 36, 39, 12};
static const bool DIG_ON[DIG_COUNT] = {0, 0, 0, 0, 0, 0, 0, 0};
#define ANA_COUNT 3
static const int ANA_PIN[ANA_COUNT] = {32, 34, 35};
static const bool ANA_ON[ANA_COUNT] = {1, 1, 0};
#define OUT_COUNT 2
static const int OUT_PIN[OUT_COUNT] = {2, 0};
static const bool OUT_ON[OUT_COUNT] = {0, 0};
static const bool OUT_HIGH[OUT_COUNT] = {0, 0};
#define REC_BTN_PIN 15
#define REC_SD_ENABLED 1
#define SD_CS_PIN 13
#define SD_MOSI_PIN 23
#define SD_MISO_PIN 19
#define SD_SCK_PIN 18
#define LED_GREEN_PIN 21
#define LED_RED_PIN 22
#define LED_BLUE_PIN 17
