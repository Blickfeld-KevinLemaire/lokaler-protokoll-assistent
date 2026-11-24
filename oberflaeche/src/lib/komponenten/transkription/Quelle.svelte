<script module lang="ts">
  export interface Auswahl {
    pfad: string;
    name: string;
    groesse?: number;
  }
</script>

<script lang="ts">
  /**
   * Aufnahme wählen: ablegen (überall im Fenster), Datei wählen, aufnehmen; zuletzt angekommene Aufnahmen.
   * Aufnehmen: In der Windows-Anwendung nimmt der Dienst auf (`/api/aufnahme`, zuverlässiger Gerätezugriff,
   * keine Rückfrage des Fensters); im Browser die Seite selbst (MediaRecorder) mit anschließendem Hochladen.
   */
  import FileAudio from '@lucide/svelte/icons/file-audio';
  import Mic from '@lucide/svelte/icons/mic';
  import Pause from '@lucide/svelte/icons/pause';
  import Play from '@lucide/svelte/icons/play';
  import Square from '@lucide/svelte/icons/square';
  import Upload from '@lucide/svelte/icons/upload';
  import { onMount } from 'svelte';
  import { api } from '#lib/api/client.ts';
  import type { AufnahmeGeraet, EingangsDatei } from '#lib/api/typen.ts';
  import { datumText, dateiname, groesseText, zeitmarke } from '#lib/logik/format.ts';
  import { dialog, meldungen } from '#lib/stores/oberflaeche.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import { zustand } from '#lib/stores/zustand.svelte.ts';
  import { ablegenHoeren, AUDIO_ENDUNGEN, dateiWaehlen } from '#lib/tauri.ts';
  import Fortschritt from '../Fortschritt.svelte';

  let { auswahl = $bindable(null) }: { auswahl: Auswahl | null } = $props();

  let eingang = $state<EingangsDatei[]>([]);
  let schwebt = $state(false);
  let hochladen = $state<{ name: string; anteil: number } | null>(null);
  let browserAufnahme = $state<{ beginn: number; rekorder: MediaRecorder } | null>(null);
  let browserSekunden = $state(0);
  let dateiFeld: HTMLInputElement | undefined = $state();
  let mikrofone = $state<AufnahmeGeraet[]>([]);
  let mikrofon = $state('');
  let aufnahmeBeschaeftigt = $state(false);
  let ziehZaehler = 0;

  const mitPfaden = $derived(!!verbindung.info?.faehigkeiten.dateipfade && verbindung.tauri);
  /** Nimmt der Dienst auf (Windows-Anwendung)? */
  const imDienst = $derived(!!verbindung.info?.faehigkeiten.mikrofon && verbindung.info?.rolle === 'desktop');
  const imBrowserMoeglich = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  const aufnehmenMoeglich = $derived(imDienst || imBrowserMoeglich);
  const dienstAufnahme = $derived(imDienst && zustand.aufnahme?.laeuft ? zustand.aufnahme : null);

  $effect(() => {
    void zustand.dateienStand;
    if (!verbindung.bereit) return;
    api
      .eingang()
      .then((liste) => (eingang = liste.slice(0, 5)))
      .catch((e) => console.warn('Eingang nicht geladen', e));
  });

  // Mikrofone nur zeigen, wenn es mehr als eines gibt; das gemerkte ist vorausgewählt.
  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit || !imDienst) return;
    api
      .aufnahmeGeraete()
      .then((liste) => {
        mikrofone = liste;
        mikrofon = (liste.find((g) => g.gewaehlt) ?? liste.find((g) => g.standard) ?? liste[0])?.name ?? '';
      })
      .catch(() => (mikrofone = []));
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

  // Browser: Ziehen über das ganze Fenster (Tauri meldet Pfade über ablegenHoeren).
  function mitDateien(e: DragEvent): boolean {
    return !verbindung.tauri && !!e.dataTransfer?.types.includes('Files');
  }

  function ziehenRein(e: DragEvent) {
    if (!mitDateien(e)) return;
    e.preventDefault();
    ziehZaehler++;
    schwebt = true;
  }

  function ziehenUeber(e: DragEvent) {
    if (!mitDateien(e)) return;
    e.preventDefault();
    schwebt = true;
  }

  function ziehenRaus(e: DragEvent) {
    if (!mitDateien(e)) return;
    ziehZaehler = Math.max(0, ziehZaehler - 1);
    if (ziehZaehler === 0) schwebt = false;
  }

  function ablegen(e: DragEvent) {
    if (!mitDateien(e)) return;
    e.preventDefault();
    ziehZaehler = 0;
    schwebt = false;
    const datei = e.dataTransfer?.files?.[0];
    if (datei) void hochladenStarten(datei);
  }

  // ---------------------------------------------------------------- Aufnahme im Dienst
  async function dienstStarten() {
    aufnahmeBeschaeftigt = true;
    try {
      zustand.aufnahme = await api.aufnahmeStarten(mikrofon || null);
    } catch (e) {
      dialog.zeigen(e, 'Aufnahme nicht möglich');
    } finally {
      aufnahmeBeschaeftigt = false;
    }
  }

  async function dienstPause() {
    try {
      zustand.aufnahme = zustand.aufnahme?.pausiert
        ? await api.aufnahmeFortsetzen()
        : await api.aufnahmePause();
    } catch (e) {
      dialog.zeigen(e, 'Das hat nicht geklappt');
    }
  }

  async function dienstStoppen() {
    aufnahmeBeschaeftigt = true;
    try {
      const datei = await api.aufnahmeStoppen();
      zustand.aufnahme = null;
      auswahl = { pfad: datei.pfad, name: datei.name };
      meldungen.zeigen('Aufnahme gespeichert');
    } catch (e) {
      dialog.zeigen(e, 'Aufnahme nicht beendet');
    } finally {
      aufnahmeBeschaeftigt = false;
    }
  }

  // ---------------------------------------------------------------- Aufnahme im Browser
  async function browserUmschalten() {
    if (browserAufnahme) {
      browserAufnahme.rekorder.stop();
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
        browserAufnahme = null;
        const jetzt = new Date();
        const zwei = (n: number) => String(n).padStart(2, '0');
        const name = `Aufnahme ${jetzt.getFullYear()}-${zwei(jetzt.getMonth() + 1)}-${zwei(jetzt.getDate())} ${zwei(jetzt.getHours())}-${zwei(jetzt.getMinutes())}.webm`;
        void hochladenStarten(new File(teile, name, { type: 'audio/webm' }));
      };
      rekorder.start(1000);
      browserAufnahme = { beginn: Date.now(), rekorder };
      browserSekunden = 0;
      const zaehler = setInterval(() => {
        if (browserAufnahme) browserSekunden = Math.floor((Date.now() - browserAufnahme.beginn) / 1000);
      }, 500);
    } catch (e) {
      dialog.zeigen(
        e instanceof DOMException ? new Error('Kein Zugriff auf das Mikrofon.') : e,
        'Aufnahme nicht möglich'
      );
    }
  }

  function aufnehmen() {
    if (imDienst) void dienstStarten();
    else void browserUmschalten();
  }
