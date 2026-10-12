/* Verbindungs-Einstellungen, heute fest beim Bauen eingetragen (siehe vermerk_konfig.h).
 *
 * server_config.h, wifi_credentials.h und vermerk_board.h liegen im Projekt des jeweiligen Boards unter
 * main/Wireless/ (server_config.h und wifi_credentials.h als Vorlage *.example, die echten Dateien stehen
 * in .gitignore). Das CMakeLists.txt dieser Komponente macht den Ordner fuer diese eine Datei sichtbar. */

#include "vermerk_konfig.h"
#include "vermerk_protokoll.h"

#include "esp_mac.h"

#include "server_config.h"
#include "wifi_credentials.h"
#include "vermerk_board.h"

#include <stdbool.h>

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

const char *vermerk_konfig_url(vermerk_ziel_t ziel)
{
    return (ziel == VERMERK_ZIEL_SERVER) ? vermerk_konfig_server_url() : vermerk_konfig_pc_url();
}

const char *vermerk_konfig_token(vermerk_ziel_t ziel)
{
    return (ziel == VERMERK_ZIEL_SERVER) ? vermerk_konfig_server_token() : vermerk_konfig_pc_token();
}

const char *vermerk_konfig_ziel_name(vermerk_ziel_t ziel)
{
    return (ziel == VERMERK_ZIEL_SERVER) ? "SERVER" : "PC";
}

uint32_t vermerk_konfig_erste_nummer(void)
{
    return (VERMERK_UPLOAD_ERSTE_NUMMER >= 1) ? (uint32_t)VERMERK_UPLOAD_ERSTE_NUMMER : 1u;
}

const char *vermerk_geraete_id(void)
{
    static char id[VERMERK_GERAETE_ID_GROESSE];
    static bool gelesen = false;

    if (!gelesen) {
        uint8_t mac[6] = {0};
        /* Werks-MAC (eFuse BLK0), nicht die WLAN-MAC: die laesst sich per esp_base_mac_addr_set umstellen */
        if (esp_efuse_mac_get_default(mac) != ESP_OK || !vermerk_mac_hex(mac, id, sizeof(id))) {
            id[0] = '\0';   /* dann ohne X-Geraete-Id */
        }
        gelesen = true;
    }
    return id;
}

const char *vermerk_firmware(void)
{
    return VERMERK_BOARD_NAME "/" VERMERK_FIRMWARE_VERSION;
}
