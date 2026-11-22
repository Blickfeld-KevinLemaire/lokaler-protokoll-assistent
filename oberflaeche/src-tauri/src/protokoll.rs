//! Meldungen der Webseite im Protokoll des Fensters.
//!
//! In der gebauten Fassung gibt es keine Entwicklerwerkzeuge. Die Oberflaeche
//! schickt `console.warn`/`console.error` und unbehandelte Fehler deshalb
//! ueber den Befehl `protokoll_schreiben` hierher – begrenzt auf 500 je Lauf,
//! lange Texte gekuerzt. `console.log` kommt nicht an (kann Inhalte aus
//! Besprechungen enthalten), Stufen ausser Warnung/Fehler werden abgelehnt.

use std::sync::atomic::{AtomicUsize, Ordering};

/// Hoechstens so viele Meldungen je Lauf.
pub const MAX_MELDUNGEN: usize = 500;
/// Laengere Texte werden gekuerzt (Zeichen, nicht Bytes).
pub const MAX_ZEICHEN: usize = 2000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stufe {
    Warnung,
    Fehler,
}

impl Stufe {
    pub fn aus_text(stufe: &str) -> Option<Self> {
        match stufe.trim().to_ascii_lowercase().as_str() {
            "warn" | "warning" | "warnung" => Some(Self::Warnung),
            "error" | "fehler" => Some(Self::Fehler),
            _ => None,
        }
    }
}

/// Was mit einer Meldung geschehen soll.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Annahme {
    Schreiben(Stufe, String),
    /// Die 501. Meldung: einmal sagen, dass ab jetzt nichts mehr kommt.
    GrenzeErreicht,
    /// Danach: still verwerfen.
    Verwerfen,
}

#[derive(Debug, Default)]
pub struct WebseitenProtokoll {
    anzahl: AtomicUsize,
}

impl WebseitenProtokoll {
    pub fn new() -> Self {
        Self::default()
    }

    /// Zaehlt und bereitet die Meldung auf. Unbekannte Stufen zaehlen nicht.
    pub fn annehmen(&self, stufe: &str, text: &str) -> Result<Annahme, String> {
        let stufe = Stufe::aus_text(stufe)
            .ok_or_else(|| format!("Unbekannte Stufe '{stufe:.20}' (erlaubt: warn, error)"))?;
        let bisher = self.anzahl.fetch_add(1, Ordering::Relaxed);
        Ok(match bisher {
            n if n < MAX_MELDUNGEN => Annahme::Schreiben(stufe, aufbereiten(text)),
            n if n == MAX_MELDUNGEN => Annahme::GrenzeErreicht,
            _ => Annahme::Verwerfen,
        })
    }
}

/// Eine Zeile je Meldung (Zeilenumbrueche sichtbar ersetzt, Steuerzeichen
/// entfernt), hoechstens [`MAX_ZEICHEN`] Zeichen.
pub fn aufbereiten(text: &str) -> String {
    let mut ergebnis = String::with_capacity(text.len().min(MAX_ZEICHEN + 32));
    let mut zeichen = 0usize;
    let mut gekuerzt = false;
    for c in text.chars() {
        if zeichen >= MAX_ZEICHEN {
            gekuerzt = true;
            break;
        }
        match c {
            '\r' => continue,
            '\n' => ergebnis.push_str(" ⏎ "),
            c if c.is_control() => continue,
            c => ergebnis.push(c),
        }
        zeichen += 1;
    }
    if gekuerzt {
        let rest = text.chars().count() - MAX_ZEICHEN;
        ergebnis.push_str(&format!(" … [{rest} Zeichen gekürzt]"));
    }
    ergebnis
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stufen() {
        assert_eq!(Stufe::aus_text("warn"), Some(Stufe::Warnung));
        assert_eq!(Stufe::aus_text("ERROR"), Some(Stufe::Fehler));
        assert_eq!(Stufe::aus_text("fehler"), Some(Stufe::Fehler));
        assert_eq!(Stufe::aus_text("log"), None);
        assert_eq!(Stufe::aus_text("info"), None);
    }

    #[test]
    fn grenze_von_500() {
        let p = WebseitenProtokoll::new();
        for i in 0..MAX_MELDUNGEN {
            assert!(
                matches!(p.annehmen("warn", "x"), Ok(Annahme::Schreiben(..))),
                "{i}"
            );
        }
        assert_eq!(p.annehmen("error", "x"), Ok(Annahme::GrenzeErreicht));
        assert_eq!(p.annehmen("error", "x"), Ok(Annahme::Verwerfen));
        assert_eq!(p.annehmen("warn", "x"), Ok(Annahme::Verwerfen));
    }

    #[test]
    fn unbekannte_stufe_zaehlt_nicht() {
        let p = WebseitenProtokoll::new();
        assert!(p.annehmen("log", "geheimer Inhalt").is_err());
        for _ in 0..MAX_MELDUNGEN {
            p.annehmen("warn", "x").unwrap();
        }
        assert_eq!(p.annehmen("warn", "x"), Ok(Annahme::GrenzeErreicht));
    }

    #[test]
    fn lange_texte_werden_gekuerzt() {
        let lang = "ä".repeat(MAX_ZEICHEN + 10);
        let t = aufbereiten(&lang);
        assert!(t.starts_with(&"ä".repeat(MAX_ZEICHEN)));
        assert!(t.ends_with("[10 Zeichen gekürzt]"));
        assert_eq!(
            aufbereiten(&"a".repeat(MAX_ZEICHEN)),
            "a".repeat(MAX_ZEICHEN)
        );
    }

    #[test]
    fn eine_zeile_ohne_steuerzeichen() {
        assert_eq!(aufbereiten("a\r\nb\u{1b}[31mc"), "a ⏎ b[31mc");
    }
}
