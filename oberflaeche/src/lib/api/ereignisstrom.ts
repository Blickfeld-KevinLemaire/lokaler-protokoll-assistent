/**
 * Der Ereignisstrom `/api/ereignisse`: fetch + ReadableStream, Wiederverbinden nach 3 s mit
 * `Last-Event-ID`, Schluss bei 401/403 (nicht endlos wiederholen) und wenn das Startgatter schließt.
 */
import { api, GatterGeschlossen, NichtAngemeldet } from './client';
import { stromLesen, type SseNachricht } from './sse';
import type { Ereignis } from './typen';

export const WIEDERVERBINDEN_MS = 3000;

export type StromZustand = 'verbindet' | 'verbunden' | 'getrennt' | 'beendet';

export interface StromOptionen {
  seit: number;
  beiEreignis: (ereignis: Ereignis) => void;
  beiZustand?: (zustand: StromZustand) => void;
  beiAbmeldung?: () => void;
  /** Im Test ersetzbar. */
  warten?: (ms: number, signal: AbortSignal) => Promise<void>;
}

export interface Abo {
  beenden(): void;
  /** Erfüllt, sobald die Schleife endet (für Tests). */
  ende: Promise<void>;
}

function standardWarten(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((erfuellen) => {
    const zeit = setTimeout(erfuellen, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(zeit);
        erfuellen();
      },
      { once: true }
    );
  });
}

export function nachrichtAuswerten(n: SseNachricht): Ereignis | null {
  try {
    const roh = JSON.parse(n.data) as Partial<Ereignis>;
    if (!roh || typeof roh !== 'object') return null;
    return {
      nummer: typeof roh.nummer === 'number' ? roh.nummer : Number(n.id ?? 0),
      art: roh.art ?? n.event,
      daten: roh.daten ?? {},
      zeit: typeof roh.zeit === 'number' ? roh.zeit : 0
    };
  } catch {
    return null;
  }
}

export function ereignisseAbonnieren(optionen: StromOptionen): Abo {
  const steuerung = new AbortController();
  const warten = optionen.warten ?? standardWarten;
  const melden = (z: StromZustand) => optionen.beiZustand?.(z);

  async function schleife(): Promise<void> {
    let letzteId: string | null = null;
    while (!steuerung.signal.aborted) {
      melden('verbindet');
      try {
        const antwort = await api.ereignisse(letzteId ? null : optionen.seit, letzteId, steuerung.signal);
        if (!antwort.body) throw new Error('Leerer Strom');
        melden('verbunden');
        await stromLesen(
          antwort.body,
          (n) => {
            if (n.id) letzteId = n.id;
            const ereignis = nachrichtAuswerten(n);
            if (ereignis && !steuerung.signal.aborted) optionen.beiEreignis(ereignis);
          },
          steuerung.signal
        );
      } catch (fehler) {
        if (fehler instanceof NichtAngemeldet) {
          melden('beendet');
          optionen.beiAbmeldung?.();
          return;
        }
        if (fehler instanceof GatterGeschlossen) {
          // Das Startgatter hat zugemacht (Neustart des Dienstes): Wer es wieder öffnet, abonniert neu.
          melden('beendet');
          return;
        }
      }
      if (steuerung.signal.aborted) break;
      melden('getrennt');
      await warten(WIEDERVERBINDEN_MS, steuerung.signal);
    }
    melden('beendet');
  }

  const ende = schleife();
  return {
    beenden: () => steuerung.abort(),
    ende
  };
}
