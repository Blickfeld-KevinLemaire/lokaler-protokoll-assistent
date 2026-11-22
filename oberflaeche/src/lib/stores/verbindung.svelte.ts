/**
 * Verbindung zum Dienst: Startgatter, Zustand, Ereignisstrom. Seiten fragen erst, wenn `phase === 'bereit'`.
 */
import { api, nichtAngemeldetMelden } from '../api/client';
import { ereignisseAbonnieren, type Abo, type StromZustand } from '../api/ereignisstrom';
import type { Anmeldedaten, Info } from '../api/typen';
import { Startgatter, type Phase } from '../start/gatter';
import { istTauri, tauriHuelle } from '../tauri';
import { einstellungen } from './einstellungen.svelte';
import { zustand } from './zustand.svelte';

class Verbindung {
  phase = $state<Phase>('startet');
  meldung = $state('');
  info = $state<Info | null>(null);
  strom = $state<StromZustand>('beendet');
  tauri = $state(false);
  /** Steigt bei jedem Öffnen des Gatters: Seiten laden dann ihre Daten neu. */
  runde = $state(0);

  private gatter: Startgatter | null = null;
  private abo: Abo | null = null;

  get bereit(): boolean {
    return this.phase === 'bereit';
  }

  async starten(): Promise<void> {
    if (this.gatter) return;
    this.tauri = istTauri();
    this.gatter = new Startgatter({
      huelle: this.tauri ? tauriHuelle() : null,
      beiOffen: (info) => this.offen(info),
      beiZu: () => this.zu(),
      beiPhase: (phase, meldung) => {
        this.phase = phase;
        this.meldung = meldung;
      }
    });
    nichtAngemeldetMelden(() => this.gatter?.nichtAngemeldet());
    await this.gatter.starten();
  }

  async anmelden(daten: Anmeldedaten): Promise<void> {
    await this.gatter?.anmelden(daten);
  }

  /** Mehrere Nutzer (Servermodus)? Dann gibt es Konto, Teilen und fremde Aufträge. */
  get mehrbenutzer(): boolean {
    return !!this.info?.mehrbenutzer;
  }

  /** Darf Einstellungen, Geräte, Vorlagen ändern (Windows-Anwendung: immer). */
  get verwalten(): boolean {
    return !this.info?.mehrbenutzer || !!this.info.admin;
  }

  async abmelden(): Promise<void> {
    try {
      await api.abmelden();
    } finally {
      this.gatter?.nichtAngemeldet();
    }
  }

  private async offen(info: Info): Promise<void> {
    this.info = info;
    await this.zustandLaden();
    void einstellungen.laden().catch((e) => console.warn('Einstellungen nicht geladen', e));
    this.runde++;
  }

  private async zustandLaden(): Promise<void> {
    this.abo?.beenden();
    const stand = await api.zustand();
    zustand.uebernehmen(stand);
    if (this.info?.faehigkeiten.mikrofon && this.info.rolle === 'desktop') {
      zustand.aufnahme = await api.aufnahme().catch(() => null);
    }
    this.abo = ereignisseAbonnieren({
      seit: stand.letzte_nummer,
      beiEreignis: (e) => {
        if (e.art === 'neu_laden') {
          void this.zustandLaden().catch((f) => console.warn('Zustand nicht geladen', f));
          return;
        }
        zustand.ereignis(e);
        if (e.art === 'einstellungen') void einstellungen.laden().catch(() => undefined);
      },
      beiZustand: (z) => (this.strom = z),
      beiAbmeldung: () => this.gatter?.nichtAngemeldet()
    });
  }

  private zu(): void {
    this.abo?.beenden();
    this.abo = null;
    this.strom = 'beendet';
  }
}

export const verbindung = new Verbindung();
