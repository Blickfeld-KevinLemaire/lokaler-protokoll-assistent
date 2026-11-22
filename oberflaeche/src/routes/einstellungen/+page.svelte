<script lang="ts">
  import { tick } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import type { Anbieter, Einstellungen } from '$lib/api/typen';
  import Abschnitt from '$lib/komponenten/einstellungen/Abschnitt.svelte';
  import LokalesModell from '$lib/komponenten/einstellungen/LokalesModell.svelte';
  import OnlineDienst from '$lib/komponenten/einstellungen/OnlineDienst.svelte';
  import Systemcheck from '$lib/komponenten/einstellungen/Systemcheck.svelte';
  import Vorlagen from '$lib/komponenten/einstellungen/Vorlagen.svelte';
  import Wahl from '$lib/komponenten/einstellungen/Wahl.svelte';
  import Erweitert from '$lib/komponenten/Erweitert.svelte';
  import Info from '$lib/komponenten/Info.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import Schalter from '$lib/komponenten/Schalter.svelte';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { thema, type Thema } from '$lib/stores/thema.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { ordnerWaehlen } from '$lib/tauri';

  type Modus = 'lokal' | 'api';

  let anbieter = $state<Anbieter[]>([]);
  let netzPort = $state<number | null>(null);

  const w = $derived(einstellungen.werte);
  const info = $derived(verbindung.info);
  const desktop = $derived(info?.rolle === 'desktop');

  const ABSCHNITTE = $derived([
    { id: 'darstellung', text: 'Darstellung' },
    { id: 'transkription', text: 'Transkription' },
    { id: 'zusammenfassung', text: 'Zusammenfassung' },
    { id: 'chat', text: 'Frag mein Meeting' },
    ...(verbindung.tauri ? [{ id: 'ordner', text: 'Ordner' }] : []),
    { id: 'vorlagen', text: 'Vorlagen' },
    ...(desktop ? [{ id: 'netz', text: 'Im Netz anbieten' }] : []),
    { id: 'systemcheck', text: 'Systemcheck' }
  ]);

  const MODI: { wert: Modus; text: string }[] = [
    { wert: 'lokal', text: 'Auf diesem Computer' },
    { wert: 'api', text: 'Online-Dienst' }
  ];

  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit) return;
    api
      .anbieter()
      .then((a) => (anbieter = a))
      .catch((e) => console.warn('Anbieter nicht geladen', e));
  });

  $effect(() => {
    if (w && netzPort === null) netzPort = w.netz_freigabe_port ?? 8780;
  });

  // Sprung zu einem Abschnitt (z. B. aus dem Fehlerdialog)
  $effect(() => {
    const ziel = page.url.hash.slice(1);
    if (!ziel || !w) return;
    void tick().then(() => document.getElementById(ziel)?.scrollIntoView({ block: 'start' }));
  });

  async function setzen(aenderung: Partial<Einstellungen>) {
    try {
      await einstellungen.aendern(aenderung);
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    }
  }

  async function ordnerAendern(feld: 'ausgabeordner' | 'eingabeordner' | 'export_zielordner') {
    try {
      const pfad = await ordnerWaehlen(String(w?.[feld] ?? '') || null);
      if (pfad) await setzen({ [feld]: pfad });
    } catch (e) {
      dialog.zeigen(e);
    }
  }

  const ORDNER = [
    { feld: 'ausgabeordner', text: 'Ergebnisse' },
    { feld: 'eingabeordner', text: 'Eingang' },
    { feld: 'export_zielordner', text: 'Exporte' }
  ] as const;

  const KONTEXT = [
    { wert: 'auszuege', text: 'Passende Stellen' },
    { wert: 'volltext', text: 'Ganzer Text' }
  ];
</script>

<Kopf titel="Einstellungen" />

