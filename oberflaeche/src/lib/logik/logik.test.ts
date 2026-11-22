import { afterEach, describe, expect, it, vi } from 'vitest';
import { jsonAntwort } from '../../test/hilfen';
import { api, ApiFehler, zugangSetzen, zugangSperren } from '../api/client';
import type { Auftrag } from '../api/typen';
import { fehlerFuerDialog } from './fehler';
import { empfangsFehlerText, hinweisKurz, HINWEIS_CODES } from './hinweise';
import { restzeitText, RestzeitSchaetzer, rohRestzeit } from './restzeit';
import { GERAETE_ZUSTAENDE, STUFEN, stufenText, UNBEKANNT } from './stufen';
import {
  auftragTitel,
  herkunftAnzeigen,
  lageErmitteln,
  platzInReihe,
  startHinweis,
  startHinweisAusPlatz,
  startMeldung,
  wartendeSortieren
} from './warteschlange';

function auftrag(teil: Partial<Auftrag>): Auftrag {
  return {
    id: 'x',
    art: 'transkription',
    titel: 'aufnahme.m4a',
    herkunft: 'oberflaeche',
    vorrang: 0,
    status: 'wartet',
    erstellt: 0,
    stufe: '',
    stufe_text: '',
    vorschau: '',
    meldungen: [],
    angaben: {},
    fremd: false,
    ...teil
  } as Auftrag;
}

const FACHWORT =
  /chunk|abschnitt|diari|whisper|ollama|\bapi\b|endpunkt|token|embedding|cuda|vram|json|\bsse\b|pipeline|modell-id/i;

describe('Warteschlange', () => {
  const liste = [
    auftrag({ id: 'alt', erstellt: 1 }),
    auftrag({ id: 'geraet', erstellt: 3, vorrang: 10, herkunft: 'geraet:Raum-3' }),
    auftrag({ id: 'neu', erstellt: 2 }),
    auftrag({ id: 'lauf', status: 'laeuft', erstellt: 0 }),
    auftrag({ id: 'fertig', status: 'fertig', beendet: 50 }),
    auftrag({ id: 'fehler', status: 'fehler', beendet: 60 })
  ];

  it('sortiert wie der Dienst: höherer Vorrang zuerst, dann der ältere', () => {
    expect(wartendeSortieren(liste).map((a) => a.id)).toEqual(['geraet', 'alt', 'neu']);
  });

  it('leitet Laufendes, Wartendes und zuletzt Erledigtes ab', () => {
    const lage = lageErmitteln(liste);
    expect(lage.laufend?.id).toBe('lauf');
    expect(lage.wartend).toHaveLength(3);
    expect(lage.zuletztErledigt?.id).toBe('fehler');
  });

  it('zählt den Platz einschließlich des laufenden Auftrags', () => {
    expect(platzInReihe(liste, 'lauf')).toBe(1);
    expect(platzInReihe(liste, 'geraet')).toBe(2);
    expect(platzInReihe(liste, 'neu')).toBe(4);
    expect(platzInReihe(liste, 'fertig')).toBeNull();
    expect(startHinweis(liste, 'alt')).toBe('Startet nach der laufenden Verarbeitung (Platz 3)');
    expect(startHinweis([auftrag({ id: 'a' })], 'a')).toBeNull();
  });

  it('nutzt „platz“ aus der Startantwort (0 = sofort)', () => {
    expect(startHinweisAusPlatz(0)).toBeNull();
    expect(startHinweisAusPlatz(1)).toBe('Startet nach der laufenden Verarbeitung (Platz 2)');
    expect(startMeldung(auftrag({ id: 'n', platz: 2 }), [])).toBe(
      'Startet nach der laufenden Verarbeitung (Platz 3)'
    );
  });

  it('zeigt fremde Aufträge neutral und nie als „zuletzt erledigt“', () => {
    const fremd = auftrag({
      id: 'f',
      fremd: true,
      titel: 'geheim.mp3',
      herkunft: 'andere',
      status: 'fertig',
      beendet: 99
    });
    expect(auftragTitel(fremd)).toBe('Andere Verarbeitung');
    expect(herkunftAnzeigen('andere').text).toBe('Andere');
    expect(lageErmitteln([fremd]).zuletztErledigt).toBeNull();
  });

  it('zeigt die Herkunft und kurze Titel', () => {
    expect(herkunftAnzeigen('geraet:Raum-3')).toEqual({ art: 'geraet', text: 'Raum-3' });
    expect(herkunftAnzeigen('oberflaeche').art).toBe('pc');
    expect(herkunftAnzeigen('eingang:x').art).toBe('ordner');
    expect(auftragTitel(auftrag({ art: 'einrichtung_ollama', titel: 'Ollama einrichten' }))).toBe(
      'KI-Umgebung einrichten'
    );
    expect(auftragTitel(auftrag({ art: 'einrichtung_ollama' }))).not.toMatch(FACHWORT);
    expect(
      auftragTitel(auftrag({ art: 'auswertung', titel: 'Team_lokal_transkript_20261121_101500.json' }))
    ).toBe('Zusammenfassung: Team');
    expect(auftragTitel(auftrag({ art: 'modell_laden', titel: 'qwen3.5:4b' }))).toBe(
      'Sprachmodell herunterladen'
    );
  });
});

