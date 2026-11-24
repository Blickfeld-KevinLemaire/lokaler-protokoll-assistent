<script lang="ts">
  /** Nutzer anlegen, bearbeiten, entfernen (nur Verwaltung, Servermodus). */
  import Plus from '@lucide/svelte/icons/plus';
  import X from '@lucide/svelte/icons/x';
  import { api } from '#lib/api/client.ts';
  import type { NeuerZugang, Nutzer } from '#lib/api/typen.ts';
  import { dialog, meldungen, rueckfrage } from '#lib/stores/oberflaeche.svelte.ts';
  import { personen } from '#lib/stores/personen.svelte.ts';
  import { verbindung } from '#lib/stores/verbindung.svelte.ts';
  import Dialog from '../Dialog.svelte';
  import Info from '../Info.svelte';
  import Schalter from '../Schalter.svelte';
  import SchluesselEinmal from './SchluesselEinmal.svelte';

  let liste = $state<Nutzer[]>([]);
  let neuOffen = $state(false);
  let neu = $state({ name: '', anzeigename: '', passwort: '', admin: false });
  let bearbeiten = $state<Nutzer | null>(null);
  let form = $state({ anzeigename: '', admin: false, aktiv: true, passwort: '' });
  let bezeichnung = $state('');
  let neuerZugang = $state<NeuerZugang | null>(null);

  async function laden() {
    try {
      liste = await api.nutzer();
      if (bearbeiten) bearbeiten = liste.find((n) => n.name === bearbeiten!.name) ?? null;
    } catch (e) {
      console.warn('Nutzer nicht geladen', e);
    }
  }

  $effect(() => {
    void verbindung.runde;
    if (verbindung.bereit) void laden();
  });

  function oeffnen(n: Nutzer) {
    bearbeiten = n;
    form = { anzeigename: n.anzeigename, admin: n.admin, aktiv: n.aktiv !== false, passwort: '' };
    bezeichnung = '';
  }

  async function anlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      await api.nutzerAnlegen({
        name: neu.name.trim(),
        anzeigename: neu.anzeigename.trim(),
        admin: neu.admin,
        passwort: neu.passwort || null
      });
      neu = { name: '', anzeigename: '', passwort: '', admin: false };
      neuOffen = false;
      void personen.laden(true);
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Nutzer nicht angelegt');
    }
  }

  async function speichern() {
    if (!bearbeiten) return;
    try {
      await api.nutzerAendern(bearbeiten.name, {
        anzeigename: form.anzeigename.trim(),
        admin: form.admin,
        aktiv: form.aktiv,
        ...(form.passwort ? { passwort: form.passwort } : {})
      });
      meldungen.zeigen('Gespeichert');
      bearbeiten = null;
      void personen.laden(true);
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Speichern hat nicht geklappt');
    }
  }

  async function entfernen(n: Nutzer) {
    const ja = await rueckfrage.fragen({
      titel: `„${n.anzeigename}“ entfernen?`,
      text: 'Die Transkripte bleiben auf dem Server erhalten.',
      verb: 'Entfernen'
    });
    if (!ja) return;
    try {
      await api.nutzerEntfernen(n.name);
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Entfernen hat nicht geklappt');
    }
  }

  async function zugangAnlegen(e: SubmitEvent) {
    e.preventDefault();
    if (!bearbeiten) return;
    try {
      neuerZugang = await api.nutzerZugang(bearbeiten.name, bezeichnung.trim());
      bezeichnung = '';
      await laden();
    } catch (f) {
      dialog.zeigen(f, 'Schlüssel nicht angelegt');
    }
  }

  async function zugangEntfernen(name: string) {
    if (!bearbeiten) return;
    const ja = await rueckfrage.fragen({ titel: `Zugangsschlüssel „${name}“ entfernen?`, verb: 'Entfernen' });
    if (!ja) return;
    try {
      await api.nutzerZugangEntfernen(bearbeiten.name, name);
      await laden();
    } catch (f) {
      dialog.zeigen(f);
    }
  }

  const ich = $derived((verbindung.info?.angemeldet_als ?? '').toLowerCase());
</script>

