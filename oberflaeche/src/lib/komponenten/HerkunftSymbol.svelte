<script lang="ts">
  /** Woher ein Auftrag kommt: PC, Aufnahmegerät, Eingangsordner oder andere Nutzer. */
  import Folder from '@lucide/svelte/icons/folder';
  import Monitor from '@lucide/svelte/icons/monitor';
  import Radio from '@lucide/svelte/icons/radio';
  import Users from '@lucide/svelte/icons/users';
  import type { HerkunftArt } from '#lib/logik/warteschlange.ts';

  let { art, groesse = 16 }: { art: HerkunftArt; groesse?: number } = $props();

  const SYMBOLE = { pc: Monitor, geraet: Radio, ordner: Folder, andere: Users };
  const Symbol = $derived(SYMBOLE[art]);
</script>

<Symbol size={groesse} />
