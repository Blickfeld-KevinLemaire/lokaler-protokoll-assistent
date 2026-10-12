/* Tests fuer die Einrichtung ueber USB, reiner C-Teil (vermerk_einrichtung.c):  make test */

#include "vermerk_einrichtung.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int pruefungen = 0;
static int fehler = 0;

#define PRUEFE(bedingung)                                                         \
    do {                                                                          \
        pruefungen++;                                                             \
        if (!(bedingung)) {                                                       \
            fehler++;                                                             \
            fprintf(stderr, "%s:%d: FEHLER: %s\n", __FILE__, __LINE__, #bedingung); \
        }                                                                         \
    } while (0)

/* ---- Helfer ---- */

static const char *pruefe_text(vermerk_schluessel_t s, const char *text)
{
    return vermerk_wert_pruefen(s, (const uint8_t *)text, strlen(text));
}

static void hex_von(const char *text, size_t laenge, char *ziel, size_t groesse)
{
    if (!vermerk_hex((const uint8_t *)text, laenge, ziel, groesse)) {
        abort();
    }
}

/* Zeile auf den Heap (ohne Nullbyte dahinter), verarbeiten, Antwort zurueck */
static vermerk_zeile_t zeile(vermerk_vormerkung_t *v, const char *text, bool zu_lang, bool aufnahme, char *antwort,
                             size_t groesse)
{
    size_t n = strlen(text);
    char *kopie = malloc(n > 0 ? n : 1);
    if (kopie == NULL) {
        abort();
    }
    memcpy(kopie, text, n);
    vermerk_zeile_t z = vermerk_zeile_verarbeiten(v, kopie, n, zu_lang, aufnahme, antwort, groesse);
    free(kopie);
    return z;
}

static vermerk_zeile_t setze(vermerk_vormerkung_t *v, const char *schluessel, const char *wert, char *antwort,
                             size_t groesse)
{
    char hex[600];
    char text[700];
    hex_von(wert, strlen(wert), hex, sizeof(hex));
    snprintf(text, sizeof(text), "#VERMERK SETZE %s %s", schluessel, hex);
    return zeile(v, text, false, false, antwort, groesse);
}

static void gueltig_fuellen(vermerk_konfig_t *k)
{
    memset(k, 0, sizeof(*k));
    k->version = VERMERK_KONFIG_VERSION;
    strcpy(k->wlan_ssid, "Buero");
    strcpy(k->wlan_passwort, "geheim123");
    strcpy(k->pc_url, "http://192.168.0.10:8765");
    strcpy(k->pc_token, "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE");
}

/* ---- Schluessel und Hex ---- */

static void test_schluessel(void)
{
    const char *namen[] = {"wlan_ssid", "wlan_passwort", "pc_url", "pc_token", "server_url", "server_token",
                           "erste_nummer"};
    for (int i = 0; i < VERMERK_SCHLUESSEL_ANZAHL; i++) {
        PRUEFE(vermerk_schluessel_finden(namen[i], strlen(namen[i])) == i);
        PRUEFE(strcmp(vermerk_schluessel_name((vermerk_schluessel_t)i), namen[i]) == 0);
    }
    PRUEFE(vermerk_schluessel_finden("wlan", 4) == -1);
    PRUEFE(vermerk_schluessel_finden("wlan_ssidx", 10) == -1);
    PRUEFE(vermerk_schluessel_finden("WLAN_SSID", 9) == -1);
    PRUEFE(vermerk_schluessel_finden("", 0) == -1);
    PRUEFE(vermerk_schluessel_finden(NULL, 0) == -1);
    PRUEFE(strcmp(vermerk_schluessel_name(VERMERK_SCHLUESSEL_ANZAHL), "?") == 0);
}

static void test_hex_lesen(void)
{
    uint8_t b[4];
    size_t n = 99;
    PRUEFE(vermerk_hex_lesen("00ff7a", 6, b, sizeof(b), &n) && n == 3 && b[0] == 0 && b[1] == 0xff && b[2] == 0x7a);
    PRUEFE(vermerk_hex_lesen("ABcd", 4, b, sizeof(b), &n) && n == 2 && b[0] == 0xab && b[1] == 0xcd);
    PRUEFE(vermerk_hex_lesen("", 0, b, sizeof(b), &n) && n == 0);
    PRUEFE(vermerk_hex_lesen(NULL, 0, NULL, 0, &n) && n == 0);
    n = 77;
    PRUEFE(!vermerk_hex_lesen("abc", 3, b, sizeof(b), &n));          /* ungerade */
    PRUEFE(!vermerk_hex_lesen("0g", 2, b, sizeof(b), &n));           /* kein Hex */
    PRUEFE(!vermerk_hex_lesen("0 ", 2, b, sizeof(b), &n));
    PRUEFE(!vermerk_hex_lesen("-1", 2, b, sizeof(b), &n));
    PRUEFE(!vermerk_hex_lesen("0011223344", 10, b, sizeof(b), &n));  /* 5 Bytes, Platz fuer 4 */
    PRUEFE(vermerk_hex_lesen("00112233", 8, b, sizeof(b), &n) && n == 4);
    PRUEFE(!vermerk_hex_lesen("00", 2, b, sizeof(b), NULL));
    PRUEFE(!vermerk_hex_lesen("00", 2, NULL, 4, &n));
}

/* ---- Werte ---- */

static void test_werte(void)
{
    char lang[200];

    /* WLAN-Name */
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_SSID, "") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_SSID, "a") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_SSID, "Gaeste WLAN \"5 GHz\"") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_SSID, "B\xc3\xbcro") == NULL);   /* Umlaut als UTF-8 */
    memset(lang, 'x', 32);
    lang[32] = '\0';
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_SSID, lang) == NULL);
    lang[32] = 'x';
    lang[33] = '\0';
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_SSID, lang) != NULL);
    PRUEFE(vermerk_wert_pruefen(VERMERK_SCHLUESSEL_WLAN_SSID, (const uint8_t *)"a\0b", 3) != NULL);

    /* WLAN-Passwort: leer oder 8-63 */
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "1234567") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "12345678") == NULL);
    memset(lang, 'p', 63);
    lang[63] = '\0';
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, lang) == NULL);
    lang[63] = 'p';
    lang[64] = '\0';
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, lang) != NULL);
    PRUEFE(vermerk_wert_pruefen(VERMERK_SCHLUESSEL_WLAN_PASSWORT, (const uint8_t *)"12345678\0", 9) != NULL);
    /* nur druckbares ASCII 0x20-0x7E (WPA-Passphrase) */
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "mit Leer zeichen") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, " !\"#$%&'()*+,-./~") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "geheim\xc3\xa4\xc3\xb6\xc3\xbc") != NULL);   /* Umlaute */
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "geheim12\x7f") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "geheim12\t") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "geheim12\x1f") != NULL);
    PRUEFE(strcmp(pruefe_text(VERMERK_SCHLUESSEL_WLAN_PASSWORT, "geheim\xc3\xa4\xc3\xb6"),
                  "WLAN-Passwort: nur druckbare ASCII-Zeichen") == 0);

    /* Adressen */
    for (int s = VERMERK_SCHLUESSEL_PC_URL; s <= VERMERK_SCHLUESSEL_SERVER_URL; s += 2) {
        vermerk_schluessel_t u = (vermerk_schluessel_t)s;
        PRUEFE(pruefe_text(u, "") == NULL);
        PRUEFE(pruefe_text(u, "http://192.168.0.10:8765") == NULL);
        PRUEFE(pruefe_text(u, "http://pc.local") == NULL);
        PRUEFE(pruefe_text(u, "https://pc.local") != NULL);
        PRUEFE(pruefe_text(u, "ftp://pc.local") != NULL);
        PRUEFE(pruefe_text(u, "pc.local:8765") != NULL);
        PRUEFE(pruefe_text(u, "http://") != NULL);
        PRUEFE(pruefe_text(u, "http:///pfad") != NULL);
        PRUEFE(pruefe_text(u, "http://pc.local/") != NULL);
        PRUEFE(pruefe_text(u, "http://pc local") != NULL);
        PRUEFE(pruefe_text(u, "http://b\xc3\xbcro") != NULL);
        strcpy(lang, "http://");
        memset(lang + 7, 'a', 89);   /* 96 Bytes */
        lang[96] = '\0';
        PRUEFE(pruefe_text(u, lang) == NULL);
        lang[96] = 'a';
        lang[97] = '\0';
        PRUEFE(pruefe_text(u, lang) != NULL);
    }

    /* Tokens */
    for (int s = VERMERK_SCHLUESSEL_PC_TOKEN; s <= VERMERK_SCHLUESSEL_SERVER_TOKEN; s += 2) {
        vermerk_schluessel_t t = (vermerk_schluessel_t)s;
        PRUEFE(pruefe_text(t, "") == NULL);
        PRUEFE(pruefe_text(t, "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE") == NULL);   /* 43 wie die Software */
        PRUEFE(pruefe_text(t, "mit leerzeichen") != NULL);
        PRUEFE(pruefe_text(t, "tab\tdrin") != NULL);
        PRUEFE(pruefe_text(t, "\xc3\xa4") != NULL);
        memset(lang, 'k', 128);
        lang[128] = '\0';
        PRUEFE(pruefe_text(t, lang) == NULL);
        lang[128] = 'k';
        lang[129] = '\0';
        PRUEFE(pruefe_text(t, lang) != NULL);
    }

    /* erste Nummer */
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "29") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "1") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "999999999") == NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "1000000000") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "0") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "-1") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "+1") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, "2a") != NULL);
    PRUEFE(pruefe_text(VERMERK_SCHLUESSEL_ERSTE_NUMMER, " 2") != NULL);

    PRUEFE(vermerk_wert_pruefen(VERMERK_SCHLUESSEL_ANZAHL, (const uint8_t *)"x", 1) != NULL);
    PRUEFE(vermerk_wert_pruefen(VERMERK_SCHLUESSEL_WLAN_SSID, NULL, 1) != NULL);
}

