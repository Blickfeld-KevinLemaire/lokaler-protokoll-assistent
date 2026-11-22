<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { Vorlage } from '$lib/api/typen';
  import AuftragKarte from '$lib/komponenten/AuftragKarte.svelte';
  import Erweitert from '$lib/komponenten/Erweitert.svelte';
  import Info from '$lib/komponenten/Info.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import Schalter from '$lib/komponenten/Schalter.svelte';
  import Quelle, { type Auswahl } from '$lib/komponenten/transkription/Quelle.svelte';
  import { startMeldung } from '$lib/logik/warteschlange';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';

  const SPRACHEN = [
    { wert: 'de', text: 'Deutsch' },
    { wert: 'en', text: 'Englisch' },
    { wert: 'fr', text: 'Französisch' },
    { wert: 'es', text: 'Spanisch' },
    { wert: 'it', text: 'Italienisch' },
    { wert: 'nl', text: 'Niederländisch' },
    { wert: 'pl', text: 'Polnisch' },
    { wert: 'tr', text: 'Türkisch' },
    { wert: '', text: 'Automatisch erkennen' }
  ];
  const MEIN_AUFTRAG = 'vermerk.meinAuftrag';

  let auswahl = $state<Auswahl | null>(null);
  let sprache = $state('de');
  let sprecher = $state(true);
  let minSprecher = $state<number | null>(null);
  let maxSprecher = $state<number | null>(null);
  let offline = $state(false);
  let neuBeginnen = $state(false);
  let zusammenfassung = $state(true);
  let vorlagen = $state<Vorlage[]>([]);
  let vorlageName = $state('');
  let startet = $state(false);
  let vorgabenGesetzt = false;
  let meinAuftragId = $state<string | null>(lesen());

  function lesen(): string | null {
    try {
      return sessionStorage.getItem(MEIN_AUFTRAG);
    } catch {
      return null;
    }
  }

  function merken(id: string | null) {
    meinAuftragId = id;
    try {
      if (id) sessionStorage.setItem(MEIN_AUFTRAG, id);
      else sessionStorage.removeItem(MEIN_AUFTRAG);
    } catch {
      // nur für diese Ansicht
    }
  }

  const meinAuftrag = $derived(zustand.auftraege.find((a) => a.id === meinAuftragId) ?? null);

  $effect(() => {
    const w = einstellungen.werte;
    if (!w || vorgabenGesetzt) return;
    vorgabenGesetzt = true;
    sprache = w.sprache ?? 'de';
    offline = !!w.offline;
  });

  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit) return;
    api
      .vorlagen()
      .then((liste) => {
        vorlagen = liste;
        const aktiv = einstellungen.werte?.aktive_systemprompt_vorlage;
        vorlageName = liste.find((v) => v.name === aktiv)?.name ?? liste[0]?.name ?? '';
      })
      .catch((e) => console.warn('Vorlagen nicht geladen', e));
  });

  // „+ Neue Transkription“ in der Seitenleiste
  $effect(() => {
    if (page.url.searchParams.get('neu')) {
      auswahl = null;
      if (meinAuftrag && !['wartet', 'laeuft'].includes(meinAuftrag.status)) merken(null);
      void goto('/', { replaceState: true, noScroll: true });
    }
  });

  async function starten() {
    if (!auswahl) return;
    startet = true;
    try {
      const vorlage = vorlagen.find((v) => v.name === vorlageName);
      const auftrag = await api.transkriptionStarten({
        quelle: auswahl.pfad,
        sprache: sprache || null,
        sprechertrennung: sprecher,
        min_sprecher: sprecher ? minSprecher || null : null,
        max_sprecher: sprecher ? maxSprecher || null : null,
        offline,
        fortsetzen: !neuBeginnen,
        mit_auswertung: zusammenfassung,
        systemprompt: zusammenfassung && vorlage ? vorlage.text : null
      });
      zustand.auftragAktualisieren(auftrag);
      merken(auftrag.id);
      auswahl = null;
      meldungen.zeigen(startMeldung(auftrag, zustand.auftraege) ?? 'Gestartet', 'info');
    } catch (e) {
      dialog.zeigen(e, 'Start nicht möglich');
    } finally {
      startet = false;
    }
  }
</script>

<Kopf titel="Transkription" />

<div class="raster">
  <div class="links">
    <Quelle bind:auswahl />
  </div>

  <aside class="karte optionen" aria-label="Optionen">
    <label class="feldzeile">
      <span>Sprache</span>
      <select class="feld" bind:value={sprache}>
        {#each SPRACHEN as s (s.wert)}<option value={s.wert}>{s.text}</option>{/each}
      </select>
    </label>

    <Schalter bind:an={sprecher} beschriftung="Sprecher erkennen">
      {#snippet info()}
        <Info
          frage="Was bedeutet Sprecher erkennen?"
          text="Der Text wird nach Personen getrennt, z. B. „Sprecher 1“ und „Sprecher 2“. Namen lassen sich danach vergeben."
        />
      {/snippet}
    </Schalter>

    <Schalter bind:an={zusammenfassung} beschriftung="Danach Zusammenfassung erstellen" />
    {#if zusammenfassung && vorlagen.length > 1}
      <label class="feldzeile eingerueckt">
        <span>Vorlage</span>
        <select class="feld" bind:value={vorlageName}>
          {#each vorlagen as v (v.name)}<option value={v.name}>{v.name}</option>{/each}
        </select>
      </label>
    {/if}

    <Erweitert>
      {#snippet kinder()}
        {#if sprecher}
          <div class="feldzeile">
            <span>Anzahl Sprecher</span>
            <div class="zeile">
              <input
                class="feld zahl"
                type="number"
                min="1"
                max="30"
                placeholder="von"
                aria-label="Mindestens"
                bind:value={minSprecher}
              />
              <span class="leise">–</span>
              <input
                class="feld zahl"
                type="number"
                min="1"
                max="30"
                placeholder="bis"
                aria-label="Höchstens"
                bind:value={maxSprecher}
              />
            </div>
          </div>
        {/if}
        <Schalter bind:an={offline} beschriftung="Ohne Internet">
          {#snippet info()}
            <Info
              frage="Was bedeutet Ohne Internet?"
              text="Es wird nichts nachgeladen. Das klappt nur, wenn alles Nötige schon auf diesem Computer ist."
            />
          {/snippet}
        </Schalter>
        <Schalter bind:an={neuBeginnen} beschriftung="Neu beginnen">
          {#snippet info()}
            <Info
              frage="Was bedeutet Neu beginnen?"
              text="Wurde diese Aufnahme schon einmal angefangen, geht es sonst dort weiter. Eingeschaltet beginnt alles von vorn."
            />
          {/snippet}
        </Schalter>
      {/snippet}
    </Erweitert>

    <button class="knopf primaer gross start" type="button" disabled={!auswahl || startet} onclick={starten}>
      Transkription starten
    </button>
  </aside>
</div>

{#if meinAuftrag}
  <div class="mein">
    <AuftragKarte auftrag={meinAuftrag} schliessen={() => merken(null)} />
  </div>
{/if}

<style>
  .raster {
    display: grid;
    grid-template-columns: minmax(0, 1.55fr) minmax(280px, 1fr);
    gap: 20px;
    align-items: start;
  }

  .optionen {
    padding: 18px 20px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
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
  }

  .eingerueckt {
    margin: -4px 0 0 46px;
  }

  .zahl {
    width: 80px;
  }

  .start {
    margin-top: 6px;
    width: 100%;
  }

  .mein {
    margin-top: 24px;
  }
</style>
