import { describe, expect, it } from 'vitest';
import type { Auftrag, EinrichtungKosten, EinrichtungRechner, EinrichtungStand } from '../api/typen';
import {
  alleSetzen,
  alleZugestimmt,
  auftraegePlanen,
  bausteinText,
  bedarfVorhanden,
  dauerText,
  downloadDauerText,
  einrichtungLaeuft,
  gbText,
  hfSchluesselNoetig,
  LEERE_WAHL,
  mitschriftPlanen,
  nachbar,
  neustartMoeglich,
  schrittFolge,
  startSchritt,
  urteil,
  vorauswahl,
  wahlAusStand,
  wahlVollstaendig,
  zustimmungMoeglich,
  zustimmungSetzen,
  type Wahl
} from './einrichtung';

const FACHWORT = /ollama|whisper|pyannote|ffmpeg|pytorch|cuda|\bapi\b|token|endpunkt|gpu|modell-id/i;

function baustein(kennung: string, download_gb: number, vorhanden = false) {
  return { kennung, name: kennung, download_gb, platz_gb: download_gb, hinweis: '', vorhanden };
}

function kosten(bausteine: ReturnType<typeof baustein>[]): EinrichtungKosten {
  const summe = bausteine.filter((b) => !b.vorhanden).reduce((s, b) => s + b.download_gb, 0);
  return {
    arbeitsweise: {},
    bausteine,
    download_gb: summe,
    platz_gb: summe,
    download_minuten_von: 10,
    download_minuten_bis: 13,
    annahme_mbit: 50,
    freier_platz_gb: 200,
    platz_knapp: false,
    zustimmung_noetig: summe > 0,
    neustart_noetig: false,
    ollama_lizenz: null
  };
}

function stand(teil: Partial<EinrichtungStand> = {}, vorhanden: Partial<EinrichtungStand['vorhanden']> = {}) {
  return {
    einrichtung_abgeschlossen: false,
    naechster_schritt: 'willkommen',
    einrichtung_fortsetzen: '',
    lokale_einrichtung_zurueckgestellt: false,
    arbeitsweise: { transkription: 'lokal', nachbearbeitung: 'lokal', chatbot: 'lokal' },
    modelle: {
      whisper: 'turbo',
      sprachmodell: 'qwen3.5:4b',
      chat_sprachmodell: 'qwen3.5:4b',
      einbettung: 'bge-m3'
    },
    vorhanden: {
      ffmpeg: false,
      ollama: false,
      ollama_laeuft: false,
      ollama_modelle: [],
      laufzeit: false,
      laufzeit_aktiv: false,
      sprachmodell: false,
      einbettung: false,
      whisper: false,
      pyannote: false,
      hf_token: false,
      ...vorhanden
    },
    offen: [],
    rechenumgebung_fehlt: false,
    neustart_noetig: false,
    online_ohne_anbieter: [],
    geraete: 0,
    geraete_empfang_aktiv: false,
    auftraege: [],
    ...teil
  } as EinrichtungStand;
}

const ALLES_LOKAL: Wahl = { transkription: 'lokal', nachbearbeitung: 'lokal', chatbot: 'lokal' };

