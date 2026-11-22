/**
 * Nachgebauter Dienst für die Bildschirmfotos: liefert die gebaute Oberfläche (build/) und beantwortet
 * /api/* mit erfundenen, aber realistischen Daten. Nur zum Ansehen – kein Ersatz für den echten Dienst.
 *
 *   node bildschirmfotos/attrappe.mjs [port]
 *
 * Szenario wechseln: GET /__szenario?name=leer|laufend|reihe|fehler|anmelden|anmelden-mehr|nutzer|admin|
 *   einrichtung|einrichtung-nichts|neustart|mitschrift|fehler-einrichtung|aufnahme
 */
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const WURZEL = fileURLToPath(new URL('../build/', import.meta.url));
const TYPEN = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.png': 'image/png',
  '.json': 'application/json',
  '.svg': 'image/svg+xml'
};

const jetzt = () => Date.now() / 1000;
let szenario = 'reihe';
let angemeldet = false;
let nummer = 41;

const einstellungen = {
  transkription_modus: 'lokal',
  nachbearbeitung_modus: 'lokal',
  chatbot_modus: 'lokal',
  chatbot_kontext: 'auszuege',
  sprache: 'de',
  offline: false,
  ausgabeordner: 'C:\\Users\\Anwender\\Documents\\VERMERK\\Ergebnisse',
  eingabeordner: 'C:\\Users\\Anwender\\Documents\\VERMERK\\Eingang',
  export_zielordner: null,
  export_formate: ['docx', 'pdf'],
  ollama_modell: 'qwen3.5:4b',
  chatbot_ollama_modell: 'qwen3.5:4b',
  api_transkription_voreinstellung: '',
  api_transkription_endpunkt: '',
  api_transkription_modell: '',
  api_nachbearbeitung_voreinstellung: '',
  aktive_systemprompt_vorlage: 'Ergebnisprotokoll',
  geraete_empfang_aktiv: true,
  geraete_empfang_port: 8765,
  geraete_live_aktiv: true,
  geraete_live_auftrag: '',
  geraete_live_auswertung_vorab: true,
  netz_freigabe_aktiv: false,
  netz_freigabe_port: 8780,
  einrichtung_abgeschlossen: true
};

const EINRICHTUNG = ['einrichtung', 'einrichtung-nichts', 'neustart', 'mitschrift'];
const einrichtungOffen = () => EINRICHTUNG.includes(szenario);
/** Gestartete Einrichtungsaufträge (für die Seitenleiste und den Schritt „Einrichten“). */
let einrichtungsAuftraege = [];

const RECHNER = {
  profil: {
    arbeitsspeicher_gb: 32,
    prozessorkerne: 12,
    grafikkarte: 'NVIDIA RTX 4060',
    grafikspeicher_gb: 8,
    freier_platz_gb: 211
  },
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
    {
      kennung: 'sprecher',
      name: 'Sprechererkennung',
      stufe: 'gut',
      text: '',
      dauer_von: 1,
      dauer_bis: 2,
      einheit: 'minuten_je_stunde_aufnahme',
      ort: 'Grafikkarte'
    },
    {
      kennung: 'protokoll',
      name: 'Protokoll',
      stufe: 'gut',
      text: '',
      dauer_von: 4,
      dauer_bis: 8,
      einheit: 'minuten_je_stunde_aufnahme',
      ort: 'Grafikkarte'
    },
    {
      kennung: 'chat',
      name: 'Frag mein Meeting',
      stufe: 'maessig',
      text: '',
      dauer_von: 15,
      dauer_bis: 40,
      einheit: 'sekunden_je_frage',
      ort: 'Prozessor'
    }
  ],
  empfehlung: 'lokal',
  begruendung:
    'Dieser Computer schafft alles selbst. Empfehlung: alles auf diesem Computer – nichts verlässt ihn.',
  hinweise: [],
  empfohlene_modelle: { transkription: 'large-v3-turbo', nachbearbeitung: 'qwen3.5:4b', suche: 'bge-m3' },
  whisper_modelle: [],
  sprachmodelle: [],
  einbettungsmodelle: []
};

