/* Tests fuer den Ringpuffer des Live-Sendens (vermerk_ring.c), laufen auf dem PC:
 *   make test
 * Kein Test-Framework: PRUEFE zaehlt Fehler und meldet Datei und Zeile. */

#include "vermerk_ring.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int pruefungen = 0;
static int fehler = 0;

#define PRUEFE(bedingung)                                                         \
    do {                                                                          \
        pruefungen++;                                                             \
        if (!(bedingung)) {                                                       \
            fehler++;                                                             \
            fprintf(stderr, "%s:%d: FEHLER: %s\n", __FILE__, __LINE__, #bedingung); \
        }                                                                         \
    } while (0)

/* Der Puffer liegt auf dem Heap, genau gross: AddressSanitizer meldet jedes Schreiben oder Lesen darueber hinaus */
static vermerk_ring_t ring_neu(size_t groesse)
{
    vermerk_ring_t r;
    uint8_t *p = malloc(groesse);
    if (p == NULL) {
        abort();
    }
    memset(p, 0xEE, groesse);
    vermerk_ring_init(&r, p, groesse);
    return r;
}

static void ring_frei(vermerk_ring_t *r)
{
    free(r->puffer);
    r->puffer = NULL;
}

/* Bytes mit fortlaufendem Muster: byte(i) = (i * 7 + 3) & 0xFF, damit Verwechslungen auffallen */
static uint8_t muster(uint64_t i)
{
    return (uint8_t)((i * 7u + 3u) & 0xFFu);
}

static void erzeugen(uint8_t *ziel, uint64_t ab, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        ziel[i] = muster(ab + i);
    }
}

/* Alles Unbestaetigte lesen (beide Bereiche zusammengesetzt) und mit dem Muster ab "ab" vergleichen */
static bool inhalt_stimmt(const vermerk_ring_t *r, uint64_t ab, size_t max, size_t *gelesen)
{
    const uint8_t *a, *b;
    size_t al, bl;
    size_t n = vermerk_ring_lesen(r, max, &a, &al, &b, &bl);
    *gelesen = n;
    if (al + bl != n) {
        return false;
    }
    for (size_t i = 0; i < al; i++) {
        if (a[i] != muster(ab + i)) {
            return false;
        }
    }
    for (size_t i = 0; i < bl; i++) {
        if (b[i] != muster(ab + al + i)) {
            return false;
        }
    }
    return true;
}

static void test_leer(void)
{
    vermerk_ring_t r = ring_neu(16);
    const uint8_t *a, *b;
    size_t al, bl;
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 0 && !vermerk_ring_ueberlauf(&r));
    PRUEFE(vermerk_ring_lesen(&r, 100, &a, &al, &b, &bl) == 0 && a == NULL && b == NULL && al == 0 && bl == 0);
    PRUEFE(vermerk_ring_bestaetigen(&r, 0));      /* nichts zu bestaetigen ist in Ordnung */
    PRUEFE(!vermerk_ring_bestaetigen(&r, 1));     /* mehr als geschrieben */
    PRUEFE(vermerk_ring_schreiben(&r, NULL, 0));  /* nichts schreiben ist erlaubt */
    PRUEFE(!vermerk_ring_schreiben(&r, NULL, 1));
    PRUEFE(!vermerk_ring_ueberlauf(&r));
    ring_frei(&r);

    vermerk_ring_t ohne = {0};
    PRUEFE(!vermerk_ring_schreiben(&ohne, (const uint8_t *)"x", 1));
    PRUEFE(vermerk_ring_lesen(&ohne, 10, &a, &al, &b, &bl) == 0);
}

static void test_schreiben_lesen_bestaetigen(void)
{
    vermerk_ring_t r = ring_neu(16);
    uint8_t quelle[64];
    erzeugen(quelle, 0, sizeof(quelle));
    size_t n;

    PRUEFE(vermerk_ring_schreiben(&r, quelle, 10));
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 10 && vermerk_ring_geschrieben(&r) == 10);
    PRUEFE(inhalt_stimmt(&r, 0, 100, &n) && n == 10);
    PRUEFE(inhalt_stimmt(&r, 0, 4, &n) && n == 4);       /* max begrenzt */

    PRUEFE(vermerk_ring_bestaetigen(&r, 4));
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 6 && vermerk_ring_bestaetigt(&r) == 4);
    PRUEFE(inhalt_stimmt(&r, 4, 100, &n) && n == 6);
    PRUEFE(!vermerk_ring_bestaetigen(&r, 3));            /* nicht zurueck */
    PRUEFE(!vermerk_ring_bestaetigen(&r, 11));           /* nicht ueber geschrieben hinaus */
    PRUEFE(!vermerk_ring_bestaetigen(&r, (uint64_t)UINT32_MAX + 1u));
    PRUEFE(vermerk_ring_bestaetigt(&r) == 4);            /* unveraendert nach Fehlschlaegen */
    PRUEFE(vermerk_ring_bestaetigen(&r, 4));             /* dasselbe noch einmal ist harmlos */
    PRUEFE(vermerk_ring_bestaetigen(&r, 10));
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 0 && inhalt_stimmt(&r, 10, 100, &n) && n == 0);
    ring_frei(&r);
}

