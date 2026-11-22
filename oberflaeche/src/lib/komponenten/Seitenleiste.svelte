<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '$lib/api/client';
  import { dialog } from '$lib/stores/oberflaeche.svelte';
  import { verbindung } from '$lib/stores/verbindung.svelte';
  import StatusBereich from './StatusBereich.svelte';

  const eintraege = [
    { href: '/', symbol: '🎙', text: 'Transkription' },
    { href: '/besprechungen', symbol: '🗂', text: 'Besprechungen' },
    { href: '/chat', symbol: '💬', text: 'Frag mein Meeting' },
    { href: '/raum', symbol: '📡', text: 'VERMERK Raum' }
  ];

  function aktiv(href: string): boolean {
    const pfad = page.url.pathname.replace(/\/+$/, '') || '/';
    return href === '/' ? pfad === '/' : pfad === href || pfad.startsWith(`${href}/`);
  }

  async function ordnerOeffnen() {
    const pfad = verbindung.info?.ausgabeordner;
    if (!pfad) return;
    try {
      await api.ordnerOeffnen(pfad);
    } catch (e) {
      dialog.zeigen(e, 'Ordner lässt sich nicht öffnen');
    }
  }
</script>

<nav class="leiste" aria-label="Hauptnavigation">
  <div class="marke">
    <img src="/vermerk_logo_hell.png" alt="VERMERK" width="210" height="47" />
    <span class="unter">{verbindung.tauri ? 'Desktop' : 'Im Netz'}</span>
  </div>

  <button class="neu" type="button" onclick={() => goto('/?neu=1')}>
    <span aria-hidden="true">+</span>&nbsp; Neue Transkription
  </button>

  <ul class="nav">
    {#each eintraege as e (e.href)}
      <li>
        <a href={e.href} class:aktiv={aktiv(e.href)} aria-current={aktiv(e.href) ? 'page' : undefined}>
          <span class="sym" aria-hidden="true">{e.symbol}</span>{e.text}
        </a>
      </li>
    {/each}
  </ul>

  <div class="raum"></div>

  <StatusBereich />

  <ul class="nav unten">
    {#if verbindung.info?.faehigkeiten.ordner_oeffnen}
      <li>
        <button type="button" onclick={ordnerOeffnen}>
          <span class="sym" aria-hidden="true">📂</span>Ausgabeordner öffnen
        </button>
      </li>
    {/if}
    <li>
      <a
        href="/einstellungen"
        class:aktiv={aktiv('/einstellungen')}
        aria-current={aktiv('/einstellungen') ? 'page' : undefined}
      >
        <span class="sym" aria-hidden="true">⚙</span>Einstellungen
      </a>
    </li>
  </ul>
</nav>

<style>
  .leiste {
    position: fixed;
    inset: 0 auto 0 0;
    width: 250px;
    display: flex;
    flex-direction: column;
    background: var(--sb-bg);
    color: var(--sb-text);
    overflow-y: auto;
    overflow-x: hidden;
    z-index: 10;
  }

  .marke {
    padding: 22px 20px 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .marke img {
    width: 200px;
    height: auto;
    display: block;
  }

  .unter {
    color: var(--sb-muted);
    font-size: 12px;
    letter-spacing: 0.02em;
    padding-left: 2px;
  }

  .neu {
    margin: 22px 14px 14px;
    height: 40px;
    border: none;
    border-radius: 8px;
    background: var(--akzent);
    color: var(--akzent-text);
    font-weight: 600;
    font-size: 14px;
    cursor: pointer;
  }

  .neu:hover {
    background: var(--akzent-hover);
  }

  .neu:focus-visible,
  .nav a:focus-visible,
  .nav button:focus-visible {
    box-shadow: 0 0 0 2px #9cc0ff;
  }

  .nav {
    list-style: none;
    margin: 0;
    padding: 0 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .nav a,
  .nav button {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    height: 38px;
    padding: 0 12px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: var(--sb-text);
    font-size: 14px;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
  }

  .nav a:hover,
  .nav button:hover {
    background: var(--sb-hover);
  }

  .nav a.aktiv {
    background: var(--akzent);
    color: var(--akzent-text);
  }

  .sym {
    width: 20px;
    text-align: center;
    font-size: 15px;
  }

  .raum {
    flex: 1;
    min-height: 16px;
  }

  .unten {
    padding-top: 8px;
    padding-bottom: 14px;
    border-top: 1px solid var(--sb-linie);
  }
</style>