function kosten(url) {
  const nichts = szenario === 'einrichtung-nichts';
  const wahl = {
    transkription: url.searchParams.get('transkription') ?? 'lokal',
    nachbearbeitung: url.searchParams.get('nachbearbeitung') ?? 'lokal',
    chatbot: url.searchParams.get('chatbot') ?? 'lokal'
  };
  const b = (kennung, gb) => ({
    kennung,
    name: kennung,
    download_gb: gb,
    platz_gb: gb * 1.4,
    hinweis: '',
    vorhanden: nichts
  });
  const teile = [b('ffmpeg', 0.1)];
  if (wahl.nachbearbeitung === 'lokal' || wahl.chatbot === 'lokal')
    teile.push(b('ollama', 1.8), b('sprachmodell', 3.3));
  if (wahl.chatbot === 'lokal') teile.push(b('einbettung', 1.2));
  if (wahl.transkription === 'lokal') teile.push(b('laufzeit', 4.4), b('whisper', 1.6), b('pyannote', 0.1));
  const offen = teile.filter((t) => !t.vorhanden);
  const download = offen.reduce((s, t) => s + t.download_gb, 0);
  return {
    arbeitsweise: wahl,
    bausteine: teile,
    download_gb: Math.round(download * 100) / 100,
    platz_gb: Math.round(download * 140) / 100,
    download_minuten_von: Math.round(download * 2.7),
    download_minuten_bis: Math.round(download * 3.5),
    annahme_mbit: 50,
    freier_platz_gb: 211,
    platz_knapp: false,
    zustimmung_noetig: download > 0,
    neustart_noetig: !nichts && wahl.transkription === 'lokal',
    ollama_lizenz: offen.some((t) => t.kennung === 'ollama')
      ? {
          lizenz_url: 'https://github.com/ollama/ollama/blob/main/LICENSE',
          bedingungen_url: 'https://ollama.com/terms'
        }
      : null
  };
}

function einrichtungStand() {
  const nachNeustart = szenario === 'mitschrift';
  return {
    einrichtung_abgeschlossen: !einrichtungOffen(),
    naechster_schritt:
      szenario === 'neustart'
        ? 'neustart'
        : nachNeustart
          ? 'mitschrift'
          : einrichtungOffen()
            ? 'willkommen'
            : 'fertig',
    einrichtung_fortsetzen: szenario === 'neustart' || nachNeustart ? 'transkription' : '',
    lokale_einrichtung_zurueckgestellt: false,
    arbeitsweise: { transkription: 'lokal', nachbearbeitung: 'lokal', chatbot: 'lokal' },
    modelle: {
      whisper: 'large-v3-turbo',
      sprachmodell: 'qwen3.5:4b',
      chat_sprachmodell: 'qwen3.5:4b',
      einbettung: 'bge-m3'
    },
    vorhanden: {
      ffmpeg: szenario !== 'einrichtung',
      ollama: nachNeustart,
      ollama_laeuft: nachNeustart,
      ollama_version: null,
      ollama_modelle: nachNeustart ? ['qwen3.5:4b', 'bge-m3:latest'] : [],
      laufzeit: nachNeustart,
      laufzeit_aktiv: nachNeustart,
      sprachmodell: nachNeustart,
      einbettung: nachNeustart,
      whisper: false,
      pyannote: false,
      hf_token: false
    },
    offen: [],
    rechenumgebung_fehlt: szenario === 'einrichtung',
    neustart_noetig:
      szenario === 'neustart' || (szenario === 'einrichtung' && einrichtungsAuftraege.length > 0),
    online_ohne_anbieter: [],
    geraete: 0,
    geraete_empfang_aktiv: true,
    auftraege: einrichtungsAuftraege
  };
}

function auftrag(teil) {
  return {
    id: 'a0',
    art: 'transkription',
    titel: 'aufnahme.m4a',
    herkunft: 'oberflaeche',
    vorrang: 0,
    status: 'wartet',
    erstellt: jetzt() - 300,
    gestartet: null,
    beendet: null,
    stufe: '',
    stufe_text: '',
    fortschritt: null,
    abschnitt: null,
    vorschau: '',
    meldungen: [],
    ergebnis: null,
    fehler: null,
    angaben: {},
    ...teil
  };
}

const VORSCHAU =
  '[00:00] Sprecher 1: Guten Morgen zusammen, dann fangen wir an. Erster Punkt ist der Stand beim Umbau im zweiten Stock.\n' +
  '[00:12] Sprecher 2: Die Trockenbauer sind seit Montag dran, wir liegen etwa eine Woche hinter dem Plan.\n' +
  '[00:24] Sprecher 1: Was heißt das für die Elektrik? Können die trotzdem nächste Woche anfangen?\n' +
  '[00:31] Sprecher 3: Wir können parallel im Ostflügel beginnen, dann verlieren wir nichts.';

