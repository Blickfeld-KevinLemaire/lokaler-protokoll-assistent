/** Hinweise des Dienstes (Ereignis `hinweis`) kurz und ohne Fachbegriffe – zugeordnet über `code`. */
import type { Hinweis } from '../api/typen';
import { abschnittAusBereich, type Abschnitt } from './fehler';

export interface KurzHinweis {
  quelle: string;
  text: string;
  stufe: 'info' | 'warnung' | 'fehler';
  abschnitt: Abschnitt | null;
  /** Der vollständige Text (für den Tooltip); leer, wenn er Fachbegriffe enthält. */
  lang: string;
}

const FACHWORT = /\b(ollama|whisper|cuda|vram|api|endpunkt|token|chunk|gpu)\b/i;

interface Zuordnung {
  text: string;
  abschnitt: Abschnitt | null;
}

/** Je Code ein kurzer Satz und – wo es hilft – der Abschnitt der Einstellungen. */
export const HINWEIS_CODES: Record<string, Zuordnung> = {
  modell_fehlt: { text: 'Sprachmodell fehlt', abschnitt: 'zusammenfassung' },
  ki_nicht_erreichbar: { text: 'KI für Zusammenfassungen nicht erreichbar', abschnitt: 'zusammenfassung' },
  ki_neu_gestartet: { text: 'KI wieder bereit', abschnitt: null },
  port_belegt: { text: 'Im Netz anbieten gestört', abschnitt: 'netz' },
  schluessel: { text: 'Zugangsschlüssel fehlt', abschnitt: null },
  einstellungen: { text: 'Online-Dienst fehlt', abschnitt: null },
  lokale_einrichtung: { text: 'Noch nicht eingerichtet', abschnitt: 'transkription' },
  aufnahme_fehler: { text: 'Aufnahme wurde beendet', abschnitt: null }
};

function stufeVon(h: Hinweis): KurzHinweis['stufe'] {
  if (h.stufe === 'fehler') return 'fehler';
  if (h.stufe === 'warnung') return 'warnung';
  return 'info';
}

/** Erster Satz, höchstens ~70 Zeichen. */
function kuerzen(text: string): string {
  const satz = text.split(/(?<=[.!?])\s|\s[–-]\s|\n/)[0] ?? text;
  return satz.length > 72 ? `${satz.slice(0, 70).trimEnd()} …` : satz;
}

export function hinweisKurz(h: Hinweis): KurzHinweis {
  const stufe = stufeVon(h);
  const basis = { quelle: h.quelle, stufe, lang: FACHWORT.test(h.text) ? '' : h.text };
  const zuordnung = h.code ? HINWEIS_CODES[h.code] : undefined;
  if (zuordnung) {
    return {
      ...basis,
      text: zuordnung.text,
      abschnitt: abschnittAusBereich(h.bereich) ?? zuordnung.abschnitt
    };
  }
  if (FACHWORT.test(h.text)) {
    const text = stufe === 'info' ? 'Hinweis vom Dienst' : 'Es gibt ein Problem';
    return { ...basis, text, abschnitt: null };
  }
  return { ...basis, text: kuerzen(h.text), abschnitt: abschnittAusBereich(h.bereich) };
}

/** Der Empfang der Aufnahmegeräte meldet einen Fehler: kurzer Satz über `fehler_code`. */
export function empfangsFehlerText(fehlerCode: string | null | undefined): string {
  if (fehlerCode === 'port_belegt') return 'Empfang: Anschluss belegt';
  if (fehlerCode === 'ordner') return 'Empfang: Eingangsordner nicht erreichbar';
  return 'Empfang gestört';
}
