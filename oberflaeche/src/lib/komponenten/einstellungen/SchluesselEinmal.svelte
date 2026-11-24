<script lang="ts">
  /** Ein neuer Zugangsschlüssel – genau einmal sichtbar, mit Kopierknopf. */
  import type { NeuerZugang } from '#lib/api/typen.ts';
  import { meldungen } from '#lib/stores/oberflaeche.svelte.ts';
  import Dialog from '../Dialog.svelte';

  let { zugang, schliessen }: { zugang: NeuerZugang | null; schliessen: () => void } = $props();

  async function kopieren() {
    if (!zugang) return;
    try {
      await navigator.clipboard.writeText(zugang.schluessel);
      meldungen.zeigen('Kopiert');
    } catch {
      meldungen.zeigen('Kopieren nicht möglich', 'fehler');
    }
  }
</script>

<Dialog offen={!!zugang} titel="Zugangsschlüssel „{zugang?.bezeichnung ?? ''}“" {schliessen} breite={520}>
  {#snippet kinder()}
    <p class="einmal">Wird nur jetzt angezeigt.</p>
    <div class="zeile">
      <code>{zugang?.schluessel}</code>
      <button class="knopf" type="button" onclick={kopieren}>Kopieren</button>
    </div>
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf primaer" type="button" onclick={schliessen}>Fertig</button>
  {/snippet}
</Dialog>

<style>
  .einmal {
    color: var(--warn);
    font-weight: 600;
    margin-bottom: 12px;
  }

  code {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    padding: 8px 10px;
    border-radius: 6px;
    background: var(--karte-2);
    color: var(--text);
    font-family: 'Cascadia Mono', Consolas, monospace;
    font-size: 12.5px;
  }
</style>
