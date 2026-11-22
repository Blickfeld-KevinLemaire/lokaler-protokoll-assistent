//! Neustart-Budget des Dienstes (ARCHITEKTUR.md, "Prozess und Fenster").
//!
//! Drei Versuche mit wachsendem Abstand (5 s, 10 s, 20 s). Zurueckgesetzt wird
//! das Budget **nur** nach einer gesunden Identitaetspruefung – ein Dienst, der
//! immer wieder kurz nach dem Start stirbt, verbraucht es also und endet in
//! `fehlgeschlagen`, statt endlos neu gestartet zu werden.

use std::time::Duration;

/// Abstaende vor dem 1., 2. und 3. Neustart.
pub const ABSTAENDE: [Duration; 3] = [
    Duration::from_secs(5),
    Duration::from_secs(10),
    Duration::from_secs(20),
];

#[derive(Debug, Clone)]
pub struct NeustartBudget {
    verbraucht: usize,
    abstaende: Vec<Duration>,
}

impl Default for NeustartBudget {
    fn default() -> Self {
        Self::new(ABSTAENDE.to_vec())
    }
}

impl NeustartBudget {
    pub fn new(abstaende: Vec<Duration>) -> Self {
        Self {
            verbraucht: 0,
            abstaende,
        }
    }

    /// Verbraucht einen Versuch und nennt die Wartezeit davor – oder `None`,
    /// wenn das Budget erschoepft ist.
    pub fn naechster_versuch(&mut self) -> Option<Duration> {
        let abstand = self.abstaende.get(self.verbraucht).copied()?;
        self.verbraucht += 1;
        Some(abstand)
    }

    /// Nach einer gesunden Identitaetspruefung.
    pub fn zuruecksetzen(&mut self) {
        self.verbraucht = 0;
    }

    pub fn verbraucht(&self) -> usize {
        self.verbraucht
    }

    pub fn gesamt(&self) -> usize {
        self.abstaende.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drei_versuche_mit_wachsendem_abstand() {
        let mut b = NeustartBudget::default();
        assert_eq!(b.naechster_versuch(), Some(Duration::from_secs(5)));
        assert_eq!(b.naechster_versuch(), Some(Duration::from_secs(10)));
        assert_eq!(b.naechster_versuch(), Some(Duration::from_secs(20)));
        assert_eq!(b.naechster_versuch(), None);
        assert_eq!(b.naechster_versuch(), None, "bleibt erschoepft");
        assert_eq!(b.verbraucht(), 3);
        assert_eq!(b.gesamt(), 3);
    }

    #[test]
    fn zuruecksetzen_nach_gesunder_pruefung() {
        let mut b = NeustartBudget::default();
        b.naechster_versuch();
        b.naechster_versuch();
        b.zuruecksetzen();
        assert_eq!(b.verbraucht(), 0);
        assert_eq!(b.naechster_versuch(), Some(Duration::from_secs(5)));
    }

    #[test]
    fn erschoepftes_budget_laesst_sich_zuruecksetzen() {
        let mut b = NeustartBudget::default();
        while b.naechster_versuch().is_some() {}
        b.zuruecksetzen();
        assert!(b.naechster_versuch().is_some());
    }
}
