/** Teilen von Besprechungen (Servermodus mit mehreren Nutzern). */
import type { Besprechung } from '../api/typen';

type Teilbar = Pick<Besprechung, 'eigen' | 'besitzer'>;

/**
 * Ergebnis ohne Besitzer: Eingangsordner ohne `PROTOKOLL_EINGANG_NUTZER` oder Gerät ohne Besitzer. Es liegt im
 * allgemeinen Ordner, nur Admins sehen und bearbeiten es.
 */
export function ohneBesitzer(b: Teilbar | null | undefined, mehrbenutzer: boolean): boolean {
  return !!b && mehrbenutzer && b.eigen !== false && !b.besitzer;
}

/** Teilen kann nur der Besitzer – ein Ergebnis ohne Besitzer lässt sich nicht teilen (der Dienst lehnt es ab). */
export function teilenMoeglich(b: Teilbar | null | undefined, mehrbenutzer: boolean): boolean {
  return !!b && mehrbenutzer && b.eigen !== false && !!b.besitzer;
}
