<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import Files from '@lucide/svelte/icons/files';
  import Plus from '@lucide/svelte/icons/plus';
  import Search from '@lucide/svelte/icons/search';
  import SearchX from '@lucide/svelte/icons/search-x';
  import Users from '@lucide/svelte/icons/users';
  import { tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { Besprechung } from '$lib/api/typen';
  import Details from '$lib/komponenten/besprechungen/Details.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import LeerZustand from '$lib/komponenten/LeerZustand.svelte';
  import { datumText, dauerText, zeitLesen } from '$lib/logik/format';
  import { KUERZEL_TEXT } from '$lib/logik/tasten';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';

  let liste = $state<Besprechung[] | null>(null);
  let suche = $state('');
  let suchfeld: HTMLInputElement | undefined = $state();

  const id = $derived(page.url.searchParams.get('id'));
  const transkript = $derived(page.url.searchParams.get('transkript'));

  $effect(() => {
    void zustand.besprechungenStand;
    void verbindung.runde;
    if (!verbindung.bereit) return;
    api
      .besprechungen()
      .then((l) => (liste = l))
      .catch((e) => dialog.zeigen(e, 'Transkripte nicht geladen'));
  });

  $effect(() => {
    if (verbindung.mehrbenutzer) void personen.laden();
  });

  // „/“ von einer anderen Seite: hierher und in die Suche.
  $effect(() => {
    if (!page.url.searchParams.get('suche') || !suchfeld) return;
    void tick().then(() => suchfeld?.focus());
    void goto('/besprechungen', { replaceState: true, keepFocus: true, noScroll: true });
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
  <Kopf titel="Transkripte">
    {#snippet aktionen()}
      <label class="suche">
        <Search size={16} />
        <input
          id="besprechungen-suche"
          class="feld"
          type="search"
          placeholder="Suchen"
          aria-label="Transkripte suchen"
          title="Suchen ({KUERZEL_TEXT.suche})"
          bind:this={suchfeld}
          bind:value={suche}
        />
      </label>
    {/snippet}
  </Kopf>

  {#if liste === null}
    <div class="leer">…</div>
  {:else if gefiltert.length === 0}
    {#if suche}
      <LeerZustand symbol={SearchX} titel="Nichts gefunden" />
    {:else}
      <LeerZustand symbol={Files} titel="Noch keine Transkripte">
        {#snippet aktion()}
          <a class="knopf primaer" href="/?neu=1"><Plus size={16} /> Neue Transkription</a>
        {/snippet}
      </LeerZustand>
    {/if}
  {:else}
    <div class="karte tabelle" role="table" aria-label="Transkripte">
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
            {:else if verbindung.mehrbenutzer && b.geteilt_mit?.length}
              <span class="geteilt leise" title="Geteilt"><Users size={16} /></span>
            {/if}
          </span>
          <span role="cell" class="leise">{datumText(b.zeit)}</span>
          <span role="cell" class="leise">{dauerText(b.dauer_sekunden)}</span>
          <span role="cell" class="leise">{b.anzahl_sprecher ?? '–'}</span>
          <span role="cell">
            {#if b.hat_protokoll}
              <span class="marke ja"><Check size={16} /> Vorhanden</span>
            {:else}
              <span class="marke">–</span>
            {/if}
          </span>
        </a>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .suche {
    position: relative;
    display: flex;
    align-items: center;
    width: 240px;
    color: var(--text-3);
  }

  .suche :global(.lucide-icon) {
    position: absolute;
    left: 10px;
    pointer-events: none;
  }

  .suche input {
    padding-left: 32px;
    color: var(--text);
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
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--ok);
    font-weight: 500;
  }

  .geteilt.leise {
    display: inline-flex;
    color: var(--text-3);
  }
</style>
