<script lang="ts">
  /** Immer sichtbar in der Seitenleiste: was läuft, was wartet, Empfang, Hinweise, Verbindung. */
  import { api } from '$lib/api/client';
  import type { Auftrag } from '$lib/api/typen';
  import { restzeitFuerAuftrag } from '$lib/logik/restzeit';
  import { stufenText } from '$lib/logik/stufen';
  import { auftragTitel, herkunftAnzeigen } from '$lib/logik/warteschlange';
  import { dialog, uhr } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Fortschritt from './Fortschritt.svelte';

  const ERLEDIGT_ZEIGEN_S = 180;

  let reiheOffen = $state(false);
  let ausgeblendet = $state<string | null>(null);

  const lage = $derived(zustand.lage);
  const laufend = $derived(lage.laufend);
  const jetzt = $derived(zustand.jetztDienst(uhr.jetzt));
  const prozent = $derived(laufend?.fortschritt != null ? Math.round(laufend.fortschritt * 100) : null);
  const restzeit = $derived(
    laufend ? restzeitFuerAuftrag(laufend.id, laufend.fortschritt, laufend.gestartet, jetzt) : ''
  );
  const erledigt = $derived.by(() => {
    const a = lage.zuletztErledigt;
    if (!a || a.id === ausgeblendet || a.status === 'abgebrochen') return null;
    if (jetzt - (a.beendet ?? 0) > ERLEDIGT_ZEIGEN_S) return null;
    return a;
  });
  const empfang = $derived(verbindung.info?.faehigkeiten.geraete_empfang ? zustand.empfang : null);
  const portBelegt = $derived(/belegt|benutzt|in use|10048/i.test(empfang?.fehler ?? ''));
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

