<script lang="ts">
  /**
   * Die Liste unter „Transkripte“. Ein Klick öffnet wie bisher. Dazu ein Kontextmenü (Rechtsklick, Menü-Taste,
   * Umschalt+F10) und Tasten am ausgewählten Eintrag: Enter öffnet, F2 benennt um, Entf löscht, Pfeiltasten wechseln
   * den Eintrag. Wie im Explorer benennt auch ein Klick auf den Namen des schon ausgewählten Eintrags um – nach einer
   * kurzen Pause, damit ein Doppelklick weiter öffnet.
   */
  import Check from '@lucide/svelte/icons/check';
  import Copy from '@lucide/svelte/icons/copy';
  import Download from '@lucide/svelte/icons/download';
  import FileText from '@lucide/svelte/icons/file-text';
  import FolderOpen from '@lucide/svelte/icons/folder-open';
  import Pencil from '@lucide/svelte/icons/pencil';
  import Share2 from '@lucide/svelte/icons/share-2';
  import Sparkles from '@lucide/svelte/icons/sparkles';
  import SquareArrowOutUpRight from '@lucide/svelte/icons/square-arrow-out-up-right';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import Users from '@lucide/svelte/icons/users';
  import { tick, type Component } from 'svelte';
  import { api } from '#lib/api/client.ts';
  import type { Besprechung, BesprechungDetails } from '#lib/api/typen.ts';
  import {
    besprechungsMenue,
    geloeschtMeldung,
    loeschFrage,
    type BesprechungsAktion
  } from '#lib/logik/besprechungsmenue.ts';
  import { datumText, dauerText } from '#lib/logik/format.ts';
  import { oeffnetMenue } from '#lib/logik/kontextmenue.ts';
  import { ohneBesitzer } from '#lib/logik/teilen.ts';
  import { transkriptAlsText } from '#lib/logik/transkript.ts';
  import { VerzoegerterKlick } from '#lib/logik/verzoegerterKlick.ts';
  import { systempromptFuer, vorlageVorwahl } from '#lib/logik/vorlagen.ts';
  import { startMeldung } from '#lib/logik/warteschlange.ts';
  import { inZwischenablage } from '#lib/logik/zwischenablage.ts';
  import { einstellungen } from '#lib/stores/einstellungen.svelte.ts';
  import { dialog, meldungen, rueckfrage } from '#lib/stores/oberflaeche.svelte.ts';
  import { personen } from '#lib/stores/personen.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import { zustand } from '#lib/stores/zustand.svelte.ts';
  import Kontextmenue from '../Kontextmenue.svelte';
  import ExportDialog from './ExportDialog.svelte';
  import NameFeld from './NameFeld.svelte';
  import TeilenDialog from './TeilenDialog.svelte';

  let {
    eintraege,
    oeffnen,
    geaendert
  }: {
    eintraege: Besprechung[];
    oeffnen: (b: Besprechung) => void;
    /** Umbenannt, gelöscht, exportiert, geteilt: Liste neu laden. */
    geaendert: () => void;
  } = $props();

  const SYMBOLE: Record<BesprechungsAktion, Component<{ size?: number }>> = {
    oeffnen: SquareArrowOutUpRight,
    umbenennen: Pencil,
    dokument: FileText,
    explorer: FolderOpen,
    zusammenfassung: Sparkles,
    exportieren: Download,
    kopieren: Copy,
    teilen: Share2,
    loeschen: Trash2
  };

  let tabelle: HTMLDivElement | undefined = $state();
  /** Ausgewählt per Rechtsklick oder Tastatur – ein einfacher Klick öffnet ja sofort. */
  let ausgewaehlt = $state<string | null>(null);
  let bearbeitet = $state<string | null>(null);
  let menue = $state<{ b: Besprechung; x: number; y: number } | null>(null);
  let exportDetails = $state<BesprechungDetails | null>(null);
  let teilenDetails = $state<BesprechungDetails | null>(null);
  /** Neue Namen, bis die Liste neu geladen ist (sonst stünde kurz der alte da). */
  let namen = $state<Record<string, string>>({});

  const klick = new VerzoegerterKlick();
  let zeiger = false;
  let warAusgewaehlt = false;
  let tastenMenueZeit = 0;

  $effect(() => {
    void eintraege;
    namen = {};
  });

  $effect(() => () => klick.abbrechen());

  const desktop = $derived(verbindung.info?.rolle === 'desktop');

  function titel(b: Besprechung): string {
    return namen[b.id] ?? b.titel;
  }

  function eigen(b: Besprechung): boolean {
    return b.eigen !== false;
  }

  function zusammenfassungLaeuft(b: Besprechung): boolean {
    return zustand.auftraege.some(
      (a) =>
        a.art === 'auswertung' &&
        a.angaben?.transkript === b.transkript &&
        (a.status === 'wartet' || a.status === 'laeuft')
    );
  }

  function punkteFuer(b: Besprechung) {
    return besprechungsMenue(b, {
      ordnerOeffnen: !!verbindung.info?.faehigkeiten.ordner_oeffnen,
      mehrbenutzer: verbindung.mehrbenutzer,
      zusammenfassungLaeuft: zusammenfassungLaeuft(b)
    }).map((p) => ({ ...p, symbol: SYMBOLE[p.id] }));
  }

  function zeile(id: string): HTMLElement | undefined {
    return [...(tabelle?.querySelectorAll<HTMLElement>('[data-id]') ?? [])].find(
      (el) => el.dataset.id === id
    );
  }

  async function zeileFokussieren(id: string) {
    await tick();
    zeile(id)?.focus();
  }

  // ------------------------------------------------------------------ Maus

  function zeigerDruck(b: Besprechung) {
    zeiger = true;
    warAusgewaehlt = ausgewaehlt === b.id;
  }

  function fokus(b: Besprechung) {
    // Per Tastatur angekommen: ausgewählt. Per Maus nicht – der Klick öffnet gleich.
    if (!zeiger) ausgewaehlt = b.id;
    zeiger = false;
  }

  function klicken(e: MouseEvent, b: Besprechung) {
    const vorher = warAusgewaehlt;
    zeiger = false;
    warAusgewaehlt = false;
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    const aufName = (e.target as HTMLElement | null)?.closest('[data-name]');
    if (!vorher || !aufName || !eigen(b)) return; // wie bisher: der Verweis öffnet
    e.preventDefault();
    if (e.detail > 1) {
      klick.abbrechen();
      oeffnen(b);
      return;
    }
    klick.klick(() => {
      if (ausgewaehlt === b.id) bearbeitet = b.id;
    });
  }

  function doppelklick(e: MouseEvent) {
    // Geöffnet hat schon der zweite Klick (oder der Verweis); hier nur kein Umbenennen mehr.
    if (klick.wartet) e.preventDefault();
    klick.abbrechen();
  }

  function rechtsklick(e: MouseEvent, b: Besprechung) {
    e.preventDefault();
    zeiger = false;
    klick.abbrechen();
    if (performance.now() - tastenMenueZeit < 400) return; // kam von der Menü-Taste: schon offen
    ausgewaehlt = b.id;
    (e.currentTarget as HTMLElement).focus();
    menue = { b, x: e.clientX, y: e.clientY };
  }

  // ------------------------------------------------------------------ Tastatur

  function taste(e: KeyboardEvent, b: Besprechung) {
    zeiger = false;
    ausgewaehlt = b.id;
    if (oeffnetMenue(e)) {
      e.preventDefault();
      tastenMenueZeit = performance.now();
      const el =
        (e.currentTarget as HTMLElement).querySelector('[data-name]') ?? (e.currentTarget as HTMLElement);
      const r = el.getBoundingClientRect();
      menue = { b, x: r.left, y: r.bottom + 4 };
      return;
    }
    const i = eintraege.findIndex((x) => x.id === b.id);
    switch (e.key) {
      case 'F2':
        if (eigen(b)) bearbeitet = b.id;
        break;
      case 'Delete':
        void loeschen(b);
        break;
      case 'ArrowDown':
      case 'ArrowUp': {
        const ziel = eintraege[e.key === 'ArrowDown' ? i + 1 : i - 1];
        if (ziel) {
          ausgewaehlt = ziel.id;
          void zeileFokussieren(ziel.id);
        }
        break;
      }
      case 'Home':
      case 'End': {
        const ziel = e.key === 'Home' ? eintraege[0] : eintraege.at(-1);
        if (ziel) {
          ausgewaehlt = ziel.id;
          void zeileFokussieren(ziel.id);
        }
        break;
      }
      default:
        return; // Enter: der Verweis öffnet
    }
    e.preventDefault();
  }

  // ------------------------------------------------------------------ Befehle

  /** Fest an diesen Eintrag gebunden: Beim Ausführen ist das Menü (und mit ihm `menue`) schon zu. */
  function waehlenFuer(b: Besprechung): (id: string) => void {
    return (id) => void ausfuehren(id as BesprechungsAktion, b);
  }

  async function ausfuehren(aktion: BesprechungsAktion, b: Besprechung) {
    switch (aktion) {
      case 'oeffnen':
        oeffnen(b);
        return;
      case 'umbenennen':
        bearbeitet = b.id;
        return;
      case 'dokument':
        return mitFehler(() => api.dokumentOeffnen(b.id), 'Dokument nicht geöffnet');
      case 'explorer':
        return mitFehler(() => api.ordnerOeffnen(b.dokument ?? b.transkript), 'Nicht im Explorer gezeigt');
      case 'zusammenfassung':
        return zusammenfassen(b);
      case 'exportieren':
        return mitFehler(
          async () => (exportDetails = await api.besprechung(b.id)),
          'Transkript nicht geladen'
        );
      case 'kopieren':
        return kopieren(b);
      case 'teilen':
        return mitFehler(
          async () => (teilenDetails = await api.besprechung(b.id)),
          'Transkript nicht geladen'
        );
      case 'loeschen':
        return loeschen(b);
    }
  }

  async function mitFehler(tun: () => Promise<unknown>, titelText: string) {
    try {
      await tun();
    } catch (e) {
      dialog.zeigen(e, titelText);
    }
  }

  async function umbenennen(b: Besprechung, name: string, perTaste: boolean) {
    bearbeitenEnde(b, perTaste);
    namen = { ...namen, [b.id]: name };
    try {
      await api.besprechungUmbenennen(b.id, name);
      geaendert();
    } catch (e) {
      const { [b.id]: _weg, ...rest } = namen;
      namen = rest;
      dialog.zeigen(e, 'Umbenennen hat nicht geklappt');
    }
  }

  /** Mit Enter oder Esc beendet: Das Feld ist weg, der Fokus gehört wieder auf die Zeile. Ging er durch einen Klick
   * woandershin, bleibt er dort. */
  function bearbeitenEnde(b: Besprechung, perTaste: boolean) {
    bearbeitet = null;
    if (perTaste) void zeileFokussieren(b.id);
  }

  async function zusammenfassen(b: Besprechung) {
    try {
      const vorlagen = await api.vorlagen().catch(() => []);
      const vorlage = vorlageVorwahl(vorlagen, einstellungen.werte?.aktive_systemprompt_vorlage);
      const neu = await api.auswertungStarten(b.transkript, systempromptFuer(vorlagen, vorlage));
      zustand.auftragAktualisieren(neu);
      meldungen.zeigen(startMeldung(neu, zustand.auftraege) ?? 'Zusammenfassung wird erstellt', 'info');
    } catch (e) {
      dialog.zeigen(e, 'Start nicht möglich');
    }
  }

  async function kopieren(b: Besprechung) {
    try {
      const text = transkriptAlsText((await api.besprechung(b.id)).segmente);
      if (!text) {
        meldungen.zeigen('Das Transkript ist leer', 'info');
        return;
      }
      await inZwischenablage(text);
      meldungen.zeigen('Transkript kopiert');
    } catch (e) {
      dialog.zeigen(e, 'Kopieren hat nicht geklappt');
    }
  }

  async function loeschen(b: Besprechung) {
    if (!eigen(b)) return;
    if (zusammenfassungLaeuft(b)) {
      meldungen.zeigen('Löschen geht erst, wenn die Zusammenfassung fertig ist.', 'info');
      return;
    }
    const name = titel(b);
    if (!(await rueckfrage.fragen(loeschFrage(name, !desktop)))) {
      void zeileFokussieren(b.id);
      return;
    }
    try {
      const antwort = await api.besprechungLoeschen(b.id);
      if (ausgewaehlt === b.id) ausgewaehlt = null;
      meldungen.zeigen(geloeschtMeldung(name, antwort.papierkorb, desktop));
      geaendert();
    } catch (e) {
      dialog.zeigen(e, 'Löschen hat nicht geklappt');
    }
  }