</script>

<svelte:window ondragenter={ziehenRein} ondragover={ziehenUeber} ondragleave={ziehenRaus} ondrop={ablegen} />

{#if schwebt}
  <div class="ablage" aria-hidden="true">
    <div class="ablage-rahmen">
      <Upload size={44} strokeWidth={1.5} />
      <span>Aufnahme hier ablegen</span>
    </div>
  </div>
{/if}

<section class="zone karte" aria-label="Aufnahme wählen">
  {#if hochladen}
    <div class="mitte">
      <div class="name">{hochladen.name}</div>
      <div class="balken"><Fortschritt anteil={hochladen.anteil} beschriftung="Hochladen" /></div>
      <div class="leise klein">{Math.round(hochladen.anteil * 100)} %</div>
    </div>
  {:else if dienstAufnahme}
    <div class="mitte">
      <div class="aufnahme" class:pausiert={dienstAufnahme.pausiert}>
        <span class="rot" aria-hidden="true"></span>
        <span class="zeit">{zeitmarke(dienstAufnahme.dauer)}</span>
      </div>
      <div
        class="pegel"
        role="meter"
        aria-label="Lautstärke"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round((dienstAufnahme.pausiert ? 0 : dienstAufnahme.pegel) * 100)}
      >
        <div
          class="pegel-wert"
          style:width="{Math.round((dienstAufnahme.pausiert ? 0 : dienstAufnahme.pegel) * 100)}%"
        ></div>
      </div>
      <div class="zeile knoepfe">
        <button class="knopf" type="button" onclick={dienstPause}>
          {#if dienstAufnahme.pausiert}<Play size={16} /> Fortsetzen{:else}<Pause size={16} /> Pause{/if}
        </button>
        <button class="knopf primaer" type="button" disabled={aufnahmeBeschaeftigt} onclick={dienstStoppen}>
          <Square size={14} /> Beenden
        </button>
      </div>
    </div>
  {:else if browserAufnahme}
    <div class="mitte">
      <div class="aufnahme">
        <span class="rot" aria-hidden="true"></span><span class="zeit">{zeitmarke(browserSekunden)}</span>
      </div>
      <button class="knopf primaer" type="button" onclick={browserUmschalten}>
        <Square size={14} /> Beenden
      </button>
    </div>
  {:else if auswahl}
    <div class="gewaehlt">
      <span class="dateisymbol"><FileAudio size={28} strokeWidth={1.5} /></span>
      <div class="dateitext">
        <div class="name" title={auswahl.pfad}>{auswahl.name}</div>
        {#if auswahl.groesse}<div class="leise klein">{groesseText(auswahl.groesse)}</div>{/if}
      </div>
      <button class="knopf leise" type="button" onclick={() => (auswahl = null)}>Andere wählen</button>
    </div>
  {:else}
    <div class="mitte">
      <span class="gross-symbol"><Upload size={36} strokeWidth={1.5} /></span>
      <div class="ablegen">Aufnahme hierher ziehen</div>
      <div class="zeile knoepfe">
        <button class="knopf primaer" type="button" onclick={waehlen}>Datei wählen</button>
        {#if aufnehmenMoeglich}
          <button class="knopf" type="button" disabled={aufnahmeBeschaeftigt} onclick={aufnehmen}>
            <Mic size={16} /> Aufnehmen
          </button>
        {/if}
      </div>
      {#if imDienst && mikrofone.length > 1}
        <label class="mikrofon">
          <span class="unsichtbar">Mikrofon</span>
          <select class="feld" bind:value={mikrofon} title="Mikrofon">
            {#each mikrofone as g (g.name)}<option value={g.name}>{g.name}</option>{/each}
          </select>
        </label>
      {/if}
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
    min-height: 240px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1.5px dashed var(--feld-rand);
    box-shadow: none;
    background: var(--karte);
  }

  .ablage {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: rgba(15, 42, 74, 0.55);
    pointer-events: none;
  }

  .ablage-rahmen {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    border: 2px dashed rgba(255, 255, 255, 0.85);
    border-radius: 16px;
    color: #fff;
    font-size: 20px;
    font-weight: 600;
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
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: var(--akzent-weich);
    color: var(--link);
  }

  .ablegen {
    font-size: 15px;
    color: var(--text-2);
  }

  .knoepfe {
    margin-top: 4px;
  }

  .mikrofon .feld {
    width: 260px;
    height: 30px;
    font-size: 13px;
    color: var(--text-2);
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
    display: inline-flex;
    color: var(--link);
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
    gap: 12px;
    font-size: 28px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .aufnahme.pausiert {
    color: var(--text-2);
  }

  .rot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--fehler);
  }

  .pausiert .rot {
    background: var(--text-3);
  }

  .pegel {
    width: min(280px, 70%);
    height: 6px;
    border-radius: 3px;
    background: var(--rand);
    overflow: hidden;
  }

  .pegel-wert {
    height: 100%;
    border-radius: 3px;
    background: var(--ok);
    transition: width 0.2s ease-out;
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
    min-height: 40px;
    padding: 8px 12px;
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
