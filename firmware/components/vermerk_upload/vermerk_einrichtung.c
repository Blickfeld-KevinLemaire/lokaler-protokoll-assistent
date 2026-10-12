/* Einrichtung ueber USB, reiner C-Teil (siehe vermerk_einrichtung.h). Keine ESP-IDF-Includes. */

#include "vermerk_einrichtung.h"

#include <stdio.h>
#include <string.h>

#define PRAEFIX "#VERMERK"

static const char *const s_namen[VERMERK_SCHLUESSEL_ANZAHL] = {
    "wlan_ssid", "wlan_passwort", "pc_url", "pc_token", "server_url", "server_token", "erste_nummer",
};

int vermerk_schluessel_finden(const char *name, size_t laenge)
{
    if (name == NULL) {
        return -1;
    }
    for (int i = 0; i < VERMERK_SCHLUESSEL_ANZAHL; i++) {
        if (strlen(s_namen[i]) == laenge && memcmp(s_namen[i], name, laenge) == 0) {
            return i;
        }
    }
    return -1;
}

const char *vermerk_schluessel_name(vermerk_schluessel_t schluessel)
{
    return ((int)schluessel >= 0 && schluessel < VERMERK_SCHLUESSEL_ANZAHL) ? s_namen[schluessel] : "?";
}

