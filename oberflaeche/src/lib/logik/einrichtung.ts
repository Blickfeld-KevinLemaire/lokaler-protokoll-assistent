/**
 * Ersteinrichtung ohne Fenster-Code: Reihenfolge der Schritte, Urteile über den Computer in einfachen
 * Worten, Zustimmung je Download und welche Aufträge daraus werden. Die Endpunkte stehen in
 * `protokoll_assistent/api/routen_einrichtung.py`; Grundregel dort: nichts wird ohne Zustimmung geladen.
 */
import type {
  Auftrag,
  EinrichtungBaustein,
  EinrichtungKosten,
  EinrichtungModelle,
  EinrichtungRechner,
  EinrichtungSchritt,
  EinrichtungStand
} from '../api/typen';
import { ERLEDIGT } from './warteschlange';

export type Schritt =
  | 'willkommen'
  | 'computer'
  | 'arbeitsweise'
  | 'bedarf'
  | 'einrichten'
  | 'online'
  | 'raum'
  | 'mitschrift'
  | 'fertig';

export const SCHRITT_TITEL: Record<Schritt, string> = {
  willkommen: 'Willkommen',
  computer: 'Ihr Computer',
  arbeitsweise: 'Arbeitsweise',
  bedarf: 'Was nötig ist',
  einrichten: 'Einrichten',
  online: 'Online-Dienst',
  raum: 'VERMERK Raum',
  mitschrift: 'Spracherkennung',
  fertig: 'Fertig'
};

export type Bereich = 'transkription' | 'nachbearbeitung' | 'chatbot';
export type Modus = 'lokal' | 'api';
export type Wahl = Record<Bereich, Modus | null>;

export const BEREICHE: { id: Bereich; text: string; schritt: string }[] = [
  { id: 'transkription', text: 'Transkription', schritt: 'mitschrift' },
  { id: 'nachbearbeitung', text: 'Zusammenfassung', schritt: 'protokoll' },
  { id: 'chatbot', text: 'Frag mein Meeting', schritt: 'chat' }
];

export const LEERE_WAHL: Wahl = { transkription: null, nachbearbeitung: null, chatbot: null };

// ---------------------------------------------------------------- Reihenfolge

export interface FolgeOptionen {
  wahl: Wahl;
  /** Muss etwas geladen werden? `null`: noch unbekannt (vor „Arbeitsweise“) – dann mitzählen. */
  bedarf: boolean | null;
  /** Läuft die Einrichtung nach dem Neustart weiter (nur noch Spracherkennung und Abschluss)? */
  nachNeustart: boolean;
  /** Gibt es hier Aufnahmegeräte (VERMERK Raum)? */
  raum: boolean;
  /** Bereiche, für die noch ein Online-Dienst fehlt (nach dem Neustart). */
  onlineOffen?: string[];
}

export function onlineGewaehlt(wahl: Wahl): boolean {
  return Object.values(wahl).includes('api');
}

/** Die Schritte in ihrer Reihenfolge. Was nichts zu tun hat, fällt weg. */
export function schrittFolge(o: FolgeOptionen): Schritt[] {
  if (o.nachNeustart) {
    return ['mitschrift', ...(o.onlineOffen?.length ? (['online'] as Schritt[]) : []), 'fertig'];
  }
  const folge: Schritt[] = ['willkommen', 'computer', 'arbeitsweise'];
  if (o.bedarf !== false) folge.push('bedarf', 'einrichten');
  if (onlineGewaehlt(o.wahl)) folge.push('online');
  if (o.raum) folge.push('raum');
  folge.push('fertig');
  return folge;
}

/** Wo die Einrichtung beginnt (oder nach einem Neustart weitergeht). */
export function startSchritt(stand: Pick<EinrichtungStand, 'naechster_schritt'>): Schritt {
  switch (stand.naechster_schritt) {
    case 'mitschrift':
      return 'mitschrift';
    case 'neustart':
      return 'fertig';
    default:
      return 'willkommen';
  }
}

export function nachbar(folge: Schritt[], aktuell: Schritt, richtung: 1 | -1): Schritt | null {
  const i = folge.indexOf(aktuell);
  if (i < 0) return folge[0] ?? null;
  return folge[i + richtung] ?? null;
}

// ---------------------------------------------------------------- Ihr Computer

export type Ton = 'gut' | 'mittel' | 'online';

