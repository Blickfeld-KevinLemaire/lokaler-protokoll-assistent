<script lang="ts">
  import '../app.css';
  import { setLucideProps } from '@lucide/svelte';
  import { onMount, untrack, type Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import Anmeldung from '#lib/komponenten/Anmeldung.svelte';
  import Einrichtung from '#lib/komponenten/einrichtung/Einrichtung.svelte';
  import FehlerDialog from '#lib/komponenten/FehlerDialog.svelte';
  import Meldungen from '#lib/komponenten/Meldungen.svelte';
  import Rueckfrage from '#lib/komponenten/Rueckfrage.svelte';
  import Seitenleiste from '#lib/komponenten/Seitenleiste.svelte';
  import StartBildschirm from '#lib/komponenten/StartBildschirm.svelte';
  import { tastenkuerzel } from '#lib/logik/tasten.ts';
  import { protokollEinrichten } from '#lib/protokoll.ts';
  import { einrichtung } from '#lib/stores/einrichtung.svelte.ts';
  import { meldungen, uhr } from '#lib/stores/oberflaeche.svelte.ts';
  import { thema } from '#lib/stores/thema.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import { zustand } from '#lib/stores/zustand.svelte.ts';
  import { befehl, istTauri } from '#lib/tauri.ts';

  let { children }: { children: Snippet } = $props();

  // Ein Symbolsatz, überall gleich: 18 px, feine Linie, Textfarbe.
  setLucideProps({ size: 18, strokeWidth: 1.75 });

  let schonBereit = $state(false);

  onMount(() => {
    thema.laden();
    if (istTauri()) {
      protokollEinrichten((stufe, text) => {
        void befehl('protokoll_schreiben', { stufe, text }).catch(() => undefined);
      });
    }
    uhr.starten();
    void verbindung.starten();
  });

  $effect(() => {
    if (verbindung.bereit) schonBereit = true;
  });

  // Nach jedem Öffnen des Startgatters (auch nach einem Neustart): Ist die Einrichtung offen?
  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit) return;
    const info = verbindung.info;
    // Nur bei neuem Gatter prüfen – nicht jedes Mal, wenn sich in der Einrichtung etwas ändert.
    untrack(() => void einrichtung.pruefen(info));
  });

  $effect(() => {
    const text = zustand.fehlermeldung;
    if (text) {
      meldungen.zeigen(text.length > 140 ? `${text.slice(0, 138)} …` : text, 'fehler', 8000);
      zustand.fehlermeldung = null;
    }
  });

  function taste(e: KeyboardEvent) {
    if (!verbindung.bereit || einrichtung.aktiv) return;
    const ziel = tastenkuerzel(e);
    if (!ziel) return;
    e.preventDefault();
    if (ziel === 'suche') {
      const feld = document.getElementById('besprechungen-suche');
      if (feld) feld.focus();
      else void goto('/besprechungen?suche=1');
      return;
    }
    void goto(ziel === 'neu' ? '/?neu=1' : '/einstellungen');
  }

  const phase = $derived(verbindung.phase);
  const vollbild = $derived(
    phase === 'fehlgeschlagen' ||
      phase === 'neustart' ||
      (!schonBereit && (phase === 'startet' || phase === 'getrennt'))
  );
</script>

<svelte:window onkeydown={taste} />

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
    {#if einrichtung.aktiv}
      <Einrichtung />
    {:else}
      {@render children()}
    {/if}
  </main>
{/if}

<FehlerDialog />
<Rueckfrage />
<Meldungen />

<style>
  .inhalt {
    margin-left: 250px;
    min-height: 100vh;
    min-width: 850px;
    padding: 24px 36px 48px;
    max-width: 1320px;
  }
</style>
