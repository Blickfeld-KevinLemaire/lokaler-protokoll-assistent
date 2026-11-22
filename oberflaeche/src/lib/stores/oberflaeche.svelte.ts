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
  /** Z. B. „Rückgängig“ – ein Knopf in der Meldung. */
  aktion?: { text: string; tun: () => void };
}

const HOECHSTENS = 3;

class Meldungen {
  liste = $state<Meldung[]>([]);
  private nr = 0;
  private zeitgeber = new Map<number, ReturnType<typeof setTimeout>>();

  zeigen(text: string, art: Meldung['art'] = 'ok', dauerMs = 5000, aktion?: Meldung['aktion']): number {
    const nr = ++this.nr;
    this.liste = [...this.liste, { nr, text, art, aktion }].slice(-HOECHSTENS);
    this.zeitgeber.set(
      nr,
      setTimeout(() => this.entfernen(nr), dauerMs)
    );
    return nr;
  }

  /** Solange der Mauszeiger oder der Fokus auf der Meldung liegt, bleibt sie stehen. */
  anhalten(nr: number): void {
    clearTimeout(this.zeitgeber.get(nr));
    this.zeitgeber.delete(nr);
  }

  weiter(nr: number, dauerMs = 3000): void {
    if (this.zeitgeber.has(nr) || !this.liste.some((m) => m.nr === nr)) return;
    this.zeitgeber.set(
      nr,
      setTimeout(() => this.entfernen(nr), dauerMs)
    );
  }

  entfernen(nr: number): void {
    clearTimeout(this.zeitgeber.get(nr));
    this.zeitgeber.delete(nr);
    this.liste = this.liste.filter((m) => m.nr !== nr);
  }
}

export const meldungen = new Meldungen();

/**
 * Grobe Uhr für Restzeiten und „vor 3 Minuten“: tickt nur alle 5 Sekunden, damit Restzeit und Fertigzeit
 * ruhig bleiben (Zählerwerte, die jede Sekunde springen, lenken ab).
 */
export const UHR_TAKT_MS = 5000;

class Uhr {
  jetzt = $state(Date.now());
  private zeitgeber: ReturnType<typeof setInterval> | null = null;

  starten(): void {
    if (this.zeitgeber) return;
    this.zeitgeber = setInterval(() => (this.jetzt = Date.now()), UHR_TAKT_MS);
  }
}

export const uhr = new Uhr();

export interface Frage {
  titel: string;
  text?: string;
  /** Was der Knopf tut, z. B. „Löschen“, „Entfernen“. */
  verb: string;
}

/**
 * Rückfrage nur für Unwiderrufliches (Ersatz für `confirm()`): ein Dialog in der Oberfläche, Fokus auf
 * „Abbrechen“. `fragen()` liefert `true`, wenn bestätigt.
 */
class Rueckfrage {
  frage = $state<Frage | null>(null);
  private antworten: ((ja: boolean) => void) | null = null;

  fragen(frage: Frage): Promise<boolean> {
    this.antworten?.(false);
    this.frage = frage;
    return new Promise((erfuellen) => (this.antworten = erfuellen));
  }

  antworten_(ja: boolean): void {
    const a = this.antworten;
    this.antworten = null;
    this.frage = null;
    a?.(ja);
  }
}

export const rueckfrage = new Rueckfrage();
