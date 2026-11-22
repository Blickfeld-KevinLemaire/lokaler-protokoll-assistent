<script module lang="ts">
  export interface Auswahl {
    pfad: string;
    name: string;
    groesse?: number;
  }
</script>

<script lang="ts">
  /** Aufnahme wählen: ablegen, Datei wählen, aufnehmen; zuletzt angekommene Aufnahmen. */
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import type { EingangsDatei } from '$lib/api/typen';
  import { datumText, dateiname, groesseText } from '$lib/logik/format';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import { ablegenHoeren, AUDIO_ENDUNGEN, dateiWaehlen } from '$lib/tauri';
  import Fortschritt from '../Fortschritt.svelte';

  let { auswahl = $bindable(null) }: { auswahl: Auswahl | null } = $props();

  let eingang = $state<EingangsDatei[]>([]);
  let schwebt = $state(false);
  let hochladen = $state<{ name: string; anteil: number } | null>(null);
  let aufnahme = $state<{ beginn: number; rekorder: MediaRecorder } | null>(null);
  let aufnahmeSekunden = $state(0);
  let dateiFeld: HTMLInputElement | undefined = $state();

  const mitPfaden = $derived(!!verbindung.info?.faehigkeiten.dateipfade && verbindung.tauri);
  const mikrofonMoeglich = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;

  $effect(() => {
    void zustand.dateienStand;
    if (!verbindung.bereit) return;
    api
      .eingang()
      .then((liste) => (eingang = liste.slice(0, 5)))
      .catch((e) => console.warn('Eingang nicht geladen', e));
  });

  onMount(() => {
    if (!verbindung.tauri) return;
    let aufheben: (() => void) | null = null;
    let beendet = false;
    void ablegenHoeren(
      (pfade) => {
        const pfad = pfade.find((p) => AUDIO_ENDUNGEN.includes(p.split('.').pop()?.toLowerCase() ?? ''));
        if (pfad) auswahl = { pfad, name: dateiname(pfad) };
        else if (pfade.length)
          dialog.zeigen(new Error('Diese Datei ist keine Aufnahme.'), 'Nicht unterstützt');
      },
      (aktiv) => (schwebt = aktiv)
    ).then((f) => {
      if (beendet) f();
      else aufheben = f;
    });
    return () => {
      beendet = true;
      aufheben?.();
    };
  });

  async function waehlen() {
    if (mitPfaden) {
      try {
        const pfad = await dateiWaehlen();
        if (pfad) auswahl = { pfad, name: dateiname(pfad) };
      } catch (e) {
        dialog.zeigen(e);
      }
    } else {
      dateiFeld?.click();
    }
  }

  async function hochladenStarten(datei: File) {
    hochladen = { name: datei.name, anteil: 0 };
    try {
      const ergebnis = await api.hochladen(datei, (anteil) => {
        if (hochladen) hochladen.anteil = anteil;
      });
      auswahl = { pfad: ergebnis.pfad, name: ergebnis.name, groesse: ergebnis.groesse };
    } catch (e) {
      dialog.zeigen(e, 'Hochladen hat nicht geklappt');
    } finally {
      hochladen = null;
    }
  }

  function dateiGewaehlt(e: Event) {
    const datei = (e.currentTarget as HTMLInputElement).files?.[0];
    if (datei) void hochladenStarten(datei);
    (e.currentTarget as HTMLInputElement).value = '';
  }

  function ablegen(e: DragEvent) {
    if (verbindung.tauri) return; // Tauri meldet Pfade über ablegenHoeren
    e.preventDefault();
    schwebt = false;
    const datei = e.dataTransfer?.files?.[0];
    if (datei) void hochladenStarten(datei);
  }

  async function aufnehmen() {
    if (aufnahme) {
      aufnahme.rekorder.stop();
      return;
    }
    try {
      const strom = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rekorder = new MediaRecorder(strom, { mimeType: 'audio/webm' });
      const teile: Blob[] = [];
      rekorder.ondataavailable = (ev) => ev.data.size && teile.push(ev.data);
      rekorder.onstop = () => {
        strom.getTracks().forEach((t) => t.stop());
        clearInterval(zaehler);
        aufnahme = null;
        const jetzt = new Date();
        const zwei = (n: number) => String(n).padStart(2, '0');
        const name = `Aufnahme ${jetzt.getFullYear()}-${zwei(jetzt.getMonth() + 1)}-${zwei(jetzt.getDate())} ${zwei(jetzt.getHours())}-${zwei(jetzt.getMinutes())}.webm`;
        void hochladenStarten(new File(teile, name, { type: 'audio/webm' }));
      };
      rekorder.start(1000);
      aufnahme = { beginn: Date.now(), rekorder };
      aufnahmeSekunden = 0;
      const zaehler = setInterval(() => {
        if (aufnahme) aufnahmeSekunden = Math.floor((Date.now() - aufnahme.beginn) / 1000);
      }, 500);
    } catch (e) {
      dialog.zeigen(
        e instanceof DOMException ? new Error('Kein Zugriff auf das Mikrofon.') : e,
        'Aufnahme nicht möglich'
      );
    }
  }

  const aufnahmeZeit = $derived(
    `${Math.floor(aufnahmeSekunden / 60)}:${String(aufnahmeSekunden % 60).padStart(2, '0')}`
  );
