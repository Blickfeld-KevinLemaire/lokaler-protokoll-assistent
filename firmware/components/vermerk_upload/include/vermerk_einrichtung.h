#pragma once

/* Einrichtung ueber USB (GERAETE-SCHNITTSTELLE.md, Abschnitt "Einrichtung ueber USB", Version 1):
 * reiner C-Teil ohne ESP-IDF, auf dem PC getestet (test/host/).
 *
 * Die Software schickt Zeilen wie "#VERMERK SETZE pc_url 687474703a2f2f..." ueber die serielle
 * Konsole. Hier wird jede Zeile gelesen, jeder Wert geprueft, die ganze Einrichtung beim Speichern
 * geprueft und die Antwort gebaut. Lesen der Konsole, NVS und Neustart: vermerk_konsole.c. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "vermerk_protokoll.h"

#ifdef __cplusplus
extern "C" {
#endif

#define VERMERK_ZEILE_MAX         512     /* Zeichen je Anweisung, ohne Zeilenende */
#define VERMERK_SSID_MAX          32
#define VERMERK_PASSWORT_MIN      8
#define VERMERK_PASSWORT_MAX      63
#define VERMERK_EINR_URL_MAX      96
#define VERMERK_NUMMER_MAX        999999999u
#define VERMERK_KONFIG_VERSION    1u
/* INFO kann laenger als VERMERK_ZEILE_MAX werden (zwei Adressen mit je 96 Bytes als Hex) */
#define VERMERK_INFO_MAX          768

/* Eine Einrichtung. Liegt so als ein Eintrag (Blob) im NVS: ein Schreibvorgang, alles oder nichts. */
typedef struct {
    uint32_t version;                                 /* VERMERK_KONFIG_VERSION */
    uint32_t erste_nummer;                            /* 0 = nicht gesetzt: dann gilt der einkompilierte Wert */
    char wlan_ssid[VERMERK_SSID_MAX + 1];
    char wlan_passwort[VERMERK_PASSWORT_MAX + 1];
    char pc_url[VERMERK_EINR_URL_MAX + 1];
    char pc_token[VERMERK_TOKEN_MAX + 1];
    char server_url[VERMERK_EINR_URL_MAX + 1];
    char server_token[VERMERK_TOKEN_MAX + 1];
} vermerk_konfig_t;

typedef enum {
    VERMERK_SCHLUESSEL_WLAN_SSID = 0,
    VERMERK_SCHLUESSEL_WLAN_PASSWORT,
    VERMERK_SCHLUESSEL_PC_URL,
    VERMERK_SCHLUESSEL_PC_TOKEN,
    VERMERK_SCHLUESSEL_SERVER_URL,
    VERMERK_SCHLUESSEL_SERVER_TOKEN,
    VERMERK_SCHLUESSEL_ERSTE_NUMMER,
    VERMERK_SCHLUESSEL_ANZAHL
} vermerk_schluessel_t;

/* "wlan_ssid" ... -> Schluessel; -1 = unbekannt. name muss nicht mit 0 enden. */
int vermerk_schluessel_finden(const char *name, size_t laenge);
const char *vermerk_schluessel_name(vermerk_schluessel_t schluessel);

/* Hex (gerade Anzahl, 0-9 a-f, auch A-F) nach Bytes. false bei ungueltigem Zeichen, ungerader Laenge
 * oder wenn mehr als ziel_groesse Bytes herauskaemen. */
bool vermerk_hex_lesen(const char *hex, size_t hex_laenge, uint8_t *ziel, size_t ziel_groesse, size_t *laenge);

/* Einen Wert pruefen (Grenzen aus der Spezifikation). NULL = in Ordnung, sonst lesbarer Fehlertext. */
const char *vermerk_wert_pruefen(vermerk_schluessel_t schluessel, const uint8_t *wert, size_t laenge);

/* Wert pruefen und in k eintragen. NULL = in Ordnung, sonst Fehlertext (k bleibt unveraendert). */
const char *vermerk_wert_setzen(vermerk_konfig_t *k, vermerk_schluessel_t schluessel, const uint8_t *wert, size_t laenge);

/* Die ganze Einrichtung pruefen: jedes Feld, WLAN-Name Pflicht, Token Pflicht zu jeder gesetzten
 * Adresse, mindestens ein vollstaendiges Ziel. Auch fuer das, was aus dem NVS kommt.
 * NULL = in Ordnung, sonst Fehlertext. */
const char *vermerk_konfig_pruefen(const vermerk_konfig_t *k);

/* Antwort auf INFO (kompaktes JSON). Passwort und Token kommen nie hinein, nur ob sie gesetzt sind. */
typedef struct {
    const char *geraete_id;
    const char *board;
    const char *firmware;       /* nur die Version, z. B. "1.0.0" */
    bool eingerichtet;
    const char *wlan_ssid;
    const char *pc_url;
    const char *server_url;
    bool token_pc;
    bool token_server;
} vermerk_info_t;

bool vermerk_info_json(const vermerk_info_t *info, char *ziel, size_t ziel_groesse);

/* ---- Zeilen der Software ---- */

typedef struct {
    vermerk_konfig_t werte;    /* vorgemerkt mit SETZE, noch nicht gespeichert */
} vermerk_vormerkung_t;

void vermerk_vormerkung_leeren(vermerk_vormerkung_t *v);

typedef enum {
    VERMERK_ZEILE_UEBERGEHEN = 0,   /* keine Anweisung an uns: nichts antworten */
    VERMERK_ZEILE_ANTWORT,          /* antwort senden, sonst nichts */
    VERMERK_ZEILE_INFO,             /* INFO zusammenstellen und senden */
    VERMERK_ZEILE_SPEICHERN,        /* v->werte ist geprueft: speichern, OK senden, neu starten */
    VERMERK_ZEILE_LOESCHEN          /* Einrichtung loeschen, OK senden, neu starten */
} vermerk_zeile_t;

/* Eine Zeile (ohne Zeilenende) verarbeiten. zu_lang: die Zeile war laenger als VERMERK_ZEILE_MAX und
 * wurde abgeschnitten. aufnahme_laeuft: SPEICHERN und LOESCHEN werden dann abgelehnt.
 * antwort bekommt bei VERMERK_ZEILE_ANTWORT die ganze Antwortzeile ("#VERMERK OK ..." /
 * "#VERMERK FEHLER ..."), ohne Zeilenende. */
vermerk_zeile_t vermerk_zeile_verarbeiten(vermerk_vormerkung_t *v, const char *zeile, size_t laenge, bool zu_lang,
                                          bool aufnahme_laeuft, char *antwort, size_t antwort_groesse);

#ifdef __cplusplus
}
#endif