function auftraege() {
  const laufend = auftrag({
    id: 'lauf1',
    titel: 'Baubesprechung Hauptstraße 12.m4a',
    status: 'laeuft',
    erstellt: jetzt() - 400,
    gestartet: jetzt() - 150,
    stufe: 'transkription',
    stufe_text: 'Transkription läuft',
    fortschritt: 0.37,
    abschnitt: [4, 11],
    vorschau: VORSCHAU,
    angaben: { quelle: 'C:\\Aufnahmen\\Baubesprechung Hauptstraße 12.m4a', mit_auswertung: true }
  });
  const fertig = auftrag({
    id: 'fertig1',
    titel: 'Jour fixe Vertrieb.mp3',
    status: 'fertig',
    erstellt: jetzt() - 900,
    gestartet: jetzt() - 800,
    beendet: jetzt() - 40,
    fortschritt: 1,
    ergebnis: {
      transkript_json: 'C:\\VERMERK\\Ergebnisse\\Jour fixe Vertrieb_lokal_transkript_20261122_081500.json'
    }
  });
  const wartend = [
    auftrag({
      id: 'warte1',
      titel: 'Teamrunde.webm',
      erstellt: jetzt() - 100,
      angaben: { quelle: 'C:\\Aufnahmen\\Teamrunde.webm' }
    }),
    auftrag({
      id: 'warte2',
      titel: 'Raum3_20261122_0930.wav',
      herkunft: 'geraet:Raum-3',
      vorrang: 10,
      erstellt: jetzt() - 60
    })
  ];
  const fremd = auftrag({
    id: 'fremd1',
    titel: 'Andere Verarbeitung',
    herkunft: 'andere',
    fremd: true,
    status: 'laeuft',
    erstellt: jetzt() - 500,
    gestartet: jetzt() - 420,
    fortschritt: 0.62
  });
  if (einrichtungOffen()) return einrichtungsAuftraege;
  switch (szenario) {
    case 'nutzer':
      return [fremd, { ...wartend[0], besitzer: 'anna', titel: 'Kundentermin Müller.mp3' }];
    case 'admin':
      return [{ ...laufend, besitzer: 'anna' }];
    case 'leer':
    case 'anmelden':
    case 'anmelden-mehr':
    case 'aufnahme':
    case 'fehler-einrichtung':
      return [];
    case 'laufend':
      return [laufend];
    case 'fertig':
      return [fertig];
    default:
      return [fertig, laufend, ...wartend];
  }
}

function aufnahmeStand() {
  if (szenario !== 'aufnahme') return { laeuft: false, pausiert: false, dauer: 0, pegel: 0, geraet: null };
  return { laeuft: true, pausiert: false, dauer: 754.2, pegel: 0.46, geraet: 'Mikrofon (Jabra Speak 510)' };
}

const NUTZER = [
  {
    name: 'jonas',
    anzeigename: 'Jonas Weber',
    admin: true,
    aktiv: true,
    hat_passwort: true,
    zugaenge: [{ bezeichnung: 'Laptop', angelegt: '2026-11-02' }],
    angelegt: '2026-10-01'
  },
  {
    name: 'anna',
    anzeigename: 'Anna Schmidt',
    admin: false,
    aktiv: true,
    hat_passwort: true,
    zugaenge: [{ bezeichnung: 'Büro-PC', angelegt: '2026-11-10' }],
    angelegt: '2026-10-03'
  },
  {
    name: 'mehmet',
    anzeigename: 'Mehmet Kaya',
    admin: false,
    aktiv: true,
    hat_passwort: true,
    zugaenge: [],
    angelegt: '2026-10-20'
  },
  {
    name: 'lisa',
    anzeigename: 'Lisa Braun',
    admin: false,
    aktiv: false,
    hat_passwort: false,
    zugaenge: [],
    angelegt: '2026-11-05'
  }
];

const BESPRECHUNGEN = [
  ['b1', 'Baubesprechung Hauptstraße 12', '20261121_143000', 3840, 4, true],
  ['b2', 'Jour fixe Vertrieb', '20261121_091500', 1720, 3, true],
  ['b3', 'Elternabend Klasse 4b', '20261120_190000', 5460, 6, false],
  ['b4', 'Projektstart Website-Relaunch', '20261119_100000', 2700, 5, true],
  ['b5', 'Mitarbeitergespräch Planung 2027', '20261118_150000', 1260, 2, false],
  ['b6', 'Vorstandssitzung November', '20261115_170000', 6120, 7, true]
].map(([id, titel, zeit, dauer, sprecher, protokoll]) => ({
  id,
  titel,
  zeit,
  transkript: `C:\\VERMERK\\Ergebnisse\\${titel}_lokal_transkript_${zeit}.json`,
  dauer_sekunden: dauer,
  anzahl_sprecher: sprecher,
  sprache: 'de',
  hat_protokoll: protokoll,
  protokolle: protokoll ? [{ id: `p-${id}`, zeit }] : [],
  besitzer: null,
  eigen: true,
  geteilt_mit: id === 'b4' ? ['alle'] : []
}));

function besprechungen() {
  if (szenario !== 'nutzer') return BESPRECHUNGEN;
  return BESPRECHUNGEN.map((b) =>
    b.id === 'b1'
      ? { ...b, id: 'jonas~b1', besitzer: 'jonas', eigen: false, geteilt_mit: ['anna'] }
      : { ...b, besitzer: 'anna' }
  );
}

