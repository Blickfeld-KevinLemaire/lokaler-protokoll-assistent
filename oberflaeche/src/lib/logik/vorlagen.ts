/**
 * Vorlagen für Zusammenfassungen. „Standard“ ist der allgemeine Auftrag, den man in den Einstellungen unter
 * „Vorlagen“ bearbeitet; der Dienst nimmt ihn, wenn kein eigener Text mitkommt (`systemprompt: null`).
 */
import type { Vorlage } from '../api/typen';

/** Wert der Auswahl für „Standard“. */
export const STANDARD_VORLAGE = '';

/** Vorausgewählt: die in den Einstellungen als Vorgabe markierte Vorlage, sonst „Standard“. */
export function vorlageVorwahl(vorlagen: Vorlage[], aktiv: string | null | undefined): string {
  return vorlagen.find((v) => v.name === aktiv)?.name ?? STANDARD_VORLAGE;
}

/** Was als `systemprompt` an den Dienst geht: der Text der gewählten Vorlage, für „Standard“ `null`. */
export function systempromptFuer(vorlagen: Vorlage[], name: string): string | null {
  if (name === STANDARD_VORLAGE) return null;
  return vorlagen.find((v) => v.name === name)?.text ?? null;
}
