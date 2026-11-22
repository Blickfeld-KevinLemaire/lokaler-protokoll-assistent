<script lang="ts">
  /** Kleines (i) neben einer Beschriftung: Frage als Titel, ein, zwei freundliche Sätze. */
  let {
    frage,
    text,
    richtung = 'unten'
  }: { frage: string; text: string; richtung?: 'unten' | 'oben' } = $props();

  const id = `info-${Math.random().toString(36).slice(2, 9)}`;
  let offen = $state(false);
  let fest = $state(false);
  let wurzel: HTMLSpanElement | undefined = $state();
  let nachLinks = $state(false);

  // Nahe am rechten Rand öffnet die Blase nach links, damit nichts abgeschnitten wird.
  $effect(() => {
    if (!offen || !wurzel) return;
    nachLinks = wurzel.getBoundingClientRect().left + 280 > window.innerWidth - 16;
  });

  function umschalten() {
    fest = !fest;
    offen = fest;
  }

  function schliessen() {
    offen = false;
    fest = false;
  }

  function taste(e: KeyboardEvent) {
    if (e.key === 'Escape' && offen) {
      e.stopPropagation();
      schliessen();
    }
  }

  function aussen(e: MouseEvent) {
    if (fest && wurzel && !wurzel.contains(e.target as Node)) schliessen();
  }
</script>

<svelte:window onclick={aussen} />

<span class="info" bind:this={wurzel} role="presentation" onmouseleave={() => !fest && (offen = false)}>
  <button
    type="button"
    class="i"
    aria-label={frage}
    aria-describedby={offen ? id : undefined}
    aria-expanded={offen}
    onclick={umschalten}
    onmouseenter={() => (offen = true)}
    onfocus={() => (offen = true)}
    onblur={() => !fest && (offen = false)}
    onkeydown={taste}
  >
    i
  </button>
  {#if offen}
    <span class="blase" class:oben={richtung === 'oben'} class:links={nachLinks} role="tooltip" {id}>
      <strong>{frage}</strong>
      <span>{text}</span>
    </span>
  {/if}
</span>

<style>
  .info {
    position: relative;
    display: inline-flex;
    vertical-align: middle;
  }

  .i {
    width: 16px;
    height: 16px;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--text-3);
    background: transparent;
    color: var(--text-2);
    font:
      italic 600 10.5px/1 Georgia,
      'Times New Roman',
      serif;
    cursor: help;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .i:hover,
  .i[aria-expanded='true'] {
    border-color: var(--akzent);
    color: var(--akzent);
  }

  .blase {
    position: absolute;
    z-index: 40;
    top: calc(100% + 8px);
    left: -12px;
    width: 260px;
    padding: 12px 14px;
    border-radius: var(--radius);
    background: var(--karte);
    border: 1px solid var(--rand);
    box-shadow: var(--schatten-hoch);
    color: var(--text);
    font-size: 13px;
    font-weight: 400;
    line-height: 1.45;
    display: flex;
    flex-direction: column;
    gap: 4px;
    text-align: left;
    white-space: normal;
  }

  .blase.links {
    left: auto;
    right: -12px;
  }

  .blase.oben {
    top: auto;
    bottom: calc(100% + 8px);
  }

  .blase strong {
    font-weight: 600;
  }

  .blase span {
    color: var(--text-2);
  }
</style>