export function urteil(stufe: string | undefined): { text: string; ton: Ton } {
  if (stufe === 'gut') return { text: 'Läuft gut auf diesem Computer', ton: 'gut' };
  if (stufe === 'maessig') return { text: 'Geht, dauert etwas', ton: 'mittel' };
  return { text: 'Besser online', ton: 'online' };
}

function spanne(von: number, bis: number, einheit: string, einzahl: string): string {
  const a = Math.max(1, Math.round(von));
  const b = Math.max(a, Math.round(bis));
  if (a === b) return `ca. ${a} ${a === 1 ? einzahl : einheit}`;
  return `ca. ${a}–${b} ${einheit}`;
}

/** „ca. 3–5 Minuten je Stunde Aufnahme“, „ca. 5–10 Sekunden je Frage“ – oder leer. */
export function dauerText(s: Pick<EinrichtungSchritt, 'dauer_von' | 'dauer_bis' | 'einheit'>): string {
  if (s.dauer_von == null) return '';
  const von = s.dauer_von;
  const bis = s.dauer_bis ?? von;
  if (s.einheit === 'minuten_je_stunde_aufnahme') {
    const teil =
      bis >= 90 ? spanne(von / 60, bis / 60, 'Stunden', 'Stunde') : spanne(von, bis, 'Minuten', 'Minute');
    return `${teil} je Stunde Aufnahme`;
  }
  if (s.einheit === 'sekunden_je_frage') {
    const teil =
      bis >= 90 ? spanne(von / 60, bis / 60, 'Minuten', 'Minute') : spanne(von, bis, 'Sekunden', 'Sekunde');
    return `${teil} je Frage`;
  }
  return '';
}

export function schrittFuer(rechner: EinrichtungRechner | null, bereich: Bereich): EinrichtungSchritt | null {
  const kennung = BEREICHE.find((b) => b.id === bereich)!.schritt;
  return rechner?.schritte.find((s) => s.kennung === kennung) ?? null;
}

/**
 * Vorauswahl aus der Einschätzung: Was hier läuft, steht auf „Auf diesem Computer“. Ein Online-Dienst wird
 * nie von selbst gewählt (dafür gehen Daten an einen Anbieter) – dort bleibt die Wahl offen.
 */
export function vorauswahl(rechner: EinrichtungRechner | null): Wahl {
  const wahl: Wahl = { ...LEERE_WAHL };
  for (const b of BEREICHE) {
    const s = schrittFuer(rechner, b.id);
    wahl[b.id] = s && s.stufe !== 'nicht' ? 'lokal' : null;
  }
  return wahl;
}

/** Die gespeicherte Arbeitsweise (wenn die Einrichtung schon einmal abgeschlossen war). */
export function wahlAusStand(stand: Pick<EinrichtungStand, 'arbeitsweise'>): Wahl {
  const wahl: Wahl = { ...LEERE_WAHL };
  for (const b of BEREICHE) {
    const w = stand.arbeitsweise[b.id];
    wahl[b.id] = w === 'api' || w === 'lokal' ? w : null;
  }
  return wahl;
}

export function wahlVollstaendig(wahl: Wahl): wahl is Record<Bereich, Modus> {
  return BEREICHE.every((b) => wahl[b.id] !== null);
}

export function empfehlungText(empfehlung: string | null | undefined): string | null {
  switch (empfehlung) {
    case 'lokal':
      return 'Alles auf diesem Computer';
    case 'gemischt':
      return 'Transkription hier, Zusammenfassung online';
    case 'api':
      return 'Online-Dienst';
    default:
      return null;
  }
}

// ---------------------------------------------------------------- Was nötig ist

/** Bausteine in einfachen Worten (die Namen des Dienstes enthalten Produktnamen). */
export const BAUSTEIN_TEXT: Record<string, string> = {
  ffmpeg: 'Werkzeug für Aufnahmen',
  ollama: 'KI-Umgebung',
  sprachmodell: 'Sprachmodell für Zusammenfassungen',
  einbettung: 'Suchhilfe für Frag mein Meeting',
  laufzeit: 'Rechenpaket für die Transkription',
  whisper: 'Spracherkennung',
  pyannote: 'Sprechererkennung'
};

export function bausteinText(kennung: string): string {
  return BAUSTEIN_TEXT[kennung] ?? 'Zusatzpaket';
}

/** Was fehlt und heruntergeladen werden müsste. */
export function offeneBausteine(kosten: Pick<EinrichtungKosten, 'bausteine'> | null): EinrichtungBaustein[] {
  return (kosten?.bausteine ?? []).filter((b) => !b.vorhanden && b.download_gb > 0);
}

