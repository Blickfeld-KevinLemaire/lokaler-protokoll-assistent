<script lang="ts">
  /** Sprachmodell auf diesem Computer: empfohlene Auswahl, Herunterladen als Auftrag in der Warteschlange. */
  import { api } from '$lib/api/client';
  import type { ModellStand } from '$lib/api/typen';
  import { startMeldung } from '$lib/logik/warteschlange';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Fortschritt from '../Fortschritt.svelte';

  let { feld = 'ollama_modell' }: { feld?: 'ollama_modell' | 'chatbot_ollama_modell' } = $props();

  let stand = $state<ModellStand | null>(null);

  $effect(() => {
    void verbindung.runde;
    void zustand.besprechungenStand; // ändert sich auch, wenn ein Herunterladen fertig wird
    if (!verbindung.bereit) return;
    api
      .modelle()
      .then((s) => (stand = s))
      .catch((e) => console.warn('Modelle nicht geladen', e));
  });

  const gewaehlt = $derived(String(einstellungen.werte?.[feld] ?? ''));

  function installiert(id: string): boolean {
    if (!stand) return false;
    const ohneTag = id.includes(':') ? id : `${id}:latest`;
    return stand.installiert.some((m) => m === id || m === ohneTag);
  }

  function ladeAuftrag(id: string) {
    return zustand.auftraege.find(
      (a) =>
        a.art === 'modell_laden' &&
        a.angaben?.modell === id &&
        (a.status === 'wartet' || a.status === 'laeuft')
    );
  }

  /** „Qwen3.5 4B (empfohlener Standard)“ → Name und Zusatz getrennt. */
  function teile(label: string): [string, string] {
    const m = /^(.*?)\s*\((.*)\)\s*$/.exec(label);
    return m ? [m[1]!, m[2]!] : [label, ''];
  }

  async function waehlen(id: string) {
    try {
      await einstellungen.aendern({ [feld]: id });
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    }
  }

  async function laden(id: string) {
    try {
      const auftrag = await api.modellLaden(id);
      zustand.auftragAktualisieren(auftrag);
      meldungen.zeigen(startMeldung(auftrag, zustand.auftraege) ?? 'Wird heruntergeladen', 'info');
    } catch (e) {
      dialog.zeigen(e, 'Herunterladen nicht möglich');
    }
  }
</script>

{#if stand && !stand.laeuft}
  <p class="warn">⚠ Die KI auf diesem Computer ist gerade nicht erreichbar.</p>
{/if}

<ul class="modelle" role="radiogroup" aria-label="Sprachmodell">
  {#each stand?.empfohlen ?? [] as m (m.id)}
    {@const [name, zusatz] = teile(m.label)}
    {@const da = installiert(m.id)}
    {@const auftrag = ladeAuftrag(m.id)}
    <li class:aktiv={gewaehlt === m.id}>
      <label class="wahl">
        <input type="radio" name="modell-{feld}" checked={gewaehlt === m.id} onchange={() => waehlen(m.id)} />
        <span class="text">
          <span class="name">{name}</span>
          {#if zusatz}<span class="zusatz">{zusatz}</span>{/if}
        </span>
      </label>
      <span class="groesse">{String(m.groesse_gb).replace('.', ',')} GB</span>
      <span class="aktion">
        {#if auftrag}
          <span class="balken">
            <Fortschritt
              anteil={auftrag.status === 'laeuft' ? auftrag.fortschritt : null}
              beschriftung="Herunterladen"
            />
          </span>
        {:else if da}
          <span class="ok">✓ Vorhanden</span>
        {:else}
          <button class="knopf" type="button" disabled={!stand?.laeuft} onclick={() => laden(m.id)}>
            Herunterladen
          </button>
        {/if}
      </span>
    </li>
  {/each}
</ul>

<style>
  .warn {
    color: var(--warn);
  }

  .modelle {
    list-style: none;
    margin: 0;
    padding: 0;
    width: 620px;
    max-width: 100%;
    border: 1px solid var(--rand);
    border-radius: var(--radius);
    overflow: hidden;
  }

  li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 70px 140px;
    gap: 12px;
    align-items: center;
    padding: 10px 14px;
    border-top: 1px solid var(--rand);
  }

  li:first-child {
    border-top: none;
  }

  li.aktiv {
    background: var(--akzent-weich);
  }

  .wahl {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }

  .text {
    display: flex;
    flex-direction: column;
  }

  .name {
    font-weight: 500;
  }

  .zusatz {
    font-size: 12.5px;
    color: var(--text-2);
  }

  .groesse {
    color: var(--text-2);
    font-size: 13px;
    text-align: right;
  }

  .aktion {
    display: flex;
    justify-content: flex-end;
  }

  .balken {
    width: 100%;
  }

  .ok {
    color: var(--ok);
    font-size: 13px;
  }
</style>