describe('Ersteinrichtung: Reihenfolge der Schritte', () => {
  it('führt von Willkommen bis Fertig und lässt Unnötiges weg', () => {
    expect(schrittFolge({ wahl: ALLES_LOKAL, bedarf: true, nachNeustart: false, raum: true })).toEqual([
      'willkommen',
      'computer',
      'arbeitsweise',
      'bedarf',
      'einrichten',
      'raum',
      'fertig'
    ]);
    // Nichts zu laden: „Was nötig ist“ und „Einrichten“ entfallen; ohne Geräte kein „VERMERK Raum“.
    expect(schrittFolge({ wahl: ALLES_LOKAL, bedarf: false, nachNeustart: false, raum: false })).toEqual([
      'willkommen',
      'computer',
      'arbeitsweise',
      'fertig'
    ]);
    // Online gewählt: der Schritt für Anbieter und Schlüssel kommt nach dem Einrichten.
    const gemischt: Wahl = { transkription: 'lokal', nachbearbeitung: 'api', chatbot: 'lokal' };
    expect(schrittFolge({ wahl: gemischt, bedarf: null, nachNeustart: false, raum: false })).toEqual([
      'willkommen',
      'computer',
      'arbeitsweise',
      'bedarf',
      'einrichten',
      'online',
      'fertig'
    ]);
  });

  it('macht nach dem Neustart nur noch Spracherkennung (ggf. Online-Dienst) und Abschluss', () => {
    expect(schrittFolge({ wahl: LEERE_WAHL, bedarf: null, nachNeustart: true, raum: true })).toEqual([
      'mitschrift',
      'fertig'
    ]);
    expect(
      schrittFolge({
        wahl: LEERE_WAHL,
        bedarf: null,
        nachNeustart: true,
        raum: true,
        onlineOffen: ['chatbot']
      })
    ).toEqual(['mitschrift', 'online', 'fertig']);
  });

  it('beginnt dort, wo der Dienst es sagt', () => {
    expect(startSchritt({ naechster_schritt: 'willkommen' })).toBe('willkommen');
    expect(startSchritt({ naechster_schritt: 'mitschrift' })).toBe('mitschrift');
    // Zugestimmt, aber noch nicht neu gestartet: direkt zu „Fertig“ mit „Jetzt neu starten“.
    expect(startSchritt({ naechster_schritt: 'neustart' })).toBe('fertig');
    expect(startSchritt({ naechster_schritt: 'fertig' })).toBe('willkommen');
  });

  it('findet Vorgänger und Nachfolger', () => {
    const folge = schrittFolge({ wahl: ALLES_LOKAL, bedarf: true, nachNeustart: false, raum: false });
    expect(nachbar(folge, 'computer', 1)).toBe('arbeitsweise');
    expect(nachbar(folge, 'computer', -1)).toBe('willkommen');
    expect(nachbar(folge, 'fertig', 1)).toBeNull();
    expect(nachbar(folge, 'online', 1)).toBe('willkommen');
  });
});

describe('Ersteinrichtung: Ihr Computer und Arbeitsweise', () => {
  const rechner = {
    schritte: [
      {
        kennung: 'mitschrift',
        name: 'Mitschrift',
        stufe: 'gut',
        text: '',
        dauer_von: 3,
        dauer_bis: 5,
        einheit: 'minuten_je_stunde_aufnahme',
        ort: 'Grafikkarte'
      },
      { kennung: 'sprecher', name: 'Sprecher', stufe: 'gut', text: '', einheit: '', ort: '' },
      {
        kennung: 'protokoll',
        name: 'Protokoll',
        stufe: 'maessig',
        text: '',
        dauer_von: 20,
        dauer_bis: 40,
        einheit: 'minuten_je_stunde_aufnahme',
        ort: 'Prozessor'
      },
      { kennung: 'chat', name: 'Chat', stufe: 'nicht', text: '', einheit: '', ort: '' }
    ]
  } as unknown as EinrichtungRechner;

  it('sagt in einfachen Worten, wie gut es läuft', () => {
    expect(urteil('gut').text).toBe('Läuft gut auf diesem Computer');
    expect(urteil('maessig').text).toBe('Geht, dauert etwas');
    expect(urteil('nicht').text).toBe('Besser online');
    expect(urteil(undefined).ton).toBe('online');
  });

  it('nennt die Dauer in Worten', () => {
    expect(dauerText({ dauer_von: 3, dauer_bis: 5, einheit: 'minuten_je_stunde_aufnahme' })).toBe(
      'ca. 3–5 Minuten je Stunde Aufnahme'
    );
    expect(dauerText({ dauer_von: 5, dauer_bis: 5.2, einheit: 'minuten_je_stunde_aufnahme' })).toBe(
      'ca. 5 Minuten je Stunde Aufnahme'
    );
    expect(dauerText({ dauer_von: 60, dauer_bis: 120, einheit: 'minuten_je_stunde_aufnahme' })).toBe(
      'ca. 1–2 Stunden je Stunde Aufnahme'
    );
    expect(dauerText({ dauer_von: 5, dauer_bis: 10, einheit: 'sekunden_je_frage' })).toBe(
      'ca. 5–10 Sekunden je Frage'
    );
    expect(dauerText({ dauer_von: 60, dauer_bis: 180, einheit: 'sekunden_je_frage' })).toBe(
      'ca. 1–3 Minuten je Frage'
    );
    expect(dauerText({ dauer_von: null, einheit: '' })).toBe('');
  });

  it('wählt vor, was hier läuft – einen Online-Dienst nie von selbst', () => {
    const wahl = vorauswahl(rechner);
    expect(wahl).toEqual({ transkription: 'lokal', nachbearbeitung: 'lokal', chatbot: null });
    expect(wahlVollstaendig(wahl)).toBe(false);
    expect(wahlVollstaendig(ALLES_LOKAL)).toBe(true);
    expect(vorauswahl(null)).toEqual(LEERE_WAHL);
  });

  it('übernimmt beim erneuten Öffnen die gespeicherte Arbeitsweise', () => {
    expect(
      wahlAusStand(stand({ arbeitsweise: { transkription: 'api', nachbearbeitung: 'lokal', chatbot: 'x' } }))
    ).toEqual({
      transkription: 'api',
      nachbearbeitung: 'lokal',
      chatbot: null
    });
  });
});