/** Muss überhaupt etwas geladen werden (sonst entfallen „Was nötig ist“ und „Einrichten“)? */
export function bedarfVorhanden(kosten: EinrichtungKosten | null): boolean | null {
  if (!kosten) return null;
  return offeneBausteine(kosten).length > 0;
}

/** Wovon ein Baustein abhängt: Sprachmodelle brauchen die KI-Umgebung, die Spracherkennung das Rechenpaket. */
export const ABHAENGIG_VON: Record<string, string> = {
  sprachmodell: 'ollama',
  einbettung: 'ollama',
  whisper: 'laufzeit',
  pyannote: 'laufzeit'
};

export type Zustimmung = Record<string, boolean>;

/** Darf der Baustein angehakt werden? Nur, wenn das, worauf er aufbaut, da ist oder ebenfalls zugestimmt. */
export function zustimmungMoeglich(
  kennung: string,
  zustimmung: Zustimmung,
  kosten: EinrichtungKosten | null
): boolean {
  const basis = ABHAENGIG_VON[kennung];
  if (!basis) return true;
  const offen = offeneBausteine(kosten).some((b) => b.kennung === basis);
  return !offen || !!zustimmung[basis];
}

/** Haken setzen oder entfernen; wer die Grundlage abwählt, wählt die abhängigen Bausteine mit ab. */
export function zustimmungSetzen(
  zustimmung: Zustimmung,
  kennung: string,
  an: boolean,
  kosten: EinrichtungKosten | null
): Zustimmung {
  const neu: Zustimmung = { ...zustimmung, [kennung]: an };
  if (!an) {
    for (const [abhaengig, basis] of Object.entries(ABHAENGIG_VON))
      if (basis === kennung) neu[abhaengig] = false;
  }
  for (const k of Object.keys(neu)) if (neu[k] && !zustimmungMoeglich(k, neu, kosten)) neu[k] = false;
  return neu;
}

/** Allem zustimmen oder alles abwählen. */
export function alleSetzen(an: boolean, kosten: EinrichtungKosten | null): Zustimmung {
  return Object.fromEntries(offeneBausteine(kosten).map((b) => [b.kennung, an]));
}

export function alleZugestimmt(zustimmung: Zustimmung, kosten: EinrichtungKosten | null): boolean {
  const offen = offeneBausteine(kosten);
  return offen.length > 0 && offen.every((b) => zustimmung[b.kennung]);
}

/** Braucht die Sprechererkennung noch einen Zugangsschlüssel? */
export function hfSchluesselNoetig(zustimmung: Zustimmung, stand: EinrichtungStand | null): boolean {
  return !!zustimmung.pyannote && !stand?.vorhanden.hf_token;
}

function modellDa(name: string, vorhanden: string[]): boolean {
  return vorhanden.includes(name) || (!name.includes(':') && vorhanden.includes(`${name}:latest`));
}

export interface Plan {
  ffmpeg: boolean;
  ollama: boolean;
  modelle: EinrichtungModelle | null;
  /** Zustimmung, die Rechenumgebung beim nächsten Start zu laden (`entscheidung`). */
  zustimmungRechenumgebung: boolean;
}

/**
 * Aus der Zustimmung werden Aufträge. Spracherkennung und Sprechererkennung gehen nur, wenn der Dienst schon
 * in der Rechenumgebung läuft – sonst nach dem Neustart (Schritt „Spracherkennung“).
 */
export function auftraegePlanen(o: {
  kosten: EinrichtungKosten | null;
  zustimmung: Zustimmung;
  stand: EinrichtungStand | null;
  wahl: Wahl;
  hfSchluessel?: string;
}): Plan {
  const offen = new Set(offeneBausteine(o.kosten).map((b) => b.kennung));
  const z = (k: string) => offen.has(k) && !!o.zustimmung[k];
  const vorhanden = o.stand?.vorhanden;
  const modellNamen = o.stand?.modelle ?? {};
  const installiert = vorhanden?.ollama_modelle ?? [];
  const sprachmodelle: string[] = [];
  const dazu = (name: string | undefined) => {
    if (name && !modellDa(name, installiert) && !sprachmodelle.includes(name)) sprachmodelle.push(name);
  };
  if (z('sprachmodell')) {
    dazu(modellNamen.sprachmodell);
    if (o.wahl.chatbot === 'lokal') dazu(modellNamen.chat_sprachmodell);
  }
  if (z('einbettung')) dazu(modellNamen.einbettung);
  const laufzeitAktiv = !!vorhanden?.laufzeit_aktiv;
  const whisper = laufzeitAktiv && z('whisper');
  const sprechertrennung = laufzeitAktiv && z('pyannote');
  // Ist die KI-Umgebung installiert, läuft aber nicht, startet der Auftrag sie nur (lädt nichts).
  const ollamaStarten = sprachmodelle.length > 0 && !!vorhanden?.ollama && !vorhanden.ollama_laeuft;
  const hf = (o.hfSchluessel ?? '').trim();
  return {
    ffmpeg: z('ffmpeg'),
    ollama: z('ollama') || ollamaStarten,
    modelle:
      sprachmodelle.length || whisper || sprechertrennung
        ? {
            zustimmung: true,
            sprachmodelle,
            whisper,
            sprechertrennung,
            hf_token: sprechertrennung && hf ? hf : null,
            hf_token_merken: true
          }
        : null,
    zustimmungRechenumgebung: z('laufzeit')
  };
}

