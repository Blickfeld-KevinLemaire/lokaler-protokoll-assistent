<script lang="ts">
  import '../app.css';
  import { onMount, type Snippet } from 'svelte';
  import Anmeldung from '$lib/komponenten/Anmeldung.svelte';
  import FehlerDialog from '$lib/komponenten/FehlerDialog.svelte';
  import Meldungen from '$lib/komponenten/Meldungen.svelte';
  import Seitenleiste from '$lib/komponenten/Seitenleiste.svelte';
  import StartBildschirm from '$lib/komponenten/StartBildschirm.svelte';
  import { protokollEinrichten } from '$lib/protokoll';
  import { meldungen, uhr } from '$lib/stores/oberflaeche.svelte';
  import { thema } from '$lib/stores/thema.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import { befehl, istTauri } from '$lib/tauri';

  let { children }: { children: Snippet } = $props();

  let schonBereit = $state(false);
  let einrichtungAus = $state(false);

  const EINRICHTUNG_SCHLUESSEL = 'vermerk.einrichtungshinweis';

  onMount(() => {
    thema.laden();
    if (istTauri()) {
      protokollEinrichten((stufe, text) => {
        void befehl('protokoll_schreiben', { stufe, text }).catch(() => undefined);
      });
    }
    try {
      einrichtungAus = sessionStorage.getItem(EINRICHTUNG_SCHLUESSEL) === 'aus';
    } catch {
      einrichtungAus = false;
    }
    uhr.starten();
    void verbindung.starten();
  });

  $effect(() => {
    if (verbindung.bereit) schonBereit = true;
  });

  $effect(() => {
    const text = zustand.fehlermeldung;
    if (text) {
      meldungen.zeigen(text.length > 140 ? `${text.slice(0, 138)} …` : text, 'fehler', 8000);
      zustand.fehlermeldung = null;
    }
  });

  function einrichtungAusblenden() {
    einrichtungAus = true;
    try {
      sessionStorage.setItem(EINRICHTUNG_SCHLUESSEL, 'aus');
    } catch {
      // egal
    }
  }

  const phase = $derived(verbindung.phase);
  const vollbild = $derived(
    phase === 'fehlgeschlagen' ||
      phase === 'neustart' ||
      (!schonBereit && (phase === 'startet' || phase === 'getrennt'))
  );
</script>

{#if phase === 'anmelden'}
  <Anmeldung />
{:else if vollbild}
  <StartBildschirm
    zustand={phase === 'fehlgeschlagen' ? 'fehlgeschlagen' : phase === 'neustart' ? 'neustart' : 'startet'}
    meldung={verbindung.meldung}
  />
{:else}
  <Seitenleiste />
  <main class="inhalt">
    {#if verbindung.info && !verbindung.info.einrichtung_abgeschlossen && !einrichtungAus}
      <div class="einrichtung">
        <span>Einrichtung noch nicht abgeschlossen</span>
        <a href="/einstellungen">Zu den Einstellungen</a>
        <button
          class="symbolknopf"
          type="button"
          aria-label="Hinweis schließen"
          onclick={einrichtungAusblenden}
        >
          ✕
        </button>
      </div>
    {/if}
    {@render children()}
  </main>
{/if}

<FehlerDialog />
<Meldungen />

<style>
  .inhalt {
    margin-left: 250px;
    min-height: 100vh;
    min-width: 850px;
    padding: 26px 36px 48px;
    max-width: 1320px;
  }

  .einrichtung {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: -6px 0 18px;
    padding: 6px 6px 6px 14px;
    border-radius: 8px;
    background: var(--akzent-weich);
    color: var(--text);
    font-size: 13px;
  }

  .einrichtung span {
    flex: 1;
  }
</style>
