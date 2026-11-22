/**
 * Das EINE Modul für alle Anfragen an den Dienst.
 *
 * Solange das Startgatter (src/lib/start/gatter.ts) keinen Zugang gesetzt hat, scheitert jede Anfrage
 * sofort mit `GatterGeschlossen` – es gibt keinen geratenen Port und keinen Versuch ins Leere. Wird der
 * Zugang gesperrt (Dienst startet neu) oder ersetzt (neuer Port), brechen laufende Anfragen ab, und
 * Antworten aus der alten Verbindung werden verworfen.
 */
import type {
  Anbieter,
  Auftrag,
  Besprechung,
  BesprechungDetails,
  ChatVerlauf,
  ChatVerlaufKurz,
  DiagnosePunkt,
  EingangsDatei,
  Einstellungen,
  ExportErgebnis,
  ExportFormat,
  Fehlerantwort,
  GeraetAngelegt,
  GeraeteStand,
  Info,
  ModellStand,
  SchluesselStand,
  TranskriptionAnfrage,
  Vorlage,
  Zustand
} from './typen';

export interface Zugang {
  /** Leer im Browser (gleiche Herkunft), sonst z. B. `http://127.0.0.1:53817`. */
  basisUrl: string;
  /** Bearer-Schlüssel im Tauri-Fenster; `null` im Browser (Sitzungs-Cookie). */
  schluessel: string | null;
}

export class GatterGeschlossen extends Error {
  constructor() {
    super('Noch keine Verbindung zum Dienst.');
    this.name = 'GatterGeschlossen';
  }
}

export class ApiFehler extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** Bei 422 aus /api/auftraege: Titel, Text und Code für den Dialog. */
    readonly fehler: Fehlerantwort | null = null
  ) {
    super(message);
    this.name = 'ApiFehler';
  }
}

export class NichtAngemeldet extends ApiFehler {
  constructor(status: number) {
    super(status, 'Nicht angemeldet.');
    this.name = 'NichtAngemeldet';
  }
}

export class Verbindungsfehler extends Error {
  constructor(message = 'Der Dienst antwortet nicht.') {
    super(message);
    this.name = 'Verbindungsfehler';
  }
}

let zugang: Zugang | null = null;
let generation = 0;
let steuerung = new AbortController();
let beiNichtAngemeldet: ((status: number) => void) | null = null;

/** Setzt den Zugang (nach dem Startgatter). Alles aus einer früheren Verbindung wird abgebrochen. */
export function zugangSetzen(neu: Zugang): void {
  generation++;
  steuerung.abort();
  steuerung = new AbortController();
  zugang = { basisUrl: neu.basisUrl.replace(/\/+$/, ''), schluessel: neu.schluessel };
}

/** Keine Anfragen mehr, bis `zugangSetzen` wieder aufgerufen wird (z. B. Dienst startet neu). */
export function zugangSperren(): void {
  generation++;
  steuerung.abort();
  steuerung = new AbortController();
  zugang = null;
}

export function zugangBekannt(): boolean {
  return zugang !== null;
}

/** Nur für Anzeige/Tests: die aktuelle Basisadresse. */
export function aktuelleBasis(): string | null {
  return zugang?.basisUrl ?? null;
}

export function nichtAngemeldetMelden(rueckruf: ((status: number) => void) | null): void {
  beiNichtAngemeldet = rueckruf;
}

function verbundenesSignal(eigenes?: AbortSignal): AbortSignal {
  if (!eigenes) return steuerung.signal;
  const beide = new AbortController();
  const weiter = () => beide.abort();
  for (const s of [steuerung.signal, eigenes]) {
    if (s.aborted) beide.abort();
    else s.addEventListener('abort', weiter, { once: true });
  }
  return beide.signal;
}

function kopfzeilen(z: Zugang, methode: string, eigene?: Record<string, string>): Record<string, string> {
  const kopf: Record<string, string> = { Accept: 'application/json', ...eigene };
  if (z.schluessel) kopf.Authorization = `Bearer ${z.schluessel}`;
  else if (methode !== 'GET' && methode !== 'HEAD') kopf['X-Vermerk-Anfrage'] = '1';
  return kopf;
}

function istFehlerantwort(wert: unknown): wert is Fehlerantwort {
  if (!wert || typeof wert !== 'object') return false;
  const o = wert as Record<string, unknown>;
  return typeof o.titel === 'string' && typeof o.text === 'string' && typeof o.code === 'string';
}

/** Macht aus einer Fehlerantwort einen `ApiFehler` (422 mit Titel/Text/Code oder `detail`). */
export async function fehlerAusAntwort(antwort: Response): Promise<ApiFehler> {
  let koerper: unknown = null;
  try {
    koerper = await antwort.json();
  } catch {
    koerper = null;
  }
  if (antwort.status === 422 && istFehlerantwort(koerper)) {
    return new ApiFehler(422, koerper.text, koerper);
  }
  const detail = (koerper as { detail?: unknown } | null)?.detail;
  const text =
    typeof detail === 'string'
      ? detail
      : antwort.status === 422
        ? 'Die Eingaben sind unvollständig.'
        : `Das hat nicht geklappt (Fehler ${antwort.status}).`;
  return new ApiFehler(antwort.status, text);
}

