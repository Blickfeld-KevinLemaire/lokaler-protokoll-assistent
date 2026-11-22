/**
 * Tastenkürzel der ganzen Oberfläche: Strg+N neue Transkription, Strg+, Einstellungen, „/“ Suche in den
 * Besprechungen. Esc schließen Dialoge (<dialog>) und Blasen selbst.
 */

export type Kuerzel = 'neu' | 'einstellungen' | 'suche';

/** Für die Tooltips (title) der Knöpfe. */
export const KUERZEL_TEXT: Record<Kuerzel, string> = {
  neu: 'Strg+N',
  einstellungen: 'Strg+,',
  suche: '/'
};

function inEingabe(ziel: EventTarget | null): boolean {
  if (!ziel || typeof (ziel as HTMLElement).closest !== 'function') return false;
  const el = ziel as HTMLElement;
  return !!el.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""]');
}

export function tastenkuerzel(
  e: Pick<
    KeyboardEvent,
    'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey' | 'target' | 'defaultPrevented'
  >
): Kuerzel | null {
  if (e.defaultPrevented || e.altKey) return null;
  const strg = e.ctrlKey || e.metaKey;
  if (strg && !e.shiftKey && e.key.toLowerCase() === 'n') return 'neu';
  if (strg && e.key === ',') return 'einstellungen';
  if (!strg && !e.shiftKey && e.key === '/' && !inEingabe(e.target)) return 'suche';
  return null;
}
