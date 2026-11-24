<script lang="ts">
  /** Kleines Abzeichen im Seitenkopf: alles auf diesem Computer oder (teilweise) über einen Online-Dienst. */
  import Cloud from '@lucide/svelte/icons/cloud';
  import Lock from '@lucide/svelte/icons/lock';
  import { einstellungen } from '#lib/stores/einstellungen.svelte.ts';
  import Info from './Info.svelte';

  const w = $derived(einstellungen.werte);
  const online = $derived.by(() => {
    if (!w) return [] as string[];
    const liste: string[] = [];
    if (w.transkription_modus === 'api') liste.push('die Aufnahme');
    if (w.nachbearbeitung_modus === 'api') liste.push('der Text für die Zusammenfassung');
    if (w.chatbot_modus === 'api') liste.push('Ihre Fragen an das Meeting');
    return liste;
  });

  function aufzaehlen(teile: string[]): string {
    if (teile.length <= 1) return teile.join('');
    return `${teile.slice(0, -1).join(', ')} und ${teile.at(-1)}`;
  }
</script>

{#if w}
  {#if online.length === 0}
    <span class="abzeichen lokal">
      <Lock size={14} strokeWidth={2} /> Lokal
      <Info
        frage="Was bedeutet Lokal?"
        text="Aufnahmen und Texte bleiben auf diesem Computer. Nichts wird an einen Online-Dienst geschickt."
      />
    </span>
  {:else}
    <span class="abzeichen online">
      <Cloud size={14} strokeWidth={2} /> Online-Dienst
      <Info
        frage="Was verlässt den Computer?"
        text={`An den gewählten Online-Dienst geht ${aufzaehlen(online)}. Alles andere bleibt hier.`}
      />
    </span>
  {/if}
{/if}

<style>
  .abzeichen {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 8px 0 10px;
    border-radius: 14px;
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
  }

  .lokal {
    background: var(--ok-weich);
    color: var(--ok);
  }

  .online {
    background: var(--warn-weich);
    color: var(--warn);
  }
</style>
