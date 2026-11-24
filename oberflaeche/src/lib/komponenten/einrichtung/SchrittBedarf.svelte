<script lang="ts">
  /** „Was nötig ist“: Download und Platz in Worten, Zustimmung je Download – ohne Haken lädt nichts. */
  import Download from '@lucide/svelte/icons/download';
  import ExternalLink from '@lucide/svelte/icons/external-link';
  import HardDrive from '@lucide/svelte/icons/hard-drive';
  import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
  import { onMount } from 'svelte';
  import {
    alleSetzen,
    alleZugestimmt,
    bausteinText,
    downloadDauerText,
    gbText,
    hfSchluesselNoetig,
    offeneBausteine,
    wahlVollstaendig,
    zustimmungMoeglich,
    zustimmungSetzen
  } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import Info from '../Info.svelte';

  const ERKLAERUNG: Record<string, string> = {
    ollama: 'Führt die KI auf diesem Computer aus. Startet mit Windows und ist nur hier erreichbar.',
    laufzeit: 'Wird beim nächsten Start eingerichtet. Die App startet dafür einmal neu.',
    pyannote: 'Trennt den Text nach Personen.',
    einbettung: 'Findet in Frag mein Meeting die passenden Stellen.'
  };

  onMount(() => {
    if (!einrichtung.kosten && wahlVollstaendig(einrichtung.wahl)) {
      einrichtung.kostenLaden().catch((e) => dialog.zeigen(e, 'Bedarf nicht ermittelt'));
    }
  });

  const k = $derived(einrichtung.kosten);
  const offen = $derived(offeneBausteine(k));
  const alle = $derived(alleZugestimmt(einrichtung.zustimmung, k));

  function setzen(kennung: string, an: boolean) {
    einrichtung.zustimmung = zustimmungSetzen(einrichtung.zustimmung, kennung, an, k);
  }
</script>

{#if k}
  <div class="kacheln">
    <div class="kachel karte">
      <Download size={20} />
      <div>
        <div class="wert">{gbText(k.download_gb)}</div>
        <div class="unter">
          herunterladen · {downloadDauerText(k.download_minuten_von, k.download_minuten_bis)}
        </div>
      </div>
    </div>
    <div class="kachel karte" class:knapp={k.platz_knapp}>
      <HardDrive size={20} />
      <div>
        <div class="wert">{gbText(k.platz_gb)}</div>
        <div class="unter">
          Speicherplatz{k.freier_platz_gb != null ? ` · ${gbText(k.freier_platz_gb)} frei` : ''}
        </div>
      </div>
    </div>
  </div>

  {#if k.platz_knapp}
    <p class="warn"><TriangleAlert size={16} /> Der Speicherplatz wird knapp.</p>
  {/if}

  <div class="karte liste">
    <label class="zeile alle">
      <input
        type="checkbox"
        checked={alle}
        onchange={(e) => (einrichtung.zustimmung = alleSetzen(e.currentTarget.checked, k))}
      />
      <span class="name">Allem zustimmen</span>
    </label>
    {#each offen as b (b.kennung)}
      {@const moeglich = zustimmungMoeglich(b.kennung, einrichtung.zustimmung, k)}
      <div class="eintrag" class:aus={!moeglich}>
        <label class="zeile">
          <input
            type="checkbox"
            checked={!!einrichtung.zustimmung[b.kennung]}
            disabled={!moeglich}
            onchange={(e) => setzen(b.kennung, e.currentTarget.checked)}
          />
          <span class="name">{bausteinText(b.kennung)}</span>
          <span class="groesse">{gbText(b.download_gb)}</span>
        </label>
        <span class="i">
          {#if ERKLAERUNG[b.kennung]}
            <Info frage={bausteinText(b.kennung)} text={ERKLAERUNG[b.kennung]!} />
          {/if}
        </span>
        {#if b.kennung === 'ollama' && k.ollama_lizenz}
          <div class="lizenz">
            {#if k.ollama_lizenz.lizenz_url}
              <a href={k.ollama_lizenz.lizenz_url} target="_blank" rel="noopener noreferrer">
                Lizenz <ExternalLink size={14} />
              </a>
            {/if}
            {#if k.ollama_lizenz.bedingungen_url}
              <a href={k.ollama_lizenz.bedingungen_url} target="_blank" rel="noopener noreferrer">
                Nutzungsbedingungen <ExternalLink size={14} />
              </a>
            {/if}
          </div>
        {/if}
        {#if b.kennung === 'pyannote' && hfSchluesselNoetig(einrichtung.zustimmung, einrichtung.stand)}
          <label class="schluessel">
            <span>Zugangsschlüssel für die Sprechererkennung</span>
            <input
              class="feld"
              type="password"
              autocomplete="off"
              spellcheck="false"
              bind:value={einrichtung.hfSchluessel}
            />
          </label>
        {/if}
      </div>
    {/each}
  </div>
{:else}
  <p class="leise">Wird berechnet …</p>
{/if}

<style>
  .kacheln {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }

  .kachel {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 16px 20px;
    color: var(--text-2);
  }

  .kachel.knapp {
    border-color: var(--warn);
  }

  .wert {
    font-size: 22px;
    font-weight: 600;
    color: var(--text);
    line-height: 1.2;
  }

  .unter {
    font-size: 13px;
  }

  .warn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--warn);
  }

  .liste {
    padding: 4px 0;
  }

  .eintrag {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    border-top: 1px solid var(--rand);
    padding-right: 16px;
  }

  .eintrag.aus {
    opacity: 0.55;
  }

  .zeile {
    display: grid;
    grid-template-columns: 20px minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    padding: 0 12px 0 20px;
    cursor: pointer;
  }

  .zeile.alle {
    grid-template-columns: 20px minmax(0, 1fr);
    color: var(--text-2);
    min-height: 44px;
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

  .alle .name {
    font-weight: 400;
  }

  .groesse {
    color: var(--text-2);
    font-size: 13px;
  }

  .i {
    display: inline-flex;
    width: 24px;
    justify-content: center;
  }

  .lizenz,
  .schluessel {
    grid-column: 1 / -1;
    padding: 0 0 14px 52px;
  }

  .lizenz {
    display: flex;
    gap: 18px;
    margin-top: -6px;
    font-size: 13px;
  }

  .lizenz a {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .schluessel {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 420px;
    box-sizing: content-box;
  }

  .schluessel span {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }
</style>
