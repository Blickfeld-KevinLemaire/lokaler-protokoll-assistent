/**
 * Fehler für den Dialog aufbereiten. 422 aus /api/auftraege trägt {titel, text, code}; je Code gibt es
 * einen Knopf zum passenden Abschnitt der Einstellungen. Wo der Dienst Fachbegriffe benutzt, stehen hier
 * schlichte Sätze (siehe Bericht: Wunsch an den Dienst, die Texte selbst so zu formulieren).
 */
import { ApiFehler, Verbindungsfehler } from '../api/client';

export type Abschnitt = 'transkription' | 'zusammenfassung' | 'chat' | 'darstellung';

export interface DialogFehler {
  titel: string;
  text: string;
  abschnitt: Abschnitt | null;
  details?: string;
}

const UMSCHREIBUNG: Record<string, { titel: string; text: string }> = {
  schluessel: {
    titel: 'Zugangsschlüssel fehlt',
    text: 'Für den Online-Dienst ist noch kein Zugangsschlüssel hinterlegt.'
  },
  einstellungen: {
    titel: 'Online-Dienst nicht eingerichtet',
    text: 'Bitte zuerst einen Online-Dienst auswählen.'
  },
  lokale_einrichtung: {
    titel: 'Noch nicht eingerichtet',
    text: 'Die Spracherkennung auf diesem Computer ist noch nicht bereit. Alternativ geht es über einen Online-Dienst.'
  },
  modell_fehlt: {
    titel: 'Sprachmodell fehlt',
    text: 'Das gewählte Sprachmodell ist noch nicht auf diesem Computer. Es lässt sich in den Einstellungen herunterladen.'
  }
};

function abschnittFuer(code: string, text: string): Abschnitt | null {
  if (code === 'modell_fehlt') return 'zusammenfassung';
  if (code === 'lokale_einrichtung') return 'transkription';
  if (code === 'schluessel' || code === 'einstellungen') {
    return /nachbearbeitung|protokoll|zusammenfassung/i.test(text) ? 'zusammenfassung' : 'transkription';
  }
  return null;
}

export function fehlerFuerDialog(fehler: unknown, titel = 'Das hat nicht geklappt'): DialogFehler {
  if (fehler instanceof ApiFehler && fehler.fehler) {
    const { code, text } = fehler.fehler;
    const ersatz = UMSCHREIBUNG[code];
    return {
      titel: ersatz?.titel ?? fehler.fehler.titel,
      text: ersatz?.text ?? text,
      abschnitt: abschnittFuer(code, text)
    };
  }
  if (fehler instanceof Verbindungsfehler) {
    return { titel: 'Keine Verbindung', text: 'Der Dienst antwortet gerade nicht.', abschnitt: null };
  }
  if (fehler instanceof Error) return { titel, text: fehler.message, abschnitt: null };
  return { titel, text: String(fehler), abschnitt: null };
}
