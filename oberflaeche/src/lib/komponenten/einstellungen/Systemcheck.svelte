<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import CircleAlert from '@lucide/svelte/icons/circle-alert';
  import CircleX from '@lucide/svelte/icons/circle-x';
  import { api } from '$lib/api/client';
  import type { DiagnosePunkt } from '$lib/api/typen';
  import Erweitert from '../Erweitert.svelte';
  import { dialog } from '$lib/stores/oberflaeche.svelte';

  /** Prüfungen aus `utils/diagnostics.py` mit verständlichen Namen. */
  const NAMEN: Record<string, string> = {
    python_version: 'Programmumgebung',
    windows: 'Betriebssystem',
    torch: 'Rechenumgebung',
    cuda: 'Grafikkarte',
    vram: 'Grafikspeicher',
    ram: 'Arbeitsspeicher',
    disk_space: 'Freier Speicherplatz',
    ffmpeg: 'Audio umwandeln',
    ffprobe: 'Audio lesen',
    whisperx: 'Spracherkennung',
    faster_whisper: 'Spracherkennung',
    whisper: 'Spracherkennung',
    pyannote: 'Sprecher erkennen',
    model_cache: 'Gespeicherte Modelle',
    hf_token: 'Zugang für Sprecher erkennen',
    output_writable: 'Ausgabeordner',
    ollama_installed: 'KI für Zusammenfassungen',
    ollama_running: 'KI erreichbar',
    ollama_model: 'Sprachmodell vorhanden'
  };

  let punkte = $state<DiagnosePunkt[] | null>(null);
  let laeuft = $state(false);

  async function pruefen() {
    laeuft = true;
    try {
      punkte = await api.diagnose();
    } catch (e) {
      dialog.zeigen(e, 'Prüfung nicht möglich');
    } finally {
      laeuft = false;
    }
  }
</script>

<button class="knopf" type="button" disabled={laeuft} onclick={pruefen}>
  {laeuft ? 'Wird geprüft …' : 'Jetzt prüfen'}
</button>

{#if punkte}
  <ul class="liste">
    {#each punkte as p (p.id)}
      <li>
        <span
          class="zeichen"
          class:ok={p.ok}
          class:kritisch={!p.ok && p.kritisch}
          class:hinweis={!p.ok && !p.kritisch}
        >
          {#if p.ok}<Check size={16} />{:else if p.kritisch}<CircleX size={16} />{:else}<CircleAlert
              size={16}
            />{/if}
        </span>
        <span>{NAMEN[p.id] ?? p.name}</span>
      </li>
    {/each}
  </ul>
  <Erweitert titel="Details">
    {#snippet kinder()}
      <pre>{punkte!.map((p) => `${p.ok ? 'OK ' : '-- '} ${p.name}: ${p.text}`).join('\n')}</pre>
    {/snippet}
  </Erweitert>
{/if}

<style>
  .liste {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(2, minmax(220px, 1fr));
    gap: 6px 28px;
    width: 620px;
    max-width: 100%;
  }

  li {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 26px;
  }

  .zeichen {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
  }

  .ok {
    color: var(--ok);
  }

  .kritisch {
    color: var(--fehler);
  }

  .hinweis {
    color: var(--warn);
  }

  pre {
    font-size: 12px;
    white-space: pre-wrap;
    padding: 10px;
    border-radius: 6px;
    background: var(--karte-2);
    max-height: 240px;
    overflow: auto;
  }
</style>
