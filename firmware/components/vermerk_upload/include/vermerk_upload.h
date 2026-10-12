#pragma once

/* Upload an die Protokoll-Software nach protokoll_assistent/GERAETE-SCHNITTSTELLE.md (Version 1):
 * Token in jeder Anfrage, Erreichbarkeit ueber GET /api/v1/hallo, Upload in Stuecken mit Byte-Versatz
 * (wiederaufnehmbar, auch nach einem Neustart), Abschluss mit Groesse und SHA-256.
 *
 * Adresse und Token kommen aus vermerk_konfig.h. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "vermerk_konfig.h"
#include "vermerk_protokoll.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool erreichbar;          /* 200 und die Antwort ist wirklich die Protokoll-Software */
    int http_status;          /* 0 = keine Antwort, -1 = Ziel oder Token nicht eingerichtet */
    uint32_t teil_max_bytes;  /* von der Software gemeldet, 0 = unbekannt */
} vermerk_hallo_t;

/* GET /api/v1/hallo (Zeitlimit 2 s). Darf aus einer Task mit 4 KB Stack laufen: die Puffer liegen im Heap. */
vermerk_hallo_t vermerk_hallo(vermerk_ziel_t ziel);

/* Wird zwischen zwei Stuecken gefragt; true = jetzt aufhoeren (z. B. weil eine Aufnahme startet). Darf NULL sein. */
typedef bool (*vermerk_abbrechen_t)(void);

/* Eine Datei hochladen bzw. dort weitermachen, wo die Software steht.
 *   teil_max_bytes  aus vermerk_hallo (0 = Standard 256 KiB)
 *   puffer_gross    Lesepuffer im internen RAM; gelingt das nicht, puffer_klein
 * VERMERK_ERGEBNIS_FERTIG erst, wenn die Software "fertig":true gemeldet hat - erst dann darf die
 * lokale Kopie weg. Alles andere laesst die Datei liegen. */
vermerk_ergebnis_t vermerk_upload_datei(vermerk_ziel_t ziel, uint32_t teil_max_bytes,
                                        const char *pfad, const char *name,
                                        size_t puffer_gross, size_t puffer_klein,
                                        vermerk_abbrechen_t abbrechen);

#ifdef __cplusplus
}
#endif
