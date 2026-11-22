//! Die Wache des Dienstes: genau EIN Faden startet den Dienst, fuehrt den
//! Handschlag, prueft die Identitaet, beobachtet das Lebenszeichen und startet
//! im Rahmen des Budgets neu (ARCHITEKTUR.md, "Prozess und Fenster").
//!
//! Ablauf je Versuch:
//! 1. Neue, eindeutige Handschlagdatei im Laufzeitordner (alte geloescht).
//! 2. Dienst starten: `--rolle desktop --port 0 --port-datei <datei>`,
//!    Schluessel und Eltern-PID nur in der Umgebung, kein Konsolenfenster,
//!    Ausgabe in `dienst.log`.
//! 3. Auf die Datei warten – nur solange das Kind lebt, aber **ohne**
//!    Zeitgrenze: Der erste Start im lokalen Modus richtet unter Umstaenden
//!    viele Minuten lang die Rechenumgebung ein. Nach 120 s nur ein Hinweis.
//! 4. Identitaet: `GET /api/info` mit Schluessel muss 200 liefern.
//! 5. `bereit` melden, Budget zuruecksetzen, alle 2 s `/api/gesundheit`;
//!    3 Fehlschlaege in Folge (oder Ende des Kindes) -> `neustart`.

use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::dienst_pfad::DienstQuelle;
use crate::http;
use crate::identitaet::{self, Identitaet};
use crate::neustart::{NeustartBudget, ABSTAENDE};
use crate::port_datei::{self, PortDateiFehler};
use crate::prozess::KindProzess;

/// Name des Tauri-Ereignisses.
pub const EREIGNIS: &str = "dienst-status";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Zustand {
    Startet,
    Bereit,
    Neustart,
    Fehlgeschlagen,
}

/// Nutzlast des Ereignisses `dienst-status`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DienstStatus {
    pub zustand: Zustand,
    pub meldung: String,
    pub basis_url: Option<String>,
}

/// Antwort des Befehls `zugang`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Zugang {
    pub basis_url: String,
    pub schluessel: String,
}

/// Wird bei jedem Zustandswechsel aufgerufen (im Fenster: Tauri-Ereignis).
pub type Melder = Arc<dyn Fn(&DienstStatus) + Send + Sync>;

#[derive(Debug, Clone)]
pub struct Zeiten {
    /// Ab hier ein Hinweis "dauert laenger" (das Kind wird NICHT beendet).
    pub geduld: Duration,
    pub lebenszeichen_abstand: Duration,
    pub max_ausfaelle: u32,
    /// So lange darf der Dienst nach dem Handschlag gar nicht antworten.
    pub identitaet_frist: Duration,
    /// So lange darf die Handschlagdatei unlesbar sein.
    pub ungueltig_frist: Duration,
    pub http_zeitlimit: Duration,
    pub neustart_abstaende: Vec<Duration>,
    pub beenden_zeitlimit: Duration,
}

