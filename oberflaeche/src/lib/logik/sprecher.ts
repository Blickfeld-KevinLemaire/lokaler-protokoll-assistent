/** Bekannte Stimmen: Wann ein Namensvorschlag neben einem Sprecher erscheint. */
import type { SprecherVorschlaege, SprecherVorschlag } from '../api/typen';

/** Hat der Sprecher schon einen echten Namen (nicht nur die Kennung `SPEAKER_00`)? */
export function hatNamen(name: string | null | undefined): boolean {
  const n = (name ?? '').trim();
  return !!n && !/^SPEAKER_\d+$/i.test(n);
}

/**
 * Vorschlag für einen Sprecher – nur, solange er noch keinen Namen hat. Unsichere Vorschläge erscheinen
 * mit Fragezeichen („Anna?“), Ähnlichkeitswerte zeigt die Oberfläche nie.
 */
export function vorschlagFuer(
  vorschlaege: SprecherVorschlaege | null | undefined,
  sprecherId: string,
  aktuellerName: string | null | undefined
): SprecherVorschlag | null {
  if (hatNamen(aktuellerName)) return null;
  const v = vorschlaege?.vorschlaege[sprecherId];
  return v && v.name.trim() ? v : null;
}
