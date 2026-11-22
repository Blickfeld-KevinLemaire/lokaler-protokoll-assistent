<script lang="ts">
  /** Aufklappbereich für Seltenes und Technisches. */
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import type { Snippet } from 'svelte';

  let { titel = 'Erweitert', kinder }: { titel?: string; kinder: Snippet } = $props();
</script>

<details class="erweitert">
  <summary><span class="pfeil"><ChevronRight size={16} /></span>{titel}</summary>
  <div class="inhalt">{@render kinder()}</div>
</details>

<style>
  .erweitert {
    margin-top: 6px;
  }

  summary {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-height: 28px;
    padding: 4px 6px 4px 0;
    color: var(--text-2);
    font-size: 13px;
    cursor: pointer;
    list-style: none;
    border-radius: 4px;
  }

  summary::-webkit-details-marker {
    display: none;
  }

  summary::marker {
    content: '';
  }

  .pfeil {
    display: inline-flex;
    margin-left: -2px;
    transition: transform 0.15s ease-out;
  }

  details[open] .pfeil {
    transform: rotate(90deg);
  }

  summary:hover {
    color: var(--text);
  }

  .inhalt {
    padding: 10px 0 4px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
</style>
