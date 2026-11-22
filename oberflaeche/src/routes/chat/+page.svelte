<script lang="ts">
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import Library from '@lucide/svelte/icons/library';
  import MessagesSquare from '@lucide/svelte/icons/messages-square';
  import Plus from '@lucide/svelte/icons/plus';
  import Send from '@lucide/svelte/icons/send';
  import Square from '@lucide/svelte/icons/square';
  import X from '@lucide/svelte/icons/x';
  import { tick } from 'svelte';
  import { fragen } from '$lib/api/chat';
  import { api } from '$lib/api/client';
  import type { Besprechung, ChatNachricht, ChatVerlaufKurz } from '$lib/api/typen';
  import Kopf from '$lib/komponenten/Kopf.svelte';
  import LeerZustand from '$lib/komponenten/LeerZustand.svelte';
  import Markdown from '$lib/komponenten/Markdown.svelte';
  import { zeitLesen } from '$lib/logik/format';
  import { dialog, meldungen } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';

  interface Eintrag extends ChatNachricht {
    laeuft?: boolean;
    status?: string;
    fehler?: boolean;
  }

  let verlaeufe = $state<ChatVerlaufKurz[]>([]);
  let besprechungen = $state<Besprechung[] | null>(null);
  /** Gelöscht, aber noch rückgängig zu machen (wird erst nach der Meldung wirklich gelöscht). */
  let geloescht = $state<string[]>([]);
  let gewaehlt = $state<string[]>([]);
  let auswahlOffen = $state(false);
  let verlaufId = $state<string | null>(null);
  let nachrichten = $state<Eintrag[]>([]);
  let frage = $state('');
  let laeuft = $state(false);
  let abbruch: AbortController | null = null;
  let verlaufFeld: HTMLDivElement | undefined = $state();

  $effect(() => {
    void verbindung.runde;
    if (!verbindung.bereit) return;
    void verlaeufeLaden();
    api
      .besprechungen()
      .then((l) => (besprechungen = l))
      .catch((e) => console.warn('Besprechungen nicht geladen', e));
  });

  async function verlaeufeLaden() {
    try {
      verlaeufe = await api.chatVerlaeufe();
    } catch (e) {
      console.warn('Verläufe nicht geladen', e);
    }
  }

  async function nachUnten() {
    await tick();
    if (verlaufFeld) verlaufFeld.scrollTop = verlaufFeld.scrollHeight;
  }

  function neu() {
    abbruch?.abort();
    verlaufId = null;
    nachrichten = [];
    frage = '';
  }

  async function oeffnen(id: string) {
    abbruch?.abort();
    try {
      const v = await api.chatVerlauf(id);
      verlaufId = v.id;
      nachrichten = v.nachrichten;
      await nachUnten();
    } catch (e) {
      dialog.zeigen(e, 'Chat nicht geladen');
    }
  }

  /** Löschen mit „Rückgängig“: erst ausblenden, nach der Meldung wirklich löschen. */
  function loeschen(id: string) {
    const titel = verlaeufe.find((v) => v.id === id)?.titel ?? 'Chat';
    geloescht = [...geloescht, id];
    if (verlaufId === id) neu();
    let zurueck = false;
    meldungen.zeigen(`„${titel}“ gelöscht`, 'info', 6000, {
      text: 'Rückgängig',
      tun: () => {
        zurueck = true;
        geloescht = geloescht.filter((g) => g !== id);
      }
    });
    setTimeout(async () => {
      if (zurueck) return;
      try {
        await api.chatVerlaufLoeschen(id);
        await verlaeufeLaden();
      } catch (e) {
        dialog.zeigen(e);
      } finally {
        geloescht = geloescht.filter((g) => g !== id);
      }
    }, 6500);
  }

  function stoppen() {
    abbruch?.abort();
  }

  const sichtbar = $derived(verlaeufe.filter((v) => !geloescht.includes(v.id)));

  async function senden(e?: SubmitEvent) {
    e?.preventDefault();
    const text = frage.trim();
    if (!text || laeuft) return;
    frage = '';
    laeuft = true;
    nachrichten = [
      ...nachrichten,
      { role: 'user', content: text },
      { role: 'assistant', content: '', laeuft: true }
    ];
    const index = nachrichten.length - 1;
    abbruch = new AbortController();
    await nachUnten();
    try {
      await fragen(
        text,
        gewaehlt,
        verlaufId,
        {
          status: (s) => (nachrichten[index]!.status = s),
          text: (bisher) => {
            nachrichten[index]!.content = bisher;
            void nachUnten();
          },
          fertig: (antwort, quellen, id) => {
            nachrichten[index] = { role: 'assistant', content: antwort, quellen };
            verlaufId = id || verlaufId;
            void verlaeufeLaden();
          },
          fehler: (meldung) => {
            nachrichten[index] = { role: 'assistant', content: meldung, fehler: true };
          }
        },
        abbruch.signal
      );
    } catch (f) {
      if (!(f instanceof DOMException && f.name === 'AbortError')) {
        nachrichten[index] = { role: 'assistant', content: 'Keine Antwort erhalten.', fehler: true };
        console.warn('Chat abgebrochen', f);
      }
    } finally {
      if (nachrichten[index]?.laeuft) nachrichten[index]!.laeuft = false;
      laeuft = false;
      await nachUnten();
    }
  }

  function taste(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void senden();
    }
  }

  function umschalten(id: string) {
    gewaehlt = gewaehlt.includes(id) ? gewaehlt.filter((g) => g !== id) : [...gewaehlt, id];
  }

  const auswahlText = $derived(
    gewaehlt.length === 0
      ? 'Alle Besprechungen'
      : gewaehlt.length === 1
        ? (besprechungen?.find((b) => b.id === gewaehlt[0])?.titel ?? '1 Besprechung')
        : `${gewaehlt.length} Besprechungen`
  );

  function verlaufDatum(text: string): string {
    const d = zeitLesen(text);
    return d ? d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }) : '';
  }
