<script lang="ts">
  import { goto } from '$app/navigation';
  import { einrichtung } from '#lib/stores/einrichtung.svelte.ts';
  import { dialog } from '#lib/stores/oberflaeche.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import Dialog from './Dialog.svelte';

  const f = $derived(dialog.fehler);
  /** Fehlt die Einrichtung auf diesem Computer, führt der Knopf direkt dorthin (nur im Fenster). */
  const einrichten = $derived(!!f?.einrichten && einrichtung.verfuegbar(verbindung.info));

  function zuEinstellungen() {
    const abschnitt = f?.abschnitt;
    dialog.schliessen();
    if (abschnitt) void goto(`/einstellungen#${abschnitt}`);
  }

  function zurEinrichtung() {
    dialog.schliessen();
    void einrichtung.oeffnen();
  }
</script>

<Dialog offen={!!f} titel={f?.titel ?? ''} schliessen={() => dialog.schliessen()} warnung>
  {#snippet kinder()}
    <p class="text">{f?.text}</p>
  {/snippet}
  {#snippet knoepfe()}
    {#if einrichten}
      <button class="knopf" type="button" onclick={zuEinstellungen}>Einstellungen</button>
      <button class="knopf primaer" type="button" onclick={zurEinrichtung}>Jetzt einrichten</button>
    {:else if f?.abschnitt}
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
