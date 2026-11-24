<script lang="ts">
  import FolderOpen from '@lucide/svelte/icons/folder-open';
  import Files from '@lucide/svelte/icons/files';
  import MessagesSquare from '@lucide/svelte/icons/messages-square';
  import Mic from '@lucide/svelte/icons/mic';
  import Plus from '@lucide/svelte/icons/plus';
  import Radio from '@lucide/svelte/icons/radio';
  import Settings from '@lucide/svelte/icons/settings';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api } from '#lib/api/client.ts';
  import { KUERZEL_TEXT } from '#lib/logik/tasten.ts';
  import { dialog } from '#lib/stores/oberflaeche.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import StatusBereich from './StatusBereich.svelte';

  const eintraege = [
    { href: '/', symbol: Mic, text: 'Transkription' },
    { href: '/besprechungen', symbol: Files, text: 'Transkripte' },
    { href: '/chat', symbol: MessagesSquare, text: 'Frag mein Meeting' },
    { href: '/raum', symbol: Radio, text: 'VERMERK Raum' }
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

  <button
    class="neu"
    type="button"
    title="Neue Transkription ({KUERZEL_TEXT.neu})"
    onclick={() => goto('/?neu=1')}
  >
    <Plus size={18} strokeWidth={2} /> Neue Transkription
  </button>

  <ul class="nav">
    {#each eintraege as e (e.href)}
      <li>
        <a href={e.href} class:aktiv={aktiv(e.href)} aria-current={aktiv(e.href) ? 'page' : undefined}>
          <e.symbol />{e.text}
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
          <FolderOpen />Ausgabeordner öffnen
        </button>
      </li>
    {/if}
    {#if verbindung.mehrbenutzer && verbindung.info}
      <li>
        <a href="/einstellungen#konto" title="Konto">
          <span class="avatar" aria-hidden="true">
            {verbindung.info.anzeigename.slice(0, 1)}
          </span>{verbindung.info.anzeigename}
        </a>
      </li>
    {/if}
    <li>
      <a
        href="/einstellungen"
        title="Einstellungen ({KUERZEL_TEXT.einstellungen})"
        class:aktiv={aktiv('/einstellungen')}
        aria-current={aktiv('/einstellungen') ? 'page' : undefined}
      >
        <Settings />Einstellungen
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
    border-right: 1px solid var(--sb-rand);
    color: var(--sb-text);
    --fokus-farbe: var(--sb-fokus);
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
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin: 24px 14px 16px;
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
    gap: 12px;
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

  .nav a :global(.lucide-icon),
  .nav button :global(.lucide-icon) {
    opacity: 0.9;
  }

  .avatar {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.14);
    font-size: 12px;
    font-weight: 600;
    line-height: 22px;
    text-transform: uppercase;
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
