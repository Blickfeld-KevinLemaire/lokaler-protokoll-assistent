import { describe, expect, it } from 'vitest';
import type { SprecherVorschlaege } from '../api/typen';
import { modellEinordnen } from './modelle';
import { fertigText, restzeitText, uhrVersatz, zeitenFuerAuftrag } from './restzeit';
import { hatNamen, vorschlagFuer } from './sprecher';
import { tastenkuerzel } from './tasten';

describe('Restzeit nach der Uhr des Dienstes', () => {
  // Eigene Uhr: 22.11.2026 14:00:00 Ortszeit. Die Uhr des Dienstes geht 10 Minuten vor.
  const lokal = new Date(2026, 10, 22, 14, 0, 0).getTime();
  const versatz = 600;
  const dienstJetzt = lokal / 1000 + versatz;

  it('berechnet den Versatz aus „jetzt“ von /api/zustand', () => {
    expect(uhrVersatz(dienstJetzt, lokal)).toBeCloseTo(600);
    expect(uhrVersatz(undefined, lokal)).toBe(0);
  });

  it('rechnet die vergangene Zeit gegen die Uhr des Dienstes, nicht gegen die eigene', () => {
    // Gestartet laut Dienst vor 120 s, zur Hälfte fertig: noch etwa 2 Minuten.
    const gestartet = dienstJetzt - 120;
    const z = zeitenFuerAuftrag('uhr-1', 0.5, gestartet, dienstJetzt, lokal);
    expect(z.rest).toBeCloseTo(120);
    expect(z.text).toBe('noch etwa 2 Min.');
    expect(z.kurz).toBe('noch 2 Min.');
    // Fertigzeit in der EIGENEN Uhr: 14:02, nicht 14:12.
    expect(z.fertig).toBe('fertig gegen 14:02');
    // Mit der eigenen Uhr gerechnet (Versatz vergessen) wären es 12 Minuten mehr – falsch.
    const falsch = zeitenFuerAuftrag('uhr-2', 0.5, gestartet, lokal / 1000, lokal);
    expect(falsch.rest).toBeNull();
  });

  it('rundet die Fertigzeit, damit sie nicht springt', () => {
    expect(fertigText(30, lokal)).toBe('');
    expect(fertigText(4 * 60 + 20, lokal)).toBe('fertig gegen 14:04');
    // Ab 20 Minuten auf fünf Minuten gerundet.
    expect(fertigText(33 * 60, lokal)).toBe('fertig gegen 14:35');
    expect(fertigText(11 * 3600, lokal)).toBe('fertig morgen gegen 01:00');
  });

  it('formuliert die Restzeit kurz und lang', () => {
    expect(restzeitText(250)).toBe('noch etwa 4 Min.');
    expect(restzeitText(250, true)).toBe('noch 4 Min.');
    expect(restzeitText(30, true)).toBe('gleich fertig');
  });
});

describe('Modelle in einfachen Worten', () => {
  it('stellt „Empfohlen“, „Schneller“, „Genauer“ vor den Namen', () => {
    expect(modellEinordnen('Qwen3.5 4B (empfohlener Standard)')).toEqual({
      titel: 'Empfohlen',
      name: 'Qwen3.5 4B',
      zusatz: ''
    });
    expect(modellEinordnen('LFM2.5 2.6B (schneller, auch für Rechner ohne Grafikkarte)')).toEqual({
      titel: 'Schneller',
      name: 'LFM2.5 2.6B',
      zusatz: 'auch für Rechner ohne Grafikkarte'
    });
    expect(modellEinordnen('Qwen3.5 9B (genauer, braucht mehr Speicher)').titel).toBe('Genauer');
    expect(modellEinordnen('Eigenes Modell')).toEqual({ titel: 'Eigenes Modell', name: '', zusatz: '' });
  });
});

describe('Bekannte Stimmen', () => {
  const v: SprecherVorschlaege = {
    vorschlaege: { SPEAKER_00: { name: 'Anna', sicher: false }, SPEAKER_01: { name: 'Jonas', sicher: true } },
    stimmen_vorhanden: true
  };

  it('schlägt nur für Sprecher ohne Namen etwas vor', () => {
    expect(vorschlagFuer(v, 'SPEAKER_00', '')).toEqual({ name: 'Anna', sicher: false });
    expect(vorschlagFuer(v, 'SPEAKER_00', 'SPEAKER_00')).not.toBeNull();
    expect(vorschlagFuer(v, 'SPEAKER_01', 'Herr Brandt')).toBeNull();
    expect(vorschlagFuer(v, 'SPEAKER_02', '')).toBeNull();
    expect(vorschlagFuer(null, 'SPEAKER_00', '')).toBeNull();
    expect(hatNamen('  ')).toBe(false);
  });
});

describe('Tastenkürzel', () => {
  const taste = (key: string, teil: Partial<KeyboardEvent> = {}, ziel: EventTarget | null = document.body) =>
    tastenkuerzel({
      key,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      shiftKey: false,
      defaultPrevented: false,
      target: ziel,
      ...teil
    });

  it('kennt Strg+N, Strg+, und „/“', () => {
    expect(taste('n', { ctrlKey: true })).toBe('neu');
    expect(taste('N', { ctrlKey: true })).toBe('neu');
    expect(taste(',', { ctrlKey: true })).toBe('einstellungen');
    expect(taste('/')).toBe('suche');
    expect(taste('n')).toBeNull();
    expect(taste('n', { ctrlKey: true, altKey: true })).toBeNull();
  });

  it('lässt „/“ beim Tippen in Feldern in Ruhe', () => {
    const feld = document.createElement('input');
    document.body.append(feld);
    expect(taste('/', {}, feld)).toBeNull();
    expect(taste('n', { ctrlKey: true }, feld)).toBe('neu');
    feld.remove();
  });
});
