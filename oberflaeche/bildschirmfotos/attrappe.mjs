/**
 * Nachgebauter Dienst für die Bildschirmfotos: liefert die gebaute Oberfläche (build/) und beantwortet
 * /api/* mit erfundenen, aber realistischen Daten. Nur zum Ansehen – kein Ersatz für den echten Dienst.
 *
 *   node bildschirmfotos/attrappe.mjs [port]
 *
 * Szenario wechseln: GET /__szenario?name=leer|laufend|reihe|fehler|anmelden
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
  switch (szenario) {
    case 'leer':
    case 'anmelden':
      return [];
    case 'laufend':
      return [laufend];
    case 'fertig':
      return [fertig];
    default:
      return [fertig, laufend, ...wartend];
  }
}

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
  protokolle: protokoll ? [{ id: `p-${id}`, zeit }] : []
}));

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
  const b = BESPRECHUNGEN.find((x) => x.id === id) ?? BESPRECHUNGEN[0];
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
  if (szenario === 'anmelden' && !angemeldet && !mitSchluessel)
    return senden(antwort, 401, { detail: 'Nicht angemeldet.' });

  if (p === '/api/info')
    return senden(antwort, 200, {
      version: '0.6.0-alpha.1',
      rolle: mitSchluessel ? 'desktop' : 'server',
      angemeldet_als: mitSchluessel ? 'desktop' : 'büro',
      faehigkeiten: {
        lokale_transkription: true,
        mikrofon: mitSchluessel,
        dateipfade: mitSchluessel,
        ordner_oeffnen: mitSchluessel,
        geraete_empfang: true
      },
      einrichtung_abgeschlossen: true,
      ausgabeordner: einstellungen.ausgabeordner
    });
  if (p === '/api/zustand')
    return senden(antwort, 200, {
      letzte_nummer: nummer,
      auftraege: auftraege(),
      empfang: { aktiv: true, port: 8765, geraete: 2, live: true, fehler: null, zuletzt: null },
      freigaben: szenario === 'reihe' ? [{ geraet: 'Flur-EG', datei: 'rec_0007.wav', pfad: '' }] : []
    });
  if (p === '/api/ereignisse') {
    antwort.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    antwort.write(': verbunden\n\n');
    if (szenario === 'reihe' || szenario === 'fehler') {
      sse(antwort, 'hinweis', {
        text: 'Das Sprachmodell qwen3.5:4b fehlt bei Ollama – Zusammenfassungen von VERMERK Raum gehen erst, wenn es geladen ist.',
        stufe: 'fehler',
        quelle: 'ollama'
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
  if (p === '/api/besprechungen') return senden(antwort, 200, BESPRECHUNGEN);
  if (p.startsWith('/api/besprechungen/'))
    return senden(antwort, 200, details(decodeURIComponent(p.split('/')[3])));
  if (p === '/api/auftraege/transkription' && m === 'POST') {
    if (szenario === 'fehler')
      return senden(antwort, 422, {
        titel: 'Ollama-Modell fehlt',
        text: "Das Modell 'qwen3.5:4b' ist bei Ollama nicht installiert.",
        code: 'modell_fehlt'
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
