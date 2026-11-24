//! Antwortet auf dem gemeldeten Port wirklich *unser* Dienst?
//!
//! `GET /api/info` mit `Authorization: Bearer <schluessel>` muss 200 liefern.
//! Den Schluessel kennt nur der Dienst, den dieses Fenster gestartet hat. Ein
//! fremder Prozess (ein alter Dienst aus einer frueheren Sitzung, ein anderes
//! Programm auf demselben Port) antwortet mit 401/404 oder gar nicht.

use crate::http::HttpFehler;

/// Ergebnis der Identitaetspruefung.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Identitaet {
    /// 200: unser Dienst.
    Bestaetigt,
    /// Es antwortet etwas, aber nicht unser Dienst (401, 403, 404, …).
    Fremd(u16),
    /// Es antwortet etwas, das kein HTTP spricht.
    KeinHttp(String),
    /// Keine Antwort (Verbindung abgelehnt, Zeitueberschreitung).
    NichtErreichbar(String),
}

impl Identitaet {
    /// Darf noch einmal versucht werden? Nur, wenn gar keine Antwort kam
    /// (der Socket ist gebunden, uvicorn nimmt die Verbindung vielleicht erst
    /// einen Augenblick spaeter an). Eine falsche Antwort ist endgueltig.
    pub fn erneut_versuchen(&self) -> bool {
        matches!(self, Self::NichtErreichbar(_))
    }
}

/// Entscheidungstabelle.
pub fn bewerten(ergebnis: &Result<u16, HttpFehler>) -> Identitaet {
    match ergebnis {
        Ok(200) => Identitaet::Bestaetigt,
        Ok(status) => Identitaet::Fremd(*status),
        Err(fehler @ HttpFehler::Antwort(_)) => Identitaet::KeinHttp(fehler.to_string()),
        Err(fehler @ HttpFehler::Verbindung(_)) => Identitaet::NichtErreichbar(fehler.to_string()),
    }
}

/// Lebenszeichen nach dem Start (`/api/gesundheit`, ohne Schluessel).
pub fn lebt(ergebnis: &Result<u16, HttpFehler>) -> bool {
    matches!(ergebnis, Ok(200))
}

/// Vergleicht die vom Dienst gemeldete Version mit der eigenen.
pub fn version_passt(eigene: &str, dienst: &str) -> bool {
    eigene.trim() == dienst.trim()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entscheidungstabelle() {
        assert_eq!(bewerten(&Ok(200)), Identitaet::Bestaetigt);
        assert_eq!(bewerten(&Ok(401)), Identitaet::Fremd(401));
        assert_eq!(bewerten(&Ok(403)), Identitaet::Fremd(403));
        assert_eq!(bewerten(&Ok(404)), Identitaet::Fremd(404));
        assert_eq!(bewerten(&Ok(500)), Identitaet::Fremd(500));
        assert_eq!(bewerten(&Ok(204)), Identitaet::Fremd(204));
        assert!(matches!(
            bewerten(&Err(HttpFehler::Verbindung("abgelehnt".into()))),
            Identitaet::NichtErreichbar(_)
        ));
        assert!(matches!(
            bewerten(&Err(HttpFehler::Antwort("SSH".into()))),
            Identitaet::KeinHttp(_)
        ));
    }

    #[test]
    fn nur_ohne_antwort_wird_wiederholt() {
        assert!(!Identitaet::Bestaetigt.erneut_versuchen());
        assert!(!Identitaet::Fremd(401).erneut_versuchen());
        assert!(!Identitaet::Fremd(404).erneut_versuchen());
        assert!(!Identitaet::KeinHttp("x".into()).erneut_versuchen());
        assert!(Identitaet::NichtErreichbar("x".into()).erneut_versuchen());
    }

    #[test]
    fn lebenszeichen() {
        assert!(lebt(&Ok(200)));
        assert!(!lebt(&Ok(503)));
        assert!(!lebt(&Err(HttpFehler::Verbindung("x".into()))));
    }

    #[test]
    fn versionen() {
        assert!(version_passt("0.6.0-alpha.1", "0.6.0-alpha.1\n"));
        assert!(!version_passt("0.6.0-alpha.1", "0.6.0-alpha.2"));
    }
}