describe('Restzeit', () => {
  it('zeigt erst ab 5 % oder nach 20 s etwas', () => {
    expect(rohRestzeit(0.02, 10)).toBeNull();
    expect(rohRestzeit(0.02, 25)).toBeCloseTo(1225);
    expect(rohRestzeit(0.25, 60)).toBeCloseTo(180);
    expect(rohRestzeit(0, 100)).toBeNull();
  });

  it('glättet die Schätzung und zählt zwischen den Meldungen herunter', () => {
    const s = new RestzeitSchaetzer();
    expect(s.schaetzen(0.5, 0, 100)).toBeCloseTo(100);
    // gleicher Fortschritt, 10 s später: zählt nur herunter
    expect(s.schaetzen(0.5, 0, 110)).toBeCloseTo(90);
    // Sprung nach oben wird gedämpft
    const naechste = s.schaetzen(0.55, 0, 120)!;
    expect(naechste).toBeGreaterThan(80);
    expect(naechste).toBeLessThan(100);
    expect(s.schaetzen(null, 0, 120)).toBeNull();
  });

  it('formuliert freundlich', () => {
    expect(restzeitText(null)).toBe('');
    expect(restzeitText(20)).toBe('gleich fertig');
    expect(restzeitText(250)).toBe('noch etwa 4 Min.');
    expect(restzeitText(2.2 * 3600)).toBe('noch etwa 2 Std.');
    expect(restzeitText(2.6 * 3600)).toBe('noch etwa 2,5 Std.');
  });
});

describe('Stufen', () => {
  it('übersetzt jede bekannte Stufe in einen Satz ohne Fachbegriffe', () => {
    for (const [schluessel, satz] of Object.entries(STUFEN)) {
      expect(stufenText(schluessel, 'laeuft')).toBe(satz);
      expect(satz).not.toMatch(FACHWORT);
    }
    for (const satz of Object.values(GERAETE_ZUSTAENDE)) expect(satz).not.toMatch(FACHWORT);
    expect(stufenText('transkription')).toBe('Wird in Text umgewandelt');
    expect(stufenText('diarisierung')).toBe('Sprecher werden erkannt');
    expect(stufenText('protokoll_auswertung')).toBe('Zusammenfassung wird geschrieben');
  });

  it('nimmt für Unbekanntes einen allgemeinen Satz', () => {
    expect(stufenText('chunk_neu')).toBe(UNBEKANNT);
    expect(stufenText('', 'wartet')).toBe('Wartet');
  });
});

