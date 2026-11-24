<script lang="ts">
  /**
   * Namen direkt in der Liste ändern: Enter speichert, Esc bricht ab, Verlassen des Felds speichert. Leer oder
   * unverändert ist kein neuer Name – dann bleibt alles, wie es war.
   */
  import { onMount, untrack } from 'svelte';

  let {
    wert,
    beschriftung = 'Neuer Name',
    speichern,
    abbrechen
  }: {
    wert: string;
    beschriftung?: string;
    /** `perTaste`: mit Enter bzw. Esc beendet (dann gehört der Fokus zurück), sonst durch Verlassen des Felds. */
    speichern: (name: string, perTaste: boolean) => void;
    abbrechen: (perTaste: boolean) => void;
  } = $props();

  let feld: HTMLInputElement | undefined = $state();
  let text = $state(untrack(() => wert));
  let erledigt = false;

  onMount(() => {
    feld?.focus();
    feld?.select();
  });

  function fertig(uebernehmen: boolean, perTaste: boolean) {
    if (erledigt) return;
    erledigt = true;
    const neu = text.trim();
    if (uebernehmen && neu && neu !== wert) speichern(neu, perTaste);
    else abbrechen(perTaste);
  }

  function taste(e: KeyboardEvent) {
    if (e.key === 'Enter') fertig(true, true);
    else if (e.key === 'Escape') fertig(false, true);
    else return;
    e.preventDefault();
    e.stopPropagation();
  }
</script>

<input
  bind:this={feld}
  bind:value={text}
  class="feld name"
  type="text"
  aria-label={beschriftung}
  maxlength="120"
  spellcheck="false"
  onkeydown={taste}
  onblur={() => fertig(true, false)}
/>

<style>
  .name {
    width: 100%;
    height: 30px;
    padding: 3px 8px;
    font-weight: 500;
  }
</style>
