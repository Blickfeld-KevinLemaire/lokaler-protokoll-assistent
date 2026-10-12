#pragma once

/* Nur fuer den QEMU-Test (test/qemu, CONFIG_VERMERK_KONFIG_TEST=y): Einstellungen zur Laufzeit setzen,
 * damit ein Testlauf mehrere Ziele und Tokens nacheinander ausprobieren kann. Auf den Geraeten wird
 * vermerk_konfig_test.c nicht gebaut; dort kommen die Werte aus server_config.h (vermerk_konfig.c). */

#include "vermerk_konfig.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Die Texte werden nicht kopiert: Sie muessen gueltig bleiben, solange sie gesetzt sind. */
void vermerk_konfig_test_ziel(vermerk_ziel_t ziel, const char *url, const char *token);
void vermerk_konfig_test_erste_nummer(uint32_t nummer);

#ifdef __cplusplus
}
#endif
