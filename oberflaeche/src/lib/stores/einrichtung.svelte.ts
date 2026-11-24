/**
 * Ersteinrichtung (nur Windows-Anwendung, Rolle `desktop`): welcher Schritt, was gewählt und zugestimmt ist,
 * welche Aufträge laufen. Die Entscheidungen selbst stehen in `logik/einrichtung.ts`.
 *
 * Neustart: Nach `POST /api/system/neustart` schließt das Startgatter (Ereignis `neustart` des Fensters) und
 * öffnet wieder bei `bereit`. Dieser Speicher überlebt das (die Seite wird nicht neu geladen) und fragt dann
 * `stand` neu – der Dienst sagt mit `naechster_schritt`, wo es weitergeht.
 */
import { api } from '../api/client';
import type { Anbieter, EinrichtungKosten, EinrichtungRechner, EinrichtungStand, Info } from '../api/typen';
import {
  auftraegePlanen,
  BEREICHE,
  bedarfVorhanden,
  hfSchluesselNoetig,
  LEERE_WAHL,
  mitschriftPlanen,
  nachbar,
  onlineGewaehlt,
  schrittFolge,
  startSchritt,
  vorauswahl,
  wahlAusStand,
  wahlVollstaendig,
  type Bereich,
  type Schritt,
  type Wahl,
  type Zustimmung
} from '../logik/einrichtung';
import { dialog } from './oberflaeche.svelte';
import { verbindung } from './verbindung.svelte';
import { zustand } from './zustand.svelte';

const SPAETER_SCHLUESSEL = 'vermerk.einrichtungSpaeter';

export interface OnlineWahl {
  anbieter: string;
  schluessel: string;
  merken: boolean;
}

export type NeustartPhase = 'nein' | 'laeuft' | 'fehler';

function sitzungLesen(): boolean {
  try {
    return sessionStorage.getItem(SPAETER_SCHLUESSEL) === '1';
  } catch {
    return false;
  }
}

function sitzungSchreiben(wert: boolean): void {
  try {
    if (wert) sessionStorage.setItem(SPAETER_SCHLUESSEL, '1');
    else sessionStorage.removeItem(SPAETER_SCHLUESSEL);
  } catch {
    // gilt dann nur bis zum Neuladen
  }
}

class Einrichtung {
  aktiv = $state(false);
  schritt = $state<Schritt>('willkommen');
  stand = $state<EinrichtungStand | null>(null);
  rechner = $state<EinrichtungRechner | null>(null);
  kosten = $state<EinrichtungKosten | null>(null);
  anbieter = $state<Anbieter[]>([]);
  wahl = $state<Wahl>({ ...LEERE_WAHL });
  zustimmung = $state<Zustimmung>({});
  hfSchluessel = $state('');
  online = $state<Record<Bereich, OnlineWahl>>({
    transkription: { anbieter: '', schluessel: '', merken: true },
    nachbearbeitung: { anbieter: '', schluessel: '', merken: true },
    chatbot: { anbieter: '', schluessel: '', merken: true }
  });
  neustart = $state<NeustartPhase>('nein');
  nachNeustart = $state(false);
  arbeitet = $state(false);
  /** Aufträge dieser Einrichtung wurden gestartet (Schritt „Einrichten“ zeigt sie). */
  gestartet = $state(false);

  folge = $derived(
    schrittFolge({
      wahl: this.wahl,
      bedarf: bedarfVorhanden(this.kosten),
      nachNeustart: this.nachNeustart,
      raum: !!verbindung.info?.faehigkeiten.geraete_empfang,
      onlineOffen: this.stand?.online_ohne_anbieter
    })
  );

  /** Gibt es die Einrichtung hier (Windows-Anwendung, darf verwalten)? */
  verfuegbar(info: Info | null): boolean {
    return !!info && info.rolle === 'desktop' && (!info.mehrbenutzer || info.admin);
  }

