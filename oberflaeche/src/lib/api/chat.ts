/**
 * Frag mein Meeting: Antwort als Strom (`status`, `token`, `fertig`, `fehler`). Tokens werden gesammelt
 * und gedrosselt weitergegeben – das Neuzeichnen bei jedem Wort wäre spürbar träge.
 */
import { api } from './client';
import { stromLesen } from './sse';

export interface ChatRueckrufe {
  status: (text: string) => void;
  text: (bisher: string) => void;
  fertig: (antwort: string, quellen: string[], verlaufId: string) => void;
  fehler: (text: string) => void;
}

export const DROSSEL_MS = 80;

/** Status des Dienstes ohne Abschnittszähler. */
export function chatStatusText(text: string): string {
  if (/^Abschnitt \d+/i.test(text)) return 'Unterlagen werden gelesen …';
  if (/^Unterlagen werden vorbereitet/i.test(text)) return 'Unterlagen werden vorbereitet …';
  return text;
}

export async function fragen(
  frage: string,
  besprechungen: string[],
  verlaufId: string | null,
  r: ChatRueckrufe,
  signal?: AbortSignal
): Promise<void> {
  const antwort = await api.chat(frage, besprechungen, verlaufId, signal);
  if (!antwort.body) throw new Error('Keine Antwort');
  let gesammelt = '';
  let zeitgeber: ReturnType<typeof setTimeout> | null = null;
  let abgeschlossen = false;
  const ausgeben = () => {
    zeitgeber = null;
    if (!abgeschlossen) r.text(gesammelt);
  };
  await stromLesen(
    antwort.body,
    (n) => {
      let daten: Record<string, unknown> = {};
      try {
        daten = JSON.parse(n.data) as Record<string, unknown>;
      } catch {
        return;
      }
      switch (n.event) {
        case 'status':
          r.status(chatStatusText(String(daten.text ?? '')));
          break;
        case 'token':
          gesammelt += String(daten.text ?? '');
          zeitgeber ??= setTimeout(ausgeben, DROSSEL_MS);
          break;
        case 'fertig':
          abgeschlossen = true;
          if (zeitgeber) clearTimeout(zeitgeber);
          r.fertig(
            String(daten.antwort ?? gesammelt),
            Array.isArray(daten.quellen) ? daten.quellen.map(String) : [],
            String(daten.verlauf_id ?? '')
          );
          break;
        case 'fehler':
          abgeschlossen = true;
          if (zeitgeber) clearTimeout(zeitgeber);
          r.fehler(String(daten.text ?? 'Unbekannter Fehler'));
          break;
      }
    },
    signal
  );
  if (zeitgeber) clearTimeout(zeitgeber);
}