<div class="nutzer">
  <ul class="liste">
    {#each liste as n (n.name)}
      <li class:inaktiv={n.aktiv === false}>
        <span class="avatar" aria-hidden="true">{n.anzeigename.slice(0, 1)}</span>
        <div class="text">
          <div class="name">
            {n.anzeigename}
            {#if n.admin}<span class="marke">Verwaltung</span>{/if}
            {#if n.aktiv === false}<span class="marke aus">Gesperrt</span>{/if}
          </div>
          <div class="leise klein">{n.name}</div>
        </div>
        <button class="knopf leise" type="button" onclick={() => oeffnen(n)}>Bearbeiten</button>
        <button
          class="symbolknopf"
          type="button"
          aria-label="{n.anzeigename} entfernen"
          title="Entfernen"
          disabled={n.name.toLowerCase() === ich}
          onclick={() => entfernen(n)}
        >
          <X size={16} />
        </button>
      </li>
    {/each}
  </ul>
  <div>
    <button class="knopf" type="button" onclick={() => (neuOffen = true)}>
      <Plus size={16} /> Nutzer anlegen
    </button>
  </div>
</div>

<Dialog offen={neuOffen} titel="Nutzer anlegen" schliessen={() => (neuOffen = false)}>
  {#snippet kinder()}
    <form id="nutzer-neu" class="formular" onsubmit={anlegen}>
      <label class="feldzeile">
        <span>Anmeldename</span><input class="feld" maxlength="32" autocomplete="off" bind:value={neu.name} />
      </label>
      <label class="feldzeile">
        <span>Anzeigename</span><input class="feld" maxlength="80" bind:value={neu.anzeigename} />
      </label>
      <label class="feldzeile">
        <span>Passwort</span><input
          class="feld"
          type="password"
          autocomplete="new-password"
          bind:value={neu.passwort}
        />
      </label>
      <Schalter bind:an={neu.admin} beschriftung="Darf verwalten">
        {#snippet info()}
          <Info
            frage="Was bedeutet verwalten?"
            text="Ändert Einstellungen, legt Nutzer und Geräte an. Alle anderen sehen nur ihre eigenen Transkripte."
          />
        {/snippet}
      </Schalter>
    </form>
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf" type="button" onclick={() => (neuOffen = false)}>Abbrechen</button>
    <button class="knopf primaer" type="submit" form="nutzer-neu" disabled={!neu.name.trim()}>Anlegen</button>
  {/snippet}
</Dialog>

<Dialog
  offen={!!bearbeiten}
  titel={bearbeiten?.anzeigename ?? ''}
  schliessen={() => (bearbeiten = null)}
  breite={480}
>
  {#snippet kinder()}
    <div class="formular">
      <label class="feldzeile">
        <span>Anzeigename</span><input class="feld" maxlength="80" bind:value={form.anzeigename} />
      </label>
      <label class="feldzeile">
        <span>Neues Passwort</span><input
          class="feld"
          type="password"
          autocomplete="new-password"
          placeholder="Unverändert lassen"
          bind:value={form.passwort}
        />
      </label>
      <Schalter
        bind:an={form.admin}
        beschriftung="Darf verwalten"
        deaktiviert={bearbeiten?.name.toLowerCase() === ich}
      />
      <Schalter
        bind:an={form.aktiv}
        beschriftung="Darf sich anmelden"
        deaktiviert={bearbeiten?.name.toLowerCase() === ich}
      />
      <div class="feldzeile">
        <span>Zugangsschlüssel</span>
        {#each bearbeiten?.zugaenge ?? [] as z (z.bezeichnung)}
          <div class="zeile z">
            <span class="z-name">{z.bezeichnung}</span>
            <button
              class="symbolknopf"
              type="button"
              aria-label="{z.bezeichnung} entfernen"
              onclick={() => zugangEntfernen(z.bezeichnung)}
            >
              <X size={16} />
            </button>
          </div>
        {/each}
        <form class="zeile" onsubmit={zugangAnlegen}>
          <input
            class="feld"
            placeholder="Bezeichnung"
            aria-label="Bezeichnung"
            maxlength="60"
            bind:value={bezeichnung}
          />
          <button class="knopf" type="submit" disabled={!bezeichnung.trim()}>+&nbsp; Neu</button>
        </form>
      </div>
    </div>
  {/snippet}
  {#snippet knoepfe()}
    <button class="knopf" type="button" onclick={() => (bearbeiten = null)}>Abbrechen</button>
    <button class="knopf primaer" type="button" onclick={speichern}>Speichern</button>
  {/snippet}
</Dialog>

<SchluesselEinmal zugang={neuerZugang} schliessen={() => (neuerZugang = null)} />

<style>
  .nutzer {
    width: 620px;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .liste {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--rand);
    border-radius: var(--radius);
    overflow: hidden;
  }

  li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px 10px 14px;
    border-top: 1px solid var(--rand);
  }

  li:first-child {
    border-top: none;
  }

  li.inaktiv .text {
    opacity: 0.55;
  }

  .avatar {
    flex: none;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--akzent-weich);
    color: var(--link);
    font-weight: 600;
    text-transform: uppercase;
  }

  .text {
    flex: 1;
    min-width: 0;
  }

  .name {
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .marke {
    font-size: 11.5px;
    font-weight: 600;
    padding: 1px 8px;
    border-radius: 9px;
    background: var(--akzent-weich);
    color: var(--link);
  }

  .marke.aus {
    background: var(--warn-weich);
    color: var(--warn);
  }

  .formular {
    display: flex;
    flex-direction: column;
    gap: 12px;
    color: var(--text);
  }

  .feldzeile {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .feldzeile > span {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }

  .z-name {
    flex: 1;
  }
</style>
