<script lang="ts">
  import { meldungen } from '$lib/stores/oberflaeche.svelte';
</script>

<div class="meldungen" role="status" aria-live="polite">
  {#each meldungen.liste as m (m.nr)}
    <div class="meldung {m.art}">
      <span aria-hidden="true">{m.art === 'fehler' ? '!' : m.art === 'ok' ? '✓' : 'ℹ'}</span>
      <span>{m.text}</span>
      <button
        class="symbolknopf"
        type="button"
        aria-label="Schließen"
        onclick={() => meldungen.entfernen(m.nr)}
      >
        ✕
      </button>
    </div>
  {/each}
</div>

<style>
  .meldungen {
    position: fixed;
    right: 20px;
    bottom: 20px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    gap: 8px;
    pointer-events: none;
  }

  .meldung {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 260px;
    max-width: 420px;
    padding: 8px 8px 8px 14px;
    border-radius: 10px;
    background: var(--karte);
    border: 1px solid var(--rand);
    box-shadow: var(--schatten-hoch);
  }

  .meldung span:nth-child(2) {
    flex: 1;
  }

  .ok > span:first-child {
    color: var(--ok);
    font-weight: 700;
  }

  .fehler > span:first-child {
    color: var(--fehler);
    font-weight: 700;
  }

  .info > span:first-child {
    color: var(--akzent);
  }
</style>
