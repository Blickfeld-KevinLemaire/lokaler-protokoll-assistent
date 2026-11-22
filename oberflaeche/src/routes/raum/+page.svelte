<script lang="ts">
  import { api, ApiFehler } from '$lib/api/client';
  import type { GeraetAngelegt, GeraeteStand, Vorlage } from '$lib/api/typen';
  import Dialog from '$lib/komponenten/Dialog.svelte';
  import Erweitert from '$lib/komponenten/Erweitert.svelte';
  import Info from '$lib/komponenten/Info.svelte';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import Schalter from '$lib/komponenten/Schalter.svelte';
  import { uhrzeit } from '$lib/logik/format';
  import { GERAETE_ZUSTAENDE } from '$lib/logik/stufen';
  import { einstellungen } from '$lib/stores/einstellungen.svelte';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { personen } from '$lib/stores/personen.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import { zustand } from '$lib/stores/zustand.svelte';

  let stand = $state<GeraeteStand | null>(null);
  let nichtVerfuegbar = $state(false);
  let vorlagen = $state<Vorlage[]>([]);
  let neuerName = $state('');
  let besitzer = $state('');
  let anlegenOffen = $state(false);
  let angelegt = $state<GeraetAngelegt | null>(null);
  let port = $state<number | null>(null);

  const w = $derived(einstellungen.werte);

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

  async function anlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      angelegt = await api.geraetAnlegen(neuerName.trim(), besitzer || null);
      anlegenOffen = false;
      neuerName = '';
      void laden();
    } catch (f) {
      dialog.zeigen(f, 'Gerät nicht angelegt');
    }
  }

  async function entfernen(name: string) {
    if (!confirm(`„${name}“ entfernen? Das Gerät kann danach nichts mehr senden.`)) return;
    try {
      await api.geraetEntfernen(name);
      void laden();
    } catch (e) {
      dialog.zeigen(e);
    }
  }

  async function kopieren(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      meldungen.zeigen('Kopiert');
    } catch {
      meldungen.zeigen('Kopieren nicht möglich', 'fehler');
    }
  }

  function geraetStatus(name: string) {
    const eintraege = Object.values(zustand.geraeteStatus).filter((s) => s.geraet === name);
    return eintraege.sort((a, b) => (b.aktualisiert ?? 0) - (a.aktualisiert ?? 0))[0] ?? null;
  }

  const liveTexte = $derived(Object.values(zustand.live).filter((l) => l.text));
  const empfang = $derived(zustand.empfang ?? stand?.empfang ?? null);
  const portBelegt = $derived(/belegt|benutzt|in use|10048/i.test(empfang?.fehler ?? ''));
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
      {#if empfang?.fehler}<p class="warn">⚠ {portBelegt ? 'Port belegt' : 'Empfang gestört'}</p>{/if}
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
          <button class="knopf" type="button" onclick={() => (anlegenOffen = true)}>
            +&nbsp; Gerät hinzufügen
          </button>
        {/if}
      </div>
      {#if !stand || stand.geraete.length === 0}
        <div class="leer klein">Noch keine Geräte</div>
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
                    <span class="besitzer">{g.besitzer ? personen.anzeigename(g.besitzer) : 'Allgemein'}</span>
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
                  onclick={() => entfernen(g.name)}
                >
                  ✕
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
            <li><span aria-hidden="true">⏳</span> {f.geraet} · {f.datei}</li>
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

<Dialog offen={anlegenOffen} titel="Gerät hinzufügen" schliessen={() => (anlegenOffen = false)}>
  {#snippet kinder()}
    <form id="geraet-form" class="formular" onsubmit={anlegen}>
      <label class="feldzeile">
        <span>Name</span>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="feld"
          maxlength="32"
          pattern="[A-Za-z0-9_\-]+"
          placeholder="z. B. Raum-3"
          autofocus
          bind:value={neuerName}
        />
      </label>
      {#if verbindung.mehrbenutzer}
        <label class="feldzeile">
          <span>Gehört</span>
          <select class="feld" bind:value={besitzer}>
            <option value="">Allgemein</option>
            {#each personen.liste as p (p.name)}<option value={p.name}>{p.anzeigename}</option>{/each}
          </select>
        </label>
      {/if}
    </form>
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf" type="button" onclick={() => (anlegenOffen = false)}>Abbrechen</button>
    <button class="knopf primaer" type="submit" form="geraet-form" disabled={!neuerName.trim()}>
      Hinzufügen
    </button>
  {/snippet}
</Dialog>

<Dialog
  offen={!!angelegt}
  titel="„{angelegt?.name}“ einrichten"
  schliessen={() => (angelegt = null)}
  breite={560}
>
  {#snippet kinder()}
    {#if angelegt}
      <p class="einmal">Wird nur jetzt angezeigt.</p>
      <div class="kopierzeile">
        <span>Adresse</span>
        <code>{angelegt.basis_url}</code>
        <button class="knopf" type="button" onclick={() => kopieren(angelegt!.basis_url)}>Kopieren</button>
      </div>
      <div class="kopierzeile">
        <span>Schlüssel</span>
        <code>{angelegt.token}</code>
        <button class="knopf" type="button" onclick={() => kopieren(angelegt!.token)}>Kopieren</button>
      </div>
      <Erweitert titel="Für die Gerätesoftware">
        {#snippet kinder()}
          <div class="kopierzeile">
            <pre>{angelegt!.konfiguration}</pre>
            <button class="knopf" type="button" onclick={() => kopieren(angelegt!.konfiguration)}>
              Kopieren
            </button>
          </div>
        {/snippet}
      </Erweitert>
    {/if}
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf primaer" type="button" onclick={() => (angelegt = null)}>Fertig</button>
  {/snippet}
</Dialog>

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

  .formular {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .block {
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .zwischen {
    justify-content: space-between;
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
    padding: 4px 0;
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

  .einmal {
    color: var(--warn);
    font-weight: 600;
    margin-bottom: 12px;
  }

  .kopierzeile {
    display: grid;
    grid-template-columns: 80px minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
  }

  .kopierzeile code {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 6px 8px;
    border-radius: 6px;
    background: var(--karte-2);
  }

  .kopierzeile pre {
    grid-column: 1 / 3;
    margin: 0;
    padding: 8px;
    border-radius: 6px;
    background: var(--karte-2);
    font-size: 12px;
    overflow-x: auto;
    color: var(--text);
  }
</style>
