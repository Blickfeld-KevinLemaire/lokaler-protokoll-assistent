//! Welcher Dienst wird gestartet (oder benutzt)?
//!
//! Reihenfolge:
//! 1. `VERMERK_EXTERNER_DIENST=http://127.0.0.1:<port>` (nur zum Entwickeln):
//!    einen von Hand gestarteten Dienst benutzen – nie starten, nie beenden.
//!    Der Schluessel kommt dann aus `VERMERK_API_SCHLUESSEL`.
//! 2. Installiert: `<Ordner der EXE>\dienst\vermerk-dienst.exe`.
//! 3. Aus dem Quelltext: in Debug-Builds immer, in Release-Builds nur mit
//!    `VERMERK_PYTHON` – `<VERMERK_PYTHON oder python> -m protokoll_assistent.api`
//!    mit der Projektwurzel als Arbeitsordner (`VERMERK_PROJEKT` oder der
//!    Ordner, aus dem dieses Fenster gebaut wurde).
//!
//! Nie: einen schon laufenden Dienst aus einer frueheren Sitzung uebernehmen
//! oder feste Ports absuchen.

use std::path::{Path, PathBuf};

pub const UMGEBUNG_EXTERN: &str = "VERMERK_EXTERNER_DIENST";
pub const UMGEBUNG_SCHLUESSEL: &str = "VERMERK_API_SCHLUESSEL";
pub const UMGEBUNG_PYTHON: &str = "VERMERK_PYTHON";
pub const UMGEBUNG_PROJEKT: &str = "VERMERK_PROJEKT";

/// Relativ zum Ordner von `VERMERK.exe`.
pub const DIENST_RELATIV: &str = "dienst/vermerk-dienst.exe";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DienstQuelle {
    Extern {
        port: u16,
        schluessel: String,
    },
    Installiert {
        exe: PathBuf,
        /// Ordner von `VERMERK.exe` = Anwendungsordner (Einstellungen, Daten).
        anwendungsordner: PathBuf,
    },
    Quelltext {
        python: PathBuf,
        projekt: PathBuf,
    },
}

/// Die fuer die Aufloesung relevanten Umgebungsvariablen.
#[derive(Debug, Clone, Default)]
pub struct UmgebungsWerte {
    pub extern_url: Option<String>,
    pub schluessel: Option<String>,
    pub python: Option<String>,
    pub projekt: Option<String>,
}

fn nicht_leer(wert: Option<String>) -> Option<String> {
    wert.map(|w| w.trim().to_string()).filter(|w| !w.is_empty())
}

impl UmgebungsWerte {
    pub fn aus_prozess() -> Self {
        let lesen = |name: &str| nicht_leer(std::env::var(name).ok());
        Self {
            extern_url: lesen(UMGEBUNG_EXTERN),
            schluessel: lesen(UMGEBUNG_SCHLUESSEL),
            python: lesen(UMGEBUNG_PYTHON),
            projekt: lesen(UMGEBUNG_PROJEKT),
        }
    }
}

/// `http://127.0.0.1:<port>` (Schraegstrich am Ende erlaubt). Nur diese Form:
/// Die CSP des Fensters erlaubt ohnehin nur `http://127.0.0.1:*`.
pub fn externe_adresse(url: &str) -> Result<u16, String> {
    let fehler = || {
        format!("{UMGEBUNG_EXTERN} muss die Form http://127.0.0.1:<port> haben, nicht '{url:.60}'")
    };
    let rest = url
        .trim()
        .strip_prefix("http://127.0.0.1:")
        .ok_or_else(fehler)?;
    let rest = rest.strip_suffix('/').unwrap_or(rest);
    match rest.parse::<u16>() {
        Ok(0) | Err(_) => Err(fehler()),
        Ok(port) => Ok(port),
    }
}

/// Ist das ein Projektordner mit dem Dienst im Quelltext?
pub fn ist_projektordner(ordner: &Path, existiert: &impl Fn(&Path) -> bool) -> bool {
    existiert(
        &ordner
            .join("protokoll_assistent")
            .join("api")
            .join("__main__.py"),
    )
}

/// Reine Logik der Aufloesung. `quellprojekt` ist der Projektordner zur
/// Bauzeit (nur in Debug-/Entwicklerbuilds sinnvoll).
pub fn aufloesen(
    exe_ordner: &Path,
    umgebung: &UmgebungsWerte,
    debug: bool,
    quellprojekt: Option<&Path>,
    existiert: impl Fn(&Path) -> bool,
) -> Result<DienstQuelle, String> {
    if let Some(url) = &umgebung.extern_url {
        let port = externe_adresse(url)?;
        let schluessel = umgebung.schluessel.clone().ok_or_else(|| {
            format!("{UMGEBUNG_EXTERN} ist gesetzt, aber {UMGEBUNG_SCHLUESSEL} fehlt.")
        })?;
        return Ok(DienstQuelle::Extern { port, schluessel });
    }
    let installiert = exe_ordner.join(DIENST_RELATIV);
    if existiert(&installiert) {
        return Ok(DienstQuelle::Installiert {
            exe: installiert,
            anwendungsordner: exe_ordner.to_path_buf(),
        });
    }
    if debug || umgebung.python.is_some() {
        let python = PathBuf::from(umgebung.python.as_deref().unwrap_or("python"));
        let projekt = match (&umgebung.projekt, quellprojekt) {
            (Some(p), _) => PathBuf::from(p),
            (None, Some(q)) => q.to_path_buf(),
            (None, None) => {
                return Err(format!(
                    "Projektordner unbekannt: bitte {UMGEBUNG_PROJEKT} setzen."
                ))
            }
        };
        if !ist_projektordner(&projekt, &existiert) {
            return Err(format!(
                "Im Projektordner {} fehlt protokoll_assistent/api/__main__.py.",
                projekt.display()
            ));
        }
        return Ok(DienstQuelle::Quelltext { python, projekt });
    }
    Err(format!(
        "Der Dienst fehlt: {} wurde nicht gefunden. Bitte VERMERK neu installieren.",
        installiert.display()
    ))
}

