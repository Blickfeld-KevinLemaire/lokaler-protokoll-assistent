<script lang="ts">
  /** Immer sichtbar in der Seitenleiste: Aufnahme, was läuft, was wartet, Hinweise, Empfang, Verbindung. */
  import Check from '@lucide/svelte/icons/check';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import CircleAlert from '@lucide/svelte/icons/circle-alert';
  import Hourglass from '@lucide/svelte/icons/hourglass';
  import Info from '@lucide/svelte/icons/info';
  import Pause from '@lucide/svelte/icons/pause';
  import Radio from '@lucide/svelte/icons/radio';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
  import X from '@lucide/svelte/icons/x';
  import { api } from '$lib/api/client';
  import type { Auftrag } from '$lib/api/typen';
  import { zeitmarke } from '$lib/logik/format';
  import { empfangsFehlerText } from '$lib/logik/hinweise';
  import { zeitenFuerAuftrag } from '$lib/logik/restzeit';
  import { stufenText } from '$lib/logik/stufen';
  import { auftragTitel, herkunftAnzeigen } from '$lib/logik/warteschlange';
  import { dialog, uhr } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Fortschritt from './Fortschritt.svelte';
  import HerkunftSymbol from './HerkunftSymbol.svelte';

  const ERLEDIGT_ZEIGEN_S = 180;

  let reiheOffen = $state(false);
  let ausgeblendet = $state<string | null>(null);

  const lage = $derived(zustand.lage);
  const laufend = $derived(lage.laufend);
  const jetzt = $derived(zustand.jetztDienst(uhr.jetzt));
  const prozent = $derived(laufend?.fortschritt != null ? Math.round(laufend.fortschritt * 100) : null);
  const zeiten = $derived(
    laufend && !laufend.fremd
      ? zeitenFuerAuftrag(laufend.id, laufend.fortschritt, laufend.gestartet, jetzt, uhr.jetzt)
      : null
  );
  const erledigt = $derived.by(() => {
    const a = lage.zuletztErledigt;
    if (!a || a.fremd || a.id === ausgeblendet || a.status === 'abgebrochen') return null;
    if (jetzt - (a.beendet ?? 0) > ERLEDIGT_ZEIGEN_S) return null;
    return a;
  });
  const empfang = $derived(verbindung.info?.faehigkeiten.geraete_empfang ? zustand.empfang : null);
  const aufnahme = $derived(zustand.aufnahme?.laeuft ? zustand.aufnahme : null);
  const getrennt = $derived(
    verbindung.phase === 'getrennt' || (verbindung.bereit && verbindung.strom === 'getrennt')
  );

  async function abbrechen(a: Auftrag) {
    try {
      await api.auftragAbbrechen(a.id);
    } catch (e) {
      dialog.zeigen(e, 'Abbrechen hat nicht geklappt');
    }
  }

  function ergebnisLink(a: Auftrag): string | null {
    if (a.status !== 'fertig') return null;
    if (a.art === 'modell_laden') return '/einstellungen#zusammenfassung';
    const transkript =
      (a.ergebnis?.transkript_json as string | undefined) ?? (a.angaben?.transkript as string | undefined);
    if (!transkript) return null;
    const reiter = a.art === 'auswertung' ? '&reiter=zusammenfassung' : '';
    return `/besprechungen?transkript=${encodeURIComponent(transkript)}${reiter}`;
  }
</script>

