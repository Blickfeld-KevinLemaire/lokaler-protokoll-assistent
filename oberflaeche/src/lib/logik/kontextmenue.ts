/** Kontextmenü: Einträge, Tastaturführung und Lage im Fenster (ohne Oberfläche, damit testbar). */
import type { Component } from 'svelte';

export interface MenuePunkt {
  id: string;
  text: string;
  symbol?: Component<{ size?: number }>;
  /** Angezeigtes Kürzel, z. B. „Entf“. */
  kuerzel?: string;
  /** Dasselbe für Bildschirmleser (`aria-keyshortcuts`), z. B. „Delete“. */
  taste?: string;
  /** Sichtbar, aber nicht wählbar – `hinweis` sagt, warum. */
  deaktiviert?: boolean;
  hinweis?: string;
  /** Rot: z. B. „Löschen“. */
  gefahr?: boolean;
  /** Trennlinie vor diesem Eintrag. */
  trenner?: boolean;
}

/** Nächster Eintrag in `richtung` (1 oder -1), am Ende wieder von vorn. `-1` bzw. `punkte.length` als Start. */
export function naechster(anzahl: number, aktuell: number, richtung: 1 | -1): number {
  if (anzahl <= 0) return -1;
  return (((aktuell + richtung) % anzahl) + anzahl) % anzahl;
}

/** Der nächste Eintrag nach `aktuell`, dessen Text mit `zeichen` beginnt (Tippen springt dorthin). */
export function perAnfangsbuchstabe(punkte: MenuePunkt[], aktuell: number, zeichen: string): number {
  const z = zeichen.toLocaleLowerCase('de-DE');
  for (let schritt = 1; schritt <= punkte.length; schritt++) {
    const i = (aktuell + schritt) % punkte.length;
    if (punkte[i]!.text.toLocaleLowerCase('de-DE').startsWith(z)) return i;
  }
  return aktuell;
}

export const RAND = 8;

/**
 * Wo das Menü stehen soll: an der Maus (bzw. unter dem Eintrag), aber ganz im Fenster. Passt es rechts oder unten
 * nicht mehr hin, klappt es nach links bzw. oben auf.
 */
export function imFenster(
  x: number,
  y: number,
  breite: number,
  hoehe: number,
  fensterBreite: number,
  fensterHoehe: number
): { links: number; oben: number } {
  let links = x + breite + RAND > fensterBreite ? x - breite : x;
  let oben = y + hoehe + RAND > fensterHoehe ? y - hoehe : y;
  links = Math.max(RAND, Math.min(links, fensterBreite - breite - RAND));
  oben = Math.max(RAND, Math.min(oben, fensterHoehe - hoehe - RAND));
  return { links, oben };
}

/** Öffnet die Taste das Kontextmenü? (Menü-Taste oder Umschalt+F10, wie überall unter Windows.) */
export function oeffnetMenue(
  e: Pick<KeyboardEvent, 'key' | 'shiftKey' | 'ctrlKey' | 'altKey' | 'metaKey'>
): boolean {
  if (e.ctrlKey || e.altKey || e.metaKey) return false;
  return e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10');
}
