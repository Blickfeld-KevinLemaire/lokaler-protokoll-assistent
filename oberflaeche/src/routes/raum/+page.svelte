<script lang="ts">
  import Hourglass from '@lucide/svelte/icons/hourglass';
  import Plus from '@lucide/svelte/icons/plus';
  import Radio from '@lucide/svelte/icons/radio';
  import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
  import Usb from '@lucide/svelte/icons/usb';
  import X from '@lucide/svelte/icons/x';
  import { api, ApiFehler } from '$lib/api/client';
  import type { GeraeteStand, Vorlage } from '$lib/api/typen';
  import Bestaetigen from '$lib/komponenten/Bestaetigen.svelte';
  import Erweitert from '$lib/komponenten/Erweitert.svelte';
  import Info from '$lib/komponenten/Info.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import LeerZustand from '$lib/komponenten/LeerZustand.svelte';
  import GeraetHinzufuegen from '$lib/komponenten/raum/GeraetHinzufuegen.svelte';
  import UsbEinrichtung from '$lib/komponenten/raum/UsbEinrichtung.svelte';
  import Schalter from '$lib/komponenten/Schalter.svelte';
  import { uhrzeit } from '$lib/logik/format';
  import { empfangsFehlerText } from '$lib/logik/hinweise';
  import { GERAETE_ZUSTAENDE } from '$lib/logik/stufen';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';

  let stand = $state<GeraeteStand | null>(null);
  let nichtVerfuegbar = $state(false);
  let vorlagen = $state<Vorlage[]>([]);
  let usbOffen = $state(false);
  let anlegenOffen = $state(false);
  let entfernenName = $state<string | null>(null);
  let port = $state<number | null>(null);

  const w = $derived(einstellungen.werte);
  // Per Kabel nur im Fenster auf diesem Computer (der Dienst spricht mit dem USB-Anschluss).
  const usbMoeglich = $derived(
    verbindung.tauri && !!verbindung.info?.faehigkeiten.dateipfade && verbindung.verwalten
  );

  async function laden() {
    try {
      stand = await api.geraete();
      nichtVerfuegbar = false;
    } catch (e) {
      if (e instanceof ApiFehler && e.status === 404) nichtVerfuegbar = true;
      else console.warn('Geräte nicht geladen', e);
    }
  }

  $effect(() => {
    void verbindung.runde;
    void zustand.einstellungenStand;
    void zustand.empfang;
    if (!verbindung.bereit) return;
    void laden();
  });

  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit) return;
    api
      .vorlagen()
      .then((v) => (vorlagen = v))
      .catch(() => undefined);
  });

  $effect(() => {
    if (verbindung.mehrbenutzer) void personen.laden();
  });

  $effect(() => {
    if (w && port === null) port = w.geraete_empfang_port ?? 8765;
  });

  async function setzen(aenderung: Record<string, unknown>) {
    try {
      await einstellungen.aendern(aenderung);
    } catch (e) {
      dialog.zeigen(e, 'Speichern hat nicht geklappt');
    }
  }

  async function entfernen() {
    const name = entfernenName;
    if (!name) return;
    try {
      await api.geraetEntfernen(name);
      void laden();
    } catch (e) {
      dialog.zeigen(e);
    }
  }

  function geraetStatus(name: string) {
    const eintraege = Object.values(zustand.geraeteStatus).filter((s) => s.geraet === name);
    return eintraege.sort((a, b) => (b.aktualisiert ?? 0) - (a.aktualisiert ?? 0))[0] ?? null;
  }

  const liveTexte = $derived(Object.values(zustand.live).filter((l) => l.text));
  const empfang = $derived(zustand.empfang ?? stand?.empfang ?? null);
</script>

<Kopf titel="VERMERK Raum" />