impl Default for Zeiten {
    fn default() -> Self {
        Self {
            geduld: Duration::from_secs(120),
            lebenszeichen_abstand: Duration::from_secs(2),
            max_ausfaelle: 3,
            identitaet_frist: Duration::from_secs(60),
            ungueltig_frist: Duration::from_secs(5),
            http_zeitlimit: Duration::from_secs(5),
            neustart_abstaende: ABSTAENDE.to_vec(),
            beenden_zeitlimit: Duration::from_secs(10),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Einstellungen {
    pub quelle: DienstQuelle,
    /// Einmal je Fensterprozess erzeugt, bei Neustarts wiederverwendet.
    /// (Bei `DienstQuelle::Extern` gilt dessen Schluessel.)
    pub schluessel: String,
    /// Hier entstehen die Handschlagdateien.
    pub laufzeit_ordner: PathBuf,
    /// Ausgabe des Dienstes (stdout/stderr); `None` = verwerfen.
    pub dienst_log: Option<PathBuf>,
    pub eigene_version: String,
    pub zeiten: Zeiten,
}

/// Ein vorbereiteter Startbefehl (reine Daten, damit er testbar ist).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Startbefehl {
    pub programm: PathBuf,
    pub argumente: Vec<OsString>,
    pub arbeitsordner: PathBuf,
    pub umgebung: Vec<(String, String)>,
}

/// Baut den Befehl. Der Schluessel steht nur in `umgebung`.
pub fn startbefehl(
    quelle: &DienstQuelle,
    port_datei: &Path,
    schluessel: &str,
    eigene_pid: u32,
) -> Option<Startbefehl> {
    let mut argumente: Vec<OsString> = Vec::new();
    let mut umgebung = vec![
        (
            crate::dienst_pfad::UMGEBUNG_SCHLUESSEL.to_string(),
            schluessel.to_string(),
        ),
        ("VERMERK_ELTERN_PID".to_string(), eigene_pid.to_string()),
        ("PYTHONUNBUFFERED".to_string(), "1".to_string()),
        ("PYTHONIOENCODING".to_string(), "utf-8".to_string()),
    ];
    let (programm, arbeitsordner) = match quelle {
        DienstQuelle::Extern { .. } => return None,
        DienstQuelle::Installiert {
            exe,
            anwendungsordner,
        } => {
            // Einstellungen und Daten gehoeren in den Ordner von VERMERK.exe,
            // nicht in den Unterordner 'dienst'.
            umgebung.push((
                "VERMERK_ANWENDUNGSORDNER".to_string(),
                anwendungsordner.display().to_string(),
            ));
            let ordner = exe.parent().map(Path::to_path_buf).unwrap_or_default();
            (exe.clone(), ordner)
        }
        DienstQuelle::Quelltext { python, projekt } => {
            argumente.push("-m".into());
            argumente.push("protokoll_assistent.api".into());
            (python.clone(), projekt.clone())
        }
    };
    argumente.extend([
        OsString::from("--rolle"),
        "desktop".into(),
        "--port".into(),
        "0".into(),
        "--port-datei".into(),
        port_datei.as_os_str().to_owned(),
    ]);
    Some(Startbefehl {
        programm,
        argumente,
        arbeitsordner,
        umgebung,
    })
}

fn basis_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

fn status_text(status: &ExitStatus) -> String {
    match status.code() {
        Some(3) => "Exit-Code 3: kein Port frei/bindbar".to_string(),
        Some(code) => format!("Exit-Code {code}"),
        None => "ohne Exit-Code".to_string(),
    }
}

struct Innen {
    status: DienstStatus,
    zugang: Option<Zugang>,
    beendet: bool,
    kind: Option<KindProzess>,
    port_datei: Option<PathBuf>,
}

struct Geteilt {
    innen: Mutex<Innen>,
    signal: Condvar,
    melder: Melder,
}

impl Geteilt {
    fn sperren(&self) -> MutexGuard<'_, Innen> {
        self.innen.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn ist_beendet(&self) -> bool {
        self.sperren().beendet
    }

    fn melden(&self, zustand: Zustand, meldung: impl Into<String>, zugang: Option<Zugang>) {
        let status = DienstStatus {
            zustand,
            meldung: meldung.into(),
            basis_url: zugang.as_ref().map(|z| z.basis_url.clone()),
        };
        {
            let mut innen = self.sperren();
            if innen.beendet {
                return;
            }
            if innen.status == status && innen.zugang == zugang {
                return;
            }
            innen.status = status.clone();
            innen.zugang = zugang;
        }
        self.signal.notify_all();
        match zustand {
            Zustand::Fehlgeschlagen => {
                log::error!("Dienst: {} – {}", "fehlgeschlagen", status.meldung)
            }
            Zustand::Neustart => log::warn!("Dienst: neustart – {}", status.meldung),
            _ => log::info!(
                "Dienst: {:?} – {}{}",
                zustand,
                status.meldung,
                status
                    .basis_url
                    .as_deref()
                    .map(|u| format!(" ({u})"))
                    .unwrap_or_default()
            ),
        }
        (self.melder)(&status);
    }

    /// Wartet `dauer` (oder bis beendet). `false`, wenn beendet.
    fn warten(&self, dauer: Duration) -> bool {
        let innen = self.sperren();
        let (innen, _) = self
            .signal
            .wait_timeout_while(innen, dauer, |i| !i.beendet)
            .unwrap_or_else(|e| e.into_inner());
        !innen.beendet
    }

    /// Uebernimmt das gestartete Kind. Ist das Fenster inzwischen beendet,
    /// wird es sofort wieder beendet.
    fn kind_setzen(&self, mut kind: KindProzess, zeitlimit: Duration) -> bool {
        let mut innen = self.sperren();
        if innen.beendet {
            drop(innen);
            kind.beenden_und_warten(zeitlimit);
            return false;
        }
        innen.kind = Some(kind);
        true
    }

    fn kind_status(&self) -> Option<Result<ExitStatus, String>> {
        let mut innen = self.sperren();
        let kind = innen.kind.as_mut()?;
        match kind.status() {
            Ok(Some(status)) => Some(Ok(status)),
            Ok(None) => None,
            Err(e) => Some(Err(e.to_string())),
        }
    }

    fn gehoert_dazu(&self, pid: u32) -> Option<bool> {
        self.sperren()
            .kind
            .as_ref()
            .and_then(|k| k.gehoert_dazu(pid))
    }

    fn kind_beenden(&self, zeitlimit: Duration) {
        let kind = self.sperren().kind.take();
        if let Some(mut kind) = kind {
            kind.beenden_und_warten(zeitlimit);
        }
    }

    fn port_datei_setzen(&self, datei: Option<PathBuf>) {
        let alt = std::mem::replace(&mut self.sperren().port_datei, datei);
        if let Some(alt) = alt {
            let _ = fs::remove_file(alt);
        }
    }
}

/// Die Wache. Wird einmal je Fensterprozess angelegt.
pub struct Ueberwachung {
    geteilt: Arc<Geteilt>,
    faden: Mutex<Option<JoinHandle<()>>>,
    beenden_zeitlimit: Duration,
}

impl Ueberwachung {
    /// Startet den (einzigen) Wachfaden.
    pub fn starten(einstellungen: Einstellungen, melder: Melder) -> Arc<Self> {
        let geteilt = Arc::new(Geteilt {
            innen: Mutex::new(Innen {
                status: DienstStatus {
                    zustand: Zustand::Startet,
                    meldung: "Das Fenster startet …".into(),
                    basis_url: None,
                },
                zugang: None,
                beendet: false,
                kind: None,
                port_datei: None,
            }),
            signal: Condvar::new(),
            melder,
        });
        let beenden_zeitlimit = einstellungen.zeiten.beenden_zeitlimit;
        let fuer_faden = Arc::clone(&geteilt);
        let faden = std::thread::Builder::new()
            .name("dienst-wache".into())
            .spawn(move || wache(fuer_faden, einstellungen))
            .expect("Wachfaden fuer den Dienst konnte nicht starten");
        Arc::new(Self {
            geteilt,
            faden: Mutex::new(Some(faden)),
            beenden_zeitlimit,
        })
    }

    /// Ohne Dienst: Es gab schon vor dem Start einen Fehler (z. B. fehlt der
    /// Dienst im Programmordner). `zugang` meldet ihn sofort.
    pub fn fehlgeschlagen(meldung: String) -> Arc<Self> {
        log::error!("Dienst: fehlgeschlagen – {meldung}");
        Arc::new(Self {
            geteilt: Arc::new(Geteilt {
                innen: Mutex::new(Innen {
                    status: DienstStatus {
                        zustand: Zustand::Fehlgeschlagen,
                        meldung,
                        basis_url: None,
                    },
                    zugang: None,
                    beendet: false,
                    kind: None,
                    port_datei: None,
                }),
                signal: Condvar::new(),
                melder: Arc::new(|_| {}),
            }),
            faden: Mutex::new(None),
            beenden_zeitlimit: Duration::from_secs(1),
        })
    }

    pub fn status(&self) -> DienstStatus {
        self.geteilt.sperren().status.clone()
    }

    /// Der AKTUELLE Zugang. Wartet, solange der Dienst startet oder neu
    /// startet; Fehler sofort bei `fehlgeschlagen`, sonst nach `zeitlimit`.
    pub fn zugang_warten(&self, zeitlimit: Duration) -> Result<Zugang, String> {
        let innen = self.geteilt.sperren();
        let (innen, ergebnis) = self
            .geteilt
            .signal
            .wait_timeout_while(innen, zeitlimit, |i| {
                i.zugang.is_none() && !i.beendet && i.status.zustand != Zustand::Fehlgeschlagen
            })
            .unwrap_or_else(|e| e.into_inner());
        if let Some(zugang) = &innen.zugang {
            return Ok(zugang.clone());
        }
        if innen.beendet {
            return Err("Das Fenster wird beendet.".into());
        }
        if innen.status.zustand == Zustand::Fehlgeschlagen {
            return Err(innen.status.meldung.clone());
        }
        debug_assert!(ergebnis.timed_out());
        Err(format!(
            "Der Dienst ist nach {} Minuten noch nicht bereit (Stand: {}). Bitte warten oder VERMERK neu starten.",
            zeitlimit.as_secs() / 60,
            innen.status.meldung
        ))
    }

    /// Beendet den selbst gestarteten Dienst und wartet auf ihn und den
    /// Wachfaden. Mehrfacher Aufruf schadet nicht.
    pub fn beenden(&self) {
        let kind = {
            let mut innen = self.geteilt.sperren();
            innen.beendet = true;
            innen.zugang = None;
            innen.kind.take()
        };
        self.geteilt.signal.notify_all();
        if let Some(mut kind) = kind {
            kind.beenden_und_warten(self.beenden_zeitlimit);
        }
        let faden = self.faden.lock().unwrap_or_else(|e| e.into_inner()).take();
        if let Some(faden) = faden {
            let _ = faden.join();
        }
        // Falls der Wachfaden zwischendurch noch ein Kind gestartet hat.
        self.geteilt.kind_beenden(self.beenden_zeitlimit);
        self.geteilt.port_datei_setzen(None);
    }
}

fn wache(g: Arc<Geteilt>, e: Einstellungen) {
    match e.quelle.clone() {
        DienstQuelle::Extern { port, schluessel } => externe_wache(&g, &e, port, &schluessel),
        _ => kind_wache(&g, &e),
    }
}

fn kind_wache(g: &Geteilt, e: &Einstellungen) {
    let mut budget = NeustartBudget::new(e.zeiten.neustart_abstaende.clone());
    let mut versuch: u32 = 0;
    g.melden(Zustand::Startet, "Der Dienst wird gestartet …", None);
    loop {
        if g.ist_beendet() {
            return;
        }
        versuch += 1;
        let grund = ein_lauf(g, e, versuch, &mut budget);
        if g.ist_beendet() {
            return;
        }
        match budget.naechster_versuch() {
            Some(abstand) => {
                g.melden(
                    Zustand::Neustart,
                    format!(
                        "{grund}. Neuer Versuch {} von {} in {} s.",
                        budget.verbraucht(),
                        budget.gesamt(),
                        abstand.as_secs()
                    ),
                    None,
                );
                g.kind_beenden(e.zeiten.beenden_zeitlimit);
                if !g.warten(abstand) {
                    return;
                }
                g.melden(Zustand::Startet, "Der Dienst wird neu gestartet …", None);
            }
            None => {
                g.kind_beenden(e.zeiten.beenden_zeitlimit);
                g.melden(
                    Zustand::Fehlgeschlagen,
                    format!(
                        "Der Dienst ließ sich nicht starten: {grund}. Nach {} Neustarts wird es nicht weiter versucht – bitte VERMERK neu starten. Einzelheiten im Protokoll.",
                        budget.gesamt()
                    ),
                    None,
                );
                return;
            }
        }
    }
}

fn dienst_log_oeffnen(pfad: &Path, versuch: u32, befehl: &Startbefehl) -> Option<File> {
    if let Some(ordner) = pfad.parent() {
        let _ = fs::create_dir_all(ordner);
    }
    let mut datei = OpenOptions::new()
        .create(true)
        .append(true)
        .open(pfad)
        .map_err(|e| {
            log::warn!(
                "Dienst-Protokoll {} nicht beschreibbar: {e}",
                pfad.display()
            )
        })
        .ok()?;
    let zeit =
        time::OffsetDateTime::now_local().unwrap_or_else(|_| time::OffsetDateTime::now_utc());
    let _ = writeln!(
        datei,
        "\n===== {zeit} – Start {versuch}: {} =====",
        befehl.programm.display()
    );
    Some(datei)
}

/// Ein Versuch. Kehrt mit dem Grund zurueck, wenn er endet.
fn ein_lauf(g: &Geteilt, e: &Einstellungen, versuch: u32, budget: &mut NeustartBudget) -> String {
    if let Err(fehler) = fs::create_dir_all(&e.laufzeit_ordner) {
        return format!(
            "Laufzeitordner {} nicht anlegbar: {fehler}",
            e.laufzeit_ordner.display()
        );
    }
    let datei = e.laufzeit_ordner.join(format!(
        "dienst-{}-{versuch}-{}.json",
        std::process::id(),
        crate::schluessel::kennung(6)
    ));
    let _ = fs::remove_file(&datei);
    g.port_datei_setzen(Some(datei.clone()));

    let Some(befehl) = startbefehl(&e.quelle, &datei, &e.schluessel, std::process::id()) else {
        return "Kein Startbefehl für diesen Dienst".into();
    };
    let mut cmd = Command::new(&befehl.programm);
    cmd.args(&befehl.argumente)
        .current_dir(&befehl.arbeitsordner)
        .env_remove(crate::dienst_pfad::UMGEBUNG_EXTERN)
        .stdin(Stdio::null());
    for (name, wert) in &befehl.umgebung {
        cmd.env(name, wert);
    }
    match e
        .dienst_log
        .as_deref()
        .and_then(|p| dienst_log_oeffnen(p, versuch, &befehl))
    {
        Some(log) => match log.try_clone() {
            Ok(zweite) => {
                cmd.stdout(Stdio::from(log)).stderr(Stdio::from(zweite));
            }
            Err(_) => {
                cmd.stdout(Stdio::from(log)).stderr(Stdio::null());
            }
        },
        None => {
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    let argumente: Vec<String> = befehl
        .argumente
        .iter()
        .map(|a| a.to_string_lossy().into_owned())
        .collect();
    let kind = match KindProzess::starten(&mut cmd) {
        Ok(k) => k,
        Err(fehler) => {
            return format!(
                "{} ließ sich nicht starten: {fehler}",
                befehl.programm.display()
            )
        }
    };
    let pid = kind.pid();
    log::info!(
        "Dienst gestartet (Versuch {versuch}, PID {pid}): {} {} (Ordner {})",
        befehl.programm.display(),
        argumente.join(" "),
        befehl.arbeitsordner.display()
    );
    if !g.kind_setzen(kind, e.zeiten.beenden_zeitlimit) {
        return "Fenster beendet".into();
    }

    // Handschlag: warten, solange das Kind lebt – ohne Zeitgrenze.
    let start = Instant::now();
    let mut geduld_gemeldet = false;
    let mut unlesbar_seit: Option<Instant> = None;
    let handschlag = loop {
        if g.ist_beendet() {
            return "Fenster beendet".into();
        }
        if let Some(status) = g.kind_status() {
            return match status {
                Ok(s) => format!(
                    "Der Dienst hat sich vor dem Handschlag beendet ({})",
                    status_text(&s)
                ),
                Err(f) => format!("Zustand des Dienstes unbekannt: {f}"),
            };
        }
        if let Ok(text) = fs::read_to_string(&datei) {
            match port_datei::auswerten_fuer_kind(&text, pid, |p, _| g.gehoert_dazu(p)) {
                Ok(d) => break d,
                Err(f @ PortDateiFehler::FremderProzess { .. }) => return f.to_string(),
                Err(f) => {
                    let seit = *unlesbar_seit.get_or_insert_with(Instant::now);
                    if seit.elapsed() >= e.zeiten.ungueltig_frist {
                        return f.to_string();
                    }
                }
            }
        }
        if !geduld_gemeldet && start.elapsed() >= e.zeiten.geduld {
            geduld_gemeldet = true;
            g.melden(
                Zustand::Startet,
                "Der Dienst braucht länger als üblich. Beim ersten Start im lokalen Modus wird die Rechenumgebung eingerichtet – das kann viele Minuten dauern. Bitte warten.",
                None,
            );
        }
        g.warten(Duration::from_millis(100));
    };
    let port = handschlag.port;
    log::info!(
        "Handschlag: Port {port}, PID {} (gestartet: {pid}), Netz-Port {:?}, Version {}",
        handschlag.pid,
        handschlag.netz_port,
        handschlag.version
    );
    if !identitaet::version_passt(&e.eigene_version, &handschlag.version) {
        log::warn!(
            "Versionen passen nicht: Fenster {}, Dienst {}",
            e.eigene_version,
            handschlag.version
        );
    }

    if let Err(grund) = identitaet_pruefen(g, e, port, &e.schluessel, true) {
        return grund;
    }
    budget.zuruecksetzen();
    log::info!("Identität bestätigt: /api/info auf Port {port} antwortet mit 200");
    let zugang = Zugang {
        basis_url: basis_url(port),
        schluessel: e.schluessel.clone(),
    };
    g.melden(Zustand::Bereit, "Der Dienst ist bereit.", Some(zugang));

    match lebenszeichen_beobachten(g, e, port, true) {
        Some(grund) => grund,
        None => "Fenster beendet".into(),
    }
}

/// `Ok` bei 200 auf `/api/info`. Wiederholt nur, solange gar keine Antwort
/// kommt (und das Kind noch lebt) – hoechstens `identitaet_frist`.
fn identitaet_pruefen(
    g: &Geteilt,
    e: &Einstellungen,
    port: u16,
    schluessel: &str,
    mit_kind: bool,
) -> Result<(), String> {
    let frist = Instant::now() + e.zeiten.identitaet_frist;
    loop {
        let ergebnis =
            http::get_status(port, "/api/info", Some(schluessel), e.zeiten.http_zeitlimit);
        match identitaet::bewerten(&ergebnis) {
            Identitaet::Bestaetigt => return Ok(()),
            Identitaet::NichtErreichbar(grund) if Instant::now() < frist => {
                log::debug!("/api/info auf Port {port} noch nicht erreichbar: {grund}");
                if mit_kind {
                    if let Some(status) = g.kind_status() {
                        let text = status.map(|s| status_text(&s)).unwrap_or_else(|f| f);
                        return Err(format!("Der Dienst hat sich beendet ({text})"));
                    }
                }
                if !g.warten(Duration::from_millis(250)) {
                    return Err("Fenster beendet".into());
                }
            }
            Identitaet::Fremd(status) => {
                return Err(format!(
                    "Auf Port {port} antwortet nicht der eigene Dienst (/api/info: HTTP {status})"
                ))
            }
            Identitaet::KeinHttp(grund) => {
                return Err(format!(
                    "Auf Port {port} antwortet kein HTTP-Dienst ({grund})"
                ))
            }
            Identitaet::NichtErreichbar(grund) => {
                return Err(format!(
                    "Der Dienst antwortet auf Port {port} nicht ({grund})"
                ))
            }
        }
    }
}

/// Beobachtet `/api/gesundheit`. Gibt den Grund zurueck, wenn der Dienst
/// ausfaellt; `None`, wenn das Fenster beendet wird.
fn lebenszeichen_beobachten(
    g: &Geteilt,
    e: &Einstellungen,
    port: u16,
    mit_kind: bool,
) -> Option<String> {
    let mut ausfaelle = 0u32;
    loop {
        if !g.warten(e.zeiten.lebenszeichen_abstand) {
            return None;
        }
        if mit_kind {
            if let Some(status) = g.kind_status() {
                let text = status.map(|s| status_text(&s)).unwrap_or_else(|f| f);
                return Some(format!("Der Dienst wurde unerwartet beendet ({text})"));
            }
        }
        let ergebnis = http::get_status(port, "/api/gesundheit", None, e.zeiten.http_zeitlimit);
        if identitaet::lebt(&ergebnis) {
            if ausfaelle > 0 {
                log::info!("Lebenszeichen wieder da nach {ausfaelle} Ausfällen");
            }
            ausfaelle = 0;
            continue;
        }
        ausfaelle += 1;
        log::warn!(
            "Lebenszeichen {ausfaelle}/{} ausgeblieben: {:?}",
            e.zeiten.max_ausfaelle,
            ergebnis
        );
        if ausfaelle >= e.zeiten.max_ausfaelle {
            return Some(format!(
                "Der Dienst antwortet nicht mehr ({ausfaelle} Lebenszeichen in Folge ausgeblieben)"
            ));
        }
    }
}

/// Zum Entwickeln: einen von Hand gestarteten Dienst benutzen – nie starten,
/// nie beenden. Identitaet wird trotzdem geprueft.
fn externe_wache(g: &Geteilt, e: &Einstellungen, port: u16, schluessel: &str) {
    log::warn!(
        "Externer Dienst (VERMERK_EXTERNER_DIENST): {}",
        basis_url(port)
    );
    loop {
        g.melden(
            Zustand::Startet,
            format!("Warte auf den externen Dienst {} …", basis_url(port)),
            None,
        );
        loop {
            match identitaet_pruefen(g, e, port, schluessel, false) {
                Ok(()) => break,
                Err(grund) => {
                    if g.ist_beendet() {
                        return;
                    }
                    g.melden(
                        Zustand::Fehlgeschlagen,
                        format!("Externer Dienst: {grund}"),
                        None,
                    );
                    if !g.warten(e.zeiten.lebenszeichen_abstand) {
                        return;
                    }
                }
            }
        }
        g.melden(
            Zustand::Bereit,
            "Der externe Dienst ist bereit.",
            Some(Zugang {
                basis_url: basis_url(port),
                schluessel: schluessel.to_string(),
            }),
        );
        match lebenszeichen_beobachten(g, e, port, false) {
            None => return,
            Some(grund) => log::warn!("Externer Dienst: {grund}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn befehl_fuer_installierten_dienst() {
        let quelle = DienstQuelle::Installiert {
            exe: PathBuf::from("C:/App/dienst/vermerk-dienst.exe"),
            anwendungsordner: PathBuf::from("C:/App"),
        };
        let b = startbefehl(&quelle, Path::new("C:/tmp/p.json"), "geheim", 42).unwrap();
        assert_eq!(
            b.programm,
            PathBuf::from("C:/App/dienst/vermerk-dienst.exe")
        );
        assert_eq!(b.arbeitsordner, PathBuf::from("C:/App/dienst"));
        let args: Vec<String> = b
            .argumente
            .iter()
            .map(|a| a.to_string_lossy().into())
            .collect();
        assert_eq!(
            args,
            [
                "--rolle",
                "desktop",
                "--port",
                "0",
                "--port-datei",
                "C:/tmp/p.json"
            ]
        );
        assert!(b
            .umgebung
            .contains(&("VERMERK_ANWENDUNGSORDNER".into(), "C:/App".into())));
        assert!(b
            .umgebung
            .contains(&("VERMERK_ELTERN_PID".into(), "42".into())));
    }

    #[test]
    fn befehl_aus_dem_quelltext() {
        let quelle = DienstQuelle::Quelltext {
            python: PathBuf::from("python"),
            projekt: PathBuf::from("C:/repo"),
        };
        let b = startbefehl(&quelle, Path::new("p.json"), "geheim", 1).unwrap();
        let args: Vec<String> = b
            .argumente
            .iter()
            .map(|a| a.to_string_lossy().into())
            .collect();
        assert_eq!(&args[..2], ["-m", "protokoll_assistent.api"]);
        assert_eq!(b.arbeitsordner, PathBuf::from("C:/repo"));
        assert!(!b
            .umgebung
            .iter()
            .any(|(n, _)| n == "VERMERK_ANWENDUNGSORDNER"));
    }

    #[test]
    fn schluessel_nie_auf_der_befehlszeile() {
        let quelle = DienstQuelle::Quelltext {
            python: PathBuf::from("python"),
            projekt: PathBuf::from("C:/repo"),
        };
        let b = startbefehl(&quelle, Path::new("p.json"), "GEHEIMER-SCHLUESSEL", 1).unwrap();
        assert!(!b
            .argumente
            .iter()
            .any(|a| a.to_string_lossy().contains("GEHEIMER-SCHLUESSEL")));
        assert!(b.umgebung.contains(&(
            "VERMERK_API_SCHLUESSEL".into(),
            "GEHEIMER-SCHLUESSEL".into()
        )));
    }

    #[test]
    fn extern_wird_nie_gestartet() {
        let quelle = DienstQuelle::Extern {
            port: 1,
            schluessel: "k".into(),
        };
        assert_eq!(startbefehl(&quelle, Path::new("p"), "k", 1), None);
    }

    #[test]
    fn ereignis_nutzlast() {
        let s = DienstStatus {
            zustand: Zustand::Neustart,
            meldung: "m".into(),
            basis_url: None,
        };
        assert_eq!(
            serde_json::to_string(&s).unwrap(),
            r#"{"zustand":"neustart","meldung":"m","basis_url":null}"#
        );
        let z = Zugang {
            basis_url: "http://127.0.0.1:5".into(),
            schluessel: "k".into(),
        };
        assert_eq!(
            serde_json::to_string(&z).unwrap(),
            r#"{"basis_url":"http://127.0.0.1:5","schluessel":"k"}"#
        );
    }

    fn sammler() -> (Melder, Arc<Mutex<Vec<DienstStatus>>>) {
        let liste = Arc::new(Mutex::new(Vec::new()));
        let l = Arc::clone(&liste);
        (
            Arc::new(move |s: &DienstStatus| l.lock().unwrap().push(s.clone())),
            liste,
        )
    }

    fn schnelle_zeiten() -> Zeiten {
        Zeiten {
            neustart_abstaende: vec![Duration::from_millis(10); 3],
            ..Zeiten::default()
        }
    }

    /// Ein Programm, das sofort endet, verbraucht das Budget und endet in
    /// `fehlgeschlagen`; `zugang` meldet den Fehler, statt zu haengen.
    #[test]
    fn budget_erschoepft_ergibt_fehlgeschlagen() {
        let ordner =
            std::env::temp_dir().join(format!("vermerk-test-{}", crate::schluessel::kennung(4)));
        let (melder, liste) = sammler();
        let u = Ueberwachung::starten(
            Einstellungen {
                quelle: DienstQuelle::Installiert {
                    exe: PathBuf::from("C:/gibt/es/nicht/vermerk-dienst.exe"),
                    anwendungsordner: PathBuf::from("C:/gibt/es/nicht"),
                },
                schluessel: "k".into(),
                laufzeit_ordner: ordner.clone(),
                dienst_log: None,
                eigene_version: "0".into(),
                zeiten: schnelle_zeiten(),
            },
            melder,
        );
        let fehler = u.zugang_warten(Duration::from_secs(30)).unwrap_err();
        assert!(fehler.contains("nicht starten"), "{fehler}");
        u.beenden();
        let zustaende: Vec<Zustand> = liste.lock().unwrap().iter().map(|s| s.zustand).collect();
        assert_eq!(
            zustaende,
            [
                Zustand::Startet,
                Zustand::Neustart,
                Zustand::Startet,
                Zustand::Neustart,
                Zustand::Startet,
                Zustand::Neustart,
                Zustand::Startet,
                Zustand::Fehlgeschlagen
            ]
        );
        let _ = fs::remove_dir_all(ordner);
    }

    #[test]
    fn externer_dienst_ohne_antwort_meldet_fehler() {
        let port = {
            let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            l.local_addr().unwrap().port()
        };
        let (melder, _liste) = sammler();
        let u = Ueberwachung::starten(
            Einstellungen {
                quelle: DienstQuelle::Extern {
                    port,
                    schluessel: "k".into(),
                },
                schluessel: "unbenutzt".into(),
                laufzeit_ordner: std::env::temp_dir(),
                dienst_log: None,
                eigene_version: "0".into(),
                zeiten: Zeiten {
                    identitaet_frist: Duration::from_millis(200),
                    ..schnelle_zeiten()
                },
            },
            melder,
        );
        let fehler = u.zugang_warten(Duration::from_secs(30)).unwrap_err();
        assert!(fehler.contains("Externer Dienst"), "{fehler}");
        u.beenden();
        assert_eq!(
            u.zugang_warten(Duration::from_millis(10)).unwrap_err(),
            "Das Fenster wird beendet."
        );
    }
}
