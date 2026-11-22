<script lang="ts">
  import { api } from '$lib/api/client';
  import type { BesprechungDetails } from '$lib/api/typen';
  import { groesseText, ordnerVon } from '$lib/logik/format';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';

  let { details }: { details: BesprechungDetails } = $props();

  const ARTEN: Record<string, string> = {
    txt: 'Text',
    md: 'Text mit Formatierung',
    json: 'Daten',
    srt: 'Untertitel',
    vtt: 'Untertitel',
    docx: 'Word',
    pdf: 'PDF',
    odt: 'OpenDocument',
    html: 'Webseite'
  };

  const zeigenMoeglich = $derived(!!verbindung.info?.faehigkeiten.ordner_oeffnen);

  function pfadVon(name: string): string {
    const trenner = details.transkript.includes('\\') ? '\\' : '/';
    return `${ordnerVon(details.transkript)}${trenner}${name}`;
  }

  async function speichern(name: string) {
    try {
      await api.dateiSpeichern(details.id, name);
    } catch (e) {
      dialog.zeigen(e, 'Herunterladen hat nicht geklappt');
    }
  }

  async function zeigen(name: string) {
    try {
      await api.ordnerOeffnen(pfadVon(name));
    } catch (e) {
      dialog.zeigen(e, 'Ordner lässt sich nicht öffnen');
    }
  }
</script>

{#if details.dateien.length === 0}
  <div class="leer">Keine Dateien</div>
{:else}
  <ul class="karte liste">
    {#each details.dateien as d (d.name)}
      <li>
        <span class="art">{ARTEN[d.art] ?? d.art.toUpperCase()}</span>
        <span class="name" title={d.name}>{d.name}</span>
        <span class="leise klein">{groesseText(d.groesse)}</span>
        <span class="knoepfe">
          {#if zeigenMoeglich}
            <button class="knopf leise" type="button" onclick={() => zeigen(d.name)}>Im Ordner zeigen</button>
          {/if}
          <button
            class="symbolknopf"
            type="button"
            aria-label="{d.name} herunterladen"
            title="Herunterladen"
            onclick={() => speichern(d.name)}
          >
            ⤓
          </button>
        </span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .liste {
    list-style: none;
    margin: 0;
    padding: 4px 0;
  }

  li {
    display: grid;
    grid-template-columns: 150px minmax(0, 1fr) 80px auto;
    gap: 14px;
    align-items: center;
    padding: 8px 14px 8px 18px;
    border-top: 1px solid var(--rand);
  }

  li:first-child {
    border-top: none;
  }

  .art {
    font-weight: 500;
  }

  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-2);
    font-size: 13px;
  }

  .klein {
    text-align: right;
  }

  .knoepfe {
    display: flex;
    align-items: center;
    gap: 4px;
  }
</style>
