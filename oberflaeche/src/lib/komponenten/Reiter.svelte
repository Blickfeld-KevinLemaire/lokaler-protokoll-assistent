<script lang="ts">
  /** Reiterleiste mit Pfeiltasten-Bedienung. */
  let {
    reiter,
    aktiv = $bindable(),
    beschriftung
  }: { reiter: { id: string; text: string }[]; aktiv: string; beschriftung: string } = $props();

  let leiste: HTMLDivElement | undefined = $state();

  function taste(e: KeyboardEvent, index: number) {
    let ziel = -1;
    if (e.key === 'ArrowRight') ziel = (index + 1) % reiter.length;
    else if (e.key === 'ArrowLeft') ziel = (index - 1 + reiter.length) % reiter.length;
    else if (e.key === 'Home') ziel = 0;
    else if (e.key === 'End') ziel = reiter.length - 1;
    if (ziel < 0) return;
    e.preventDefault();
    aktiv = reiter[ziel]!.id;
    leiste?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[ziel]?.focus();
  }
</script>

<div class="reiter" role="tablist" aria-label={beschriftung} bind:this={leiste}>
  {#each reiter as r, i (r.id)}
    <button
      type="button"
      role="tab"
      id="reiter-{r.id}"
      aria-selected={aktiv === r.id}
      aria-controls="tafel-{r.id}"
      tabindex={aktiv === r.id ? 0 : -1}
      onclick={() => (aktiv = r.id)}
      onkeydown={(e) => taste(e, i)}
    >
      {r.text}
    </button>
  {/each}
</div>

<style>
  .reiter {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--rand);
    margin-bottom: 18px;
  }

  button {
    position: relative;
    height: 38px;
    padding: 0 14px;
    border: none;
    background: transparent;
    color: var(--text-2);
    font-weight: 500;
    cursor: pointer;
    border-radius: 6px 6px 0 0;
  }

  button:hover {
    color: var(--text);
  }

  button[aria-selected='true'] {
    color: var(--link);
  }

  button[aria-selected='true']::after {
    content: '';
    position: absolute;
    left: 10px;
    right: 10px;
    bottom: -1px;
    height: 2px;
    border-radius: 2px;
    background: var(--akzent);
  }
</style>
