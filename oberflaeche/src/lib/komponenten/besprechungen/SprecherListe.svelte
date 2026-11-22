<script lang="ts">
  import { api } from '$lib/api/client';
  import type { Sprecher } from '$lib/api/typen';
  import { dauerText } from '$lib/logik/format';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';

  let { id, sprecher, gespeichert }: { id: string; sprecher: Sprecher[]; gespeichert: () => void } = $props();

  let namen = $state<Record<string, string>>({});
  let speichert = $state(false);

  $effect(() => {
    namen = Object.fromEntries(sprecher.filter((s) => s.id).map((s) => [s.id!, s.name ?? '']));
  });

  const geaendert = $derived(sprecher.some((s) => s.id && (namen[s.id] ?? '') !== (s.name ?? '')));

  async function speichern() {
    speichert = true;
    try {
      const antwort = await api.sprecherUmbenennen(id, namen);
      meldungen.zeigen(antwort.word_hinweis ? 'Gespeichert (Word-Datei nicht aktualisiert)' : 'Gespeichert');
      gespeichert();
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    } finally {
      speichert = false;
    }
  }
</script>

{#if sprecher.length === 0}
  <div class="leer">Keine Sprecher erkannt</div>
{:else}
  <form
    class="karte liste"
    onsubmit={(e) => {
      e.preventDefault();
      void speichern();
    }}
  >
    {#each sprecher as s, i (s.id ?? i)}
      {#if s.id}
        <div class="zeile-sp">
          <span class="punkt" style:background="var(--sp{i % 6})" aria-hidden="true"></span>
          <input class="feld" aria-label="Name für {s.id}" placeholder={s.id} bind:value={namen[s.id]} />
          <span class="leise klein">{dauerText(s.sekunden)}</span>
        </div>
      {/if}
    {/each}
    <div class="fuss">
      <button class="knopf primaer" type="submit" disabled={!geaendert || speichert}>Speichern</button>
    </div>
  </form>
{/if}

<style>
  .liste {
    padding: 14px 18px;
    max-width: 560px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .zeile-sp {
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr) 90px;
    align-items: center;
    gap: 12px;
  }

  .punkt {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .klein {
    text-align: right;
  }

  .fuss {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
</style>
