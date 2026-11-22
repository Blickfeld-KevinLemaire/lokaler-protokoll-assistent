fn main() {
    // Nur diese beiden Befehle kennt die Webseite. Prozesssteuerung (Dienst
    // starten/stoppen) ist absichtlich KEIN Befehl (ARCHITEKTUR.md, Regeln).
    // Tauri erzeugt daraus die Berechtigungen 'allow-zugang' und
    // 'allow-protokoll-schreiben', die 'capabilities/default.json' freigibt.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["zugang", "protokoll_schreiben"]),
    ))
    .expect("tauri-build fehlgeschlagen");
}
