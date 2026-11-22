/**
 * Fehler für den Dialog aufbereiten. 422 aus /api/auftraege trägt {titel, text, code, bereich}: Titel und
 * Text formuliert der Dienst schon für Menschen; `bereich` sagt, welcher Abschnitt der Einstellungen hilft.
 */
import { ApiFehler, Verbindungsfehler } from '../api/client';

export type Abschnitt = 'transkription' | 'zusammenfassung' | 'chat' | 'darstellung' | 'netz';

export interface DialogFehler {
  titel: string;
  text: string;
  abschnitt: Abschnitt | null;
  /** Die Einrichtung auf diesem Computer fehlt noch: Die Oberfläche kann die Ersteinrichtung anbieten. */
  einrichten?: boolean;
  details?: string;
}

/** `bereich` des Dienstes → Abschnitt der Einstellungen. */
export function abschnittAusBereich(bereich: string | null | undefined): Abschnitt | null {
  switch (bereich) {
    case 'transkription':
      return 'transkription';
    case 'zusammenfassung':
    case 'nachbearbeitung':
      return 'zusammenfassung';
    case 'chat':
    case 'chatbot':
      return 'chat';
    default:
      return null;
  }
}

/** Codes, die auch ohne `bereich` eindeutig sind. */
const CODE_ABSCHNITT: Record<string, Abschnitt> = {
  modell_fehlt: 'zusammenfassung',
  lokale_einrichtung: 'transkription'
};

export function abschnittFuer(code: string, bereich?: string | null): Abschnitt | null {
  return abschnittAusBereich(bereich) ?? CODE_ABSCHNITT[code] ?? null;
}

export function fehlerFuerDialog(fehler: unknown, titel = 'Das hat nicht geklappt'): DialogFehler {
  if (fehler instanceof ApiFehler && fehler.fehler) {
    const { code, bereich } = fehler.fehler;
    return {
      titel: fehler.fehler.titel || titel,
      text: fehler.fehler.text,
      abschnitt: abschnittFuer(code, bereich),
      einrichten: code === 'lokale_einrichtung'
    };
  }
  if (fehler instanceof Verbindungsfehler) {
    return { titel: 'Keine Verbindung', text: 'Der Dienst antwortet gerade nicht.', abschnitt: null };
  }
  if (fehler instanceof Error) return { titel, text: fehler.message, abschnitt: null };
  return { titel, text: String(fehler), abschnitt: null };
}
