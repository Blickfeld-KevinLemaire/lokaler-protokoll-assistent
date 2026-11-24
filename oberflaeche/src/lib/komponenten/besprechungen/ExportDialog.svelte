<script lang="ts">
  /** Exportieren: Inhalt und Formate wählen; danach die Dateien im Ordner zeigen oder (im Browser) laden. */
  import Check from '@lucide/svelte/icons/check';
  import Download from '@lucide/svelte/icons/download';
  import FolderOpen from '@lucide/svelte/icons/folder-open';
  import { untrack } from 'svelte';
  import { api } from '$lib/api/client';
  import type { BesprechungDetails, ExportErgebnis, ExportFormat } from '$lib/api/typen';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import Dialog from '../Dialog.svelte';

  let {
    offen,
    details,
    schliessen,
    exportiert
  }: {
    offen: boolean;
    details: BesprechungDetails;
    schliessen: () => void;
    /** Die Dateien gehören jetzt zur Besprechung: Details neu laden. */
    exportiert?: () => void;
  } = $props();

  let formate = $state<ExportFormat[]>([]);
  let inhalt = $state<'transkript' | 'protokoll' | 'beides'>('beides');
  let gewaehlt = $state<string[]>([]);
  let laeuft = $state(false);
  let ergebnis = $state<ExportErgebnis | null>(null);

  $effect(() => {
    if (!offen) return;
    // Nur beim Öffnen zurücksetzen: Nach dem Export lädt die Besprechung neu, das Ergebnis bleibt stehen.
    untrack(() => {
      ergebnis = null;
      inhalt = details.protokoll ? 'beides' : 'transkript';
    });
    api
      .exportFormate()
      .then((f) => {
        formate = f;
        const vorgabe = einstellungen.werte?.export_formate ?? ['docx', 'pdf'];
        gewaehlt = f.filter((x) => vorgabe.includes(x.id)).map((x) => x.id);
      })
      .catch((e) => dialog.zeigen(e));
  });

  const passend = $derived(formate.filter((f) => f.inhalte.includes(inhalt)));
  const auswahl = $derived(gewaehlt.filter((g) => passend.some((p) => p.id === g)));

  function umschalten(id: string) {
    gewaehlt = gewaehlt.includes(id) ? gewaehlt.filter((g) => g !== id) : [...gewaehlt, id];
  }

  async function exportieren() {
    laeuft = true;
    try {
      ergebnis = await api.exportieren(details.id, inhalt, auswahl);
      exportiert?.();
    } catch (e) {
      schliessen();
      dialog.zeigen(e, 'Export hat nicht geklappt');
    } finally {
      laeuft = false;
    }
  }

  const imOrdner = $derived(!!verbindung.info?.faehigkeiten.ordner_oeffnen);

  async function laden(name: string) {
    try {
      await api.dateiSpeichern(details.id, name);
    } catch (e) {
      dialog.zeigen(e, 'Herunterladen hat nicht geklappt');
    }
  }

  async function zeigen(pfad: string) {
    try {
      await api.ordnerOeffnen(pfad);
    } catch (e) {
      dialog.zeigen(e);
    }
  }
</script>

<Dialog {offen} titel="Exportieren" {schliessen}>
  {#snippet kinder()}
    {#if ergebnis}
      <ul class="ergebnis">
        {#each ergebnis.dateien as d (d.pfad)}
          <li>
            <span class="datei"><Check size={16} /> <span class="name">{d.name}</span></span>
            {#if imOrdner}
              <button class="knopf leise" type="button" onclick={() => zeigen(d.pfad)}>
                <FolderOpen size={16} /> Im Ordner zeigen
              </button>
            {:else}
              <button class="knopf" type="button" onclick={() => laden(d.name)}>
                <Download size={16} /> Herunterladen
              </button>
            {/if}
          </li>
        {/each}
        {#each ergebnis.fehler as f, i (i)}<li class="fehler">{f}</li>{/each}
      </ul>
    {:else}
      <fieldset>
        <legend>Inhalt</legend>
        <div class="wahl">
          {#each [['transkript', 'Transkript'], ['protokoll', 'Zusammenfassung'], ['beides', 'Beides']] as [wert, text] (wert)}
            <label class="option" class:aus={wert !== 'transkript' && !details.protokoll}>
              <input
                type="radio"
                name="inhalt"
                value={wert}
                bind:group={inhalt}
                disabled={wert !== 'transkript' && !details.protokoll}
              />
              {text}
            </label>
          {/each}
        </div>
      </fieldset>
      <fieldset>
        <legend>Format</legend>
        <div class="wahl">
          {#each passend as f (f.id)}
            <label class="option">
              <input type="checkbox" checked={gewaehlt.includes(f.id)} onchange={() => umschalten(f.id)} />
              {f.name}
            </label>
          {/each}
        </div>
      </fieldset>
    {/if}
  {/snippet}
  {#snippet knoepfe()}
    {#if ergebnis}
      <button class="knopf primaer" type="button" onclick={schliessen}>Fertig</button>
    {:else}
      <button class="knopf" type="button" onclick={schliessen}>Abbrechen</button>
      <button class="knopf primaer" type="button" disabled={!auswahl.length || laeuft} onclick={exportieren}>
        Exportieren
      </button>
    {/if}
  {/snippet}
</Dialog>

<style>
  fieldset {
    border: none;
    margin: 0 0 14px;
    padding: 0;
  }

  legend {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
    margin-bottom: 6px;
  }

  .wahl {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .option {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border: 1px solid var(--rand);
    border-radius: 8px;
    color: var(--text);
    cursor: pointer;
  }

  .option:has(input:checked) {
    border-color: var(--akzent);
    background: var(--akzent-weich);
  }

  .option.aus {
    opacity: 0.5;
    cursor: default;
  }

  .ergebnis {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--text);
  }

  .ergebnis li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  .datei {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    color: var(--ok);
  }

  .datei .name {
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fehler {
    color: var(--fehler);
  }
</style>
