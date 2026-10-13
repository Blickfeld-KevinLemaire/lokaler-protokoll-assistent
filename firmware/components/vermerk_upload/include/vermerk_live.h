#pragma once

/* Senden waehrend der Aufnahme (protokoll_assistent/GERAETE-SCHNITTSTELLE.md, "Senden waehrend der Aufnahme").
 *
 * Der Encoder gibt jede fertige Ogg-Seite an vermerk_live_seite(); sie landet in einem Ringpuffer im PSRAM.
 * Der Upload-Manager ruft waehrend der Aufnahme vermerk_live_schritt(): alle 15 s sendet er die neuen Bytes mit
 * PUT und X-Offset an die Software. Die Software transkribiert die Aufnahme daraufhin schon, waehrend sie laeuft.
 *
 * Es geht nie etwas verloren, auch wenn dies hier scheitert: Die Aufnahme liegt ohnehin ganz auf der SD-Karte.
 * Nach der Aufnahme laedt der normale Upload dort weiter, wo die Software steht (GET .../aufnahmen/<Name> ->
 * naechstes_byte), und schliesst mit Groesse und Pruefsumme ab. Das Live-Senden hoert auf, wenn
 *   - der Ringpuffer voll wird (WLAN lange weg),
 *   - die Software den Stand nicht zur Aufnahme passend meldet (Luecke) oder dauerhaft ablehnt (Token, Name).
 *
 * Aufrufer: vermerk_live_beginnen / _seite / _beenden aus der Aufnahme-Task (auch _seite, bitte schnell:
 * nur kopieren), vermerk_live_schritt aus dem Upload-Manager. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "vermerk_konfig.h"

#ifdef __cplusplus
extern "C" {
#endif

#define VERMERK_LIVE_INTERVALL_MS  15000u            /* so oft werden die neuen Bytes gesendet */
#define VERMERK_LIVE_RING_BYTES    (1024u * 1024u)   /* ca. 5,7 Minuten bei 24 kbit/s; kleinere Groessen als Ersatz */
#define VERMERK_LIVE_STUECK_MAX    (64u * 1024u)     /* hoechstens so viel je PUT: die Anfrage bleibt kurz */

/* Vor der ersten Seite einer Aufnahme (vor dem Schreiben der Ogg-Kopfseiten): Aufnahmename wie am Ziel
 * (z. B. "H5_007.opus"). false: kein Live-Senden fuer diese Aufnahme (kein PSRAM, Name ungueltig, ...). */
bool vermerk_live_beginnen(const char *name);

/* Eine fertige Ogg-Seite (Encoder-Haken). Tut nichts, wenn nicht live gesendet wird. */
void vermerk_live_seite(const uint8_t *seite, size_t laenge);

/* Die Aufnahme ist zu Ende (gespeichert oder abgebrochen): keine Seiten mehr annehmen. */
void vermerk_live_beenden(void);

/* Waehrend einer Aufnahme regelmaessig aufrufen (etwa alle 1 bis 2 s). Sendet hoechstens ein Stueck;
 * kehrt sofort zurueck, wenn nichts zu tun ist. ziel/teil_max_bytes wie beim Upload (vermerk_hallo). */
void vermerk_live_schritt(vermerk_ziel_t ziel, uint32_t teil_max_bytes);

#ifdef __cplusplus
}
#endif