interface Optionen {
  json?: unknown;
  body?: BodyInit;
  kopf?: Record<string, string>;
  signal?: AbortSignal;
}

/** Rohe Anfrage; wirft bei Fehlern. Für Ströme (`/api/ereignisse`, `/api/chat`). */
export async function anfrage(methode: string, pfad: string, optionen: Optionen = {}): Promise<Response> {
  const z = zugang;
  if (!z) throw new GatterGeschlossen();
  const meineGeneration = generation;
  const kopf = kopfzeilen(z, methode, optionen.kopf);
  let body = optionen.body;
  if (optionen.json !== undefined) {
    kopf['Content-Type'] = 'application/json';
    body = JSON.stringify(optionen.json);
  }
  let antwort: Response;
  try {
    antwort = await fetch(z.basisUrl + pfad, {
      method: methode,
      headers: kopf,
      body,
      credentials: z.schluessel ? 'omit' : 'same-origin',
      cache: 'no-store',
      signal: verbundenesSignal(optionen.signal)
    });
  } catch (fehler) {
    if (meineGeneration !== generation) throw new GatterGeschlossen();
    if (fehler instanceof DOMException && fehler.name === 'AbortError') throw fehler;
    throw new Verbindungsfehler();
  }
  if (meineGeneration !== generation) throw new GatterGeschlossen();
  if (antwort.status === 401 || (antwort.status === 403 && pfad.startsWith('/api/ereignisse'))) {
    beiNichtAngemeldet?.(antwort.status);
    throw new NichtAngemeldet(antwort.status);
  }
  if (!antwort.ok) throw await fehlerAusAntwort(antwort);
  return antwort;
}

async function json<T>(methode: string, pfad: string, optionen: Optionen = {}): Promise<T> {
  const antwort = await anfrage(methode, pfad, optionen);
  if (antwort.status === 204) return undefined as T;
  return (await antwort.json()) as T;
}

const pfadteil = encodeURIComponent;