/// Projektordner zur Bauzeit (`oberflaeche/src-tauri/../..`).
pub fn quellprojekt_zur_bauzeit() -> PathBuf {
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    manifest
        .ancestors()
        .nth(2)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| manifest.join("..").join(".."))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn vorhanden(pfade: &[PathBuf]) -> impl Fn(&Path) -> bool {
        let menge: HashSet<PathBuf> = pfade.iter().cloned().collect();
        move |p: &Path| menge.contains(p)
    }

    fn projekt_datei(projekt: &Path) -> PathBuf {
        projekt
            .join("protokoll_assistent")
            .join("api")
            .join("__main__.py")
    }

    #[test]
    fn externe_adressen() {
        assert_eq!(externe_adresse("http://127.0.0.1:8780"), Ok(8780));
        assert_eq!(externe_adresse(" http://127.0.0.1:8780/ "), Ok(8780));
        assert!(externe_adresse("http://localhost:8780").is_err());
        assert!(externe_adresse("https://127.0.0.1:8780").is_err());
        assert!(externe_adresse("http://127.0.0.1:0").is_err());
        assert!(externe_adresse("http://127.0.0.1:99999").is_err());
        assert!(externe_adresse("http://127.0.0.1:80/api").is_err());
        assert!(externe_adresse("http://10.0.0.1:8780").is_err());
    }

    #[test]
    fn extern_hat_vorrang_und_braucht_schluessel() {
        let exe = Path::new("C:/App");
        let installiert = exe.join(DIENST_RELATIV);
        let mut u = UmgebungsWerte {
            extern_url: Some("http://127.0.0.1:9000".into()),
            schluessel: Some("k".into()),
            ..Default::default()
        };
        assert_eq!(
            aufloesen(
                exe,
                &u,
                false,
                None,
                vorhanden(std::slice::from_ref(&installiert))
            ),
            Ok(DienstQuelle::Extern {
                port: 9000,
                schluessel: "k".into()
            })
        );
        u.schluessel = None;
        assert!(aufloesen(exe, &u, false, None, vorhanden(&[installiert])).is_err());
    }

    #[test]
    fn installierter_dienst() {
        let exe = Path::new("C:/Programme/VERMERK");
        let installiert = exe.join(DIENST_RELATIV);
        let u = UmgebungsWerte {
            python: Some("C:/py/python.exe".into()),
            ..Default::default()
        };
        assert_eq!(
            aufloesen(
                exe,
                &u,
                true,
                None,
                vorhanden(std::slice::from_ref(&installiert))
            ),
            Ok(DienstQuelle::Installiert {
                exe: installiert,
                anwendungsordner: exe.to_path_buf()
            })
        );
    }

    #[test]
    fn quelltext_im_debug_build() {
        let exe = Path::new("C:/repo/oberflaeche/src-tauri/target/debug");
        let projekt = Path::new("C:/repo");
        let ex = vorhanden(&[projekt_datei(projekt)]);
        assert_eq!(
            aufloesen(exe, &UmgebungsWerte::default(), true, Some(projekt), ex),
            Ok(DienstQuelle::Quelltext {
                python: PathBuf::from("python"),
                projekt: projekt.to_path_buf()
            })
        );
    }

    #[test]
    fn quelltext_im_release_nur_mit_vermerk_python() {
        let exe = Path::new("C:/repo/oberflaeche/src-tauri/target/release");
        let projekt = Path::new("C:/repo");
        let ohne = aufloesen(
            exe,
            &UmgebungsWerte::default(),
            false,
            Some(projekt),
            vorhanden(&[projekt_datei(projekt)]),
        );
        assert!(ohne.unwrap_err().contains("Der Dienst fehlt"));
        let u = UmgebungsWerte {
            python: Some("C:/repo/.venv/Scripts/python.exe".into()),
            ..Default::default()
        };
        assert_eq!(
            aufloesen(
                exe,
                &u,
                false,
                Some(projekt),
                vorhanden(&[projekt_datei(projekt)])
            ),
            Ok(DienstQuelle::Quelltext {
                python: PathBuf::from("C:/repo/.venv/Scripts/python.exe"),
                projekt: projekt.to_path_buf()
            })
        );
    }

    #[test]
    fn projekt_aus_umgebung_und_pruefung() {
        let exe = Path::new("C:/x");
        let anderes = Path::new("D:/anderes");
        let u = UmgebungsWerte {
            projekt: Some("D:/anderes".into()),
            ..Default::default()
        };
        assert_eq!(
            aufloesen(
                exe,
                &u,
                true,
                Some(Path::new("C:/repo")),
                vorhanden(&[projekt_datei(anderes)])
            ),
            Ok(DienstQuelle::Quelltext {
                python: PathBuf::from("python"),
                projekt: anderes.to_path_buf()
            })
        );
        // Ordner ohne Dienst-Quelltext wird abgelehnt.
        assert!(aufloesen(exe, &u, true, None, vorhanden(&[])).is_err());
        assert!(aufloesen(exe, &UmgebungsWerte::default(), true, None, vorhanden(&[])).is_err());
    }
}
