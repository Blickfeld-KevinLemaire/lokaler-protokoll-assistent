<script lang="ts">
  /**
   * Rückfrage nur für Unwiderrufliches: nennt das Objekt, der Knopf sagt, was passiert („Löschen“).
   * Der Fokus liegt zuerst auf „Abbrechen“ – Enter löscht nicht aus Versehen.
   */
  import Dialog from './Dialog.svelte';

  let {
    offen,
    titel,
    text = '',
    verb = 'Löschen',
    bestaetigen,
    schliessen
  }: {
    offen: boolean;
    titel: string;
    text?: string;
    verb?: string;
    bestaetigen: () => void | Promise<void>;
    schliessen: () => void;
  } = $props();

  let laeuft = $state(false);

  async function ja() {
    laeuft = true;
    try {
      await bestaetigen();
    } finally {
      laeuft = false;
      schliessen();
    }
  }
</script>

<Dialog {offen} {titel} {schliessen} warnung breite={420}>
  {#snippet kinder()}
    {#if text}<p>{text}</p>{/if}
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf" type="button" onclick={schliessen}>Abbrechen</button>
    <button class="knopf gefahr-voll" type="button" disabled={laeuft} onclick={ja}>{verb}</button>
  {/snippet}
</Dialog>

<style>
  .gefahr-voll {
    background: var(--fehler);
    border-color: var(--fehler);
    color: #fff;
  }

  .gefahr-voll:hover:not(:disabled) {
    background: var(--fehler);
    border-color: var(--fehler);
    filter: brightness(0.92);
  }
</style>
