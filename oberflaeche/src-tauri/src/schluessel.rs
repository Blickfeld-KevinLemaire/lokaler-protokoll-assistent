//! Schluessel fuer die Programmschnittstelle: einmal je Fensterprozess
//! erzeugt (32 Zufallsbytes, base64url ohne Auffuellung), bei Neustarts des
//! Dienstes wiederverwendet. Er steht nur in der Umgebung des Kindes
//! (`VERMERK_API_SCHLUESSEL`), nie auf der Befehlszeile und nie im Protokoll.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;

pub fn erzeugen() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("Kein Zufall vom System: {e}"))?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

/// Zufaellige Hex-Zeichen fuer eindeutige Dateinamen.
pub fn kennung(laenge_bytes: usize) -> String {
    let mut bytes = vec![0u8; laenge_bytes];
    if getrandom::fill(&mut bytes).is_err() {
        // Notfalls Zeit – eindeutig genug fuer einen Dateinamen.
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or_default();
        return format!("{nanos:x}");
    }
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schluessel_ist_base64url_mit_256_bit() {
        let s = erzeugen().unwrap();
        assert_eq!(s.len(), 43);
        assert!(s
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
        assert_ne!(s, erzeugen().unwrap());
    }

    #[test]
    fn kennung_ist_hex() {
        let k = kennung(8);
        assert_eq!(k.len(), 16);
        assert!(k.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