{#if nichtVerfuegbar}
  <div class="leer">Hier nicht verfügbar</div>
{:else}
  <div class="raster" class:einzeln={!verbindung.verwalten}>
    {#if verbindung.verwalten}
      <section class="karte block" aria-labelledby="empfang-titel">
        <h2 id="empfang-titel">Empfang</h2>
        <div class="zeile zwischen">
          <Schalter
            an={!!w?.geraete_empfang_aktiv}
            beschriftung="Aufnahmen von Geräten annehmen"
            deaktiviert={!w}
            aendern={(an) => setzen({ geraete_empfang_aktiv: an })}
          />
          {#if empfang}
            <span class="marke" class:an={empfang.aktiv}>{empfang.aktiv ? 'Empfang an' : 'Aus'}</span>
          {/if}
        </div>
        {#if empfang?.fehler}
          <p class="warn" title={empfang.fehler}>
            <TriangleAlert size={16} />
            {empfangsFehlerText(empfang.fehler_code)}
          </p>
        {/if}
        <Schalter
          an={!!w?.geraete_live_aktiv}
          beschriftung="Live mitschreiben"
          deaktiviert={!w}
          aendern={(an) => setzen({ geraete_live_aktiv: an })}
        >
          {#snippet info()}
            <Info
              frage="Was bedeutet Live mitschreiben?"
              text="Schon während der Aufnahme erscheint hier der Text. Das Ergebnis ist so früher fertig."
            />
          {/snippet}
        </Schalter>
        <Schalter
          an={!!w?.geraete_live_auswertung_vorab}
          beschriftung="Zusammenfassung vorbereiten"
          deaktiviert={!w || !w.geraete_live_aktiv}
          aendern={(an) => setzen({ geraete_live_auswertung_vorab: an })}
        >
          {#snippet info()}
            <Info
              frage="Was bedeutet Zusammenfassung vorbereiten?"
              text="Die Zusammenfassung entsteht schon während der Besprechung. Nach dem Ende ist sie schneller da."
            />
          {/snippet}
        </Schalter>
        <label class="feldzeile">
          <span>Vorlage für Zusammenfassungen</span>
          <select
            class="feld"
            value={w?.geraete_live_auftrag ?? ''}
            onchange={(e) => setzen({ geraete_live_auftrag: (e.currentTarget as HTMLSelectElement).value })}
          >
            <option value="">Automatisch</option>
            {#each vorlagen as v (v.name)}<option value={v.name}>{v.name}</option>{/each}
          </select>
        </label>
        <Erweitert>
          {#snippet kinder()}
            <label class="feldzeile">
              <span>Port</span>
              <div class="zeile">
                <input class="feld kurz" type="number" min="1024" max="65535" bind:value={port} />
                <button
                  class="knopf"
                  type="button"
                  disabled={!port || port === w?.geraete_empfang_port}
                  onclick={() => setzen({ geraete_empfang_port: port })}
                >
                  Übernehmen
                </button>
              </div>
            </label>
            {#if stand?.adressen.length}
              <div class="feldzeile">
                <span>Adresse dieses Computers</span>
                {#each stand.adressen as a (a)}<code>{a}</code>{/each}
              </div>
            {/if}
          {/snippet}
        </Erweitert>
      </section>
    {/if}

    <section class="karte block" aria-labelledby="geraete-titel">
      <div class="zeile zwischen">
        <h2 id="geraete-titel">Geräte</h2>
        {#if verbindung.verwalten}
          <div class="zeile kopfknoepfe">
            {#if usbMoeglich}
              <button class="knopf leise" type="button" onclick={() => (anlegenOffen = true)}>
                <Plus size={16} /> Ohne USB hinzufügen
              </button>
              <button class="knopf primaer" type="button" onclick={() => (usbOffen = true)}>
                <Usb size={16} /> Per USB verbinden
              </button>
            {:else}
              <button class="knopf" type="button" onclick={() => (anlegenOffen = true)}>
                <Plus size={16} /> Gerät hinzufügen
              </button>
            {/if}
          </div>
        {/if}
      </div>
      {#if !stand || stand.geraete.length === 0}
        <LeerZustand symbol={Radio} titel="Noch keine Geräte" klein />
      {:else}
        <ul class="geraete">
          {#each stand.geraete as g (g.name)}
            {@const s = geraetStatus(g.name)}
            <li>
              <span class="punkt" class:online={!!g.kontakt} aria-hidden="true"></span>
              <div class="g-text">
                <div class="g-name">
                  {g.name}
                  {#if verbindung.mehrbenutzer && verbindung.verwalten}
                    <span class="besitzer">
                      {g.besitzer ? personen.anzeigename(g.besitzer) : 'Allgemein'}
                    </span>
                  {/if}
                </div>
                <div class="leise klein">
                  {#if s}
                    {GERAETE_ZUSTAENDE[s.zustand] ?? 'Aktiv'}
                  {:else if g.kontakt}
                    Zuletzt gesehen {uhrzeit(g.kontakt.zeit)}
                  {:else}
                    Noch nicht verbunden
                  {/if}
                  {#if g.kontakt?.andere_id}<span class="warn"> · anderes Gerät meldet sich</span>{/if}
                </div>
              </div>
              {#if verbindung.verwalten}
                <button
                  class="symbolknopf"
                  type="button"
                  aria-label="{g.name} entfernen"
                  title="Entfernen"
                  onclick={() => (entfernenName = g.name)}
                >
                  <X size={16} />
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}

      {#if zustand.freigaben.length}
        <h3 class="unterkopf">Wartet auf Freigabe am Gerät</h3>
        <ul class="freigaben">
          {#each zustand.freigaben as f (f.geraet + f.datei)}
            <li><Hourglass size={16} /> {f.geraet} · {f.datei}</li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>

  {#each liveTexte as l (l.geraet)}
    <section class="karte live" aria-label="Live-Text von {l.geraet}">
      <div class="zeile">
        <span class="rot" aria-hidden="true"></span>
        <h2>{l.geraet}</h2>
      </div>
      <div class="live-text">{l.text}</div>
    </section>
  {/each}
{/if}

<UsbEinrichtung offen={usbOffen} schliessen={() => (usbOffen = false)} fertig={() => void laden()} />

<GeraetHinzufuegen
  offen={anlegenOffen}
  schliessen={() => (anlegenOffen = false)}
  fertig={() => void laden()}
/>

<Bestaetigen
  offen={!!entfernenName}
  titel="„{entfernenName}“ entfernen?"
  text="Das Gerät kann danach nichts mehr senden."
  verb="Entfernen"
  bestaetigen={entfernen}
  schliessen={() => (entfernenName = null)}
/>

<style>
  .raster {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 20px;
    align-items: start;
  }

  .raster.einzeln {
    grid-template-columns: minmax(0, 640px);
  }

  .block {
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .zwischen {
    justify-content: space-between;
    flex-wrap: wrap;
    row-gap: 8px;
  }

  .kopfknoepfe {
    flex-wrap: wrap;
    justify-content: flex-end;
    row-gap: 8px;
    margin-left: auto;
  }

  .feldzeile {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .feldzeile > span {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }

  .kurz {
    width: 110px;
  }

  .marke {
    flex: none;
    white-space: nowrap;
    font-size: 12px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 10px;
    background: var(--karte-2);
    color: var(--text-3);
  }

  .marke.an {
    background: var(--ok-weich);
    color: var(--ok);
  }

  .warn {
    color: var(--warn);
  }

  code {
    font-family: 'Cascadia Mono', Consolas, monospace;
    font-size: 12.5px;
    color: var(--text);
  }

  .geraete,
  .freigaben {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .geraete li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 0;
    border-top: 1px solid var(--rand);
  }

  .geraete li:first-child {
    border-top: none;
  }

  .punkt {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--text-3);
    opacity: 0.5;
  }

  .punkt.online {
    background: var(--ok);
    opacity: 1;
  }

  .g-text {
    flex: 1;
    min-width: 0;
  }

  .besitzer {
    margin-left: 6px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-2);
  }

  .g-name {
    font-weight: 600;
  }

  .unterkopf {
    font-size: 12.5px;
    color: var(--text-2);
    margin-top: 6px;
  }

  .freigaben li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
  }

  p.warn {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .live {
    margin-top: 20px;
    padding: 18px 20px;
  }

  .rot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--fehler);
  }

  .live-text {
    margin-top: 10px;
    max-height: 260px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.6;
  }
</style>
