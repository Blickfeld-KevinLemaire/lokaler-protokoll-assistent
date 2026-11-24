<script lang="ts">
  /** „Einrichten“: die Aufträge der Einrichtung mit Fortschritt – dieselben stehen in der Seitenleiste. */
  import CircleCheck from '@lucide/svelte/icons/circle-check';
  import {
    einrichtungLaeuft,
    juengsteEinrichtungsAuftraege,
    sprechererkennungGescheitert
  } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Info from '../Info.svelte';
  import AuftragZeile from './AuftragZeile.svelte';

  // Nur die jüngsten je Art (ein früherer, abgebrochener Versuch soll nicht stören).
  const auftraege = $derived(juengsteEinrichtungsAuftraege(zustand.auftraege));
  const laeuft = $derived(einrichtungLaeuft(zustand.auftraege));
  const alleFertig = $derived(auftraege.length > 0 && auftraege.every((a) => a.status === 'fertig'));
  const schluesselNeu = $derived(!laeuft && sprechererkennungGescheitert(zustand.auftraege));
</script>

{#if auftraege.length}
  <ul class="karte liste" aria-live="polite">
    {#each auftraege as a (a.id)}
      <AuftragZeile auftrag={a} wiederholen={() => einrichtung.wiederholen(a.art)} />
    {/each}
  </ul>
{/if}

{#if schluesselNeu}
  <div class="schluessel">
    <span class="beschriftung">
      <label for="hf-schluessel-neu">Zugangsschlüssel für die Sprechererkennung</label>
      <Info
        frage="Wann ist das nötig?"
        text="Nur wenn der Schlüssel nicht stimmt. Leer lassen, um es mit dem bisherigen noch einmal zu versuchen."
      />
    </span>
    <input
      id="hf-schluessel-neu"
      class="feld"
      type="password"
      autocomplete="off"
      spellcheck="false"
      bind:value={einrichtung.hfSchluessel}
    />
  </div>
{/if}

{#if alleFertig && !laeuft}
  <p class="ok"><CircleCheck size={18} /> Alles eingerichtet</p>
{/if}

<style>
  .liste {
    list-style: none;
    margin: 0;
    padding: 0;
    width: 100%;
    text-align: left;
  }

  .schluessel {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 420px;
    text-align: left;
  }

  .beschriftung {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }

  .ok {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--ok);
    font-weight: 500;
  }
</style>
