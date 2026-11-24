//! Der selbst gestartete Dienst-Prozess – und nur der.
//!
//! Unter Windows kommt das Kind sofort nach dem Start in ein eigenes
//! Job-Objekt mit `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Prozesse, die das Kind
//! startet (der Neustart in der Rechenumgebung im lokalen Modus, der echte
//! Interpreter hinter dem `python.exe` einer virtuellen Umgebung), landen
//! automatisch im selben Job. Beenden heisst deshalb: diesen Job beenden –
//! also genau den eigenen Prozessbaum, nie etwas per Programmname. Stuerzt das
//! Fenster ab, schliesst Windows den Job-Griff und beendet den Baum ebenfalls
//! (zusaetzlich zur Elternwache des Dienstes, `VERMERK_ELTERN_PID`).
//!
//! Ausnahme: `JOB_OBJECT_LIMIT_BREAKAWAY_OK` erlaubt einem Prozess, den der
//! Dienst ausdruecklich mit `CREATE_BREAKAWAY_FROM_JOB` startet, den Job zu
//! verlassen. So starten Ollama (`ollama serve`) und sein Installer
//! (`utils/prozess.py`, `ausserhalb_des_jobs_starten`): Sie sollen das Fenster
//! und einen Neustart des Dienstes ueberleben. Alles andere bleibt im Job.
//!
//! Bekannte Luecke: Zwischen dem Start des Kindes und der Zuordnung zum Job
//! liegen Mikrosekunden. Ein Enkel, der in dieser Zeit entstuende, waere nicht
//! im Job – Python braucht aber weit laenger, bis es irgendetwas startet.

use std::io;
use std::process::{Child, Command, ExitStatus};
use std::time::{Duration, Instant};

/// Kein Konsolenfenster fuer den Dienst.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub struct KindProzess {
    kind: Child,
    #[cfg(windows)]
    job: Option<job::Job>,
    beendet: bool,
}

