//! `__COMPAT_LAYER` ohne `RUNASADMIN`.
//!
//! Hat jemand in den Eigenschaften der EXE "Als Administrator ausfuehren"
//! angehakt (oder ein Kompatibilitaetsassistent es gesetzt), steht
//! `RUNASADMIN` in `__COMPAT_LAYER` – und wird an jeden Kindprozess vererbt.
//! Der Dienst und das mitgelieferte Python verlangten dann ihrerseits
//! Administratorrechte (UAC-Abfrage, oder sie starten gar nicht). Das Fenster
//! entfernt den Eintrag deshalb als allererstes.

/// Name der Umgebungsvariable.
pub const VARIABLE: &str = "__COMPAT_LAYER";

/// Was mit der Variable geschehen soll.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KompatAenderung {
    /// Kein `RUNASADMIN` darin – nichts tun.
    Unveraendert,
    /// Nach dem Entfernen bleibt nichts Sinnvolles uebrig – Variable loeschen.
    Entfernen,
    /// Andere Eintraege bleiben erhalten.
    Setzen(String),
}

/// Reine Logik: `RUNASADMIN` (Gross-/Kleinschreibung egal) aus der durch
/// Leerzeichen getrennten Liste entfernen. Uebrig bleibende Kennzeichen wie
/// `~` (nur ein Praefix) zaehlen nicht als Inhalt.
pub fn ohne_runasadmin(wert: &str) -> KompatAenderung {
    let teile: Vec<&str> = wert.split_whitespace().collect();
    if !teile.iter().any(|t| t.eq_ignore_ascii_case("RUNASADMIN")) {
        return KompatAenderung::Unveraendert;
    }
    let rest: Vec<&str> = teile
        .into_iter()
        .filter(|t| !t.eq_ignore_ascii_case("RUNASADMIN"))
        .collect();
    if rest.iter().all(|t| *t == "~") {
        KompatAenderung::Entfernen
    } else {
        KompatAenderung::Setzen(rest.join(" "))
    }
}

/// Wendet [`ohne_runasadmin`] auf die Umgebung dieses Prozesses an. Muss vor
/// dem ersten Faden laufen (erste Anweisung in `main`).
pub fn bereinigen() -> KompatAenderung {
    let Some(wert) = std::env::var_os(VARIABLE) else {
        return KompatAenderung::Unveraendert;
    };
    let aenderung = ohne_runasadmin(&wert.to_string_lossy());
    match &aenderung {
        KompatAenderung::Unveraendert => {}
        KompatAenderung::Entfernen => std::env::remove_var(VARIABLE),
        KompatAenderung::Setzen(neu) => std::env::set_var(VARIABLE, neu),
    }
    aenderung
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ohne_runasadmin_bleibt_unveraendert() {
        assert_eq!(ohne_runasadmin(""), KompatAenderung::Unveraendert);
        assert_eq!(ohne_runasadmin("WINXPSP3"), KompatAenderung::Unveraendert);
        assert_eq!(
            ohne_runasadmin("~ HIGHDPIAWARE"),
            KompatAenderung::Unveraendert
        );
    }

    #[test]
    fn nur_runasadmin_wird_entfernt() {
        assert_eq!(ohne_runasadmin("RUNASADMIN"), KompatAenderung::Entfernen);
        assert_eq!(ohne_runasadmin("~ RUNASADMIN"), KompatAenderung::Entfernen);
        assert_eq!(
            ohne_runasadmin("  runasadmin  "),
            KompatAenderung::Entfernen
        );
    }

    #[test]
    fn andere_eintraege_bleiben() {
        assert_eq!(
            ohne_runasadmin("~ RUNASADMIN HIGHDPIAWARE"),
            KompatAenderung::Setzen("~ HIGHDPIAWARE".into())
        );
        assert_eq!(
            ohne_runasadmin("WINXPSP3 RunAsAdmin"),
            KompatAenderung::Setzen("WINXPSP3".into())
        );
    }

    #[test]
    fn teilwort_zaehlt_nicht() {
        assert_eq!(
            ohne_runasadmin("RUNASADMINX"),
            KompatAenderung::Unveraendert
        );
    }
}
