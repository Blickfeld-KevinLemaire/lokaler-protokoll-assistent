#pragma once

/* Verbindungs-Einstellungen und Kennung des Geraets: WLAN, Ziele (PC und Server) mit Token,
 * erste hochzuladende Nummer, Geraete-Id und Firmware-Stand.
 *
 * Alles, was die Firmware davon braucht, liest sie NUR ueber diese Funktionen - nie direkt aus
 * server_config.h oder wifi_credentials.h. Heute liefern sie die beim Bauen eingetragenen Werte
 * (vermerk_konfig.c). Spaeter sollen Kunden die Werte selbst setzen koennen (z. B. per USB aus der
 * Anwendung, gespeichert im NVS); dann aendert sich nur vermerk_konfig.c, nicht der Upload-Code.
 *
 * Leerer Text = nicht eingerichtet. Die Zeiger bleiben gueltig, solange das Geraet laeuft. */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Stand der Firmware, geht mit dem Board-Namen (VERMERK_BOARD_NAME in main/Wireless/vermerk_board.h)
 * als X-Firmware an die Software, z. B. "esp32-s3-audio/1.0.0" */
#define VERMERK_FIRMWARE_VERSION "1.0.0"

typedef enum {
    VERMERK_ZIEL_SERVER = 0,   /* hat Vorrang, wenn beide erreichbar sind */
    VERMERK_ZIEL_PC
} vermerk_ziel_t;

const char *vermerk_konfig_wlan_name(void);
const char *vermerk_konfig_wlan_passwort(void);

/* Basis-Adresse ohne Schraegstrich am Ende, z. B. "http://192.168.0.10:8765" */
const char *vermerk_konfig_pc_url(void);
const char *vermerk_konfig_pc_token(void);
const char *vermerk_konfig_server_url(void);
const char *vermerk_konfig_server_token(void);

/* Dasselbe je Ziel */
const char *vermerk_konfig_url(vermerk_ziel_t ziel);
const char *vermerk_konfig_token(vermerk_ziel_t ziel);
const char *vermerk_konfig_ziel_name(vermerk_ziel_t ziel);   /* "SERVER" / "PC", fuer Meldungen */

/* Aufnahmen mit kleinerer Nummer werden nicht hochgeladen (Standard 1 = alle) */
uint32_t vermerk_konfig_erste_nummer(void);

/* Werks-MAC aus dem eFuse als 12 Hex-Zeichen (X-Geraete-Id). Aendert sich nie, auch nicht, wenn
 * jemand die WLAN-MAC umstellt. Nur zur Zuordnung - angemeldet wird ausschliesslich ueber das Token.
 * Leer, wenn der eFuse nicht lesbar war (dann geht die Kopfzeile nicht mit). */
const char *vermerk_geraete_id(void);

/* "<Board>/<Version>" (X-Firmware), z. B. "esp32-c6/1.0.0" */
const char *vermerk_firmware(void);

#ifdef __cplusplus
}
#endif
