<script lang="ts">
  /** „Online-Dienst“: je online gewähltem Bereich ein Anbieter und sein Zugangsschlüssel. */
  import ExternalLink from '@lucide/svelte/icons/external-link';
  import { onMount } from 'svelte';
  import type { Anbieter } from '#lib/api/typen.ts';
  import { BEREICHE, type Bereich } from '#lib/logik/einrichtung.ts';
  import { einrichtung } from '#lib/stores/einrichtung.svelte.ts';
  import Info from '../Info.svelte';

  onMount(() => {
    void einrichtung.anbieterLaden();
  });

  function passend(bereich: Bereich): Anbieter[] {
    return einrichtung.anbieter.filter((a) =>
      bereich === 'transkription'
        ? !!a.transkription
        : bereich === 'chatbot'
          ? !!a.chat && !!a.embedding
          : !!a.chat
    );
  }

  function name(bereich: Bereich): string {
    return BEREICHE.find((b) => b.id === bereich)?.text ?? bereich;
  }
</script>

<div class="bereiche">
  {#each einrichtung.onlineBereiche as bereich (bereich)}
    {@const o = einrichtung.online[bereich]}
    {@const gewaehlt = einrichtung.anbieter.find((a) => a.id === o.anbieter)}
    <section class="karte bereich" aria-label={name(bereich)}>
      <h2>{name(bereich)}</h2>
      <label class="feldzeile">
        <span>Anbieter</span>
        <select class="feld" bind:value={einrichtung.online[bereich].anbieter}>
          <option value="" disabled>Bitte wählen</option>
          {#each passend(bereich) as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
        </select>
        {#if gewaehlt?.standort}<small class="leise">{gewaehlt.standort}</small>{/if}
      </label>
      <div class="feldzeile">
        <span class="beschriftung">
          <label for="schluessel-{bereich}">Zugangsschlüssel</label>
          <Info
            frage="Woher kommt der Zugangsschlüssel?"
            text="Sie bekommen ihn beim Anbieter, meist im Kundenkonto. Er bleibt auf diesem Computer."
          />
          {#if gewaehlt?.schluessel_link}
            <a class="extern" href={gewaehlt.schluessel_link} target="_blank" rel="noopener noreferrer">
              Schlüssel holen <ExternalLink size={14} />
            </a>
          {/if}
        </span>
        <input
          id="schluessel-{bereich}"
          class="feld"
          type="password"
          autocomplete="off"
          spellcheck="false"
          bind:value={einrichtung.online[bereich].schluessel}
        />
        <label class="merken">
          <input type="checkbox" bind:checked={einrichtung.online[bereich].merken} /> Auf diesem Computer merken
        </label>
      </div>
    </section>
  {/each}
</div>

<style>
  .bereiche {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .bereich {
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .feldzeile {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 460px;
  }

  .feldzeile > span,
  .beschriftung {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }

  .beschriftung {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .extern {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
    font-weight: 500;
  }

  .merken {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-2);
  }
</style>
