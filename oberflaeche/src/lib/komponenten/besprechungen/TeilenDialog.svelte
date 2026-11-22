<script lang="ts">
  /** Besprechung mit einzelnen Personen oder allen teilen. */
  import { api } from '$lib/api/client';
  import type { BesprechungDetails } from '$lib/api/typen';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import Dialog from '../Dialog.svelte';

  let {
    offen,
    details,
    schliessen,
    gespeichert
  }: { offen: boolean; details: BesprechungDetails; schliessen: () => void; gespeichert: () => void } = $props();

  let alle = $state(false);
  let gewaehlt = $state<string[]>([]);
  let speichert = $state(false);

  $effect(() => {
    if (!offen) return;
    void personen.laden(true);
    const mit = details.geteilt_mit ?? [];
    alle = mit.includes('alle');
    gewaehlt = mit.filter((m) => m !== 'alle');
  });

  const andere = $derived(
    personen.liste.filter((p) => p.name.toLowerCase() !== (verbindung.info?.angemeldet_als ?? '').toLowerCase())
  );

  function umschalten(name: string) {
    gewaehlt = gewaehlt.includes(name) ? gewaehlt.filter((g) => g !== name) : [...gewaehlt, name];
  }

  async function speichern() {
    speichert = true;
    try {
      await api.freigabeSetzen(details.id, alle ? ['alle'] : gewaehlt);
      meldungen.zeigen(alle || gewaehlt.length ? 'Geteilt' : 'Nicht mehr geteilt');
      gespeichert();
      schliessen();
    } catch (e) {
      dialog.zeigen(e, 'Teilen hat nicht geklappt');
    } finally {
      speichert = false;
    }
  }
</script>

<Dialog {offen} titel="Teilen" {schliessen}>
  {#snippet kinder()}
    <div class="liste">
      <label class="option alle">
        <input type="checkbox" bind:checked={alle} />
        Alle
      </label>
      {#each andere as p (p.name)}
        <label class="option" class:aus={alle}>
          <input
            type="checkbox"
            checked={alle || gewaehlt.includes(p.name)}
            disabled={alle}
            onchange={() => umschalten(p.name)}
          />
          {p.anzeigename}
        </label>
      {/each}
    </div>
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf" type="button" onclick={schliessen}>Abbrechen</button>
    <button class="knopf primaer" type="button" disabled={speichert} onclick={speichern}>Speichern</button>
  {/snippet}
</Dialog>

<style>
  .liste {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 320px;
    overflow-y: auto;
    color: var(--text);
  }

  .option {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 6px;
    border-radius: 6px;
    cursor: pointer;
  }

  .option:hover {
    background: var(--karte-2);
  }

  .alle {
    font-weight: 600;
    border-bottom: 1px solid var(--rand);
    border-radius: 6px 6px 0 0;
    margin-bottom: 4px;
  }

  .aus {
    opacity: 0.55;
  }
</style>
