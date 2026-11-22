<script lang="ts">
  import type { Snippet } from 'svelte';
  import Datenschutz from './Datenschutz.svelte';

  let { titel, aktionen }: { titel: string; aktionen?: Snippet } = $props();
</script>

<svelte:head><title>{titel} · VERMERK</title></svelte:head>

<header class="kopf">
  <h1>{titel}</h1>
  <div class="rechts">
    {@render aktionen?.()}
    <Datenschutz />
  </div>
</header>

<style>
  .kopf {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    min-height: 40px;
    margin-bottom: 20px;
  }

  .rechts {
    display: flex;
    align-items: center;
    gap: 10px;
  }
</style>
