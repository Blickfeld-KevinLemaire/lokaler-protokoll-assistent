/**
 * Wie im Windows-Explorer: Ein Klick auf den Namen des schon ausgewählten Eintrags benennt ihn um – aber erst nach
 * einer kurzen Pause. Kommt vorher ein zweiter Klick (Doppelklick), passiert das nicht.
 */
export const UMBENENNEN_NACH_MS = 500;

export class VerzoegerterKlick {
  private zeitgeber: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly ms = UMBENENNEN_NACH_MS) {}

  /** `ausloesen` läuft nach der Pause, falls bis dahin nicht `abbrechen` kommt. */
  klick(ausloesen: () => void): void {
    this.abbrechen();
    this.zeitgeber = setTimeout(() => {
      this.zeitgeber = null;
      ausloesen();
    }, this.ms);
  }

  abbrechen(): void {
    if (this.zeitgeber !== null) clearTimeout(this.zeitgeber);
    this.zeitgeber = null;
  }

  get wartet(): boolean {
    return this.zeitgeber !== null;
  }
}
