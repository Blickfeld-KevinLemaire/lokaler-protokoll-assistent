import { afterEach, describe, expect, it, vi } from 'vitest';
import { stromAntwort } from '../../test/hilfen';
import { chatStatusText, fragen } from './chat';
import { zugangSetzen, zugangSperren } from './client';

describe('Frag mein Meeting', () => {
  afterEach(() => {
    zugangSperren();
    vi.unstubAllGlobals();
  });

  it('liest status, token und fertig aus dem Strom', async () => {
    zugangSetzen({ basisUrl: '', schluessel: null });
    const sse = (art: string, daten: unknown) => `event: ${art}\ndata: ${JSON.stringify(daten)}\n\n`;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        stromAntwort([
          sse('status', { text: 'Abschnitt 2 von 5 wird gelesen …' }),
          sse('token', { text: 'Frau ' }),
          sse('token', { text: 'Petrov' }),
          sse('fertig', { antwort: '**Frau Petrov**', quellen: ['Baubesprechung'], verlauf_id: 'v1' })
        ])
      )
    );
    const status: string[] = [];
    const fertig = vi.fn();
    await fragen('Wer?', [], null, {
      status: (s) => status.push(s),
      text: () => undefined,
      fertig,
      fehler: vi.fn()
    });
    expect(status).toEqual(['Unterlagen werden gelesen …']);
    expect(fertig).toHaveBeenCalledWith('**Frau Petrov**', ['Baubesprechung'], 'v1');
  });

  it('gibt Status ohne Zähler weiter', () => {
    expect(chatStatusText('Unterlagen werden vorbereitet: Team (2/4)')).toBe(
      'Unterlagen werden vorbereitet …'
    );
    expect(chatStatusText('Antwort wird erzeugt …')).toBe('Antwort wird erzeugt …');
  });
});