/** Nach dem Neustart: Spracherkennung und Sprechererkennung laden (nur mit Zustimmung). */
export function mitschriftPlanen(o: {
  zustimmung: Zustimmung;
  stand: EinrichtungStand | null;
  hfSchluessel?: string;
}): EinrichtungModelle | null {
  const v = o.stand?.vorhanden;
  const whisper = !!o.zustimmung.whisper && !v?.whisper;
  const sprechertrennung = !!o.zustimmung.pyannote && !v?.pyannote;
  if (!whisper && !sprechertrennung) return null;
  const hf = (o.hfSchluessel ?? '').trim();
  return {
    zustimmung: true,
    sprachmodelle: [],
    whisper,
    sprechertrennung,
    hf_token: sprechertrennung && hf ? hf : null,
    hf_token_merken: true
  };
}

// ---------------------------------------------------------------- Einrichten

export function einrichtungsAuftraege(auftraege: Auftrag[]): Auftrag[] {
  return auftraege.filter((a) => a.art.startsWith('einrichtung_'));
}

/** Der jüngste Auftrag je Art (ein früherer, gescheiterter Versuch soll nicht stören). */
export function juengsteEinrichtungsAuftraege(auftraege: Auftrag[]): Auftrag[] {
  const jeArt: Record<string, Auftrag> = {};
  for (const a of einrichtungsAuftraege(auftraege)) {
    const bisher = jeArt[a.art];
    if (!bisher || bisher.erstellt <= a.erstellt) jeArt[a.art] = a;
  }
  return Object.values(jeArt).sort((a, b) => a.erstellt - b.erstellt);
}

/**
 * Ist die Sprechererkennung beim letzten Laden gescheitert? Dann darf der Zugangsschlüssel noch einmal
 * eingegeben werden – ein falscher blieb sonst gemerkt, und „Erneut versuchen“ scheiterte immer wieder.
 */
export function sprechererkennungGescheitert(auftraege: Auftrag[]): boolean {
  const letzter = juengsteEinrichtungsAuftraege(auftraege).find((a) => a.art === 'einrichtung_modelle');
  const teile = letzter?.angaben?.teile as Record<string, boolean> | undefined;
  return letzter?.status === 'fehler' && teile?.pyannote === false;
}

/** Laufen noch Einrichtungsaufträge (dann wird nicht neu gestartet)? */
export function einrichtungLaeuft(auftraege: Auftrag[]): boolean {
  return einrichtungsAuftraege(auftraege).some((a) => !ERLEDIGT.has(a.status));
}

/** Darf jetzt neu gestartet werden? Nur, wenn nötig und nichts mehr lädt. */
export function neustartMoeglich(stand: EinrichtungStand | null, auftraege: Auftrag[]): boolean {
  return !!stand?.neustart_noetig && !einrichtungLaeuft(auftraege);
}

// ---------------------------------------------------------------- Zahlen in Worten

/** „1,2 GB“, „350 MB“ */
export function gbText(gb: number): string {
  if (gb < 1) return `${Math.max(10, Math.round((gb * 1000) / 10) * 10)} MB`;
  return `${(Math.round(gb * 10) / 10).toFixed(1).replace('.', ',').replace(',0', '')} GB`;
}

/** „ca. 20 Minuten“ / „ca. 1–2 Stunden“ */
export function downloadDauerText(von: number, bis: number): string {
  if (bis < 1) return 'unter einer Minute';
  if (bis >= 90) return spanne(von / 60, bis / 60, 'Stunden', 'Stunde');
  return spanne(von, bis, 'Minuten', 'Minute');
}
