/* Senden waehrend der Aufnahme, siehe vermerk_live.h. */

#include "vermerk_live.h"

#include "vermerk_protokoll.h"
#include "vermerk_ring.h"
#include "vermerk_upload.h"

#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include <stdio.h>
#include <string.h>

typedef enum {
    LIVE_AUS = 0,   /* nichts zu tun (keine Aufnahme, oder aufgegeben) */
    LIVE_AKTIV,     /* Aufnahme laeuft, Seiten kommen in den Ringpuffer */
    LIVE_ENDE       /* Aufnahme zu Ende, nichts mehr annehmen */
} live_zustand_t;

#define NAME_MAX_LAENGE 40

static vermerk_ring_t s_ring;
static uint8_t *s_puffer = NULL;       /* einmal im PSRAM angelegt und behalten: nichts wird je freigegeben */
static size_t s_puffer_groesse = 0;
static volatile live_zustand_t s_zustand = LIVE_AUS;
static char s_name[NAME_MAX_LAENGE];
static uint64_t s_letzter_versuch_ms = 0;
static bool s_stand_geprueft = false;
static uint32_t s_fehlversuche = 0;
static uint32_t s_stuecke = 0;
static SemaphoreHandle_t s_sperre = NULL;   /* schuetzt Anlegen und Senden voreinander; die Seiten laufen ohne Sperre */

static uint64_t jetzt_ms(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000);
}

static void aufgeben(const char *grund)
{
    s_zustand = LIVE_AUS;   /* vermerk_live_seite nimmt nichts mehr an */
    printf("VERMERK Live %s: beendet (%s), %u Stuecke gesendet, bestaetigt %u von %u Bytes. "
           "Die fertige Aufnahme wird nach dem Ende normal hochgeladen.\n",
           s_name, grund, (unsigned)s_stuecke, (unsigned)vermerk_ring_bestaetigt(&s_ring),
           (unsigned)vermerk_ring_geschrieben(&s_ring));
}

