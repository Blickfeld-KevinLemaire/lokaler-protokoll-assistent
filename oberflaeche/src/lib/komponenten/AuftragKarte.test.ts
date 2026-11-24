import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Auftrag } from '$lib/api/typen';
import AuftragKarte from './AuftragKarte.svelte';

function auftrag(teil: Partial<Auftrag>): Auftrag {
  return {
    id: 'a1',
    art: 'transkription',
    titel: 'Besprechung.m4a',
    herkunft: 'oberflaeche',
    vorrang: 0,
    status: 'fertig',
    erstellt: 0,
    stufe: 'abgeschlossen',
    stufe_text: '',
    vorschau: '',
    meldungen: [],
    angaben: {},
    ...teil
  } as Auftrag;
}

describe('AuftragKarte', () => {
  it('sagt, wenn die Sprecher nicht getrennt werden konnten (statt nur „Fertig“)', () => {
    render(AuftragKarte, {
      auftrag: auftrag({
        ergebnis: { transkript_json: 'C:/aus/x.json', diarisierung_fehler: 'Zugang zum Modell fehlt' }
      })
    });
    expect(screen.getByText(/Sprecher ließen sich nicht unterscheiden/)).toBeTruthy();
  });

  it('zeigt keinen Hinweis, wenn alles geklappt hat', () => {
    render(AuftragKarte, {
      auftrag: auftrag({ ergebnis: { transkript_json: 'C:/aus/x.json', diarisierung_fehler: null } })
    });
    expect(screen.queryByText(/Sprecher ließen sich nicht unterscheiden/)).toBeNull();
  });
});
