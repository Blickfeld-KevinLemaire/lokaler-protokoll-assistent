<script lang="ts">
  /** Vorlagen für Zusammenfassungen bearbeiten; „Standard“ ist der allgemeine Auftrag. */
  import Check from '@lucide/svelte/icons/check';
  import Plus from '@lucide/svelte/icons/plus';
  import { api } from '#lib/api/client.ts';
  import type { Vorlage } from '#lib/api/typen.ts';
  import { einstellungen } from '#lib/stores/einstellungen.svelte.ts';
  import { dialog, meldungen } from '#lib/stores/oberflaeche.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';

  const STANDARD = '';

  let vorlagen = $state<Vorlage[]>([]);
  let standardText = $state('');
  let auswahl = $state(STANDARD);
  let text = $state('');
  let neuerName = $state('');
  let neuOffen = $state(false);

  async function laden() {
    const [liste, standard] = await Promise.all([api.vorlagen(), api.systemprompt()]);
    vorlagen = liste;
    standardText = standard.text;
    waehlen(auswahl);
  }

  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit) return;
    laden().catch((e) => console.warn('Vorlagen nicht geladen', e));
  });

  function waehlen(name: string) {
    auswahl = name;
    text = name === STANDARD ? standardText : (vorlagen.find((v) => v.name === name)?.text ?? '');
  }

  const original = $derived(
    auswahl === STANDARD ? standardText : (vorlagen.find((v) => v.name === auswahl)?.text ?? '')
  );
  const aktiv = $derived(einstellungen.werte?.aktive_systemprompt_vorlage ?? null);

  async function speichern() {
    try {
      if (auswahl === STANDARD) await api.systempromptSpeichern(text);
      else await api.vorlageSpeichern(auswahl, text);
      meldungen.zeigen('Gespeichert');
      await laden();
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    }
  }

  async function anlegen(e: SubmitEvent) {
    e.preventDefault();
    const name = neuerName.trim();
    if (!name) return;
    try {
      await api.vorlageSpeichern(name, text || standardText);
      neuerName = '';
      neuOffen = false;
      auswahl = name;
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Vorlage nicht angelegt');
    }
  }

  async function alsVorgabe() {
    try {
      await einstellungen.aendern({ aktive_systemprompt_vorlage: auswahl || null });
    } catch (e) {
      dialog.zeigen(e);
    }
  }
</script>

<div class="vorlagen">
  <div class="zeile">
    <select
      class="feld wahl"
      aria-label="Vorlage"
      value={auswahl}
      onchange={(e) => waehlen((e.currentTarget as HTMLSelectElement).value)}
    >
      <option value={STANDARD}>Standard</option>
      {#each vorlagen as v (v.name)}<option value={v.name}>{v.name}</option>{/each}
    </select>
    {#if (aktiv ?? '') === auswahl}
      <span class="ok klein"><Check size={16} /> Vorgabe</span>
    {:else}
      <button class="knopf leise" type="button" onclick={alsVorgabe}>Als Vorgabe</button>
    {/if}
    <span class="raum"></span>
    <button class="knopf leise" type="button" onclick={() => (neuOffen = !neuOffen)}>
      <Plus size={16} /> Neue Vorlage
    </button>
  </div>
  {#if neuOffen}
    <form class="zeile" onsubmit={anlegen}>
      <input
        class="feld"
        placeholder="Name"
        aria-label="Name der neuen Vorlage"
        maxlength="60"
        bind:value={neuerName}
      />
      <button class="knopf primaer" type="submit" disabled={!neuerName.trim()}>Anlegen</button>
    </form>
  {/if}
  <textarea class="feld text" rows="12" aria-label="Text der Vorlage" bind:value={text}></textarea>
  <div class="zeile rechts">
    <button class="knopf" type="button" disabled={text === original} onclick={() => (text = original)}>
      Verwerfen
    </button>
    <button class="knopf primaer" type="button" disabled={text === original} onclick={speichern}>
      Speichern
    </button>
  </div>
</div>

<style>
  .vorlagen {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .wahl {
    width: 240px;
  }

  .raum {
    flex: 1;
  }

  .text {
    font-size: 13px;
  }

  .rechts {
    justify-content: flex-end;
  }

  .ok {
    color: var(--ok);
  }
</style>
