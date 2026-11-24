import { createEvent, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '$lib/api/client';
import type { Besprechung, BesprechungDetails, Info } from '$lib/api/typen';
import { rueckfrage } from '$lib/stores/oberflaeche.svelte';
import { verbindung } from '$lib/stores/verbindung.svelte';
import { zustand } from '$lib/stores/zustand.svelte';
import { INFO } from '../../../test/hilfen';
import BesprechungsTabelle from './BesprechungsTabelle.svelte';

function eintrag(id: string, titel: string, teil: Partial<Besprechung> = {}): Besprechung {
  return {
    id,
    titel,
    zeit: '20260101_100000',
    transkript: `C:/aus/${id}.json`,
    dokument: null,
    hat_protokoll: false,
    protokolle: [],
    eigen: true,
    besitzer: null,
    geteilt_mit: [],
    ...teil
  } as Besprechung;
}

const LISTE = [
  eintrag('a', 'Jour fixe'),
  eintrag('b', 'Vorstand'),
  eintrag('c', 'Fremd', { eigen: false, besitzer: 'ben' })
];

function zeigen(eintraege = LISTE) {
  const oeffnen = vi.fn();
  const geaendert = vi.fn();
  render(BesprechungsTabelle, { eintraege, oeffnen, geaendert });
  return { oeffnen, geaendert };
}

const zeile = (titel: string) => screen.getByText(titel).closest('[role="row"]') as HTMLElement;
const name = (titel: string) => screen.getByText(titel);
const feld = () => screen.queryByRole('textbox') as HTMLInputElement | null;

/** Per Tastatur auswählen (Tab landet auf der Zeile). */
async function auswaehlen(titel: string) {
  zeile(titel).focus();
  await tick();
}

/** Klicks auf einen Verweis wollte jsdom ausführen („Not implemented: navigation“) – hier nur mitschreiben. */
let ohneNavigation: (e: Event) => void;

beforeEach(() => {
  verbindung.info = { ...INFO } as unknown as Info;
  ohneNavigation = (e) => e.preventDefault();
  document.addEventListener('click', ohneNavigation);
});

afterEach(() => {
  document.removeEventListener('click', ohneNavigation);
  vi.useRealTimers();
  verbindung.info = null;
  zustand.auftraege = [];
  rueckfrage.antworten_(false);
});

describe('Umbenennen in der Liste', () => {
  it('F2 öffnet das Feld; Enter speichert den neuen Namen', async () => {
    const umbenennen = vi.spyOn(api, 'besprechungUmbenennen').mockResolvedValue({ titel: 'Jour fixe KW 2' });
    const { geaendert } = zeigen();
    await auswaehlen('Jour fixe');
    await fireEvent.keyDown(zeile('Jour fixe'), { key: 'F2' });
    const eingabe = feld()!;
    expect(eingabe.value).toBe('Jour fixe');
    expect(document.activeElement).toBe(eingabe);
    await fireEvent.input(eingabe, { target: { value: '  Jour fixe KW 2 ' } });
    await fireEvent.keyDown(eingabe, { key: 'Enter' });
    expect(umbenennen).toHaveBeenCalledWith('a', 'Jour fixe KW 2');
    expect(feld()).toBeNull();
    expect(screen.getByText('Jour fixe KW 2')).toBeTruthy(); // schon vor dem Neuladen
    await waitFor(() => expect(geaendert).toHaveBeenCalled());
    expect(document.activeElement).toBe(zeile('Jour fixe KW 2'));
  });

  it('Esc bricht ab, ein leerer oder unveränderter Name auch', async () => {
    const umbenennen = vi.spyOn(api, 'besprechungUmbenennen');
    zeigen();
    await auswaehlen('Vorstand');
    await fireEvent.keyDown(zeile('Vorstand'), { key: 'F2' });
    await fireEvent.input(feld()!, { target: { value: 'Anders' } });
    await fireEvent.keyDown(feld()!, { key: 'Escape' });
    expect(feld()).toBeNull();
    expect(screen.getByText('Vorstand')).toBeTruthy();

    await fireEvent.keyDown(zeile('Vorstand'), { key: 'F2' });
    await fireEvent.input(feld()!, { target: { value: '   ' } });
    await fireEvent.keyDown(feld()!, { key: 'Enter' });
    await fireEvent.keyDown(zeile('Vorstand'), { key: 'F2' });
    await fireEvent.keyDown(feld()!, { key: 'Enter' });
    expect(umbenennen).not.toHaveBeenCalled();
  });

  it('Verlassen des Felds speichert', async () => {
    const umbenennen = vi.spyOn(api, 'besprechungUmbenennen').mockResolvedValue({ titel: 'Neu' });
    zeigen();
    await auswaehlen('Vorstand');
    await fireEvent.keyDown(zeile('Vorstand'), { key: 'F2' });
    await fireEvent.input(feld()!, { target: { value: 'Neu' } });
    await fireEvent.blur(feld()!);
    expect(umbenennen).toHaveBeenCalledWith('b', 'Neu');
  });

  it('scheitert das Speichern, steht wieder der alte Name da', async () => {
    vi.spyOn(api, 'besprechungUmbenennen').mockRejectedValue(new Error('kaputt'));
    zeigen();
    await auswaehlen('Vorstand');
    await fireEvent.keyDown(zeile('Vorstand'), { key: 'F2' });
    await fireEvent.input(feld()!, { target: { value: 'Neu' } });
    await fireEvent.keyDown(feld()!, { key: 'Enter' });
    await waitFor(() => expect(screen.getByText('Vorstand')).toBeTruthy());
  });

  it('nicht für Transkripte, die jemand anderem gehören', async () => {
    zeigen();
    await auswaehlen('Fremd');
    await fireEvent.keyDown(zeile('Fremd'), { key: 'F2' });
    expect(feld()).toBeNull();
  });

  it('Klick auf den Namen des ausgewählten Eintrags: nach einer Pause umbenennen', async () => {
    vi.useFakeTimers();
    const { oeffnen } = zeigen();
    await auswaehlen('Jour fixe');
    await fireEvent.pointerDown(name('Jour fixe'));
    const klick = createEvent.click(name('Jour fixe'), { detail: 1 });
    await fireEvent(name('Jour fixe'), klick);
    expect(klick.defaultPrevented).toBe(true); // öffnet nicht
    expect(feld()).toBeNull(); // noch nicht
    vi.advanceTimersByTime(499);
    await tick();
    expect(feld()).toBeNull();
    vi.advanceTimersByTime(1);
    await tick();
    expect(feld()?.value).toBe('Jour fixe');
    expect(oeffnen).not.toHaveBeenCalled();
  });

  it('Doppelklick auf den Namen öffnet, statt umzubenennen', async () => {
    vi.useFakeTimers();
    const { oeffnen } = zeigen();
    await auswaehlen('Jour fixe');
    await fireEvent.pointerDown(name('Jour fixe'));
    await fireEvent.click(name('Jour fixe'), { detail: 1 });
    await fireEvent.pointerDown(name('Jour fixe'));
    await fireEvent.click(name('Jour fixe'), { detail: 2 });
    await fireEvent.dblClick(name('Jour fixe'));
    vi.advanceTimersByTime(1000);
    await tick();
    expect(feld()).toBeNull();
    expect(oeffnen).toHaveBeenCalledTimes(1);
  });

  it('ein Klick auf einen nicht ausgewählten Eintrag öffnet wie bisher', async () => {
    vi.useFakeTimers();
    zeigen();
    await auswaehlen('Vorstand');
    await fireEvent.pointerDown(name('Jour fixe'));
    const klick = createEvent.click(name('Jour fixe'), { detail: 1 });
    let verhindert: boolean | null = null;
    // Nach dem Svelte-Handler (der am Dokument hängt) nachsehen, ob er den Verweis aufgehalten hat.
    document.removeEventListener('click', ohneNavigation);
    ohneNavigation = (e) => {
      verhindert = e.defaultPrevented;
      e.preventDefault();
    };
    document.addEventListener('click', ohneNavigation);
    await fireEvent(name('Jour fixe'), klick);
    expect(verhindert).toBe(false);
    vi.advanceTimersByTime(1000);
    await tick();
    expect(feld()).toBeNull();
  });
});

describe('Kontextmenü der Liste', () => {
  it('Rechtsklick öffnet es; „Umbenennen“ startet das Feld', async () => {
    zeigen();
    await fireEvent.contextMenu(zeile('Vorstand'), { clientX: 30, clientY: 40 });
    const menue = screen.getByRole('menu', { name: 'Aktionen für „Vorstand“' });
    expect(menue).toBeTruthy();
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Öffnen Enter',
      'Umbenennen F2',
      'Dokument öffnen Es gibt noch kein Word-Dokument.',
      'Im Explorer zeigen',
      'Zusammenfassung erstellen',
      'Exportieren …',
      'Transkript kopieren',
      'Löschen Entf'
    ]);
    await fireEvent.click(screen.getByRole('menuitem', { name: /Umbenennen/ }));
    expect(screen.queryByRole('menu')).toBeNull();
    expect(feld()?.value).toBe('Vorstand');
  });

  it('Menü-Taste öffnet es am Eintrag; Esc schließt und lässt den Fokus dort', async () => {
    zeigen();
    await auswaehlen('Jour fixe');
    await fireEvent.keyDown(zeile('Jour fixe'), { key: 'ContextMenu' });
    await tick();
    expect(screen.getByRole('menu')).toBeTruthy();
    // Der Browser schickt danach noch ein contextmenu-Ereignis: kein zweites Menü.
    await fireEvent.contextMenu(zeile('Jour fixe'));
    expect(screen.getAllByRole('menu')).toHaveLength(1);
    await fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(zeile('Jour fixe'));
    await fireEvent.keyDown(zeile('Jour fixe'), { key: 'F10', shiftKey: true });
    expect(screen.getByRole('menu')).toBeTruthy();
  });

  it('„Transkript kopieren“ legt Zeitmarken und Namen in die Zwischenablage', async () => {
    const schreiben = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: schreiben }, configurable: true });
    vi.spyOn(api, 'besprechung').mockResolvedValue({
      segmente: [{ start: 3, ende: 5, sprecher_id: 'SPEAKER_00', sprecher: 'Anna', text: 'Hallo.' }]
    } as unknown as BesprechungDetails);
    zeigen();
    await fireEvent.contextMenu(zeile('Vorstand'));
    await fireEvent.click(screen.getByRole('menuitem', { name: 'Transkript kopieren' }));
    await waitFor(() => expect(schreiben).toHaveBeenCalledWith('[0:03] Anna: Hallo.\n'));
  });

  it('„Im Explorer zeigen“ markiert das Dokument, sonst das Transkript', async () => {
    const zeigenImOrdner = vi.spyOn(api, 'ordnerOeffnen').mockResolvedValue({ geoeffnet: true });
    zeigen([eintrag('a', 'Mit Dokument', { dokument: 'C:/aus/a.docx' }), eintrag('b', 'Ohne')]);
    for (const titel of ['Mit Dokument', 'Ohne']) {
      await fireEvent.contextMenu(zeile(titel));
      await fireEvent.click(screen.getByRole('menuitem', { name: 'Im Explorer zeigen' }));
    }
    expect(zeigenImOrdner.mock.calls).toEqual([['C:/aus/a.docx'], ['C:/aus/b.json']]);
  });

  it('im Browser (Servermodus) gibt es weder Explorer noch Dokument öffnen', async () => {
    verbindung.info = {
      ...INFO,
      rolle: 'server',
      mehrbenutzer: true,
      faehigkeiten: { ...INFO.faehigkeiten, ordner_oeffnen: false }
    } as unknown as Info;
    zeigen([eintrag('anna~a', 'Meins', { besitzer: 'anna' })]);
    await fireEvent.contextMenu(zeile('Meins'));
    const namen = screen.getAllByRole('menuitem').map((m) => m.textContent ?? '');
    expect(namen.some((n) => n.includes('Explorer') || n.includes('Dokument öffnen'))).toBe(false);
    expect(namen.some((n) => n.includes('Teilen'))).toBe(true);
  });
});

