import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { jsonAntwort, stromAntwort } from '../../test/hilfen';
import { zugangSetzen, zugangSperren } from './client';
import { ereignisseAbonnieren, WIEDERVERBINDEN_MS } from './ereignisstrom';
import type { Ereignis } from './typen';

function zeile(nummer: number, art: string, daten: unknown): string {
  return `id: ${nummer}\nevent: ${art}\ndata: ${JSON.stringify({ nummer, art, daten, zeit: 1 })}\n\n`;
}

describe('Ereignisstrom', () => {
  beforeEach(() => zugangSetzen({ basisUrl: 'http://127.0.0.1:5000', schluessel: 'geheim' }));
  afterEach(() => {
    zugangSperren();
    vi.unstubAllGlobals();
  });

  it('verbindet nach dem Abreißen neu – mit Last-Event-ID und Wartezeit', async () => {
    const anfragen: { url: string; kopf: Record<string, string> }[] = [];
    let aufruf = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        anfragen.push({ url, kopf: init.headers as Record<string, string> });
        aufruf++;
        if (aufruf === 1) return stromAntwort([': verbunden\n\n', zeile(11, 'auftrag', { id: 'a' })]);
        return stromAntwort([zeile(12, 'dateien', {})], 200, true);
      })
    );
    const ereignisse: Ereignis[] = [];
    const wartezeiten: number[] = [];
    const abo = ereignisseAbonnieren({
      seit: 10,
      beiEreignis: (e) => {
        ereignisse.push(e);
        if (e.nummer === 12) abo.beenden();
      },
      warten: async (ms) => {
        wartezeiten.push(ms);
      }
    });
    await abo.ende;

    expect(ereignisse.map((e) => e.art)).toEqual(['auftrag', 'dateien']);
    expect(ereignisse[0]?.daten).toEqual({ id: 'a' });
    expect(wartezeiten).toEqual([WIEDERVERBINDEN_MS]);
    expect(anfragen[0]?.url).toBe('http://127.0.0.1:5000/api/ereignisse?seit=10');
    expect(anfragen[0]?.kopf.Authorization).toBe('Bearer geheim');
    expect(anfragen[1]?.url).toBe('http://127.0.0.1:5000/api/ereignisse');
    expect(anfragen[1]?.kopf['Last-Event-ID']).toBe('11');
  });

  it('hört bei 401 auf, statt endlos zu wiederholen', async () => {
    const abruf = vi.fn(async () => jsonAntwort({ detail: 'Nicht angemeldet.' }, 401));
    vi.stubGlobal('fetch', abruf);
    const abmeldung = vi.fn();
    const abo = ereignisseAbonnieren({
      seit: 0,
      beiEreignis: () => undefined,
      beiAbmeldung: abmeldung,
      warten: async () => undefined
    });
    await abo.ende;
    expect(abruf).toHaveBeenCalledTimes(1);
    expect(abmeldung).toHaveBeenCalledOnce();
  });

  it('wiederholt nach Netzfehlern', async () => {
    let aufruf = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        aufruf++;
        if (aufruf < 3) throw new TypeError('Failed to fetch');
        return stromAntwort([zeile(1, 'dateien', {})], 200, true);
      })
    );
    const zustaende: string[] = [];
    const abo = ereignisseAbonnieren({
      seit: 0,
      beiEreignis: () => abo.beenden(),
      beiZustand: (z) => zustaende.push(z),
      warten: async () => undefined
    });
    await abo.ende;
    expect(aufruf).toBe(3);
    expect(zustaende.filter((z) => z === 'getrennt')).toHaveLength(2);
  });

  it('endet, wenn das Startgatter schließt', async () => {
    zugangSperren();
    const abruf = vi.fn();
    vi.stubGlobal('fetch', abruf);
    const abo = ereignisseAbonnieren({
      seit: 0,
      beiEreignis: () => undefined,
      warten: async () => undefined
    });
    await abo.ende;
    expect(abruf).not.toHaveBeenCalled();
  });
});
