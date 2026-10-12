/* Geltende Einstellungen (siehe vermerk_konfig.h):
 *   1. einkompilierte Werte (vermerk_konfig_standard.c bzw. im QEMU-Test vermerk_konfig_test.c),
 *   2. ersetzt durch die Einrichtung ueber USB, wenn eine im NVS liegt.
 * Die Einrichtung liegt als ein Blob ("konfig") im NVS-Namensraum "vermerk": ein Schreibvorgang, alles
 * oder nichts. Derselbe Namensraum haelt den Aufnahmezaehler (next_rec_id); LOESCHEN entfernt nur "konfig". */

#include "vermerk_konfig.h"
#include "vermerk_konfig_intern.h"

#include "esp_mac.h"
#include "nvs.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NVS_BEREICH    "vermerk"
#define NVS_SCHLUESSEL "konfig"

static vermerk_konfig_t s_konfig;
static const char *s_board = "";
static uint32_t s_erste_nummer_standard = 1;
static bool s_geladen = false;
static bool s_eingerichtet = false;

static void standard_laden(void)
{
    memset(&s_konfig, 0, sizeof(s_konfig));
    s_konfig.version = VERMERK_KONFIG_VERSION;
    vermerk_konfig_standard(&s_konfig, &s_board);
    s_erste_nummer_standard = (s_konfig.erste_nummer >= 1) ? s_konfig.erste_nummer : 1;
    s_eingerichtet = false;
    s_geladen = true;
}

static void sicherstellen(void)
{
    if (!s_geladen) {
        standard_laden();   /* vor vermerk_konfig_laden(): die einkompilierten Werte */
    }
}

vermerk_konfig_t *vermerk_konfig_aktuell(void)
{
    sicherstellen();
    return &s_konfig;
}

void vermerk_konfig_laden(void)
{
    standard_laden();

    nvs_handle_t nvs;
    if (nvs_open(NVS_BEREICH, NVS_READONLY, &nvs) != ESP_OK) {
        printf("VERMERK Einstellungen: einkompiliert (nicht ueber USB eingerichtet)\n");
        return;
    }
    vermerk_konfig_t *gelesen = calloc(1, sizeof(*gelesen));
    size_t groesse = sizeof(*gelesen);
    esp_err_t err = (gelesen != NULL) ? nvs_get_blob(nvs, NVS_SCHLUESSEL, gelesen, &groesse) : ESP_ERR_NO_MEM;
    nvs_close(nvs);

    if (err == ESP_OK && groesse == sizeof(*gelesen)) {
        const char *fehler = vermerk_konfig_pruefen(gelesen);
        if (fehler == NULL) {
            s_konfig = *gelesen;
            s_eingerichtet = true;
            printf("VERMERK Einstellungen: ueber USB eingerichtet\n");
        } else {
            printf("VERMERK Einstellungen: Einrichtung im NVS ungueltig (%s), nutze die einkompilierten\n", fehler);
        }
    } else if (err == ESP_ERR_NVS_NOT_FOUND) {
        printf("VERMERK Einstellungen: einkompiliert (nicht ueber USB eingerichtet)\n");
    } else {
        printf("VERMERK Einstellungen: Einrichtung im NVS nicht lesbar (%s), nutze die einkompilierten\n",
               err == ESP_OK ? "falsche Groesse" : esp_err_to_name(err));
    }
    if (gelesen != NULL) {
        memset(gelesen, 0, sizeof(*gelesen));   /* enthaelt Passwort und Token */
        free(gelesen);
    }
}

bool vermerk_konfig_speichern(const vermerk_konfig_t *k)
{
    if (vermerk_konfig_pruefen(k) != NULL) {
        return false;
    }
    nvs_handle_t nvs;
    if (nvs_open(NVS_BEREICH, NVS_READWRITE, &nvs) != ESP_OK) {
        return false;
    }
    esp_err_t err = nvs_set_blob(nvs, NVS_SCHLUESSEL, k, sizeof(*k));
    if (err == ESP_OK) {
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    return err == ESP_OK;
}

bool vermerk_konfig_loeschen(void)
{
    nvs_handle_t nvs;
    if (nvs_open(NVS_BEREICH, NVS_READWRITE, &nvs) != ESP_OK) {
        return false;
    }
    esp_err_t err = nvs_erase_key(nvs, NVS_SCHLUESSEL);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_OK;   /* war nicht eingerichtet */
    }
    if (err == ESP_OK) {
        err = nvs_commit(nvs);
    }
    nvs_close(nvs);
    return err == ESP_OK;
}

bool vermerk_konfig_eingerichtet(void)
{
    sicherstellen();
    return s_eingerichtet;
}

const char *vermerk_konfig_wlan_name(void)     { sicherstellen(); return s_konfig.wlan_ssid; }
const char *vermerk_konfig_wlan_passwort(void) { sicherstellen(); return s_konfig.wlan_passwort; }
const char *vermerk_konfig_pc_url(void)        { sicherstellen(); return s_konfig.pc_url; }
const char *vermerk_konfig_pc_token(void)      { sicherstellen(); return s_konfig.pc_token; }
const char *vermerk_konfig_server_url(void)    { sicherstellen(); return s_konfig.server_url; }
const char *vermerk_konfig_server_token(void)  { sicherstellen(); return s_konfig.server_token; }

uint32_t vermerk_konfig_erste_nummer(void)
{
    sicherstellen();
    /* Ohne erste_nummer in der Einrichtung gilt der einkompilierte Wert */
    return (s_eingerichtet && s_konfig.erste_nummer >= 1) ? s_konfig.erste_nummer : s_erste_nummer_standard;
}

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

const char *vermerk_board(void)
{
    sicherstellen();
    return s_board;
}

const char *vermerk_firmware(void)
{
    static char text[64];
    if (text[0] == '\0') {
        snprintf(text, sizeof(text), "%s/%s", vermerk_board(), VERMERK_FIRMWARE_VERSION);
    }
    return text;
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
