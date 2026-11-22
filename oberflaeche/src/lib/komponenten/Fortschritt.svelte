<script lang="ts">
  /** Balken: mit Anteil (0..1) bestimmt, ohne (null) als ruhige Laufanimation. */
  let {
    anteil,
    dunkel = false,
    beschriftung = 'Fortschritt'
  }: { anteil: number | null | undefined; dunkel?: boolean; beschriftung?: string } = $props();

  const prozent = $derived(anteil == null ? null : Math.round(Math.min(1, Math.max(0, anteil)) * 100));
</script>

<div
  class="balken"
  class:dunkel
  role="progressbar"
  aria-label={beschriftung}
  aria-valuemin={0}
  aria-valuemax={100}
  aria-valuenow={prozent ?? undefined}
>
  {#if prozent === null}
    <div class="lauf"></div>
  {:else}
    <div class="fuellung" style:width="{prozent}%"></div>
  {/if}
</div>

<style>
  .balken {
    position: relative;
    height: 6px;
    border-radius: 3px;
    background: var(--rand);
    overflow: hidden;
  }

  .balken.dunkel {
    background: rgba(255, 255, 255, 0.12);
  }

  .fuellung {
    height: 100%;
    border-radius: 3px;
    background: var(--akzent);
    transition: width 0.6s ease;
  }

  .dunkel .fuellung {
    background: #4f8cff;
  }

  .lauf {
    position: absolute;
    inset: 0 auto 0 0;
    width: 35%;
    border-radius: 3px;
    background: var(--akzent);
    animation: lauf 1.6s ease-in-out infinite;
  }

  .dunkel .lauf {
    background: #4f8cff;
  }

  @keyframes lauf {
    0% {
      transform: translateX(-100%);
    }
    100% {
      transform: translateX(300%);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .lauf {
      animation: none;
      width: 100%;
      opacity: 0.4;
    }
  }
</style>
