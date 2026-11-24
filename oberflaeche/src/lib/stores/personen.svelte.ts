/** Anzeigenamen der Nutzer (Servermodus) – für „geteilt von …“ und den Teilen-Dialog. */
import { api } from '../api/client';
import type { NutzerName } from '../api/typen';

class Personen {
  liste = $state<NutzerName[]>([]);
  private geladen = false;

  async laden(neu = false): Promise<void> {
    if (this.geladen && !neu) return;
    this.geladen = true;
    try {
      this.liste = await api.nutzerNamen();
    } catch (e) {
      this.geladen = false;
      console.warn('Namen nicht geladen', e);
    }
  }

  anzeigename(name: string | null | undefined): string {
    if (!name) return '';
    return this.liste.find((p) => p.name.toLowerCase() === name.toLowerCase())?.anzeigename ?? name;
  }
}

export const personen = new Personen();
