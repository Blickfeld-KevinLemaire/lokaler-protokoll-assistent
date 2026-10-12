/* Einstellungen fuer den QEMU-Test: zur Laufzeit gesetzt (vermerk_konfig_test.h). Ersetzt vermerk_konfig.c,
 * wenn CONFIG_VERMERK_KONFIG_TEST eingeschaltet ist - auf den Geraeten nie. */

#include "vermerk_konfig_test.h"

#include <stddef.h>

static const char *s_url[2] = {"", ""};
static const char *s_token[2] = {"", ""};
static uint32_t s_erste_nummer = 1;

void vermerk_konfig_test_ziel(vermerk_ziel_t ziel, const char *url, const char *token)
{
    int i = (ziel == VERMERK_ZIEL_SERVER) ? 0 : 1;
    s_url[i] = (url != NULL) ? url : "";
    s_token[i] = (token != NULL) ? token : "";
}

void vermerk_konfig_test_erste_nummer(uint32_t nummer)
{
    s_erste_nummer = (nummer >= 1) ? nummer : 1;
}

const char *vermerk_konfig_wlan_name(void)     { return ""; }   /* QEMU: Ethernet statt WLAN */
const char *vermerk_konfig_wlan_passwort(void) { return ""; }

const char *vermerk_konfig_server_url(void)    { return s_url[0]; }
const char *vermerk_konfig_server_token(void)  { return s_token[0]; }
const char *vermerk_konfig_pc_url(void)        { return s_url[1]; }
const char *vermerk_konfig_pc_token(void)      { return s_token[1]; }

uint32_t vermerk_konfig_erste_nummer(void)     { return s_erste_nummer; }

const char *vermerk_firmware(void)
{
    return "e2e-qemu/" VERMERK_FIRMWARE_VERSION;
}
