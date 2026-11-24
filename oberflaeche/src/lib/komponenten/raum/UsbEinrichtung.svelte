<script lang="ts">
  /** Aufnahmegerät per USB-Kabel einrichten: anschließen → Name und WLAN → fertig. */
  import Check from '@lucide/svelte/icons/check';
  import { api, ApiFehler } from '#lib/api/client.ts';
  import type { UsbAnschluss, UsbGeraet } from '#lib/api/typen.ts';
  import Dialog from '../Dialog.svelte';
  import Erweitert from '../Erweitert.svelte';
  import Fortschritt from '../Fortschritt.svelte';
  import FirewallFreigabe from './FirewallFreigabe.svelte';
  import Info from '../Info.svelte';

  let { offen, schliessen, fertig }: { offen: boolean; schliessen: () => void; fertig: () => void } =
    $props();

  type Schritt = 'anschliessen' | 'angaben' | 'einrichten' | 'fertig';

  let schritt = $state<Schritt>('anschliessen');
  let anschluesse = $state<UsbAnschluss[] | null>(null);
  let port = $state('');
  let geraet = $state<UsbGeraet | null>(null);
  let laeuft = $state(false);
  let fehler = $state('');
  let nichtUnterstuetzt = $state(false);
  let name = $state('');
  let ssid = $state('');
  let wlanPasswort = $state('');
  let pcUrl = $state('');
  let serverUrl = $state('');
  let serverSchluessel = $state('');
  let eingerichtetAls = $state('');
  let erreicht = $state(true);

  $effect(() => {
    if (!offen) return;
    schritt = 'anschliessen';
    geraet = null;
    fehler = '';
    name = '';
    wlanPasswort = '';
    void suchen();
  });

  function meldung(e: unknown): string {
    return e instanceof ApiFehler || e instanceof Error ? e.message : 'Das hat nicht geklappt.';
  }

  async function suchen() {
    laeuft = true;
    fehler = '';
    try {
      anschluesse = await api.usbAnschluesse();
      nichtUnterstuetzt = false;
      const vermerk = anschluesse.find((a) => a.vermerk);
      if (!anschluesse.some((a) => a.port === port)) port = vermerk?.port ?? anschluesse[0]?.port ?? '';
    } catch (e) {
      anschluesse = [];
      if (e instanceof ApiFehler && e.status === 503) nichtUnterstuetzt = true;
      else fehler = meldung(e);
    } finally {
      laeuft = false;
    }
  }

  async function erkennen() {
    laeuft = true;
    fehler = '';
    try {
      geraet = await api.usbErkennen(port);
      name = geraet.bekannt_als ?? '';
      ssid = ssid || geraet.wlan || '';
      schritt = 'angaben';
    } catch (e) {
      fehler = meldung(e);
    } finally {
      laeuft = false;
    }
  }

  async function einrichten(e: SubmitEvent) {
    e.preventDefault();
    schritt = 'einrichten';
    fehler = '';
    try {
      const ergebnis = await api.usbEinrichten({
        port,
        name: name.trim(),
        wlan_ssid: ssid.trim(),
        wlan_passwort: wlanPasswort,
        pc_url: pcUrl.trim(),
        server_url: serverUrl.trim(),
        server_token: serverSchluessel.trim()
      });
      eingerichtetAls = ergebnis.name;
      erreicht = ergebnis.erreicht;
      wlanPasswort = '';
      schritt = 'fertig';
      fertig();
    } catch (f) {
      fehler = meldung(f);
      schritt = 'angaben';
    }
  }

  const SCHRITTE: { id: Schritt; text: string }[] = [
    { id: 'anschliessen', text: 'Anschließen' },
    { id: 'angaben', text: 'Name und WLAN' },
    { id: 'fertig', text: 'Fertig' }
  ];
  const aktuellerIndex = $derived(schritt === 'einrichten' ? 1 : SCHRITTE.findIndex((s) => s.id === schritt));
</script>

<Dialog
  {offen}
  titel="Gerät per USB verbinden"
  schliessen={() => schritt !== 'einrichten' && schliessen()}
  breite={520}
