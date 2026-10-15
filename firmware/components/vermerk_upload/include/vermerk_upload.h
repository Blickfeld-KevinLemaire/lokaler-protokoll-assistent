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

/* GET /api/v1/aufnahmen/<name><anhang> (anhang: "" fuer den Upload-Stand, "/status" fuer den Verarbeitungsstand).
 * Rueckgabe: HTTP-Status, 0 = keine Antwort, -1 = Ziel oder Name nicht gueltig. antwort bekommt den Text
 * (hoechstens antwort_max - 1 Bytes, mit Nullbyte). Zeitlimit 4 s; darf aus einer Task mit 4 KB Stack laufen. */
int vermerk_aufnahme_abfragen(vermerk_ziel_t ziel, const char *name, const char *anhang,
                              char *antwort, size_t antwort_max);

/* Auftrag und Rueckfrage des Geraets: gehen mit jeder weiteren Anfrage als Kopfzeilen mit (X-Auftrag, UTF-8
 * prozentcodiert; X-Rueckfrage: 1). auftrag_utf8 = NULL oder "": kein Auftrag (die Software nimmt den aus ihren
 * Einstellungen). Vom Geraet beim Start einer Aufnahme zu setzen: Die Software ordnet beides der Aufnahme zu. */
void vermerk_wunsch_setzen(const char *auftrag_utf8, bool rueckfrage);

/* Allgemeine kleine Anfrage an die Software. pfad beginnt mit "/api/v1/" (nur A-Z a-z 0-9 / _ . -).
 * post = false: GET; post = true: POST mit Inhalt (inhalt_typ darf NULL sein, inhalt darf leer sein).
 * ausgabe (darf NULL sein): Kopfzeile X-Ausgabe ("anzeige" oder "ton").
 * Rueckgabe: HTTP-Status, 0 = keine Antwort, -1 = Ziel, Token oder Pfad nicht gueltig. antwort bekommt den Text
 * der Antwort (hoechstens antwort_max - 1 Bytes, mit Nullbyte). Die Puffer des Aufrufs liegen im Heap. */
int vermerk_anfrage(vermerk_ziel_t ziel, bool post, const char *pfad, const char *inhalt_typ,
                    const uint8_t *inhalt, size_t inhalt_laenge, const char *ausgabe,
                    char *antwort, size_t antwort_max, int timeout_ms);

/* Ein Stueck einer wachsenden Aufnahme anhaengen: PUT mit X-Offset, ohne Abschluss (Senden waehrend der
 * Aufnahme). Die Bytes liegen in zwei Bereichen (Ende und Anfang des Ringpuffers; b darf leer sein).
 * Rueckgabe wie oben; antwort bekommt den Text, mit dem vermerk_live_entscheiden() weiterarbeitet. */
int vermerk_teil_anhaengen(vermerk_ziel_t ziel, const char *name, uint64_t offset,
                           const uint8_t *a, size_t a_laenge, const uint8_t *b, size_t b_laenge,
                           char *antwort, size_t antwort_max);

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
