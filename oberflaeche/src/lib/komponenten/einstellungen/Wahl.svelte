<script lang="ts" generics="T extends string">
  /** Segmentierte Auswahl (wie Radioknöpfe, aber kompakt). */
  let {
    optionen,
    wert,
    beschriftung,
    aendern
  }: {
    optionen: { wert: T; text: string }[];
    wert: T | undefined;
    beschriftung: string;
    aendern: (wert: T) => void;
  } = $props();

  const name = `wahl-${Math.random().toString(36).slice(2, 9)}`;
</script>

<div class="wahl" role="radiogroup" aria-label={beschriftung}>
  {#each optionen as o (o.wert)}
    <label class:aktiv={o.wert === wert}>
      <input type="radio" {name} value={o.wert} checked={o.wert === wert} onchange={() => aendern(o.wert)} />
      {o.text}
    </label>
  {/each}
</div>

<style>
  .wahl {
    display: inline-flex;
    padding: 3px;
    gap: 2px;
    border-radius: 9px;
    background: var(--karte-2);
    border: 1px solid var(--rand);
  }

  label {
    position: relative;
    padding: 6px 14px;
    border-radius: 7px;
    color: var(--text-2);
    cursor: pointer;
    font-weight: 500;
    white-space: nowrap;
  }

  label:hover {
    color: var(--text);
  }

  label.aktiv {
    background: var(--karte);
    color: var(--text);
    box-shadow: var(--schatten);
  }

  input {
    position: absolute;
    opacity: 0;
    inset: 0;
    margin: 0;
    cursor: pointer;
  }

  label:has(input:focus-visible) {
    box-shadow: var(--fokus);
  }
</style>
