<script lang="ts">
  import Files from '@lucide/svelte/icons/files';
  import Plus from '@lucide/svelte/icons/plus';
  import Search from '@lucide/svelte/icons/search';
  import SearchX from '@lucide/svelte/icons/search-x';
  import { tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { Besprechung } from '$lib/api/typen';
  import BesprechungsTabelle from '$lib/komponenten/besprechungen/BesprechungsTabelle.svelte';
  import Details from '$lib/komponenten/besprechungen/Details.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import LeerZustand from '$lib/komponenten/LeerZustand.svelte';
  import { zeitLesen } from '$lib/logik/format';
  import { KUERZEL_TEXT } from '$lib/logik/tasten';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';

  let liste = $state<Besprechung[] | null>(null);
  let suche = $state('');
  let suchfeld: HTMLInputElement | undefined = $state();
  let neuLaden = $state(0);

  const id = $derived(page.url.searchParams.get('id'));
  const transkript = $derived(page.url.searchParams.get('transkript'));

  $effect(() => {
    void zustand.besprechungenStand;
    void verbindung.runde;
    void neuLaden;
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
    <BesprechungsTabelle
      eintraege={gefiltert}
      oeffnen={(b) => goto(`/besprechungen?id=${encodeURIComponent(b.id)}`)}
      geaendert={() => neuLaden++}
    />
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
</style>
