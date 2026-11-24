<script lang="ts">
  /** Online-Dienst wählen: fertige Anbieter, Zugangsschlüssel; Adresse und Modell unter „Erweitert“. */
  import Check from '@lucide/svelte/icons/check';
  import { api } from '#lib/api/client.ts';
  import type { Anbieter, Einstellungen, SchluesselStand } from '#lib/api/typen.ts';
  import { einstellungen } from '#lib/stores/einstellungen.svelte.ts';
  import { dialog, meldungen } from '#lib/stores/oberflaeche.svelte.ts';
  import Erweitert from '../Erweitert.svelte';

  type Bereich = 'transkription' | 'nachbearbeitung' | 'chat';

  let { bereich, anbieter }: { bereich: Bereich; anbieter: Anbieter[] } = $props();

  const FELDER = {
    transkription: {
      voreinstellung: 'api_transkription_voreinstellung',
      endpunkt: 'api_transkription_endpunkt',
      modell: 'api_transkription_modell'
    },
    nachbearbeitung: {
      voreinstellung: 'api_nachbearbeitung_voreinstellung',
      endpunkt: 'api_nachbearbeitung_endpunkt',
      modell: 'api_nachbearbeitung_modell'
    },
    chat: {
      voreinstellung: 'chatbot_api_voreinstellung',
      endpunkt: 'chatbot_api_endpunkt',
      modell: 'chatbot_api_modell'
    }
  } as const;

  const f = $derived(FELDER[bereich]);
  const w = $derived(einstellungen.werte ?? ({} as Einstellungen));
  const passend = $derived(anbieter.filter((a) => (bereich === 'transkription' ? a.transkription : a.chat)));
  const gewaehlt = $derived(String(w[f.voreinstellung] ?? ''));
  const vorlage = $derived(passend.find((a) => a.id === gewaehlt) ?? null);

  /** Welcher gespeicherte Schlüssel gilt? (wie `Schluesselablage` im Dienst) */
  const schluesselName = $derived.by((): keyof SchluesselStand => {
    if (bereich === 'transkription') return 'transkription';
    if (bereich === 'chat' && w.chatbot_api_eigener_schluessel) return 'chatbot';
    if (w.api_nachbearbeitung_eigener_schluessel) return 'nachbearbeitung';
    return 'transkription';
  });
  const vorhanden = $derived(!!einstellungen.schluessel?.[schluesselName]);

  let schluessel = $state('');
  let merken = $state(true);
  let endpunkt = $state('');
  let modell = $state('');
  let embEndpunkt = $state('');
  let embModell = $state('');

  $effect(() => {
    endpunkt = String(w[f.endpunkt] ?? '');
    modell = String(w[f.modell] ?? '');
    embEndpunkt = String(w.chatbot_api_embedding_endpunkt ?? '');
    embModell = String(w.chatbot_api_embedding_modell ?? '');
  });

  async function setzen(aenderung: Partial<Einstellungen>) {
    try {
      await einstellungen.aendern(aenderung);
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    }
  }

  function anbieterWaehlen(id: string) {
    const a = passend.find((x) => x.id === id);
    const aenderung: Partial<Einstellungen> = { [f.voreinstellung]: id };
    const ziel = bereich === 'transkription' ? a?.transkription : a?.chat;
    if (ziel) {
      aenderung[f.endpunkt] = ziel.url;
      aenderung[f.modell] = ziel.modell;
    }
    // Wie die alte Anwendung: Bei der Transkription auch die Sprechertrennung des Anbieters übernehmen.
    if (bereich === 'transkription') aenderung.api_transkription_anbieter = a?.diarisierung_anbieter ?? '';
    if (bereich === 'chat' && a?.embedding) {
      aenderung.chatbot_api_embedding_endpunkt = a.embedding.url;
      aenderung.chatbot_api_embedding_modell = a.embedding.modell;
    }
    void setzen(aenderung);
  }

  async function schluesselSpeichern(e: SubmitEvent) {
    e.preventDefault();
    const name: keyof SchluesselStand =
      bereich === 'transkription' ? 'transkription' : bereich === 'chat' ? 'chatbot' : 'nachbearbeitung';
    try {
      if (bereich === 'nachbearbeitung' && !w.api_nachbearbeitung_eigener_schluessel) {
        await einstellungen.aendern({ api_nachbearbeitung_eigener_schluessel: true });
      }
      if (bereich === 'chat' && !w.chatbot_api_eigener_schluessel) {
        await einstellungen.aendern({ chatbot_api_eigener_schluessel: true });
      }
      const antwort = await api.schluesselSetzen(name, schluessel, merken);
      schluessel = '';
      await einstellungen.schluesselNeu();
      meldungen.zeigen(merken && !antwort.gemerkt ? 'Gespeichert (nur bis zum Beenden)' : 'Gespeichert');
    } catch (f) {
      dialog.zeigen(f, 'Schlüssel nicht gespeichert');
    }
  }

  function erweitertSpeichern() {
    const aenderung: Partial<Einstellungen> = { [f.endpunkt]: endpunkt.trim(), [f.modell]: modell.trim() };
    if (bereich === 'chat') {
      aenderung.chatbot_api_embedding_endpunkt = embEndpunkt.trim();
      aenderung.chatbot_api_embedding_modell = embModell.trim();
    }
    void setzen(aenderung).then(() => meldungen.zeigen('Gespeichert'));
  }
