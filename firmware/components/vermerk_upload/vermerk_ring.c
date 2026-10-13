/* Ringpuffer fuer das Senden waehrend der Aufnahme, siehe vermerk_ring.h. Keine ESP-IDF-Includes. */

#include "vermerk_ring.h"

#include <string.h>

void vermerk_ring_init(vermerk_ring_t *ring, uint8_t *puffer, size_t groesse)
{
    ring->puffer = puffer;
    ring->groesse = groesse;
    atomic_store(&ring->geschrieben, 0);
    atomic_store(&ring->bestaetigt, 0);
    atomic_store(&ring->ueberlauf, false);
}

uint32_t vermerk_ring_geschrieben(const vermerk_ring_t *ring)
{
    return (uint32_t)atomic_load_explicit(&((vermerk_ring_t *)ring)->geschrieben, memory_order_acquire);
}

uint32_t vermerk_ring_bestaetigt(const vermerk_ring_t *ring)
{
    return (uint32_t)atomic_load_explicit(&((vermerk_ring_t *)ring)->bestaetigt, memory_order_acquire);
}

bool vermerk_ring_ueberlauf(const vermerk_ring_t *ring)
{
    return atomic_load(&((vermerk_ring_t *)ring)->ueberlauf);
}

size_t vermerk_ring_unbestaetigt(const vermerk_ring_t *ring)
{
    /* Unterschied zweier 32-Bit-Zaehler: stimmt auch, wenn der Zaehler ueberlaeuft */
    return (size_t)(uint32_t)(vermerk_ring_geschrieben(ring) - vermerk_ring_bestaetigt(ring));
}

bool vermerk_ring_schreiben(vermerk_ring_t *ring, const uint8_t *daten, size_t laenge)
{
    if (ring->puffer == NULL || ring->groesse == 0 || (daten == NULL && laenge > 0)) {
        return false;
    }
    if (atomic_load(&ring->ueberlauf)) {
        return false;
    }
    if (laenge == 0) {
        return true;
    }
    uint32_t geschrieben = vermerk_ring_geschrieben(ring);
    /* "bestaetigt" kann sich nur vergroessern: ein veralteter Wert schaetzt den Puffer voller, nie leerer */
    size_t belegt = (size_t)(uint32_t)(geschrieben - vermerk_ring_bestaetigt(ring));
    if (laenge > ring->groesse || belegt > ring->groesse - laenge) {
        atomic_store(&ring->ueberlauf, true);
        return false;
    }

    size_t pos = (size_t)(geschrieben % ring->groesse);
    size_t bis_ende = ring->groesse - pos;
    size_t erst = (laenge < bis_ende) ? laenge : bis_ende;
    memcpy(ring->puffer + pos, daten, erst);
    if (laenge > erst) {
        memcpy(ring->puffer, daten + erst, laenge - erst);
    }
    /* erst jetzt zeigen: Der Verbraucher sieht die Bytes nie vor dem Kopieren */
    atomic_store_explicit(&ring->geschrieben, (uint32_t)(geschrieben + (uint32_t)laenge), memory_order_release);
    return true;
}

size_t vermerk_ring_lesen(const vermerk_ring_t *ring, size_t max, const uint8_t **a, size_t *a_laenge,
                          const uint8_t **b, size_t *b_laenge)
{
    *a = NULL;
    *a_laenge = 0;
    *b = NULL;
    *b_laenge = 0;
    if (ring->puffer == NULL || ring->groesse == 0) {
        return 0;
    }
    uint32_t bestaetigt = vermerk_ring_bestaetigt(ring);
    size_t n = vermerk_ring_unbestaetigt(ring);
    if (n > max) {
        n = max;
    }
    if (n == 0) {
        return 0;
    }
    size_t pos = (size_t)(bestaetigt % ring->groesse);
    size_t bis_ende = ring->groesse - pos;
    *a = ring->puffer + pos;
    *a_laenge = (n < bis_ende) ? n : bis_ende;
    if (n > *a_laenge) {
        *b = ring->puffer;
        *b_laenge = n - *a_laenge;
    }
    return n;
}

bool vermerk_ring_bestaetigen(vermerk_ring_t *ring, uint64_t bis)
{
    uint32_t bestaetigt = vermerk_ring_bestaetigt(ring);
    uint32_t geschrieben = vermerk_ring_geschrieben(ring);
    if (bis > UINT32_MAX) {
        return false;
    }
    uint32_t ziel = (uint32_t)bis;
    /* im Bereich [bestaetigt, geschrieben], gerechnet als Abstand ab "bestaetigt" (ueberlaufsicher) */
    if ((uint32_t)(ziel - bestaetigt) > (uint32_t)(geschrieben - bestaetigt)) {
        return false;
    }
    atomic_store_explicit(&ring->bestaetigt, ziel, memory_order_release);
    return true;
}
