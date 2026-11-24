<script lang="ts">
  /**
   * Die ganze Warteschlange unter dem Start: was gerade läuft (mit Fortschritt und Text), darunter alles, was
   * wartet, in der Reihenfolge, in der es drankommt. Ein eigener, schon fertiger Auftrag bleibt oben stehen,
   * bis er geschlossen wird (dort gibt es „Öffnen“).
   */
  import X from '@lucide/svelte/icons/x';
  import { api } from '#lib/api/client.ts';
  import type { Auftrag } from '#lib/api/typen.ts';
  import { ERLEDIGT, auftragTitel, herkunftAnzeigen } from '#lib/logik/warteschlange.ts';
  import { dialog } from '#lib/stores/oberflaeche.svelte.ts';
  import { zustand } from '#lib/stores/zustand.svelte.ts';
  import AuftragKarte from '../AuftragKarte.svelte';
  import HerkunftSymbol from '../HerkunftSymbol.svelte';

  let { meinAuftrag, schliessen }: { meinAuftrag: Auftrag | null; schliessen: () => void } = $props();

  const laufend = $derived(zustand.lage.laufend);
  const wartend = $derived(zustand.lage.wartend);
  const meinFertig = $derived(meinAuftrag && ERLEDIGT.has(meinAuftrag.status) ? meinAuftrag : null);

  async function abbrechen(a: Auftrag) {
    try {
      await api.auftragAbbrechen(a.id);
    } catch (e) {
      dialog.zeigen(e, 'Abbrechen hat nicht geklappt');
    }
  }
</script>

{#if meinFertig || laufend || wartend.length}
  <div class="reihe">
    {#if meinFertig}
      <AuftragKarte auftrag={meinFertig} {schliessen} />
    {/if}
    {#if laufend}
      <AuftragKarte auftrag={laufend} />
    {/if}
    {#if wartend.length}
      <section aria-labelledby="wartet-titel">
        <h2 id="wartet-titel">Danach</h2>
        <ol class="karte">
          {#each wartend as a, i (a.id)}
            {@const h = herkunftAnzeigen(a.herkunft)}
            <li class:meins={a.id === meinAuftrag?.id}>
              <span class="platz" title="Platz {i + 1 + (laufend ? 1 : 0)}">{i + 1 + (laufend ? 1 : 0)}</span>
              <span class="symbol" title={h.text}><HerkunftSymbol art={h.art} /></span>
              <span class="titel" title={auftragTitel(a)}>{auftragTitel(a)}</span>
              {#if !a.fremd}
                <button
                  class="symbolknopf"
                  type="button"
                  aria-label="{auftragTitel(a)} aus der Warteschlange nehmen"
                  title="Aus der Warteschlange nehmen"
                  onclick={() => abbrechen(a)}
                >
                  <X size={16} />
                </button>
              {/if}
            </li>
          {/each}
        </ol>
      </section>
    {/if}
  </div>
{/if}

<style>
  .reihe {
    margin-top: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  h2 {
    font-size: 13px;
    color: var(--text-2);
    font-weight: 600;
    margin-bottom: 8px;
  }

  ol {
    list-style: none;
    margin: 0;
    padding: 4px;
  }

  li {
    display: grid;
    grid-template-columns: 24px 20px minmax(0, 1fr) auto;
    gap: 12px;
    align-items: center;
    min-height: 44px;
    padding: 4px 8px 4px 12px;
    border-radius: 7px;
  }

  li + li {
    border-top: 1px solid var(--rand);
  }

  li.meins {
    background: var(--akzent-weich);
  }

  .platz {
    font-variant-numeric: tabular-nums;
    color: var(--text-2);
    font-size: 13px;
    text-align: right;
  }

  .symbol {
    display: inline-flex;
    color: var(--text-2);
  }

  .titel {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
