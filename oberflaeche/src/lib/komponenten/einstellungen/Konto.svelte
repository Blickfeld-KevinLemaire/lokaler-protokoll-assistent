<script lang="ts">
  /** Eigenes Konto (Servermodus): Passwort, eigene Zugangsschlüssel, Abmelden. */
  import { api } from '$lib/api/client';
  import type { NeuerZugang, Nutzer } from '$lib/api/typen';
  import { datumText } from '$lib/logik/format';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import Info from '../Info.svelte';
  import SchluesselEinmal from './SchluesselEinmal.svelte';

  let ich = $state<Nutzer | null>(null);
  let bisher = $state('');
  let neu = $state('');
  let bezeichnung = $state('');
  let neuerZugang = $state<NeuerZugang | null>(null);

  async function laden() {
    try {
      ich = await api.ich();
    } catch (e) {
      console.warn('Konto nicht geladen', e);
    }
  }

  $effect(() => {
    void verbindung.runde;
    if (verbindung.bereit) void laden();
  });

  async function passwortAendern(e: SubmitEvent) {
    e.preventDefault();
    try {
      await api.passwortAendern(bisher, neu);
      bisher = '';
      neu = '';
      meldungen.zeigen('Passwort geändert');
      void laden();
    } catch (f) {
      dialog.zeigen(f, 'Passwort nicht geändert');
    }
  }

  async function zugangAnlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      neuerZugang = await api.eigenerZugang(bezeichnung.trim());
      bezeichnung = '';
      void laden();
    } catch (f) {
      dialog.zeigen(f, 'Schlüssel nicht angelegt');
    }
  }

  async function zugangEntfernen(name: string) {
    if (!confirm(`Zugangsschlüssel „${name}“ entfernen?`)) return;
    try {
      await api.eigenenZugangEntfernen(name);
      void laden();
    } catch (f) {
      dialog.zeigen(f);
    }
  }
</script>

<div class="konto">
  <div class="wer">
    <span class="avatar" aria-hidden="true">
      {(ich?.anzeigename ?? verbindung.info?.anzeigename ?? '?').slice(0, 1)}
    </span>
    <div>
      <div class="name">{ich?.anzeigename ?? verbindung.info?.anzeigename}</div>
      <div class="leise klein">
        {ich?.name ?? verbindung.info?.angemeldet_als}{ich?.admin ? ' · Verwaltung' : ''}
      </div>
    </div>
    <span class="raum"></span>
    <button class="knopf" type="button" onclick={() => verbindung.abmelden()}>Abmelden</button>
  </div>

  <form class="block" onsubmit={passwortAendern}>
    <span class="beschriftung">Passwort ändern</span>
    <div class="zeile">
      {#if ich?.hat_passwort}
        <input
          class="feld"
          type="password"
          autocomplete="current-password"
          placeholder="Bisher"
          aria-label="Bisheriges Passwort"
          bind:value={bisher}
        />
      {/if}
      <input
        class="feld"
        type="password"
        autocomplete="new-password"
        placeholder="Neu"
        aria-label="Neues Passwort"
        bind:value={neu}
      />
      <button class="knopf" type="submit" disabled={!neu || (ich?.hat_passwort && !bisher)}>Ändern</button>
    </div>
  </form>

  <div class="block">
    <span class="beschriftung">
      Zugangsschlüssel
      <Info
        frage="Wofür sind Zugangsschlüssel?"
        text="Damit melden Sie sich ohne Passwort an, z. B. auf einem zweiten Computer. Jeder Schlüssel lässt sich einzeln entfernen."
      />
    </span>
    {#if ich?.zugaenge.length}
      <ul class="zugaenge">
        {#each ich.zugaenge as z (z.bezeichnung)}
          <li>
            <span class="z-name">{z.bezeichnung}</span>
            <span class="leise klein">{datumText(z.angelegt)}</span>
            <button
              class="symbolknopf"
              type="button"
              aria-label="{z.bezeichnung} entfernen"
              onclick={() => zugangEntfernen(z.bezeichnung)}
            >
              ✕
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    <form class="zeile" onsubmit={zugangAnlegen}>
      <input
        class="feld"
        placeholder="Bezeichnung, z. B. Laptop"
        aria-label="Bezeichnung"
        maxlength="60"
        bind:value={bezeichnung}
      />
      <button class="knopf" type="submit" disabled={!bezeichnung.trim()}>+&nbsp; Neuer Schlüssel</button>
    </form>
  </div>
</div>

<SchluesselEinmal zugang={neuerZugang} schliessen={() => (neuerZugang = null)} />

<style>
  .konto {
    width: 520px;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .wer {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .avatar {
    width: 38px;
    height: 38px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--akzent);
    color: var(--akzent-text);
    font-weight: 600;
    text-transform: uppercase;
  }

  .name {
    font-weight: 600;
  }

  .raum {
    flex: 1;
  }

  .block {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .beschriftung {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .zugaenge {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .zugaenge li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 4px 0;
  }

  .z-name {
    flex: 1;
  }
</style>
