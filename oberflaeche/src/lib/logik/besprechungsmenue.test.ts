import { describe, expect, it } from 'vitest';
import type { Besprechung, Segment } from '../api/typen';
import { besprechungsMenue, geloeschtMeldung, loeschFrage, type MenueLage } from './besprechungsmenue';
import { imFenster, naechster, oeffnetMenue, perAnfangsbuchstabe } from './kontextmenue';
import { transkriptAlsText } from './transkript';

function eintrag(teil: Partial<Besprechung> = {}): Besprechung {
  return {
    id: 'sitzung',
    titel: 'Sitzung',
    zeit: '20260101_100000',
    transkript: 'C:/aus/sitzung.json',
    dokument: 'C:/aus/sitzung.docx',
    hat_protokoll: true,
    protokolle: [],
    eigen: true,
    besitzer: null,
    geteilt_mit: [],
    ...teil
  } as Besprechung;
}

const DESKTOP: MenueLage = { ordnerOeffnen: true, mehrbenutzer: false, zusammenfassungLaeuft: false };
const SERVER: MenueLage = { ordnerOeffnen: false, mehrbenutzer: true, zusammenfassungLaeuft: false };

const ids = (b: Besprechung, lage: MenueLage) => besprechungsMenue(b, lage).map((p) => p.id);
const punkt = (b: Besprechung, lage: MenueLage, id: string) =>
  besprechungsMenue(b, lage).find((p) => p.id === id);

describe('Kontextmenü der Transkripte', () => {
  it('Windows-Anwendung: alles außer Teilen, in der festen Reihenfolge', () => {
    expect(ids(eintrag(), DESKTOP)).toEqual([
      'oeffnen',
      'umbenennen',
      'dokument',
      'explorer',
      'zusammenfassung',
      'exportieren',
      'kopieren',
      'loeschen'
    ]);
    expect(punkt(eintrag(), DESKTOP, 'zusammenfassung')?.text).toBe('Zusammenfassung neu erstellen');
    expect(punkt(eintrag({ hat_protokoll: false }), DESKTOP, 'zusammenfassung')?.text).toBe(
      'Zusammenfassung erstellen'
    );
    expect(punkt(eintrag(), DESKTOP, 'loeschen')).toMatchObject({
      kuerzel: 'Entf',
      taste: 'Delete',
      gefahr: true
    });
  });

  it('ohne Word-Dokument ist „Dokument öffnen“ ausgegraut, mit Begründung', () => {
    expect(punkt(eintrag({ dokument: null }), DESKTOP, 'dokument')).toMatchObject({
      deaktiviert: true,
      hinweis: expect.stringContaining('Word-Dokument')
    });
  });

  it('Browser auf dem Server: kein Explorer, kein Dokument öffnen; Teilen nur für den Besitzer', () => {
    expect(ids(eintrag({ besitzer: 'anna' }), SERVER)).toEqual([
      'oeffnen',
      'umbenennen',
      'zusammenfassung',
      'exportieren',
      'kopieren',
      'teilen',
      'loeschen'
    ]);
    // Ohne Besitzer (allgemeiner Ordner) lässt sich nichts teilen.
    expect(ids(eintrag({ besitzer: null }), SERVER)).not.toContain('teilen');
  });

  it('geteilt von jemand anderem: lesen und kopieren; Umbenennen und Löschen ausgegraut', () => {
    const geteilt = eintrag({ eigen: false, besitzer: 'ben' });
    expect(ids(geteilt, SERVER)).toEqual(['oeffnen', 'umbenennen', 'kopieren', 'loeschen']);
    for (const id of ['umbenennen', 'loeschen']) {
      expect(punkt(geteilt, SERVER, id)).toMatchObject({ deaktiviert: true, hinweis: expect.any(String) });
    }
  });

  it('während einer Zusammenfassung kein zweites Erstellen und kein Löschen', () => {
    const lage = { ...DESKTOP, zusammenfassungLaeuft: true };
    expect(punkt(eintrag(), lage, 'zusammenfassung')?.deaktiviert).toBe(true);
    expect(punkt(eintrag(), lage, 'loeschen')).toMatchObject({
      deaktiviert: true,
      hinweis: expect.any(String)
    });
    expect(punkt(eintrag(), lage, 'umbenennen')?.deaktiviert).toBeFalsy();
  });

  it('Rückfrage und Meldung beim Löschen', () => {
    expect(loeschFrage('Jour fixe', false)).toMatchObject({
      titel: '„Jour fixe“ wirklich löschen?',
      text: expect.stringContaining('Papierkorb'),
      verb: 'Löschen'
    });
    expect(loeschFrage('x', true).text).toContain('Server');
    expect(geloeschtMeldung('x', 'windows', true)).toBe('„x“ gelöscht');
    expect(geloeschtMeldung('x', 'ordner', true)).toContain('.papierkorb');
    expect(geloeschtMeldung('x', 'ordner', false)).toBe('„x“ gelöscht');
  });
});

