<script lang="ts">
  /**
   * Kontextmenü (Rechtsklick, Menü-Taste, Umschalt+F10). Offen, solange es eingeblendet ist: Pfeiltasten, Pos1 und
   * Ende bewegen, ein Buchstabe springt zum passenden Eintrag, Enter oder Leertaste wählt. Esc und Tab schließen und
   * geben den Fokus zurück; ein Klick daneben oder Verlassen des Fensters schließt auch. Es bleibt ganz im Fenster.
   */
  import { onMount } from 'svelte';
  import { imFenster, naechster, perAnfangsbuchstabe, type MenuePunkt } from '$lib/logik/kontextmenue';

  let {
    x,
    y,
    punkte,
    beschriftung,
    waehlen,
    schliessen
  }: {
    /** Wo es aufgeht (Fensterkoordinaten): an der Maus oder unter dem Eintrag. */
    x: number;
    y: number;
    punkte: MenuePunkt[];
    beschriftung: string;
    waehlen: (id: string) => void;
    schliessen: () => void;
  } = $props();

  let menue: HTMLDivElement | undefined = $state();
  let lage = $state<{ links: number; oben: number } | null>(null);
  let aktiv = $state(0);
  let vorher: HTMLElement | null = null;

  onMount(() => {
    vorher = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (menue) {
      const r = menue.getBoundingClientRect();
      lage = imFenster(x, y, r.width, r.height, window.innerWidth, window.innerHeight);
    }
    fokussieren(0);
  });

  function fokussieren(i: number) {
    if (i < 0) return;
    aktiv = i;
    menue?.querySelectorAll<HTMLElement>('[role="menuitem"]')[i]?.focus();
  }

  function zu(fokusZurueck: boolean) {
    schliessen();
    if (fokusZurueck && vorher?.isConnected) vorher.focus();
  }

  function auswaehlen(i: number) {
    const p = punkte[i];
    if (!p || p.deaktiviert) return;
    // Erst schließen (Fokus zurück zum Eintrag), dann ausführen: Ein Dialog oder ein Eingabefeld nimmt ihn dann mit.
    // `waehlen` vorher lesen – nach dem Schließen kann es beim Aufrufer schon fehlen.
    const ausfuehren = waehlen;
    zu(true);
    ausfuehren(p.id);
  }

  function taste(e: KeyboardEvent) {
    switch (e.key) {
      case 'ArrowDown':
        fokussieren(naechster(punkte.length, aktiv, 1));
        break;
      case 'ArrowUp':
        fokussieren(naechster(punkte.length, aktiv, -1));
        break;
      case 'Home':
        fokussieren(0);
        break;
      case 'End':
        fokussieren(punkte.length - 1);
        break;
      case 'Escape':
      case 'Tab':
        zu(true);
        break;
      case 'Enter':
      case ' ':
        auswaehlen(aktiv);
        break;
      default:
        if (e.key.length !== 1 || e.ctrlKey || e.altKey || e.metaKey) return;
        fokussieren(perAnfangsbuchstabe(punkte, aktiv, e.key));
    }
    e.preventDefault();
    e.stopPropagation();
  }

  function aussen(e: PointerEvent) {
    if (menue && !menue.contains(e.target as Node)) zu(false);
  }
</script>

<svelte:window onpointerdowncapture={aussen} onresize={() => zu(false)} onblur={() => zu(false)} />

<div
  bind:this={menue}
  class="menue"
  role="menu"
  aria-label={beschriftung}
  tabindex="-1"
  style:left="{lage?.links ?? x}px"
  style:top="{lage?.oben ?? y}px"
  oncontextmenu={(e) => e.preventDefault()}
>
  {#each punkte as p, i (p.id)}
    {#if p.trenner && i > 0}<div class="trenner" role="separator"></div>{/if}
    <div
      class="punkt"
      class:gefahr={p.gefahr}
      class:aus={p.deaktiviert}
      role="menuitem"
      tabindex={i === aktiv ? 0 : -1}
      aria-disabled={p.deaktiviert ? 'true' : undefined}
      aria-keyshortcuts={p.taste}
      onclick={() => auswaehlen(i)}
      onkeydown={taste}
      onpointerenter={() => fokussieren(i)}
    >
      <span class="symbol" aria-hidden="true">
        {#if p.symbol}<p.symbol size={16} />{/if}
      </span>
      <span class="text">
        {p.text}
        {#if p.deaktiviert && p.hinweis}<span class="hinweis">{p.hinweis}</span>{/if}
      </span>
      {#if p.kuerzel}<span class="kuerzel" aria-hidden="true">{p.kuerzel}</span>{/if}
    </div>
  {/each}
</div>

<style>
  .menue {
    position: fixed;
    z-index: 60;
    min-width: 230px;
    max-width: 320px;
    padding: 5px;
    border: 1px solid var(--rand);
    border-radius: var(--radius);
    background: var(--karte);
    box-shadow: var(--schatten-hoch);
    outline: none;
  }

  .punkt {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-radius: var(--radius-klein);
    color: var(--text);
    font-size: 13.5px;
    cursor: default;
    outline: none;
    user-select: none;
  }

  .punkt:focus {
    background: var(--akzent-weich);
  }

  .punkt:focus-visible {
    box-shadow: inset 0 0 0 1px var(--fokus-farbe);
  }

  .symbol {
    display: inline-flex;
    flex: none;
    width: 16px;
    color: var(--text-2);
  }

  .text {
    flex: 1;
    min-width: 0;
  }

  .hinweis {
    display: block;
    font-size: 11.5px;
    color: var(--text-3);
  }

  .kuerzel {
    flex: none;
    margin-left: 16px;
    font-size: 12px;
    color: var(--text-3);
  }

  .gefahr,
  .gefahr .symbol {
    color: var(--fehler);
  }

  .aus,
  .aus .symbol {
    color: var(--text-3);
  }

  .trenner {
    height: 1px;
    margin: 5px 4px;
    background: var(--rand);
  }
</style>
