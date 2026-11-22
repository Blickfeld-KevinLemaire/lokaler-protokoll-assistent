<script lang="ts">
  /** Modales Fenster auf Basis von <dialog>: Fokus bleibt drin, Escape schließt. */
  import type { Snippet } from 'svelte';

  let {
    offen,
    titel,
    schliessen,
    kinder,
    knoepfe,
    breite = 440,
    warnung = false
  }: {
    offen: boolean;
    titel: string;
    schliessen: () => void;
    kinder: Snippet;
    knoepfe?: Snippet;
    breite?: number;
    /** Warnung oder Rückfrage: `alertdialog` (Bildschirmleser lesen den Inhalt sofort vor). */
    warnung?: boolean;
  } = $props();

  let element: HTMLDialogElement | undefined = $state();
  const id = `dialog-${Math.random().toString(36).slice(2, 9)}`;

  $effect(() => {
    if (!element) return;
    if (offen && !element.open) element.showModal?.();
    if (!offen && element.open) element.close();
  });
</script>

<dialog
  bind:this={element}
  aria-labelledby={id}
  role={warnung ? 'alertdialog' : undefined}
  style:width="{breite}px"
  oncancel={(e) => {
    e.preventDefault();
    schliessen();
  }}
>
  {#if offen}
    <h2 {id}>{titel}</h2>
    <div class="inhalt">{@render kinder()}</div>
    {#if knoepfe}
      <div class="knoepfe">{@render knoepfe()}</div>
    {/if}
  {/if}
</dialog>

<style>
  dialog {
    max-width: calc(100vw - 48px);
    padding: 22px 24px 18px;
    border: 1px solid var(--rand);
    border-radius: 12px;
    background: var(--karte);
    color: var(--text);
    box-shadow: var(--schatten-hoch);
  }

  dialog::backdrop {
    background: rgba(10, 18, 32, 0.45);
  }

  h2 {
    font-size: 16px;
    margin-bottom: 10px;
  }

  .inhalt {
    color: var(--text-2);
    line-height: 1.5;
  }

  .knoepfe {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 20px;
  }
</style>
