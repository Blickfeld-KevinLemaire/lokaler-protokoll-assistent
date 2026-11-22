<script lang="ts">
  import type { Snippet } from 'svelte';

  let { id, titel, kinder }: { id: string; titel: string; kinder: Snippet } = $props();
</script>

<section class="karte abschnitt" {id} aria-labelledby="{id}-titel">
  <h2 id="{id}-titel">{titel}</h2>
  <div class="inhalt">{@render kinder()}</div>
</section>

<style>
  .abschnitt {
    padding: 20px 22px;
    scroll-margin-top: 20px;
  }

  h2 {
    margin-bottom: 14px;
  }

  .inhalt {
    display: flex;
    flex-direction: column;
    gap: 14px;
    align-items: flex-start;
  }

  .inhalt > :global(*) {
    max-width: 100%;
  }
</style>
