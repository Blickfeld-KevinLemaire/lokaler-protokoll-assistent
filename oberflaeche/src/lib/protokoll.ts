/**
 * In der gebauten Fassung gibt es keine Entwicklerwerkzeuge. Warnungen, Fehler und unbehandelte Ausnahmen
 * gehen deshalb an das Protokoll des Fensters (Befehl `protokoll_schreiben`) – höchstens 500 je Lauf,
 * damit eine Fehlerschleife die Platte nicht füllt. `console.log` wird bewusst nicht weitergeleitet
 * (kann Inhalte aus Besprechungen enthalten).
 */

export const MAX_EINTRAEGE = 500;
const MAX_LAENGE = 4000;

type Schreiber = (stufe: 'warn' | 'error', text: string) => void;

function alsText(teile: unknown[]): string {
  const text = teile
    .map((t) => {
      if (t instanceof Error) return `${t.name}: ${t.message}${t.stack ? `\n${t.stack}` : ''}`;
      if (typeof t === 'string') return t;
      try {
        return JSON.stringify(t);
      } catch {
        return String(t);
      }
    })
    .join(' ');
  return text.length > MAX_LAENGE ? `${text.slice(0, MAX_LAENGE)} …` : text;
}

/** Richtet die Weiterleitung ein; gibt eine Funktion zum Aufheben zurück (für Tests). */
export function protokollEinrichten(schreiben: Schreiber): () => void {
  let anzahl = 0;
  const senden = (stufe: 'warn' | 'error', teile: unknown[]) => {
    if (anzahl >= MAX_EINTRAEGE) return;
    anzahl++;
    try {
      schreiben(stufe, alsText(teile));
    } catch {
      // Das Protokoll darf nie selbst einen Fehler auslösen.
    }
  };
  const warnVorher = console.warn;
  const errorVorher = console.error;
  console.warn = (...teile: unknown[]) => {
    senden('warn', teile);
    warnVorher.apply(console, teile);
  };
  console.error = (...teile: unknown[]) => {
    senden('error', teile);
    errorVorher.apply(console, teile);
  };
  const beiFehler = (e: ErrorEvent) => senden('error', [e.error ?? e.message]);
  const beiAblehnung = (e: PromiseRejectionEvent) => senden('error', ['Unbehandelt:', e.reason]);
  window.addEventListener('error', beiFehler);
  window.addEventListener('unhandledrejection', beiAblehnung);
  return () => {
    console.warn = warnVorher;
    console.error = errorVorher;
    window.removeEventListener('error', beiFehler);
    window.removeEventListener('unhandledrejection', beiAblehnung);
  };
}
