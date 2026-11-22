<script lang="ts">
  import { api } from '$lib/api/client';
  import type { BesprechungDetails, Vorlage } from '$lib/api/typen';
  import { startMeldung } from '$lib/logik/warteschlange';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import AuftragKarte from '../AuftragKarte.svelte';
  import Markdown from '../Markdown.svelte';

  let {
    details,
    text = $bindable(),
    nurLesen = false,
    gespeichert
  }: { details: BesprechungDetails; text: string; nurLesen?: boolean; gespeichert: () => void } = $props();

  let bearbeiten = $state(false);
  let speichert = $state(false);
  let vorlagen = $state<Vorlage[]>([]);
  let vorlageName = $state('');

  const original = $derived(details.protokoll?.text ?? '');
  const geaendert = $derived(text !== original);

  // Läuft oder wartet schon eine Zusammenfassung für diese Besprechung?
  const auftrag = $derived.by(() => {
    const letzter = zustand.auftraege.findLast(
      (a) => a.art === 'auswertung' && a.angaben?.transkript === details.transkript
    );
    return letzter && ['wartet', 'laeuft', 'fehler'].includes(letzter.status) ? letzter : null;
  });

  $effect(() => {
    api
      .vorlagen()
      .then((liste) => {
        vorlagen = liste;
        const aktiv = einstellungen.werte?.aktive_systemprompt_vorlage;
        vorlageName = liste.find((v) => v.name === aktiv)?.name ?? liste[0]?.name ?? '';
      })
      .catch((e) => console.warn('Vorlagen nicht geladen', e));
  });

  async function speichern() {
    speichert = true;
    try {
      const antwort = await api.protokollSpeichern(details.id, text);
      meldungen.zeigen(antwort.word_hinweis ? 'Gespeichert (Word-Datei nicht aktualisiert)' : 'Gespeichert');
      bearbeiten = false;
      gespeichert();
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    } finally {
      speichert = false;
    }
  }

  async function erstellen() {
    if (geaendert && !confirm('Ungespeicherte Änderungen gehen verloren. Trotzdem neu erstellen?')) return;
    try {
      const vorlage = vorlagen.find((v) => v.name === vorlageName);
      const neu = await api.auswertungStarten(details.transkript, vorlage?.text ?? null);
      zustand.auftragAktualisieren(neu);
      text = original;
      bearbeiten = false;
      meldungen.zeigen(startMeldung(neu, zustand.auftraege) ?? 'Zusammenfassung wird erstellt', 'info');
    } catch (e) {
      dialog.zeigen(e, 'Start nicht möglich');
    }
  }
</script>

{#if !nurLesen}
<div class="leiste">
  {#if vorlagen.length > 1}
    <select class="feld vorlage" aria-label="Vorlage" bind:value={vorlageName}>
      {#each vorlagen as v (v.name)}<option value={v.name}>{v.name}</option>{/each}
    </select>
  {/if}
  <button
    class="knopf"
    class:primaer={!details.protokoll}
    type="button"
    disabled={auftrag?.status === 'wartet' || auftrag?.status === 'laeuft'}
    onclick={erstellen}
  >
    {details.protokoll ? 'Neu erstellen' : 'Erstellen'}
  </button>
  <span class="raum"></span>
  {#if details.protokoll}
    {#if bearbeiten}
      <button
        class="knopf leise"
        type="button"
        onclick={() => {
          text = original;
          bearbeiten = false;
        }}
      >
        Verwerfen
      </button>
      <button class="knopf primaer" type="button" disabled={!geaendert || speichert} onclick={speichern}>
        Speichern
      </button>
    {:else}
      <button class="knopf" type="button" onclick={() => (bearbeiten = true)}>✎&nbsp; Bearbeiten</button>
    {/if}
  {/if}
</div>{/if}

{#if auftrag}
  <div class="auftrag"><AuftragKarte {auftrag} /></div>
{/if}

{#if details.protokoll}
  {#if bearbeiten}
    <div class="geteilt">
      <textarea
        class="feld editor"
        aria-label="Zusammenfassung bearbeiten"
        bind:value={text}
        spellcheck="true"></textarea>
      <div class="karte vorschau" aria-label="Vorschau"><Markdown {text} /></div>
    </div>
  {:else}
    <div class="karte lesen"><Markdown text={original} /></div>
  {/if}
{:else if !auftrag}
  <div class="leer">Noch keine Zusammenfassung</div>
{/if}

<style>
  .leiste {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 14px;
  }

  .vorlage {
    width: 220px;
  }

  .raum {
    flex: 1;
  }

  .auftrag {
    margin-bottom: 14px;
  }

  .lesen {
    padding: 22px 26px;
  }

  .geteilt {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    height: calc(100vh - 260px);
    min-height: 360px;
  }

  .editor {
    height: 100%;
    resize: none;
    font-family: 'Cascadia Mono', Consolas, 'Segoe UI Mono', monospace;
    font-size: 13px;
  }

  .vorschau {
    padding: 18px 22px;
    overflow-y: auto;
  }
</style>
