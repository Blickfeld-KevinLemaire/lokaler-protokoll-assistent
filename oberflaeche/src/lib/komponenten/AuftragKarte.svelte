<script lang="ts">
  /** Ein Auftrag mit Fortschritt und Live-Text; bei Fehlern die Meldungen eingeklappt unter „Details“. */
  import { api } from '$lib/api/client';
  import type { Auftrag } from '$lib/api/typen';
  import { restzeitFuerAuftrag } from '$lib/logik/restzeit';
  import { stufenText } from '$lib/logik/stufen';
  import { auftragTitel, platzInReihe } from '$lib/logik/warteschlange';
  import { dialog, uhr } from '$lib/stores/oberflaeche.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Fortschritt from './Fortschritt.svelte';

  let { auftrag, schliessen }: { auftrag: Auftrag; schliessen?: () => void } = $props();

  let textfeld: HTMLDivElement | undefined = $state();

  const jetzt = $derived(zustand.jetztDienst(uhr.jetzt));
  const restzeit = $derived(
    auftrag.status === 'laeuft'
      ? restzeitFuerAuftrag(auftrag.id, auftrag.fortschritt, auftrag.gestartet, jetzt)
      : ''
  );
  const platz = $derived(platzInReihe(zustand.auftraege, auftrag.id));
  const ergebnis = $derived(
    (auftrag.ergebnis?.transkript_json as string | undefined) ??
      (auftrag.angaben?.transkript as string | undefined)
  );

  $effect(() => {
    void auftrag.vorschau;
    if (textfeld) textfeld.scrollTop = textfeld.scrollHeight;
  });

  async function abbrechen() {
    try {
      await api.auftragAbbrechen(auftrag.id);
    } catch (e) {
      dialog.zeigen(e, 'Abbrechen hat nicht geklappt');
    }
  }
</script>

<section class="karte auftrag" aria-label="Verarbeitung">
  <div class="kopf">
    <div class="titel">
      <h2>{auftragTitel(auftrag)}</h2>
      <span class="zustand {auftrag.status}">
        {#if auftrag.status === 'wartet'}
          Wartet{platz ? ` · Platz ${platz}` : ''}
        {:else if auftrag.status === 'laeuft'}
          {stufenText(auftrag.stufe, auftrag.status)}
        {:else if auftrag.status === 'fertig'}
          Fertig
        {:else if auftrag.status === 'fehler'}
          Hat nicht geklappt
        {:else}
          Abgebrochen
        {/if}
      </span>
    </div>
    {#if auftrag.status === 'laeuft' || auftrag.status === 'wartet'}
      <button class="knopf leise" type="button" onclick={abbrechen}>Abbrechen</button>
    {:else}
      {#if auftrag.status === 'fertig' && ergebnis}
        <a class="knopf primaer" href="/besprechungen?transkript={encodeURIComponent(ergebnis)}">Öffnen</a>
      {/if}
      {#if schliessen}
        <button class="symbolknopf" type="button" aria-label="Schließen" onclick={schliessen}>✕</button>
      {/if}
    {/if}
  </div>

  {#if auftrag.status === 'laeuft'}
    <Fortschritt anteil={auftrag.fortschritt} />
    <div class="fuss">
      <span>{auftrag.fortschritt != null ? `${Math.round(auftrag.fortschritt * 100)} %` : ''}</span>
      <span>{restzeit}</span>
    </div>
  {/if}

  {#if auftrag.vorschau && auftrag.status !== 'fehler'}
    <div class="vorschau" bind:this={textfeld} aria-live="off">{auftrag.vorschau}</div>
  {/if}

  {#if auftrag.status === 'fehler'}
    {#if auftrag.fehler}<p class="fehlertext">{auftrag.fehler}</p>{/if}
    {#if auftrag.meldungen?.length}
      <details class="details">
        <summary>Details</summary>
        <pre>{auftrag.meldungen.join('\n')}</pre>
      </details>
    {/if}
  {/if}
</section>

<style>
  .auftrag {
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .kopf {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .titel {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  h2 {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .zustand {
    font-size: 13px;
    color: var(--text-2);
  }

  .zustand.fertig {
    color: var(--ok);
  }

  .zustand.fehler {
    color: var(--fehler);
  }

  .fuss {
    display: flex;
    justify-content: space-between;
    font-size: 12.5px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  .vorschau {
    max-height: 220px;
    overflow-y: auto;
    padding: 12px 14px;
    border-radius: 8px;
    background: var(--karte-2);
    border: 1px solid var(--rand);
    white-space: pre-wrap;
    line-height: 1.55;
    color: var(--text);
  }

  .details summary {
    cursor: pointer;
    color: var(--text-2);
    font-size: 13px;
  }

  .details pre {
    max-height: 200px;
    overflow: auto;
    font-size: 12px;
    padding: 10px;
    border-radius: 6px;
    background: var(--karte-2);
    white-space: pre-wrap;
  }
</style>
