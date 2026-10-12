#pragma once

#include <stdint.h>

/* Automatische Pegelregelung (AGC) fuer die Aufnahme.
 *
 * Problem: Sprache aus einigen Metern Abstand liegt oft bei -50 bis -60 dB und ist beim Abspielen kaum zu hoeren.
 * Loesung: Der Pegel wird blockweise (ca. 16 ms) gemessen und die Verstaerkung langsam nachgefuehrt:
 *   - leise Sprache wird bis maximal +18 dB angehoben, auf eine einheitliche Spitzenhoehe
 *   - laute Stellen senken die Verstaerkung sofort, so dass nichts uebersteuert
 *   - Stille und Rauschen (unter der Rauschschwelle) werden NICHT hochgezogen
 * Festkomma-Rechnung, damit es auch auf dem C6 (ohne Gleitkommaeinheit) guenstig ist. */

/* Block in place bearbeiten (Mono, 16 Bit). */
void agc_process(int16_t *samples, int count);

/* Aktuelle Verstaerkung in Zehntel (10 = 1,0-fach, 80 = 8-fach) fuer die Diagnoseausgabe. */
int agc_gain_x10(void);
