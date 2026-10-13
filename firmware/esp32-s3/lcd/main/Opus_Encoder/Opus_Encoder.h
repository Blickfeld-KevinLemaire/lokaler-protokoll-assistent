#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/* Aufnahme als Ogg-Opus (.opus): Mono, 16 kHz.
 * Die Protokoll-Software rechnet ohnehin alles auf Mono / 16 kHz um (ffmpeg -ac 1 -ar 16000).
 * Bitrate in bit/s (bei 16 kHz und Frames ab 10 ms erlaubt: 6000 ... 256000):
 *   16000 =  2,0 KB/s =  7,2 MB/Stunde  (ca. 115 min auf 13,8 MB)
 *   24000 =  3,0 KB/s = 10,8 MB/Stunde  (ca.  77 min)   <- Standard
 *   32000 =  4,0 KB/s = 14,4 MB/Stunde  (ca.  58 min)
 * Mit variabler Bitrate (VBR) ist das ein Mittelwert: Pausen kosten weniger.
 * Messung mit Whisper large-v3-turbo an vier echten Aufnahmen (Oktober 2026): Bei sauberer Sprache
 * ist selbst 12 kbit/s unauffaellig, bei schlechtem Material (Rauschen, Abstand zum Mikrofon) steigt
 * die Abweichung vom unkomprimierten Original unterhalb von 24 kbit/s spuerbar. */
#define OPUS_SAMPLE_RATE     16000
#define OPUS_BITRATE_BPS     24000
#define OPUS_COMPLEXITY      2        /* 0 = schnell ... 10 = beste Qualitaet; kostet Rechenzeit */
#define OPUS_FRAME_MS        20       /* kurze Frames: der Encoder braucht dann ca. 22 KB Stack, bei 40 ms mehr als 20 KB */

/* Haken fuer jede fertig geschriebene Ogg-Seite (auch die Kopfseiten): Die Seite ist vollstaendig und liegt
 * im Puffer des Encoders; der Haken muss sie sofort kopieren und schnell zurueckkehren (er laeuft in der
 * Aufnahme-Task). NULL = kein Haken. Dient dem Senden waehrend der Aufnahme (vermerk_live). */
typedef void (*opus_seiten_haken_t)(const uint8_t *seite, size_t laenge);
void opus_enc_seiten_haken(opus_seiten_haken_t haken);

/* Encoder einmalig anlegen, solange noch ein grosser RAM-Block frei ist (vor WLAN und Display). */
bool opus_enc_init(void);

/* Neue Datei beginnen (setzt den Encoder zurueck, schreibt die Ogg-Kopfseiten). */
bool opus_enc_begin(FILE *f);

/* Mono-Samples (16 Bit, 16 kHz) einspeisen. false, wenn das Schreiben fehlschlug (Speicher voll). */
bool opus_enc_push(const int16_t *mono, int count);

/* Restpuffer enden lassen, Abschlussseite schreiben. Die Datei bleibt offen. */
bool opus_enc_end(void);

/* Datei loslassen (nach Fehler). Der Encoder bleibt im RAM. */
void opus_enc_abort(void);

/* Rechenzeit des Encoders im Verhaeltnis zur Aufnahmedauer in Prozent (Messung). */
int opus_enc_load_percent(void);
