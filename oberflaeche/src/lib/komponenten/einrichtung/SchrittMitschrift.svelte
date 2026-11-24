<script lang="ts">
  /**
   * Nach dem Neustart: Spracherkennung und Sprechererkennung laden (das geht erst, wenn das Rechenpaket
   * läuft). Die Haken von „Was nötig ist“ gelten weiter; ohne Haken lädt nichts.
   */
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { EinrichtungBaustein } from '$lib/api/typen';
  import { bausteinText, gbText, hfSchluesselNoetig } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import Info from '../Info.svelte';
  import SchrittEinrichten from './SchrittEinrichten.svelte';

  let bausteine = $state<EinrichtungBaustein[]>([]);

  onMount(() => {
    api
      .einrichtungKosten()
      .then((k) => {
        bausteine = k.bausteine.filter(
          (b) => (b.kennung === 'whisper' || b.kennung === 'pyannote') && !b.vorhanden
        );
      })
      .catch((e) => console.warn('Bedarf nicht ermittelt', e));
  });
</script>

{#if einrichtung.gestartet}
  <SchrittEinrichten />
{:else if bausteine.length}
  <div class="karte liste">
    {#each bausteine as b (b.kennung)}
      <label class="zeile">
        <input
          type="checkbox"
          checked={!!einrichtung.zustimmung[b.kennung]}
          onchange={(e) =>
            (einrichtung.zustimmung = { ...einrichtung.zustimmung, [b.kennung]: e.currentTarget.checked })}
        />
        <span class="name">{bausteinText(b.kennung)}</span>
        <span class="groesse">{gbText(b.download_gb)}</span>
      </label>
    {/each}
    {#if hfSchluesselNoetig(einrichtung.zustimmung, einrichtung.stand)}
      <div class="schluessel">
        <span class="beschriftung">
          <label for="hf-schluessel">Zugangsschlüssel für die Sprechererkennung</label>
          <Info
            frage="Woher kommt dieser Schlüssel?"
            text="Die Sprechererkennung kommt von Hugging Face. Dort gibt es den Schlüssel kostenlos."
          />
        </span>
        <input
          id="hf-schluessel"
          class="feld"
          type="password"
          autocomplete="off"
          spellcheck="false"
          bind:value={einrichtung.hfSchluessel}
        />
      </div>
    {/if}
  </div>
{:else}
  <p class="leise">Alles vorhanden.</p>
{/if}

<style>
  .liste {
    padding: 4px 0;
  }

  .zeile {
    display: grid;
    grid-template-columns: 20px minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    padding: 0 20px;
    border-top: 1px solid var(--rand);
    cursor: pointer;
  }

  .zeile:first-child {
    border-top: none;
  }

  .zeile input {
    width: 16px;
    height: 16px;
    margin: 0;
    accent-color: var(--akzent);
  }

  .name {
    font-weight: 500;
  }

  .groesse {
    color: var(--text-2);
    font-size: 13px;
  }

  .schluessel {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 420px;
    padding: 4px 20px 16px 52px;
  }

  .beschriftung {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }
</style>