describe('Ersteinrichtung: Zustimmung je Download', () => {
  const k = kosten([
    baustein('ffmpeg', 0.1),
    baustein('ollama', 1.8),
    baustein('sprachmodell', 3.3),
    baustein('einbettung', 1.2),
    baustein('laufzeit', 3.5),
    baustein('whisper', 1.6),
    baustein('pyannote', 0.1),
    baustein('schon_da', 2, true)
  ]);

  it('lädt ohne Haken nichts', () => {
    const plan = auftraegePlanen({ kosten: k, zustimmung: {}, stand: stand(), wahl: ALLES_LOKAL });
    expect(plan).toEqual({ ffmpeg: false, ollama: false, modelle: null, zustimmungRechenumgebung: false });
  });

  it('lässt Sprachmodelle erst zu, wenn der KI-Umgebung zugestimmt ist', () => {
    expect(zustimmungMoeglich('sprachmodell', {}, k)).toBe(false);
    expect(zustimmungMoeglich('sprachmodell', { ollama: true }, k)).toBe(true);
    expect(zustimmungMoeglich('whisper', {}, k)).toBe(false);
    expect(zustimmungMoeglich('whisper', { laufzeit: true }, k)).toBe(true);
    expect(zustimmungMoeglich('ffmpeg', {}, k)).toBe(true);
    // Ist die Grundlage schon da, hängt nichts mehr daran.
    const ohneOllama = kosten([baustein('ollama', 1.8, true), baustein('sprachmodell', 3.3)]);
    expect(zustimmungMoeglich('sprachmodell', {}, ohneOllama)).toBe(true);
  });

  it('nimmt mit der Grundlage auch die abhängigen Haken weg', () => {
    let z = zustimmungSetzen({}, 'ollama', true, k);
    z = zustimmungSetzen(z, 'sprachmodell', true, k);
    z = zustimmungSetzen(z, 'einbettung', true, k);
    expect(z).toMatchObject({ ollama: true, sprachmodell: true, einbettung: true });
    z = zustimmungSetzen(z, 'ollama', false, k);
    expect(z).toMatchObject({ ollama: false, sprachmodell: false, einbettung: false });
  });

  it('kann allem zustimmen und erkennt das', () => {
    const z = alleSetzen(true, k);
    expect(Object.keys(z).sort()).toEqual(
      ['einbettung', 'ffmpeg', 'laufzeit', 'ollama', 'pyannote', 'sprachmodell', 'whisper'].sort()
    );
    expect(alleZugestimmt(z, k)).toBe(true);
    expect(alleZugestimmt({ ...z, ffmpeg: false }, k)).toBe(false);
    expect(alleZugestimmt({}, kosten([]))).toBe(false);
  });

  it('macht aus der Zustimmung die Aufträge – Spracherkennung erst nach dem Neustart', () => {
    const z = alleSetzen(true, k);
    const plan = auftraegePlanen({ kosten: k, zustimmung: z, stand: stand(), wahl: ALLES_LOKAL });
    expect(plan.ffmpeg).toBe(true);
    expect(plan.ollama).toBe(true);
    expect(plan.zustimmungRechenumgebung).toBe(true);
    expect(plan.modelle).toMatchObject({
      zustimmung: true,
      sprachmodelle: ['qwen3.5:4b', 'bge-m3'],
      whisper: false,
      sprechertrennung: false
    });
  });

  it('lädt Spracherkennung gleich mit, wenn die Rechenumgebung schon läuft', () => {
    const z = alleSetzen(true, k);
    const s = stand({}, { laufzeit: true, laufzeit_aktiv: true, hf_token: true });
    const plan = auftraegePlanen({ kosten: k, zustimmung: z, stand: s, wahl: ALLES_LOKAL });
    expect(plan.modelle).toMatchObject({ whisper: true, sprechertrennung: true, hf_token: null });
  });

  it('lässt schon vorhandene Modelle weg und startet eine installierte KI-Umgebung nur', () => {
    const nurModelle = kosten([baustein('ollama', 1.8, true), baustein('sprachmodell', 3.3)]);
    const s = stand({}, { ollama: true, ollama_laeuft: false, ollama_modelle: ['bge-m3:latest'] });
    const plan = auftraegePlanen({
      kosten: nurModelle,
      zustimmung: { sprachmodell: true },
      stand: s,
      wahl: { transkription: 'api', nachbearbeitung: 'lokal', chatbot: 'api' }
    });
    expect(plan.ollama).toBe(true);
    expect(plan.modelle?.sprachmodelle).toEqual(['qwen3.5:4b']);
  });

  it('fragt nach dem Schlüssel der Sprechererkennung nur, wenn er fehlt', () => {
    expect(hfSchluesselNoetig({ pyannote: true }, stand())).toBe(true);
    expect(hfSchluesselNoetig({ pyannote: true }, stand({}, { hf_token: true }))).toBe(false);
    expect(hfSchluesselNoetig({}, stand())).toBe(false);
  });

  it('plant nach dem Neustart nur, was zugestimmt und noch nicht da ist', () => {
    expect(mitschriftPlanen({ zustimmung: {}, stand: stand() })).toBeNull();
    expect(
      mitschriftPlanen({
        zustimmung: { whisper: true, pyannote: true },
        stand: stand({}, { whisper: true }),
        hfSchluessel: ' hf_x '
      })
    ).toMatchObject({ whisper: false, sprechertrennung: true, hf_token: 'hf_x' });
  });

  it('erkennt, ob überhaupt etwas zu laden ist', () => {
    expect(bedarfVorhanden(null)).toBeNull();
    expect(bedarfVorhanden(kosten([baustein('ffmpeg', 0.1, true)]))).toBe(false);
    expect(bedarfVorhanden(k)).toBe(true);
  });
});

