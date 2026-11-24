import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { api } from '#lib/api/client.ts';
import type { Sprecher } from '#lib/api/typen.ts';
import SprecherListe from './SprecherListe.svelte';

function sprecher(namen: [string, string][]): Sprecher[] {
  return namen.map(([id, name]) => ({ id, name, segmente: 3, sekunden: 30 }) as Sprecher);
}

describe('Sprecher umbenennen', () => {
  it('behält eingetippte Namen, wenn die Besprechung zwischendurch neu lädt', async () => {
    vi.spyOn(api, 'sprecherVorschlaege').mockResolvedValue({ vorschlaege: {}, stimmen_vorhanden: false });
    const ansicht = render(SprecherListe, {
      id: 'sitzung',
      sprecher: sprecher([
        ['SPEAKER_00', 'Sprecher 1'],
        ['SPEAKER_01', 'Sprecher 2']
      ]),
      gespeichert: () => {}
    });
    const feld = screen.getAllByRole('textbox')[0] as HTMLInputElement;
    await fireEvent.input(feld, { target: { value: 'Anna' } });

    // Irgendein anderer Auftrag wird fertig: Die Besprechung lädt neu (neue, gleiche Liste) – oder ein anderer
    // Name hat sich im Dienst geändert.
    await ansicht.rerender({
      sprecher: sprecher([
        ['SPEAKER_00', 'Sprecher 1'],
        ['SPEAKER_01', 'Bernd']
      ])
    });

    const felder = screen.getAllByRole('textbox') as HTMLInputElement[];
    expect(felder.map((f) => f.value)).toEqual(['Anna', 'Bernd']);
  });

  it('übernimmt nach dem Speichern, was der Dienst daraus macht (geleerter Name wird wieder „Sprecher 1“)', async () => {
    vi.spyOn(api, 'sprecherVorschlaege').mockResolvedValue({ vorschlaege: {}, stimmen_vorhanden: false });
    const umbenennen = vi
      .spyOn(api, 'sprecherUmbenennen')
      .mockResolvedValue({ gespeichert: true, word_hinweis: null });
    const ansicht = render(SprecherListe, {
      id: 'sitzung',
      sprecher: sprecher([['SPEAKER_00', 'Anna']]),
      gespeichert: () => {}
    });
    const feld = screen.getByRole('textbox') as HTMLInputElement;
    await fireEvent.input(feld, { target: { value: '' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await vi.waitFor(() => expect(umbenennen).toHaveBeenCalled());
    await ansicht.rerender({ sprecher: sprecher([['SPEAKER_00', 'Sprecher 1']]) });
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('Sprecher 1');
  });
});