static void test_umlauf_im_puffer(void)
{
    vermerk_ring_t r = ring_neu(16);
    uint8_t quelle[64];
    erzeugen(quelle, 0, sizeof(quelle));
    size_t n;
    const uint8_t *a, *b;
    size_t al, bl;

    /* 12 Bytes schreiben und bestaetigen, dann 10 weitere: das Stueck laeuft ueber das Ende des Puffers */
    PRUEFE(vermerk_ring_schreiben(&r, quelle, 12));
    PRUEFE(vermerk_ring_bestaetigen(&r, 12));
    PRUEFE(vermerk_ring_schreiben(&r, quelle + 12, 10));
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 10);
    PRUEFE(vermerk_ring_lesen(&r, 100, &a, &al, &b, &bl) == 10);
    PRUEFE(al == 4 && bl == 6 && a == r.puffer + 12 && b == r.puffer);   /* zwei Bereiche */
    PRUEFE(inhalt_stimmt(&r, 12, 100, &n) && n == 10);
    PRUEFE(inhalt_stimmt(&r, 12, 5, &n) && n == 5);

    /* zwei Bereiche, aber max endet im ersten */
    PRUEFE(vermerk_ring_lesen(&r, 3, &a, &al, &b, &bl) == 3 && al == 3 && bl == 0 && b == NULL);
    ring_frei(&r);
}

static void test_voll_und_ueberlauf(void)
{
    vermerk_ring_t r = ring_neu(16);
    uint8_t quelle[64];
    erzeugen(quelle, 0, sizeof(quelle));
    size_t n;

    PRUEFE(vermerk_ring_schreiben(&r, quelle, 16));       /* genau voll */
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 16 && !vermerk_ring_ueberlauf(&r));
    PRUEFE(inhalt_stimmt(&r, 0, 100, &n) && n == 16);

    PRUEFE(!vermerk_ring_schreiben(&r, quelle + 16, 1));  /* ein Byte zu viel: nichts wird ueberschrieben */
    PRUEFE(vermerk_ring_ueberlauf(&r));
    PRUEFE(vermerk_ring_geschrieben(&r) == 16);
    PRUEFE(inhalt_stimmt(&r, 0, 100, &n) && n == 16);     /* Inhalt unversehrt */
    PRUEFE(vermerk_ring_bestaetigen(&r, 16));
    PRUEFE(!vermerk_ring_schreiben(&r, quelle, 1));       /* nach dem Ueberlauf wird nichts mehr angenommen */
    ring_frei(&r);

    r = ring_neu(16);
    PRUEFE(!vermerk_ring_schreiben(&r, quelle, 17));      /* groesser als der ganze Puffer */
    PRUEFE(vermerk_ring_ueberlauf(&r) && vermerk_ring_geschrieben(&r) == 0);
    ring_frei(&r);

    /* Platz entsteht durch Bestaetigen */
    r = ring_neu(16);
    PRUEFE(vermerk_ring_schreiben(&r, quelle, 12));
    PRUEFE(vermerk_ring_bestaetigen(&r, 8));
    PRUEFE(vermerk_ring_schreiben(&r, quelle + 12, 12));  /* 4 unbestaetigt + 12 = 16 */
    PRUEFE(!vermerk_ring_ueberlauf(&r) && vermerk_ring_unbestaetigt(&r) == 16);
    PRUEFE(inhalt_stimmt(&r, 8, 100, &n) && n == 16);
    ring_frei(&r);
}

/* Lange Folge: Stuecke unterschiedlicher Groesse schreiben, in anderen Stuecken senden und bestaetigen.
 * Nichts darf verloren gehen oder sich verschieben, auch nach vielen Runden durch den Puffer. */
