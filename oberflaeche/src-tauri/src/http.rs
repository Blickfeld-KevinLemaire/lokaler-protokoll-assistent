//! Kleinster HTTP-Client fuer genau zwei Anfragen an den eigenen Dienst:
//! `GET /api/info` (mit Schluessel) und `GET /api/gesundheit` (ohne).
//!
//! Absichtlich ohne HTTP-Bibliothek: Es geht nur an `127.0.0.1`, nur um den
//! Statuscode, und so bleibt die EXE klein und ohne TLS-Stapel.

use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::time::Duration;

/// Fehler auf dem Weg zum Dienst (kein Statuscode erhalten).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HttpFehler {
    /// Verbindung abgelehnt, Zeitueberschreitung, abgebrochen.
    Verbindung(String),
    /// Antwort war kein HTTP.
    Antwort(String),
}

impl std::fmt::Display for HttpFehler {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Verbindung(t) => write!(f, "keine Verbindung: {t}"),
            Self::Antwort(t) => write!(f, "keine gültige HTTP-Antwort: {t}"),
        }
    }
}

/// Liest den Statuscode aus der ersten Zeile einer HTTP-Antwort.
pub fn statuszeile_lesen(anfang: &[u8]) -> Result<u16, HttpFehler> {
    let text = String::from_utf8_lossy(anfang);
    let zeile = text
        .split("\r\n")
        .next()
        .filter(|_| text.contains("\r\n"))
        .ok_or_else(|| HttpFehler::Antwort("Statuszeile unvollständig".into()))?;
    let mut teile = zeile.split(' ');
    let protokoll = teile.next().unwrap_or_default();
    if !protokoll.starts_with("HTTP/1.") {
        return Err(HttpFehler::Antwort(format!("unerwartet: {zeile:.40}")));
    }
    teile
        .next()
        .and_then(|c| c.parse::<u16>().ok())
        .filter(|c| (100..=599).contains(c))
        .ok_or_else(|| HttpFehler::Antwort(format!("kein Statuscode: {zeile:.40}")))
}

/// Baut die Anfrage. Der Schluessel steht nur in der Kopfzeile.
pub fn anfrage_bauen(port: u16, pfad: &str, schluessel: Option<&str>) -> String {
    let mut anfrage = format!(
        "GET {pfad} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUser-Agent: VERMERK-Fenster\r\nAccept: application/json\r\nConnection: close\r\n"
    );
    if let Some(s) = schluessel {
        anfrage.push_str(&format!("Authorization: Bearer {s}\r\n"));
    }
    anfrage.push_str("\r\n");
    anfrage
}

/// `GET http://127.0.0.1:<port><pfad>` und nur den Statuscode zurueckgeben.
pub fn get_status(
    port: u16,
    pfad: &str,
    schluessel: Option<&str>,
    zeitlimit: Duration,
) -> Result<u16, HttpFehler> {
    let adresse = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut strom = TcpStream::connect_timeout(&adresse, zeitlimit)
        .map_err(|e| HttpFehler::Verbindung(e.to_string()))?;
    strom
        .set_read_timeout(Some(zeitlimit))
        .and_then(|_| strom.set_write_timeout(Some(zeitlimit)))
        .map_err(|e| HttpFehler::Verbindung(e.to_string()))?;
    strom
        .write_all(anfrage_bauen(port, pfad, schluessel).as_bytes())
        .map_err(|e| HttpFehler::Verbindung(e.to_string()))?;
    let mut puffer = Vec::with_capacity(256);
    let mut stueck = [0u8; 256];
    while !puffer.windows(2).any(|w| w == b"\r\n") && puffer.len() < 2048 {
        let n = strom
            .read(&mut stueck)
            .map_err(|e| HttpFehler::Verbindung(e.to_string()))?;
        if n == 0 {
            break;
        }
        puffer.extend_from_slice(&stueck[..n]);
    }
    if puffer.is_empty() {
        return Err(HttpFehler::Verbindung(
            "Verbindung ohne Antwort geschlossen".into(),
        ));
    }
    statuszeile_lesen(&puffer)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    #[test]
    fn statuszeilen() {
        assert_eq!(statuszeile_lesen(b"HTTP/1.1 200 OK\r\n"), Ok(200));
        assert_eq!(
            statuszeile_lesen(b"HTTP/1.0 401 Unauthorized\r\nx: y\r\n\r\n"),
            Ok(401)
        );
        assert_eq!(statuszeile_lesen(b"HTTP/1.1 404\r\n"), Ok(404));
        assert!(statuszeile_lesen(b"HTTP/1.1 200 OK").is_err());
        assert!(statuszeile_lesen(b"SSH-2.0-OpenSSH\r\n").is_err());
        assert!(statuszeile_lesen(b"HTTP/1.1 abc\r\n").is_err());
        assert!(statuszeile_lesen(b"HTTP/1.1 999 X\r\n").is_err());
    }

    #[test]
    fn anfrage_traegt_schluessel_nur_wenn_gegeben() {
        let mit = anfrage_bauen(5, "/api/info", Some("geheim"));
        assert!(mit.starts_with("GET /api/info HTTP/1.1\r\nHost: 127.0.0.1:5\r\n"));
        assert!(mit.contains("Authorization: Bearer geheim\r\n"));
        assert!(mit.ends_with("\r\n\r\n"));
        assert!(!anfrage_bauen(5, "/api/gesundheit", None).contains("Authorization"));
    }

    fn einmal_antworten(antwort: &'static [u8]) -> (u16, thread::JoinHandle<String>) {
        let lauscher = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = lauscher.local_addr().unwrap().port();
        let faden = thread::spawn(move || {
            let (mut s, _) = lauscher.accept().unwrap();
            let mut puffer = [0u8; 1024];
            let n = s.read(&mut puffer).unwrap();
            s.write_all(antwort).unwrap();
            String::from_utf8_lossy(&puffer[..n]).into_owned()
        });
        (port, faden)
    }

    #[test]
    fn echter_austausch() {
        let (port, faden) =
            einmal_antworten(b"HTTP/1.1 401 Unauthorized\r\ncontent-length: 0\r\n\r\n");
        let status = get_status(port, "/api/info", Some("k"), Duration::from_secs(5));
        assert_eq!(status, Ok(401));
        assert!(faden.join().unwrap().contains("Authorization: Bearer k"));
    }

    #[test]
    fn niemand_lauscht() {
        let port = {
            let l = TcpListener::bind("127.0.0.1:0").unwrap();
            l.local_addr().unwrap().port()
        };
        assert!(matches!(
            get_status(port, "/api/gesundheit", None, Duration::from_secs(2)),
            Err(HttpFehler::Verbindung(_))
        ));
    }
}
