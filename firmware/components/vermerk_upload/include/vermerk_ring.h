#pragma once

/* Ringpuffer fuer das Senden waehrend der Aufnahme (siehe vermerk_live.h).
 *
 * Ein Erzeuger (die Aufnahme-Task: jede fertige Ogg-Seite) und ein Verbraucher (der Upload-Manager: Stuecke
 * senden und bestaetigen) arbeiten ohne Sperre zusammen, auch auf zwei Kernen. Das geht, weil jeder nur
 * "seinen" Zaehler schreibt und der Erzeuger nie ueber Unbestaetigtes schreibt:
 *   geschrieben  nur der Erzeuger, nach dem Kopieren der Bytes
 *   bestaetigt   nur der Verbraucher, nachdem die Software die Bytes sicher hat
 * Ist der Puffer voll, wird nichts ueberschrieben: Der Erzeuger setzt ueberlauf und schreibt nichts mehr
 * (das Live-Senden endet dann, die fertige Datei wird nach der Aufnahme normal hochgeladen).
 *
 * Die Zaehler sind 32 Bit und zaehlen Bytes seit Beginn der Aufnahme (Byte-Versatz in der Datei). Eine
 * Aufnahme ist hoechstens 2 GB gross (Grenze der Software), der Zaehler laeuft also nie ueber.
 *
 * Reines C ohne ESP-IDF: wird auf dem PC getestet (test/host/). */

#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t *puffer;
    size_t groesse;
    atomic_uint_least32_t geschrieben;
    atomic_uint_least32_t bestaetigt;
    atomic_bool ueberlauf;
} vermerk_ring_t;

/* Puffer (vom Aufrufer bereitgestellt) leer uebernehmen */
void vermerk_ring_init(vermerk_ring_t *ring, uint8_t *puffer, size_t groesse);

/* Erzeuger: Bytes anhaengen. false (und ueberlauf), wenn sie nicht mehr ganz hineinpassen; dann bleibt
 * der Inhalt unveraendert. */
bool vermerk_ring_schreiben(vermerk_ring_t *ring, const uint8_t *daten, size_t laenge);

/* So viele Bytes sind geschrieben, aber noch nicht bestaetigt */
size_t vermerk_ring_unbestaetigt(const vermerk_ring_t *ring);

/* Verbraucher: Die naechsten hoechstens max unbestaetigten Bytes (ab "bestaetigt") als bis zu zwei zusammen-
 * haengende Bereiche (Ende des Puffers, dann Anfang). Liefert die Gesamtzahl; kopiert nichts. */
size_t vermerk_ring_lesen(const vermerk_ring_t *ring, size_t max, const uint8_t **a, size_t *a_laenge,
                          const uint8_t **b, size_t *b_laenge);

/* Verbraucher: Alles bis (ausschliesslich) Byte "bis" ist bei der Software angekommen und darf verworfen
 * werden. false, wenn "bis" nicht im Bereich [bestaetigt, geschrieben] liegt (dann bleibt alles, wie es ist). */
bool vermerk_ring_bestaetigen(vermerk_ring_t *ring, uint64_t bis);

uint32_t vermerk_ring_geschrieben(const vermerk_ring_t *ring);
uint32_t vermerk_ring_bestaetigt(const vermerk_ring_t *ring);
bool vermerk_ring_ueberlauf(const vermerk_ring_t *ring);

#ifdef __cplusplus
}
#endif