<div class="raster">
  <nav class="inhalt" aria-label="Abschnitte">
    {#each ABSCHNITTE as a (a.id)}
      <a href="#{a.id}" class:aktiv={page.url.hash === `#${a.id}`}>{a.text}</a>
    {/each}
  </nav>

  <div class="abschnitte">
    <Abschnitt id="darstellung" titel="Darstellung">
      {#snippet kinder()}
        <Wahl
          beschriftung="Farbschema"
          optionen={[
            { wert: 'system' as Thema, text: 'Wie Windows' },
            { wert: 'hell' as Thema, text: 'Hell' },
            { wert: 'dunkel' as Thema, text: 'Dunkel' }
          ]}
          wert={thema.wahl}
          aendern={(t) => thema.setzen(t)}
        />
      {/snippet}
    </Abschnitt>

    {#if w}
      <Abschnitt id="transkription" titel="Transkription">
        {#snippet kinder()}
          <Wahl
            beschriftung="Spracherkennung"
            optionen={MODI}
            wert={w.transkription_modus ?? 'lokal'}
            aendern={(m) => setzen({ transkription_modus: m })}
          />
          {#if (w.transkription_modus ?? 'lokal') === 'lokal'}
            {#if info && !info.faehigkeiten.lokale_transkription}
              <p class="warn">⚠ Auf diesem Computer noch nicht eingerichtet</p>
            {/if}
          {:else}
            <OnlineDienst bereich="transkription" {anbieter} />
          {/if}
        {/snippet}
      </Abschnitt>

      <Abschnitt id="zusammenfassung" titel="Zusammenfassung">
        {#snippet kinder()}
          <Wahl
            beschriftung="Sprachmodell"
            optionen={MODI}
            wert={w.nachbearbeitung_modus ?? 'lokal'}
            aendern={(m) => setzen({ nachbearbeitung_modus: m })}
          />
          {#if (w.nachbearbeitung_modus ?? 'lokal') === 'lokal'}
            <LokalesModell feld="ollama_modell" />
          {:else}
            <OnlineDienst bereich="nachbearbeitung" {anbieter} />
          {/if}
        {/snippet}
      </Abschnitt>

      <Abschnitt id="chat" titel="Frag mein Meeting">
        {#snippet kinder()}
          <Wahl
            beschriftung="Sprachmodell für Fragen"
            optionen={MODI}
            wert={w.chatbot_modus ?? 'lokal'}
            aendern={(m) => setzen({ chatbot_modus: m })}
          />
          <div class="zeile">
            <span class="beschriftung">Antworten aus</span>
            <Wahl
              beschriftung="Antworten aus"
              optionen={KONTEXT}
              wert={w.chatbot_kontext ?? 'auszuege'}
              aendern={(k) => setzen({ chatbot_kontext: k })}
            />
            <Info
              frage="Passende Stellen oder ganzer Text?"
              text="„Passende Stellen“ ist schnell und reicht meistens. „Ganzer Text“ liest alles und findet mehr, dauert aber länger."
            />
          </div>
          {#if (w.chatbot_modus ?? 'lokal') === 'lokal'}
            <LokalesModell feld="chatbot_ollama_modell" />
          {:else}
            <OnlineDienst bereich="chat" {anbieter} />
          {/if}
        {/snippet}
      </Abschnitt>

      {#if verbindung.tauri}
        <Abschnitt id="ordner" titel="Ordner">
          {#snippet kinder()}
            <div class="ordner">
              {#each ORDNER as o (o.feld)}
                <span class="beschriftung">{o.text}</span>
                <span class="pfad" title={String(w[o.feld] ?? '')}>
                  {w[o.feld] || (o.feld === 'ausgabeordner' ? info?.ausgabeordner : '') || '–'}
                </span>
                <button class="knopf" type="button" onclick={() => ordnerAendern(o.feld)}>Ändern</button>
              {/each}
            </div>
          {/snippet}
        </Abschnitt>
      {/if}

      <Abschnitt id="vorlagen" titel="Vorlagen">
        {#snippet kinder()}
          <Vorlagen />
        {/snippet}
      </Abschnitt>

      {#if desktop}
        <Abschnitt id="netz" titel="Im Netz anbieten">
          {#snippet kinder()}
            <Schalter
              an={!!w.netz_freigabe_aktiv}
              beschriftung="Andere Computer dürfen zugreifen"
              aendern={(an) => setzen({ netz_freigabe_aktiv: an })}
            >
              {#snippet info()}
                <Info
                  frage="Was bedeutet Im Netz anbieten?"
                  text="Kolleginnen und Kollegen öffnen VERMERK dann im Browser und melden sich mit einem Zugangsschlüssel an. Gilt ab dem nächsten Start."
                />
              {/snippet}
            </Schalter>
            <Erweitert>
              {#snippet kinder()}
                <div class="zeile">
                  <span class="beschriftung">Port</span>
                  <input
                    class="feld kurz"
                    type="number"
                    min="1024"
                    max="65535"
                    aria-label="Port"
                    bind:value={netzPort}
                  />
                  <button
                    class="knopf"
                    type="button"
                    disabled={!netzPort || netzPort === w.netz_freigabe_port}
                    onclick={() => setzen({ netz_freigabe_port: netzPort ?? 8780 })}
                  >
                    Übernehmen
                  </button>
                </div>
              {/snippet}
            </Erweitert>
          {/snippet}
        </Abschnitt>
      {/if}

      <Abschnitt id="systemcheck" titel="Systemcheck">
        {#snippet kinder()}
          <Systemcheck />
        {/snippet}
      </Abschnitt>
    {/if}

    <p class="version leise klein">
      VERMERK {info?.version ?? ''}{info?.angemeldet_als && !verbindung.tauri
        ? ` · angemeldet als ${info.angemeldet_als}`
        : ''}
      {#if !verbindung.tauri}
        · <button class="verweis" type="button" onclick={() => verbindung.abmelden()}>Abmelden</button>
      {/if}
    </p>
  </div>
</div>

<style>
  .raster {
    display: grid;
    grid-template-columns: 180px minmax(0, 1fr);
    gap: 28px;
    align-items: start;
  }

  .inhalt {
    position: sticky;
    top: 20px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .inhalt a {
    padding: 7px 12px;
    border-radius: 7px;
    color: var(--text-2);
    text-decoration: none;
  }

  .inhalt a:hover {
    background: var(--akzent-weich);
    color: var(--text);
  }

  .inhalt a.aktiv {
    color: var(--link);
    background: var(--akzent-weich);
    font-weight: 500;
  }

  .abschnitte {
    display: flex;
    flex-direction: column;
    gap: 18px;
    min-width: 0;
  }

  .warn {
    color: var(--warn);
  }

  .beschriftung {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }

  .ordner {
    display: grid;
    grid-template-columns: 100px minmax(0, 1fr) auto;
    gap: 10px 14px;
    align-items: center;
    width: 100%;
  }

  .pfad {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
  }

  .kurz {
    width: 110px;
  }

  .version {
    text-align: center;
    margin-top: 6px;
  }

  .verweis {
    border: none;
    background: none;
    padding: 0;
    color: var(--link);
    cursor: pointer;
  }
</style>
