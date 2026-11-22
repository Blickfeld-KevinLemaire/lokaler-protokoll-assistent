<script lang="ts">
  import { ApiFehler } from '$lib/api/client';
  import { verbindung } from '$lib/stores/verbindung.svelte';

  let schluessel = $state('');
  let fehler = $state('');
  let laeuft = $state(false);

  async function absenden(e: SubmitEvent) {
    e.preventDefault();
    if (!schluessel.trim()) return;
    laeuft = true;
    fehler = '';
    try {
      await verbindung.anmelden(schluessel.trim());
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
    <label for="schluessel">Zugangsschlüssel</label>
    <!-- svelte-ignore a11y_autofocus -->
    <input
      id="schluessel"
      class="feld"
      type="password"
      autocomplete="current-password"
      autofocus
      bind:value={schluessel}
      aria-invalid={!!fehler}
      aria-describedby={fehler ? 'anmeldefehler' : undefined}
    />
    {#if fehler}<p id="anmeldefehler" class="fehler">{fehler}</p>{/if}
    <button class="knopf primaer gross" type="submit" disabled={laeuft || !schluessel.trim()}>
      Anmelden
    </button>
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
    padding: 0 28px 28px;
    display: flex;
    flex-direction: column;
    gap: 10px;
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
  }

  .fehler {
    color: var(--fehler);
    font-size: 13px;
  }

  button {
    margin-top: 8px;
  }
</style>