static void test_dauerlauf(void)
{
    enum { GROESSE = 100, RUNDEN = 5000 };
    vermerk_ring_t r = ring_neu(GROESSE);
    uint8_t quelle[40];
    uint64_t erzeugt = 0, bestaetigt = 0;
    uint32_t zufall = 12345;
    bool alles_gut = true;

    for (int runde = 0; runde < RUNDEN && alles_gut; runde++) {
        zufall = zufall * 1103515245u + 12345u;
        size_t laenge = (zufall >> 16) % 40u + 1u;
        erzeugen(quelle, erzeugt, laenge);
        if (vermerk_ring_schreiben(&r, quelle, laenge)) {
            erzeugt += laenge;
        } else {
            alles_gut = false;   /* wird unten per Bestaetigen vermieden: es darf nie ueberlaufen */
            break;
        }
        /* senden: hoechstens 37 Bytes, davon "angekommen" zufaellig viele */
        size_t n;
        if (!inhalt_stimmt(&r, bestaetigt, 37, &n)) {
            alles_gut = false;
            break;
        }
        zufall = zufall * 1103515245u + 12345u;
        size_t angekommen = n == 0 ? 0 : (zufall >> 16) % (n + 1u);
        if (!vermerk_ring_bestaetigen(&r, bestaetigt + angekommen)) {
            alles_gut = false;
            break;
        }
        bestaetigt += angekommen;
        /* Der Verbraucher haelt Schritt, wenn der Puffer zu voll wird: sonst liefe er ueber */
        while (vermerk_ring_unbestaetigt(&r) > GROESSE - 41u) {
            if (!inhalt_stimmt(&r, bestaetigt, 37, &n) || n == 0 ||
                !vermerk_ring_bestaetigen(&r, bestaetigt + n)) {
                alles_gut = false;
                break;
            }
            bestaetigt += n;
        }
    }
    PRUEFE(alles_gut);
    PRUEFE(!vermerk_ring_ueberlauf(&r));
    PRUEFE(erzeugt > (uint64_t)GROESSE * 20u);   /* mehrfach durch den Puffer gelaufen */
    PRUEFE(vermerk_ring_geschrieben(&r) == (uint32_t)erzeugt && vermerk_ring_bestaetigt(&r) == (uint32_t)bestaetigt);
    ring_frei(&r);
}

/* Die 32-Bit-Zaehler laufen irgendwann ueber (hier erzwungen): Rechnen und Bestaetigen muessen weiter stimmen */
static void test_zaehlerueberlauf(void)
{
    vermerk_ring_t r = ring_neu(16);
    uint8_t quelle[16];
    const uint32_t start = UINT32_MAX - 5u;   /* 6 Bytes bis zum Ueberlauf */
    atomic_store(&r.geschrieben, start);
    atomic_store(&r.bestaetigt, start);
    erzeugen(quelle, 0, sizeof(quelle));
    const uint8_t *a, *b;
    size_t al, bl;

    PRUEFE(vermerk_ring_schreiben(&r, quelle, 10));        /* ueber den Ueberlauf hinweg */
    PRUEFE(vermerk_ring_geschrieben(&r) == 4u);            /* start + 10 mod 2^32 */
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 10);
    PRUEFE(vermerk_ring_lesen(&r, 100, &a, &al, &b, &bl) == 10);
    size_t gesamt = al + bl;
    PRUEFE(gesamt == 10);
    uint8_t gelesen[16];
    memcpy(gelesen, a, al);
    if (bl > 0) {
        memcpy(gelesen + al, b, bl);
    }
    PRUEFE(memcmp(gelesen, quelle, 10) == 0);
    PRUEFE(vermerk_ring_bestaetigen(&r, 2));               /* "2" liegt hinter dem Ueberlauf, aber im Bereich */
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 2);
    PRUEFE(!vermerk_ring_bestaetigen(&r, 5));              /* hinter geschrieben */
    PRUEFE(!vermerk_ring_bestaetigen(&r, start));          /* hinter bestaetigt zurueck */
    PRUEFE(vermerk_ring_bestaetigen(&r, 4));
    PRUEFE(vermerk_ring_unbestaetigt(&r) == 0);
    ring_frei(&r);
}

int main(void)
{
    test_leer();
    test_schreiben_lesen_bestaetigen();
    test_umlauf_im_puffer();
    test_voll_und_ueberlauf();
    test_dauerlauf();
    test_zaehlerueberlauf();

    if (fehler > 0) {
        fprintf(stderr, "%d von %d Pruefungen fehlgeschlagen\n", fehler, pruefungen);
        return 1;
    }
    printf("Alle %d Pruefungen bestanden\n", pruefungen);
    return 0;
}