</script>

<svelte:window
  onclick={(e) => auswahlOffen && !(e.target as HTMLElement).closest('.auswahl') && (auswahlOffen = false)}
  onkeydown={(e) => {
    if (e.key === 'Escape' && auswahlOffen) {
      e.preventDefault();
      auswahlOffen = false;
    }
  }}
/>

<Kopf titel="Frag mein Meeting">
  {#snippet aktionen()}
    <div class="auswahl">
      <button
        class="knopf"
        type="button"
        aria-haspopup="true"
        aria-expanded={auswahlOffen}
        onclick={() => (auswahlOffen = !auswahlOffen)}
      >
        <span class="auswahl-text">{auswahlText}</span>
        <ChevronDown size={16} />
      </button>
      {#if auswahlOffen}
        <div class="liste karte" role="group" aria-label="Besprechungen auswählen">
          <label class="option">
            <input type="checkbox" checked={gewaehlt.length === 0} onchange={() => (gewaehlt = [])} />
            Alle Besprechungen
          </label>
          {#each besprechungen ?? [] as b (b.id)}
            <label class="option">
              <input type="checkbox" checked={gewaehlt.includes(b.id)} onchange={() => umschalten(b.id)} />
              <span class="name">{b.titel}</span>
            </label>
          {/each}
        </div>
      {/if}
    </div>
  {/snippet}
</Kopf>

<div class="chat">
  <aside class="verlaeufe" aria-label="Frühere Chats">
    <button class="knopf neu" type="button" onclick={neu}><Plus size={16} /> Neuer Chat</button>
    <ul>
      {#each sichtbar as v (v.id)}
        <li class:aktiv={v.id === verlaufId}>
          <button class="eintrag" type="button" onclick={() => oeffnen(v.id)} title={v.titel}>
            <span class="name">{v.titel}</span>
            <span class="datum">{verlaufDatum(v.aktualisiert)}</span>
          </button>
          <button
            class="symbolknopf loeschen"
            type="button"
            aria-label="„{v.titel}“ löschen"
            title="Löschen"
            onclick={() => loeschen(v.id)}
          >
            <X size={16} />
          </button>
        </li>
      {/each}
    </ul>
  </aside>

  <section class="gespraech karte">
    <div class="nachrichten" bind:this={verlaufFeld} aria-live="polite">
      {#if nachrichten.length === 0}
        <div class="leer-chat">
          {#if besprechungen && besprechungen.length === 0}
            <LeerZustand symbol={Library} titel="Noch keine Besprechungen">
              {#snippet aktion()}
                <a class="knopf primaer" href="/?neu=1"><Plus size={16} /> Neue Transkription</a>
              {/snippet}
            </LeerZustand>
          {:else}
            <LeerZustand symbol={MessagesSquare} titel="Was möchten Sie wissen?" />
          {/if}
        </div>
      {/if}
      {#each nachrichten as n, i (i)}
        {#if n.role === 'user'}
          <div class="frage">{n.content}</div>
        {:else}
          <div class="antwort" class:fehler={n.fehler}>
            {#if n.laeuft}
              {#if n.content}
                <div class="strom">{n.content}</div>
              {:else}
                <div class="status"><span class="punkte" aria-hidden="true">•••</span> {n.status ?? ''}</div>
              {/if}
            {:else if n.fehler}
              {n.content}
            {:else}
              <Markdown text={n.content} />
              {#if n.quellen?.length}
                <div class="quellen">
                  {#each n.quellen as q, j (j)}<span class="quelle">{q}</span>{/each}
                </div>
              {/if}
            {/if}
          </div>
        {/if}
      {/each}
    </div>
    <form class="eingabe" onsubmit={senden}>
      <textarea
        class="feld"
        rows="2"
        placeholder="Frage stellen …"
        aria-label="Frage"
        bind:value={frage}
        onkeydown={taste}></textarea>
      {#if laeuft}
        <button class="knopf" type="button" onclick={stoppen}><Square size={14} /> Stopp</button>
      {:else}
        <button class="knopf primaer" type="submit" disabled={!frage.trim()}>
          <Send size={16} /> Senden
        </button>
      {/if}
    </form>
  </section>
</div>

<style>
  .auswahl {
    position: relative;
  }

  .auswahl .knopf {
    max-width: 280px;
  }

  .auswahl-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .liste {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 30;
    width: 320px;
    max-height: 340px;
    overflow-y: auto;
    padding: 6px;
    box-shadow: var(--schatten-hoch);
  }

  .option {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 8px;
    border-radius: 6px;
    cursor: pointer;
  }

  .option:hover {
    background: var(--karte-2);
  }

  .option .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chat {
    display: grid;
    grid-template-columns: 230px minmax(0, 1fr);
    gap: 18px;
    height: calc(100vh - 120px);
    min-height: 420px;
  }

  .verlaeufe {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }

  .neu {
    width: 100%;
  }

  .verlaeufe ul {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .verlaeufe li {
    display: flex;
    align-items: center;
    border-radius: 7px;
  }

  .verlaeufe li:hover,
  .verlaeufe li.aktiv {
    background: var(--akzent-weich);
  }

  .eintrag {
    flex: 1;
    min-width: 0;
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 4px 8px 10px;
    border: none;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }

  .eintrag .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .datum {
    color: var(--text-3);
    font-size: 12px;
    flex: none;
  }

  .loeschen {
    opacity: 0;
  }

  .verlaeufe li:hover .loeschen,
  .loeschen:focus-visible {
    opacity: 1;
  }

  .gespraech {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .nachrichten {
    flex: 1;
    overflow-y: auto;
    padding: 22px 26px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .leer-chat {
    margin: auto;
  }

  .frage {
    align-self: flex-end;
    max-width: 75%;
    padding: 9px 14px;
    border-radius: 14px 14px 4px 14px;
    background: var(--akzent);
    color: var(--akzent-text);
    white-space: pre-wrap;
  }

  .antwort {
    align-self: flex-start;
    max-width: 85%;
    padding: 12px 16px;
    border-radius: 14px 14px 14px 4px;
    background: var(--karte-2);
    border: 1px solid var(--rand);
  }

  .antwort.fehler {
    color: var(--fehler);
    background: var(--fehler-weich);
    border-color: transparent;
  }

  .strom {
    white-space: pre-wrap;
    line-height: 1.6;
  }

  .status {
    color: var(--text-2);
    font-size: 13px;
  }

  .punkte {
    letter-spacing: 2px;
    animation: atmen 1.2s ease-in-out infinite;
  }

  @keyframes atmen {
    50% {
      opacity: 0.3;
    }
  }

  .quellen {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }

  .quelle {
    padding: 2px 9px;
    border-radius: 10px;
    background: var(--karte);
    border: 1px solid var(--rand);
    font-size: 12px;
    color: var(--text-2);
  }

  .eingabe {
    display: flex;
    gap: 10px;
    align-items: flex-end;
    padding: 14px 16px;
    border-top: 1px solid var(--rand);
  }

  .eingabe textarea {
    resize: none;
  }
</style>
