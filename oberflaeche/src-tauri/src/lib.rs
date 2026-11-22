//! VERMERK – Desktop-Fenster (Tauri 2).
//!
//! Das Fenster startet den Python-Dienst (`protokoll_assistent.api`), fuehrt
//! den Handschlag ueber eine Portdatei, prueft die Identitaet mit dem
//! Schluessel und reicht der Oberflaeche ueber den Befehl `zugang` die
//! aktuelle Basis-URL samt Schluessel. Regeln: ARCHITEKTUR.md.

pub mod dienst_pfad;
pub mod http;
pub mod identitaet;
pub mod kompat;
pub mod neustart;
pub mod port_datei;
pub mod protokoll;
pub mod prozess;
pub mod schluessel;
pub mod ueberwachung;

mod fenster;

pub use fenster::run;
