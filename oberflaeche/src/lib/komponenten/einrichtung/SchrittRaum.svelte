<script lang="ts">
  /** „VERMERK Raum“ (freiwillig): Aufnahmegerät per USB oder ohne USB hinzufügen. */
  import Plus from '@lucide/svelte/icons/plus';
  import Radio from '@lucide/svelte/icons/radio';
  import Usb from '@lucide/svelte/icons/usb';
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { GeraetEintrag } from '$lib/api/typen';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import GeraetHinzufuegen from '../raum/GeraetHinzufuegen.svelte';
  import UsbEinrichtung from '../raum/UsbEinrichtung.svelte';
  import Info from '../Info.svelte';

  let geraete = $state<GeraetEintrag[]>([]);
  let usbOffen = $state(false);
  let ohneUsbOffen = $state(false);

  const usbMoeglich = $derived(verbindung.tauri && !!verbindung.info?.faehigkeiten.dateipfade);

  async function laden() {
    try {
      geraete = (await api.geraete()).geraete;
    } catch (e) {
      console.warn('Geräte nicht geladen', e);
    }
  }

  /** Mit dem ersten Gerät den Empfang einschalten (sonst kommt nichts an). */
  async function hinzugefuegt() {
    await laden();
    if (geraete.length && !einstellungen.werte?.geraete_empfang_aktiv) {
      await einstellungen.aendern({ geraete_empfang_aktiv: true }).catch(() => undefined);
    }
  }

  onMount(() => {
    void laden();
  });
</script>

<div class="karte raum">
  <span class="kreis"><Radio size={26} strokeWidth={1.5} /></span>
  <div class="text">
    <span class="titel">
      Aufnahmegeräte
      <Info
        frage="Was ist VERMERK Raum?"
        text="Ein kleines Gerät nimmt Besprechungen auf und schickt sie an diesen Computer. Das geht auch später."
      />
    </span>
    <span class="leise">
      {geraete.length ? geraete.map((g) => g.name).join(', ') : 'Noch keines verbunden'}
    </span>
  </div>
  <div class="knoepfe">
    <button class="knopf" type="button" onclick={() => (ohneUsbOffen = true)}>
      <Plus size={16} /> Ohne USB hinzufügen
    </button>
    {#if usbMoeglich}
      <button class="knopf primaer" type="button" onclick={() => (usbOffen = true)}>
        <Usb size={16} /> Per USB verbinden
      </button>
    {/if}
  </div>
</div>

<UsbEinrichtung offen={usbOffen} schliessen={() => (usbOffen = false)} fertig={() => void hinzugefuegt()} />
<GeraetHinzufuegen
  offen={ohneUsbOffen}
  schliessen={() => (ohneUsbOffen = false)}
  fertig={() => void hinzugefuegt()}
/>

<style>
  .raum {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px;
  }

  .kreis {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    flex: none;
    border-radius: 50%;
    background: var(--akzent-weich);
    color: var(--link);
  }

  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .titel {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
  }

  .knoepfe {
    display: flex;
    gap: 8px;
  }
</style>
