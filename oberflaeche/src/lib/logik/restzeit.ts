/**
 * Restzeit aus Fortschritt und Startzeit: Rest = vergangen × (1 − p) / p, geglättet.
 * Angezeigt wird erst ab p ≥ 0,05 oder nach 20 s – vorher springt die Schätzung zu stark.
 */

export const MIN_ANTEIL = 0.05;
export const MIN_SEKUNDEN = 20;
const GLAETTUNG = 0.25;

export function rohRestzeit(anteil: number, vergangen: number): number | null {
  if (!(anteil > 0) || anteil >= 1 || vergangen <= 0) return anteil >= 1 ? 0 : null;
  if (anteil < MIN_ANTEIL && vergangen < MIN_SEKUNDEN) return null;
  return (vergangen * (1 - anteil)) / anteil;
}

/** Glättet die geschätzte Gesamtdauer (stabiler als die Restzeit selbst) und zählt dazwischen herunter. */
export class RestzeitSchaetzer {
  private gesamt: number | null = null;
  private letzterAnteil = -1;

  schaetzen(
    anteil: number | null | undefined,
    gestartet: number | null | undefined,
    jetzt: number
  ): number | null {
    if (anteil == null || gestartet == null) return null;
    const vergangen = Math.max(0, jetzt - gestartet);
    const roh = rohRestzeit(anteil, vergangen);
    if (roh === null) return null;
    if (anteil !== this.letzterAnteil) {
      const neuGesamt = vergangen + roh;
      this.gesamt = this.gesamt === null ? neuGesamt : this.gesamt + GLAETTUNG * (neuGesamt - this.gesamt);
      this.letzterAnteil = anteil;
    }
    return Math.max(0, (this.gesamt ?? vergangen + roh) - vergangen);
  }

  zuruecksetzen(): void {
    this.gesamt = null;
    this.letzterAnteil = -1;
  }
}

export function restzeitText(sekunden: number | null): string {
  if (sekunden === null || !Number.isFinite(sekunden)) return '';
  if (sekunden < 45) return 'gleich fertig';
  const minuten = Math.round(sekunden / 60);
  if (minuten < 90) return `noch etwa ${Math.max(1, minuten)} Min.`;
  const stunden = Math.round((sekunden / 3600) * 2) / 2;
  return `noch etwa ${String(stunden).replace('.', ',')} Std.`;
}

const schaetzerJeAuftrag = new Map<string, RestzeitSchaetzer>();

/** Restzeit-Text für einen laufenden Auftrag; die Glättung bleibt je Auftrag erhalten. */
export function restzeitFuerAuftrag(
  id: string,
  anteil: number | null | undefined,
  gestartet: number | null | undefined,
  jetzt: number
): string {
  let s = schaetzerJeAuftrag.get(id);
  if (!s) {
    if (schaetzerJeAuftrag.size > 20) schaetzerJeAuftrag.clear();
    s = new RestzeitSchaetzer();
    schaetzerJeAuftrag.set(id, s);
  }
  return restzeitText(s.schaetzen(anteil, gestartet, jetzt));
}
