//! Integrationstest mit dem ECHTEN Python-Dienst: Start mit `--port 0`,
//! Handschlag ueber die Portdatei, Identitaetspruefung, Beenden.
//!
//! Standardmaessig uebersprungen (braucht Python mit den Paketen aus
//! `uv sync`). Ausfuehren aus `oberflaeche/src-tauri`:
//!
//! ```powershell
//! uv sync                       # einmal, in der Projektwurzel
//! cargo test -- --ignored       # nimmt ..\..\.venv\Scripts\python.exe
//! $env:VERMERK_PYTHON = "C:\pfad\python.exe"; cargo test -- --ignored
//! ```

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use vermerk_lib::dienst_pfad::{quellprojekt_zur_bauzeit, DienstQuelle};
use vermerk_lib::http::get_status;
use vermerk_lib::ueberwachung::{
    DienstStatus, Einstellungen, Melder, Ueberwachung, Zeiten, Zustand,
};

fn python() -> PathBuf {
    if let Ok(p) = std::env::var("VERMERK_PYTHON") {
        return PathBuf::from(p);
    }
    let projekt = quellprojekt_zur_bauzeit();
    let venv = if cfg!(windows) {
        projekt.join(".venv").join("Scripts").join("python.exe")
    } else {
        projekt.join(".venv").join("bin").join("python")
    };
    assert!(
        venv.is_file(),
        "{} fehlt – erst 'uv sync' ausfuehren oder VERMERK_PYTHON setzen",
        venv.display()
    );
    venv
}

fn starten(name: &str) -> (Arc<Ueberwachung>, Arc<Mutex<Vec<DienstStatus>>>, PathBuf) {
    let ordner = std::env::temp_dir().join(format!(
        "vermerk-integration-{name}-{}",
        vermerk_lib::schluessel::kennung(4)
    ));
    let liste = Arc::new(Mutex::new(Vec::new()));
    let l = Arc::clone(&liste);
    let melder: Melder = Arc::new(move |s: &DienstStatus| l.lock().unwrap().push(s.clone()));
    let u = Ueberwachung::starten(
        Einstellungen {
            quelle: DienstQuelle::Quelltext {
                python: python(),
                projekt: quellprojekt_zur_bauzeit(),
            },
            schluessel: vermerk_lib::schluessel::erzeugen().unwrap(),
            laufzeit_ordner: ordner.join("laufzeit"),
            dienst_log: Some(ordner.join("dienst.log")),
            eigene_version: env!("CARGO_PKG_VERSION").to_string(),
            zeiten: Zeiten::default(),
        },
        melder,
    );
    (u, liste, ordner)
}

fn port_aus(basis_url: &str) -> u16 {
    basis_url
        .rsplit(':')
        .next()
        .and_then(|p| p.parse().ok())
        .expect("Basis-URL ohne Port")
}

#[test]
#[ignore = "startet den echten Python-Dienst; mit 'cargo test -- --ignored' ausfuehren"]
fn echter_dienst_handschlag_identitaet_und_ende() {
    let (a, ereignisse_a, ordner_a) = starten("a");
    let (b, _ereignisse_b, ordner_b) = starten("b");
    let zugang_a = a
        .zugang_warten(Duration::from_secs(120))
        .unwrap_or_else(|f| {
            panic!(
                "{f}\nDienst-Protokoll: {}",
                ordner_a.join("dienst.log").display()
            )
        });
    let zugang_b = b
        .zugang_warten(Duration::from_secs(120))
        .unwrap_or_else(|f| {
            panic!(
                "{f}\nDienst-Protokoll: {}",
                ordner_b.join("dienst.log").display()
            )
        });
    let port_a = port_aus(&zugang_a.basis_url);
    let port_b = port_aus(&zugang_b.basis_url);
    assert_ne!(port_a, port_b, "zwei Dienste, zwei Ports");

    let t = Duration::from_secs(5);
    assert_eq!(get_status(port_a, "/api/gesundheit", None, t), Ok(200));
    assert_eq!(get_status(port_a, "/api/info", None, t), Ok(401));
    assert_eq!(
        get_status(port_a, "/api/info", Some(&zugang_a.schluessel), t),
        Ok(200)
    );
    // Der Schluessel des einen Dienstes passt nicht zum anderen.
    assert_eq!(
        get_status(port_b, "/api/info", Some(&zugang_a.schluessel), t),
        Ok(401)
    );
    assert_eq!(
        get_status(port_b, "/api/info", Some(&zugang_b.schluessel), t),
        Ok(200)
    );

    let zustaende: Vec<Zustand> = ereignisse_a
        .lock()
        .unwrap()
        .iter()
        .map(|s| s.zustand)
        .collect();
    assert_eq!(zustaende, [Zustand::Startet, Zustand::Bereit]);
    assert_eq!(
        a.status().basis_url.as_deref(),
        Some(zugang_a.basis_url.as_str())
    );

    a.beenden();
    b.beenden();
    // Nach dem Beenden lauscht niemand mehr auf den Ports.
    assert!(get_status(port_a, "/api/gesundheit", None, t).is_err());
    assert!(get_status(port_b, "/api/gesundheit", None, t).is_err());
    // Die Handschlagdateien sind aufgeraeumt.
    for ordner in [&ordner_a, &ordner_b] {
        let rest: Vec<_> = std::fs::read_dir(ordner.join("laufzeit"))
            .map(|d| d.flatten().map(|e| e.file_name()).collect())
            .unwrap_or_default();
        assert!(rest.is_empty(), "uebrig: {rest:?}");
        let _ = std::fs::remove_dir_all(ordner);
    }
}
