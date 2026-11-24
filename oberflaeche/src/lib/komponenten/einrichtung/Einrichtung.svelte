<script lang="ts">
  /**
   * Ersteinrichtung als geführter Ablauf im Inhaltsbereich (die Seitenleiste mit Warteschlange bleibt
   * sichtbar). Je Schritt eine ruhige Seite; erklärt wird nur über Beschriftungen und (i).
   */
  import CircleCheck from '@lucide/svelte/icons/circle-check';
  import { tick } from 'svelte';
  import {
    BEREICHE,
    einrichtungLaeuft,
    einrichtungsAuftraege,
    neustartMoeglich,
    offeneAuftraege,
    offeneBausteine,
    SCHRITT_TITEL
  } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';
  import Fortschritt from '../Fortschritt.svelte';
  import Info from '../Info.svelte';
  import SchrittArbeitsweise from './SchrittArbeitsweise.svelte';
  import SchrittBedarf from './SchrittBedarf.svelte';
  import SchrittComputer from './SchrittComputer.svelte';
  import SchrittEinrichten from './SchrittEinrichten.svelte';
  import SchrittMitschrift from './SchrittMitschrift.svelte';
  import SchrittOnline from './SchrittOnline.svelte';
  import SchrittRaum from './SchrittRaum.svelte';

  let ueberschrift: HTMLHeadingElement | undefined = $state();

  const schritt = $derived(einrichtung.schritt);
  const folge = $derived(einrichtung.folge);
  const index = $derived(Math.max(0, folge.indexOf(schritt)));
  const stand = $derived(einrichtung.stand);
  const neustartNoetig = $derived(!!stand?.neustart_noetig);
  const laedtNoch = $derived(einrichtungLaeuft(zustand.auftraege));
  // Andere Aufträge (Transkription, auch von einem Aufnahmegerät): Der Neustart bräche sie ab.
  const andereOffen = $derived(
    offeneAuftraege(zustand.auftraege) - offeneAuftraege(einrichtungsAuftraege(zustand.auftraege))
  );

  // Nach jedem Schrittwechsel: Fokus auf die Überschrift (Bildschirmleser, Tastatur).
  $effect(() => {
    void schritt;
    void tick().then(() => ueberschrift?.focus({ preventScroll: true }));
  });

  // Auf „Fertig“: frisch fragen, ob ein Neustart nötig ist.
  $effect(() => {
    if (schritt === 'fertig') void einrichtung.standNeu();
  });

  const titel = $derived(
    schritt === 'willkommen'
      ? 'Willkommen bei VERMERK'
      : schritt === 'fertig' && neustartNoetig
        ? 'Fast geschafft'
        : SCHRITT_TITEL[schritt]
  );

  const LOS = 'Los geht’s';

  const primaer = $derived.by((): { text: string; tun: () => void; aus: boolean } => {
    const weiter = () => void einrichtung.weiter();
    switch (schritt) {
      case 'willkommen':
        return { text: LOS, tun: weiter, aus: false };
      case 'bedarf': {
        const ja = offeneBausteine(einrichtung.kosten).some((b) => einrichtung.zustimmung[b.kennung]);
        return { text: ja ? 'Einrichten' : 'Weiter', tun: weiter, aus: !einrichtung.kannWeiter };
      }
      case 'mitschrift':
        return {
          text: einrichtung.gestartet ? 'Weiter' : 'Laden',
          tun: weiter,
          aus: !einrichtung.kannWeiter || (einrichtung.gestartet && laedtNoch)
        };
      case 'fertig':
        if (neustartNoetig)
          return {
            text: 'Jetzt neu starten',
            tun: () => void einrichtung.neuStarten(),
            aus: !neustartMoeglich(stand, zustand.auftraege) || einrichtung.neustart === 'laeuft'
          };
        return { text: LOS, tun: () => void einrichtung.abschliessen(), aus: einrichtung.arbeitet };
      default:
        return { text: 'Weiter', tun: weiter, aus: !einrichtung.kannWeiter };
    }
  });

  const zurueckMoeglich = $derived(
    index > 0 && schritt !== 'mitschrift' && einrichtung.neustart !== 'laeuft'
  );

  function arbeitsweiseText(bereich: (typeof BEREICHE)[number]['id']): string {
    const w = stand?.arbeitsweise[bereich] ?? einrichtung.wahl[bereich];
    return w === 'api' ? 'Online-Dienst' : 'Auf diesem Computer';
  }
</script>

<svelte:head><title>Einrichtung · VERMERK</title></svelte:head>