static void test_wert_setzen(void)
{
    vermerk_konfig_t k;
    memset(&k, 0, sizeof(k));

    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_PC_URL, (const uint8_t *)"http://lang.beispiel:8765", 25) == NULL);
    PRUEFE(strcmp(k.pc_url, "http://lang.beispiel:8765") == 0);
    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_PC_URL, (const uint8_t *)"http://a", 8) == NULL);
    PRUEFE(strcmp(k.pc_url, "http://a") == 0);
    PRUEFE(k.pc_url[9] == '\0' && k.pc_url[20] == '\0');   /* kein Rest des laengeren Werts */

    /* Fehler laesst den alten Wert stehen */
    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_PC_URL, (const uint8_t *)"ftp://x", 7) != NULL);
    PRUEFE(strcmp(k.pc_url, "http://a") == 0);

    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_ERSTE_NUMMER, (const uint8_t *)"29", 2) == NULL && k.erste_nummer == 29);
    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_ERSTE_NUMMER, (const uint8_t *)"", 0) == NULL && k.erste_nummer == 0);
    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_ERSTE_NUMMER, (const uint8_t *)"x", 1) != NULL && k.erste_nummer == 0);

    /* leeres Passwort (offenes WLAN) */
    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_WLAN_PASSWORT, (const uint8_t *)"geheim123", 9) == NULL);
    PRUEFE(vermerk_wert_setzen(&k, VERMERK_SCHLUESSEL_WLAN_PASSWORT, NULL, 0) == NULL && k.wlan_passwort[0] == '\0');

    PRUEFE(vermerk_wert_setzen(NULL, VERMERK_SCHLUESSEL_PC_URL, (const uint8_t *)"http://a", 8) != NULL);
}

