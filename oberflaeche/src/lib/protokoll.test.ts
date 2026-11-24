import { afterEach, describe, expect, it, vi } from 'vitest';
import { MAX_EINTRAEGE, protokollEinrichten } from './protokoll';

describe('Protokoll des Fensters', () => {
  let aufheben: (() => void) | null = null;
  afterEach(() => aufheben?.());

  it('leitet Warnungen und Fehler weiter, höchstens 500 je Lauf, console.log nie', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const schreiben = vi.fn();
    aufheben = protokollEinrichten(schreiben);
    console.warn('achtung', { a: 1 });
    console.error(new Error('kaputt'));
    expect(schreiben).toHaveBeenNthCalledWith(1, 'warn', 'achtung {"a":1}');
    expect(schreiben.mock.calls[1]?.[0]).toBe('error');
    expect(schreiben.mock.calls[1]?.[1]).toContain('Error: kaputt');
    for (let i = 0; i < 600; i++) console.error('viel');
    expect(schreiben).toHaveBeenCalledTimes(MAX_EINTRAEGE);
  });

  it('meldet unbehandelte Fehler', () => {
    const schreiben = vi.fn();
    aufheben = protokollEinrichten(schreiben);
    window.dispatchEvent(new ErrorEvent('error', { message: 'Unerwartet', error: new Error('Unerwartet') }));
    expect(schreiben).toHaveBeenCalledWith('error', expect.stringContaining('Unerwartet'));
  });
});
