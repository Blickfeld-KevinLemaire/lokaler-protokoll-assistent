<script lang="ts">
  import { beforeNavigate } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { BesprechungDetails } from '$lib/api/typen';
  import { datumText, dauerText } from '$lib/logik/format';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Datenschutz from '../Datenschutz.svelte';
  import Reiter from '../Reiter.svelte';
  import Dateien from './Dateien.svelte';
  import ExportDialog from './ExportDialog.svelte';
  import SprecherListe from './SprecherListe.svelte';
  import Transkript from './Transkript.svelte';
  import Zusammenfassung from './Zusammenfassung.svelte';

  let { id }: { id: string } = $props();

  const REITER = [
    { id: 'transkript', text: 'Transkript' },
    { id: 'sprecher', text: 'Sprecher' },
    { id: 'zusammenfassung', text: 'Zusammenfassung' },
    { id: 'dateien', text: 'Dateien' }
  ];

  let details = $state<BesprechungDetails | null>(null);
  let reiter = $state(page.url.searchParams.get('reiter') ?? 'transkript');
  let text = $state('');
  let exportOffen = $state(false);
  let neuLaden = $state(0);

  const ungespeichert = $derived(!!details?.protokoll && text !== details.protokoll.text);

  $effect(() => {
    void neuLaden;
    void zustand.besprechungenStand;
    void verbindung.runde;
    if (!verbindung.bereit) return;
    api
      .besprechung(id)
      .then((d) => {
        const warUngespeichert = ungespeichert;
        details = d;
        if (!warUngespeichert) text = d.protokoll?.text ?? '';
      })
      .catch((e) => dialog.zeigen(e, 'Besprechung nicht geladen'));
  });

  beforeNavigate((nav) => {
    if (ungespeichert && !confirm('Änderungen an der Zusammenfassung verwerfen?')) nav.cancel();
  });

  function gespeichert() {
    if (details?.protokoll) details.protokoll.text = text;
    neuLaden++;
  }
</script>

<svelte:window
  onbeforeunload={(e) => {
    if (ungespeichert) e.preventDefault();
  }}
/>

<svelte:head><title>{details?.titel ?? 'Besprechung'} · VERMERK</title></svelte:head>

<header class="kopf">
  <a class="zurueck symbolknopf" href="/besprechungen" aria-label="Zurück zur Liste" title="Zurück">←</a>
  <div class="titel">
    <h1>{details?.titel ?? ''}</h1>
    {#if details}
      <div class="meta">
        <span>{datumText(details.zeit)}</span>
        <span>{dauerText(details.dauer_sekunden)}</span>
        {#if details.anzahl_sprecher}<span>{details.anzahl_sprecher} Sprecher</span>{/if}
      </div>
    {/if}
  </div>
  <button class="knopf" type="button" disabled={!details} onclick={() => (exportOffen = true)}>
    Exportieren
  </button>
  <Datenschutz />
</header>

<Reiter reiter={REITER} bind:aktiv={reiter} beschriftung="Ansicht" />

{#if details}
  <div role="tabpanel" id="tafel-{reiter}" aria-labelledby="reiter-{reiter}">
    {#if reiter === 'transkript'}
      <Transkript segmente={details.segmente} />
    {:else if reiter === 'sprecher'}
      <SprecherListe id={details.id} sprecher={details.sprecher} gespeichert={() => neuLaden++} />
    {:else if reiter === 'zusammenfassung'}
      <Zusammenfassung {details} bind:text {gespeichert} />
    {:else}
      <Dateien {details} />
    {/if}
  </div>
  <ExportDialog offen={exportOffen} {details} schliessen={() => (exportOffen = false)} />
{:else}
  <div class="leer">…</div>
{/if}

<style>
  .kopf {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
  }

  .zurueck {
    width: 34px;
    height: 34px;
    font-size: 17px;
    text-decoration: none;
  }

  .titel {
    flex: 1;
    min-width: 0;
  }

  h1 {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .meta {
    display: flex;
    gap: 14px;
    font-size: 12.5px;
    color: var(--text-2);
  }
</style>
