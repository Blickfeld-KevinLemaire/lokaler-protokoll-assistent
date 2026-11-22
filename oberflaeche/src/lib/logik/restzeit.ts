/**
 * Restzeit aus Fortschritt und Startzeit: Rest = vergangen × (1 − p) / p, geglättet.
 * Angezeigt wird erst ab p ≥ 0,05 oder nach 20 s – vorher springt die Schätzung zu stark.
 *
 * Alle Zeiten des Dienstes (`gestartet`) zählen nach SEINER Uhr. Die Oberfläche kann auf einem anderen
 * Rechner laufen; deshalb rechnet sie mit `jetztDienst` (eigene Uhr + Versatz aus `/api/zustand`) und
 * gibt die Fertigzeit wieder in der eigenen Uhr aus.
 */

export const MIN_ANTEIL = 0.05;
export const MIN_SEKUNDEN = 20;
const GLAETTUNG = 0.25;
/** Darunter heißt es nur noch „gleich fertig“. */
const GLEICH_FERTIG_S = 45;

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

/** „noch etwa 4 Min.“ – mit `kurz` ohne „etwa“ (für die schmale Seitenleiste). */
export function restzeitText(sekunden: number | null, kurz = false): string {
  if (sekunden === null || !Number.isFinite(sekunden)) return '';
  if (sekunden < GLEICH_FERTIG_S) return 'gleich fertig';
  const noch = kurz ? 'noch' : 'noch etwa';
  const minuten = Math.round(sekunden / 60);
  if (minuten < 90) return `${noch} ${Math.max(1, minuten)} Min.`;
  const stunden = Math.round((sekunden / 3600) * 2) / 2;
  return `${noch} ${String(stunden).replace('.', ',')} Std.`;
}

/**
 * „fertig gegen 14:35“ in der Uhr dieses Rechners. Gerundet: ab 20 Minuten Rest auf 5 Minuten, darunter auf
 * die Minute – so springt die Uhrzeit nicht bei jeder neuen Schätzung.
 */
export function fertigText(sekunden: number | null, jetztLokalMs: number): string {
  if (sekunden === null || !Number.isFinite(sekunden) || sekunden < GLEICH_FERTIG_S) return '';
  const schritt = sekunden >= 20 * 60 ? 5 * 60_000 : 60_000;
  const ziel = new Date(Math.round((jetztLokalMs + sekunden * 1000) / schritt) * schritt);
  const zeit = ziel.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  const heute = new Date(jetztLokalMs).toDateString() === ziel.toDateString();
  return heute ? `fertig gegen ${zeit}` : `fertig morgen gegen ${zeit}`;
}

export interface Zeiten {
  /** Geschätzte Restsekunden oder `null` (noch keine Schätzung). */
  rest: number | null;
  /** „noch etwa 4 Min.“ */
  text: string;
  /** „noch 4 Min.“ */
  kurz: string;
  /** „fertig gegen 14:35“ */
  fertig: string;
}

const schaetzerJeAuftrag = new Map<string, RestzeitSchaetzer>();

/**
 * Restzeit und Fertigzeit für einen laufenden Auftrag; die Glättung bleibt je Auftrag erhalten.
 * `jetztDienst` in Sekunden nach der Uhr des Dienstes, `jetztLokalMs` nach der eigenen Uhr.
 */
export function zeitenFuerAuftrag(
  id: string,
  anteil: number | null | undefined,
  gestartet: number | null | undefined,
  jetztDienst: number,
  jetztLokalMs: number
): Zeiten {
  let s = schaetzerJeAuftrag.get(id);
  if (!s) {
    if (schaetzerJeAuftrag.size > 20) schaetzerJeAuftrag.clear();
    s = new RestzeitSchaetzer();
    schaetzerJeAuftrag.set(id, s);
  }
  const rest = s.schaetzen(anteil, gestartet, jetztDienst);
  return {
    rest,
    text: restzeitText(rest),
    kurz: restzeitText(rest, true),
    fertig: fertigText(rest, jetztLokalMs)
  };
}

/** Versatz der Uhren in Sekunden: Uhr des Dienstes minus eigene Uhr. */
export function uhrVersatz(jetztDienst: number | null | undefined, jetztLokalMs: number): number {
  if (jetztDienst == null || !Number.isFinite(jetztDienst)) return 0;
  return jetztDienst - jetztLokalMs / 1000;
}