static void test_konfig_pruefen(void)
{
    vermerk_konfig_t k;

    gueltig_fuellen(&k);
    PRUEFE(vermerk_konfig_pruefen(&k) == NULL);

    /* nur Server */
    gueltig_fuellen(&k);
    k.pc_url[0] = '\0';
    k.pc_token[0] = '\0';
    strcpy(k.server_url, "http://server:8765");
    strcpy(k.server_token, "tok");
    PRUEFE(vermerk_konfig_pruefen(&k) == NULL);

    /* offenes WLAN */
    gueltig_fuellen(&k);
    k.wlan_passwort[0] = '\0';
    PRUEFE(vermerk_konfig_pruefen(&k) == NULL);

    /* Token ohne Adresse schadet nicht */
    gueltig_fuellen(&k);
    strcpy(k.server_token, "tok");
    PRUEFE(vermerk_konfig_pruefen(&k) == NULL);

    gueltig_fuellen(&k);
    k.wlan_ssid[0] = '\0';
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL && strstr(vermerk_konfig_pruefen(&k), "wlan_ssid") != NULL);

    gueltig_fuellen(&k);
    k.pc_token[0] = '\0';
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL && strstr(vermerk_konfig_pruefen(&k), "pc_token fehlt") != NULL);

    gueltig_fuellen(&k);
    strcpy(k.server_url, "http://server:8765");
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL && strstr(vermerk_konfig_pruefen(&k), "server_token fehlt") != NULL);

    gueltig_fuellen(&k);
    k.pc_url[0] = '\0';
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL && strstr(vermerk_konfig_pruefen(&k), "kein Ziel") != NULL);

    gueltig_fuellen(&k);
    k.version = 2;
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL);

    /* kaputter NVS-Eintrag: Feld ohne Nullbyte, ungueltiger Inhalt, zu grosse Nummer */
    gueltig_fuellen(&k);
    memset(k.pc_url, 'a', sizeof(k.pc_url));
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL);
    gueltig_fuellen(&k);
    strcpy(k.pc_url, "ftp://x");
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL);
    gueltig_fuellen(&k);
    strcpy(k.wlan_passwort, "kurz");
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL);
    gueltig_fuellen(&k);
    k.erste_nummer = VERMERK_NUMMER_MAX + 1;
    PRUEFE(vermerk_konfig_pruefen(&k) != NULL);

    PRUEFE(vermerk_konfig_pruefen(NULL) != NULL);
}

