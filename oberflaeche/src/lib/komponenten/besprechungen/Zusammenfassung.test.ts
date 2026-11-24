import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '$lib/api/client';
import type { Auftrag, BesprechungDetails, Einstellungen } from '$lib/api/typen';
import { einstellungen } from '$lib/stores/einstellungen.svelte';
import Zusammenfassung from './Zusammenfassung.svelte';

const VORLAGEN = [
  { name: 'Zusammenfassung', text: 'Fasse kurz zusammen.', eigene: false },
  { name: 'Agenda', text: 'Erstelle eine Agenda.', eigene: false }
];

const DETAILS = {
  id: 'sitzung_lokal_transkript_20260101_100000',
  titel: 'sitzung',
  zeit: '20260101_100000',
  transkript: 'C:\\Ausgabe\\sitzung_lokal_transkript_20260101_100000.json',
  hat_protokoll: false,
  protokolle: [],
  protokoll: null,
  sprecher: [],
  segmente: [],
  dateien: []
} as unknown as BesprechungDetails;

function starten() {
  vi.spyOn(api, 'vorlagen').mockResolvedValue(VORLAGEN);
  const start = vi
    .spyOn(api, 'auswertungStarten')
    .mockResolvedValue({ id: 'a1', art: 'auswertung', status: 'wartet', platz: 0 } as unknown as Auftrag);
  render(Zusammenfassung, { details: DETAILS, text: '', gespeichert: () => {} });
  return start;
}

describe('Zusammenfassung erstellen', () => {
  afterEach(() => {
    einstellungen.werte = null;
  });

  it('nimmt ohne andere Vorgabe den Standard-Auftrag aus den Einstellungen (kein eigener Text)', async () => {
    const start = starten();
    const auswahl = (await screen.findByRole('combobox', { name: 'Vorlage' })) as HTMLSelectElement;
    await waitFor(() => expect(auswahl.value).toBe(''));
    expect(auswahl.selectedOptions[0]?.textContent).toBe('Standard');
    await fireEvent.click(screen.getByRole('button', { name: 'Erstellen' }));
    expect(start).toHaveBeenCalledWith(DETAILS.transkript, null);
  });

  it('nimmt die als Vorgabe markierte Vorlage', async () => {
    einstellungen.werte = { aktive_systemprompt_vorlage: 'Agenda' } as unknown as Einstellungen;
    const start = starten();
    const auswahl = (await screen.findByRole('combobox', { name: 'Vorlage' })) as HTMLSelectElement;
    await waitFor(() => expect(auswahl.value).toBe('Agenda'));
    await fireEvent.click(screen.getByRole('button', { name: 'Erstellen' }));
    expect(start).toHaveBeenCalledWith(DETAILS.transkript, 'Erstelle eine Agenda.');
  });
});
