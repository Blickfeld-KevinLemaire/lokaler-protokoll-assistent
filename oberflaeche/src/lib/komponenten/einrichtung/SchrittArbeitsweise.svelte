<script lang="ts">
  /** „Arbeitsweise“: je Bereich auf diesem Computer oder über einen Online-Dienst. */
  import { BEREICHE, schrittFuer, urteil, type Modus } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import Wahl from '../einstellungen/Wahl.svelte';
  import Info from '../Info.svelte';

  const MODI: { wert: Modus; text: string }[] = [
    { wert: 'lokal', text: 'Auf diesem Computer' },
    { wert: 'api', text: 'Online-Dienst' }
  ];

  const KURZ: Record<string, string> = { gut: 'Läuft gut', mittel: 'Dauert etwas', online: 'Besser online' };
</script>

<ul class="karte bereiche">
  {#each BEREICHE as b (b.id)}
    {@const u = urteil(schrittFuer(einrichtung.rechner, b.id)?.stufe)}
    <li>
      <span class="name">
        {b.text}
        {#if einrichtung.rechner}<span class="hinweis {u.ton}">{KURZ[u.ton]}</span>{/if}
      </span>
      <Wahl
        beschriftung={b.text}
        optionen={MODI}
        wert={einrichtung.wahl[b.id] ?? undefined}
        aendern={(m) => einrichtung.wahlSetzen(b.id, m)}
      />
    </li>
  {/each}
</ul>

<p class="fuss">
  <span>Online-Dienst</span>
  <Info
    frage="Was heißt Online-Dienst?"
    text="Die Aufnahme oder der Text geht dafür an einen Anbieter Ihrer Wahl. Das ist schneller, verlässt aber den Computer."
  />
</p>

<style>
  .bereiche {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 20px;
    border-top: 1px solid var(--rand);
  }

  li:first-child {
    border-top: none;
  }

  .name {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-weight: 600;
  }

  .hinweis {
    font-size: 12.5px;
    font-weight: 400;
    color: var(--text-2);
  }

  .fuss {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text-2);
    font-size: 13px;
  }
</style>
