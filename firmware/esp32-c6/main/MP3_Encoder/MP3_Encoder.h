#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

/* Aufnahme-Qualitaet: Die Transkriptionssoftware rechnet ohnehin alles auf
 * Mono / 16 kHz um (ffmpeg -ac 1 -ar 16000), daher nehmen wir direkt so auf.
 * Bitrate (kbit/s, MPEG-2 Layer III bei 16 kHz erlaubt: 8, 16, 24, 32, 40, 48, ...):
 *   32 kbit/s = 4,0 KB/s = 14,4 MB/Stunde   (Standard)
 *   24 kbit/s = 3,0 KB/s = 10,8 MB/Stunde
 *   16 kbit/s = 2,0 KB/s =  7,2 MB/Stunde */
#define MP3_SAMPLE_RATE      16000
#define MP3_BITRATE_KBPS     32

/* Encoder einmalig anlegen. Muss frueh beim Start laufen (vor WLAN und Display), solange
 * noch ein grosser zusammenhaengender RAM-Block frei ist. */
bool mp3_enc_init(void);

/* Beginnt eine neue MP3-Datei (neuer Encoder, schreibt in f). false bei Speichermangel. */
bool mp3_enc_begin(FILE *f);

/* Mono-Samples (16 Bit, 16 kHz) einspeisen; fertige MP3-Frames werden direkt in die Datei
 * geschrieben. Gibt false zurueck, wenn das Schreiben fehlschlug (z. B. Speicher voll). */
bool mp3_enc_push(const int16_t *mono, int count);

/* Restpuffer enden lassen, letzte Frames schreiben, Encoder freigeben. Die Datei bleibt offen. */
bool mp3_enc_end(void);

/* Encoder verwerfen (nach Fehler). */
void mp3_enc_abort(void);

/* Auslastung des Encoders seit dem Start in Prozent (Rechenzeit / Echtzeit), fuer die Messung. */
int mp3_enc_load_percent(void);
