/**
 * Datenformen der Programmschnittstelle. Wo `openapi.json` ein Schema hat, kommt es aus `schema.d.ts`
 * (erzeugt mit `npm run api:typen`); für Antworten ohne Schema stehen die Formen hier, abgelesen aus
 * `protokoll_assistent/api/`.
 */
import type { components } from './schema';

type S = components['schemas'];

export type AuftragStatus = 'wartet' | 'laeuft' | 'fertig' | 'fehler' | 'abgebrochen';
export type Auftrag = Omit<S['Auftrag'], 'status'> & { status: AuftragStatus };
export type Info = S['Info'];
export type Faehigkeiten = S['Faehigkeiten'];
export type Besprechung = S['Besprechung'];
export type BesprechungDetails = S['BesprechungDetails'];
export type Segment = S['Segment'];
export type Sprecher = S['Sprecher'];
export type Datei = S['Datei'];
export type EingangsDatei = S['EingangsDatei'];
export type Vorlage = S['Vorlage'];
export type Fehlerantwort = S['Fehler'];
export type TranskriptionAnfrage = S['TranskriptionAnfrage'];

export interface Empfang {
  aktiv: boolean;
  port?: number;
  geraete?: number;
  ziel?: string;
  live?: boolean;
  fehler?: string | null;
  zuletzt?: string | null;
}

export interface Freigabe {
  geraet: string;
  datei: string;
  pfad: string;
}

export interface Zustand {
  letzte_nummer: number;
  auftraege: Auftrag[];
  empfang: Empfang | null;
  freigaben: Freigabe[];
}

/** Ein Ereignis aus `/api/ereignisse` (Inhalt der `data`-Zeile). */
export interface Ereignis<T = unknown> {
  nummer: number;
  art: string;
  daten: T;
  zeit: number;
}

export interface Hinweis {
  text: string;
  stufe: string;
  quelle: string;
}

export interface GeraetStatus {
  geraet: string;
  datei: string;
  zustand: string;
  fortschritt?: number;
  meldung?: string;
  aktualisiert?: number;
}

export interface LiveText {
  geraet: string;
  datei: string;
  text: string;
  bis: number;
}

export interface GeraetEintrag {
  name: string;
  angelegt: string;
  /** Servermodus: wem das Gerät gehört (Anmeldename) oder `null` (allgemein). */
  besitzer?: string | null;
  geraete_id: string | null;
  kontakt: {
    zeit: number;
    adresse: string;
    geraete_id: string;
    firmware: string;
    andere_id: boolean;
  } | null;
}

export interface GeraeteStand {
  empfang: Empfang;
  geraete: GeraetEintrag[];
  adressen: string[];
  freigaben: Freigabe[];
}

export interface GeraetAngelegt {
  name: string;
  token: string;
  basis_url: string;
  konfiguration: string;
}

export interface AnbieterZiel {
  url: string;
  modell: string;
}

export interface Anbieter {
  id: string;
  name: string;
  standort: string;
  hinweis: string;
  schluessel_link: string;
  doku_link: string;
  hat_platzhalter: boolean;
  chat: AnbieterZiel | null;
  embedding: AnbieterZiel | null;
  transkription: AnbieterZiel | null;
}

export interface ModellOption {
  id: string;
  label: string;
  groesse_gb: number;
  hinweis: string;
}

export interface ModellStand {
  laeuft: boolean;
  installiert: string[];
  empfohlen: ModellOption[];
  einbettung: ModellOption[];
}

export interface DiagnosePunkt {
  id: string;
  name: string;
  ok: boolean;
  text: string;
  kritisch: boolean;
}

export interface ExportFormat {
  id: string;
  name: string;
  inhalte: string[];
}

export interface ExportErgebnis {
  dateien: { name: string; pfad: string }[];
  fehler: string[];
}

export interface ChatVerlaufKurz {
  id: string;
  titel: string;
  erstellt: string;
  aktualisiert: string;
  fragen: number;
}

/** Eine Quelle unter einer Antwort: Titel der Unterlage, ggf. mit Zeitangabe. */
export type ChatQuelle = string;

export interface ChatNachricht {
  role: 'user' | 'assistant';
  content: string;
  quellen?: ChatQuelle[];
}

export interface ChatVerlauf {
  id: string;
  titel: string;
  nachrichten: ChatNachricht[];
  dokumente: string[];
}

/** Einstellungen: frei geformtes Objekt; die Felder, die die Oberfläche benutzt, stehen hier. */
export interface Einstellungen {
  transkription_modus?: 'lokal' | 'api';
  nachbearbeitung_modus?: 'lokal' | 'api';
  chatbot_modus?: 'lokal' | 'api';
  chatbot_kontext?: string;
  sprache?: string;
  offline?: boolean;
  ausgabeordner?: string | null;
  eingabeordner?: string | null;
  export_zielordner?: string | null;
  export_formate?: string[];
  ollama_modell?: string;
  chatbot_ollama_modell?: string;
  api_transkription_voreinstellung?: string;
  api_transkription_endpunkt?: string;
  api_transkription_modell?: string;
  api_nachbearbeitung_voreinstellung?: string;
  api_nachbearbeitung_endpunkt?: string;
  api_nachbearbeitung_modell?: string;
  api_nachbearbeitung_eigener_schluessel?: boolean;
  chatbot_api_voreinstellung?: string;
  chatbot_api_endpunkt?: string;
  chatbot_api_modell?: string;
  chatbot_api_embedding_endpunkt?: string;
  chatbot_api_embedding_modell?: string;
  chatbot_api_eigener_schluessel?: boolean;
  aktive_systemprompt_vorlage?: string | null;
  geraete_empfang_aktiv?: boolean;
  geraete_empfang_port?: number;
  geraete_live_aktiv?: boolean;
  geraete_live_auftrag?: string;
  geraete_live_auswertung_vorab?: boolean;
  netz_freigabe_aktiv?: boolean;
  netz_freigabe_port?: number;
  einrichtung_abgeschlossen?: boolean;
  [schluessel: string]: unknown;
}

export type SchluesselStand = Record<'transkription' | 'nachbearbeitung' | 'chatbot', boolean>;

export type Anmeldedaten = { schluessel: string } | { name: string; passwort: string };

export interface ZugangKurz {
  bezeichnung: string;
  angelegt: string;
}

/** Ein Nutzer, wie ihn `/api/nutzer` und `/api/ich` liefern (ohne Geheimnisse). */
export interface Nutzer {
  name: string;
  anzeigename: string;
  admin: boolean;
  aktiv?: boolean;
  hat_passwort: boolean;
  zugaenge: ZugangKurz[];
  angelegt?: string;
}

export interface NutzerName {
  name: string;
  anzeigename: string;
}

export interface NeuerZugang {
  bezeichnung: string;
  schluessel: string;
}
