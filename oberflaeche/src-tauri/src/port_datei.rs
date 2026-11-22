//! Handschlagdatei des Dienstes.
//!
//! Der Dienst bindet Port 0 selbst (Windows vergibt einen freien Port) und
//! schreibt danach atomar `{"port", "pid", "netz_port", "version"}` in die
//! Datei, die ihm das Fenster mit `--port-datei` genannt hat
//! (`protokoll_assistent/api/__main__.py`: `socket_binden`,
//! `port_datei_schreiben`). Erst daraus erfaehrt das Fenster den Port.

use serde::Deserialize;

/// Gueltiger Inhalt der Handschlagdatei.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PortDatei {
    pub port: u16,
    pub pid: u32,
    pub netz_port: Option<u16>,
    pub version: String,
}

/// Warum ein Inhalt (noch) nicht taugt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PortDateiFehler {
    /// Leer oder kein vollstaendiges JSON. Kann bei einem Lesezugriff mitten
    /// im Ersetzen vorkommen – weiter warten.
    Unvollstaendig,
    /// Vollstaendiges JSON, aber Felder fehlen oder sind unbrauchbar.
    Ungueltig(String),
    /// Die Datei stammt nicht vom selbst gestarteten Prozess (oder einem
    /// seiner Nachfahren).
    FremderProzess { pid: u32 },
}

impl std::fmt::Display for PortDateiFehler {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unvollstaendig => write!(f, "Handschlagdatei unvollständig"),
            Self::Ungueltig(grund) => write!(f, "Handschlagdatei ungültig: {grund}"),
            Self::FremderProzess { pid } => write!(
                f,
                "Handschlagdatei stammt von Prozess {pid}, nicht vom gestarteten Dienst"
            ),
        }
    }
}

#[derive(Deserialize)]
struct Roh {
    port: Option<serde_json::Value>,
    pid: Option<serde_json::Value>,
    #[serde(default)]
    netz_port: Option<serde_json::Value>,
    version: Option<serde_json::Value>,
}

fn port_aus(wert: &serde_json::Value, feld: &str) -> Result<u16, PortDateiFehler> {
    let zahl = wert
        .as_u64()
        .ok_or_else(|| PortDateiFehler::Ungueltig(format!("'{feld}' ist keine Zahl")))?;
    match u16::try_from(zahl) {
        Ok(0) | Err(_) => Err(PortDateiFehler::Ungueltig(format!(
            "'{feld}' ist kein gültiger Port: {zahl}"
        ))),
        Ok(p) => Ok(p),
    }
}

/// Liest und prueft den Inhalt (ohne Herkunftspruefung).
pub fn auswerten(text: &str) -> Result<PortDatei, PortDateiFehler> {
    let text = text.trim_start_matches('\u{feff}').trim();
    if text.is_empty() {
        return Err(PortDateiFehler::Unvollstaendig);
    }
    let roh: Roh = match serde_json::from_str(text) {
        Ok(r) => r,
        Err(fehler) if fehler.is_eof() => return Err(PortDateiFehler::Unvollstaendig),
        Err(fehler) => return Err(PortDateiFehler::Ungueltig(fehler.to_string())),
    };
    let port = port_aus(
        roh.port
            .as_ref()
            .ok_or_else(|| PortDateiFehler::Ungueltig("'port' fehlt".into()))?,
        "port",
    )?;
    let pid = roh
        .pid
        .as_ref()
        .ok_or_else(|| PortDateiFehler::Ungueltig("'pid' fehlt".into()))?
        .as_u64()
        .and_then(|p| u32::try_from(p).ok())
        .filter(|p| *p != 0)
        .ok_or_else(|| {
            PortDateiFehler::Ungueltig("'pid' ist keine gültige Prozessnummer".into())
        })?;
    let netz_port = match roh.netz_port {
        None | Some(serde_json::Value::Null) => None,
        Some(ref w) => Some(port_aus(w, "netz_port")?),
    };
    let version = roh
        .version
        .as_ref()
        .ok_or_else(|| PortDateiFehler::Ungueltig("'version' fehlt".into()))?
        .as_str()
        .ok_or_else(|| PortDateiFehler::Ungueltig("'version' ist kein Text".into()))?
        .to_string();
    Ok(PortDatei {
        port,
        pid,
        netz_port,
        version,
    })
}

/// Liest den Inhalt und prueft, ob er vom gestarteten Prozess stammt.
///
/// Entscheidung zur Prozessnummer: Der Dienst darf eine **andere** Nummer
/// melden als das gestartete Kind – im lokalen Modus startet er sich in der
/// Rechenumgebung neu (`bootstrap`), und schon das `python.exe` einer
/// virtuellen Umgebung ist unter Windows nur ein Starter, der den echten
/// Interpreter als Kind startet. Angenommen wird deshalb das Kind selbst
/// oder ein **Nachfahre** davon (`ist_nachfahre`). Laesst sich der
/// Prozessbaum nicht lesen, entscheidet allein die Identitaetspruefung mit
/// dem Schluessel (`/api/info`), die ohnehin immer folgt – sie ist der
/// eigentliche Beweis, die Prozessnummer nur ein frueher Plausibilitaetstest.
pub fn auswerten_fuer_kind(
    text: &str,
    kind_pid: u32,
    ist_nachfahre: impl Fn(u32, u32) -> Option<bool>,
) -> Result<PortDatei, PortDateiFehler> {
    let datei = auswerten(text)?;
    if datei.pid == kind_pid {
        return Ok(datei);
    }
    match ist_nachfahre(datei.pid, kind_pid) {
        Some(true) | None => Ok(datei),
        Some(false) => Err(PortDateiFehler::FremderProzess { pid: datei.pid }),
    }
}

