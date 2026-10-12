/* Einkompilierte Einstellungen der Geraete (siehe vermerk_konfig.h). Gelten, solange das Geraet nicht
 * ueber USB eingerichtet ist; eine Einrichtung im NVS ersetzt sie ganz (vermerk_konfig.c).
 *
 * server_config.h, wifi_credentials.h und vermerk_board.h liegen im Projekt des jeweiligen Boards unter
 * main/Wireless/ (server_config.h und wifi_credentials.h als Vorlage *.example, die echten Dateien stehen
 * in .gitignore). Das CMakeLists.txt dieser Komponente macht den Ordner fuer diese eine Datei sichtbar. */

#include "vermerk_konfig_intern.h"

#include "server_config.h"
#include "wifi_credentials.h"
#include "vermerk_board.h"

#include <string.h>

#if !defined(VERMERK_PC_TOKEN) || !defined(VERMERK_SERVER_TOKEN)
#error "server_config.h ist veraltet: VERMERK_PC_TOKEN und VERMERK_SERVER_TOKEN fehlen. Vorlage server_config.h.example ansehen."
#endif

#ifndef VERMERK_BOARD_NAME
#error "VERMERK_BOARD_NAME fehlt (main/Wireless/vermerk_board.h)"
#endif

#ifndef VERMERK_UPLOAD_ERSTE_NUMMER
#define VERMERK_UPLOAD_ERSTE_NUMMER 1
#endif

/* Dieselben Grenzen wie bei der Einrichtung ueber USB */
_Static_assert(sizeof(VERMERK_WIFI_SSID) <= VERMERK_SSID_MAX + 1, "VERMERK_WIFI_SSID: hoechstens 32 Bytes");
_Static_assert(sizeof(VERMERK_WIFI_PASSWORD) <= VERMERK_PASSWORT_MAX + 1, "VERMERK_WIFI_PASSWORD: hoechstens 63 Bytes");
_Static_assert(sizeof(VERMERK_PC_BASE_URL) <= VERMERK_EINR_URL_MAX + 1, "VERMERK_PC_BASE_URL: hoechstens 96 Bytes");
_Static_assert(sizeof(VERMERK_SERVER_BASE_URL) <= VERMERK_EINR_URL_MAX + 1, "VERMERK_SERVER_BASE_URL: hoechstens 96 Bytes");
_Static_assert(sizeof(VERMERK_PC_TOKEN) <= VERMERK_TOKEN_MAX + 1, "VERMERK_PC_TOKEN: hoechstens 128 Zeichen");
_Static_assert(sizeof(VERMERK_SERVER_TOKEN) <= VERMERK_TOKEN_MAX + 1, "VERMERK_SERVER_TOKEN: hoechstens 128 Zeichen");

void vermerk_konfig_standard(vermerk_konfig_t *k, const char **board)
{
    strcpy(k->wlan_ssid, VERMERK_WIFI_SSID);
    strcpy(k->wlan_passwort, VERMERK_WIFI_PASSWORD);
    strcpy(k->pc_url, VERMERK_PC_BASE_URL);
    strcpy(k->pc_token, VERMERK_PC_TOKEN);
    strcpy(k->server_url, VERMERK_SERVER_BASE_URL);
    strcpy(k->server_token, VERMERK_SERVER_TOKEN);
    k->erste_nummer = (VERMERK_UPLOAD_ERSTE_NUMMER >= 1) ? (uint32_t)VERMERK_UPLOAD_ERSTE_NUMMER : 1u;
    *board = VERMERK_BOARD_NAME;
}
