/** Die eine Warteschlange des Dienstes, so aufbereitet, wie die Oberfläche sie zeigt. */
import type { Auftrag } from '../api/typen';

export const ERLEDIGT = new Set(['fertig', 'fehler', 'abgebrochen']);

/** Wie der Dienst wählt: höherer Vorrang zuerst, bei gleichem Vorrang der ältere. */
export function wartendeSortieren(auftraege: Auftrag[]): Auftrag[] {
  return auftraege
    .filter((a) => a.status === 'wartet')
    .sort((a, b) => b.vorrang - a.vorrang || a.erstellt - b.erstellt);
}

export interface Lage {
  laufend: Auftrag | null;
  wartend: Auftrag[];
  zuletztErledigt: Auftrag | null;
}

export function lageErmitteln(auftraege: Auftrag[]): Lage {
  const laufend = auftraege.find((a) => a.status === 'laeuft') ?? null;
  const erledigt = auftraege
    .filter((a) => ERLEDIGT.has(a.status) && !a.fremd)
    .sort((a, b) => (b.beendet ?? 0) - (a.beendet ?? 0));
  return { laufend, wartend: wartendeSortieren(auftraege), zuletztErledigt: erledigt[0] ?? null };
}

/** Platz in der Reihe (1 = läuft gerade bzw. ist als Nächstes dran); `null`, wenn nicht wartend/laufend. */
export function platzInReihe(auftraege: Auftrag[], id: string): number | null {
  const { laufend, wartend } = lageErmitteln(auftraege);
  if (laufend?.id === id) return 1;
  const index = wartend.findIndex((a) => a.id === id);
  if (index < 0) return null;
  return index + 1 + (laufend ? 1 : 0);
}

/**
 * Kurzer Text nach dem Start aus `platz` der Antwort (Zahl der Aufträge davor; 0 = startet sofort bzw.
 * als Nächstes).
 */
export function startHinweisAusPlatz(platz: number | null | undefined): string | null {
  if (platz == null || platz <= 0) return null;
  return `Startet nach der laufenden Verarbeitung (Platz ${platz + 1})`;
}

/** Kurzer Text nach dem Start, wenn schon etwas läuft oder wartet (aus der eigenen Liste errechnet). */
export function startHinweis(auftraege: Auftrag[], id: string): string | null {
  const platz = platzInReihe(auftraege, id);
  if (platz === null || platz <= 1) return null;
  return `Startet nach der laufenden Verarbeitung (Platz ${platz})`;
}

export type HerkunftArt = 'pc' | 'geraet' | 'ordner' | 'andere';

export interface Herkunft {
  /** Welches Symbol die Oberfläche zeigt (siehe komponenten/HerkunftSymbol.svelte). */
  art: HerkunftArt;
  text: string;
}

/** `oberflaeche` → PC, `geraet:<Name>` → Gerät, `ordner…`/`eingang…` → Eingangsordner. */
export function herkunftAnzeigen(herkunft: string): Herkunft {
  if (herkunft === 'andere') return { art: 'andere', text: 'Andere' };
  if (herkunft.startsWith('geraet:')) return { art: 'geraet', text: herkunft.slice(7) || 'Gerät' };
  if (herkunft.startsWith('ordner') || herkunft.startsWith('eingang'))
    return { art: 'ordner', text: 'Ordner' };
  return { art: 'pc', text: 'PC' };
}

/** Titel der Aufträge der Ersteinrichtung (`einrichtung_*`). */
export const EINRICHTUNG_TITEL: Record<string, string> = {
  einrichtung_ffmpeg: 'Werkzeug für Aufnahmen einrichten',
  einrichtung_ollama: 'KI-Umgebung einrichten',
  einrichtung_modelle: 'KI-Bausteine laden'
};

/** Anzeigename eines Auftrags ohne Dateiendung und ohne technische Namensteile. */
export function auftragTitel(a: Auftrag): string {
  if (a.fremd) return 'Andere Verarbeitung';
  if (a.art === 'modell_laden') return 'Sprachmodell herunterladen';
  if (a.art.startsWith('einrichtung_')) return EINRICHTUNG_TITEL[a.art] ?? 'Einrichtung';
  let titel = a.titel.replace(/\.[a-z0-9]{2,5}$/i, '');
  titel = titel.replace(/_lokal_transkript_\d{8}_\d{6}(_\d+)?$/, '');
  if (a.art === 'auswertung') return `Zusammenfassung: ${titel}`;
  return titel;
}

/**
 * Hinweis zu einem fertigen Auftrag, dem etwas fehlt: Die Sprechertrennung kann scheitern (Zugang zum Modell
 * fehlt, zu wenig Speicher), der Text entsteht dann trotzdem – nur ohne Sprecher. `null`, wenn alles da ist.
 */
export function auftragHinweis(a: Auftrag): string | null {
  if (a.status !== 'fertig' || !a.ergebnis?.diarisierung_fehler) return null;
  return 'Die Sprecher ließen sich nicht unterscheiden. Der Text ist vollständig, aber ohne Sprecher.';
}

/** Meldung nach dem Start: bevorzugt `platz` aus der Antwort, sonst aus der eigenen Liste. */
export function startMeldung(auftrag: Auftrag, auftraege: Auftrag[]): string | null {
  if (auftrag.platz !== undefined && auftrag.platz !== null) return startHinweisAusPlatz(auftrag.platz);
  return startHinweis(auftraege, auftrag.id);
}