/// Reine Logik fuer die Nachfahren-Pruefung: folgt der Elternkette von `pid`
/// (hoechstens `max_tiefe` Schritte) und sucht `vorfahr`.
pub fn ist_nachfahre_in(
    pid: u32,
    vorfahr: u32,
    eltern_von: impl Fn(u32) -> Option<u32>,
    max_tiefe: usize,
) -> bool {
    let mut aktuell = pid;
    for _ in 0..max_tiefe {
        match eltern_von(aktuell) {
            Some(eltern) if eltern == vorfahr => return true,
            Some(eltern) if eltern != 0 && eltern != aktuell => aktuell = eltern,
            _ => return false,
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    const GUT: &str =
        r#"{"port": 51234, "pid": 4711, "netz_port": null, "version": "0.6.0-alpha.1"}"#;

    #[test]
    fn gueltige_datei() {
        let d = auswerten(GUT).unwrap();
        assert_eq!(d.port, 51234);
        assert_eq!(d.pid, 4711);
        assert_eq!(d.netz_port, None);
        assert_eq!(d.version, "0.6.0-alpha.1");
    }

    #[test]
    fn netz_port_wird_gelesen_und_darf_fehlen() {
        let d = auswerten(r#"{"port": 1, "pid": 2, "netz_port": 8780, "version": "x"}"#).unwrap();
        assert_eq!(d.netz_port, Some(8780));
        let d = auswerten(r#"{"port": 1, "pid": 2, "version": "x"}"#).unwrap();
        assert_eq!(d.netz_port, None);
    }

    #[test]
    fn bom_und_leerraum_stoeren_nicht() {
        assert!(auswerten(&format!("\u{feff}  {GUT}\n")).is_ok());
    }

    #[test]
    fn leer_oder_abgeschnitten_ist_unvollstaendig() {
        assert_eq!(auswerten(""), Err(PortDateiFehler::Unvollstaendig));
        assert_eq!(auswerten("   "), Err(PortDateiFehler::Unvollstaendig));
        assert_eq!(
            auswerten(r#"{"port": 512"#),
            Err(PortDateiFehler::Unvollstaendig)
        );
        assert_eq!(
            auswerten(&GUT[..GUT.len() - 1]),
            Err(PortDateiFehler::Unvollstaendig)
        );
    }

    #[test]
    fn kaputtes_json_ist_ungueltig() {
        assert!(matches!(
            auswerten("{port: 1}"),
            Err(PortDateiFehler::Ungueltig(_))
        ));
        assert!(matches!(
            auswerten("[1, 2]"),
            Err(PortDateiFehler::Ungueltig(_))
        ));
        assert!(matches!(
            auswerten("hallo"),
            Err(PortDateiFehler::Ungueltig(_))
        ));
    }

    #[test]
    fn fehlende_felder_sind_ungueltig() {
        for text in [
            r#"{"pid": 1, "version": "x"}"#,
            r#"{"port": 1, "version": "x"}"#,
            r#"{"port": 1, "pid": 2}"#,
        ] {
            assert!(
                matches!(auswerten(text), Err(PortDateiFehler::Ungueltig(_))),
                "{text}"
            );
        }
    }

    #[test]
    fn falsche_werte_sind_ungueltig() {
        for text in [
            r#"{"port": 0, "pid": 1, "version": "x"}"#,
            r#"{"port": 70000, "pid": 1, "version": "x"}"#,
            r#"{"port": -1, "pid": 1, "version": "x"}"#,
            r#"{"port": "51234", "pid": 1, "version": "x"}"#,
            r#"{"port": 1, "pid": 0, "version": "x"}"#,
            r#"{"port": 1, "pid": "4711", "version": "x"}"#,
            r#"{"port": 1, "pid": 1, "version": 6}"#,
            r#"{"port": 1, "pid": 1, "netz_port": 0, "version": "x"}"#,
        ] {
            assert!(
                matches!(auswerten(text), Err(PortDateiFehler::Ungueltig(_))),
                "{text}"
            );
        }
    }

    #[test]
    fn eigene_pid_wird_angenommen() {
        let d = auswerten_fuer_kind(GUT, 4711, |_, _| Some(false)).unwrap();
        assert_eq!(d.port, 51234);
    }

    #[test]
    fn nachfahre_wird_angenommen() {
        assert!(
            auswerten_fuer_kind(GUT, 100, |pid, vorfahr| Some(pid == 4711 && vorfahr == 100))
                .is_ok()
        );
    }

    #[test]
    fn fremde_pid_wird_abgelehnt() {
        assert_eq!(
            auswerten_fuer_kind(GUT, 100, |_, _| Some(false)),
            Err(PortDateiFehler::FremderProzess { pid: 4711 })
        );
    }

    #[test]
    fn unbekannter_prozessbaum_verlaesst_sich_auf_die_identitaet() {
        assert!(auswerten_fuer_kind(GUT, 100, |_, _| None).is_ok());
    }

    #[test]
    fn elternkette() {
        // 30 -> 20 -> 10 -> 1
        let eltern = |p: u32| match p {
            30 => Some(20),
            20 => Some(10),
            10 => Some(1),
            _ => None,
        };
        assert!(ist_nachfahre_in(30, 10, eltern, 8));
        assert!(ist_nachfahre_in(30, 20, eltern, 8));
        assert!(!ist_nachfahre_in(30, 99, eltern, 8));
        assert!(!ist_nachfahre_in(30, 10, eltern, 1));
        // Schleifen enden.
        assert!(!ist_nachfahre_in(5, 9, Some, 8));
        assert!(!ist_nachfahre_in(5, 9, |_| Some(0), 8));
    }
}