  /** Nach jedem Öffnen des Startgatters: zeigen, wenn die Einrichtung offen ist (oder nach dem Neustart). */
  async pruefen(info: Info | null): Promise<void> {
    if (!info || !this.verfuegbar(info)) {
      this.aktiv = false;
      return;
    }
    const nachNeustart = this.neustart === 'laeuft';
    if (!nachNeustart && (this.aktiv || sitzungLesen())) return;
    // Abgeschlossen – außer die Rechenumgebung ist erst mit diesem Start gekommen (zugestimmt, aber die App wurde
    // statt „Jetzt neu starten“ geschlossen): Dann geht es wie versprochen mit der Spracherkennung weiter.
    const mitschriftMoeglich = !!info.faehigkeiten.lokale_transkription;
    if (!nachNeustart && info.einrichtung_abgeschlossen && !mitschriftMoeglich) return;
    let stand: EinrichtungStand;
    try {
      stand = await api.einrichtungStand();
    } catch (e) {
      console.warn('Einrichtung nicht geprüft', e);
      return;
    }
    this.stand = stand;
    if (nachNeustart) {
      this.neustart = 'nein';
      this.gestartet = false;
      if (stand.naechster_schritt === 'mitschrift') {
        this.nachNeustart = true;
        this.schritt = 'mitschrift';
        this.aktiv = true;
      } else if (!stand.einrichtung_abgeschlossen) {
        this.nachNeustart = false;
        this.schritt = startSchritt(stand);
        this.aktiv = true;
      } else {
        this.aktiv = false;
      }
      return;
    }
    if (stand.einrichtung_abgeschlossen && stand.naechster_schritt !== 'mitschrift') return;
    const start = startSchritt(stand);
    this.nachNeustart = start === 'mitschrift';
    this.schritt = start;
    this.aktiv = true;
  }

  /** Aus den Einstellungen: von vorn, mit der gespeicherten Arbeitsweise. */
  async oeffnen(): Promise<void> {
    sitzungSchreiben(false);
    this.nachNeustart = false;
    this.gestartet = false;
    this.neustart = 'nein';
    this.zustimmung = {};
    this.kosten = null;
    this.schritt = 'willkommen';
    this.aktiv = true;
    try {
      this.stand = await api.einrichtungStand();
      if (this.stand.einrichtung_abgeschlossen) this.wahl = wahlAusStand(this.stand);
    } catch (e) {
      dialog.zeigen(e, 'Einrichtung nicht geladen');
    }
  }

  /** „Später“: wartende Einrichtungsaufträge enden, beim nächsten Start kommt die Einrichtung wieder. */
  async spaeter(): Promise<void> {
    sitzungSchreiben(true);
    this.aktiv = false;
    try {
      this.stand = await api.einrichtungSpaeter(false);
    } catch (e) {
      console.warn('Später nicht gemeldet', e);
    }
  }

  async rechnerLaden(neu = false): Promise<void> {
    if (this.rechner && !neu) return;
    try {
      this.rechner = await api.einrichtungRechner(neu);
      if (!this.stand?.einrichtung_abgeschlossen && !wahlVollstaendig(this.wahl)) {
        this.wahl = vorauswahl(this.rechner);
      }
    } catch (e) {
      dialog.zeigen(e, 'Computer nicht geprüft');
    }
  }

  async anbieterLaden(): Promise<void> {
    if (this.anbieter.length) return;
    try {
      this.anbieter = await api.anbieter();
    } catch (e) {
      console.warn('Anbieter nicht geladen', e);
    }
  }

  wahlSetzen(bereich: Bereich, modus: 'lokal' | 'api'): void {
    this.wahl = { ...this.wahl, [bereich]: modus };
    this.kosten = null;
  }