describe('Fehler und Hinweise', () => {
  afterEach(() => {
    zugangSperren();
    vi.unstubAllGlobals();
  });

  it('übernimmt Titel und Text des Dienstes und wählt den Abschnitt über „bereich“', async () => {
    zugangSetzen({ basisUrl: '', schluessel: null });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonAntwort(
          {
            titel: 'Sprachmodell fehlt',
            text: 'Das Sprachmodell für Zusammenfassungen ist noch nicht geladen.',
            code: 'modell_fehlt',
            bereich: 'zusammenfassung'
          },
          422
        )
      )
    );
    const fehler = await api.transkriptionStarten({ quelle: 'a.wav' } as never).catch((e) => e);
    expect(fehler).toBeInstanceOf(ApiFehler);
    expect(fehler.fehler.code).toBe('modell_fehlt');
    const d = fehlerFuerDialog(fehler);
    expect(d.abschnitt).toBe('zusammenfassung');
    expect(d.titel).toBe('Sprachmodell fehlt');
    expect(d.text).toBe('Das Sprachmodell für Zusammenfassungen ist noch nicht geladen.');
    expect(`${d.titel} ${d.text}`).not.toMatch(FACHWORT);
  });

  it('nimmt „bereich“ statt den Text zu raten', () => {
    const f = (code: string, bereich: string, text = 'unter „Zusammenfassung“') =>
      fehlerFuerDialog(new ApiFehler(422, text, { titel: 'T', text, code, bereich }));
    // Der Text sagt „Zusammenfassung“, der Bereich „transkription“: der Bereich gilt.
    expect(f('schluessel', 'transkription').abschnitt).toBe('transkription');
    expect(f('schluessel', 'zusammenfassung', 'x').abschnitt).toBe('zusammenfassung');
    expect(f('einstellungen', 'zusammenfassung').abschnitt).toBe('zusammenfassung');
    // Ohne Bereich nur, wo der Code eindeutig ist.
    expect(f('schluessel', '').abschnitt).toBeNull();
    expect(f('lokale_einrichtung', '').abschnitt).toBe('transkription');
    expect(f('lokale_einrichtung', '').einrichten).toBe(true);
    expect(f('modell_fehlt', '').abschnitt).toBe('zusammenfassung');
    expect(f('eingabe', '', 'Datei ist leer').abschnitt).toBeNull();
    expect(f('belegt', '', 'Gerade belegt').text).toBe('Gerade belegt');
    expect(fehlerFuerDialog(new ApiFehler(404, 'Weg')).text).toBe('Weg');
  });

  it('ordnet Hinweise über „code“ zu, nicht über den Text', () => {
    const h = (code: string | undefined, text = 'irgendein Text', quelle = 'ollama', bereich?: string) =>
      hinweisKurz({ text, stufe: 'fehler', quelle, code, bereich });
    expect(h('modell_fehlt')).toMatchObject({ text: 'Sprachmodell fehlt', abschnitt: 'zusammenfassung' });
    expect(h('ki_nicht_erreichbar').text).toBe('KI für Zusammenfassungen nicht erreichbar');
    expect(h('ki_neu_gestartet').text).toBe('KI wieder bereit');
    expect(h('port_belegt', 'Port 8780 wird schon benutzt.', 'netz')).toMatchObject({
      text: 'Im Netz anbieten gestört',
      abschnitt: 'netz'
    });
    expect(h('schluessel', 'Zugangsschlüssel fehlt: …', 'Raum-3', 'zusammenfassung').abschnitt).toBe(
      'zusammenfassung'
    );
    // Ohne Code entscheidet der Wortlaut nicht über die Zuordnung (früher: „fehlt“ hieß Sprachmodell).
    expect(h(undefined, 'Etwas fehlt noch.', 'ollama').text).toBe('Etwas fehlt noch.');
    expect(h(undefined, 'Ollama antwortet nicht').text).toBe('Es gibt ein Problem');
    expect(h(undefined, 'Ollama antwortet nicht').lang).toBe('');
    for (const code of Object.keys(HINWEIS_CODES)) expect(h(code).text).not.toMatch(FACHWORT);
  });

  it('beschreibt Empfangsfehler über „fehler_code“', () => {
    expect(empfangsFehlerText('port_belegt')).toBe('Empfang: Anschluss belegt');
    expect(empfangsFehlerText(null)).toBe('Empfang gestört');
  });
});

describe('Sprechernamen', () => {
  it('zeigt statt technischer Kennungen „Sprecher n“', async () => {
    const { sprecherName } = await import('./format');
    expect(sprecherName('', 'SPEAKER_03')).toBe('Sprecher 4');
    expect(sprecherName('SPEAKER_00', 'SPEAKER_00')).toBe('Sprecher 1');
    expect(sprecherName('Frau Keller', 'SPEAKER_00')).toBe('Frau Keller');
  });
});
