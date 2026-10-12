/* Teil von vermerk_konfig.h, der nicht davon abhaengt, woher die Werte kommen: Auswahl je Ziel und
 * Geraete-Id aus dem eFuse. Wird immer gebaut - auf den Geraeten zusammen mit vermerk_konfig.c, im
 * QEMU-Test mit vermerk_konfig_test.c. */

#include "vermerk_konfig.h"
#include "vermerk_protokoll.h"

#include "esp_mac.h"

#include <stdbool.h>

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
