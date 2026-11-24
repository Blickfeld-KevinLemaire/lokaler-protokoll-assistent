import { afterEach, describe, expect, it, vi } from 'vitest';
import { inZwischenablage } from './zwischenablage';

const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

function zwischenablage(wert: unknown) {
  Object.defineProperty(navigator, 'clipboard', { value: wert, configurable: true });
}

describe('Zwischenablage', () => {
  afterEach(() => {
    if (original) Object.defineProperty(navigator, 'clipboard', original);
    else Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('nimmt navigator.clipboard, wo es das gibt', async () => {
    const schreiben = vi.fn().mockResolvedValue(undefined);
    zwischenablage({ writeText: schreiben });
    await inZwischenablage('Hallo');
    expect(schreiben).toHaveBeenCalledWith('Hallo');
  });

  it('im Browser über http (ohne navigator.clipboard) über ein unsichtbares Textfeld', async () => {
    zwischenablage(undefined);
    const knopf = document.createElement('button');
    document.body.append(knopf);
    knopf.focus();
    let kopiert = '';
    const befehl = vi.fn(() => {
      kopiert = (document.activeElement as HTMLTextAreaElement).value;
      return true;
    });
    Object.defineProperty(document, 'execCommand', { value: befehl, configurable: true });
    await inZwischenablage('Text');
    expect(befehl).toHaveBeenCalledWith('copy');
    expect(kopiert).toBe('Text');
    expect(document.querySelector('textarea')).toBeNull();
    expect(document.activeElement).toBe(knopf);

    // Scheitert auch das (oder lehnt navigator.clipboard ab): ein Fehler, den die Oberfläche meldet.
    zwischenablage({ writeText: vi.fn().mockRejectedValue(new Error('verweigert')) });
    befehl.mockReturnValue(false);
    await expect(inZwischenablage('Text')).rejects.toThrow('Kopieren nicht möglich');
    knopf.remove();
  });
});
