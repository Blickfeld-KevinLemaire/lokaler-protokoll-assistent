<script lang="ts">
  /** Gemerkte Stimmen: umbenennen, vergessen. Gemerkt wird im Reiter „Sprecher“ einer Besprechung. */
  import AudioLines from '@lucide/svelte/icons/audio-lines';
  import Check from '@lucide/svelte/icons/check';
  import Pencil from '@lucide/svelte/icons/pencil';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import X from '@lucide/svelte/icons/x';
  import { api } from '#lib/api/client.ts';
  import type { SprecherProfil } from '#lib/api/typen.ts';
  import { datumText } from '#lib/logik/format.ts';
  import { dialog, meldungen, rueckfrage } from '#lib/stores/oberflaeche.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import LeerZustand from '../LeerZustand.svelte';

  let profile = $state<SprecherProfil[] | null>(null);
  let bearbeitet = $state<string | null>(null);
  let neuerName = $state('');

  async function laden() {
    try {
      profile = await api.sprecherprofile();
    } catch (e) {
      profile = [];
      console.warn('Stimmen nicht geladen', e);
    }
  }

  $effect(() => {
    void verbindung.runde;
    if (verbindung.bereit) void laden();
  });

  function bearbeiten(p: SprecherProfil) {
    bearbeitet = p.id;
    neuerName = p.name;
  }

  async function umbenennen(e: SubmitEvent, p: SprecherProfil) {
    e.preventDefault();
    const name = neuerName.trim();
    if (!name || name === p.name) {
      bearbeitet = null;
      return;
    }
    try {
      await api.sprecherprofilUmbenennen(p.id, name);
      bearbeitet = null;
      meldungen.zeigen('Gespeichert');
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Umbenennen hat nicht geklappt');
    }
  }

  async function vergessen(p: SprecherProfil) {
    const ja = await rueckfrage.fragen({
      titel: `Stimme „${p.name}“ vergessen?`,
      text: 'In neuen Aufnahmen wird sie dann nicht mehr erkannt.',
      verb: 'Vergessen'
    });
    if (!ja) return;
    try {
      await api.sprecherprofilLoeschen(p.id);
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Das hat nicht geklappt');
    }
  }
</script>

{#if profile && profile.length === 0}
  <LeerZustand symbol={AudioLines} titel="Noch keine Stimmen gemerkt" klein />
{:else if profile}
  <ul class="liste">
    {#each profile as p (p.id)}
      <li>
        {#if bearbeitet === p.id}
          <form class="zeile" onsubmit={(e) => umbenennen(e, p)}>
            <!-- svelte-ignore a11y_autofocus -->
            <input class="feld" aria-label="Name" maxlength="80" autofocus bind:value={neuerName} />
            <button class="symbolknopf" type="submit" aria-label="Speichern" title="Speichern">
              <Check />
            </button>
            <button
              class="symbolknopf"
              type="button"
              aria-label="Abbrechen"
              title="Abbrechen"
              onclick={() => (bearbeitet = null)}
            >
              <X />
            </button>
          </form>
        {:else}
          <span class="name">{p.name}</span>
          <span class="leise klein">{datumText(p.aktualisiert || p.erstellt)}</span>
          <button
            class="symbolknopf"
            type="button"
            aria-label="{p.name} umbenennen"
            title="Umbenennen"
            onclick={() => bearbeiten(p)}
          >
            <Pencil />
          </button>
          <button
            class="symbolknopf"
            type="button"
            aria-label="{p.name} vergessen"
            title="Vergessen"
            onclick={() => vergessen(p)}
          >
            <Trash2 />
          </button>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  .liste {
    list-style: none;
    margin: 0;
    padding: 0;
    width: 460px;
    max-width: 100%;
  }

  li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto auto;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    border-top: 1px solid var(--rand);
  }

  li:first-child {
    border-top: none;
  }

  .zeile {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .name {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
