/**
 * Kontextmenü eines Eintrags in „Transkripte“: welche Befehle es gibt. Nur, was in dieser Rolle und für diese
 * Person geht; ändern darf nur, wem das Transkript gehört – dort steht der Befehl ausgegraut mit Begründung, statt
 * einfach zu fehlen.
 */
import type { Besprechung } from '../api/typen';
import type { MenuePunkt } from './kontextmenue';
import { teilenMoeglich } from './teilen';

export type BesprechungsAktion =
  | 'oeffnen'
  | 'umbenennen'
  | 'dokument'
  | 'explorer'
  | 'zusammenfassung'
  | 'exportieren'
  | 'kopieren'
  | 'teilen'
  | 'loeschen';

export interface MenueLage {
  /** Windows-Anwendung: Dateien im Explorer zeigen und mit dem Standardprogramm öffnen. */
  ordnerOeffnen: boolean;
  mehrbenutzer: boolean;
  /** Wartet oder läuft gerade eine Zusammenfassung für dieses Transkript? */
  zusammenfassungLaeuft: boolean;
}

export type BesprechungsPunkt = MenuePunkt & { id: BesprechungsAktion };

type Eintrag = Pick<Besprechung, 'eigen' | 'besitzer' | 'hat_protokoll' | 'dokument'>;

const NUR_BESITZER = 'Das kann nur, wem das Transkript gehört.';

export function besprechungsMenue(b: Eintrag, lage: MenueLage): BesprechungsPunkt[] {
  const eigen = b.eigen !== false;
  const punkte: BesprechungsPunkt[] = [
    { id: 'oeffnen', text: 'Öffnen', kuerzel: 'Enter', taste: 'Enter' },
    {
      id: 'umbenennen',
      text: 'Umbenennen',
      kuerzel: 'F2',
      taste: 'F2',
      deaktiviert: !eigen,
      hinweis: eigen ? undefined : NUR_BESITZER
    }
  ];
  if (lage.ordnerOeffnen) {
    punkte.push(
      {
        id: 'dokument',
        text: 'Dokument öffnen',
        trenner: true,
        deaktiviert: !b.dokument,
        hinweis: b.dokument ? undefined : 'Es gibt noch kein Word-Dokument.'
      },
      { id: 'explorer', text: 'Im Explorer zeigen' }
    );
  }
  if (eigen) {
    punkte.push(
      {
        id: 'zusammenfassung',
        text: b.hat_protokoll ? 'Zusammenfassung neu erstellen' : 'Zusammenfassung erstellen',
        trenner: true,
        deaktiviert: lage.zusammenfassungLaeuft,
        hinweis: lage.zusammenfassungLaeuft ? 'Wird gerade erstellt.' : undefined
      },
      { id: 'exportieren', text: 'Exportieren …' }
    );
  }
  punkte.push({ id: 'kopieren', text: 'Transkript kopieren', trenner: !eigen });
  if (teilenMoeglich(b, lage.mehrbenutzer)) punkte.push({ id: 'teilen', text: 'Teilen …' });
  punkte.push({
    id: 'loeschen',
    text: 'Löschen',
    kuerzel: 'Entf',
    taste: 'Delete',
    gefahr: true,
    trenner: true,
    deaktiviert: !eigen || lage.zusammenfassungLaeuft,
    hinweis: !eigen
      ? NUR_BESITZER
      : lage.zusammenfassungLaeuft
        ? 'Erst, wenn die Zusammenfassung fertig ist.'
        : undefined
  });
  return punkte;
}

/** Text für die Rückfrage vor dem Löschen (`server`: im Browser, die Dateien liegen auf einem anderen Rechner). */
export function loeschFrage(titel: string, server: boolean): { titel: string; text: string; verb: string } {
  return {
    titel: `„${titel}“ wirklich löschen?`,
    text: server
      ? 'Transkript, Zusammenfassungen und exportierte Dateien landen im Papierkorb auf dem Server – zurückholen kann sie, wer den Server betreut. Die Aufnahme selbst bleibt erhalten.'
      : 'Transkript, Zusammenfassungen und exportierte Dateien landen im Papierkorb. Die Aufnahme selbst bleibt erhalten.',
    verb: 'Löschen'
  };
}

/** Meldung nach dem Löschen. `ordner`: nicht im Papierkorb von Windows, sondern im Ordner „.papierkorb“. */
export function geloeschtMeldung(titel: string, papierkorb: string, desktop: boolean): string {
  if (desktop && papierkorb === 'ordner') {
    return `„${titel}“ gelöscht – die Dateien liegen im Ordner „.papierkorb“ im Ausgabeordner.`;
  }
  return `„${titel}“ gelöscht`;
}