  /** Online-Bereiche, die noch einen Anbieter brauchen. */
  get onlineBereiche(): Bereich[] {
    if (this.nachNeustart) {
      const offen = this.stand?.online_ohne_anbieter ?? [];
      return BEREICHE.map((b) => b.id).filter((b) => offen.includes(b));
    }
    return BEREICHE.map((b) => b.id).filter((b) => this.wahl[b] === 'api');
  }

  get kannWeiter(): boolean {
    if (this.arbeitet) return false;
    switch (this.schritt) {
      case 'computer':
        return !!this.rechner;
      case 'arbeitsweise':
        return wahlVollstaendig(this.wahl);
      case 'bedarf':
        return (
          !!this.kosten && !(hfSchluesselNoetig(this.zustimmung, this.stand) && !this.hfSchluessel.trim())
        );
      case 'online':
        return this.onlineBereiche.every((b) => !!this.online[b].anbieter);
      case 'mitschrift':
        return !(hfSchluesselNoetig(this.zustimmung, this.stand) && !this.hfSchluessel.trim());
      default:
        return true;
    }
  }

  /** „Einrichten“ zeigt nur etwas, wenn Aufträge gestartet wurden – sonst wird der Schritt übersprungen. */
  private ueberspringen(ziel: Schritt | null, richtung: 1 | -1): Schritt | null {
    if (ziel === 'einrichten' && !this.gestartet) return nachbar(this.folge, ziel, richtung);
    return ziel;
  }

  zurueck(): void {
    const ziel = this.ueberspringen(nachbar(this.folge, this.schritt, -1), -1);
    if (ziel) this.schritt = ziel;
  }

  /** Weiter – mit der Arbeit, die der aktuelle Schritt beim Verlassen erledigt. */
  async weiter(): Promise<void> {
    if (!this.kannWeiter) return;
    this.arbeitet = true;
    try {
      const fertig = await this.schrittAbschliessen();
      if (!fertig) return;
      const ziel = this.ueberspringen(nachbar(this.folge, this.schritt, 1), 1);
      if (ziel) this.schritt = ziel;
    } catch (e) {
      dialog.zeigen(e, 'Das hat nicht geklappt');
    } finally {
      this.arbeitet = false;
    }
  }

  private async schrittAbschliessen(): Promise<boolean> {
    switch (this.schritt) {
      case 'arbeitsweise': {
        if (!wahlVollstaendig(this.wahl)) return false;
        this.kosten = await api.einrichtungKosten(this.wahl);
        if (!bedarfVorhanden(this.kosten)) await this.entscheiden();
        return true;
      }
      case 'bedarf':
        await this.entscheiden();
        await this.auftraegeStarten();
        return true;
      case 'online':
        await this.anbieterSpeichern();
        return true;
      case 'mitschrift': {
        const plan = mitschriftPlanen({
          zustimmung: this.zustimmung,
          stand: this.stand,
          hfSchluessel: this.hfSchluessel
        });
        if (plan && !this.gestartet) {
          const auftrag = await api.einrichtungModelle(plan);
          zustand.auftragAktualisieren(auftrag);
          this.gestartet = true;
          this.hfSchluessel = '';
          return false; // bleibt stehen und zeigt den Fortschritt
        }
        return true;
      }
      default:
        return true;
    }
  }

  private async entscheiden(): Promise<void> {
    if (!wahlVollstaendig(this.wahl)) return;
    const empfohlen = this.rechner?.empfohlene_modelle ?? {};
    this.stand = await api.einrichtungEntscheidung({
      ...this.wahl,
      sprachmodell: this.wahl.nachbearbeitung === 'lokal' ? (empfohlen.nachbearbeitung ?? null) : null,
      whisper_modell: this.wahl.transkription === 'lokal' ? (empfohlen.transkription ?? null) : null,
      zustimmung_rechenumgebung: !!this.zustimmung.laufzeit
    });
  }