</script>

<section
  class="zone karte"
  class:schwebt
  aria-label="Aufnahme wählen"
  ondragover={(e) => {
    if (!verbindung.tauri) {
      e.preventDefault();
      schwebt = true;
    }
  }}
  ondragleave={() => !verbindung.tauri && (schwebt = false)}
  ondrop={ablegen}
>
  {#if hochladen}
    <div class="mitte">
      <div class="name">{hochladen.name}</div>
      <div class="balken"><Fortschritt anteil={hochladen.anteil} beschriftung="Hochladen" /></div>
      <div class="leise klein">{Math.round(hochladen.anteil * 100)} %</div>
    </div>
  {:else if aufnahme}
    <div class="mitte">
      <div class="aufnahme"><span class="rot" aria-hidden="true"></span>{aufnahmeZeit}</div>
      <button class="knopf gross" type="button" onclick={aufnehmen}>■&nbsp; Aufnahme beenden</button>
    </div>
  {:else if auswahl}
    <div class="gewaehlt">
      <span class="dateisymbol" aria-hidden="true">🎧</span>
      <div class="dateitext">
        <div class="name" title={auswahl.pfad}>{auswahl.name}</div>
        {#if auswahl.groesse}<div class="leise klein">{groesseText(auswahl.groesse)}</div>{/if}
      </div>
      <button class="knopf leise" type="button" onclick={() => (auswahl = null)}>Andere wählen</button>
    </div>
  {:else}
    <div class="mitte">
      <div class="gross-symbol" aria-hidden="true">⤓</div>
      <div class="ablegen">Aufnahme hierher ziehen</div>
      <div class="zeile knoepfe">
        <button class="knopf primaer" type="button" onclick={waehlen}>Datei wählen</button>
        {#if mikrofonMoeglich}
          <button class="knopf" type="button" onclick={aufnehmen}>🎙&nbsp; Aufnehmen</button>
        {/if}
      </div>
    </div>
  {/if}
  <input
    bind:this={dateiFeld}
    class="unsichtbar"
    type="file"
    tabindex="-1"
    aria-hidden="true"
    accept={AUDIO_ENDUNGEN.map((e) => `.${e}`).join(',')}
    onchange={dateiGewaehlt}
  />
</section>

{#if eingang.length}
  <section class="zuletzt" aria-labelledby="zuletzt-titel">
    <h2 id="zuletzt-titel">Zuletzt angekommen</h2>
    <ul class="karte">
      {#each eingang as d (d.pfad)}
        <li>
          <button
            type="button"
            class:gewaehlt={auswahl?.pfad === d.pfad}
            onclick={() => (auswahl = { pfad: d.pfad, name: d.name, groesse: d.groesse })}
          >
            <span class="name">{d.name}</span>
            <span class="leise klein">{datumText(new Date(d.geaendert * 1000).toISOString())}</span>
            <span class="leise klein groesse">{groesseText(d.groesse)}</span>
          </button>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  .zone {
    min-height: 230px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1.5px dashed var(--feld-rand);
    box-shadow: none;
    background: var(--karte);
    transition:
      border-color 0.15s,
      background 0.15s;
  }

  .zone.schwebt {
    border-color: var(--akzent);
    background: var(--akzent-weich);
  }

  .mitte {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 28px;
    width: 100%;
  }

  .gross-symbol {
    font-size: 30px;
    line-height: 1;
    color: var(--text-3);
  }

  .ablegen {
    font-size: 15px;
    color: var(--text-2);
  }

  .knoepfe {
    margin-top: 6px;
  }

  .balken {
    width: min(360px, 80%);
  }

  .gewaehlt {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
    padding: 24px 28px;
  }

  .dateisymbol {
    font-size: 26px;
  }

  .dateitext {
    flex: 1;
    min-width: 0;
  }

  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .aufnahme {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 26px;
    font-variant-numeric: tabular-nums;
  }

  .rot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--fehler);
    animation: blinken 1s ease-in-out infinite;
  }

  @keyframes blinken {
    50% {
      opacity: 0.3;
    }
  }

  .zuletzt {
    margin-top: 24px;
  }

  .zuletzt h2 {
    font-size: 13px;
    color: var(--text-2);
    font-weight: 600;
    margin-bottom: 8px;
  }

  .zuletzt ul {
    list-style: none;
    margin: 0;
    padding: 4px;
  }

  .zuletzt li button {
    display: grid;
    grid-template-columns: 1fr auto 70px;
    gap: 16px;
    align-items: center;
    width: 100%;
    padding: 9px 12px;
    border: none;
    border-radius: 7px;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }

  .zuletzt li button:hover {
    background: var(--karte-2);
  }

  .zuletzt li button.gewaehlt {
    background: var(--akzent-weich);
  }

  .zuletzt .name {
    font-weight: 500;
  }

  .groesse {
    text-align: right;
  }
</style>