/* ---- INFO ---- */

static void test_info(void)
{
    char json[VERMERK_INFO_MAX];
    vermerk_info_t info = {
        .geraete_id = "1a2b3c4d5e6f", .board = "esp32-s3-audio", .firmware = "1.0.0", .eingerichtet = true,
        .wlan_ssid = "Buero", .pc_url = "http://a", .server_url = "", .token_pc = true, .token_server = false,
    };
    PRUEFE(vermerk_info_json(&info, json, sizeof(json)));
    PRUEFE(strcmp(json,
                  "{\"geraete_id\":\"1a2b3c4d5e6f\",\"board\":\"esp32-s3-audio\",\"firmware\":\"1.0.0\","
                  "\"eingerichtet\":true,\"wlan_hex\":\"427565726f\",\"pc_url_hex\":\"687474703a2f2f61\","
                  "\"server_url_hex\":\"\",\"token_pc\":true,\"token_server\":false}") == 0);

    /* Umlaut im WLAN-Namen als Hex, Sonderzeichen im Board maskiert, NULL als leer */
    info.wlan_ssid = "B\xc3\xbc\"ro";
    info.board = "a\"b\\c\n";
    info.server_url = NULL;
    info.eingerichtet = false;
    PRUEFE(vermerk_info_json(&info, json, sizeof(json)));
    PRUEFE(strstr(json, "\"wlan_hex\":\"42c3bc22726f\"") != NULL);
    PRUEFE(strstr(json, "\"board\":\"a\\\"b\\\\c\\u000a\"") != NULL);
    PRUEFE(strstr(json, "\"eingerichtet\":false") != NULL);
    PRUEFE(strstr(json, "\"server_url_hex\":\"\"") != NULL);

    /* groesste Antwort passt in VERMERK_INFO_MAX - und ist laenger als eine Zeile der Software */
    char ssid[33];
    char url[97];
    memset(ssid, 'W', 32);
    ssid[32] = '\0';
    strcpy(url, "http://");
    memset(url + 7, 'u', 89);
    url[96] = '\0';
    vermerk_info_t gross = {
        .geraete_id = "1a2b3c4d5e6f", .board = "esp32-s3-audio", .firmware = "1.0.0", .eingerichtet = true,
        .wlan_ssid = ssid, .pc_url = url, .server_url = url, .token_pc = true, .token_server = true,
    };
    PRUEFE(vermerk_info_json(&gross, json, sizeof(json)));
    PRUEFE(strlen(json) + strlen("#VERMERK INFO ") > VERMERK_ZEILE_MAX);
    PRUEFE(strlen(json) + strlen("#VERMERK INFO ") < VERMERK_INFO_MAX);

    /* zu kleiner Puffer: false und leer, kein Ueberlauf */
    char klein[40];
    PRUEFE(!vermerk_info_json(&gross, klein, sizeof(klein)) && klein[0] == '\0');
    PRUEFE(!vermerk_info_json(NULL, json, sizeof(json)));
    PRUEFE(!vermerk_info_json(&gross, json, 0));
}