describe('Löschen', () => {
  it('fragt nach und löscht erst nach der Bestätigung', async () => {
    const loeschen = vi
      .spyOn(api, 'besprechungLoeschen')
      .mockResolvedValue({ geloescht: true, papierkorb: 'windows' });
    const { geaendert } = zeigen();
    await auswaehlen('Vorstand');
    await fireEvent.keyDown(zeile('Vorstand'), { key: 'Delete' });
    await waitFor(() => expect(rueckfrage.frage?.titel).toBe('„Vorstand“ wirklich löschen?'));
    expect(rueckfrage.frage?.text).toContain('Papierkorb');
    rueckfrage.antworten_(false);
    await tick();
    expect(loeschen).not.toHaveBeenCalled();

    await fireEvent.contextMenu(zeile('Vorstand'));
    await fireEvent.click(screen.getByRole('menuitem', { name: /Löschen/ }));
    await waitFor(() => expect(rueckfrage.frage).not.toBeNull());
    rueckfrage.antworten_(true);
    await waitFor(() => expect(loeschen).toHaveBeenCalledWith('b'));
    await waitFor(() => expect(geaendert).toHaveBeenCalled());
  });

  it('nicht, solange eine Zusammenfassung läuft, und nicht bei fremden Transkripten', async () => {
    zustand.auftraege = [
      { id: 'x', art: 'auswertung', status: 'laeuft', angaben: { transkript: 'C:/aus/a.json' } }
    ] as unknown as typeof zustand.auftraege;
    zeigen();
    await auswaehlen('Jour fixe');
    await fireEvent.keyDown(zeile('Jour fixe'), { key: 'Delete' });
    await auswaehlen('Fremd');
    await fireEvent.keyDown(zeile('Fremd'), { key: 'Delete' });
    await tick();
    expect(rueckfrage.frage).toBeNull();
    await fireEvent.contextMenu(zeile('Jour fixe'));
    expect(screen.getByRole('menuitem', { name: /Löschen/ }).getAttribute('aria-disabled')).toBe('true');
  });
});

describe('Tastatur in der Liste', () => {
  it('Pfeiltasten wechseln den Eintrag', async () => {
    zeigen();
    await auswaehlen('Jour fixe');
    await fireEvent.keyDown(zeile('Jour fixe'), { key: 'ArrowDown' });
    await tick();
    expect(document.activeElement).toBe(zeile('Vorstand'));
    await fireEvent.keyDown(zeile('Vorstand'), { key: 'End' });
    await tick();
    expect(document.activeElement).toBe(zeile('Fremd'));
    await fireEvent.keyDown(zeile('Fremd'), { key: 'ArrowDown' });
    await fireEvent.keyDown(zeile('Fremd'), { key: 'Home' });
    await tick();
    expect(document.activeElement).toBe(zeile('Jour fixe'));
    expect(zeile('Jour fixe').classList.contains('ausgewaehlt')).toBe(true);
  });
});
