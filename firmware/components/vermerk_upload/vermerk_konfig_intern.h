#pragma once

/* Nur innerhalb der Komponente: woher die einkompilierten Werte kommen.
 *   vermerk_konfig_standard.c  Geraete: server_config.h, wifi_credentials.h, vermerk_board.h
 *   vermerk_konfig_test.c      QEMU-Test (CONFIG_VERMERK_KONFIG_TEST): leer, Board "e2e-qemu" */

#include "vermerk_einrichtung.h"

/* Einkompilierte Werte in k eintragen (k ist vorher genullt). erste_nummer: einkompilierter Wert, mind. 1. */
void vermerk_konfig_standard(vermerk_konfig_t *k, const char **board);

/* Die gerade geltenden Werte (fuer den Test-Zugang in vermerk_konfig_test.c) */
vermerk_konfig_t *vermerk_konfig_aktuell(void);
