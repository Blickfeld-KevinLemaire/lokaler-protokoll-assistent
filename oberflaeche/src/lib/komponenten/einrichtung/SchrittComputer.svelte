<script lang="ts">
  /** „Ihr Computer“: je Bereich ein schlichtes Urteil und die Dauer in Worten. */
  import AudioLines from '@lucide/svelte/icons/audio-lines';
  import FileText from '@lucide/svelte/icons/file-text';
  import MessagesSquare from '@lucide/svelte/icons/messages-square';
  import { onMount } from 'svelte';
  import { BEREICHE, dauerText, empfehlungText, schrittFuer, urteil } from '$lib/logik/einrichtung';
  import { einrichtung } from '$lib/stores/einrichtung.svelte';
  import Fortschritt from '../Fortschritt.svelte';
  import Info from '../Info.svelte';

  const SYMBOLE = { transkription: AudioLines, nachbearbeitung: FileText, chatbot: MessagesSquare };

  onMount(() => {
    void einrichtung.rechnerLaden();
  });

  const r = $derived(einrichtung.rechner);
  const profil = $derived((r?.profil ?? {}) as Record<string, unknown>);
  const empfehlung = $derived(empfehlungText(r?.empfehlung));

  /** „32 GB Arbeitsspeicher · Grafikkarte RTX 4060 · 211 GB frei“ */
  const ausstattung = $derived.by(() => {
    const teile: string[] = [];
    const ram = profil.arbeitsspeicher_gb;
    if (typeof ram === 'number') teile.push(`${Math.round(ram)} GB Arbeitsspeicher`);
    const karte = profil.grafikkarte;
    if (typeof karte === 'string' && karte) teile.push(`Grafikkarte ${karte}`);
    const frei = profil.freier_platz_gb;
    if (typeof frei === 'number') teile.push(`${Math.round(frei)} GB frei`);
    return teile.join(' · ');
  });
</script>

{#if !r}
  <div class="laedt" role="status">
    <Fortschritt anteil={null} beschriftung="Computer wird geprüft" />
    <span>Wird geprüft …</span>
  </div>
{:else}
  {#if ausstattung}<p class="ausstattung">{ausstattung}</p>{/if}

  <ul class="karte bereiche">
    {#each BEREICHE as b (b.id)}
      {@const s = schrittFuer(r, b.id)}
      {@const u = urteil(s?.stufe)}
      {@const Symbol = SYMBOLE[b.id]}
      <li>
        <span class="symbol"><Symbol size={20} /></span>
        <span class="name">{b.text}</span>
        <span class="urteil {u.ton}"><span class="punkt" aria-hidden="true"></span>{u.text}</span>
        <span class="dauer">{s && u.ton !== 'online' ? dauerText(s) : ''}</span>
      </li>
    {/each}
  </ul>

  {#if empfehlung}
    <p class="empfehlung">
      <span>Empfehlung: <strong>{empfehlung}</strong></span>
      {#if r.begruendung}
        <Info frage="Warum diese Empfehlung?" text={r.begruendung} />
      {/if}
    </p>
  {/if}
{/if}

<style>
  .laedt {
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 360px;
    color: var(--text-2);
  }

  .ausstattung {
    color: var(--text-2);
    font-size: 13px;
    margin-top: -8px;
  }

  .bereiche {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  li {
    display: grid;
    grid-template-columns: 24px 170px minmax(0, 1fr) auto;
    align-items: center;
    gap: 14px;
    padding: 16px 20px;
    border-top: 1px solid var(--rand);
  }

  li:first-child {
    border-top: none;
  }

  .symbol {
    display: inline-flex;
    color: var(--text-2);
  }

  .name {
    font-weight: 600;
  }

  .urteil {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .punkt {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }

  .gut .punkt {
    background: var(--ok);
  }

  .mittel .punkt {
    background: var(--warn);
  }

  .online .punkt {
    background: var(--akzent);
  }

  .dauer {
    color: var(--text-2);
    font-size: 13px;
    text-align: right;
  }

  .empfehlung {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text-2);
  }

  .empfehlung strong {
    color: var(--text);
    font-weight: 600;
  }
</style>
