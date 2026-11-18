// Wiederverwendbare Bausteine: App-Fenster, Transkript, Protokoll, Gerät.
// Alle Inhalte sind ein erfundenes Beispiel (Projektbesprechung "Relaunch Website").

const NAV = [["🎙", "Transkription"], ["👥", "Ergebnis und Sprecher"], ["📝", "Nachbearbeitung"], ["💬", "Frag mein Meeting"]];

function fenster(aktiv, titel, unter, inhalt) {
  const nav = NAV.map(([s, t], i) => `<div class="nav ${i === aktiv ? "aktiv" : ""}">${s}&nbsp;&nbsp; ${t}</div>`).join("");
  return `
  <div class="fenster">
    <div class="titelzeile"><img src="icon_dunkel.svg">VERMERK Desktop<div class="knoepfe"><span>—</span><span>☐</span><span>✕</span></div></div>
    <div class="fenster-koerper">
      <div class="seitenleiste">
        <img class="logo" src="logo_hell.svg"><div class="unter">Desktop</div>
        <div class="primaer">+&nbsp; Neue Transkription</div>
        ${nav}
        <div class="abstand"></div>
        <div class="nav">📂&nbsp;&nbsp; Ausgabeordner öffnen</div>
        <div class="nav">⚙&nbsp;&nbsp; Einstellungen</div>
      </div>
      <div class="inhalt">
        <div class="seitentitel">${titel}</div>
        <div class="seitenunter">${unter}</div>
        <div class="datenschutz">🔒 Die Verarbeitung erfolgt vollständig lokal auf diesem Computer. Es werden keine Audio- oder Videodaten übertragen.</div>
        ${inhalt}
      </div>
    </div>
  </div>`;
}

function welle(n = 48) {
  let s = "";
  for (let i = 0; i < n; i++) {
    const v = (Math.sin(i * 1.7) * 0.5 + 0.5) * 0.6 + 0.4;
    s += `<i style="animation-delay:${(-i * 0.11 - (i % 5) * 0.07).toFixed(2)}s;animation-duration:${(0.55 + v * 0.5).toFixed(2)}s"></i>`;
  }
  return `<div class="welle">${s}</div>`;
}

function aufnahmeSeite() {
  return fenster(0, "Transkription", "Aufnahme oder Datei auswählen und in Text umwandeln.", `
    <div class="karte">
      <h4>Mikrofon-Aufnahme</h4>
      <div class="aufnahme-kopf"><span class="punkt"></span>Aufnahme läuft · Konferenzmikrofon<span class="uhr" data-uhr="2520" data-start="0">42:00</span></div>
      ${welle()}
      <div class="knopfzeile"><span class="knopf">⏸ Pause</span><span class="knopf rot">■ Aufnahme beenden</span></div>
    </div>
    <div class="karte" style="display:flex;align-items:center;gap:14px;color:var(--grau)">
      <span style="font-size:26px">⇪</span> oder eine Audio- bzw. Videodatei hierher ziehen (MP3, WAV, M4A, MP4 …)
    </div>`);
}

const TRANSKRIPT = [
  ["00:00:12", 1, "Anna", "Lasst uns mit dem Zeitplan für den Relaunch anfangen."],
  ["00:00:19", 2, "Murat", "Die Server-Umstellung schaffen wir bis Ende März."],
  ["00:00:27", 3, "Sabine", "Dann brauche ich die Texte spätestens am 15. März."],
  ["00:00:34", 1, "Anna", "Gut, dann halten wir den 1. April als Go-live fest."],
  ["00:00:41", 2, "Murat", "Ich plane vorher noch einen Lasttest ein."],
];

function transkriptZeilen(start = 0, schritt = 0.45) {
  return TRANSKRIPT.map(([z, s, n, t], i) =>
    `<div class="zeile ein" style="--d:${(start + i * schritt).toFixed(2)}s"><span class="zeit">${z}</span><span><span class="sprecher sp${s}">${n}:</span>${t}</span></div>`).join("");
}

function sprecherSeite(start = 0) {
  return fenster(1, "Ergebnis und Sprecher", "Vorschau ansehen, Sprecher benennen, Stimmen anhören.", `
    <div class="karte" style="padding:12px 18px">
      <div style="display:flex;justify-content:space-between;font-size:13px;color:var(--grau);margin-bottom:8px"><span>Transkription mit Sprechertrennung</span><span>fertig ✓</span></div>
      <div class="fortschritt"><b style="animation-delay:${start}s"></b></div>
    </div>
    <div class="karte" style="padding:6px 18px">${transkriptZeilen(start + 0.4)}</div>
    <div class="sprecherliste ein" style="--d:${start + 2.8}s">
      <span class="sp1">● Anna</span><span class="sp2">● Murat</span><span class="sp3">● Sabine</span>
    </div>`);
}

const AUFGABEN = [["Server-Umstellung und Lasttest", "Murat", "31.03."], ["Texte für die neuen Seiten liefern", "Sabine", "15.03."], ["Abnahme mit der Geschäftsführung", "Anna", "25.03."]];

function protokoll(start = 0) {
  const a = AUFGABEN.map(([t, w, b], i) =>
    `<div class="aufgabe ein" style="--d:${(start + 1.3 + i * 0.35).toFixed(2)}s"><span class="kasten"></span><span>${t}</span><span class="wer">${w}</span><span class="bis">${b}</span></div>`).join("");
  return `
  <div class="dokument">
    <div class="kopf">
      <div><h2>Protokoll: Relaunch Website</h2><div class="meta">Projektbesprechung · 12.11.2026 · Anna, Murat, Sabine</div></div>
      <span class="word">W&nbsp; Word-Export</span>
    </div>
    <h3 class="ein" style="--d:${start + 0.3}s">Zusammenfassung</h3>
    <p class="ein" style="--d:${start + 0.45}s">Der Relaunch geht am 1. April live. Die Server-Umstellung läuft bis Ende März, die Texte kommen bis Mitte März.</p>
    <h3 class="ein" style="--d:${start + 1.1}s">Aufgaben</h3>
    ${a}
  </div>`;
}

function geraet(innen) {
  return `<div class="geraet"><div class="schirm">${innen}</div></div>`;
}

const HAKEN = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M7 12.5l3.2 3.2L17 9"/></svg>`;

// Zeit gezielt setzen: alle Animationen pausieren und auf t Sekunden stellen; Uhren mitzählen.
window.setzeZeit = function (t) {
  document.getAnimations().forEach((a) => { a.pause(); a.currentTime = t * 1000; });
  document.querySelectorAll("[data-uhr]").forEach((el) => {
    const s = Math.max(0, Number(el.dataset.uhr) + (t - Number(el.dataset.start)) * Number(el.dataset.tempo || 1));
    const m = Math.floor(s / 60), sek = Math.floor(s % 60);
    el.textContent = `${String(m).padStart(2, "0")}:${String(sek).padStart(2, "0")}`;
  });
};
