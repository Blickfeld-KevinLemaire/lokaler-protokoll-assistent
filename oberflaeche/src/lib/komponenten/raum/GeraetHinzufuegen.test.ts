import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { api } from '#lib/api/client.ts';
import GeraetHinzufuegen from './GeraetHinzufuegen.svelte';

describe('Gerät ohne USB hinzufügen', () => {
  it('nimmt Namen mit Leerzeichen und Umlauten an (wie der Dienst)', async () => {
    const anlegen = vi.spyOn(api, 'geraetAnlegen').mockResolvedValue({
      name: 'Besprechungsraum 3',
      token: 't',
      basis_url: 'http://192.168.1.20:8765',
      konfiguration: ''
    });
    render(GeraetHinzufuegen, { offen: true, schliessen: () => undefined, fertig: () => undefined });
    const feld = screen.getByPlaceholderText('z. B. Besprechungsraum 3') as HTMLInputElement;
    for (const name of ['Besprechungsraum 3', 'Küche', 'Raum-1']) {
      await fireEvent.input(feld, { target: { value: name } });
      // Vorher lehnte schon das Formular (pattern) solche Namen ab: Der Knopf „Hinzufügen“ tat dann nichts.
      expect(feld.checkValidity()).toBe(true);
    }
    await fireEvent.input(feld, { target: { value: 'Besprechungsraum 3' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Hinzufügen', hidden: true }));
    expect(anlegen).toHaveBeenCalledWith('Besprechungsraum 3', null);
  });
});
