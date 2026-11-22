/** Laufender Stand aus `/api/zustand` plus den Ereignissen danach. */
import type {
  AufnahmeStand,
  Auftrag,
  Empfang,
  Ereignis,
  Freigabe,
  GeraetStatus,
  Hinweis,
  LiveText,
  Zustand
} from '../api/typen';
import { hinweisKurz, type KurzHinweis } from '../logik/hinweise';
import { uhrVersatz } from '../logik/restzeit';
import { lageErmitteln } from '../logik/warteschlange';

const INFO_HINWEIS_MS = 15_000;

export type AktiverHinweis = KurzHinweis & { schluessel: string; nr: number };
let hinweisNummer = 0;

class ZustandSpeicher {
  auftraege = $state<Auftrag[]>([]);
  empfang = $state<Empfang | null>(null);
  freigaben = $state<Freigabe[]>([]);
  hinweise = $state<AktiverHinweis[]>([]);
  geraeteStatus = $state<Record<string, GeraetStatus>>({});
  live = $state<Record<string, LiveText>>({});
  /** Zähler: steigt, wenn sich Dateien/Einstellungen/Besprechungen geändert haben (Seiten laden dann neu). */
  dateienStand = $state(0);
  einstellungenStand = $state(0);
  besprechungenStand = $state(0);
  /** Laufende Mikrofonaufnahme im Dienst (Windows-Anwendung) oder `null`. */
  aufnahme = $state<AufnahmeStand | null>(null);
  /** Letzte Fehlermeldung ohne Auftrag (Ereignis `fehler`). */
  fehlermeldung = $state<string | null>(null);
  /** Uhr des Dienstes minus eigene Uhr, in Sekunden (der Browser kann auf einem anderen Rechner laufen). */
  uhrVersatz = $state(0);

  lage = $derived(lageErmitteln(this.auftraege));

  zuruecksetzen(): void {
    this.auftraege = [];
    this.empfang = null;
    this.freigaben = [];
    this.hinweise = [];
    this.geraeteStatus = {};
    this.live = {};
    this.aufnahme = null;
  }

  uebernehmen(z: Zustand, jetztLokalMs = Date.now()): void {
    // Nur aus /api/zustand: Ereignisse können nachgeliefert sein (Wiederverbinden) und tragen dann alte Zeiten.
    this.uhrVersatz = uhrVersatz(z.jetzt, jetztLokalMs);
    this.auftraege = z.auftraege;
    this.empfang = z.empfang;
    this.freigaben = z.freigaben;
    this.besprechungenStand++;
    this.dateienStand++;
  }

  auftragAktualisieren(neu: Partial<Auftrag> & { id: string }): void {
    const index = this.auftraege.findIndex((a) => a.id === neu.id);
    if (index < 0) {
      this.auftraege = [...this.auftraege, { vorschau: '', meldungen: [], ...neu } as Auftrag];
      return;
    }
    const alt = this.auftraege[index]!;
    // Gedrosselte Meldungen lassen `vorschau` weg: dann bleibt die bisherige.
    const zusammen = { ...alt, ...neu, vorschau: 'vorschau' in neu ? (neu.vorschau ?? '') : alt.vorschau };
    if (alt.status !== 'fertig' && zusammen.status === 'fertig') this.besprechungenStand++;
    const liste = [...this.auftraege];
    liste[index] = zusammen as Auftrag;
    this.auftraege = liste;
  }

  hinweisSetzen(h: Hinweis): void {
    const schluessel = h.quelle || `text:${h.text}`;
    const ohne = this.hinweise.filter((x) => x.schluessel !== schluessel);
    if (h.stufe === 'erledigt' || !h.text) {
      this.hinweise = ohne;
      return;
    }
    const kurz: AktiverHinweis = { ...hinweisKurz(h), schluessel, nr: ++hinweisNummer };
    this.hinweise = [...ohne, kurz];
    if (kurz.stufe === 'info') {
      setTimeout(() => {
        this.hinweise = this.hinweise.filter((x) => x.nr !== kurz.nr);
      }, INFO_HINWEIS_MS);
    }
  }

  hinweisEntfernen(schluessel: string): void {
    this.hinweise = this.hinweise.filter((x) => x.schluessel !== schluessel);
  }

  ereignis(e: Ereignis): void {
    const d = e.daten as Record<string, unknown>;
    switch (e.art) {
      case 'auftrag':
        this.auftragAktualisieren(d as Partial<Auftrag> & { id: string });
        break;
      case 'auftrag_meldung': {
        const a = this.auftraege.find((x) => x.id === d.id);
        if (a) this.auftragAktualisieren({ id: a.id, meldungen: [...(a.meldungen ?? []), String(d.text)] });
        break;
      }
      case 'hinweis':
        this.hinweisSetzen({
          text: String(d.text ?? ''),
          stufe: String(d.stufe ?? 'info'),
          quelle: String(d.quelle ?? ''),
          code: d.code ? String(d.code) : undefined,
          bereich: d.bereich ? String(d.bereich) : undefined
        });
        break;
      case 'empfang':
        this.empfang = d as unknown as Empfang;
        break;
      case 'geraet_status': {
        const s = d as unknown as GeraetStatus;
        this.geraeteStatus = { ...this.geraeteStatus, [`${s.geraet}/${s.datei}`]: s };
        break;
      }
      case 'live': {
        const l = d as unknown as LiveText;
        this.live = { ...this.live, [l.geraet]: l };
        break;
      }
      case 'aufnahme':
        this.aufnahme = d as unknown as AufnahmeStand;
        break;
      case 'dateien':
        this.dateienStand++;
        break;
      case 'einstellungen':
        this.einstellungenStand++;
        break;
      case 'fehler':
        this.fehlermeldung = String(d.text ?? '');
        break;
      default:
        break;
    }
  }

  /** Jetzt in Sekunden nach der Uhr des Dienstes. */
  jetztDienst(jetztMs: number): number {
    return jetztMs / 1000 + this.uhrVersatz;
  }
}

export const zustand = new ZustandSpeicher();
