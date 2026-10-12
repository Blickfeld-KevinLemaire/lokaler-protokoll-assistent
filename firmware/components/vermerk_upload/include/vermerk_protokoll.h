#pragma once

/* Reiner C-Teil der Geraete-Schnittstelle (protokoll_assistent/GERAETE-SCHNITTSTELLE.md, Version 1).
 *
 * Hier steht alles, was sich ohne Netzwerk und ohne ESP-IDF pruefen laesst: Antworten auslesen,
 * Dateinamen pruefen, Wartezeiten berechnen und entscheiden, wie es nach einer Antwort weitergeht.
 * Keine ESP-IDF-Includes: die Datei wird auf dem PC mit gcc getestet (test/host/). */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Groesse eines Stuecks (ein PUT). Die Spezifikation nennt 256 KiB; meldet die Software in
 * /hallo ein kleineres teil_max_bytes, gilt das. Gestreamt wird aus einem kleinen Puffer. */
#define VERMERK_TEIL_BYTES          (256u * 1024u)

#define VERMERK_NAME_MAX_STAMM      64      /* Zeichen vor der Endung */
#define VERMERK_TOKEN_MAX           128     /* laenger nimmt die Firmware nicht an */
#define VERMERK_SHA256_HEX_GROESSE  65      /* 64 Hex-Zeichen + Nullbyte */
#define VERMERK_GERAETE_ID_GROESSE  13      /* MAC: 12 Hex-Zeichen + Nullbyte */

/* Wartezeit vor dem naechsten Versuch einer Datei: 5 s, dann doppelt so lang, hoechstens 5 min */
#define VERMERK_WARTEZEIT_START_MS  5000u
#define VERMERK_WARTEZEIT_MAX_MS    300000u

/* ---- Pruefungen ---- */

/* Dateiname nach Spezifikation: Buchstaben (A-Z, a-z), Ziffern, '_' und '-', 1 bis 64 Zeichen,
 * dann genau eine Endung aus .opus, .ogg, .wav, .mp3 (klein geschrieben). */
bool vermerk_name_gueltig(const char *name);

/* Token: 1 bis VERMERK_TOKEN_MAX sichtbare ASCII-Zeichen ohne Leerzeichen
 * (es landet unveraendert in der Kopfzeile Authorization). */
bool vermerk_token_gueltig(const char *token);

/* Nummer aus einem Aufnahmenamen "H5_<Nummer>.<endung>" (H/h, Endung ohne Punkt, Gross-/Kleinschreibung
 * egal). 1 bis 9 Ziffern, also hoechstens 999999999. Anderes: false. */
bool vermerk_aufnahme_nummer(const char *dateiname, const char *endung, uint32_t *nummer);

/* Nummer aufsteigend und ohne Doppelte in liste[0..*anzahl) einfuegen, hoechstens max Eintraege.
 * Ist die Liste voll, bleiben die kleinsten Nummern (die groesste faellt heraus). So sammelt der
 * Upload-Manager aus einem Verzeichnis die naechsten Aufnahmen, egal wie viele dort liegen. */
void vermerk_nummer_einfuegen(uint32_t *liste, int *anzahl, int max, uint32_t nummer);

/* ---- Antworten lesen ----
 * Die Software antwortet mit kompaktem JSON ohne Leerzeichen. Gelesen wird per Textsuche, immer nur
 * innerhalb von text[0..laenge) (der Text muss nicht mit 0 enden). Ein Schluessel zaehlt nur, wenn
 * davor '{' oder ',' steht und danach ':' - so trifft die Suche nie Text innerhalb eines Werts. */

/* Nicht-negative ganze Zahl. Kein Vorzeichen, keine fuehrenden Nullen ausser "0", kein Ueberlauf;
 * danach muss ',' oder '}' folgen. */
bool vermerk_json_zahl(const char *text, size_t laenge, const char *schluessel, uint64_t *wert);

/* 1 = true, 0 = false, -1 = fehlt oder ungueltig */
int vermerk_json_wahrheitswert(const char *text, size_t laenge, const char *schluessel);

/* Antwort von GET /api/v1/hallo: true nur mit "dienst":"protokoll-assistent" und "schnittstelle":1.
 * teil_max_bytes (darf NULL sein) bekommt den gemeldeten Wert oder 0, wenn er fehlt/ungueltig ist. */
bool vermerk_hallo_pruefen(const char *text, size_t laenge, uint32_t *teil_max_bytes);

/* Stueckgroesse: VERMERK_TEIL_BYTES, oder weniger, wenn die Software weniger annimmt (0 = unbekannt) */
uint32_t vermerk_teil_bytes(uint32_t teil_max_server);

/* Bytes als Hex-Text, klein geschrieben, mit Nullbyte. false, wenn ziel zu klein ist. */
bool vermerk_hex(const uint8_t *daten, size_t laenge, char *ziel, size_t ziel_groesse);

/* Geraete-Id fuer X-Geraete-Id: die 6 Bytes der Werks-MAC als 12 Hex-Zeichen, klein, ohne Trenner */
bool vermerk_mac_hex(const uint8_t mac[6], char *ziel, size_t ziel_groesse);