</script>

{#snippet spalten(b: Besprechung)}
  <span role="cell" class="leise">{datumText(b.zeit)}</span>
  <span role="cell" class="leise">{dauerText(b.dauer_sekunden)}</span>
  <span role="cell" class="leise">{b.anzahl_sprecher ?? '–'}</span>
  <span role="cell">
    {#if b.hat_protokoll}
      <span class="marke ja"><Check size={16} /> Vorhanden</span>
    {:else}
      <span class="marke">–</span>
    {/if}
  </span>
{/snippet}

<div class="karte tabelle" role="table" aria-label="Transkripte" bind:this={tabelle}>
  <div class="zeile kopfzeile" role="row">
    <span role="columnheader">Titel</span>
    <span role="columnheader">Datum</span>
    <span role="columnheader">Dauer</span>
    <span role="columnheader">Sprecher</span>
    <span role="columnheader">Zusammenfassung</span>
  </div>
  {#each eintraege as b (b.id)}
    {#if bearbeitet === b.id}
      <div class="zeile ausgewaehlt" role="row" data-id={b.id}>
        <span class="titel" role="cell">
          <NameFeld
            wert={titel(b)}
            beschriftung="Neuer Name für „{titel(b)}“"
            speichern={(name, perTaste) => umbenennen(b, name, perTaste)}
            abbrechen={(perTaste) => bearbeitenEnde(b, perTaste)}
          />
        </span>
        {@render spalten(b)}
      </div>
    {:else}
      <a
        class="zeile"
        class:ausgewaehlt={ausgewaehlt === b.id}
        role="row"
        href="/besprechungen?id={encodeURIComponent(b.id)}"
        data-id={b.id}
        aria-keyshortcuts="Enter F2 Delete Shift+F10"
        onpointerdown={() => zeigerDruck(b)}
        onfocus={() => fokus(b)}
        onclick={(e) => klicken(e, b)}
        ondblclick={doppelklick}
        oncontextmenu={(e) => rechtsklick(e, b)}
        onkeydown={(e) => taste(e, b)}
      >
        <span class="titel" role="cell">
          <span class="text" data-name>{titel(b)}</span>
          {#if b.eigen === false}
            <span class="geteilt">geteilt von {personen.anzeigename(b.besitzer)}</span>
          {:else if verbindung.mehrbenutzer && b.geteilt_mit?.length}
            <span class="geteilt leise" title="Geteilt"><Users size={16} /></span>
          {:else if ohneBesitzer(b, verbindung.mehrbenutzer)}
            <span class="geteilt leise">ohne Besitzer</span>
          {/if}
        </span>
        {@render spalten(b)}
      </a>
    {/if}
  {/each}
</div>

{#if menue}
  {#key menue}
    <Kontextmenue
      x={menue.x}
      y={menue.y}
      punkte={punkteFuer(menue.b)}
      beschriftung="Aktionen für „{titel(menue.b)}“"
      waehlen={waehlenFuer(menue.b)}
      schliessen={() => (menue = null)}
    />
  {/key}
{/if}

{#if exportDetails}
  <ExportDialog
    offen={true}
    details={exportDetails}
    schliessen={() => (exportDetails = null)}
    exportiert={geaendert}
  />
{/if}

{#if teilenDetails}
  <TeilenDialog
    offen={true}
    details={teilenDetails}
    schliessen={() => (teilenDetails = null)}
    gespeichert={geaendert}
  />
{/if}

<style>
  .tabelle {
    overflow: hidden;
  }

  .zeile {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 150px 110px 80px 140px;
    gap: 16px;
    align-items: center;
    padding: 12px 18px;
    border-top: 1px solid var(--rand);
    color: var(--text);
  }

  a.zeile:hover {
    background: var(--karte-2);
    text-decoration: none;
  }

  .zeile.ausgewaehlt,
  a.zeile.ausgewaehlt:hover {
    background: var(--akzent-weich);
  }

  a.zeile:focus-visible {
    outline: none;
    box-shadow: inset 0 0 0 2px var(--fokus-farbe);
  }

  div.zeile.ausgewaehlt {
    padding-top: 7px;
    padding-bottom: 7px;
  }

  .kopfzeile {
    border-top: none;
    padding-top: 10px;
    padding-bottom: 10px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-3);
    background: var(--karte-2);
  }

  .titel {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    font-weight: 500;
  }

  .titel .text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .geteilt {
    flex: none;
    padding: 1px 8px;
    border-radius: 9px;
    background: var(--akzent-weich);
    color: var(--link);
    font-size: 12px;
    font-weight: 500;
  }

  .geteilt.leise {
    background: none;
    padding: 0;
  }

  .marke {
    font-size: 12.5px;
    color: var(--text-3);
  }

  .marke.ja {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--ok);
    font-weight: 500;
  }

  .geteilt.leise {
    display: inline-flex;
    color: var(--text-3);
  }
</style>
