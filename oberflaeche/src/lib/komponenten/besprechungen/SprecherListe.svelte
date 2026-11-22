<script lang="ts">
  /**
   * Sprecher einer Besprechung: Namen vergeben, Vorschläge aus bekannten Stimmen übernehmen, kurz
   * hineinhören, eine Stimme merken, Audio und Text eines Sprechers speichern.
   */
  import BookmarkPlus from '@lucide/svelte/icons/bookmark-plus';
  import FileDown from '@lucide/svelte/icons/file-down';
  import Pause from '@lucide/svelte/icons/pause';
  import Play from '@lucide/svelte/icons/play';
  import { onDestroy } from 'svelte';
  import { api } from '$lib/api/client';
  import type { Sprecher, SprecherVorschlaege } from '$lib/api/typen';
  import { dauerText, sprecherName } from '$lib/logik/format';
  import { vorschlagFuer } from '$lib/logik/sprecher';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';

  let {
    id,
    sprecher,
    nurLesen = false,
    gespeichert,
    zuDateien
  }: {
    id: string;
    sprecher: Sprecher[];
    nurLesen?: boolean;
    gespeichert: () => void;
    /** Nach dem Speichern von Audio und Text: zum Reiter „Dateien“. */
    zuDateien?: () => void;
  } = $props();

  // Tief reaktiv (bind:value auf einzelne Einträge); neu gesetzt, sobald die Besprechung neu geladen wird.
  // eslint-disable-next-line svelte/prefer-writable-derived -- $derived wäre nicht tief reaktiv
  let namen = $state<Record<string, string>>({});
  let speichert = $state(false);
  let vorschlaege = $state<SprecherVorschlaege | null>(null);
  let spielt = $state<string | null>(null);
  let laedt = $state<string | null>(null);
  let beschaeftigt = $state<string | null>(null);
  let audio: HTMLAudioElement | null = null;
  /** Geladene Hörproben (Blob-Adressen) je Sprecher – nur zum Wiederverwenden, nicht reaktiv. */
  const proben: Record<string, string> = {};

  $effect(() => {
    namen = Object.fromEntries(sprecher.filter((s) => s.id).map((s) => [s.id!, s.name ?? '']));
  });

  $effect(() => {
    void sprecher;
    api
      .sprecherVorschlaege(id)
      .then((v) => (vorschlaege = v))
      .catch(() => (vorschlaege = null));
  });

  onDestroy(() => {
    audio?.pause();
    for (const url of Object.values(proben)) URL.revokeObjectURL(url);
  });

  const geaendert = $derived(sprecher.some((s) => s.id && (namen[s.id] ?? '') !== (s.name ?? '')));

  async function speichern(neu = namen) {
    speichert = true;
    try {
      const antwort = await api.sprecherUmbenennen(id, neu);
      meldungen.zeigen(antwort.word_hinweis ? 'Gespeichert (Word-Datei nicht aktualisiert)' : 'Gespeichert');
      gespeichert();
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    } finally {
      speichert = false;
    }
  }

  /** Ein Klick auf den Vorschlag: Name übernehmen und gleich speichern. */
  function uebernehmen(sid: string, name: string) {
    namen[sid] = name;
    void speichern({ ...namen, [sid]: name });
  }

  async function abspielen(sid: string) {
    if (spielt === sid) {
      audio?.pause();
      spielt = null;
      return;
    }
    audio?.pause();
    let url = proben[sid];
    if (!url) {
      laedt = sid;
      try {
        url = URL.createObjectURL(await api.hoerprobe(id, sid));
        proben[sid] = url;
      } catch (e) {
        dialog.zeigen(e, 'Hörprobe nicht möglich');
        return;
      } finally {
        laedt = null;
      }
    }
    audio = new Audio(url);
    audio.onended = () => (spielt = null);
    spielt = sid;
    void audio.play().catch(() => (spielt = null));
  }

  async function merken(s: Sprecher) {
    const name = (namen[s.id!] ?? '').trim() || (s.name ?? '').trim();
    if (!name) {
      meldungen.zeigen('Bitte zuerst einen Namen eintragen', 'info');
      document.getElementById(`sprecher-${s.id}`)?.focus();
      return;
    }
    beschaeftigt = s.id!;
    try {
      await api.stimmeMerken(id, s.id!, name);
      meldungen.zeigen(`Stimme von ${name} gemerkt`);
    } catch (e) {
      dialog.zeigen(e, 'Stimme nicht gemerkt');
    } finally {
      beschaeftigt = null;
    }
  }

  async function exportieren(s: Sprecher) {
    beschaeftigt = s.id!;
    try {
      const ergebnis = await api.sprecherExportieren(id, s.id!);
      gespeichert();
      meldungen.zeigen(
        `${ergebnis.dateien.length} Datei${ergebnis.dateien.length === 1 ? '' : 'en'} gespeichert`,
        'ok',
        6000,
        zuDateien ? { text: 'Anzeigen', tun: zuDateien } : undefined
      );
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    } finally {
      beschaeftigt = null;
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
        {@const v = vorschlagFuer(vorschlaege, s.id, namen[s.id] ?? s.name)}
        <div class="zeile-sp">
          <span class="punkt" style:background="var(--sp{i % 6})" aria-hidden="true"></span>
          <span class="name-feld">
            {#if nurLesen}
              <span class="name">{sprecherName(s.name, s.id)}</span>
            {:else}
              <input
                id="sprecher-{s.id}"
                class="feld"
                aria-label="Name für {sprecherName(null, s.id)}"
                placeholder={sprecherName(null, s.id)}
                bind:value={namen[s.id]}
              />
            {/if}
            {#if v && !nurLesen}
              <button
                class="vorschlag"
                class:unsicher={!v.sicher}
                type="button"
                title="Als Namen übernehmen"
                onclick={() => uebernehmen(s.id!, v.name)}
              >
                {v.sicher ? v.name : `${v.name}?`}
              </button>
            {/if}
          </span>
          <span class="leise klein dauer">{dauerText(s.sekunden)}</span>
          <span class="aktionen">
            <button
              class="symbolknopf"
              type="button"
              aria-label="{spielt === s.id ? 'Anhalten' : 'Hineinhören'}: {sprecherName(namen[s.id], s.id)}"
              title={spielt === s.id ? 'Anhalten' : 'Hineinhören'}
              aria-pressed={spielt === s.id}
              disabled={laedt === s.id}
              onclick={() => abspielen(s.id!)}
            >
              {#if spielt === s.id}<Pause />{:else}<Play />{/if}
            </button>
            {#if vorschlaege?.stimmen_vorhanden}
              <button
                class="symbolknopf"
                type="button"
                aria-label="Stimme merken: {sprecherName(namen[s.id], s.id)}"
                title="Stimme merken"
                disabled={beschaeftigt === s.id}
                onclick={() => merken(s)}
              >
                <BookmarkPlus />
              </button>
            {/if}
            {#if !nurLesen}
              <button
                class="symbolknopf"
                type="button"
                aria-label="Audio und Text speichern: {sprecherName(namen[s.id], s.id)}"
                title="Audio und Text speichern"
                disabled={beschaeftigt === s.id}
                onclick={() => exportieren(s)}
              >
                <FileDown />
              </button>
            {/if}
          </span>
        </div>
      {/if}
    {/each}
    {#if !nurLesen}
      <div class="fuss">
        <button class="knopf primaer" type="submit" disabled={!geaendert || speichert}>Speichern</button>
      </div>
    {/if}
  </form>
{/if}

<style>
  .liste {
    padding: 14px 18px;
    max-width: 680px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .zeile-sp {
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr) 80px auto;
    align-items: center;
    gap: 12px;
  }

  .punkt {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .name-feld {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .name-feld .feld {
    flex: 1;
    min-width: 0;
  }

  .vorschlag {
    flex: none;
    height: 26px;
    padding: 0 10px;
    border-radius: 13px;
    border: 1px solid var(--akzent);
    background: var(--akzent-weich);
    color: var(--link);
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }

  .vorschlag.unsicher {
    border-style: dashed;
    font-weight: 500;
  }

  .vorschlag:hover {
    background: var(--akzent);
    color: var(--akzent-text);
  }

  .dauer {
    text-align: right;
  }

  .aktionen {
    display: flex;
    gap: 2px;
  }

  .name {
    font-weight: 500;
    line-height: 34px;
  }

  .fuss {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
</style>