/* ---- Ablauf ---- */

typedef enum {
    VERMERK_PHASE_STATUS = 0,   /* GET  /api/v1/aufnahmen/<Name> */
    VERMERK_PHASE_TEIL,         /* PUT  mit Daten, ohne Abschluss-Kopfzeilen */
    VERMERK_PHASE_ABSCHLUSS     /* PUT  mit X-Gesamtgroesse und X-SHA256 */
} vermerk_phase_t;

typedef enum {
    VERMERK_AKTION_WEITER_AB = 0,  /* ab naechstes_byte weitersenden */
    VERMERK_AKTION_FERTIG,         /* Software hat die Datei vollstaendig: lokale Kopie darf weg */
    VERMERK_AKTION_VON_VORN,       /* 422: Teilstand verworfen, einmal ab Byte 0 neu */
    VERMERK_AKTION_SPAETER,        /* voruebergehend (Netz, 503, 507, ...): spaeter, wachsende Wartezeit */
    VERMERK_AKTION_AUFGEBEN        /* hilft so nicht (401, 413, ...): fuer jetzt aufgeben, lange Wartezeit */
} vermerk_aktion_t;

typedef struct {
    vermerk_aktion_t aktion;
    uint64_t naechstes_byte;   /* nur bei VERMERK_AKTION_WEITER_AB */
} vermerk_entscheidung_t;

/* Was nach einer Antwort zu tun ist. http_status 0 = keine Antwort (Netzwerkfehler).
 * von_vorn_versucht: diese Datei hat in diesem Versuch schon einmal von vorn begonnen.
 * "fertig":true zaehlt nur beim Abschluss - nur dann hat die Software Groesse und Pruefsumme geprueft. */
vermerk_entscheidung_t vermerk_entscheiden(vermerk_phase_t phase, int http_status,
                                           const char *text, size_t laenge, bool von_vorn_versucht);

/* Ergebnis eines Upload-Versuchs fuer den Upload-Manager */
typedef enum {
    VERMERK_ERGEBNIS_FERTIG = 0,   /* Software meldet "fertig":true */
    VERMERK_ERGEBNIS_SPAETER,      /* diese Datei spaeter erneut (wachsende Wartezeit) */
    VERMERK_ERGEBNIS_AUFGEBEN,     /* diese Datei spaeter erneut (gleich die lange Wartezeit) */
    VERMERK_ERGEBNIS_KEIN_ZIEL,    /* kein Ziel erreichbar: Durchgang beenden */
    VERMERK_ERGEBNIS_UNTERBROCHEN  /* vom Aufrufer abgebrochen (neue Aufnahme): ohne Wartezeit spaeter weiter */
} vermerk_ergebnis_t;

const char *vermerk_ergebnis_text(vermerk_ergebnis_t ergebnis);

/* Wartezeit nach fehlversuche gescheiterten Versuchen: 0 -> 0, 1 -> 5 s, 2 -> 10 s ... hoechstens 5 min */
uint32_t vermerk_wartezeit_ms(uint32_t fehlversuche);

/* ---- Warteliste: Wartezeit je Datei, nur im RAM ----
 * Eine Datei, die scheitert, wartet; die anderen gehen weiter. Nach einem Neustart beginnt alles
 * ohne Wartezeit. Ist die Liste voll, ersetzt ein neuer Eintrag den, der am fruehesten wieder dran ist. */

#define VERMERK_WARTELISTE_PLAETZE  16

typedef struct {
    uint32_t nummer;               /* Aufnahme-Nummer (H5_<nummer>) */
    uint8_t art;                   /* Endung, z. B. 0 = .opus, 1 = .wav (Sache des Aufrufers) */
    uint8_t fehlversuche;          /* 0 = Platz frei */
    uint64_t naechster_versuch_ms;
} vermerk_wartend_t;

typedef struct {
    vermerk_wartend_t eintrag[VERMERK_WARTELISTE_PLAETZE];
} vermerk_warteliste_t;

void vermerk_warteliste_leeren(vermerk_warteliste_t *liste);
/* Darf diese Datei jetzt versucht werden? */
bool vermerk_warteliste_bereit(const vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art, uint64_t jetzt_ms);
/* Versuch gescheitert: Wartezeit verlaengern (bei VERMERK_ERGEBNIS_AUFGEBEN gleich die laengste).
 * FERTIG, KEIN_ZIEL und UNTERBROCHEN aendern nichts: daran ist nicht die Datei schuld. */
void vermerk_warteliste_fehler(vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art,
                               vermerk_ergebnis_t ergebnis, uint64_t jetzt_ms);
/* Versuch gelungen: Eintrag entfernen */
void vermerk_warteliste_erfolg(vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art);
/* Wie lange die Datei noch wartet (0 = bereit); fuer Meldungen */
uint32_t vermerk_warteliste_rest_ms(const vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art, uint64_t jetzt_ms);

#ifdef __cplusplus
}
#endif
