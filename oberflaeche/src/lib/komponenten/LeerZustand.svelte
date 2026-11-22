<script lang="ts">
  /** Leerzustand: ein Symbol, eine Überschrift, höchstens eine Hauptaktion – kein Erklärtext. */
  import type { Component, Snippet } from 'svelte';

  let {
    symbol: Symbol,
    titel,
    aktion,
    klein = false
  }: {
    symbol: Component<{ size?: number; strokeWidth?: number }>;
    titel: string;
    aktion?: Snippet;
    klein?: boolean;
  } = $props();
</script>

<div class="leerzustand" class:klein>
  <span class="kreis"><Symbol size={klein ? 22 : 28} strokeWidth={1.5} /></span>
  <p class="titel">{titel}</p>
  {#if aktion}<div class="aktion">{@render aktion()}</div>{/if}
</div>

<style>
  .leerzustand {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 56px 24px;
    text-align: center;
  }

  .leerzustand.klein {
    padding: 28px 16px;
    gap: 10px;
  }

  .kreis {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: var(--akzent-weich);
    color: var(--link);
  }

  .klein .kreis {
    width: 44px;
    height: 44px;
  }

  .titel {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
  }

  .klein .titel {
    font-size: 14px;
  }

  .aktion {
    margin-top: 4px;
  }
</style>
