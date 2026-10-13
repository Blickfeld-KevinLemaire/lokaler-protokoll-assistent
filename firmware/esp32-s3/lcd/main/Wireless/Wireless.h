#pragma once

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "esp_wifi.h"
#include "nvs_flash.h" 
#include "esp_log.h"

#include <stdio.h>
#include <string.h>  // For memcpy
#include "esp_system.h"
#include "vermerk_live.h"
#include "vermerk_upload.h"



extern volatile bool WIFI_CONNECTED;
extern volatile bool SERVER_REACHABLE;
extern volatile bool PC_REACHABLE;

void Wireless_Init(void);
void WIFI_Init(void *arg);
vermerk_ergebnis_t VERMERK_Upload_File(const char *path, const char *filename, vermerk_abbrechen_t abbrechen);
void VERMERK_Wifi_Fast_Mode(bool on);

/* Senden waehrend der Aufnahme: vom Upload-Manager waehrend einer Aufnahme regelmaessig aufrufen.
 * Tut nichts, wenn kein Ziel erreichbar ist. */
void VERMERK_Live_Schritt(void);

/* Verarbeitungsstand einer hochgeladenen Aufnahme bei der Software abfragen (GET .../status).
 * true, wenn die Software geantwortet hat (auch mit "unbekannt"). */
bool VERMERK_Status_Abfragen(const char *dateiname, vermerk_status_t *status);
