/** Hell, Dunkel oder wie das System. Gemerkt im Browser-Speicher (kann fehlen oder gesperrt sein). */

export type Thema = 'system' | 'hell' | 'dunkel';
const SCHLUESSEL = 'vermerk.thema';

function lesen(): Thema {
  try {
    const wert = localStorage.getItem(SCHLUESSEL);
    if (wert === 'hell' || wert === 'dunkel' || wert === 'system') return wert;
  } catch {
    // privater Modus oder gesperrter Speicher
  }
  return 'system';
}

function anwenden(thema: Thema): void {
  const wurzel = document.documentElement;
  if (thema === 'system') wurzel.removeAttribute('data-theme');
  else wurzel.setAttribute('data-theme', thema);
}

class ThemaSpeicher {
  wahl = $state<Thema>('system');

  laden(): void {
    this.wahl = lesen();
    anwenden(this.wahl);
  }

  setzen(thema: Thema): void {
    this.wahl = thema;
    anwenden(thema);
    try {
      localStorage.setItem(SCHLUESSEL, thema);
    } catch {
      // nicht speicherbar: gilt dann nur bis zum Schließen
    }
  }
}

export const thema = new ThemaSpeicher();
