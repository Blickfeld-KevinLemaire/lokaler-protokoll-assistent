#include "Gain_Control.h"

#include <stdlib.h>

#define GAIN_ONE        4096                 /* Q12: 4096 = 1,0-fach */
#define GAIN_MAX        (8 * GAIN_ONE)       /* +18 dB */
#define GAIN_START      (2 * GAIN_ONE)       /* Startwert: +6 dB, damit der Anfang nicht zu leise ist */

#define TARGET_PEAK     12000                /* gewuenschte Blockspitze (ca. -8,7 dBFS) */
#define LIMIT_PEAK      29000                /* nie darueber (ca. -1 dBFS) */
#define NOISE_GATE      250                  /* Blockspitzen darunter (ca. -42 dBFS) sind Rauschen/Stille: Verstaerkung nicht anheben */

#define RISE_SHIFT      6                    /* langsam hoch: ca. 1 s */
#define FALL_SHIFT      3                    /* schnell runter: ca. 130 ms */
#define IDLE_DECAY_SHIFT 11                  /* in der Stille sehr langsam Richtung Start: ca. 30 s */

static int32_t s_gain = GAIN_START;

void agc_process(int16_t *samples, int count)
{
    int32_t peak = 0;
    for (int i = 0; i < count; i++) {
        int32_t v = samples[i];
        if (v < 0) v = -v;
        if (v > peak) peak = v;
    }

    int32_t g = s_gain;

    if (peak >= NOISE_GATE) {
        /* gewuenschte Verstaerkung, damit die Spitze auf TARGET_PEAK kommt */
        int32_t desired = (int32_t)(((int64_t)TARGET_PEAK * GAIN_ONE) / peak);
        if (desired > GAIN_MAX) desired = GAIN_MAX;
        if (desired < GAIN_ONE / 4) desired = GAIN_ONE / 4;

        if (desired < g) {
            g -= (g - desired) >> FALL_SHIFT;
        } else {
            g += (desired - g) >> RISE_SHIFT;
        }
    } else {
        /* Stille: Verstaerkung halten, ganz langsam Richtung Startwert */
        g -= (g - GAIN_START) >> IDLE_DECAY_SHIFT;
    }

    /* Harte Obergrenze: die Spitze dieses Blocks darf nie ueber LIMIT_PEAK kommen */
    if (peak > 0 && ((int64_t)peak * g) > ((int64_t)LIMIT_PEAK * GAIN_ONE)) {
        g = (int32_t)(((int64_t)LIMIT_PEAK * GAIN_ONE) / peak);
    }
    s_gain = g;

    for (int i = 0; i < count; i++) {
        int32_t v = ((int32_t)samples[i] * g) >> 12;
        if (v > 32767) v = 32767;
        if (v < -32768) v = -32768;
        samples[i] = (int16_t)v;
    }
}

int agc_gain_x10(void)
{
    return (int)((int64_t)s_gain * 10 / GAIN_ONE);
}
