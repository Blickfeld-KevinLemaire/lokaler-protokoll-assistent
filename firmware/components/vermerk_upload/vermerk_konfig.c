/* Verbindungs-Einstellungen, heute fest beim Bauen eingetragen (siehe vermerk_konfig.h).
 *
 * server_config.h, wifi_credentials.h und vermerk_board.h liegen im Projekt des jeweiligen Boards unter
 * main/Wireless/ (server_config.h und wifi_credentials.h als Vorlage *.example, die echten Dateien stehen
 * in .gitignore). Das CMakeLists.txt dieser Komponente macht den Ordner fuer diese eine Datei sichtbar.
 * Auswahl je Ziel und Geraete-Id: vermerk_konfig_gemeinsam.c. */

#include "vermerk_konfig.h"

#include "server_config.h"
#include "wifi_credentials.h"
#include "vermerk_board.h"

#if !defined(VERMERK_PC_TOKEN) || !defined(VERMERK_SERVER_TOKEN)
#error "server_config.h ist veraltet: VERMERK_PC_TOKEN und VERMERK_SERVER_TOKEN fehlen. Vorlage server_config.h.example ansehen."
#endif

#ifndef VERMERK_BOARD_NAME
#error "VERMERK_BOARD_NAME fehlt (main/Wireless/vermerk_board.h)"
#endif

#ifndef VERMERK_UPLOAD_ERSTE_NUMMER
#define VERMERK_UPLOAD_ERSTE_NUMMER 1
#endif

const char *vermerk_konfig_wlan_name(void)     { return VERMERK_WIFI_SSID; }
const char *vermerk_konfig_wlan_passwort(void) { return VERMERK_WIFI_PASSWORD; }

const char *vermerk_konfig_pc_url(void)        { return VERMERK_PC_BASE_URL; }
const char *vermerk_konfig_pc_token(void)      { return VERMERK_PC_TOKEN; }
const char *vermerk_konfig_server_url(void)    { return VERMERK_SERVER_BASE_URL; }
const char *vermerk_konfig_server_token(void)  { return VERMERK_SERVER_TOKEN; }

uint32_t vermerk_konfig_erste_nummer(void)
{
    return (VERMERK_UPLOAD_ERSTE_NUMMER >= 1) ? (uint32_t)VERMERK_UPLOAD_ERSTE_NUMMER : 1u;
}

const char *vermerk_firmware(void)
{
    return VERMERK_BOARD_NAME "/" VERMERK_FIRMWARE_VERSION;
}