/** Hochladen mit Fortschritt (fetch kann das nicht melden). */
function hochladen(datei: File, fortschritt?: (anteil: number) => void): Promise<EingangsDatei> {
  const z = zugang;
  if (!z) return Promise.reject(new GatterGeschlossen());
  const meineGeneration = generation;
  return new Promise((erfuellen, ablehnen) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${z.basisUrl}/api/dateien/hochladen`);
    for (const [name, wert] of Object.entries(kopfzeilen(z, 'POST'))) xhr.setRequestHeader(name, wert);
    xhr.withCredentials = !z.schluessel;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && fortschritt) fortschritt(e.loaded / e.total);
    };
    const abbruch = () => xhr.abort();
    steuerung.signal.addEventListener('abort', abbruch, { once: true });
    xhr.onerror = () => ablehnen(new Verbindungsfehler());
    xhr.onabort = () => ablehnen(new GatterGeschlossen());
    xhr.onload = () => {
      steuerung.signal.removeEventListener('abort', abbruch);
      if (meineGeneration !== generation) return ablehnen(new GatterGeschlossen());
      if (xhr.status === 401) {
        beiNichtAngemeldet?.(401);
        return ablehnen(new NichtAngemeldet(401));
      }
      const antwort = new Response(xhr.responseText || null, { status: xhr.status });
      if (xhr.status < 200 || xhr.status >= 300) {
        void fehlerAusAntwort(antwort).then(ablehnen);
        return;
      }
      void antwort.json().then(erfuellen, ablehnen);
    };
    const form = new FormData();
    form.append('datei', datei, datei.name);
    xhr.send(form);
  });
}

/** Lädt eine Datei der Besprechung und bietet sie zum Speichern an (funktioniert mit Schlüssel und Cookie). */
async function speichernUnter(pfad: string, name: string): Promise<void> {
  const antwort = await anfrage('GET', pfad, { kopf: { Accept: '*/*' } });
  const blob = await antwort.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const api = {
  anmelden: (schluessel: string) =>
    json<{ angemeldet_als: string }>('POST', '/api/anmelden', { json: { schluessel } }),
  abmelden: () => json<{ abgemeldet: boolean }>('POST', '/api/abmelden'),
  info: () => json<Info>('GET', '/api/info'),
  zustand: () => json<Zustand>('GET', '/api/zustand'),
  ereignisse: (seit: number | null, letzteId: string | null, signal?: AbortSignal) =>
    anfrage('GET', seit === null ? '/api/ereignisse' : `/api/ereignisse?seit=${seit}`, {
      kopf: { Accept: 'text/event-stream', ...(letzteId ? { 'Last-Event-ID': letzteId } : {}) },
      signal
    }),

  transkriptionStarten: (daten: TranskriptionAnfrage) =>
    json<Auftrag>('POST', '/api/auftraege/transkription', { json: daten }),
  auswertungStarten: (transkript: string, systemprompt: string | null) =>
    json<Auftrag>('POST', '/api/auftraege/auswertung', { json: { transkript, systemprompt } }),
  auftragAbbrechen: (id: string) =>
    json<{ abgebrochen: boolean }>('DELETE', `/api/auftraege/${pfadteil(id)}`),

  besprechungen: () => json<Besprechung[]>('GET', '/api/besprechungen'),
  besprechung: (id: string) => json<BesprechungDetails>('GET', `/api/besprechungen/${pfadteil(id)}`),
  protokollSpeichern: (id: string, text: string) =>
    json<{ gespeichert: boolean; word_hinweis: string | null }>(
      'PUT',
      `/api/besprechungen/${pfadteil(id)}/protokoll`,
      { json: { text } }
    ),
  sprecherUmbenennen: (id: string, namen: Record<string, string>) =>
    json<{ gespeichert: boolean; word_hinweis: string | null }>(
      'PUT',
      `/api/besprechungen/${pfadteil(id)}/sprecher`,
      { json: { namen } }
    ),
  exportFormate: () => json<ExportFormat[]>('GET', '/api/besprechungen/export/formate'),
  exportieren: (id: string, inhalt: string, formate: string[]) =>
    json<ExportErgebnis>('POST', `/api/besprechungen/${pfadteil(id)}/export`, { json: { inhalt, formate } }),
  dateiSpeichern: (id: string, name: string) =>
    speichernUnter(`/api/besprechungen/${pfadteil(id)}/dateien/${pfadteil(name)}`, name),

  eingang: () => json<EingangsDatei[]>('GET', '/api/dateien/eingang'),
  hochladen,

  einstellungen: () => json<Einstellungen>('GET', '/api/einstellungen'),
  einstellungenAendern: (aenderungen: Partial<Einstellungen>) =>
    json<Einstellungen>('PATCH', '/api/einstellungen', { json: aenderungen }),
  anbieter: () => json<Anbieter[]>('GET', '/api/einstellungen/anbieter'),
  schluesselStand: () => json<SchluesselStand>('GET', '/api/einstellungen/schluessel'),
  schluesselSetzen: (name: keyof SchluesselStand, wert: string, merken: boolean) =>
    json<{ vorhanden: boolean; gemerkt: boolean }>('PUT', `/api/einstellungen/schluessel/${name}`, {
      json: { wert, merken }
    }),
  schluesselLoeschen: (name: keyof SchluesselStand) =>
    json<{ vorhanden: boolean }>('DELETE', `/api/einstellungen/schluessel/${name}`),
  vorlagen: () => json<Vorlage[]>('GET', '/api/einstellungen/vorlagen'),
  vorlageSpeichern: (name: string, text: string) =>
    json<{ gespeichert: boolean }>('PUT', `/api/einstellungen/vorlagen/${pfadteil(name)}`, {
      json: { text }
    }),
  systemprompt: () => json<{ text: string }>('GET', '/api/einstellungen/systemprompt'),
  systempromptSpeichern: (text: string) =>
    json<{ gespeichert: boolean }>('PUT', '/api/einstellungen/systemprompt', { json: { text } }),

  geraete: () => json<GeraeteStand>('GET', '/api/geraete'),
  geraetAnlegen: (name: string) => json<GeraetAngelegt>('POST', '/api/geraete', { json: { name } }),
  geraetEntfernen: (name: string) => json<{ entfernt: boolean }>('DELETE', `/api/geraete/${pfadteil(name)}`),

  chat: (frage: string, besprechungen: string[], verlaufId: string | null, signal?: AbortSignal) =>
    anfrage('POST', '/api/chat', {
      json: { frage, besprechungen, verlauf_id: verlaufId },
      kopf: { Accept: 'text/event-stream' },
      signal
    }),
  chatVerlaeufe: () => json<ChatVerlaufKurz[]>('GET', '/api/chat/verlaeufe'),
  chatVerlauf: (id: string) => json<ChatVerlauf>('GET', `/api/chat/verlaeufe/${pfadteil(id)}`),
  chatVerlaufLoeschen: (id: string) =>
    json<{ geloescht: boolean }>('DELETE', `/api/chat/verlaeufe/${pfadteil(id)}`),

  modelle: () => json<ModellStand>('GET', '/api/ollama/modelle'),
  modellLaden: (modell: string) => json<Auftrag>('POST', '/api/ollama/laden', { json: { modell } }),

  diagnose: () => json<DiagnosePunkt[]>('GET', '/api/system/diagnose'),
  ordnerOeffnen: (pfad: string) =>
    json<{ geoeffnet: boolean }>('POST', '/api/system/ordner-oeffnen', { json: { pfad } })
};
