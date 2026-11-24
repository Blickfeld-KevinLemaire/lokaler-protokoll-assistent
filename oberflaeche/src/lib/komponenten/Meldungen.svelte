<script lang="ts">
  /** Kurze Meldungen unten rechts; bleiben stehen, solange Maus oder Fokus darauf liegen. */
  import CircleAlert from '@lucide/svelte/icons/circle-alert';
  import CircleCheck from '@lucide/svelte/icons/circle-check';
  import Info from '@lucide/svelte/icons/info';
  import X from '@lucide/svelte/icons/x';
  import { meldungen } from '#lib/stores/oberflaeche.svelte.ts';
</script>

<div class="meldungen" role="status" aria-live="polite">
  {#each meldungen.liste as m (m.nr)}
    <div
      class="meldung {m.art}"
      role="group"
      aria-label={m.text}
      onmouseenter={() => meldungen.anhalten(m.nr)}
      onmouseleave={() => meldungen.weiter(m.nr)}
      onfocusin={() => meldungen.anhalten(m.nr)}
      onfocusout={() => meldungen.weiter(m.nr)}
    >
      <span class="symbol">
        {#if m.art === 'fehler'}<CircleAlert />{:else if m.art === 'ok'}<CircleCheck />{:else}<Info />{/if}
      </span>
      <span class="text">{m.text}</span>
      {#if m.aktion}
        <button
          class="knopf leise aktion"
          type="button"
          onclick={() => {
            m.aktion?.tun();
            meldungen.entfernen(m.nr);
          }}
        >
          {m.aktion.text}
        </button>
      {/if}
      <button
        class="symbolknopf"
        type="button"
        aria-label="Meldung schließen"
        onclick={() => meldungen.entfernen(m.nr)}
      >
        <X size={16} />
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
    padding: 6px 6px 6px 14px;
    border-radius: 10px;
    background: var(--karte);
    border: 1px solid var(--rand);
    box-shadow: var(--schatten-hoch);
  }

  .text {
    flex: 1;
  }

  .symbol {
    display: inline-flex;
  }

  .ok .symbol {
    color: var(--ok);
  }

  .fehler .symbol {
    color: var(--fehler);
  }

  .info .symbol {
    color: var(--akzent);
  }

  .aktion {
    height: 30px;
    padding: 0 10px;
    color: var(--link);
    font-weight: 600;
  }
</style>
