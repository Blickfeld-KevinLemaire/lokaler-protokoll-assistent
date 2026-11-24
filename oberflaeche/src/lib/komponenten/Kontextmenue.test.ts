import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Kontextmenue from './Kontextmenue.svelte';

const PUNKTE = [
  { id: 'oeffnen', text: 'Öffnen', kuerzel: 'Enter', taste: 'Enter' },
  { id: 'umbenennen', text: 'Umbenennen', deaktiviert: true, hinweis: 'Gehört jemand anderem.' },
  { id: 'kopieren', text: 'Transkript kopieren', trenner: true },
  { id: 'loeschen', text: 'Löschen', gefahr: true, trenner: true }
];

function oeffnen() {
  const ausloeser = document.createElement('button');
  ausloeser.textContent = 'Zeile';
  document.body.append(ausloeser);
  ausloeser.focus();
  const waehlen = vi.fn();
  const schliessen = vi.fn();
  render(Kontextmenue, { x: 40, y: 50, punkte: PUNKTE, beschriftung: 'Aktionen', waehlen, schliessen });
  return { ausloeser, waehlen, schliessen };
}

const fokussiert = () => document.activeElement?.textContent?.trim() ?? '';

describe('Kontextmenü', () => {
  afterEach(() => {
    for (const knopf of document.querySelectorAll('body > button')) knopf.remove();
  });

  it('ist ein Menü mit Einträgen; der erste hat den Fokus', () => {
    oeffnen();
    expect(screen.getByRole('menu', { name: 'Aktionen' })).toBeTruthy();
    const eintraege = screen.getAllByRole('menuitem');
    expect(eintraege.map((e) => e.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Öffnen Enter',
      'Umbenennen Gehört jemand anderem.',
      'Transkript kopieren',
      'Löschen'
    ]);
    expect(eintraege[1]?.getAttribute('aria-disabled')).toBe('true');
    expect(eintraege[0]?.getAttribute('aria-keyshortcuts')).toBe('Enter');
    expect(screen.getAllByRole('separator')).toHaveLength(2);
    expect(fokussiert()).toMatch(/^Öffnen/);
  });

  it('Pfeiltasten (im Kreis), Pos1/Ende und Anfangsbuchstaben bewegen den Fokus', async () => {
    oeffnen();
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowUp' });
    expect(fokussiert()).toBe('Löschen');
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    expect(fokussiert()).toMatch(/^Öffnen/);
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    expect(fokussiert()).toMatch(/^Umbenennen/);
    await fireEvent.keyDown(document.activeElement!, { key: 'End' });
    expect(fokussiert()).toBe('Löschen');
    await fireEvent.keyDown(document.activeElement!, { key: 'Home' });
    expect(fokussiert()).toMatch(/^Öffnen/);
    await fireEvent.keyDown(document.activeElement!, { key: 't' });
    expect(fokussiert()).toBe('Transkript kopieren');
  });

  it('Enter wählt; ein ausgegrauter Eintrag tut nichts', async () => {
    const { waehlen, schliessen, ausloeser } = oeffnen();
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    await fireEvent.keyDown(document.activeElement!, { key: 'Enter' });
    expect(waehlen).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('menuitem', { name: /Umbenennen/ }));
    expect(waehlen).not.toHaveBeenCalled();
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    await fireEvent.keyDown(document.activeElement!, { key: ' ' });
    expect(waehlen).toHaveBeenCalledWith('kopieren');
    expect(schliessen).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(ausloeser);
  });

  it('Mausklick wählt', async () => {
    const { waehlen } = oeffnen();
    await fireEvent.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(waehlen).toHaveBeenCalledWith('loeschen');
  });

  it('Esc und Tab schließen und geben den Fokus zurück', async () => {
    const { schliessen, ausloeser, waehlen } = oeffnen();
    await fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(schliessen).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(ausloeser);
    expect(waehlen).not.toHaveBeenCalled();
    screen.getAllByRole('menuitem')[0]!.focus();
    await fireEvent.keyDown(document.activeElement!, { key: 'Tab' });
    expect(schliessen).toHaveBeenCalledTimes(2);
  });

  it('ein Klick daneben schließt, ein Klick hinein nicht', async () => {
    const { schliessen, ausloeser } = oeffnen();
    await fireEvent.pointerDown(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(schliessen).not.toHaveBeenCalled();
    await fireEvent.pointerDown(ausloeser);
    expect(schliessen).toHaveBeenCalledTimes(1);
  });

  it('andere Tasten bleiben unberührt', async () => {
    const { schliessen } = oeffnen();
    const ereignis = new KeyboardEvent('keydown', { key: 'F5', bubbles: true, cancelable: true });
    document.activeElement!.dispatchEvent(ereignis);
    expect(ereignis.defaultPrevented).toBe(false);
    expect(schliessen).not.toHaveBeenCalled();
  });
});
