<script lang="ts">
  /** Vollbild, solange der Dienst startet, neu startet oder nicht starten konnte. */
  let { zustand, meldung = '' }: { zustand: 'startet' | 'neustart' | 'fehlgeschlagen'; meldung?: string } =
    $props();
</script>

<main class="start" aria-busy={zustand !== 'fehlgeschlagen'}>
  <img src="/vermerk_logo_hell.png" alt="VERMERK" width="220" height="49" />
  {#if zustand === 'fehlgeschlagen'}
    <h1>VERMERK konnte nicht starten</h1>
    {#if meldung}<p class="meldung">{meldung}</p>{/if}
    <p class="tipp">Bitte VERMERK schließen und neu starten.</p>
  {:else}
    <div class="punkte" aria-hidden="true"><span></span><span></span><span></span></div>
    <p class="meldung">{zustand === 'neustart' ? 'Wird neu gestartet …' : 'Wird gestartet …'}</p>
  {/if}
</main>

<style>
  .start {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
    background: var(--sb-bg);
    color: var(--sb-text);
    text-align: center;
    padding: 24px;
  }

  h1 {
    color: #fff;
    font-size: 18px;
  }

  .meldung {
    color: var(--sb-muted);
    max-width: 420px;
  }

  .tipp {
    color: var(--sb-text);
    font-weight: 600;
  }

  .punkte {
    display: flex;
    gap: 8px;
  }

  .punkte span {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--sb-muted);
    animation: puls 1.2s ease-in-out infinite;
  }

  .punkte span:nth-child(2) {
    animation-delay: 0.15s;
  }

  .punkte span:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes puls {
    0%,
    100% {
      opacity: 0.3;
    }
    50% {
      opacity: 1;
    }
  }
</style>