static int hex_ziffer(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

bool vermerk_hex_lesen(const char *hex, size_t hex_laenge, uint8_t *ziel, size_t ziel_groesse, size_t *laenge)
{
    if ((hex == NULL && hex_laenge > 0) || laenge == NULL || (hex_laenge % 2) != 0 ||
        hex_laenge / 2 > ziel_groesse || (ziel == NULL && hex_laenge > 0)) {
        return false;
    }
    for (size_t i = 0; i < hex_laenge; i += 2) {
        int hoch = hex_ziffer(hex[i]);
        int tief = hex_ziffer(hex[i + 1]);
        if (hoch < 0 || tief < 0) {
            return false;
        }
        ziel[i / 2] = (uint8_t)((hoch << 4) | tief);
    }
    *laenge = hex_laenge / 2;
    return true;
}

/* ---- Werte ---- */

static bool hat_nullbyte(const uint8_t *wert, size_t laenge)
{
    return laenge > 0 && memchr(wert, 0, laenge) != NULL;
}

static const char *url_pruefen(const uint8_t *wert, size_t laenge)
{
    static const char schema[] = "http://";
    const size_t s_len = sizeof(schema) - 1;

    if (laenge == 0) {
        return NULL;   /* Ziel nicht genutzt */
    }
    if (laenge > VERMERK_EINR_URL_MAX) {
        return "Adresse zu lang (hoechstens 96 Bytes)";
    }
    if (laenge <= s_len || memcmp(wert, schema, s_len) != 0) {
        return "Adresse muss mit http:// beginnen";
    }
    for (size_t i = 0; i < laenge; i++) {
        if (wert[i] <= 0x20 || wert[i] >= 0x7F) {
            return "Adresse enthaelt Leer- oder Sonderzeichen";
        }
    }
    if (wert[s_len] == '/') {
        return "Adresse ohne Rechnername";
    }
    if (wert[laenge - 1] == '/') {
        return "Adresse ohne / am Ende angeben";
    }
    return NULL;
}

static const char *nummer_pruefen(const uint8_t *wert, size_t laenge, uint32_t *nummer)
{
    if (laenge == 0) {
        *nummer = 0;
        return NULL;
    }
    if (laenge > 9) {
        return "erste_nummer hat zu viele Ziffern";
    }
    uint32_t n = 0;
    for (size_t i = 0; i < laenge; i++) {
        if (wert[i] < '0' || wert[i] > '9') {
            return "erste_nummer ist keine Dezimalzahl";
        }
        n = n * 10u + (uint32_t)(wert[i] - '0');
    }
    if (n == 0) {
        return "erste_nummer muss mindestens 1 sein";
    }
    *nummer = n;
    return NULL;
}

const char *vermerk_wert_pruefen(vermerk_schluessel_t schluessel, const uint8_t *wert, size_t laenge)
{
    if (wert == NULL && laenge > 0) {
        return "kein Wert";
    }
    if (hat_nullbyte(wert, laenge)) {
        return "Wert enthaelt ein Nullbyte";
    }
    switch (schluessel) {
    case VERMERK_SCHLUESSEL_WLAN_SSID:
        return (laenge >= 1 && laenge <= VERMERK_SSID_MAX) ? NULL : "WLAN-Name: 1 bis 32 Bytes";

    case VERMERK_SCHLUESSEL_WLAN_PASSWORT:
        return (laenge == 0 || (laenge >= VERMERK_PASSWORT_MIN && laenge <= VERMERK_PASSWORT_MAX))
                   ? NULL : "WLAN-Passwort: leer oder 8 bis 63 Bytes";

    case VERMERK_SCHLUESSEL_PC_URL:
    case VERMERK_SCHLUESSEL_SERVER_URL:
        return url_pruefen(wert, laenge);

    case VERMERK_SCHLUESSEL_PC_TOKEN:
    case VERMERK_SCHLUESSEL_SERVER_TOKEN: {
        if (laenge == 0) {
            return NULL;
        }
        if (laenge > VERMERK_TOKEN_MAX) {
            return "Token zu lang (hoechstens 128 Zeichen)";
        }
        char token[VERMERK_TOKEN_MAX + 1];
        memcpy(token, wert, laenge);
        token[laenge] = '\0';
        return vermerk_token_gueltig(token) ? NULL : "Token: nur sichtbare ASCII-Zeichen ohne Leerzeichen";
    }

    case VERMERK_SCHLUESSEL_ERSTE_NUMMER: {
        uint32_t n = 0;
        return nummer_pruefen(wert, laenge, &n);
    }

    default:
        return "unbekannter Schluessel";
    }
}

static char *feld(vermerk_konfig_t *k, vermerk_schluessel_t schluessel, size_t *groesse)
{
    switch (schluessel) {
    case VERMERK_SCHLUESSEL_WLAN_SSID:     *groesse = sizeof(k->wlan_ssid);     return k->wlan_ssid;
    case VERMERK_SCHLUESSEL_WLAN_PASSWORT: *groesse = sizeof(k->wlan_passwort); return k->wlan_passwort;
    case VERMERK_SCHLUESSEL_PC_URL:        *groesse = sizeof(k->pc_url);        return k->pc_url;
    case VERMERK_SCHLUESSEL_PC_TOKEN:      *groesse = sizeof(k->pc_token);      return k->pc_token;
    case VERMERK_SCHLUESSEL_SERVER_URL:    *groesse = sizeof(k->server_url);    return k->server_url;
    case VERMERK_SCHLUESSEL_SERVER_TOKEN:  *groesse = sizeof(k->server_token);  return k->server_token;
    default:                               *groesse = 0;                        return NULL;
    }
}

const char *vermerk_wert_setzen(vermerk_konfig_t *k, vermerk_schluessel_t schluessel, const uint8_t *wert, size_t laenge)
{
    if (k == NULL) {
        return "keine Einrichtung";
    }
    const char *fehler = vermerk_wert_pruefen(schluessel, wert, laenge);
    if (fehler != NULL) {
        return fehler;
    }
    if (schluessel == VERMERK_SCHLUESSEL_ERSTE_NUMMER) {
        return nummer_pruefen(wert, laenge, &k->erste_nummer);
    }
    size_t groesse = 0;
    char *ziel = feld(k, schluessel, &groesse);
    if (ziel == NULL || laenge >= groesse) {
        return "unbekannter Schluessel";
    }
    if (laenge > 0) {
        memcpy(ziel, wert, laenge);
    }
    memset(ziel + laenge, 0, groesse - laenge);
    return NULL;
}

const char *vermerk_konfig_pruefen(const vermerk_konfig_t *k)
{
    if (k == NULL || k->version != VERMERK_KONFIG_VERSION) {
        return "unbekannte Version";
    }
    for (int s = 0; s < VERMERK_SCHLUESSEL_ANZAHL; s++) {
        if (s == VERMERK_SCHLUESSEL_ERSTE_NUMMER) {
            continue;
        }
        size_t groesse = 0;
        const char *wert = feld((vermerk_konfig_t *)k, (vermerk_schluessel_t)s, &groesse);
        const char *ende = memchr(wert, 0, groesse);
        if (ende == NULL) {
            return "Feld nicht abgeschlossen";
        }
        size_t laenge = (size_t)(ende - wert);
        if (s != VERMERK_SCHLUESSEL_WLAN_SSID || laenge > 0) {
            const char *fehler = vermerk_wert_pruefen((vermerk_schluessel_t)s, (const uint8_t *)wert, laenge);
            if (fehler != NULL) {
                return fehler;
            }
        }
    }
    if (k->erste_nummer > VERMERK_NUMMER_MAX) {
        return "erste_nummer zu gross";
    }
    if (k->wlan_ssid[0] == '\0') {
        return "wlan_ssid fehlt";
    }
    if (k->pc_url[0] != '\0' && k->pc_token[0] == '\0') {
        return "pc_token fehlt (pc_url ist gesetzt)";
    }
    if (k->server_url[0] != '\0' && k->server_token[0] == '\0') {
        return "server_token fehlt (server_url ist gesetzt)";
    }
    if (k->pc_url[0] == '\0' && k->server_url[0] == '\0') {
        return "kein Ziel vollstaendig (Adresse und Token)";
    }
    return NULL;
}

/* ---- INFO ---- */

typedef struct {
    char *ziel;
    size_t groesse;
    size_t pos;
    bool ok;
} puffer_t;

static void anhaengen(puffer_t *p, const char *text)
{
    size_t n = strlen(text);
    if (!p->ok || p->pos + n >= p->groesse) {
        p->ok = false;
        return;
    }
    memcpy(p->ziel + p->pos, text, n);
    p->pos += n;
    p->ziel[p->pos] = '\0';
}

/* JSON-Text: Anfuehrungszeichen, Backslash und Steuerzeichen werden maskiert */
static void json_text(puffer_t *p, const char *text)
{
    anhaengen(p, "\"");
    for (const char *c = (text != NULL) ? text : ""; *c != '\0' && p->ok; c++) {
        char kurz[8];
        unsigned char u = (unsigned char)*c;
        if (*c == '"' || *c == '\\') {
            snprintf(kurz, sizeof(kurz), "\\%c", *c);
        } else if (u < 0x20) {
            snprintf(kurz, sizeof(kurz), "\\u%04x", u);
        } else {
            kurz[0] = *c;
            kurz[1] = '\0';
        }
        anhaengen(p, kurz);
    }
    anhaengen(p, "\"");
}

static void json_hex(puffer_t *p, const char *text)
{
    const char *t = (text != NULL) ? text : "";
    size_t n = strlen(t);
    anhaengen(p, "\"");
    for (size_t i = 0; i < n && p->ok; i++) {
        char zwei[3];
        if (!vermerk_hex((const uint8_t *)t + i, 1, zwei, sizeof(zwei))) {
            p->ok = false;
            return;
        }
        anhaengen(p, zwei);
    }
    anhaengen(p, "\"");
}

bool vermerk_info_json(const vermerk_info_t *info, char *ziel, size_t ziel_groesse)
{
    if (info == NULL || ziel == NULL || ziel_groesse == 0) {
        return false;
    }
    puffer_t p = {.ziel = ziel, .groesse = ziel_groesse, .pos = 0, .ok = true};
    ziel[0] = '\0';
    anhaengen(&p, "{\"geraete_id\":");
    json_text(&p, info->geraete_id);
    anhaengen(&p, ",\"board\":");
    json_text(&p, info->board);
    anhaengen(&p, ",\"firmware\":");
    json_text(&p, info->firmware);
    anhaengen(&p, info->eingerichtet ? ",\"eingerichtet\":true" : ",\"eingerichtet\":false");
    anhaengen(&p, ",\"wlan_hex\":");
    json_hex(&p, info->wlan_ssid);
    anhaengen(&p, ",\"pc_url_hex\":");
    json_hex(&p, info->pc_url);
    anhaengen(&p, ",\"server_url_hex\":");
    json_hex(&p, info->server_url);
    anhaengen(&p, info->token_pc ? ",\"token_pc\":true" : ",\"token_pc\":false");
    anhaengen(&p, info->token_server ? ",\"token_server\":true}" : ",\"token_server\":false}");
    if (!p.ok) {
        ziel[0] = '\0';
    }
    return p.ok;
}

/* ---- Zeilen ---- */

void vermerk_vormerkung_leeren(vermerk_vormerkung_t *v)
{
    if (v != NULL) {
        memset(v, 0, sizeof(*v));
        v->werte.version = VERMERK_KONFIG_VERSION;
    }
}

/* Ein Wort aus der Zeile nur dann zurueckgeben, wenn es harmlos ist (a-z, A-Z, 0-9, _), sonst "?" */
static void wort_kopieren(char *ziel, size_t groesse, const char *wort, size_t laenge)
{
    if (laenge == 0 || laenge >= groesse) {
        snprintf(ziel, groesse, "?");
        return;
    }
    for (size_t i = 0; i < laenge; i++) {
        char c = wort[i];
        bool harmlos = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
        if (!harmlos) {
            snprintf(ziel, groesse, "?");
            return;
        }
    }
    memcpy(ziel, wort, laenge);
    ziel[laenge] = '\0';
}

static bool wort_ist(const char *wort, size_t laenge, const char *text)
{
    return strlen(text) == laenge && memcmp(wort, text, laenge) == 0;
}

vermerk_zeile_t vermerk_zeile_verarbeiten(vermerk_vormerkung_t *v, const char *zeile, size_t laenge, bool zu_lang,
                                          bool aufnahme_laeuft, char *antwort, size_t antwort_groesse)
{
    const size_t p_len = sizeof(PRAEFIX) - 1;

    if (antwort == NULL || antwort_groesse == 0 || v == NULL || zeile == NULL) {
        return VERMERK_ZEILE_UEBERGEHEN;
    }
    antwort[0] = '\0';

    /* Zeilenende-Reste und Leerzeichen am Ende ignorieren */
    while (laenge > 0 && (zeile[laenge - 1] == '\r' || zeile[laenge - 1] == ' ' || zeile[laenge - 1] == '\t')) {
        laenge--;
    }
    /* Nur "#VERMERK" allein oder "#VERMERK <...>" ist an uns gerichtet */
    if (laenge < p_len || memcmp(zeile, PRAEFIX, p_len) != 0 || (laenge > p_len && zeile[p_len] != ' ')) {
        return VERMERK_ZEILE_UEBERGEHEN;
    }
    if (zu_lang) {
        snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER ZEILE zu lang (hoechstens %d Zeichen)", VERMERK_ZEILE_MAX);
        return VERMERK_ZEILE_ANTWORT;
    }

    const char *rest = zeile + p_len;
    size_t rest_len = laenge - p_len;
    while (rest_len > 0 && *rest == ' ') {
        rest++;
        rest_len--;
    }
    size_t befehl_len = 0;
    while (befehl_len < rest_len && rest[befehl_len] != ' ') {
        befehl_len++;
    }
    const char *befehl = rest;
    const char *arg = rest + befehl_len;
    size_t arg_len = rest_len - befehl_len;
    if (arg_len > 0) {   /* genau ein Leerzeichen trennt */
        arg++;
        arg_len--;
    }
    char wort[33];
    wort_kopieren(wort, sizeof(wort), befehl, befehl_len);

    bool ohne_zusatz = (arg_len == 0);

    if (wort_ist(befehl, befehl_len, "INFO")) {
        if (!ohne_zusatz) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER INFO unerwarteter Zusatz");
            return VERMERK_ZEILE_ANTWORT;
        }
        return VERMERK_ZEILE_INFO;
    }

    if (wort_ist(befehl, befehl_len, "VERWERFEN")) {
        if (!ohne_zusatz) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER VERWERFEN unerwarteter Zusatz");
            return VERMERK_ZEILE_ANTWORT;
        }
        vermerk_vormerkung_leeren(v);
        snprintf(antwort, antwort_groesse, PRAEFIX " OK VERWERFEN");
        return VERMERK_ZEILE_ANTWORT;
    }

    if (wort_ist(befehl, befehl_len, "SPEICHERN") || wort_ist(befehl, befehl_len, "LOESCHEN")) {
        bool speichern = wort_ist(befehl, befehl_len, "SPEICHERN");
        if (!ohne_zusatz) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER %s unerwarteter Zusatz", wort);
            return VERMERK_ZEILE_ANTWORT;
        }
        if (aufnahme_laeuft) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER %s Aufnahme laeuft, nichts geaendert", wort);
            return VERMERK_ZEILE_ANTWORT;
        }
        if (!speichern) {
            return VERMERK_ZEILE_LOESCHEN;
        }
        v->werte.version = VERMERK_KONFIG_VERSION;
        const char *fehler = vermerk_konfig_pruefen(&v->werte);
        if (fehler != NULL) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER SPEICHERN %s", fehler);
            return VERMERK_ZEILE_ANTWORT;
        }
        return VERMERK_ZEILE_SPEICHERN;
    }

    if (wort_ist(befehl, befehl_len, "SETZE")) {
        /* SETZE <Schluessel>[ <Hex>] */
        size_t s_len = 0;
        while (s_len < arg_len && arg[s_len] != ' ') {
            s_len++;
        }
        const char *hex = arg + s_len;
        size_t hex_len = arg_len - s_len;
        if (hex_len > 0) {
            hex++;
            hex_len--;
        }
        char name[33];
        wort_kopieren(name, sizeof(name), arg, s_len);
        int schluessel = vermerk_schluessel_finden(arg, s_len);
        if (schluessel < 0) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER %s unbekannter Schluessel", name);
            return VERMERK_ZEILE_ANTWORT;
        }
        uint8_t wert[VERMERK_ZEILE_MAX / 2];
        size_t wert_len = 0;
        if (!vermerk_hex_lesen(hex, hex_len, wert, sizeof(wert), &wert_len)) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER %s Wert ist kein gueltiges Hex", name);
            return VERMERK_ZEILE_ANTWORT;
        }
        const char *fehler = vermerk_wert_setzen(&v->werte, (vermerk_schluessel_t)schluessel, wert, wert_len);
        memset(wert, 0, sizeof(wert));   /* kann ein Passwort oder Token sein */
        if (fehler != NULL) {
            snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER %s %s", name, fehler);
            return VERMERK_ZEILE_ANTWORT;
        }
        snprintf(antwort, antwort_groesse, PRAEFIX " OK SETZE %s", name);
        return VERMERK_ZEILE_ANTWORT;
    }

    snprintf(antwort, antwort_groesse, PRAEFIX " FEHLER %s unbekannte Anweisung", wort);
    return VERMERK_ZEILE_ANTWORT;
}
