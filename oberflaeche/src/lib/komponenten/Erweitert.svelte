<script lang="ts">
  /** Aufklappbereich für Seltenes und Technisches. */
  import type { Snippet } from 'svelte';

  let { titel = 'Erweitert', kinder }: { titel?: string; kinder: Snippet } = $props();
</script>

<details class="erweitert">
  <summary>{titel}</summary>
  <div class="inhalt">{@render kinder()}</div>
</details>

<style>
  .erweitert {
    margin-top: 6px;
  }

  summary {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 0;
    color: var(--text-2);
    font-size: 13px;
    cursor: pointer;
    list-style: none;
    border-radius: 4px;
  }

  summary::-webkit-details-marker {
    display: none;
  }

  summary::before {
    content: '▸';
    font-size: 11px;
    transition: transform 0.15s;
  }

  details[open] summary::before {
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