const SEGMENTE = [
  [
    0,
    11,
    'SPEAKER_00',
    'Frau Keller',
    'Guten Tag zusammen. Ich würde vorschlagen, wir gehen direkt in die Punkte. Erstens der Zeitplan, zweitens die Mehrkosten beim Dach.'
  ],
  [
    11,
    26,
    'SPEAKER_01',
    'Herr Brandt',
    'Beim Zeitplan liegen wir etwa eine Woche zurück. Die Trockenbauer hatten Lieferprobleme bei den Profilen, das ist aber seit Montag gelöst.'
  ],
  [26, 34, 'SPEAKER_00', 'Frau Keller', 'Und was bedeutet das für die Elektrik?'],
  [
    34,
    52,
    'SPEAKER_02',
    'Herr Yilmaz',
    'Wir können im Ostflügel schon anfangen, dort ist alles fertig. Dann holen wir einen Teil der Woche wieder auf.'
  ],
  [
    52,
    70,
    'SPEAKER_03',
    'Frau Petrov',
    'Zum Dach: Das Angebot für die zusätzliche Dämmung liegt bei rund 18.000 Euro. Ich habe zwei Vergleichsangebote angefragt.'
  ],
  [70, 81, 'SPEAKER_01', 'Herr Brandt', 'Bis wann brauchen wir die Entscheidung?'],
  [
    81,
    96,
    'SPEAKER_03',
    'Frau Petrov',
    'Spätestens Ende des Monats, sonst verschiebt sich der Dachdecker in den Januar.'
  ],
  [
    96,
    110,
    'SPEAKER_00',
    'Frau Keller',
    'Gut. Dann entscheiden wir das in der nächsten Runde am 28. Ich nehme es als offenen Punkt auf.'
  ]
];

const PROTOKOLL = `# Baubesprechung Hauptstraße 12

**Datum:** 21.11.2026 · **Teilnehmende:** Frau Keller, Herr Brandt, Herr Yilmaz, Frau Petrov

## Zeitplan
- Rückstand von etwa **einer Woche** durch Lieferprobleme beim Trockenbau (seit Montag behoben).
- Elektrik beginnt vorgezogen im **Ostflügel**, um Zeit aufzuholen.

## Mehrkosten Dach
- Angebot zusätzliche Dämmung: rund **18.000 €**.
- Zwei Vergleichsangebote sind angefragt.

## Beschlüsse
| Punkt | Entscheidung |
|---|---|
| Elektrik | Start im Ostflügel nächste Woche |
| Dach | Entscheidung am 28.11. |

## Aufgaben
1. Frau Petrov: Vergleichsangebote bis 26.11. einholen.
2. Herr Yilmaz: Ablauf Ostflügel mit Trockenbau abstimmen.
`;

function details(id) {
  const b = besprechungen().find((x) => x.id === id) ?? besprechungen()[0];
  const stamm = b.transkript.split('\\').pop().replace('.json', '');
  return {
    ...b,
    sprecher: [
      { id: 'SPEAKER_00', name: 'Frau Keller', segmente: 3, sekunden: 1180 },
      { id: 'SPEAKER_01', name: 'Herr Brandt', segmente: 2, sekunden: 920 },
      { id: 'SPEAKER_02', name: 'Herr Yilmaz', segmente: 1, sekunden: 860 },
      { id: 'SPEAKER_03', name: '', segmente: 2, sekunden: 880 }
    ],
    segmente: SEGMENTE.map(([start, ende, sprecher_id, sprecher, text]) => ({
      start,
      ende,
      sprecher_id,
      sprecher,
      text
    })),
    protokoll: b.hat_protokoll ? { id: `p-${b.id}`, text: PROTOKOLL } : null,
    dateien: [
      { name: `${stamm}.txt`, art: 'txt', groesse: 48213 },
      { name: `${stamm}.docx`, art: 'docx', groesse: 21877 },
      { name: `${stamm}.srt`, art: 'srt', groesse: 61202 },
      { name: `${stamm}.json`, art: 'json', groesse: 233901 },
      ...(b.hat_protokoll ? [{ name: `${b.titel}_protokoll_${b.zeit}.md`, art: 'md', groesse: 2817 }] : [])
    ]
  };
}

const VORLAGEN = [
  {
    name: 'Ergebnisprotokoll',
    text: 'Erstelle ein knappes Ergebnisprotokoll mit Beschlüssen und Aufgaben.',
    eigene: false
  },
  {
    name: 'Verlaufsprotokoll',
    text: 'Gib den Verlauf der Besprechung Punkt für Punkt wieder.',
    eigene: false
  },
  {
    name: 'Baubesprechung',
    text: 'Fasse Termine, Mängel, Kosten und Zuständigkeiten zusammen.',
    eigene: true
  }
];

const ANBIETER = [
  {
    id: 'ionos',
    name: 'IONOS AI Model Hub',
    standort: 'Rechenzentrum in Deutschland (Berlin)',
    hinweis: '',
    schluessel_link: '',
    doku_link: '',
    hat_platzhalter: false,
    chat: {
      url: 'https://openai.inference.de-txl.ionos.com/v1/chat/completions',
      modell: 'meta-llama/Llama-3.3-70B-Instruct'
    },
    embedding: { url: 'https://openai.inference.de-txl.ionos.com/v1/embeddings', modell: 'BAAI/bge-m3' },
    transkription: null
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    standort: 'Anbieter aus den USA',
    hinweis: '',
    schluessel_link: '',
    doku_link: '',
    hat_platzhalter: false,
    chat: { url: 'https://openrouter.ai/api/v1/chat/completions', modell: 'mistralai/mistral-small' },
    embedding: null,
    diarisierung_anbieter: '',
    transkription: { url: 'https://openrouter.ai/api/v1/audio/transcriptions', modell: 'openai/whisper-1' }
  }
];

