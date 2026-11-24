<script lang="ts">
  /** Die eine Rückfrage der Oberfläche (siehe `rueckfrage` in stores/oberflaeche.svelte.ts). */
  import { rueckfrage } from '$lib/stores/oberflaeche.svelte';
  import Bestaetigen from './Bestaetigen.svelte';

  const f = $derived(rueckfrage.frage);
  let bestaetigt = false;
</script>

<Bestaetigen
  offen={!!f}
  titel={f?.titel ?? ''}
  text={f?.text ?? ''}
  verb={f?.verb ?? 'OK'}
  bestaetigen={() => {
    bestaetigt = true;
  }}
  schliessen={() => {
    rueckfrage.antworten_(bestaetigt);
    bestaetigt = false;
  }}
/>
