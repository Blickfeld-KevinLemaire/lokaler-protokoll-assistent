<script lang="ts">
  import type { Segment } from '#lib/api/typen.ts';
  import { zeitmarke } from '#lib/logik/format.ts';
  import { transkriptBloecke } from '#lib/logik/transkript.ts';

  let { segmente }: { segmente: Segment[] } = $props();

  /** Aufeinanderfolgende Stücke derselben Person zusammenfassen – liest sich wie ein Gespräch. */
  const bloecke = $derived(transkriptBloecke(segmente));

  const FARBEN = 6;
  const reihenfolge = $derived([...new Set(bloecke.map((b) => b.id))]);
</script>

{#if bloecke.length === 0}
  <div class="leer">Kein Text vorhanden</div>
{:else}
  <div class="transkript karte">
    {#each bloecke as b, i (i)}
      <div class="block">
        <div class="meta">
          {#if b.sprecher}
            <span class="sprecher" style:color="var(--sp{reihenfolge.indexOf(b.id) % FARBEN})">
              {b.sprecher}
            </span>
          {/if}
          <span class="zeit">{zeitmarke(b.start)}</span>
        </div>
        <p>{b.text.trim()}</p>
      </div>
    {/each}
  </div>
{/if}

<style>
  .transkript {
    padding: 8px 22px;
  }

  .block {
    display: grid;
    grid-template-columns: 150px minmax(0, 1fr);
    gap: 16px;
    padding: 12px 0;
    border-top: 1px solid var(--rand);
  }

  .block:first-child {
    border-top: none;
  }

  .meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .sprecher {
    font-weight: 600;
    font-size: 13px;
  }

  .zeit {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  p {
    line-height: 1.6;
  }
</style>