impl KindProzess {
    /// Startet `befehl` ohne Konsolenfenster und ordnet ihn dem Job zu.
    pub fn starten(befehl: &mut Command) -> io::Result<Self> {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            befehl.creation_flags(CREATE_NO_WINDOW);
        }
        let kind = befehl.spawn()?;
        #[cfg(windows)]
        let job = match job::Job::fuer(&kind) {
            Ok(j) => Some(j),
            Err(e) => {
                log::warn!("Dienst konnte keinem Job-Objekt zugeordnet werden: {e}");
                None
            }
        };
        Ok(Self {
            kind,
            #[cfg(windows)]
            job,
            beendet: false,
        })
    }

    pub fn pid(&self) -> u32 {
        self.kind.id()
    }

    /// `Some(status)`, sobald das Kind beendet ist.
    pub fn status(&mut self) -> io::Result<Option<ExitStatus>> {
        self.kind.try_wait()
    }

    /// Gehoert `pid` zu diesem Prozessbaum? `None`: nicht feststellbar.
    pub fn gehoert_dazu(&self, pid: u32) -> Option<bool> {
        if pid == self.kind.id() {
            return Some(true);
        }
        #[cfg(windows)]
        {
            if let Some(job) = &self.job {
                if job.enthaelt(pid) == Some(true) {
                    return Some(true);
                }
            }
            let tabelle = baum::eltern_tabelle()?;
            Some(crate::port_datei::ist_nachfahre_in(
                pid,
                self.kind.id(),
                |p| tabelle.get(&p).copied(),
                8,
            ))
        }
        #[cfg(not(windows))]
        {
            None
        }
    }

    /// Beendet den ganzen Prozessbaum und wartet, bis er weg ist.
    pub fn beenden_und_warten(&mut self, zeitlimit: Duration) {
        if self.beendet {
            return;
        }
        self.beendet = true;
        let pid = self.kind.id();
        #[cfg(windows)]
        if let Some(job) = &self.job {
            job.beenden();
        }
        // Falls die Job-Zuordnung fehlte (oder nicht Windows): das Kind selbst.
        let _ = self.kind.kill();
        let start = Instant::now();
        loop {
            match self.kind.try_wait() {
                Ok(Some(_)) | Err(_) => break,
                Ok(None) if start.elapsed() >= zeitlimit => {
                    log::error!("Dienst (PID {pid}) hat sich nach {zeitlimit:?} nicht beendet");
                    break;
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            }
        }
        #[cfg(windows)]
        if let Some(job) = &self.job {
            while job.aktive_prozesse().unwrap_or(0) > 0 {
                if start.elapsed() >= zeitlimit {
                    log::error!("Prozesse des Dienstes laufen nach {zeitlimit:?} noch");
                    break;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        }
        log::info!("Dienst (PID {pid}) beendet");
    }
}

impl Drop for KindProzess {
    fn drop(&mut self) {
        self.beenden_und_warten(Duration::from_secs(5));
    }
}

#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use windows_sys::Win32::Foundation::{CloseHandle, FALSE, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, IsProcessInJob,
        JobObjectBasicAccountingInformation, JobObjectExtendedLimitInformation,
        QueryInformationJobObject, SetInformationJobObject, TerminateJobObject,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION};

    /// Grenzen des Jobs: Mit dem Fenster endet der ganze Baum; nur wer
    /// ausdruecklich `CREATE_BREAKAWAY_FROM_JOB` verlangt, darf hinaus.
    pub const GRENZEN: u32 = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;

    pub struct Job(HANDLE);

    // Ein Job-Griff darf aus jedem Faden benutzt werden.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        pub fn fuer(kind: &Child) -> std::io::Result<Self> {
            // SAFETY: Aufrufe der Win32-API mit gueltigen Zeigern/Griffen;
            // jeder Fehler wird geprueft, der Griff in Drop geschlossen.
            unsafe {
                let griff = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if griff.is_null() {
                    return Err(std::io::Error::last_os_error());
                }
                let job = Job(griff);
                let mut grenzen: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                grenzen.BasicLimitInformation.LimitFlags = GRENZEN;
                if SetInformationJobObject(
                    griff,
                    JobObjectExtendedLimitInformation,
                    &grenzen as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                ) == FALSE
                {
                    return Err(std::io::Error::last_os_error());
                }
                if AssignProcessToJobObject(griff, kind.as_raw_handle() as HANDLE) == FALSE {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(job)
            }
        }

        pub fn beenden(&self) {
            // SAFETY: gueltiger Job-Griff.
            unsafe {
                TerminateJobObject(self.0, 1);
            }
        }

        pub fn aktive_prozesse(&self) -> Option<u32> {
            // SAFETY: Struktur passender Groesse, gueltiger Griff.
            unsafe {
                let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
                let ok = QueryInformationJobObject(
                    self.0,
                    JobObjectBasicAccountingInformation,
                    &mut info as *mut _ as *mut core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                    std::ptr::null_mut(),
                );
                (ok != FALSE).then_some(info.ActiveProcesses)
            }
        }

        /// Die tatsaechlich gesetzten Grenzen des Jobs.
        #[cfg(test)]
        pub fn grenzen(&self) -> Option<u32> {
            // SAFETY: Struktur passender Groesse, gueltiger Griff.
            unsafe {
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                let ok = QueryInformationJobObject(
                    self.0,
                    JobObjectExtendedLimitInformation,
                    &mut info as *mut _ as *mut core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                    std::ptr::null_mut(),
                );
                (ok != FALSE).then_some(info.BasicLimitInformation.LimitFlags)
            }
        }

        pub fn enthaelt(&self, pid: u32) -> Option<bool> {
            // SAFETY: Griff wird nach Gebrauch geschlossen.
            unsafe {
                let prozess = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
                if prozess.is_null() {
                    return None;
                }
                let mut drin = FALSE;
                let ok = IsProcessInJob(prozess, self.0, &mut drin);
                CloseHandle(prozess);
                (ok != FALSE).then_some(drin != FALSE)
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            // SAFETY: eigener Griff, genau einmal geschlossen. Mit
            // KILL_ON_JOB_CLOSE endet dabei ein noch laufender Baum.
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[cfg(windows)]
mod baum {
    use std::collections::HashMap;
    use windows_sys::Win32::Foundation::{CloseHandle, FALSE, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };

    /// PID -> Eltern-PID aller laufenden Prozesse.
    pub fn eltern_tabelle() -> Option<HashMap<u32, u32>> {
        // SAFETY: Schnappschuss-Griff wird geschlossen, Struktur mit dwSize.
        unsafe {
            let schnappschuss = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if schnappschuss == INVALID_HANDLE_VALUE {
                return None;
            }
            let mut eintrag: PROCESSENTRY32W = std::mem::zeroed();
            eintrag.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
            let mut tabelle = HashMap::new();
            let mut ok = Process32FirstW(schnappschuss, &mut eintrag);
            while ok != FALSE {
                tabelle.insert(eintrag.th32ProcessID, eintrag.th32ParentProcessID);
                ok = Process32NextW(schnappschuss, &mut eintrag);
            }
            CloseHandle(schnappschuss);
            Some(tabelle)
        }
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    /// Ein Enkel (hier: `ping`, gestartet von `cmd`) ueberlebt das Beenden
    /// nicht – der ganze Job endet, nicht nur das direkte Kind. So verhaelt
    /// sich auch der Neustart des Dienstes in der Rechenumgebung.
    #[test]
    fn enkel_endet_mit_dem_job() {
        let mut befehl = Command::new("cmd");
        befehl.args(["/d", "/c", "ping -n 60 127.0.0.1 >nul"]);
        let mut kind = KindProzess::starten(&mut befehl).expect("cmd startet");
        let kind_pid = kind.pid();
        let start = Instant::now();
        let enkel = loop {
            let tabelle = baum::eltern_tabelle().expect("Prozessliste");
            if let Some((&pid, _)) = tabelle.iter().find(|(_, &eltern)| eltern == kind_pid) {
                break pid;
            }
            assert!(
                start.elapsed() < Duration::from_secs(10),
                "kein Enkel entstanden"
            );
            std::thread::sleep(Duration::from_millis(50));
        };
        assert_eq!(kind.gehoert_dazu(enkel), Some(true));
        assert_eq!(kind.gehoert_dazu(std::process::id()), Some(false));
        kind.beenden_und_warten(Duration::from_secs(10));
        let tabelle = baum::eltern_tabelle().expect("Prozessliste");
        assert!(!tabelle.contains_key(&kind_pid), "Kind laeuft noch");
        assert!(!tabelle.contains_key(&enkel), "Enkel laeuft noch");
    }

    /// Der Job endet mit dem Fenster, laesst aber ausdruecklich losgeloeste
    /// Prozesse hinaus (Ollama und sein Installer starten mit
    /// `CREATE_BREAKAWAY_FROM_JOB`). Ohne `BREAKAWAY_OK` erbten sie den Job
    /// und endeten mit dem Fenster – auch mitten in der Installation.
    #[test]
    fn job_erlaubt_ausdrueckliches_verlassen() {
        use windows_sys::Win32::System::JobObjects::{
            JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
            JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK,
        };
        let mut befehl = Command::new("cmd");
        befehl.args(["/d", "/c", "ping -n 30 127.0.0.1 >nul"]);
        let mut kind = KindProzess::starten(&mut befehl).expect("cmd startet");
        let grenzen = kind
            .job
            .as_ref()
            .and_then(|job| job.grenzen())
            .expect("Grenzen lesbar");
        kind.beenden_und_warten(Duration::from_secs(10));
        assert_ne!(grenzen & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, 0);
        assert_ne!(grenzen & JOB_OBJECT_LIMIT_BREAKAWAY_OK, 0);
        // Nur auf Verlangen: Ohne das Flag bleibt jeder Enkel im Job.
        assert_eq!(grenzen & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK, 0);
    }
}