describe('Kontextmenü: Tastatur und Lage', () => {
  it('Pfeiltasten laufen im Kreis', () => {
    expect(naechster(3, -1, 1)).toBe(0);
    expect(naechster(3, 2, 1)).toBe(0);
    expect(naechster(3, 0, -1)).toBe(2);
    expect(naechster(0, 0, 1)).toBe(-1);
  });

  it('ein Buchstabe springt zum nächsten passenden Eintrag', () => {
    const punkte = [
      { id: 'a', text: 'Öffnen' },
      { id: 'b', text: 'Umbenennen' },
      { id: 'c', text: 'Exportieren …' },
      { id: 'd', text: 'Löschen' }
    ];
    expect(perAnfangsbuchstabe(punkte, 0, 'l')).toBe(3);
    expect(perAnfangsbuchstabe(punkte, 3, 'ö')).toBe(0);
    expect(perAnfangsbuchstabe(punkte, 1, 'x')).toBe(1);
  });

  it('bleibt im Fenster und klappt am Rand um', () => {
    expect(imFenster(100, 100, 200, 300, 1000, 800)).toEqual({ links: 100, oben: 100 });
    expect(imFenster(950, 700, 200, 300, 1000, 800)).toEqual({ links: 750, oben: 400 });
    expect(imFenster(5, 5, 200, 300, 1000, 800)).toEqual({ links: 8, oben: 8 });
    // Größer als das Fenster: wenigstens oben links sichtbar.
    expect(imFenster(500, 500, 2000, 300, 1000, 800).links).toBe(8);
  });

  it('Menü-Taste und Umschalt+F10 öffnen es', () => {
    const t = (key: string, shiftKey = false, ctrlKey = false) =>
      oeffnetMenue({ key, shiftKey, ctrlKey, altKey: false, metaKey: false });
    expect(t('ContextMenu')).toBe(true);
    expect(t('F10', true)).toBe(true);
    expect(t('F10')).toBe(false);
    expect(t('F10', true, true)).toBe(false);
  });
});

describe('Transkript kopieren', () => {
  it('je Wortbeitrag eine Zeile mit Zeitmarke und Namen', () => {
    const segmente = [
      { start: 0, ende: 2, sprecher_id: 'SPEAKER_00', sprecher: 'Anna', text: 'Hallo zusammen.' },
      { start: 2, ende: 4, sprecher_id: 'SPEAKER_00', sprecher: 'Anna', text: 'Fangen wir an.' },
      { start: 65, ende: 70, sprecher_id: 'SPEAKER_01', sprecher: 'SPEAKER_01', text: ' Gern. ' },
      { start: 3725, ende: 3730, sprecher_id: null, sprecher: null, text: 'Ohne Namen' },
      { start: 3800, ende: 3801, sprecher_id: 'SPEAKER_00', sprecher: 'Anna', text: '  ' }
    ] as Segment[];
    expect(transkriptAlsText(segmente)).toBe(
      '[0:00] Anna: Hallo zusammen. Fangen wir an.\n[1:05] Sprecher 2: Gern.\n[1:02:05] Ohne Namen\n'
    );
    expect(transkriptAlsText([])).toBe('');
  });
});
