import { afterEach, describe, expect, it, vi } from 'vitest';
import { INFO } from '../../test/hilfen';
import { api } from '../api/client';
import type { EinrichtungStand, Info } from '../api/typen';
import { einrichtung } from './einrichtung.svelte';
import { zustand } from './zustand.svelte';

function stand(teil: Partial<EinrichtungStand>): EinrichtungStand {
  return {
    einrichtung_abgeschlossen: false,
    naechster_schritt: 'willkommen',
    arbeitsweise: { transkription: 'lokal', nachbearbeitung: 'lokal', chatbot: 'lokal' },
    online_ohne_anbieter: [],
    neustart_noetig: false,
    ...teil
  } as EinrichtungStand;
}

const OFFEN = { ...INFO, einrichtung_abgeschlossen: false } as Info;

describe('Zustand: Uhr des Dienstes', () => {
  it('übernimmt den Versatz aus /api/zustand – nicht aus nachgelieferten Ereignissen', () => {
    const lokal = 1_800_000_000_000;
    zustand.uebernehmen(
      { letzte_nummer: 1, jetzt: lokal / 1000 + 90, auftraege: [], empfang: null, freigaben: [] },
      lokal
    );
    expect(zustand.uhrVersatz).toBeCloseTo(90);
    expect(zustand.jetztDienst(lokal)).toBeCloseTo(lokal / 1000 + 90);
    // Ein altes Ereignis (z. B. nach dem Wiederverbinden) verstellt die Uhr nicht.
    zustand.ereignis({ nummer: 2, art: 'dateien', daten: {}, zeit: 1000 });
    expect(zustand.uhrVersatz).toBeCloseTo(90);
  });

  it('nimmt den Stand der Aufnahme aus dem Ereignis „aufnahme“', () => {
    zustand.ereignis({
      nummer: 3,
      art: 'aufnahme',
      daten: { laeuft: true, pausiert: false, dauer: 12.4, pegel: 0.3, geraet: 'Mikrofon' },
      zeit: 0
    });
    expect(zustand.aufnahme?.laeuft).toBe(true);
    expect(zustand.aufnahme?.dauer).toBeCloseTo(12.4);
  });

  it('reicht code und bereich der Hinweise weiter', () => {
    zustand.ereignis({
      nummer: 4,
      art: 'hinweis',
      daten: {
        text: 'Das Sprachmodell für Zusammenfassungen fehlt noch.',
        stufe: 'fehler',
        quelle: 'ollama',
        code: 'modell_fehlt'
      },
      zeit: 0
    });
    expect(zustand.hinweise.at(-1)).toMatchObject({
      text: 'Sprachmodell fehlt',
      abschnitt: 'zusammenfassung'
    });
  });
});

