/** Kleine Zustände der Oberfläche: Fehlerdialog, kurze Meldungen, laufende Uhr. */
import { fehlerFuerDialog, type DialogFehler } from '../logik/fehler';

class Dialog {
  fehler = $state<DialogFehler | null>(null);

  zeigen(fehler: unknown, titel?: string): void {
    this.fehler = fehlerFuerDialog(fehler, titel);
  }

  schliessen(): void {
    this.fehler = null;
  }
}

export const dialog = new Dialog();

export interface Meldung {
  nr: number;
  text: string;
  art: 'ok' | 'info' | 'fehler';
}

class Meldungen {
  liste = $state<Meldung[]>([]);
  private nr = 0;

  zeigen(text: string, art: Meldung['art'] = 'ok', dauerMs = 5000): void {
    const nr = ++this.nr;
    this.liste = [...this.liste, { nr, text, art }];
    setTimeout(() => this.entfernen(nr), dauerMs);
  }

  entfernen(nr: number): void {
    this.liste = this.liste.filter((m) => m.nr !== nr);
  }
}

export const meldungen = new Meldungen();

class Uhr {
  jetzt = $state(Date.now());
  private zeitgeber: ReturnType<typeof setInterval> | null = null;

  starten(): void {
    if (this.zeitgeber) return;
    this.zeitgeber = setInterval(() => (this.jetzt = Date.now()), 1000);
  }
}

export const uhr = new Uhr();
