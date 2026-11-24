<script lang="ts">
  /** Ein Einrichtungsauftrag, ruhig dargestellt: was, wie weit, wann fertig. */
  import Check from '@lucide/svelte/icons/check';
  import CircleAlert from '@lucide/svelte/icons/circle-alert';
  import type { Auftrag } from '$lib/api/typen';
  import { textMitAdressen } from '$lib/logik/format';
  import { zeitenFuerAuftrag } from '$lib/logik/restzeit';
  import { stufenText } from '$lib/logik/stufen';
  import { auftragTitel } from '$lib/logik/warteschlange';
  import { uhr } from '$lib/stores/oberflaeche.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Fortschritt from '../Fortschritt.svelte';

  let { auftrag, wiederholen }: { auftrag: Auftrag; wiederholen?: () => void } = $props();

  const jetzt = $derived(zustand.jetztDienst(uhr.jetzt));
  const zeiten = $derived(
    auftrag.status === 'laeuft'
      ? zeitenFuerAuftrag(auftrag.id, auftrag.fortschritt, auftrag.gestartet, jetzt, uhr.jetzt)
      : null
  );
  const prozent = $derived(auftrag.fortschritt != null ? Math.round(auftrag.fortschritt * 100) : null);
</script>

<li class="auftrag" class:fertig={auftrag.status === 'fertig'} class:fehler={auftrag.status === 'fehler'}>
  <div class="kopf">
    <span class="titel">{auftragTitel(auftrag)}</span>
    <span class="zustand">
      {#if auftrag.status === 'fertig'}
        <Check size={16} /> Fertig
      {:else if auftrag.status === 'fehler'}
        <CircleAlert size={16} /> Hat nicht geklappt
      {:else if auftrag.status === 'abgebrochen'}
        Abgebrochen
      {:else if auftrag.status === 'wartet'}
        Wartet
      {:else}
        {stufenText(auftrag.stufe, auftrag.status)}{prozent !== null ? ` · ${prozent} %` : ''}
      {/if}
    </span>
  </div>
  {#if auftrag.status === 'laeuft' || auftrag.status === 'wartet'}
    <Fortschritt
      anteil={auftrag.status === 'laeuft' ? auftrag.fortschritt : 0}
      beschriftung={auftragTitel(auftrag)}
    />
    {#if zeiten?.text}
      <div class="fuss">
        <span>{zeiten.text}</span>
        <span>{zeiten.fertig}</span>
      </div>
    {/if}
  {/if}
  {#if auftrag.status === 'fehler' && auftrag.fehler}
    <!-- Der Grund sagt, was zu tun ist (z. B. die Nutzungsbedingungen akzeptieren) – ohne ihn half auch
         „Erneut versuchen“ nicht weiter. -->
    <p class="grund">
      {#each textMitAdressen(auftrag.fehler) as teil, i (i)}{#if teil.adresse}<a
            href={teil.adresse}
            target="_blank"
            rel="noopener noreferrer"
          >
            {teil.text}
          </a>{:else}{teil.text}{/if}{/each}
    </p>
  {/if}
  {#if auftrag.status === 'fehler' && wiederholen}
    <div><button class="knopf" type="button" onclick={wiederholen}>Erneut versuchen</button></div>
  {/if}
</li>

<style>
  .auftrag {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    border-top: 1px solid var(--rand);
  }

  .auftrag:first-child {
    border-top: none;
  }

  .kopf {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .titel {
    font-weight: 600;
  }

  .zustand {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--text-2);
    font-size: 13px;
  }

  .fertig .zustand {
    color: var(--ok);
  }

  .fehler .zustand {
    color: var(--fehler);
  }

  .grund {
    margin: 0;
    font-size: 13px;
    color: var(--text-2);
    overflow-wrap: anywhere;
  }

  .fuss {
    display: flex;
    justify-content: space-between;
    font-size: 12.5px;
    color: var(--text-2);
  }
</style>
