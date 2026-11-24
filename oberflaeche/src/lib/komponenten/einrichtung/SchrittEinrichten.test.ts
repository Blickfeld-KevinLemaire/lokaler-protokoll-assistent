import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { Auftrag } from '#lib/api/typen.ts';
import { zustand } from '#lib/stores/zustand.svelte.ts';
import SchrittEinrichten from './SchrittEinrichten.svelte';

const BEDINGUNGEN = 'https://huggingface.co/pyannote/speaker-diarization-community-1';

function auftrag(teil: Partial<Auftrag>): Auftrag {
  return {
    id: 'a1',
    art: 'einrichtung_modelle',
    titel: 'Modelle laden',
    herkunft: 'oberflaeche',
    vorrang: -5,
    status: 'fertig',
    erstellt: 1,
    fremd: false,
    stufe: '',
    stufe_text: '',
    vorschau: '',
    meldungen: [],
    angaben: {},
    ...teil
  } as Auftrag;
}

describe('Einrichten: gescheiterte Aufträge', () => {
  afterEach(() => {
    zustand.auftraege = [];
  });

  it('nennt den Grund mit anklickbarer Adresse und fragt den Zugangsschlüssel neu ab', () => {
    zustand.auftraege = [
      auftrag({
        status: 'fehler',
        fehler: `Nicht geklappt: pyannote: Die Nutzungsbedingungen bitte akzeptieren:\n  ${BEDINGUNGEN}`,
        angaben: { teile: { whisper: true, pyannote: false } }
      })
    ];
    render(SchrittEinrichten);
    expect(screen.getByText(/Nutzungsbedingungen bitte akzeptieren/)).toBeTruthy();
    expect(screen.getByRole('link', { name: BEDINGUNGEN }).getAttribute('href')).toBe(BEDINGUNGEN);
    expect(screen.getByLabelText('Zugangsschlüssel für die Sprechererkennung')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Erneut versuchen' })).toBeTruthy();
  });

  it('fragt keinen Schlüssel ab, wenn nur ein Sprachmodell scheiterte', () => {
    zustand.auftraege = [
      auftrag({
        status: 'fehler',
        fehler: 'Nicht geklappt: qwen: Verbindung abgerissen',
        angaben: { teile: { 'modell:qwen': false } }
      })
    ];
    render(SchrittEinrichten);
    expect(screen.getByText(/Verbindung abgerissen/)).toBeTruthy();
    expect(screen.queryByLabelText('Zugangsschlüssel für die Sprechererkennung')).toBeNull();
  });
});