<section class="status" aria-label="Status" aria-live="polite">
  {#if getrennt}
    <div class="zeile-klein warn">
      <span class="dreh" aria-hidden="true">⟳</span> Verbindung wird wiederhergestellt …
    </div>
  {/if}

  {#if laufend}
    {@const herkunft = herkunftAnzeigen(laufend.herkunft)}
    <div class="laufend">
      <div class="kopf">
        <span class="symbol" title={herkunft.text} aria-label={herkunft.text}>{herkunft.symbol}</span>
        <span class="titel" title={auftragTitel(laufend)}>{auftragTitel(laufend)}</span>
        <button
          class="x"
          type="button"
          aria-label="Verarbeitung abbrechen"
          title="Abbrechen"
          onclick={() => abbrechen(laufend)}
        >
          ✕
        </button>
      </div>
      <div class="stufe">{stufenText(laufend.stufe, laufend.status)}</div>
      <Fortschritt anteil={laufend.fortschritt} dunkel beschriftung="Fortschritt der Verarbeitung" />
      <div class="fuss">
        <span>{prozent !== null ? `${prozent} %` : ''}</span>
        <span>{restzeit}</span>
      </div>
    </div>
  {:else if !getrennt && verbindung.bereit}
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
        <span class="pfeil" class:offen={reiheOffen} aria-hidden="true">▸</span>
        {lage.wartend.length}
        {lage.wartend.length === 1 ? 'wartet' : 'warten'}
      </button>
      {#if reiheOffen}
        <ol class="liste">
          {#each lage.wartend as a (a.id)}
            {@const h = herkunftAnzeigen(a.herkunft)}
            <li>
              <span class="symbol" title={h.text}>{h.symbol}</span>
              <span class="titel" title={auftragTitel(a)}>{auftragTitel(a)}</span>
              <button
                class="x"
                type="button"
                aria-label="Aus der Warteschlange nehmen"
                onclick={() => abbrechen(a)}
              >
                ✕
              </button>
            </li>
          {/each}
        </ol>
      {/if}
    </div>
  {/if}

  {#if erledigt}
    {@const link = ergebnisLink(erledigt)}
    <div class="erledigt" class:fehler={erledigt.status === 'fehler'}>
      <span aria-hidden="true">{erledigt.status === 'fertig' ? '✓' : '!'}</span>
      <span class="titel" title={auftragTitel(erledigt)}>
        {erledigt.status === 'fertig' ? 'Fertig' : 'Fehlgeschlagen'}: {auftragTitel(erledigt)}
      </span>
      {#if link}<a href={link}>Öffnen</a>{/if}
      <button class="x" type="button" aria-label="Ausblenden" onclick={() => (ausgeblendet = erledigt.id)}>
        ✕
      </button>
    </div>
  {/if}

  {#if zustand.freigaben.length}
    <div class="zeile-klein">
      <span aria-hidden="true">⏳</span>
      <a href="/raum" class="hell">
        {zustand.freigaben.length} Freigabe{zustand.freigaben.length === 1 ? '' : 'n'} am Gerät
      </a>
    </div>
  {/if}

  {#each zustand.hinweise as h (h.nr)}
    <div
      class="zeile-klein"
      class:warn={h.stufe !== 'info'}
      class:fehler={h.stufe === 'fehler'}
      title={h.lang}
    >
      <span aria-hidden="true">{h.stufe === 'info' ? 'ℹ' : '⚠'}</span>
      {#if h.abschnitt}
        <a class="hell" href="/einstellungen#{h.abschnitt}">{h.text}</a>
      {:else}
        <span class="titel">{h.text}</span>
      {/if}
      <button
        class="x"
        type="button"
        aria-label="Hinweis ausblenden"
        onclick={() => zustand.hinweisEntfernen(h.schluessel)}
      >
        ✕
      </button>
    </div>
  {/each}

  {#if empfang}
    <div class="zeile-klein empfang" class:aus={!empfang.aktiv}>
      <span aria-hidden="true">📡</span>
      {#if empfang.aktiv}
        Empfang an · {empfang.geraete ?? 0} Gerät{empfang.geraete === 1 ? '' : 'e'}
      {:else}
        Empfang aus
      {/if}
    </div>
    {#if empfang.fehler}
      <div class="zeile-klein warn" title={empfang.fehler}>
        <span aria-hidden="true">⚠</span>
        {portBelegt ? 'Port belegt' : 'Empfang gestört'}
      </div>
    {/if}
  {/if}
</section>

<style>
  .status {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 0 14px 10px;
    font-size: 12.5px;
    color: var(--sb-text);
  }

  .laufend,
  .reihe,
  .erledigt {
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
    gap: 6px;
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

  .stufe {
    color: var(--sb-muted);
  }

  .fuss {
    display: flex;
    justify-content: space-between;
    color: var(--sb-muted);
    font-variant-numeric: tabular-nums;
    min-height: 17px;
  }

  .symbol {
    flex: none;
    width: 18px;
    text-align: center;
  }

  .x {
    flex: none;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 5px;
    background: transparent;
    color: var(--sb-muted);
    cursor: pointer;
    font-size: 11px;
  }

  .x:hover {
    background: var(--sb-hover);
    color: #fff;
  }

  .zeile-klein {
    display: flex;
    align-items: center;
    gap: 7px;
    min-height: 22px;
    color: var(--sb-text);
  }

  .zeile-klein.warn {
    color: var(--sb-warn);
  }

  .zeile-klein.fehler {
    color: var(--sb-fehler);
  }

  .bereit {
    color: var(--sb-muted);
  }

  .punkt {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--sb-ok);
    margin: 0 5px 0 5px;
  }

  .reihe-knopf {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 7px 10px;
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
    display: inline-block;
    transition: transform 0.15s;
    color: var(--sb-muted);
  }

  .pfeil.offen {
    transform: rotate(90deg);
  }

  .liste {
    list-style: none;
    margin: 0;
    padding: 0 6px 6px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .liste li {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 24px;
  }

  .erledigt {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 6px 6px 10px;
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
    color: #9cc0ff;
  }

  .empfang.aus {
    color: var(--sb-muted);
  }

  .dreh {
    display: inline-block;
    animation: dreh 1.2s linear infinite;
  }

  @keyframes dreh {
    to {
      transform: rotate(360deg);
    }
  }
</style>
