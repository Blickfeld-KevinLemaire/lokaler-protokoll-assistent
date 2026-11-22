/** Hinweise des Dienstes (Ereignis `hinweis`) kurz und ohne Fachbegriffe. */
import type { Hinweis } from '../api/typen';
import type { Abschnitt } from './fehler';

export interface KurzHinweis {
  quelle: string;
  text: string;
  stufe: 'info' | 'warnung' | 'fehler';
  abschnitt: Abschnitt | null;
  /** Der vollständige Text (für den Tooltip). */
  lang: string;
}

const FACHWORT = /\b(ollama|whisper|cuda|vram|api|endpunkt|token|chunk)\b/i;

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
  if (h.quelle === 'ollama') {
    if (/fehlt/i.test(h.text)) return { ...basis, text: 'Sprachmodell fehlt', abschnitt: 'zusammenfassung' };
    if (stufe === 'info') return { ...basis, text: 'KI wieder bereit', abschnitt: null };
    return { ...basis, text: 'KI für Zusammenfassungen nicht erreichbar', abschnitt: 'zusammenfassung' };
  }
  if (/port .*(belegt|benutzt)/i.test(h.text)) {
    return { ...basis, text: 'Port belegt', abschnitt: null };
  }
  if (FACHWORT.test(h.text)) {
    const text = stufe === 'info' ? 'Hinweis vom Dienst' : 'Es gibt ein Problem';
    return { ...basis, text, abschnitt: null };
  }
  return { ...basis, text: kuerzen(h.text), abschnitt: null };
}
