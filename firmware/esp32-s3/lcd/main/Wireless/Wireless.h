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

/* Kleine Anfrage an die Software (siehe vermerk_anfrage). Ziel wie beim Upload; -2: gerade kein Ziel erreichbar. */
int VERMERK_Anfrage(bool post, const char *pfad, const char *inhalt_typ, const uint8_t *inhalt, size_t laenge,
                    const char *ausgabe, char *antwort, size_t antwort_max, int timeout_ms);

/* Verarbeitungsstand einer hochgeladenen Aufnahme bei der Software abfragen (GET .../status).
 * VERMERK_STATUSABFRAGE_ZUSTAND: status ist gefuellt (auch "unbekannt"); _SPAETER: kein Ziel, Netz, 5xx;
 * _ENDE: die Software lehnt die Abfrage dauerhaft ab (4xx, z. B. eine aeltere Software ohne .../status). */
vermerk_statusabfrage_t VERMERK_Status_Abfragen(const char *dateiname, vermerk_status_t *status);
