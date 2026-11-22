<script lang="ts">
  /** „Einrichten“: die Aufträge der Einrichtung mit Fortschritt – dieselben stehen in der Seitenleiste. */
  import CircleCheck from '@lucide/svelte/icons/circle-check';
  import type { Auftrag } from '$lib/api/typen';
  import { einrichtungLaeuft, einrichtungsAuftraege } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import AuftragZeile from './AuftragZeile.svelte';

  // Nur die jüngsten je Art (ein früherer, abgebrochener Versuch soll nicht stören).
  const auftraege = $derived.by(() => {
    const jeArt: Record<string, Auftrag> = {};
    for (const a of einrichtungsAuftraege(zustand.auftraege)) {
      const bisher = jeArt[a.art];
      if (!bisher || bisher.erstellt <= a.erstellt) jeArt[a.art] = a;
    }
    return Object.values(jeArt).sort((a, b) => a.erstellt - b.erstellt);
  });
  const laeuft = $derived(einrichtungLaeuft(zustand.auftraege));
  const alleFertig = $derived(auftraege.length > 0 && auftraege.every((a) => a.status === 'fertig'));
</script>

{#if auftraege.length}
  <ul class="karte liste" aria-live="polite">
    {#each auftraege as a (a.id)}
      <AuftragZeile auftrag={a} wiederholen={() => einrichtung.wiederholen(a.art)} />
    {/each}
  </ul>
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

  .ok {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--ok);
    font-weight: 500;
  }
</style>
