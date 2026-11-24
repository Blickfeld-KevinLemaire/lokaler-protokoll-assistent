<script lang="ts">
  /**
   * Gerät ohne USB hinzufügen: Name (und im Servermodus Besitzer), danach Adresse und Schlüssel einmal zeigen.
   * Der Name darf Leerzeichen und Umlaute haben („Besprechungsraum 3“); die Regeln prüft der Dienst und nennt sie.
   */
  import Copy from '@lucide/svelte/icons/copy';
  import { api } from '#lib/api/client.ts';
  import type { GeraetAngelegt } from '#lib/api/typen.ts';
  import { dialog, meldungen } from '#lib/stores/oberflaeche.svelte.ts';
  import { personen } from '#lib/stores/personen.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import Dialog from '../Dialog.svelte';
  import Erweitert from '../Erweitert.svelte';

  let { offen, schliessen, fertig }: { offen: boolean; schliessen: () => void; fertig: () => void } =
    $props();

  let name = $state('');
  let besitzer = $state('');
  let angelegt = $state<GeraetAngelegt | null>(null);

  $effect(() => {
    if (offen && verbindung.mehrbenutzer) void personen.laden();
  });

  async function anlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      angelegt = await api.geraetAnlegen(name.trim(), besitzer || null);
      schliessen();
      name = '';
      fertig();
    } catch (f) {
      dialog.zeigen(f, 'Gerät nicht angelegt');
    }
  }

  async function kopieren(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      meldungen.zeigen('Kopiert');
    } catch {
      meldungen.zeigen('Kopieren nicht möglich', 'fehler');
    }
  }
</script>

<Dialog {offen} titel="Gerät hinzufügen" {schliessen}>
  {#snippet kinder()}
    <form id="geraet-form" class="formular" onsubmit={anlegen}>
      <label class="feldzeile">
        <span>Name</span>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="feld"
          maxlength="32"
          placeholder="z. B. Besprechungsraum 3"
          autofocus
          bind:value={name}
        />
      </label>
      {#if verbindung.mehrbenutzer}
        <label class="feldzeile">
          <span>Gehört</span>
          <select class="feld" bind:value={besitzer}>
            <option value="">Allgemein</option>
            {#each personen.liste as p (p.name)}<option value={p.name}>{p.anzeigename}</option>{/each}
          </select>
        </label>
      {/if}
    </form>
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf" type="button" onclick={schliessen}>Abbrechen</button>
    <button class="knopf primaer" type="submit" form="geraet-form" disabled={!name.trim()}>Hinzufügen</button>
  {/snippet}
</Dialog>

<Dialog
  offen={!!angelegt}
  titel="„{angelegt?.name}“ einrichten"
  schliessen={() => (angelegt = null)}
  breite={560}
>
  {#snippet kinder()}
    {#if angelegt}
      <p class="einmal">Wird nur jetzt angezeigt.</p>
      <div class="kopierzeile">
        <span>Adresse</span>
        <code>{angelegt.basis_url}</code>
        <button class="knopf" type="button" onclick={() => kopieren(angelegt!.basis_url)}>
          <Copy size={16} /> Kopieren
        </button>
      </div>
      <div class="kopierzeile">
        <span>Schlüssel</span>
        <code>{angelegt.token}</code>
        <button class="knopf" type="button" onclick={() => kopieren(angelegt!.token)}>
          <Copy size={16} /> Kopieren
        </button>
      </div>
      <Erweitert titel="Für die Gerätesoftware">
        {#snippet kinder()}
          <div class="kopierzeile">
            <pre>{angelegt!.konfiguration}</pre>
            <button class="knopf" type="button" onclick={() => kopieren(angelegt!.konfiguration)}>
              <Copy size={16} /> Kopieren
            </button>
          </div>
        {/snippet}
      </Erweitert>
    {/if}
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf primaer" type="button" onclick={() => (angelegt = null)}>Fertig</button>
  {/snippet}
</Dialog>

<style>
  .formular {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .feldzeile {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .feldzeile > span {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }

  code {
    font-family: 'Cascadia Mono', Consolas, monospace;
    font-size: 12.5px;
    color: var(--text);
  }

  .einmal {
    color: var(--warn);
    font-weight: 600;
    margin-bottom: 12px;
  }

  .kopierzeile {
    display: grid;
    grid-template-columns: 80px minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
  }

  .kopierzeile code {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 6px 8px;
    border-radius: 6px;
    background: var(--karte-2);
  }

  .kopierzeile pre {
    grid-column: 1 / 3;
    margin: 0;
    padding: 8px;
    border-radius: 6px;
    background: var(--karte-2);
    font-size: 12px;
    overflow-x: auto;
    color: var(--text);
  }
</style>