  private async auftraegeStarten(): Promise<void> {
    const plan = auftraegePlanen({
      kosten: this.kosten,
      zustimmung: this.zustimmung,
      stand: this.stand,
      wahl: this.wahl,
      hfSchluessel: this.hfSchluessel
    });
    // Der Reihe nach einreihen: Die Warteschlange arbeitet bei gleichem Vorrang in dieser Reihenfolge.
    if (plan.ffmpeg) zustand.auftragAktualisieren(await api.einrichtungFfmpeg());
    if (plan.ollama) zustand.auftragAktualisieren(await api.einrichtungOllama());
    if (plan.modelle) zustand.auftragAktualisieren(await api.einrichtungModelle(plan.modelle));
    this.gestartet = plan.ffmpeg || plan.ollama || !!plan.modelle;
    if (plan.modelle?.hf_token) this.hfSchluessel = '';
  }

  /** Ein gescheiterter Einrichtungsauftrag: noch einmal einreihen (die Zustimmung gilt weiter). */
  async wiederholen(art: string): Promise<void> {
    try {
      if (art === 'einrichtung_ffmpeg') zustand.auftragAktualisieren(await api.einrichtungFfmpeg());
      else if (art === 'einrichtung_ollama') zustand.auftragAktualisieren(await api.einrichtungOllama());
      else {
        const plan = this.nachNeustart
          ? mitschriftPlanen({
              zustimmung: this.zustimmung,
              stand: this.stand,
              hfSchluessel: this.hfSchluessel
            })
          : auftraegePlanen({
              kosten: this.kosten,
              zustimmung: this.zustimmung,
              stand: this.stand,
              wahl: this.wahl,
              hfSchluessel: this.hfSchluessel
            }).modelle;
        if (plan) {
          zustand.auftragAktualisieren(await api.einrichtungModelle(plan));
          // Ein neu eingegebener Zugangsschlüssel ist jetzt beim Dienst (und dort gemerkt).
          if (plan.hf_token) this.hfSchluessel = '';
        }
      }
    } catch (e) {
      dialog.zeigen(e, 'Das hat nicht geklappt');
    }
  }

  private async anbieterSpeichern(): Promise<void> {
    for (const bereich of this.onlineBereiche) {
      const o = this.online[bereich];
      if (!o.anbieter) continue;
      await api.einrichtungAnbieter({
        bereich,
        anbieter: o.anbieter,
        schluessel: o.schluessel.trim() || null,
        merken: o.merken
      });
      o.schluessel = '';
    }
    this.stand = await api.einrichtungStand();
  }

  /** Den Stand neu holen (z. B. auf „Fertig“: Muss neu gestartet werden?). */
  async standNeu(): Promise<void> {
    try {
      this.stand = await api.einrichtungStand();
    } catch (e) {
      console.warn('Stand nicht geladen', e);
    }
  }

  /** „Jetzt neu starten“: Der Dienst beendet sich, das Fenster startet ihn wieder. */
  async neuStarten(): Promise<void> {
    this.neustart = 'laeuft';
    try {
      await api.neustart();
    } catch (e) {
      this.neustart = 'fehler';
      dialog.zeigen(e, 'Neu starten hat nicht geklappt');
    }
  }

  /** „Los geht's“: abgeschlossen. Muss der Dienst danach noch einmal starten, bleibt „Fertig“ stehen. */
  async abschliessen(): Promise<void> {
    this.arbeitet = true;
    try {
      this.stand = await api.einrichtungAbschliessen();
      if (verbindung.info) verbindung.info = { ...verbindung.info, einrichtung_abgeschlossen: true };
      if (!this.stand.neustart_noetig) {
        this.aktiv = false;
        sitzungSchreiben(false);
      }
    } catch (e) {
      dialog.zeigen(e, 'Abschließen hat nicht geklappt');
    } finally {
      this.arbeitet = false;
    }
  }

  /** Nur für die Anzeige: Wurde online gewählt? */
  get mitOnline(): boolean {
    return onlineGewaehlt(this.wahl);
  }
}

export const einrichtung = new Einrichtung();