describe('Ersteinrichtung: Ablauf mit Neustart', () => {
  afterEach(() => {
    einrichtung.aktiv = false;
    einrichtung.neustart = 'nein';
    einrichtung.nachNeustart = false;
  });

  it('erscheint nur in der Windows-Anwendung und nur, solange sie offen ist', async () => {
    const abfrage = vi.spyOn(api, 'einrichtungStand').mockResolvedValue(stand({}));
    await einrichtung.pruefen({ ...OFFEN, rolle: 'server' } as Info);
    expect(einrichtung.aktiv).toBe(false);
    expect(abfrage).not.toHaveBeenCalled();
    const OHNE_RECHENUMGEBUNG = { ...INFO.faehigkeiten, lokale_transkription: false };
    await einrichtung.pruefen({
      ...OFFEN,
      einrichtung_abgeschlossen: true,
      faehigkeiten: OHNE_RECHENUMGEBUNG
    } as Info);
    expect(einrichtung.aktiv).toBe(false);
    expect(abfrage).not.toHaveBeenCalled();
    abfrage.mockResolvedValueOnce(stand({ einrichtung_abgeschlossen: true, naechster_schritt: 'fertig' }));
    await einrichtung.pruefen({ ...OFFEN, einrichtung_abgeschlossen: true } as Info);
    expect(einrichtung.aktiv).toBe(false);
    await einrichtung.pruefen(OFFEN);
    expect(einrichtung.aktiv).toBe(true);
    expect(einrichtung.schritt).toBe('willkommen');
  });

  it('startet neu und macht danach bei der Spracherkennung weiter', async () => {
    vi.spyOn(api, 'neustart').mockResolvedValue({ neustart: true });
    einrichtung.aktiv = true;
    einrichtung.schritt = 'fertig';
    await einrichtung.neuStarten();
    expect(einrichtung.neustart).toBe('laeuft');
    // Das Startgatter öffnet wieder (Ereignis „bereit“ des Fensters): Der Dienst sagt, wo es weitergeht.
    vi.spyOn(api, 'einrichtungStand').mockResolvedValue(stand({ naechster_schritt: 'mitschrift' }));
    await einrichtung.pruefen(OFFEN);
    expect(einrichtung.neustart).toBe('nein');
    expect(einrichtung.nachNeustart).toBe(true);
    expect(einrichtung.schritt).toBe('mitschrift');
    expect(einrichtung.folge).toEqual(['mitschrift', 'fertig']);
  });

  it('macht mit der Spracherkennung weiter, wenn die App statt „Jetzt neu starten“ geschlossen wurde', async () => {
    // Einrichtung aus den Einstellungen erneut geöffnet (also schon abgeschlossen), lokal mit Zustimmung – dann das
    // Fenster geschlossen. Der nächste Start richtet die Rechenumgebung ein; die Spracherkennung fehlt noch.
    vi.spyOn(api, 'einrichtungStand').mockResolvedValue(
      stand({ einrichtung_abgeschlossen: true, naechster_schritt: 'mitschrift' })
    );
    await einrichtung.pruefen({ ...OFFEN, einrichtung_abgeschlossen: true } as Info);
    expect(einrichtung.aktiv).toBe(true);
    expect(einrichtung.schritt).toBe('mitschrift');
    expect(einrichtung.folge).toEqual(['mitschrift', 'fertig']);
  });

  it('nimmt beim erneuten Versuch einen neu eingegebenen Zugangsschlüssel mit', async () => {
    // Die Sprechererkennung scheiterte (z. B. falscher Schlüssel): Der neue Schlüssel geht mit und bleibt nicht stehen.
    const laden = vi.spyOn(api, 'einrichtungModelle').mockResolvedValue({ id: 'neu' } as never);
    einrichtung.nachNeustart = true;
    einrichtung.stand = stand({});
    einrichtung.zustimmung = { pyannote: true };
    einrichtung.hfSchluessel = ' hf_neu ';
    await einrichtung.wiederholen('einrichtung_modelle');
    expect(laden).toHaveBeenCalledWith(
      expect.objectContaining({ sprechertrennung: true, hf_token: 'hf_neu' })
    );
    expect(einrichtung.hfSchluessel).toBe('');
    einrichtung.zustimmung = {};
  });

  it('schließt nach dem Neustart, wenn nichts mehr offen ist', async () => {
    vi.spyOn(api, 'neustart').mockResolvedValue({ neustart: true });
    einrichtung.aktiv = true;
    await einrichtung.neuStarten();
    vi.spyOn(api, 'einrichtungStand').mockResolvedValue(
      stand({ einrichtung_abgeschlossen: true, naechster_schritt: 'fertig' })
    );
    await einrichtung.pruefen({ ...OFFEN, einrichtung_abgeschlossen: true } as Info);
    expect(einrichtung.aktiv).toBe(false);
  });

  it('meldet, wenn der Neustart nicht geht, und bleibt stehen', async () => {
    vi.spyOn(api, 'neustart').mockRejectedValue(new Error('geht nicht'));
    einrichtung.aktiv = true;
    await einrichtung.neuStarten();
    expect(einrichtung.neustart).toBe('fehler');
    expect(einrichtung.aktiv).toBe(true);
  });

  it('„Später“ schließt die Einrichtung und meldet es dem Dienst', async () => {
    const spaeter = vi.spyOn(api, 'einrichtungSpaeter').mockResolvedValue(stand({}));
    einrichtung.aktiv = true;
    await einrichtung.spaeter();
    expect(einrichtung.aktiv).toBe(false);
    expect(spaeter).toHaveBeenCalledWith(false);
    // In dieser Sitzung kommt sie nicht wieder (erst beim nächsten Start).
    const abfrage = vi.spyOn(api, 'einrichtungStand').mockResolvedValue(stand({}));
    await einrichtung.pruefen(OFFEN);
    expect(abfrage).not.toHaveBeenCalled();
    sessionStorage.clear();
  });
});
