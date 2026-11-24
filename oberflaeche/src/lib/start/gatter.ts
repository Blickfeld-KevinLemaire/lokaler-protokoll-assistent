/**
 * Das EINE Startgatter. Vorher gibt es keine Anfrage, kein Abo, kein Abfragen.
 *
 * Tauri-Fenster: Basis-URL und Schlüssel kommen vom Befehl `zugang`. Der Port wird bei jedem Start des
 * Dienstes neu vergeben – deshalb wird er nie über einen Neustart hinweg behalten: Bei `neustart` schließt
 * das Gatter (laufende Anfragen brechen ab), bei `bereit` wird `zugang` neu gefragt.
 *
 * Browser: gleiche Herkunft und Sitzungs-Cookie; 401 heißt „Anmeldung zeigen“.
 */
import { api, GatterGeschlossen, NichtAngemeldet, zugangSetzen, zugangSperren } from '../api/client';
import type { Anmeldedaten, Info } from '../api/typen';
import type { DienstStatus, Huelle } from '../tauri';

export type Phase = 'startet' | 'bereit' | 'neustart' | 'fehlgeschlagen' | 'anmelden' | 'getrennt';

export interface GatterOptionen {
  /** `null`: Browser (gleiche Herkunft). */
  huelle: Huelle | null;
  /** Nach dem Öffnen: Zustand laden, Ereignisse abonnieren. */
  beiOffen: (info: Info) => Promise<void> | void;
  /** Vor dem Schließen: Ereignisstrom beenden usw. */
  beiZu: () => void;
  beiPhase: (phase: Phase, meldung: string) => void;
  /** Im Test ersetzbar. */
  warten?: (ms: number) => Promise<void>;
  wiederholenMs?: number;
}

const standardWarten = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export class Startgatter {
  private lauf = 0;
  private abmelden: (() => void) | null = null;
  private phase: Phase = 'startet';
  private schluesselFehler = 0;

  constructor(private readonly o: GatterOptionen) {}

  get aktuellePhase(): Phase {
    return this.phase;
  }

  private setzen(phase: Phase, meldung = ''): void {
    this.phase = phase;
    this.o.beiPhase(phase, meldung);
  }

  async starten(): Promise<void> {
    if (this.o.huelle) {
      this.abmelden = await this.o.huelle.dienstStatusHoeren((s) => this.dienstStatus(s));
    }
    await this.oeffnen();
  }

  beenden(): void {
    this.lauf++;
    this.abmelden?.();
    this.abmelden = null;
    this.schliessen();
  }

  /** Gatter schließen: keine Anfragen mehr, Strom zu. */
  schliessen(): void {
    this.o.beiZu();
    zugangSperren();
  }

  dienstStatus(s: DienstStatus): void {
    switch (s.zustand) {
      case 'startet':
        if (this.phase !== 'bereit') this.setzen('startet', s.meldung);
        break;
      case 'neustart':
        this.lauf++;
        this.schliessen();
        this.setzen('neustart', s.meldung);
        break;
      case 'fehlgeschlagen':
        this.lauf++;
        this.schliessen();
        this.setzen('fehlgeschlagen', s.meldung);
        break;
      case 'bereit':
        // Immer neu fragen: Der Port kann sich geändert haben (basis_url im Ereignis nur als Hinweis).
        this.schliessen();
        void this.oeffnen();
        break;
    }
  }

  /** Browser: nach erfolgreicher Anmeldung erneut öffnen. */
  async anmelden(daten: Anmeldedaten): Promise<void> {
    await api.anmelden(daten);
    await this.oeffnen();
  }

  /** Die Anmeldung ist abgelaufen oder der Schlüssel passt nicht mehr. */
  nichtAngemeldet(): void {
    if (this.o.huelle) {
      // Im Fenster gibt es keine Anmeldung: Schlüssel neu holen (der Dienst kann neu gestartet sein).
      this.schluesselFehler++;
      this.schliessen();
      if (this.schluesselFehler > 2) {
        this.setzen('fehlgeschlagen', 'Der Dienst lehnt die Verbindung ab.');
        return;
      }
      void this.oeffnen();
      return;
    }
    this.lauf++;
    this.schliessen();
    zugangSetzen({ basisUrl: '', schluessel: null }); // für /api/anmelden
    this.setzen('anmelden');
  }

  async oeffnen(): Promise<void> {
    const meinLauf = ++this.lauf;
    const warten = this.o.warten ?? standardWarten;
    const abstand = this.o.wiederholenMs ?? 2000;
    if (this.phase !== 'neustart' && this.phase !== 'anmelden') this.setzen('startet');
    for (let versuch = 0; ; versuch++) {
      if (meinLauf !== this.lauf) return;
      try {
        if (this.o.huelle) {
          const z = await this.o.huelle.zugangHolen();
          if (meinLauf !== this.lauf) return;
          zugangSetzen({ basisUrl: z.basis_url, schluessel: z.schluessel });
        } else {
          zugangSetzen({ basisUrl: '', schluessel: null });
        }
        const info = await api.info();
        if (meinLauf !== this.lauf) return;
        this.schluesselFehler = 0;
        await this.o.beiOffen(info);
        if (meinLauf !== this.lauf) return;
        this.setzen('bereit');
        return;
      } catch (fehler) {
        if (meinLauf !== this.lauf) return;
        if (fehler instanceof NichtAngemeldet) {
          if (!this.o.huelle) {
            this.setzen('anmelden');
            return;
          }
          this.schluesselFehler++;
          if (this.schluesselFehler > 2) {
            this.schliessen();
            this.setzen('fehlgeschlagen', 'Der Dienst lehnt die Verbindung ab.');
            return;
          }
        }
        if (!(fehler instanceof GatterGeschlossen)) zugangSperren();
        // Dienst noch nicht da (Fenster: wartet auf „bereit“, fragt aber auch selbst nach).
        if (!this.o.huelle && versuch > 0) this.setzen('getrennt');
      }
      await warten(Math.min(abstand * (1 + versuch), 10_000));
    }
  }
}
