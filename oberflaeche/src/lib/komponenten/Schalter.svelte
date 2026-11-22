<script lang="ts">
  /** Ein-/Aus-Schalter mit Beschriftung (und optional einem (i)). */
  import type { Snippet } from 'svelte';

  let {
    an = $bindable(false),
    beschriftung,
    deaktiviert = false,
    aendern,
    info
  }: {
    an?: boolean;
    beschriftung: string;
    deaktiviert?: boolean;
    aendern?: (an: boolean) => void;
    info?: Snippet;
  } = $props();

  function umschalten() {
    if (deaktiviert) return;
    an = !an;
    aendern?.(an);
  }
</script>

<div class="schalter">
  <button
    type="button"
    role="switch"
    aria-checked={an}
    aria-label={beschriftung}
    disabled={deaktiviert}
    class="spur"
    class:an
    onclick={umschalten}
  >
    <span class="knauf"></span>
  </button>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <span class="text" onclick={umschalten}>{beschriftung}</span>
  {@render info?.()}
</div>

<style>
  .schalter {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-height: 30px;
  }

  .spur {
    position: relative;
    flex: none;
    width: 36px;
    height: 20px;
    padding: 0;
    border: none;
    border-radius: 10px;
    background: var(--feld-rand);
    cursor: pointer;
    transition: background 0.15s;
  }

  .spur.an {
    background: var(--akzent);
  }

  .spur:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .knauf {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
    transition: transform 0.15s;
  }

  .an .knauf {
    transform: translateX(16px);
  }

  .text {
    cursor: pointer;
    user-select: none;
  }
</style>
