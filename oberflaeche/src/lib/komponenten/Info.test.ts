import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Info from './Info.svelte';

describe('Info (i)', () => {
  it('öffnet bei Fokus, verweist per aria-describedby und schließt mit Escape', async () => {
    render(Info, { frage: 'Was bedeutet Sprecher erkennen?', text: 'Der Text wird nach Personen getrennt.' });
    const knopf = screen.getByRole('button', { name: 'Was bedeutet Sprecher erkennen?' });
    expect(screen.queryByRole('tooltip')).toBeNull();
    await fireEvent.focus(knopf);
    const blase = screen.getByRole('tooltip');
    expect(blase.textContent).toContain('Der Text wird nach Personen getrennt.');
    expect(knopf.getAttribute('aria-describedby')).toBe(blase.id);
    await fireEvent.keyDown(knopf, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