</script>

<div class="online">
  <label class="feldzeile">
    <span>Anbieter</span>
    <select
      class="feld"
      value={gewaehlt}
      onchange={(e) => anbieterWaehlen((e.currentTarget as HTMLSelectElement).value)}
    >
      <option value="" disabled>Bitte wählen</option>
      {#each passend as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
      <option value="eigener">Eigener Dienst</option>
    </select>
    {#if vorlage?.standort}<small class="leise">{vorlage.standort}</small>{/if}
  </label>

  <form class="feldzeile" onsubmit={schluesselSpeichern}>
    <span>
      Zugangsschlüssel
      {#if vorhanden}<em class="ok"><Check size={14} /> Hinterlegt</em>{:else}<em class="fehlt">
          Fehlt
        </em>{/if}
    </span>
    <div class="zeile">
      <input
        class="feld"
        type="password"
        autocomplete="off"
        placeholder={vorhanden ? 'Neuen Schlüssel eingeben' : 'Schlüssel eingeben'}
        aria-label="Zugangsschlüssel"
        bind:value={schluessel}
      />
      <button class="knopf" type="submit" disabled={!schluessel.trim()}>Speichern</button>
    </div>
    <label class="merken"><input type="checkbox" bind:checked={merken} /> Auf diesem Computer merken</label>
  </form>

  <Erweitert>
    {#snippet kinder()}
      <label class="feldzeile">
        <span>Adresse</span>
        <input class="feld" bind:value={endpunkt} spellcheck="false" />
      </label>
      <label class="feldzeile">
        <span>Modell</span>
        <input class="feld" bind:value={modell} spellcheck="false" />
      </label>
      {#if bereich === 'chat'}
        <label class="feldzeile">
          <span>Adresse für die Suche</span>
          <input class="feld" bind:value={embEndpunkt} spellcheck="false" />
        </label>
        <label class="feldzeile">
          <span>Modell für die Suche</span>
          <input class="feld" bind:value={embModell} spellcheck="false" />
        </label>
      {/if}
      <div><button class="knopf" type="button" onclick={erweitertSpeichern}>Übernehmen</button></div>
    {/snippet}
  </Erweitert>
</div>

<style>
  .online {
    width: 460px;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .feldzeile {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .feldzeile > span {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
    display: flex;
    gap: 8px;
  }

  em {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-style: normal;
    font-weight: 500;
  }

  .ok {
    color: var(--ok);
  }

  .fehlt {
    color: var(--warn);
  }

  .merken {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-2);
  }
</style>
