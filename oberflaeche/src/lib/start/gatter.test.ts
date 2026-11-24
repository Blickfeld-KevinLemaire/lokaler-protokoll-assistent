import { afterEach, describe, expect, it, vi } from 'vitest';
import { INFO, jsonAntwort } from '../../test/hilfen';
import { api, GatterGeschlossen, zugangBekannt, zugangSperren } from '../api/client';
import type { DienstStatus, Huelle } from '../tauri';
import { Startgatter, type Phase } from './gatter';

function testHuelle(zugaenge: { basis_url: string; schluessel: string }[]) {
  let hoerer: ((s: DienstStatus) => void) | null = null;
  let index = 0;
  const huelle: Huelle = {
    zugangHolen: vi.fn(async () => zugaenge[Math.min(index++, zugaenge.length - 1)]!),
    dienstStatusHoeren: async (r) => {
      hoerer = r;
      return () => (hoerer = null);
    }
  };
  return { huelle, senden: (s: DienstStatus) => hoerer?.(s) };
}

describe('Startgatter', () => {
  afterEach(() => {
    zugangSperren();
    vi.unstubAllGlobals();
  });

  it('fragt nichts, bevor der Zugang feststeht', async () => {
    zugangSperren();
    const abruf = vi.fn();
    vi.stubGlobal('fetch', abruf);
    await expect(api.info()).rejects.toBeInstanceOf(GatterGeschlossen);
    expect(abruf).not.toHaveBeenCalled();
  });

  it('holt nach einem Neustart den Zugang neu – keine Anfrage geht mehr an den alten Port', async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        urls.push(url);
        return jsonAntwort(INFO);
      })
    );
    const { huelle, senden } = testHuelle([
      { basis_url: 'http://127.0.0.1:50001', schluessel: 'eins' },
      { basis_url: 'http://127.0.0.1:50002', schluessel: 'zwei' }
    ]);
    const phasen: Phase[] = [];
    const offen = vi.fn();
    const zu = vi.fn();
    const gatter = new Startgatter({
      huelle,
      beiOffen: offen,
      beiZu: zu,
      beiPhase: (p) => phasen.push(p),
      warten: async () => undefined
    });
    await gatter.starten();
    expect(urls).toEqual(['http://127.0.0.1:50001/api/info']);
    expect(phasen.at(-1)).toBe('bereit');

    senden({ zustand: 'neustart', meldung: '' });
    expect(zugangBekannt()).toBe(false);
    expect(phasen.at(-1)).toBe('neustart');
    expect(zu).toHaveBeenCalled();
    await expect(api.zustand()).rejects.toBeInstanceOf(GatterGeschlossen);

    urls.length = 0;
    senden({ zustand: 'bereit', meldung: '', basis_url: 'http://127.0.0.1:50002' });
    await vi.waitFor(() => expect(phasen.at(-1)).toBe('bereit'));
    expect(huelle.zugangHolen).toHaveBeenCalledTimes(2);
    expect(offen).toHaveBeenCalledTimes(2);

    await api.einstellungen();
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u.startsWith('http://127.0.0.1:50002/'))).toBe(true);
  });

  it('verwirft Antworten, die nach dem Schließen ankommen', async () => {
    // Ein Abruf, der den Abbruch ignoriert und erst später antwortet (wie eine langsame Verbindung).
    const offen: ((r: Response) => void)[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>((r) => offen.push(r)))
    );
    const { huelle } = testHuelle([{ basis_url: 'http://127.0.0.1:50001', schluessel: 'eins' }]);
    const gatter = new Startgatter({
      huelle,
      beiOffen: vi.fn(),
      beiZu: vi.fn(),
      beiPhase: vi.fn(),
      warten: async () => undefined
    });
    void gatter.starten();
    await vi.waitFor(() => expect(offen).toHaveLength(1)); // info() hängt noch
    const laufend = api.einstellungen();
    gatter.dienstStatus({ zustand: 'neustart', meldung: '' });
    for (const r of offen) r(jsonAntwort({}));
    await expect(laufend).rejects.toBeInstanceOf(GatterGeschlossen);
  });

  it('zeigt bei „fehlgeschlagen“ die Fehlerseite', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonAntwort(INFO))
    );
    const { huelle, senden } = testHuelle([{ basis_url: 'http://127.0.0.1:50001', schluessel: 'eins' }]);
    const phasen: [Phase, string][] = [];
    const gatter = new Startgatter({
      huelle,
      beiOffen: vi.fn(),
      beiZu: vi.fn(),
      beiPhase: (p, m) => phasen.push([p, m]),
      warten: async () => undefined
    });
    await gatter.starten();
    senden({ zustand: 'fehlgeschlagen', meldung: 'Port belegt' });
    expect(phasen.at(-1)).toEqual(['fehlgeschlagen', 'Port belegt']);
    expect(zugangBekannt()).toBe(false);
  });

  it('zeigt im Browser bei 401 die Anmeldung und sendet danach die Kennzeichnung mit', async () => {
    const anfragen: { url: string; init: RequestInit }[] = [];
    let angemeldet = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        anfragen.push({ url, init });
        if (url === '/api/anmelden') {
          angemeldet = true;
          return jsonAntwort({ angemeldet_als: 'büro' });
        }
        return angemeldet ? jsonAntwort(INFO) : jsonAntwort({ detail: 'Nicht angemeldet.' }, 401);
      })
    );
    const phasen: Phase[] = [];
    const gatter = new Startgatter({
      huelle: null,
      beiOffen: vi.fn(),
      beiZu: vi.fn(),
      beiPhase: (p) => phasen.push(p),
      warten: async () => undefined
    });
    await gatter.starten();
    expect(phasen.at(-1)).toBe('anmelden');
    await gatter.anmelden({ name: 'anna', passwort: 'x' });
    expect(phasen.at(-1)).toBe('bereit');
    const anmeldung = anfragen.find((a) => a.url === '/api/anmelden')!;
    expect((anmeldung.init.headers as Record<string, string>)['X-Vermerk-Anfrage']).toBe('1');
    expect(anmeldung.init.credentials).toBe('same-origin');
    expect(JSON.parse(String(anmeldung.init.body))).toEqual({ name: 'anna', passwort: 'x' });
  });
});
