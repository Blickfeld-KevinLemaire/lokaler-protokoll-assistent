<script lang="ts">
  /**
   * Ein eingerichtetes Gerät meldet sich nicht: fast immer verwirft die Windows-Firewall seine Anfragen.
   * Ein Klick legt die Freigabe an (Windows fragt nach Administratorrechten). Nur in der Windows-Anwendung.
   */
  import ShieldCheck from '@lucide/svelte/icons/shield-check';
  import { api, ApiFehler } from '#lib/api/client.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import Info from '../Info.svelte';

  let { kurz = false }: { kurz?: boolean } = $props();

  let laeuft = $state(false);
  let fertig = $state(false);
  let fehler = $state('');

  const moeglich = $derived(!!verbindung.info?.faehigkeiten.firewall_freigabe && verbindung.verwalten);

  async function freigeben() {
    laeuft = true;
    fehler = '';
    try {
      await api.firewallFreigeben();
      fertig = true;
    } catch (e) {
      fehler = e instanceof ApiFehler || e instanceof Error ? e.message : 'Das hat nicht geklappt.';
    } finally {
      laeuft = false;
    }
  }
</script>

{#if moeglich}
  <div class="freigabe" class:kurz role="status">
    {#if fertig}
      <span class="ok">Freigegeben. Das Gerät meldet sich gleich.</span>
    {:else}
      {#if !kurz}
        <span>Das Gerät erreicht diesen Computer nicht.</span>
      {/if}
      <button
        class="knopf {kurz ? 'leise klein' : 'primaer'}"
        type="button"
        disabled={laeuft}
        onclick={freigeben}
      >
        <ShieldCheck size={16} /> Empfang freigeben
      </button>
      <Info
        frage="Warum freigeben?"
        text="Meist blockiert die Windows-Firewall das Gerät. Die Freigabe gilt nur im Heim- und Firmennetz. Windows fragt einmal nach."
      />
      {#if fehler}<span class="fehler" role="alert">{fehler}</span>{/if}
    {/if}
  </div>
{/if}

<style>
  .freigabe {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
    padding: 12px 14px;
    border-radius: 8px;
    background: var(--warn-weich);
  }

  .freigabe.kurz {
    padding: 0;
    background: transparent;
  }

  .ok {
    color: var(--ok);
    font-weight: 500;
  }

  .fehler {
    color: var(--fehler);
    flex-basis: 100%;
  }
</style>