<section class="einrichtung" aria-labelledby="einrichtung-titel">
  <header class="oben">
    <ol class="segmente" aria-label="Schritt {index + 1} von {folge.length}">
      {#each folge as s, i (s)}
        <li
          class:erledigt={i < index}
          class:aktiv={i === index}
          title={SCHRITT_TITEL[s]}
          aria-current={i === index ? 'step' : undefined}
        >
          <span class="unsichtbar">{SCHRITT_TITEL[s]}</span>
        </li>
      {/each}
    </ol>
    {#if einrichtung.neustart !== 'laeuft'}
      <button
        class="knopf leise"
        type="button"
        title="Beim nächsten Start geht es hier weiter"
        onclick={() => einrichtung.spaeter()}
      >
        Später
      </button>
    {/if}
  </header>

  <div class="buehne" class:mitte={schritt === 'willkommen' || schritt === 'fertig'}>
    {#if schritt === 'willkommen'}
      <img class="zeichen" src="/vermerk_icon.png" alt="" width="72" height="72" />
    {:else if schritt === 'fertig' && !neustartNoetig}
      <span class="haken"><CircleCheck size={44} strokeWidth={1.5} /></span>
    {/if}

    <div class="titelzeile">
      <h1 id="einrichtung-titel" bind:this={ueberschrift} tabindex="-1">{titel}</h1>
      {#if schritt === 'fertig' && neustartNoetig && einrichtung.neustart !== 'laeuft'}
        <Info
          frage="Warum neu starten?"
          text="Für die Transkription auf diesem Computer startet die App einmal neu. Danach geht es hier weiter."
        />
      {/if}
    </div>

    {#if schritt === 'willkommen'}
      <p class="satz">In wenigen Schritten ist alles bereit.</p>
    {:else if schritt === 'computer'}
      <SchrittComputer />
    {:else if schritt === 'arbeitsweise'}
      <SchrittArbeitsweise />
    {:else if schritt === 'bedarf'}
      <SchrittBedarf />
    {:else if schritt === 'einrichten'}
      <SchrittEinrichten />
    {:else if schritt === 'online'}
      <SchrittOnline />
    {:else if schritt === 'raum'}
      <SchrittRaum />
    {:else if schritt === 'mitschrift'}
      <SchrittMitschrift />
    {:else if schritt === 'fertig'}
      {#if einrichtung.neustart === 'laeuft'}
        <div class="neustart" role="status">
          <Fortschritt anteil={null} beschriftung="Die App startet neu" />
          <p>Die App startet kurz neu …</p>
          {#if stand?.rechenumgebung_fehlt}
            <p class="leise">
              Dabei wird die Rechenumgebung eingerichtet – das kann viele Minuten dauern. Den Fortschritt
              zeigt das Fenster „VERMERK Desktop – Einrichtung“.
            </p>
          {/if}
        </div>
      {:else}
        <dl class="zusammenfassung karte">
          {#each BEREICHE as b (b.id)}
            <div>
              <dt>{b.text}</dt>
              <dd>{arbeitsweiseText(b.id)}</dd>
            </div>
          {/each}
        </dl>
        {#if neustartNoetig && laedtNoch}
          <SchrittEinrichten />
        {/if}
        {#if neustartNoetig && andereOffen > 0}
          <p class="leise" role="status">
            {andereOffen === 1 ? 'Eine Verarbeitung läuft' : `${andereOffen} Verarbeitungen laufen`} noch oder warten.
            Neu starten geht, sobald sie fertig sind.
          </p>
        {/if}
      {/if}
    {/if}
  </div>

  <footer class="unten">
    {#if zurueckMoeglich}
      <button class="knopf leise" type="button" onclick={() => einrichtung.zurueck()}>Zurück</button>
    {/if}
    <span class="platz"></span>
    <button class="knopf primaer gross" type="button" disabled={primaer.aus} onclick={primaer.tun}>
      {primaer.text}
    </button>
  </footer>
</section>

<style>
  .einrichtung {
    min-height: calc(100vh - 72px);
    display: flex;
    flex-direction: column;
    max-width: 720px;
    margin: 0 auto;
  }

  .oben {
    display: flex;
    align-items: center;
    gap: 16px;
    min-height: 34px;
    margin-bottom: 32px;
  }

  .segmente {
    flex: 1;
    display: flex;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .segmente li {
    flex: 1;
    height: 4px;
    border-radius: 2px;
    background: var(--rand);
  }

  .segmente li.erledigt {
    background: var(--akzent);
  }

  .segmente li.aktiv {
    background: var(--akzent);
    opacity: 0.5;
  }

  .buehne {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .buehne.mitte {
    align-items: center;
    text-align: center;
    justify-content: center;
    padding-bottom: 48px;
  }

  .titelzeile {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  h1 {
    font-size: 24px;
    outline: none;
  }

  .zeichen {
    border-radius: 16px;
  }

  .haken {
    color: var(--ok);
    display: inline-flex;
  }

  .satz {
    color: var(--text-2);
    font-size: 15px;
  }

  .zusammenfassung {
    margin: 0;
    padding: 4px 20px;
    min-width: 380px;
    text-align: left;
  }

  .zusammenfassung div {
    display: flex;
    justify-content: space-between;
    gap: 24px;
    padding: 12px 0;
    border-top: 1px solid var(--rand);
  }

  .zusammenfassung div:first-child {
    border-top: none;
  }

  dt {
    color: var(--text-2);
  }

  dd {
    margin: 0;
    font-weight: 600;
  }

  .neustart {
    width: 320px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    color: var(--text-2);
  }

  .unten {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 32px;
    padding-top: 20px;
    border-top: 1px solid var(--rand);
  }

  .platz {
    flex: 1;
  }
</style>