>
  {#snippet kinder()}
    <ol class="schritte" aria-label="Schritte">
      {#each SCHRITTE as s, i (s.id)}
        <li
          class:erledigt={i < aktuellerIndex}
          class:aktiv={i === aktuellerIndex}
          aria-current={i === aktuellerIndex ? 'step' : undefined}
        >
          <span class="nr">
            {#if i < aktuellerIndex}<Check size={12} strokeWidth={2.5} />{:else}{i + 1}{/if}
          </span>{s.text}
        </li>
      {/each}
    </ol>

    {#if schritt === 'anschliessen'}
      {#if nichtUnterstuetzt}
        <p class="hinweis">Auf diesem Computer ist das Einrichten per USB nicht möglich.</p>
      {:else if anschluesse && anschluesse.length === 0 && !laeuft}
        <p class="leise">Kein Gerät gefunden. Bitte das Gerät per USB-Kabel anschließen.</p>
      {:else if anschluesse}
        <div class="anschluesse" role="radiogroup" aria-label="Gerät">
          {#each anschluesse as a (a.port)}
            <label class="anschluss" class:gewaehlt={port === a.port}>
              <input type="radio" name="usb-port" value={a.port} bind:group={port} />
              <span class="a-text">
                <span class="a-name">
                  {a.vermerk ? 'VERMERK-Gerät' : a.beschreibung || 'Unbekanntes Gerät'}
                </span>
                <span class="leise klein">{a.vermerk ? a.beschreibung : ''} {a.port}</span>
              </span>
            </label>
          {/each}
        </div>
      {/if}
      {#if laeuft}<div class="laeuft"><Fortschritt anteil={null} beschriftung="Suche" /></div>{/if}
    {:else if schritt === 'angaben' || schritt === 'einrichten'}
      <form id="usb-form" class="formular" onsubmit={einrichten}>
        {#if geraet?.bekannt_als}
          <p class="leise klein">Bisher eingerichtet als „{geraet.bekannt_als}“.</p>
        {/if}
        <label class="feldzeile">
          <span>Name des Geräts</span>
          <input
            class="feld"
            maxlength="32"
            placeholder="z. B. Besprechungsraum 3"
            disabled={schritt === 'einrichten'}
            bind:value={name}
          />
        </label>
        <label class="feldzeile">
          <span>WLAN</span>
          <input
            class="feld"
            maxlength="64"
            autocomplete="off"
            disabled={schritt === 'einrichten'}
            bind:value={ssid}
          />
        </label>
        <label class="feldzeile">
          <span>WLAN-Passwort</span>
          <input
            class="feld"
            type="password"
            maxlength="64"
            autocomplete="off"
            disabled={schritt === 'einrichten'}
            bind:value={wlanPasswort}
          />
        </label>
        <Erweitert>
          {#snippet kinder()}
            <label class="feldzeile">
              <span>Adresse dieses Computers</span>
              <input class="feld" placeholder="Wird selbst ermittelt" spellcheck="false" bind:value={pcUrl} />
            </label>
            <label class="feldzeile">
              <span>
                Zusätzlich an einen Server senden
                <Info
                  frage="Was bedeutet zusätzlich an einen Server?"
                  text="Das Gerät kann seine Aufnahmen auch an einen VERMERK-Server schicken – neben diesem Computer."
                />
              </span>
              <input
                class="feld"
                placeholder="Adresse des Servers"
                spellcheck="false"
                bind:value={serverUrl}
              />
            </label>
            <label class="feldzeile">
              <span>Schlüssel für den Server</span>
              <input class="feld" type="password" autocomplete="off" bind:value={serverSchluessel} />
            </label>
          {/snippet}
        </Erweitert>
      </form>
      {#if schritt === 'einrichten'}
        <div class="laeuft">
          <Fortschritt anteil={null} beschriftung="Einrichtung" />
          <p class="leise">Gerät wird eingerichtet …</p>
        </div>
      {/if}
    {:else}
      <div class="fertig">
        <span class="haken"><Check size={20} strokeWidth={2.25} /></span>
        <p><strong>„{eingerichtetAls}“</strong> ist eingerichtet. Das Kabel kann jetzt ab.</p>
      </div>
      {#if !erreicht}<FirewallFreigabe />{/if}
    {/if}

    {#if fehler}<p class="fehler" role="alert">{fehler}</p>{/if}
  {/snippet}
  {#snippet knoepfe()}
    {#if schritt === 'anschliessen'}
      <button class="knopf leise" type="button" disabled={laeuft || nichtUnterstuetzt} onclick={suchen}>
        Neu suchen
      </button>
      <button class="knopf" type="button" onclick={schliessen}>Abbrechen</button>
      <button class="knopf primaer" type="button" disabled={!port || laeuft} onclick={erkennen}>
        Weiter
      </button>
    {:else if schritt === 'angaben' || schritt === 'einrichten'}
      <button
        class="knopf"
        type="button"
        disabled={schritt === 'einrichten'}
        onclick={() => (schritt = 'anschliessen')}
      >
        Zurück
      </button>
      <button
        class="knopf primaer"
        type="submit"
        form="usb-form"
        disabled={schritt === 'einrichten' || !name.trim() || !ssid.trim()}
      >
        Einrichten
      </button>
    {:else}
      <button class="knopf primaer" type="button" onclick={schliessen}>Fertig</button>
    {/if}
  {/snippet}
</Dialog>

<style>
  .schritte {
    list-style: none;
    margin: 0 0 18px;
    padding: 0;
    display: flex;
    gap: 18px;
    font-size: 13px;
    color: var(--text-3);
  }

  .schritte li {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .schritte li.aktiv {
    color: var(--text);
    font-weight: 600;
  }

  .schritte li.erledigt {
    color: var(--ok);
  }

  .nr {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid currentColor;
    font-size: 11px;
  }

  .aktiv .nr {
    background: var(--akzent);
    border-color: var(--akzent);
    color: var(--akzent-text);
  }

  .anschluesse {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .anschluss {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border: 1px solid var(--rand);
    border-radius: 8px;
    cursor: pointer;
    color: var(--text);
  }

  .anschluss.gewaehlt {
    border-color: var(--akzent);
    background: var(--akzent-weich);
  }

  .a-text {
    display: flex;
    flex-direction: column;
  }

  .a-name {
    font-weight: 500;
  }

  .formular {
    display: flex;
    flex-direction: column;
    gap: 12px;
    color: var(--text);
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
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .laeuft {
    margin-top: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .hinweis {
    color: var(--warn);
  }

  .fehler {
    margin-top: 12px;
    color: var(--fehler);
  }

  .fertig {
    display: flex;
    align-items: center;
    gap: 14px;
    color: var(--text);
  }

  .haken {
    width: 36px;
    height: 36px;
    flex: none;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--ok-weich);
    color: var(--ok);
    font-weight: 700;
  }
</style>
