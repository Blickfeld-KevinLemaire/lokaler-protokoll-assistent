import { describe, expect, it } from 'vitest';
import { stromAntwort } from '../../test/hilfen';
import { SseParser, stromLesen, type SseNachricht } from './sse';

function parsen(stuecke: string[]): SseNachricht[] {
  const ergebnis: SseNachricht[] = [];
  const p = new SseParser((n) => ergebnis.push(n));
  for (const s of stuecke) p.hinzufuegen(s);
  p.beenden();
  return ergebnis;
}

describe('SseParser', () => {
  it('liest id, event und data', () => {
    expect(parsen(['id: 7\nevent: auftrag\ndata: {"a":1}\n\n'])).toEqual([
      { id: '7', event: 'auftrag', data: '{"a":1}' }
    ]);
  });

  it('setzt Nachrichten über beliebige Stückgrenzen zusammen', () => {
    const text = 'id: 1\nevent: hinweis\ndata: {"text":"Grüße"}\n\nid: 2\ndata: zwei\n\n';
    for (let schnitt = 1; schnitt < text.length; schnitt++) {
      const n = parsen([text.slice(0, schnitt), text.slice(schnitt)]);
      expect(n).toHaveLength(2);
      expect(n[0]).toEqual({ id: '1', event: 'hinweis', data: '{"text":"Grüße"}' });
      expect(n[1]).toEqual({ id: '2', event: 'message', data: 'zwei' });
    }
  });

  it('übergeht Kommentare (Herzschlag) und leere Blöcke', () => {
    expect(parsen([': verbunden\n\n', ': herzschlag\n\n', 'data: x\n\n'])).toEqual([
      { id: null, event: 'message', data: 'x' }
    ]);
  });

  it('verbindet mehrzeilige data-Felder mit Zeilenumbruch', () => {
    expect(parsen(['data: eins\ndata: zwei\ndata:drei\n\n'])[0]?.data).toBe('eins\nzwei\ndrei');
  });

  it('behält die letzte id für folgende Nachrichten ohne eigene id', () => {
    const n = parsen(['id: 5\ndata: a\n\ndata: b\n\n']);
    expect(n.map((x) => x.id)).toEqual(['5', '5']);
  });

  it('versteht CRLF, auch wenn \\r und \\n in verschiedenen Stücken kommen', () => {
    expect(parsen(['data: a\r', '\n\r', '\n'])).toEqual([{ id: null, event: 'message', data: 'a' }]);
  });

  it('verwirft eine unvollständige letzte Nachricht', () => {
    expect(parsen(['data: halb'])).toEqual([]);
  });

  it('liest einen Strom bis zum Ende und meldet die letzte id', async () => {
    const gesehen: string[] = [];
    const id = await stromLesen(stromAntwort(['id: 3\nda', 'ta: x\n\n']).body!, (n) => gesehen.push(n.data));
    expect(gesehen).toEqual(['x']);
    expect(id).toBe('3');
  });
});
