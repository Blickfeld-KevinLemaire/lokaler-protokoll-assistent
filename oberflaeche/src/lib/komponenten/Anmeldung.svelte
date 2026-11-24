<script lang="ts">
  /**
   * Anmeldung im Browser. Name und Passwort gibt es nur mit mehreren Nutzern (`GET /api/anmeldung`);
   * sonst genügt der Zugangsschlüssel.
   */
  import { onMount } from 'svelte';
  import { api, ApiFehler } from '#lib/api/client.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';

  type Art = 'passwort' | 'schluessel';
  const ART_SCHLUESSEL = 'vermerk.anmeldeart';

  function gemerkt(): Art {
    try {
      return localStorage.getItem(ART_SCHLUESSEL) === 'schluessel' ? 'schluessel' : 'passwort';
    } catch {
      return 'passwort';
    }
  }

  let mehrbenutzer = $state<boolean | null>(null);
  let art = $state<Art>(gemerkt());

  onMount(() => {
    api
      .anmeldung()
      .then((a) => {
        mehrbenutzer = a.mehrbenutzer;
        if (!a.mehrbenutzer) art = 'schluessel';
      })
      .catch(() => (mehrbenutzer = true));
  });
  let name = $state('');
  let passwort = $state('');
  let schluessel = $state('');
  let fehler = $state('');
  let laeuft = $state(false);

  const vollstaendig = $derived(art === 'passwort' ? !!name.trim() && !!passwort : !!schluessel.trim());

  function wechseln(neu: Art) {
    art = neu;
    fehler = '';
    try {
      localStorage.setItem(ART_SCHLUESSEL, neu);
    } catch {
      // nicht speicherbar
    }
  }

  async function absenden(e: SubmitEvent) {
    e.preventDefault();
    if (!vollstaendig) return;
    laeuft = true;
    fehler = '';
    try {
      await verbindung.anmelden(
        art === 'passwort' ? { name: name.trim(), passwort } : { schluessel: schluessel.trim() }
      );
      passwort = '';
      schluessel = '';
    } catch (f) {
      fehler = f instanceof ApiFehler ? f.message : 'Anmeldung nicht möglich.';
    } finally {
      laeuft = false;
    }
  }
</script>

<svelte:head><title>Anmelden · VERMERK</title></svelte:head>

<main class="anmeldung">
  <form class="karte" onsubmit={absenden}>
    <div class="logo"><img src="/vermerk_logo_hell.png" alt="VERMERK" width="180" height="40" /></div>

    {#if mehrbenutzer === null}
      <div class="platzhalter" aria-hidden="true"></div>
    {:else if art === 'passwort'}
      <label for="name">Name</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input id="name" class="feld" autocomplete="username" autofocus bind:value={name} />
      <label for="passwort">Passwort</label>
      <input
        id="passwort"
        class="feld"
        type="password"
        autocomplete="current-password"
        bind:value={passwort}
        aria-invalid={!!fehler}
        aria-describedby={fehler ? 'anmeldefehler' : undefined}
      />
    {:else}
      <label for="schluessel">Zugangsschlüssel</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input
        id="schluessel"
        class="feld"
        type="password"
        autocomplete="off"
        autofocus
        bind:value={schluessel}
        aria-invalid={!!fehler}
        aria-describedby={fehler ? 'anmeldefehler' : undefined}
      />
    {/if}
    {#if fehler}<p id="anmeldefehler" class="fehler" role="alert">{fehler}</p>{/if}
    <button class="knopf primaer gross" type="submit" disabled={laeuft || !vollstaendig}>Anmelden</button>
    {#if mehrbenutzer}
      <button
        class="wechsel"
        type="button"
        onclick={() => wechseln(art === 'passwort' ? 'schluessel' : 'passwort')}
      >
        {art === 'passwort' ? 'Mit Zugangsschlüssel anmelden' : 'Mit Name und Passwort anmelden'}
      </button>
    {/if}
  </form>
</main>

<style>
  .anmeldung {
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 24px;
    background: var(--bg);
  }

  form {
    width: 340px;
    padding: 0 28px 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow: hidden;
  }

  .logo {
    margin: 0 -28px 18px;
    padding: 22px 28px;
    background: var(--sb-bg);
  }

  label {
    font-weight: 600;
    font-size: 13px;
    margin-top: 4px;
  }

  .platzhalter {
    height: 62px;
  }

  .fehler {
    color: var(--fehler);
    font-size: 13px;
  }

  button[type='submit'] {
    margin-top: 12px;
  }

  .wechsel {
    margin-top: 4px;
    padding: 6px;
    border: none;
    background: none;
    color: var(--link);
    font-size: 13px;
    cursor: pointer;
    border-radius: 6px;
  }
</style>
