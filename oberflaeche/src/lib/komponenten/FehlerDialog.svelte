<script lang="ts">
  import { goto } from '$app/navigation';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import Dialog from './Dialog.svelte';

  const f = $derived(dialog.fehler);

  function zuEinstellungen() {
    const abschnitt = f?.abschnitt;
    dialog.schliessen();
    if (abschnitt) void goto(`/einstellungen#${abschnitt}`);
  }
</script>

<Dialog offen={!!f} titel={f?.titel ?? ''} schliessen={() => dialog.schliessen()}>
  {#snippet kinder()}
    <p class="text">{f?.text}</p>
  {/snippet}
  {#snippet knoepfe()}
    {#if f?.abschnitt}
      <button class="knopf" type="button" onclick={() => dialog.schliessen()}>Schließen</button>
      <button class="knopf primaer" type="button" onclick={zuEinstellungen}>Einstellungen öffnen</button>
    {:else}
      <button class="knopf primaer" type="button" onclick={() => dialog.schliessen()}>OK</button>
    {/if}
  {/snippet}
</Dialog>

<style>
  .text {
    white-space: pre-line;
  }
</style>