function senden(antwort, status, daten) {
  antwort.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store'
  });
  antwort.end(JSON.stringify(daten));
}

function sse(antwort, art, daten) {
  nummer++;
  antwort.write(
    `id: ${nummer}\nevent: ${art}\ndata: ${JSON.stringify({ nummer, art, daten, zeit: jetzt() })}\n\n`
  );
}

async function koerper(anfrage) {
  let text = '';
  for await (const teil of anfrage) text += teil;
  try {
    return JSON.parse(text || '{}');
  } catch {
    return {};
  }
}

async function api(anfrage, antwort, url) {
  const p = url.pathname;
  const m = anfrage.method;
  const mitSchluessel = (anfrage.headers.authorization ?? '').startsWith('Bearer ');
  if (p === '/api/anmelden' && m === 'POST') {
    const { schluessel } = await koerper(anfrage);
    if (schluessel === 'falsch')
      return senden(antwort, 401, { detail: 'Der Zugangsschlüssel stimmt nicht.' });
    angemeldet = true;
    return senden(antwort, 200, { angemeldet_als: 'büro' });
  }
  if (p === '/api/gesundheit') return senden(antwort, 200, { status: 'ok', version: '0.6.0-alpha.1' });
  if (p === '/api/anmeldung') return senden(antwort, 200, { mehrbenutzer: szenario === 'anmelden-mehr' });
  if (szenario.startsWith('anmelden') && !angemeldet && !mitSchluessel)
    return senden(antwort, 401, { detail: 'Nicht angemeldet.' });

  if (p === '/api/info') {
    const mehr = szenario === 'nutzer' || szenario === 'admin';
    return senden(antwort, 200, {
      version: '0.6.0-alpha.1',
      rolle: mitSchluessel ? 'desktop' : 'server',
      angemeldet_als: mehr ? (szenario === 'admin' ? 'jonas' : 'anna') : mitSchluessel ? 'desktop' : 'büro',
      anzeigename: mehr
        ? szenario === 'admin'
          ? 'Jonas Weber'
          : 'Anna Schmidt'
        : mitSchluessel
          ? 'desktop'
          : 'büro',
      admin: szenario !== 'nutzer',
      mehrbenutzer: mehr,
      faehigkeiten: {
        lokale_transkription: true,
        mikrofon: mitSchluessel,
        dateipfade: mitSchluessel,
        ordner_oeffnen: mitSchluessel,
        geraete_empfang: true
      },
      einrichtung_abgeschlossen: !(mitSchluessel && einrichtungOffen()),
      ausgabeordner: einstellungen.ausgabeordner
    });
  }
  if (p === '/api/nutzer/namen')
    return senden(
      antwort,
      200,
      NUTZER.map(({ name, anzeigename }) => ({ name, anzeigename }))
    );
  if (p === '/api/nutzer') return senden(antwort, 200, NUTZER);
  if (p === '/api/ich')
    return senden(
      antwort,
      200,
      NUTZER.find((n) => n.name === (szenario === 'admin' ? 'jonas' : 'anna'))
    );
  if (p === '/api/zustand')
    return senden(antwort, 200, {
      letzte_nummer: nummer,
      jetzt: jetzt(),
      auftraege: auftraege(),
      empfang:
        szenario === 'nutzer'
          ? null
          : { aktiv: true, port: 8765, geraete: 2, live: true, fehler: null, zuletzt: null },
      freigaben: szenario === 'reihe' ? [{ geraet: 'Flur-EG', datei: 'rec_0007.wav', pfad: '' }] : []
    });
  if (p === '/api/ereignisse') {
    antwort.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    antwort.write(': verbunden\n\n');
    if (szenario === 'reihe' || szenario === 'fehler') {
      sse(antwort, 'hinweis', {
        text: 'Das Sprachmodell für Zusammenfassungen fehlt noch.',
        stufe: 'fehler',
        quelle: 'ollama',
        code: 'modell_fehlt'
      });
    }
    sse(antwort, 'live', {
      geraet: 'Raum-3',
      datei: 'rec_0012.wav',
      text: 'Dann zum nächsten Punkt: die Raumplanung für Januar. Wir brauchen den großen Saal an zwei Terminen …',
      bis: 812
    });
    const herz = setInterval(() => antwort.write(': herzschlag\n\n'), 15000);
    anfrage.on('close', () => clearInterval(herz));
    return;
  }
  if (p === '/api/einstellungen' && m === 'GET') return senden(antwort, 200, einstellungen);
  if (p === '/api/einstellungen' && m === 'PATCH') {
    Object.assign(einstellungen, await koerper(anfrage));
    return senden(antwort, 200, einstellungen);
  }
  if (p === '/api/einstellungen/schluessel')
    return senden(antwort, 200, { transkription: false, nachbearbeitung: false, chatbot: false });
  if (p === '/api/einstellungen/vorlagen') return senden(antwort, 200, VORLAGEN);
  if (p === '/api/einstellungen/anbieter') return senden(antwort, 200, ANBIETER);
  if (p === '/api/einstellungen/systemprompt')
    return senden(antwort, 200, { text: 'Fasse die Besprechung sachlich zusammen.' });
  if (p === '/api/dateien/eingang')
    return senden(antwort, 200, [
      {
        name: 'Baubesprechung Hauptstraße 12.m4a',
        pfad: 'C:\\Aufnahmen\\Baubesprechung Hauptstraße 12.m4a',
        groesse: 61_400_000,
        geaendert: jetzt() - 3600 * 20
      },
      {
        name: 'Teamrunde.webm',
        pfad: 'C:\\Aufnahmen\\Teamrunde.webm',
        groesse: 18_200_000,
        geaendert: jetzt() - 3600 * 26
      },
      {
        name: 'Kundentermin Müller.mp3',
        pfad: 'C:\\Aufnahmen\\Kundentermin Müller.mp3',
        groesse: 34_900_000,
        geaendert: jetzt() - 3600 * 50
      }
    ]);
  if (p === '/api/besprechungen/export/formate')
    return senden(antwort, 200, [
      { id: 'docx', name: 'Word', inhalte: ['transkript', 'protokoll', 'beides'] },
      { id: 'pdf', name: 'PDF', inhalte: ['transkript', 'protokoll', 'beides'] },
      { id: 'odt', name: 'OpenDocument', inhalte: ['transkript', 'protokoll', 'beides'] },
      { id: 'txt', name: 'Text', inhalte: ['transkript'] },
      { id: 'srt', name: 'Untertitel', inhalte: ['transkript'] }
    ]);
  if (p === '/api/besprechungen') return senden(antwort, 200, besprechungen());
  if (/^\/api\/besprechungen\/[^/]+\/sprecher\/vorschlaege$/.test(p))
    return senden(antwort, 200, {
      vorschlaege: { SPEAKER_03: { name: 'Frau Petrov', sicher: false } },
      stimmen_vorhanden: true
    });
  if (/^\/api\/besprechungen\/[^/]+\/export$/.test(p) && m === 'POST') {
    const b = details(decodeURIComponent(p.split('/')[3]));
    return senden(antwort, 200, {
      dateien: [
        { name: `${b.titel}.docx`, pfad: `C:\\VERMERK\\Ergebnisse\\${b.titel}.docx` },
        { name: `${b.titel}.pdf`, pfad: `C:\\VERMERK\\Ergebnisse\\${b.titel}.pdf` }
      ],
      fehler: []
    });
  }
  if (p === '/api/sprecherprofile')
    return senden(antwort, 200, [
      {
        id: 'p1',
        name: 'Frau Keller',
        erstellt: '2026-10-12T09:00:00+02:00',
        aktualisiert: '2026-11-21T15:00:00+01:00'
      },
      {
        id: 'p2',
        name: 'Herr Brandt',
        erstellt: '2026-10-12T09:05:00+02:00',
        aktualisiert: '2026-10-12T09:05:00+02:00'
      },
      {
        id: 'p3',
        name: 'Jonas Weber',
        erstellt: '2026-11-02T11:00:00+01:00',
        aktualisiert: '2026-11-02T11:00:00+01:00'
      }
    ]);
  if (p === '/api/aufnahme') return senden(antwort, 200, aufnahmeStand());
  if (p === '/api/aufnahme/geraete')
    return senden(antwort, 200, [
      { name: 'Mikrofon (Jabra Speak 510)', standard: false, gewaehlt: true },
      { name: 'Mikrofonarray (Realtek Audio)', standard: true, gewaehlt: false }
    ]);
  if (p === '/api/system/neustart' && m === 'POST') return senden(antwort, 200, { neustart: true });
  if (p === '/api/einrichtung/stand') return senden(antwort, 200, einrichtungStand());
  if (p === '/api/einrichtung/rechner') {
    await new Promise((r) => setTimeout(r, 150));
    return senden(antwort, 200, RECHNER);
  }
  if (p === '/api/einrichtung/kosten') return senden(antwort, 200, kosten(url));
  if (p === '/api/einrichtung/entscheidung' && m === 'POST') {
    const wahl = await koerper(anfrage);
    const stand = einrichtungStand();
    stand.arbeitsweise = {
      transkription: wahl.transkription,
      nachbearbeitung: wahl.nachbearbeitung,
      chatbot: wahl.chatbot
    };
    return senden(antwort, 200, stand);
  }
  const einrichtungsAuftrag = (art, titel, teil) => {
    const a = auftrag({ id: art, art, titel, vorrang: -5, ...teil });
    einrichtungsAuftraege = [...einrichtungsAuftraege.filter((x) => x.art !== art), a];
    return a;
  };
  if (p === '/api/einrichtung/ffmpeg' && m === 'POST')
    return senden(
      antwort,
      201,
      einrichtungsAuftrag('einrichtung_ffmpeg', 'FFmpeg einrichten', {
        status: 'fertig',
        gestartet: jetzt() - 40,
        beendet: jetzt() - 25,
        fortschritt: 1
      })
    );
  if (p === '/api/einrichtung/ollama' && m === 'POST')
    return senden(
      antwort,
      201,
      einrichtungsAuftrag('einrichtung_ollama', 'Ollama einrichten', {
        status: 'laeuft',
        stufe: 'ollama',
        gestartet: jetzt() - 160,
        fortschritt: 0.42
      })
    );
  if (p === '/api/einrichtung/modelle' && m === 'POST') {
    const lauf = szenario === 'mitschrift';
    return senden(
      antwort,
      201,
      einrichtungsAuftrag('einrichtung_modelle', 'Modelle laden', {
        status: lauf ? 'laeuft' : 'wartet',
        stufe: lauf ? 'whisper' : '',
        gestartet: lauf ? jetzt() - 50 : null,
        fortschritt: lauf ? 0.28 : null
      })
    );
  }
  if (p === '/api/einrichtung/anbieter' && m === 'POST') {
    const d = await koerper(anfrage);
    return senden(antwort, 200, {
      bereich: d.bereich,
      anbieter: d.anbieter,
      endpunkt: '',
      modell: '',
      adresse_vollstaendig: true,
      schluessel_vorhanden: !!d.schluessel,
      gemerkt: true
    });
  }
  if (p === '/api/einrichtung/spaeter' || p === '/api/einrichtung/abschliessen')
    return senden(antwort, 200, {
      ...einrichtungStand(),
      einrichtung_abgeschlossen: true,
      neustart_noetig: false
    });
  if (p.startsWith('/api/besprechungen/'))
    return senden(antwort, 200, details(decodeURIComponent(p.split('/')[3])));
  if (p === '/api/auftraege/transkription' && m === 'POST') {
    if (szenario === 'fehler')
      return senden(antwort, 422, {
        titel: 'Sprachmodell fehlt',
        text: 'Das Sprachmodell für Zusammenfassungen ist noch nicht geladen. Bitte in den Einstellungen unter „Zusammenfassung“ herunterladen.',
        code: 'modell_fehlt',
        bereich: 'zusammenfassung'
      });
    if (szenario === 'fehler-einrichtung')
      return senden(antwort, 422, {
        titel: 'Noch nicht bereit',
        text: 'Für das Umwandeln in Text auf diesem Computer fehlt noch ein Teil. Er wird eingerichtet, wenn Sie zustimmen – oder Sie wählen in den Einstellungen einen Online-Dienst.',
        code: 'lokale_einrichtung',
        bereich: 'transkription'
      });
    return senden(antwort, 201, auftrag({ id: 'neu1', titel: 'Teamrunde.webm' }));
  }
  if (p === '/api/chat/verlaeufe')
    return senden(antwort, 200, [
      {
        id: 'c1',
        titel: 'Wer kümmert sich um das Dach?',
        erstellt: '2026-11-21T15:02:00+01:00',
        aktualisiert: '2026-11-21T15:04:00+01:00',
        fragen: 2
      },
      {
        id: 'c2',
        titel: 'Offene Punkte Vertrieb',
        erstellt: '2026-11-20T10:00:00+01:00',
        aktualisiert: '2026-11-20T10:03:00+01:00',
        fragen: 1
      }
    ]);
  if (p.startsWith('/api/chat/verlaeufe/'))
    return senden(antwort, 200, {
      id: 'c1',
      titel: 'Wer kümmert sich um das Dach?',
      dokumente: [],
      nachrichten: [
        { role: 'user', content: 'Wer kümmert sich um die Angebote für das Dach?', quellen: [] },
        {
          role: 'assistant',
          content:
            '**Frau Petrov** holt zwei Vergleichsangebote für die zusätzliche Dämmung ein (bisher rund 18.000 €). Die Entscheidung fällt in der Runde am **28.11.** – danach würde sich der Dachdecker in den Januar verschieben.',
          quellen: ['Baubesprechung Hauptstraße 12 (01:10)', 'Protokoll Baubesprechung Hauptstraße 12']
        }
      ]
    });
  if (p === '/api/geraete/usb/anschluesse')
    return senden(antwort, 200, [
      { port: 'COM5', beschreibung: 'USB-JTAG/serial debug unit', vermerk: true },
      { port: 'COM3', beschreibung: 'Standardmäßige Seriell-über-Bluetooth-Verbindung', vermerk: false }
    ]);
  if (p === '/api/geraete/usb/erkennen')
    return senden(antwort, 200, {
      geraete_id: 'a1b2c3',
      board: 'S3',
      firmware: '1.4.0',
      eingerichtet: false,
      wlan: 'Büro-WLAN',
      fuer_pc: false,
      fuer_server: false,
      bekannt_als: null
    });
  if (p === '/api/geraete/usb/einrichten') {
    await new Promise((r) => setTimeout(r, 20000));
    return senden(antwort, 200, {
      name: 'Raum-4',
      info: {},
      pc_url: 'http://192.168.1.20:8765',
      inventar: ''
    });
  }
  if (p === '/api/geraete')
    return senden(antwort, 200, {
      empfang: { aktiv: true, port: 8765, geraete: 2, live: true, fehler: null, zuletzt: null },
      geraete: [
        {
          name: 'Raum-3',
          angelegt: '2026-10-02',
          geraete_id: 'a1b2',
          kontakt: {
            zeit: jetzt() - 30,
            adresse: '192.168.1.41',
            geraete_id: 'a1b2',
            firmware: '1.4.0',
            andere_id: false
          }
        },
        {
          name: 'Flur-EG',
          angelegt: '2026-10-15',
          geraete_id: null,
          kontakt: {
            zeit: jetzt() - 7200,
            adresse: '192.168.1.57',
            geraete_id: 'c3d4',
            firmware: '1.4.0',
            andere_id: false
          }
        }
      ],
      adressen: ['http://192.168.1.20:8765'],
      freigaben: []
    });
  if (p === '/api/ollama/modelle')
    return senden(antwort, 200, {
      laeuft: true,
      installiert: ['qwen3.5:9b-q4_K_M'],
      empfohlen: [
        { id: 'qwen3.5:4b', label: 'Qwen3.5 4B (empfohlener Standard)', groesse_gb: 3.3, hinweis: '' },
        {
          id: 'hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M',
          label: 'LFM2.5 2.6B (schneller, auch für Rechner ohne Grafikkarte)',
          groesse_gb: 1.6,
          hinweis: ''
        },
        {
          id: 'qwen3.5:9b-q4_K_M',
          label: 'Qwen3.5 9B (genauer, braucht mehr Speicher)',
          groesse_gb: 6.6,
          hinweis: ''
        }
      ],
      einbettung: []
    });
  if (p === '/api/system/diagnose')
    return senden(antwort, 200, [
      { id: 'python_version', name: 'Python-Version', ok: true, text: '3.11.9', kritisch: true },
      { id: 'cuda', name: 'GPU-Beschleunigung (CUDA)', ok: true, text: 'RTX 4060', kritisch: false },
      { id: 'ram', name: 'Arbeitsspeicher', ok: true, text: '32 GB', kritisch: false },
      { id: 'disk_space', name: 'Freier Speicherplatz', ok: true, text: '211 GB', kritisch: false },
      { id: 'ffmpeg', name: 'FFmpeg', ok: true, text: '7.1', kritisch: true },
      { id: 'hf_token', name: 'HF_TOKEN vorhanden', ok: false, text: 'nicht gesetzt', kritisch: false },
      { id: 'ollama_running', name: 'Ollama-Dienst erreichbar', ok: true, text: 'ok', kritisch: false },
      {
        id: 'ollama_model',
        name: 'Ollama-Modell vorhanden',
        ok: false,
        text: 'qwen3.5:4b fehlt',
        kritisch: false
      }
    ]);
  if (m !== 'GET') return senden(antwort, 200, {});
  return senden(antwort, 404, { detail: 'Unbekannter Endpunkt.' });
}

