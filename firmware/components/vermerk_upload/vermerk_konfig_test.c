/* Einkompilierte Werte fuer den QEMU-Test: keine (das Geraet ist "nicht eingerichtet"), Board "e2e-qemu".
 * Dazu der Test-Zugang (vermerk_konfig_test.h), mit dem die Upload-Faelle Adresse und Token zur Laufzeit
 * setzen. Ersetzt vermerk_konfig_standard.c, wenn CONFIG_VERMERK_KONFIG_TEST eingeschaltet ist - auf den
 * Geraeten nie. */

#include "vermerk_konfig_test.h"
#include "vermerk_konfig_intern.h"

#include <stdio.h>

void vermerk_konfig_standard(vermerk_konfig_t *k, const char **board)
{
    k->erste_nummer = 1;
    *board = "e2e-qemu";
}

void vermerk_konfig_test_ziel(vermerk_ziel_t ziel, const char *url, const char *token)
{
    vermerk_konfig_t *k = vermerk_konfig_aktuell();
    bool server = (ziel == VERMERK_ZIEL_SERVER);
    snprintf(server ? k->server_url : k->pc_url, sizeof(k->pc_url), "%s", (url != NULL) ? url : "");
    snprintf(server ? k->server_token : k->pc_token, sizeof(k->pc_token), "%s", (token != NULL) ? token : "");
}

void vermerk_konfig_test_erste_nummer(uint32_t nummer)
{
    vermerk_konfig_aktuell()->erste_nummer = (nummer >= 1) ? nummer : 1;
}
