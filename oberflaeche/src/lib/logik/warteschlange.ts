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
    .filter((a) => ERLEDIGT.has(a.status))
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

/** Kurzer Text nach dem Start, wenn schon etwas läuft oder wartet. */
export function startHinweis(auftraege: Auftrag[], id: string): string | null {
  const platz = platzInReihe(auftraege, id);
  if (platz === null || platz <= 1) return null;
  return `Startet nach der laufenden Verarbeitung (Platz ${platz})`;
}

export interface Herkunft {
  symbol: string;
  text: string;
}

/** `oberflaeche` → PC, `geraet:<Name>` → Gerät, `ordner…`/`eingang…` → Eingangsordner. */
export function herkunftAnzeigen(herkunft: string): Herkunft {
  if (herkunft.startsWith('geraet:')) return { symbol: '📡', text: herkunft.slice(7) || 'Gerät' };
  if (herkunft.startsWith('ordner') || herkunft.startsWith('eingang'))
    return { symbol: '📁', text: 'Ordner' };
  return { symbol: '💻', text: 'PC' };
}

/** Anzeigename eines Auftrags ohne Dateiendung und ohne technische Namensteile. */
export function auftragTitel(a: Auftrag): string {
  if (a.art === 'modell_laden') return 'Sprachmodell herunterladen';
  let titel = a.titel.replace(/\.[a-z0-9]{2,5}$/i, '');
  titel = titel.replace(/_lokal_transkript_\d{8}_\d{6}(_\d+)?$/, '');
  if (a.art === 'auswertung') return `Zusammenfassung: ${titel}`;
  return titel;
}