<section class="status" aria-label="Status">
  {#if aufnahme}
    <a class="aufnahme" href="/" title="Zur Aufnahme">
      {#if aufnahme.pausiert}
        <Pause size={14} />
        <span class="titel">Aufnahme pausiert</span>
      {:else}
        <span class="rot" aria-hidden="true"></span>
        <span class="titel">Aufnahme läuft</span>
      {/if}
      <span class="zeit">{zeitmarke(aufnahme.dauer)}</span>
    </a>
  {/if}

  {#if laufend}
    {@const herkunft = herkunftAnzeigen(laufend.herkunft)}
    <div class="laufend">
      <div class="kopf">
        <span class="symbol" title={herkunft.text}><HerkunftSymbol art={herkunft.art} /></span>
        <span class="titel" title={auftragTitel(laufend)}>{auftragTitel(laufend)}</span>
        {#if !laufend.fremd}
          <button
            class="x"
            type="button"
            aria-label="Verarbeitung abbrechen"
            title="Abbrechen"
            onclick={() => abbrechen(laufend)}
          >
            <X size={14} />
          </button>
        {/if}
      </div>
      <div class="stufe" aria-live="polite">
        <span>{laufend.fremd ? 'Wird verarbeitet' : stufenText(laufend.stufe, laufend.status)}</span>
        <span class="zahl">{prozent !== null ? `${prozent} %` : ''}</span>
      </div>
      <Fortschritt anteil={laufend.fortschritt} dunkel beschriftung="Fortschritt der Verarbeitung" />
      {#if zeiten?.kurz}
        <div class="fuss">
          <span>{zeiten.kurz}</span>
          <span>{zeiten.fertig}</span>
        </div>
      {/if}
    </div>
  {:else if !getrennt && verbindung.bereit && !aufnahme}
    <div class="zeile-klein bereit"><span class="punkt" aria-hidden="true"></span> Bereit</div>
  {/if}

  {#if lage.wartend.length}
    <div class="reihe">
      <button
        class="reihe-knopf"
        type="button"
        aria-expanded={reiheOffen}
        onclick={() => (reiheOffen = !reiheOffen)}
      >
        <span class="pfeil" class:offen={reiheOffen}><ChevronRight size={14} /></span>
        {lage.wartend.length}
        {lage.wartend.length === 1 ? 'wartet' : 'warten'}
      </button>
      {#if reiheOffen}
        <ol class="liste">
          {#each lage.wartend as a (a.id)}
            {@const h = herkunftAnzeigen(a.herkunft)}
            <li>
              <span class="symbol" title={h.text}><HerkunftSymbol art={h.art} /></span>
              <span class="titel" title={auftragTitel(a)}>{auftragTitel(a)}</span>
              {#if !a.fremd}
                <button
                  class="x"
                  type="button"
                  aria-label="{auftragTitel(a)} aus der Warteschlange nehmen"
                  title="Aus der Warteschlange nehmen"
                  onclick={() => abbrechen(a)}
                >
                  <X size={14} />
                </button>
              {/if}
            </li>
          {/each}
        </ol>
      {/if}
    </div>
  {/if}

  {#if erledigt}
    {@const link = ergebnisLink(erledigt)}
    <div class="erledigt" class:fehler={erledigt.status === 'fehler'}>
      {#if erledigt.status === 'fertig'}<Check size={16} />{:else}<CircleAlert size={16} />{/if}
      <span class="titel" title={auftragTitel(erledigt)}>
        {erledigt.status === 'fertig' ? 'Fertig' : 'Fehlgeschlagen'}: {auftragTitel(erledigt)}
      </span>
      {#if link}<a href={link}>Öffnen</a>{/if}
      <button class="x" type="button" aria-label="Ausblenden" onclick={() => (ausgeblendet = erledigt.id)}>
        <X size={14} />
      </button>
    </div>
  {/if}

  {#if getrennt || zustand.freigaben.length || zustand.hinweise.length || empfang}
    <ul class="kleines">
      {#if getrennt}
        <li class="warn">
          <span class="dreh"><RefreshCw size={16} /></span>
          <span class="titel">Verbindung wird wiederhergestellt …</span>
        </li>
      {/if}

      {#if zustand.freigaben.length}
        <li>
          <Hourglass size={16} />
          <a href="/raum" class="titel hell">
            {zustand.freigaben.length} Freigabe{zustand.freigaben.length === 1 ? '' : 'n'} am Gerät
          </a>
        </li>
      {/if}

      {#each zustand.hinweise as h (h.nr)}
        <li class:warn={h.stufe === 'warnung'} class:fehler={h.stufe === 'fehler'} title={h.lang}>
          {#if h.stufe === 'info'}<Info size={16} />{:else}<TriangleAlert size={16} />{/if}
          {#if h.abschnitt}
            <a class="titel hell" href="/einstellungen#{h.abschnitt}">{h.text}</a>
          {:else}
            <span class="titel">{h.text}</span>
          {/if}
          <button
            class="x"
            type="button"
            aria-label="Hinweis ausblenden"
            onclick={() => zustand.hinweisEntfernen(h.schluessel)}
          >
            <X size={14} />
          </button>
        </li>
      {/each}

      {#if empfang}
        {#if empfang.fehler}
          <li class="warn" title={empfang.fehler}>
            <TriangleAlert size={16} />
            <a class="titel hell" href="/raum">{empfangsFehlerText(empfang.fehler_code)}</a>
          </li>
        {:else}
          <li class:aus={!empfang.aktiv}>
            <Radio size={16} />
            <span class="titel">
              {#if empfang.aktiv}
                Empfang an · {empfang.geraete ?? 0} Gerät{empfang.geraete === 1 ? '' : 'e'}
              {:else}
                Empfang aus
              {/if}
            </span>
          </li>
        {/if}
      {/if}
    </ul>
  {/if}
</section>

<style>
  .status {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 0 14px 12px;
    font-size: 12.5px;
    color: var(--sb-text);
  }

  .laufend,
  .reihe,
  .erledigt,
  .aufnahme {
    border-radius: 8px;
    background: var(--sb-feld);
    border: 1px solid var(--sb-linie);
  }

  .laufend {
    padding: 10px 10px 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .kopf {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .titel {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .kopf .titel {
    font-weight: 600;
    color: #fff;
    font-size: 13px;
  }

  .stufe,
  .fuss {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    color: var(--sb-muted);
    font-variant-numeric: tabular-nums;
  }

  .stufe > span:first-child {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .zahl {
    flex: none;
  }

  .symbol {
    flex: none;
    display: inline-flex;
    color: var(--sb-muted);
  }

  .x {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    margin: -2px -4px -2px 0;
    padding: 0;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--sb-muted);
    cursor: pointer;
  }

  .x:hover {
    background: var(--sb-hover);
    color: #fff;
  }

  .aufnahme {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    color: var(--sb-text);
    text-decoration: none;
  }

  .aufnahme:hover {
    background: var(--sb-hover);
    text-decoration: none;
  }

  .aufnahme .zeit {
    font-variant-numeric: tabular-nums;
    color: #fff;
    font-weight: 600;
  }

  .rot {
    flex: none;
    width: 8px;
    height: 8px;
    margin: 0 3px;
    border-radius: 50%;
    background: var(--sb-fehler);
  }

  .kleines {
    list-style: none;
    margin: 0;
    padding: 2px 0 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .kleines li {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 26px;
    padding: 0 2px 0 4px;
    color: var(--sb-text);
  }

  .kleines li :global(.lucide-icon) {
    color: var(--sb-muted);
  }

  .kleines li.warn,
  .kleines li.warn :global(.lucide-icon) {
    color: var(--sb-warn);
  }

  .kleines li.fehler :global(.lucide-icon) {
    color: var(--sb-fehler);
  }

  .kleines li.aus {
    color: var(--sb-muted);
  }

  .zeile-klein {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 24px;
    padding-left: 4px;
  }

  .bereit {
    color: var(--sb-muted);
  }

  .punkt {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--sb-ok);
    margin: 0 4px;
  }

  .reihe-knopf {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 6px 10px;
    border: none;
    background: transparent;
    color: var(--sb-text);
    cursor: pointer;
    border-radius: 8px;
    text-align: left;
  }

  .reihe-knopf:hover {
    background: var(--sb-hover);
  }

  .pfeil {
    display: inline-flex;
    transition: transform 0.15s ease-out;
    color: var(--sb-muted);
  }

  .pfeil.offen {
    transform: rotate(90deg);
  }

  .liste {
    list-style: none;
    margin: 0;
    padding: 0 8px 6px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .liste li {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 26px;
  }

  .erledigt {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px 6px 10px;
    color: var(--sb-ok);
  }

  .erledigt.fehler {
    color: var(--sb-fehler);
  }

  .erledigt .titel {
    color: var(--sb-text);
  }

  .erledigt a,
  a.hell {
    color: var(--sb-link);
  }

  .dreh {
    display: inline-flex;
    animation: dreh 1.2s linear infinite;
  }

  @keyframes dreh {
    to {
      transform: rotate(360deg);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .dreh {
      animation: none;
    }
  }
</style>
