//! Tauri-Anbindung: Plugins, die beiden Befehle, Start und Ende der Wache.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_log::{RotationStrategy, Target, TargetKind, TimezoneStrategy};

use crate::dienst_pfad::{self, DienstQuelle, UmgebungsWerte};
use crate::kompat::KompatAenderung;
use crate::protokoll::{Annahme, Stufe, WebseitenProtokoll};
use crate::ueberwachung::{self, DienstStatus, Einstellungen, Ueberwachung, Zeiten, Zugang};

/// So lange wartet `zugang` hoechstens. Grosszuegig: Der erste Start im
/// lokalen Modus kann die Rechenumgebung einrichten. Die Oberflaeche ruft
/// danach einfach erneut auf.
const ZUGANG_ZEITLIMIT: Duration = Duration::from_secs(15 * 60);
/// Tagesdateien des Fensterprotokolls, die aelter sind, werden geloescht.
const PROTOKOLL_AUFBEWAHRUNG: Duration = Duration::from_secs(14 * 24 * 3600);
/// Groesse einer Protokolldatei, danach wird rotiert (je Tag hoechstens 3).
const PROTOKOLL_MAX_BYTES: u128 = 5 * 1024 * 1024;
/// `dienst.log` wird beim Start rotiert, wenn es groesser ist.
const DIENST_LOG_MAX_BYTES: u64 = 10 * 1024 * 1024;

struct FensterZustand {
    ueberwachung: Arc<Ueberwachung>,
    protokoll: WebseitenProtokoll,
}

/// Aktuelle Basis-URL und Schluessel. Wartet, solange der Dienst startet.
#[tauri::command]
async fn zugang(zustand: tauri::State<'_, FensterZustand>) -> Result<Zugang, String> {
    let ueberwachung = Arc::clone(&zustand.ueberwachung);
    tauri::async_runtime::spawn_blocking(move || ueberwachung.zugang_warten(ZUGANG_ZEITLIMIT))
        .await
        .map_err(|e| format!("Interner Fehler: {e}"))?
}

/// Warnungen und Fehler der Webseite ins Protokoll (hoechstens 500 je Lauf).
#[tauri::command]
fn protokoll_schreiben(
    stufe: String,
    text: String,
    zustand: tauri::State<'_, FensterZustand>,
) -> Result<(), String> {
    match zustand.protokoll.annehmen(&stufe, &text)? {
        Annahme::Schreiben(Stufe::Warnung, t) => log::warn!(target: "webseite", "{t}"),
        Annahme::Schreiben(Stufe::Fehler, t) => log::error!(target: "webseite", "{t}"),
        Annahme::GrenzeErreicht => log::warn!(
            target: "webseite",
            "{} Meldungen erreicht – weitere Meldungen der Oberfläche werden in diesem Lauf nicht mehr protokolliert.",
            crate::protokoll::MAX_MELDUNGEN
        ),
        Annahme::Verwerfen => {}
    }
    Ok(())
}

fn heute() -> String {
    let jetzt =
        time::OffsetDateTime::now_local().unwrap_or_else(|_| time::OffsetDateTime::now_utc());
    format!(
        "{:04}-{:02}-{:02}",
        jetzt.year(),
        u8::from(jetzt.month()),
        jetzt.day()
    )
}

fn protokoll_plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    let mut builder = tauri_plugin_log::Builder::new()
        .clear_targets()
        // Eine Datei je Tag; innerhalb des Tages begrenzt und rotiert.
        .target(Target::new(TargetKind::LogDir {
            file_name: Some(format!("vermerk-{}", heute())),
        }))
        .max_file_size(PROTOKOLL_MAX_BYTES)
        .rotation_strategy(RotationStrategy::KeepSome(3))
        .timezone_strategy(TimezoneStrategy::UseLocal)
        .level(log::LevelFilter::Info)
        // Laute Bibliotheken nur mit Warnungen.
        .level_for("tao", log::LevelFilter::Warn)
        .level_for("wry", log::LevelFilter::Warn);
    if cfg!(debug_assertions) {
        builder = builder.target(Target::new(TargetKind::Stdout));
    }
    builder.build()
}

/// Loescht alte Tagesdateien (`vermerk-*.log`) des Fensterprotokolls.
fn alte_protokolle_entfernen(ordner: &Path) {
    let Ok(eintraege) = std::fs::read_dir(ordner) else {
        return;
    };
    let grenze = SystemTime::now()
        .checked_sub(PROTOKOLL_AUFBEWAHRUNG)
        .unwrap_or(SystemTime::UNIX_EPOCH);
    for eintrag in eintraege.flatten() {
        let name = eintrag.file_name().to_string_lossy().into_owned();
        if !(name.starts_with("vermerk-") && name.ends_with(".log")) {
            continue;
        }
        let alt = eintrag
            .metadata()
            .and_then(|m| m.modified())
            .map(|t| t < grenze)
            .unwrap_or(false);
        if alt {
            let _ = std::fs::remove_file(eintrag.path());
        }
    }
}