function datei(antwort, pfad) {
  let ziel = normalize(join(WURZEL, pfad === '/' ? 'index.html' : pfad));
  if (!ziel.startsWith(normalize(WURZEL))) ziel = join(WURZEL, 'index.html');
  if (!existsSync(ziel) || statSync(ziel).isDirectory()) {
    ziel = existsSync(`${ziel}.html`) ? `${ziel}.html` : join(WURZEL, 'index.html');
  }
  antwort.writeHead(200, { 'Content-Type': TYPEN[extname(ziel)] ?? 'application/octet-stream' });
  createReadStream(ziel).pipe(antwort);
}

export function starten(port = 4319) {
  const server = createServer((anfrage, antwort) => {
    const url = new URL(anfrage.url ?? '/', 'http://localhost');
    if (url.pathname === '/__szenario') {
      szenario = url.searchParams.get('name') ?? 'reihe';
      angemeldet = false;
      einrichtungsAuftraege = [];
      return senden(antwort, 200, { szenario });
    }
    if (url.pathname.startsWith('/api/')) {
      void api(anfrage, antwort, url).catch((e) => senden(antwort, 500, { detail: String(e) }));
      return;
    }
    datei(antwort, decodeURIComponent(url.pathname));
  });
  return new Promise((erfuellen) => server.listen(port, '127.0.0.1', () => erfuellen(server)));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === normalize(process.argv[1])) {
  const port = Number(process.argv[2] ?? 4319);
  await starten(port);
  console.log(`Attrappe läuft auf http://127.0.0.1:${port}`);
}