/* ---- Zeilen ---- */

static void test_zeilen_uebergehen(void)
{
    vermerk_vormerkung_t v;
    char a[256];
    vermerk_vormerkung_leeren(&v);
    PRUEFE(zeile(&v, "", false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
    PRUEFE(zeile(&v, "I (1234) wifi: connected", false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
    PRUEFE(zeile(&v, "VERMERK Upload: H5_001.opus", false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
    PRUEFE(zeile(&v, "#VERMERKINFO", false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
    PRUEFE(zeile(&v, " #VERMERK INFO", false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
    PRUEFE(zeile(&v, "#vermerk INFO", false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
    /* zu lang, aber nicht an uns: still */
    PRUEFE(zeile(&v, "xxxxxxxx", true, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN && a[0] == '\0');
}

static void test_zeilen_info(void)
{
    vermerk_vormerkung_t v;
    char a[256];
    vermerk_vormerkung_leeren(&v);
    PRUEFE(zeile(&v, "#VERMERK INFO", false, false, a, sizeof(a)) == VERMERK_ZEILE_INFO);
    PRUEFE(zeile(&v, "#VERMERK INFO\r", false, false, a, sizeof(a)) == VERMERK_ZEILE_INFO);
    PRUEFE(zeile(&v, "#VERMERK INFO  ", false, true, a, sizeof(a)) == VERMERK_ZEILE_INFO);   /* auch waehrend Aufnahme */
    PRUEFE(zeile(&v, "#VERMERK INFO bitte", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER INFO unerwarteter Zusatz") == 0);
    PRUEFE(zeile(&v, "#VERMERK", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER ? unbekannte Anweisung") == 0);
    PRUEFE(zeile(&v, "#VERMERK HILFE", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER HILFE unbekannte Anweisung") == 0);
    PRUEFE(zeile(&v, "#VERMERK info", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(zeile(&v, "#VERMERK <script>", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER ? unbekannte Anweisung") == 0);
    PRUEFE(zeile(&v, "#VERMERK INFO", true, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER ZEILE zu lang (hoechstens 512 Zeichen)") == 0);
}

static void test_zeilen_einrichtung(void)
{
    vermerk_vormerkung_t v;
    char a[256];
    const char *token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE";
    vermerk_vormerkung_leeren(&v);

    /* leer speichern geht nicht */
    PRUEFE(zeile(&v, "#VERMERK SPEICHERN", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER SPEICHERN wlan_ssid fehlt") == 0);

    PRUEFE(setze(&v, "wlan_ssid", "Buero 2.4", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK SETZE wlan_ssid") == 0);
    PRUEFE(setze(&v, "wlan_passwort", "geheim123", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK SETZE wlan_passwort") == 0);
    PRUEFE(setze(&v, "pc_url", "http://192.168.0.10:8765", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);

    /* Adresse ohne Token */
    PRUEFE(zeile(&v, "#VERMERK SPEICHERN", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER SPEICHERN pc_token fehlt (pc_url ist gesetzt)") == 0);

    PRUEFE(setze(&v, "pc_token", token, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK SETZE pc_token") == 0);   /* der Wert kommt nie zurueck */
    PRUEFE(setze(&v, "erste_nummer", "29", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);

    /* waehrend einer Aufnahme: nichts speichern, nichts loeschen */
    PRUEFE(zeile(&v, "#VERMERK SPEICHERN", false, true, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER SPEICHERN Aufnahme laeuft, nichts geaendert") == 0);
    PRUEFE(zeile(&v, "#VERMERK LOESCHEN", false, true, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER LOESCHEN Aufnahme laeuft, nichts geaendert") == 0);

    PRUEFE(zeile(&v, "#VERMERK SPEICHERN", false, false, a, sizeof(a)) == VERMERK_ZEILE_SPEICHERN);
    PRUEFE(strcmp(v.werte.wlan_ssid, "Buero 2.4") == 0);
    PRUEFE(strcmp(v.werte.wlan_passwort, "geheim123") == 0);
    PRUEFE(strcmp(v.werte.pc_url, "http://192.168.0.10:8765") == 0);
    PRUEFE(strcmp(v.werte.pc_token, token) == 0);
    PRUEFE(v.werte.server_url[0] == '\0' && v.werte.server_token[0] == '\0');   /* nicht gesetzt = leer */
    PRUEFE(v.werte.erste_nummer == 29 && v.werte.version == VERMERK_KONFIG_VERSION);

    PRUEFE(zeile(&v, "#VERMERK SPEICHERN jetzt", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(zeile(&v, "#VERMERK LOESCHEN", false, false, a, sizeof(a)) == VERMERK_ZEILE_LOESCHEN);

    /* VERWERFEN vergisst alles */
    PRUEFE(zeile(&v, "#VERMERK VERWERFEN", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK VERWERFEN") == 0);
    PRUEFE(zeile(&v, "#VERMERK SPEICHERN", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER SPEICHERN wlan_ssid fehlt") == 0);
}

static void test_zeilen_setze_fehler(void)
{
    vermerk_vormerkung_t v;
    char a[256];
    char text[1100];
    vermerk_vormerkung_leeren(&v);

    PRUEFE(zeile(&v, "#VERMERK SETZE farbe 00", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER farbe unbekannter Schluessel") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE \"; rm 00", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER ? unbekannter Schluessel") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER ? unbekannter Schluessel") == 0);

    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_ssid 4", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER wlan_ssid Wert ist kein gueltiges Hex") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_ssid 4x", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER wlan_ssid Wert ist kein gueltiges Hex") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_ssid 41 42", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strstr(a, "#VERMERK FEHLER wlan_ssid") == a);
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_ssid", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER wlan_ssid WLAN-Name: 1 bis 32 Bytes") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_ssid 4142\r", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK SETZE wlan_ssid") == 0 && strcmp(v.werte.wlan_ssid, "AB") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_ssid 41004200", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strstr(a, "Nullbyte") != NULL && strcmp(v.werte.wlan_ssid, "AB") == 0);

    /* Passwort: 7 Zeichen abgelehnt, leer erlaubt (mit und ohne Leerzeichen am Ende) */
    PRUEFE(setze(&v, "wlan_passwort", "1234567", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER wlan_passwort WLAN-Passwort: leer oder 8 bis 63 Bytes") == 0);
    PRUEFE(strstr(a, "31323334") == NULL);   /* der Wert kommt nicht zurueck */
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_passwort", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK SETZE wlan_passwort") == 0);
    PRUEFE(zeile(&v, "#VERMERK SETZE wlan_passwort ", false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK OK SETZE wlan_passwort") == 0);

    /* zu lange Adresse (97 Bytes) */
    char url[100];
    strcpy(url, "http://");
    memset(url + 7, 'a', 90);
    url[97] = '\0';
    PRUEFE(setze(&v, "pc_url", url, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER pc_url Adresse zu lang (hoechstens 96 Bytes)") == 0);

    /* ungueltiges Token: Fehler ohne den Wert */
    PRUEFE(setze(&v, "server_token", "ab cd", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strstr(a, "#VERMERK FEHLER server_token") == a && strstr(a, "ab cd") == NULL);

    /* Hex laenger als jeder erlaubte Wert, aber Zeile noch innerhalb von 512 Zeichen */
    strcpy(text, "#VERMERK SETZE pc_token ");
    size_t n = strlen(text);
    while (n < VERMERK_ZEILE_MAX - 1) {
        text[n++] = '6';
        text[n++] = '1';
    }
    text[n] = '\0';
    PRUEFE(strlen(text) <= VERMERK_ZEILE_MAX);
    PRUEFE(zeile(&v, text, false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER pc_token Token zu lang (hoechstens 128 Zeichen)") == 0);

    /* noch laenger (Leser meldet zu_lang): Zeile zu lang */
    memset(text + 24, '6', 1000);
    text[1024] = '\0';
    PRUEFE(zeile(&v, text, false, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER pc_token Wert ist kein gueltiges Hex") == 0);   /* > 256 Bytes */
    PRUEFE(zeile(&v, text, true, false, a, sizeof(a)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strcmp(a, "#VERMERK FEHLER ZEILE zu lang (hoechstens 512 Zeichen)") == 0);

    /* erste_nummer als Dezimaltext */
    PRUEFE(setze(&v, "erste_nummer", "0", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT && strstr(a, "FEHLER") != NULL);
    PRUEFE(setze(&v, "erste_nummer", "1000", a, sizeof(a)) == VERMERK_ZEILE_ANTWORT && v.werte.erste_nummer == 1000);

    /* kleiner Antwortpuffer: abgeschnitten, kein Ueberlauf */
    char eng[12];
    PRUEFE(zeile(&v, "#VERMERK SETZE farbe 00", false, false, eng, sizeof(eng)) == VERMERK_ZEILE_ANTWORT);
    PRUEFE(strlen(eng) == sizeof(eng) - 1);
    PRUEFE(vermerk_zeile_verarbeiten(&v, "#VERMERK INFO", 13, false, false, NULL, 0) == VERMERK_ZEILE_UEBERGEHEN);
    PRUEFE(vermerk_zeile_verarbeiten(NULL, "#VERMERK INFO", 13, false, false, a, sizeof(a)) == VERMERK_ZEILE_UEBERGEHEN);
}

int main(void)
{
    test_schluessel();
    test_hex_lesen();
    test_werte();
    test_wert_setzen();
    test_konfig_pruefen();
    test_info();
    test_zeilen_uebergehen();
    test_zeilen_info();
    test_zeilen_einrichtung();
    test_zeilen_setze_fehler();

    if (fehler > 0) {
        fprintf(stderr, "Einrichtung: %d von %d Pruefungen fehlgeschlagen\n", fehler, pruefungen);
        return 1;
    }
    printf("Einrichtung: alle %d Pruefungen bestanden\n", pruefungen);
    return 0;
}