bool vermerk_live_beginnen(const char *name)
{
    s_zustand = LIVE_AUS;
    if (name == NULL || !vermerk_name_gueltig(name) || strlen(name) >= NAME_MAX_LAENGE) {
        return false;
    }
    if (s_sperre == NULL) {
        s_sperre = xSemaphoreCreateMutex();
        if (s_sperre == NULL) {
            return false;
        }
    }
    /* Haengt der Upload-Manager noch in einer Anfrage der vorigen Aufnahme, fuer diese kein Live-Senden:
     * hier darf nie gewartet werden (die Aufnahme liefe sonst an), und es geht nichts verloren. */
    if (xSemaphoreTake(s_sperre, 0) != pdTRUE) {
        return false;
    }

    if (s_puffer == NULL) {
        static const size_t groessen[] = {VERMERK_LIVE_RING_BYTES, VERMERK_LIVE_RING_BYTES / 2,
                                          VERMERK_LIVE_RING_BYTES / 4};
        for (size_t i = 0; i < sizeof(groessen) / sizeof(groessen[0]) && s_puffer == NULL; i++) {
            s_puffer = heap_caps_malloc(groessen[i], MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            s_puffer_groesse = (s_puffer != NULL) ? groessen[i] : 0;
        }
    }
    if (s_puffer == NULL) {
        xSemaphoreGive(s_sperre);
        printf("VERMERK Live: kein PSRAM fuer den Ringpuffer, kein Senden waehrend der Aufnahme\n");
        return false;
    }

    vermerk_ring_init(&s_ring, s_puffer, s_puffer_groesse);
    strncpy(s_name, name, sizeof(s_name) - 1);
    s_name[sizeof(s_name) - 1] = '\0';
    s_letzter_versuch_ms = 0;
    s_stand_geprueft = false;
    s_fehlversuche = 0;
    s_stuecke = 0;
    s_zustand = LIVE_AKTIV;   /* zuletzt: erst jetzt nimmt vermerk_live_seite Seiten an */
    xSemaphoreGive(s_sperre);
    printf("VERMERK Live %s: bereit (Ringpuffer %u KB)\n", s_name, (unsigned)(s_puffer_groesse / 1024));
    return true;
}

void vermerk_live_seite(const uint8_t *seite, size_t laenge)
{
    if (s_zustand != LIVE_AKTIV) {
        return;
    }
    if (!vermerk_ring_schreiben(&s_ring, seite, laenge)) {
        /* Ringpuffer voll (das Ziel war zu lange nicht erreichbar): Live-Senden endet, die Aufnahme laeuft
         * ungestoert weiter und wird nach dem Ende normal hochgeladen. */
        s_zustand = LIVE_AUS;
        printf("VERMERK Live %s: Ringpuffer voll (%u B unbestaetigt), kein Senden mehr waehrend der Aufnahme\n",
               s_name, (unsigned)vermerk_ring_unbestaetigt(&s_ring));
    }
}

void vermerk_live_beenden(void)
{
    if (s_zustand == LIVE_AKTIV) {
        s_zustand = LIVE_ENDE;
    }
}

/* Die Software kennt die Aufnahme schon (anderer Stand als 0): Das Live-Senden passt nicht dazu. */
static bool stand_pruefen(vermerk_ziel_t ziel)
{
    char antwort[128];
    int status = vermerk_aufnahme_abfragen(ziel, s_name, "", antwort, sizeof(antwort));
    vermerk_entscheidung_t e = vermerk_entscheiden(VERMERK_PHASE_STATUS, status, antwort, strlen(antwort), false);

    if (e.aktion == VERMERK_AKTION_WEITER_AB) {
        if (e.naechstes_byte != 0) {
            aufgeben("die Software hat schon einen Teilstand unter diesem Namen");
            return false;
        }
        s_stand_geprueft = true;
        return true;
    }
    if (e.aktion == VERMERK_AKTION_AUFGEBEN) {
        aufgeben("die Software lehnt die Abfrage ab");
    }
    return false;   /* vorruebergehend: beim naechsten Mal */
}

static void senden(vermerk_ziel_t ziel, uint32_t teil_max_bytes)
{
    size_t max = vermerk_teil_bytes(teil_max_bytes);
    if (max > VERMERK_LIVE_STUECK_MAX) {
        max = VERMERK_LIVE_STUECK_MAX;
    }
    const uint8_t *a, *b;
    size_t a_laenge, b_laenge;
    size_t n = vermerk_ring_lesen(&s_ring, max, &a, &a_laenge, &b, &b_laenge);
    if (n == 0) {
        return;
    }
    const uint32_t ab = vermerk_ring_bestaetigt(&s_ring);

    char antwort[160];
    int64_t t0 = esp_timer_get_time();
    int status = vermerk_teil_anhaengen(ziel, s_name, ab, a, a_laenge, b, b_laenge, antwort, sizeof(antwort));
    int64_t dauer_ms = (esp_timer_get_time() - t0) / 1000;

    vermerk_live_entscheidung_t e =
        vermerk_live_entscheiden(status, antwort, strlen(antwort), ab, vermerk_ring_geschrieben(&s_ring));
    switch (e.aktion) {
    case VERMERK_LIVE_WEITER:
        if (vermerk_ring_bestaetigen(&s_ring, e.naechstes_byte)) {
            s_fehlversuche = 0;
            s_stuecke++;
            printf("VERMERK Live %s: Byte %u bis %u gesendet (%u B in %lld ms), Rueckstand %u B\n", s_name,
                   (unsigned)ab, (unsigned)e.naechstes_byte, (unsigned)n, (long long)dauer_ms,
                   (unsigned)vermerk_ring_unbestaetigt(&s_ring));
        }
        break;
    case VERMERK_LIVE_SPAETER:
        /* Nicht jede Wiederholung melden: nur die erste und dann alle zehn */
        if (s_fehlversuche++ % 10 == 0) {
            printf("VERMERK Live %s: HTTP %d, Rueckstand %u B, spaeter erneut\n", s_name, status,
                   (unsigned)vermerk_ring_unbestaetigt(&s_ring));
        }
        break;
    default:
        aufgeben(status == 0 ? "keine Antwort" : "die Software lehnt das Stueck ab");
        break;
    }
}

void vermerk_live_schritt(vermerk_ziel_t ziel, uint32_t teil_max_bytes)
{
    if (s_sperre == NULL || s_zustand == LIVE_AUS) {
        return;
    }
    xSemaphoreTake(s_sperre, portMAX_DELAY);

    if (s_zustand == LIVE_AKTIV || s_zustand == LIVE_ENDE) {
        if (vermerk_ring_ueberlauf(&s_ring)) {
            aufgeben("Ringpuffer voll");
        } else if (s_zustand == LIVE_AKTIV && vermerk_ring_unbestaetigt(&s_ring) > 0) {
            const uint64_t jetzt = jetzt_ms();
            const bool rueckstand = vermerk_ring_unbestaetigt(&s_ring) >= VERMERK_LIVE_STUECK_MAX;
            if (rueckstand || s_letzter_versuch_ms == 0 || jetzt - s_letzter_versuch_ms >= VERMERK_LIVE_INTERVALL_MS) {
                s_letzter_versuch_ms = jetzt;
                if (s_stand_geprueft || stand_pruefen(ziel)) {
                    if (s_zustand == LIVE_AKTIV) {
                        senden(ziel, teil_max_bytes);
                    }
                }
            }
        }
    }
    xSemaphoreGive(s_sperre);
}
