<script lang="ts">
  import ArrowLeft from '@lucide/svelte/icons/arrow-left';
  import Users from '@lucide/svelte/icons/users';
  import { beforeNavigate, goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api, ApiFehler } from '$lib/api/client';
  import type { BesprechungDetails } from '$lib/api/typen';
  import { datumText, dauerText } from '$lib/logik/format';
  import { ohneBesitzer, teilenMoeglich } from '$lib/logik/teilen';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Bestaetigen from '../Bestaetigen.svelte';
  import Datenschutz from '../Datenschutz.svelte';
  import Reiter from '../Reiter.svelte';
  import Dateien from './Dateien.svelte';
  import ExportDialog from './ExportDialog.svelte';
  import SprecherListe from './SprecherListe.svelte';
  import TeilenDialog from './TeilenDialog.svelte';
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
  let teilenOffen = $state(false);
  let neuLaden = $state(0);
  /** Wohin es gehen sollte, als ungespeicherte Änderungen das Verlassen aufhielten. */
  let wartendesZiel = $state<URL | null>(null);
  let verlassenErlaubt = false;

  /** Geteilte Besprechung eines anderen: nur lesen. */
  const eigen = $derived(details?.eigen !== false);

  $effect(() => {
    if (verbindung.mehrbenutzer) void personen.laden();
  });

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
      .catch((e) => {
        // Inzwischen gelöscht (z. B. in einem anderen Fenster): zurück zur Liste statt einer Fehlermeldung.
        if (details && e instanceof ApiFehler && e.status === 404) {
          meldungen.zeigen('Dieses Transkript wurde gelöscht.', 'info');
          verlassenErlaubt = true;
          void goto('/besprechungen');
          return;
        }
        dialog.zeigen(e, 'Transkript nicht geladen');
      });
  });

  beforeNavigate((nav) => {
    if (!ungespeichert || verlassenErlaubt) return;
    nav.cancel();
    // Fenster schließen: das übernimmt die Rückfrage des Browsers (beforeunload).
    if (nav.type !== 'leave' && nav.to) wartendesZiel = nav.to.url;
  });

  function verlassen() {
    const ziel = wartendesZiel;
    wartendesZiel = null;
    if (!ziel) return;
    verlassenErlaubt = true;
    void goto(ziel.pathname + ziel.search + ziel.hash);
  }

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

<svelte:head><title>{details?.titel ?? 'Transkript'} · VERMERK</title></svelte:head>

<header class="kopf">
  <a class="zurueck symbolknopf" href="/besprechungen" aria-label="Zurück zur Liste" title="Zurück">
    <ArrowLeft size={20} />
  </a>
  <div class="titel">
    <h1>{details?.titel ?? ''}</h1>
    {#if details}
      <div class="meta">
        <span>{datumText(details.zeit)}</span>
        <span>{dauerText(details.dauer_sekunden)}</span>
        {#if details.anzahl_sprecher}<span>{details.anzahl_sprecher} Sprecher</span>{/if}
        {#if !eigen}<span class="geteilt">geteilt von {personen.anzeigename(details.besitzer)}</span>{/if}
        {#if ohneBesitzer(details, verbindung.mehrbenutzer)}<span>ohne Besitzer</span>{/if}
      </div>
    {/if}
  </div>
  {#if details && teilenMoeglich(details, verbindung.mehrbenutzer)}
    <button class="knopf" type="button" onclick={() => (teilenOffen = true)}>
      {#if details.geteilt_mit?.length}<Users size={16} /> Geteilt{:else}Teilen{/if}
    </button>
  {/if}
  {#if eigen}
    <button class="knopf" type="button" disabled={!details} onclick={() => (exportOffen = true)}>
      Exportieren
    </button>
  {/if}
  <Datenschutz />
</header>

<Reiter reiter={REITER} bind:aktiv={reiter} beschriftung="Ansicht" />

{#if details}
  <div role="tabpanel" id="tafel-{reiter}" aria-labelledby="reiter-{reiter}">
    {#if reiter === 'transkript'}
      <Transkript segmente={details.segmente} />
    {:else if reiter === 'sprecher'}
      <SprecherListe
        id={details.id}
        sprecher={details.sprecher}
        nurLesen={!eigen}
        gespeichert={() => neuLaden++}
        zuDateien={() => (reiter = 'dateien')}
      />
    {:else if reiter === 'zusammenfassung'}
      <Zusammenfassung {details} bind:text nurLesen={!eigen} {gespeichert} />
    {:else}
      <Dateien {details} />
    {/if}
  </div>
  <ExportDialog
    offen={exportOffen}
    {details}
    schliessen={() => (exportOffen = false)}
    exportiert={() => neuLaden++}
  />
  <TeilenDialog
    offen={teilenOffen}
    {details}
    schliessen={() => (teilenOffen = false)}
    gespeichert={() => neuLaden++}
  />
{:else}
  <div class="leer">…</div>
{/if}

<Bestaetigen
  offen={!!wartendesZiel}
  titel="Änderungen verwerfen?"
  text="Die Änderungen an der Zusammenfassung sind noch nicht gespeichert."
  verb="Verwerfen"
  bestaetigen={verlassen}
  schliessen={() => (wartendesZiel = null)}
/>

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

  .geteilt {
    padding: 0 8px;
    border-radius: 9px;
    background: var(--akzent-weich);
    color: var(--link);
    font-weight: 500;
  }

  .meta {
    display: flex;
    gap: 14px;
    font-size: 12.5px;
    color: var(--text-2);
  }
</style>
