<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { Besprechung } from '$lib/api/typen';
  import Details from '$lib/komponenten/besprechungen/Details.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import { datumText, dauerText, zeitLesen } from '$lib/logik/format';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';

  let liste = $state<Besprechung[] | null>(null);
  let suche = $state('');

  const id = $derived(page.url.searchParams.get('id'));
  const transkript = $derived(page.url.searchParams.get('transkript'));

  $effect(() => {
    void zustand.besprechungenStand;
    void verbindung.runde;
    if (!verbindung.bereit) return;
    api
      .besprechungen()
      .then((l) => (liste = l))
      .catch((e) => dialog.zeigen(e, 'Besprechungen nicht geladen'));
  });

  $effect(() => {
    if (verbindung.mehrbenutzer) void personen.laden();
  });

  // Aus dem Status-Bereich kommt der Pfad des Transkripts; daraus wird die Besprechung.
  $effect(() => {
    if (!transkript || !liste) return;
    const treffer = liste.find((b) => b.transkript === transkript);
    if (treffer) {
      const reiter = page.url.searchParams.get('reiter');
      void goto(`/besprechungen?id=${encodeURIComponent(treffer.id)}${reiter ? `&reiter=${reiter}` : ''}`, {
        replaceState: true
      });
    }
  });

  const gefiltert = $derived.by(() => {
    const l = [...(liste ?? [])].sort(
      (a, b) => (zeitLesen(b.zeit)?.getTime() ?? 0) - (zeitLesen(a.zeit)?.getTime() ?? 0)
    );
    const s = suche.trim().toLowerCase();
    return s ? l.filter((b) => b.titel.toLowerCase().includes(s)) : l;
  });
</script>

{#if id}
  <Details {id} />
{:else}
  <Kopf titel="Besprechungen">
    {#snippet aktionen()}
      <input
        class="feld suche"
        type="search"
        placeholder="Suchen"
        aria-label="Besprechungen suchen"
        bind:value={suche}
      />
    {/snippet}
  </Kopf>

  {#if liste === null}
    <div class="leer">…</div>
  {:else if gefiltert.length === 0}
    <div class="leer">{suche ? 'Nichts gefunden' : 'Noch keine Besprechungen'}</div>
  {:else}
    <div class="karte tabelle" role="table" aria-label="Besprechungen">
      <div class="zeile kopfzeile" role="row">
        <span role="columnheader">Titel</span>
        <span role="columnheader">Datum</span>
        <span role="columnheader">Dauer</span>
        <span role="columnheader">Sprecher</span>
        <span role="columnheader">Zusammenfassung</span>
      </div>
      {#each gefiltert as b (b.id)}
        <a class="zeile" role="row" href="/besprechungen?id={encodeURIComponent(b.id)}">
          <span class="titel" role="cell">
            <span class="text">{b.titel}</span>
            {#if b.eigen === false}
              <span class="geteilt">geteilt von {personen.anzeigename(b.besitzer)}</span>
            {:else if b.geteilt_mit?.length}
              <span class="geteilt leise" title="Geteilt">👥</span>
            {/if}
          </span>
          <span role="cell" class="leise">{datumText(b.zeit)}</span>
          <span role="cell" class="leise">{dauerText(b.dauer_sekunden)}</span>
          <span role="cell" class="leise">{b.anzahl_sprecher ?? '–'}</span>
          <span role="cell">
            {#if b.hat_protokoll}<span class="marke ja">✓ Vorhanden</span>{:else}<span class="marke">
                –
              </span>{/if}
          </span>
        </a>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .suche {
    width: 240px;
  }

  .tabelle {
    overflow: hidden;
  }

  .zeile {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 150px 110px 80px 140px;
    gap: 16px;
    align-items: center;
    padding: 12px 18px;
    border-top: 1px solid var(--rand);
    color: var(--text);
  }

  a.zeile:hover {
    background: var(--karte-2);
    text-decoration: none;
  }

  .kopfzeile {
    border-top: none;
    padding-top: 10px;
    padding-bottom: 10px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-3);
    background: var(--karte-2);
  }

  .titel {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    font-weight: 500;
  }

  .titel .text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .geteilt {
    flex: none;
    padding: 1px 8px;
    border-radius: 9px;
    background: var(--akzent-weich);
    color: var(--link);
    font-size: 12px;
    font-weight: 500;
  }

  .geteilt.leise {
    background: none;
    padding: 0;
  }

  .marke {
    font-size: 12.5px;
    color: var(--text-3);
  }

  .marke.ja {
    color: var(--ok);
    font-weight: 500;
  }
</style>