fn dienst_log_rotieren(pfad: &Path) {
    let gross = std::fs::metadata(pfad)
        .map(|m| m.len() > DIENST_LOG_MAX_BYTES)
        .unwrap_or(false);
    if gross {
        let alt = pfad.with_extension("alt.log");
        let _ = std::fs::remove_file(&alt);
        let _ = std::fs::rename(pfad, alt);
    }
}

fn quelle_beschreiben(quelle: &DienstQuelle) -> String {
    match quelle {
        DienstQuelle::Extern { port, .. } => format!("extern, http://127.0.0.1:{port}"),
        DienstQuelle::Installiert { exe, .. } => format!("installiert, {}", exe.display()),
        DienstQuelle::Quelltext { python, projekt } => format!(
            "Quelltext, {} -m protokoll_assistent.api in {}",
            python.display(),
            projekt.display()
        ),
    }
}

fn wache_starten(app: &tauri::App) -> Arc<Ueberwachung> {
    let pfade = app.path();
    let log_ordner = pfade
        .app_log_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("VERMERK").join("logs"));
    let laufzeit_ordner = pfade
        .app_local_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("VERMERK"))
        .join("laufzeit");
    alte_protokolle_entfernen(&log_ordner);
    let dienst_log = log_ordner.join("dienst.log");
    dienst_log_rotieren(&dienst_log);

    let exe_ordner = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));
    let quellprojekt = dienst_pfad::quellprojekt_zur_bauzeit();
    let quelle = match dienst_pfad::aufloesen(
        &exe_ordner,
        &UmgebungsWerte::aus_prozess(),
        cfg!(debug_assertions),
        Some(&quellprojekt),
        |p| p.is_file(),
    ) {
        Ok(q) => q,
        Err(meldung) => return Ueberwachung::fehlgeschlagen(meldung),
    };
    log::info!("Dienst: {}", quelle_beschreiben(&quelle));
    let schluessel = match crate::schluessel::erzeugen() {
        Ok(s) => s,
        Err(meldung) => return Ueberwachung::fehlgeschlagen(meldung),
    };
    let handle = app.handle().clone();
    let melder: ueberwachung::Melder = Arc::new(move |status: &DienstStatus| {
        if let Err(e) = handle.emit(ueberwachung::EREIGNIS, status) {
            log::warn!("Ereignis {} nicht gesendet: {e}", ueberwachung::EREIGNIS);
        }
    });
    Ueberwachung::starten(
        Einstellungen {
            quelle,
            schluessel,
            laufzeit_ordner,
            dienst_log: Some(dienst_log),
            eigene_version: env!("CARGO_PKG_VERSION").to_string(),
            zeiten: Zeiten::default(),
        },
        melder,
    )
}

fn hauptfenster_zeigen(app: &tauri::AppHandle) {
    if let Some(fenster) = app.get_webview_window("main") {
        let _ = fenster.unminimize();
        let _ = fenster.show();
        let _ = fenster.set_focus();
    }
}

/// Startet das Fenster. `kompat`: was `main` an `__COMPAT_LAYER` geaendert hat.
pub fn run(kompat: KompatAenderung) {
    let app = tauri::Builder::default()
        // Als erstes Plugin: Ein zweiter Start bringt nur das vorhandene
        // Fenster nach vorn (zwei Fenster = zwei Dienste = Grafikspeicher voll).
        .plugin(tauri_plugin_single_instance::init(
            |app, _argumente, _ordner| {
                log::info!("Zweiter Start – vorhandenes Fenster wird gezeigt");
                hauptfenster_zeigen(app);
            },
        ))
        .plugin(protokoll_plugin())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![zugang, protokoll_schreiben])
        .setup(move |app| {
            log::info!(
                "VERMERK {} startet (PID {})",
                env!("CARGO_PKG_VERSION"),
                std::process::id()
            );
            if kompat != KompatAenderung::Unveraendert {
                log::warn!("RUNASADMIN aus __COMPAT_LAYER entfernt ({kompat:?})");
            }
            let ueberwachung = wache_starten(app);
            app.manage(FensterZustand {
                ueberwachung,
                protokoll: WebseitenProtokoll::new(),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("VERMERK-Fenster konnte nicht starten");

    app.run(|app, ereignis| {
        if let RunEvent::Exit = ereignis {
            if let Some(zustand) = app.try_state::<FensterZustand>() {
                log::info!("Fenster wird beendet – Dienst wird beendet");
                zustand.ueberwachung.beenden();
            }
        }
    });
}
