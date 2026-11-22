/** Einstellungen des Dienstes; neu geladen, wenn das Ereignis `einstellungen` kommt. */
import { api } from '../api/client';
import type { Einstellungen, SchluesselStand } from '../api/typen';

class EinstellungsSpeicher {
  werte = $state<Einstellungen | null>(null);
  schluessel = $state<SchluesselStand | null>(null);

  async laden(): Promise<void> {
    const [werte, schluessel] = await Promise.all([api.einstellungen(), api.schluesselStand()]);
    this.werte = werte;
    this.schluessel = schluessel;
  }

  async aendern(aenderungen: Partial<Einstellungen>): Promise<void> {
    const vorher = this.werte;
    if (vorher) this.werte = { ...vorher, ...aenderungen };
    try {
      this.werte = await api.einstellungenAendern(aenderungen);
    } catch (fehler) {
      this.werte = vorher;
      throw fehler;
    }
  }

  async schluesselNeu(): Promise<void> {
    this.schluessel = await api.schluesselStand();
  }

  /** Läuft alles auf diesem Computer? (für das Schloss-Symbol im Kopf) */
  get lokal(): boolean {
    const w = this.werte;
    return (
      !!w && w.transkription_modus !== 'api' && w.nachbearbeitung_modus !== 'api' && w.chatbot_modus !== 'api'
    );
  }
}

export const einstellungen = new EinstellungsSpeicher();