describe('Ersteinrichtung: Neustart', () => {
  function auftrag(status: string, art = 'einrichtung_modelle'): Auftrag {
    return { id: art + status, art, status } as Auftrag;
  }

  it('startet nur neu, wenn nötig und nichts mehr lädt', () => {
    const noetig = stand({ neustart_noetig: true });
    expect(neustartMoeglich(noetig, [])).toBe(true);
    expect(neustartMoeglich(noetig, [auftrag('laeuft')])).toBe(false);
    expect(neustartMoeglich(noetig, [auftrag('fertig'), auftrag('fehler', 'einrichtung_ffmpeg')])).toBe(true);
    // Andere Aufträge (Transkription) halten den Neustart nicht auf – sie zählen nicht zur Einrichtung.
    expect(neustartMoeglich(noetig, [auftrag('laeuft', 'transkription')])).toBe(true);
    expect(neustartMoeglich(stand(), [])).toBe(false);
    expect(neustartMoeglich(null, [])).toBe(false);
    expect(einrichtungLaeuft([auftrag('wartet', 'einrichtung_ollama')])).toBe(true);
  });
});

describe('Ersteinrichtung: Worte statt Fachbegriffe', () => {
  it('benennt jeden Baustein ohne Produktnamen', () => {
    for (const kennung of [
      'ffmpeg',
      'ollama',
      'sprachmodell',
      'einbettung',
      'laufzeit',
      'whisper',
      'pyannote',
      'neu'
    ]) {
      expect(bausteinText(kennung)).not.toMatch(FACHWORT);
    }
  });

  it('schreibt Größen und Dauer verständlich', () => {
    expect(gbText(3.3)).toBe('3,3 GB');
    expect(gbText(2)).toBe('2 GB');
    expect(gbText(0.35)).toBe('350 MB');
    expect(downloadDauerText(10, 13)).toBe('ca. 10–13 Minuten');
    expect(downloadDauerText(0.2, 0.3)).toBe('unter einer Minute');
    expect(downloadDauerText(100, 130)).toBe('ca. 2 Stunden');
  });
});
