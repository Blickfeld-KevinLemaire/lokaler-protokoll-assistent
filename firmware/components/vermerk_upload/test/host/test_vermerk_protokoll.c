/* Tests fuer den reinen C-Teil der Geraete-Schnittstelle (vermerk_protokoll.c), laufen auf dem PC:
 *   make test
 * Kein Test-Framework: PRUEFE zaehlt Fehler und meldet Datei und Zeile. */

#include "vermerk_protokoll.h"

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

/* Text ohne abschliessendes Nullbyte auf den Heap kopieren: AddressSanitizer meldet so jedes
 * Lesen hinter dem Ende, genau wie bei einem Antwortpuffer, der nicht mit 0 endet. */
static char *ohne_null(const char *text, size_t *laenge)
{
    *laenge = strlen(text);
    char *kopie = malloc(*laenge > 0 ? *laenge : 1);
    if (kopie == NULL) {
        abort();
    }
    memcpy(kopie, text, *laenge);
    return kopie;
}

static bool zahl(const char *text, const char *schluessel, uint64_t *wert)
{
    size_t n;
    char *t = ohne_null(text, &n);
    bool ok = vermerk_json_zahl(t, n, schluessel, wert);
    free(t);
    return ok;
}

static int wahr(const char *text, const char *schluessel)
{
    size_t n;
    char *t = ohne_null(text, &n);
    int w = vermerk_json_wahrheitswert(t, n, schluessel);
    free(t);
    return w;
}

static bool hallo(const char *text, uint32_t *teil)
{
    size_t n;
    char *t = ohne_null(text, &n);
    bool ok = vermerk_hallo_pruefen(t, n, teil);
    free(t);
    return ok;
}

static vermerk_entscheidung_t entscheide(vermerk_phase_t phase, int status, const char *text, bool von_vorn)
{
    if (text == NULL) {
        return vermerk_entscheiden(phase, status, NULL, 0, von_vorn);
    }
    size_t n;
    char *t = ohne_null(text, &n);
    vermerk_entscheidung_t e = vermerk_entscheiden(phase, status, t, n, von_vorn);
    free(t);
    return e;
}

/* ---- Dateinamen ---- */

static void test_name(void)
{
    PRUEFE(vermerk_name_gueltig("H5_007.opus"));
    PRUEFE(vermerk_name_gueltig("H5_1000.opus"));
    PRUEFE(vermerk_name_gueltig("a.ogg"));
    PRUEFE(vermerk_name_gueltig("Kurz-Name_1.wav"));
    PRUEFE(vermerk_name_gueltig("x.mp3"));

    /* 64 Zeichen Stamm sind erlaubt, 65 nicht */
    char lang[80];
    memset(lang, 'a', 64);
    strcpy(lang + 64, ".opus");
    PRUEFE(vermerk_name_gueltig(lang));
    memset(lang, 'a', 65);
    strcpy(lang + 65, ".opus");
    PRUEFE(!vermerk_name_gueltig(lang));

    PRUEFE(!vermerk_name_gueltig(NULL));
    PRUEFE(!vermerk_name_gueltig(""));
    PRUEFE(!vermerk_name_gueltig(".opus"));          /* leerer Stamm */
    PRUEFE(!vermerk_name_gueltig("H5_007"));         /* keine Endung */
    PRUEFE(!vermerk_name_gueltig("H5_007."));
    PRUEFE(!vermerk_name_gueltig("H5_007.flac"));
    PRUEFE(!vermerk_name_gueltig("H5_007.OPUS"));    /* Endung klein */
    PRUEFE(!vermerk_name_gueltig("H5_007.opus.wav"));
    PRUEFE(!vermerk_name_gueltig("H5_007.opusx"));
    PRUEFE(!vermerk_name_gueltig("H5 007.opus"));
    PRUEFE(!vermerk_name_gueltig("../H5.opus"));
    PRUEFE(!vermerk_name_gueltig("a/b.opus"));
    PRUEFE(!vermerk_name_gueltig("a%2f.opus"));
    PRUEFE(!vermerk_name_gueltig("\xc3\xa4.opus"));  /* Umlaut */
    PRUEFE(!vermerk_name_gueltig("a\r\n.opus"));
}

static void test_token(void)
{
    PRUEFE(vermerk_token_gueltig("abc"));
    PRUEFE(vermerk_token_gueltig("Zx9-_.~+/="));
    PRUEFE(!vermerk_token_gueltig(NULL));
    PRUEFE(!vermerk_token_gueltig(""));
    PRUEFE(!vermerk_token_gueltig("a b"));
    PRUEFE(!vermerk_token_gueltig("abc\r\nX-Evil: 1"));
    PRUEFE(!vermerk_token_gueltig("\x7f"));
    PRUEFE(!vermerk_token_gueltig("\xc3\xa4"));

    char t[VERMERK_TOKEN_MAX + 2];
    memset(t, 'k', VERMERK_TOKEN_MAX);
    t[VERMERK_TOKEN_MAX] = '\0';
    PRUEFE(vermerk_token_gueltig(t));
    t[VERMERK_TOKEN_MAX] = 'k';
    t[VERMERK_TOKEN_MAX + 1] = '\0';
    PRUEFE(!vermerk_token_gueltig(t));
}

static void test_aufnahme_nummer(void)
{
    uint32_t n = 0;
    PRUEFE(vermerk_aufnahme_nummer("H5_007.opus", "opus", &n) && n == 7);
    PRUEFE(vermerk_aufnahme_nummer("h5_1.OPUS", "opus", &n) && n == 1);
    PRUEFE(vermerk_aufnahme_nummer("H5_999.wav", "wav", &n) && n == 999);
    PRUEFE(vermerk_aufnahme_nummer("H5_1000.opus", "opus", &n) && n == 1000);
    PRUEFE(vermerk_aufnahme_nummer("H5_123456789.sent", "sent", &n) && n == 123456789);
    PRUEFE(vermerk_aufnahme_nummer("H5_000.opus", "opus", &n) && n == 0);

    n = 42;
    PRUEFE(!vermerk_aufnahme_nummer("H5_1234567890.opus", "opus", &n));   /* 10 Ziffern */
    PRUEFE(!vermerk_aufnahme_nummer("H5_4294967296.opus", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_.opus", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_-1.opus", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_12a.opus", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_12.wav", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_12.opus.bak", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_12.opu", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H4_12.opus", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("XH5_12.opus", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("", "opus", &n));
    PRUEFE(!vermerk_aufnahme_nummer("H5_1.opus", "", &n));
    PRUEFE(!vermerk_aufnahme_nummer(NULL, "opus", &n));
    PRUEFE(n == 42);   /* bei Fehlern unveraendert */
}

static void test_nummer_einfuegen(void)
{
    uint32_t l[4];
    int n = 0;
    vermerk_nummer_einfuegen(l, &n, 4, 7);
    vermerk_nummer_einfuegen(l, &n, 4, 3);
    vermerk_nummer_einfuegen(l, &n, 4, 7);    /* doppelt */
    vermerk_nummer_einfuegen(l, &n, 4, 1000);
    PRUEFE(n == 3 && l[0] == 3 && l[1] == 7 && l[2] == 1000);

    vermerk_nummer_einfuegen(l, &n, 4, 5);
    PRUEFE(n == 4 && l[0] == 3 && l[1] == 5 && l[2] == 7 && l[3] == 1000);

    /* voll: kleinere Nummer verdraengt die groesste, groessere kommt nicht hinein */
    vermerk_nummer_einfuegen(l, &n, 4, 1);
    PRUEFE(n == 4 && l[0] == 1 && l[1] == 3 && l[2] == 5 && l[3] == 7);
    vermerk_nummer_einfuegen(l, &n, 4, 8);
    PRUEFE(n == 4 && l[3] == 7);
    vermerk_nummer_einfuegen(l, &n, 4, 6);
    PRUEFE(n == 4 && l[0] == 1 && l[1] == 3 && l[2] == 5 && l[3] == 6);
    vermerk_nummer_einfuegen(l, &n, 4, 6);
    PRUEFE(n == 4 && l[3] == 6);

    /* viele Nummern in beliebiger Reihenfolge: es bleiben die kleinsten, aufsteigend */
    uint32_t g[8];
    int m = 0;
    for (uint32_t i = 0; i < 100; i++) {
        vermerk_nummer_einfuegen(g, &m, 8, (i * 37u) % 100u + 1u);
    }
    PRUEFE(m == 8);
    for (int i = 0; i < 8; i++) {
        PRUEFE(g[i] == (uint32_t)i + 1u);
    }

    /* Grenzen */
    uint32_t e[1];
    int k = 0;
    vermerk_nummer_einfuegen(e, &k, 1, 9);
    vermerk_nummer_einfuegen(e, &k, 1, 4);
    PRUEFE(k == 1 && e[0] == 4);
    vermerk_nummer_einfuegen(e, &k, 0, 1);
    vermerk_nummer_einfuegen(NULL, &k, 1, 1);
    vermerk_nummer_einfuegen(e, NULL, 1, 1);
    k = 2;   /* ungueltige Anzahl: nichts tun */
    vermerk_nummer_einfuegen(e, &k, 1, 1);
    PRUEFE(k == 2 && e[0] == 4);
}

/* ---- Antworten lesen ---- */

static void test_json_zahl(void)
{
    uint64_t w = 0;
    PRUEFE(zahl("{\"naechstes_byte\":262144,\"fertig\":false}", "naechstes_byte", &w) && w == 262144);
    PRUEFE(zahl("{\"fertig\":false,\"naechstes_byte\":0}", "naechstes_byte", &w) && w == 0);
    PRUEFE(zahl("{\"naechstes_byte\":18446744073709551615}", "naechstes_byte", &w) && w == UINT64_MAX);

    w = 7;
    PRUEFE(!zahl("{\"naechstes_byte\":18446744073709551616}", "naechstes_byte", &w));   /* Ueberlauf */
    PRUEFE(!zahl("{\"naechstes_byte\":99999999999999999999999}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":-1}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":+1}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":007}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":1.5}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":1e3}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":\"12\"}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":null}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\":}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\": 5}", "naechstes_byte", &w));   /* Spezifikation: ohne Leerzeichen */
    PRUEFE(!zahl("{\"naechstes_byte\":12", "naechstes_byte", &w));    /* abgeschnitten */
    PRUEFE(!zahl("{\"naechstes_byte\":", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte\"", "naechstes_byte", &w));
    PRUEFE(!zahl("", "naechstes_byte", &w));
    PRUEFE(!zahl("{}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"x_naechstes_byte\":5}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"naechstes_byte_x\":5}", "naechstes_byte", &w));
    PRUEFE(!zahl("naechstes_byte:5", "naechstes_byte", &w));
    PRUEFE(!zahl("\"naechstes_byte\":5}", "naechstes_byte", &w));   /* davor weder { noch , */
    /* Schluessel im Text eines Werts zaehlt nicht (Anfuehrungszeichen sind dort maskiert) */
    PRUEFE(!zahl("{\"fehler\":\"x,\\\"naechstes_byte\\\":5\"}", "naechstes_byte", &w));
    PRUEFE(!zahl("{\"fehler\":\"{\\\"naechstes_byte\\\":5}\"}", "naechstes_byte", &w));
    PRUEFE(w == 7);

    /* Nach dem Fehlertext steht der echte Wert */
    PRUEFE(zahl("{\"fehler\":\"\\\"naechstes_byte\\\":5\",\"naechstes_byte\":9}", "naechstes_byte", &w) && w == 9);

    PRUEFE(!vermerk_json_zahl(NULL, 0, "naechstes_byte", &w));
    PRUEFE(!vermerk_json_zahl("{\"a\":1}", 7, "", &w));
    PRUEFE(!vermerk_json_zahl("{\"a\":1}", 7, NULL, &w));
    PRUEFE(!vermerk_json_zahl("{\"a\":1}", 7, "a", NULL));

    /* Laenge begrenzt die Suche: der Wert hinter laenge zaehlt nicht */
    const char *voll = "{\"a\":12}";
    PRUEFE(!vermerk_json_zahl(voll, 6, "a", &w));
    PRUEFE(vermerk_json_zahl(voll, 8, "a", &w) && w == 12);
}

static void test_json_wahrheitswert(void)
{
    PRUEFE(wahr("{\"naechstes_byte\":5,\"fertig\":true}", "fertig") == 1);
    PRUEFE(wahr("{\"fertig\":false,\"naechstes_byte\":5}", "fertig") == 0);
    PRUEFE(wahr("{\"fertig\":true,\"datei\":\"S3_H5_007.opus\"}", "fertig") == 1);
    PRUEFE(wahr("{\"fertig\":truex}", "fertig") == -1);
    PRUEFE(wahr("{\"fertig\":tru}", "fertig") == -1);
    PRUEFE(wahr("{\"fertig\":true", "fertig") == -1);   /* abgeschnitten */
    PRUEFE(wahr("{\"fertig\":\"true\"}", "fertig") == -1);
    PRUEFE(wahr("{\"fertig\":1}", "fertig") == -1);
    PRUEFE(wahr("{\"fertig\":TRUE}", "fertig") == -1);
    PRUEFE(wahr("{\"unfertig\":true}", "fertig") == -1);
    PRUEFE(wahr("{\"fehler\":\"\\\"fertig\\\":true\"}", "fertig") == -1);
    PRUEFE(wahr("", "fertig") == -1);
    PRUEFE(vermerk_json_wahrheitswert(NULL, 0, "fertig") == -1);
}

static void test_hallo(void)
{
    uint32_t teil = 99;
    PRUEFE(hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1,\"geraet\":\"S3-Audio\",\"teil_max_bytes\":4194304}", &teil));
    PRUEFE(teil == 4194304);

    /* Reihenfolge egal, teil_max_bytes darf fehlen */
    teil = 99;
    PRUEFE(hallo("{\"schnittstelle\":1,\"dienst\":\"protokoll-assistent\"}", &teil) && teil == 0);
    PRUEFE(hallo("{\"schnittstelle\":1,\"dienst\":\"protokoll-assistent\"}", NULL));

    /* ungueltiges teil_max_bytes: erreichbar, aber Wert unbekannt */
    teil = 99;
    PRUEFE(hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1,\"teil_max_bytes\":-5}", &teil) && teil == 0);
    PRUEFE(hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1,\"teil_max_bytes\":0}", &teil) && teil == 0);
    PRUEFE(hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1,\"teil_max_bytes\":4294967296}", &teil) && teil == 0);

    PRUEFE(!hallo("", &teil));
    PRUEFE(!hallo("<html>It works!</html>", &teil));                         /* beliebiger Webserver */
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent\"}", &teil));            /* Version fehlt */
    PRUEFE(!hallo("{\"schnittstelle\":1}", &teil));                           /* Dienst fehlt */
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":2}", &teil));
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":10}", &teil));
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1.0}", &teil));
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":\"1\"}", &teil));
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent-alt\",\"schnittstelle\":1}", &teil));
    PRUEFE(!hallo("{\"dienst\":\"anderer\",\"schnittstelle\":1}", &teil));
    PRUEFE(!hallo("{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1", &teil));   /* abgeschnitten */
    PRUEFE(!hallo("{\"x\":\"\\\"dienst\\\":\\\"protokoll-assistent\\\"\",\"schnittstelle\":1}", &teil));
    PRUEFE(!vermerk_hallo_pruefen(NULL, 0, &teil));
}

static void test_teil_bytes(void)
{
    PRUEFE(vermerk_teil_bytes(0) == VERMERK_TEIL_BYTES);
    PRUEFE(vermerk_teil_bytes(4194304) == VERMERK_TEIL_BYTES);
    PRUEFE(vermerk_teil_bytes(VERMERK_TEIL_BYTES) == VERMERK_TEIL_BYTES);
    PRUEFE(vermerk_teil_bytes(65536) == 65536);
    PRUEFE(vermerk_teil_bytes(1) == 1);
}

static void test_hex(void)
{
    const uint8_t daten[] = {0x00, 0x01, 0xab, 0xcd, 0xef, 0xff, 0x10};
    char hex[VERMERK_SHA256_HEX_GROESSE];
    PRUEFE(vermerk_hex(daten, sizeof(daten), hex, sizeof(hex)));
    PRUEFE(strcmp(hex, "0001abcdefff10") == 0);

    uint8_t sha[32];
    for (int i = 0; i < 32; i++) {
        sha[i] = (uint8_t)(0xF0 + (i & 0x0F));
    }
    PRUEFE(vermerk_hex(sha, sizeof(sha), hex, sizeof(hex)));
    PRUEFE(strlen(hex) == 64);
    PRUEFE(strncmp(hex, "f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff", 32) == 0);

    char knapp[64];   /* ein Byte zu wenig fuer 32 Bytes */
    PRUEFE(!vermerk_hex(sha, sizeof(sha), knapp, sizeof(knapp)));
    PRUEFE(knapp[0] == '\0');

    char leer[1];
    PRUEFE(vermerk_hex(daten, 0, leer, sizeof(leer)) && leer[0] == '\0');
    PRUEFE(!vermerk_hex(daten, 1, leer, sizeof(leer)));
    PRUEFE(!vermerk_hex(daten, 1, NULL, 3));
    PRUEFE(!vermerk_hex(NULL, 1, hex, sizeof(hex)));
}

static void test_mac_hex(void)
{
    const uint8_t mac[6] = {0x1a, 0x2b, 0x3c, 0x4d, 0x5e, 0x6f};
    char id[VERMERK_GERAETE_ID_GROESSE];
    PRUEFE(vermerk_mac_hex(mac, id, sizeof(id)));
    PRUEFE(strcmp(id, "1a2b3c4d5e6f") == 0);

    const uint8_t mac2[6] = {0x00, 0x00, 0x0A, 0xFF, 0x80, 0x01};
    PRUEFE(vermerk_mac_hex(mac2, id, sizeof(id)));
    PRUEFE(strcmp(id, "00000aff8001") == 0);   /* fuehrende Nullen bleiben, klein, ohne Trenner */
    PRUEFE(strlen(id) == 12);

    char knapp[12];   /* ohne Platz fuer das Nullbyte */
    PRUEFE(!vermerk_mac_hex(mac, knapp, sizeof(knapp)));
    PRUEFE(knapp[0] == '\0');
    PRUEFE(!vermerk_mac_hex(NULL, id, sizeof(id)));
    PRUEFE(id[0] == '\0');
    PRUEFE(!vermerk_mac_hex(mac, NULL, 13));
}

/* ---- Entscheidungen ---- */

static void test_entscheiden(void)
{
    vermerk_entscheidung_t e;
    const char *weiter = "{\"naechstes_byte\":262144,\"fertig\":false}";
    const char *fertig = "{\"naechstes_byte\":300000,\"fertig\":true,\"datei\":\"S3-Audio_H5_007.opus\"}";

    /* Status-Abfrage */
    e = entscheide(VERMERK_PHASE_STATUS, 200, "{\"naechstes_byte\":0,\"fertig\":false}", false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 0);
    e = entscheide(VERMERK_PHASE_STATUS, 200, weiter, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 262144);
    /* "fertig":true bei der Abfrage loescht nichts: es wurde nichts geprueft */
    e = entscheide(VERMERK_PHASE_STATUS, 200, fertig, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 300000);
    e = entscheide(VERMERK_PHASE_STATUS, 200, "{\"fertig\":false}", false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_STATUS, 200, "OK", false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_STATUS, 200, NULL, false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_STATUS, 200, "{\"naechstes_byte\":-1,\"fertig\":false}", false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);

    /* Stueck angehaengt */
    e = entscheide(VERMERK_PHASE_TEIL, 200, weiter, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 262144);
    e = entscheide(VERMERK_PHASE_TEIL, 200, fertig, false);   /* ohne Abschluss kein Loeschen */
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 300000);
    e = entscheide(VERMERK_PHASE_TEIL, 200, "{}", false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);

    /* Abschluss */
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 200, fertig, false);
    PRUEFE(e.aktion == VERMERK_AKTION_FERTIG);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 200, "{\"fertig\":true}", true);
    PRUEFE(e.aktion == VERMERK_AKTION_FERTIG);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 200, weiter, false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 200, "{\"fertig\":\"true\"}", false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 200, NULL, false);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 201, fertig, false);   /* nur 200 zaehlt */
    PRUEFE(e.aktion == VERMERK_AKTION_AUFGEBEN);

    /* 409: ab dem gemeldeten Byte weiter, in jeder Phase */
    const char *versatz = "{\"naechstes_byte\":524288,\"fertig\":false,\"fehler\":\"X-Offset passt nicht\"}";
    for (int p = VERMERK_PHASE_STATUS; p <= VERMERK_PHASE_ABSCHLUSS; p++) {
        e = entscheide((vermerk_phase_t)p, 409, versatz, false);
        PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 524288);
        e = entscheide((vermerk_phase_t)p, 409, "{\"fehler\":\"kaputt\"}", false);
        PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    }

    /* 422: einmal von vorn, beim zweiten Mal spaeter */
    const char *pruefsumme = "{\"naechstes_byte\":0,\"fertig\":false,\"fehler\":\"Pruefsumme\"}";
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 422, pruefsumme, false);
    PRUEFE(e.aktion == VERMERK_AKTION_VON_VORN);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 422, pruefsumme, true);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, 422, NULL, false);
    PRUEFE(e.aktion == VERMERK_AKTION_VON_VORN);

    /* voruebergehend: spaeter */
    const int spaeter[] = {0, 408, 429, 500, 502, 503, 504, 507, 599};
    for (size_t i = 0; i < sizeof(spaeter) / sizeof(spaeter[0]); i++) {
        e = entscheide(VERMERK_PHASE_TEIL, spaeter[i], "{\"fehler\":\"x\"}", false);
        PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
        e = entscheide(VERMERK_PHASE_STATUS, spaeter[i], NULL, false);
        PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);
    }

    /* dauerhaft: aufgeben (Datei bleibt liegen) - auch wenn der Text naechstes_byte enthaelt */
    const int aufgeben[] = {-1, 100, 201, 204, 301, 302, 400, 401, 403, 404, 405, 411, 413, 600};
    for (size_t i = 0; i < sizeof(aufgeben) / sizeof(aufgeben[0]); i++) {
        e = entscheide(VERMERK_PHASE_TEIL, aufgeben[i], weiter, false);
        PRUEFE(e.aktion == VERMERK_AKTION_AUFGEBEN);
        e = entscheide(VERMERK_PHASE_ABSCHLUSS, aufgeben[i], fertig, false);
        PRUEFE(e.aktion == VERMERK_AKTION_AUFGEBEN);
    }
}

static void test_ergebnis_text(void)
{
    PRUEFE(strcmp(vermerk_ergebnis_text(VERMERK_ERGEBNIS_FERTIG), "fertig") == 0);
    PRUEFE(strlen(vermerk_ergebnis_text(VERMERK_ERGEBNIS_SPAETER)) > 0);
    PRUEFE(strlen(vermerk_ergebnis_text(VERMERK_ERGEBNIS_AUFGEBEN)) > 0);
    PRUEFE(strlen(vermerk_ergebnis_text(VERMERK_ERGEBNIS_KEIN_ZIEL)) > 0);
    PRUEFE(strlen(vermerk_ergebnis_text(VERMERK_ERGEBNIS_UNTERBROCHEN)) > 0);
    PRUEFE(strcmp(vermerk_ergebnis_text((vermerk_ergebnis_t)99), "?") == 0);
}

/* ---- Wartezeit und Warteliste ---- */

static void test_wartezeit(void)
{
    PRUEFE(vermerk_wartezeit_ms(0) == 0);
    PRUEFE(vermerk_wartezeit_ms(1) == 5000);
    PRUEFE(vermerk_wartezeit_ms(2) == 10000);
    PRUEFE(vermerk_wartezeit_ms(3) == 20000);
    PRUEFE(vermerk_wartezeit_ms(4) == 40000);
    PRUEFE(vermerk_wartezeit_ms(5) == 80000);
    PRUEFE(vermerk_wartezeit_ms(6) == 160000);
    PRUEFE(vermerk_wartezeit_ms(7) == 300000);   /* 320 s gekappt */
    PRUEFE(vermerk_wartezeit_ms(8) == 300000);
    PRUEFE(vermerk_wartezeit_ms(255) == 300000);
    PRUEFE(vermerk_wartezeit_ms(UINT32_MAX) == 300000);

    /* waechst nie und faellt nie */
    for (uint32_t i = 1; i < 300; i++) {
        PRUEFE(vermerk_wartezeit_ms(i) >= vermerk_wartezeit_ms(i - 1));
        PRUEFE(vermerk_wartezeit_ms(i) <= VERMERK_WARTEZEIT_MAX_MS);
    }
}

static void test_warteliste(void)
{
    vermerk_warteliste_t l;
    vermerk_warteliste_leeren(&l);
    const uint64_t t0 = 1000000;

    PRUEFE(vermerk_warteliste_bereit(&l, 7, 0, t0));

    /* erster Fehler: 5 s warten, die anderen Dateien sind nicht betroffen */
    vermerk_warteliste_fehler(&l, 7, 0, VERMERK_ERGEBNIS_SPAETER, t0);
    PRUEFE(!vermerk_warteliste_bereit(&l, 7, 0, t0));
    PRUEFE(!vermerk_warteliste_bereit(&l, 7, 0, t0 + 4999));
    PRUEFE(vermerk_warteliste_bereit(&l, 7, 0, t0 + 5000));
    PRUEFE(vermerk_warteliste_bereit(&l, 8, 0, t0));
    PRUEFE(vermerk_warteliste_bereit(&l, 7, 1, t0));   /* andere Endung, andere Datei */
    PRUEFE(vermerk_warteliste_rest_ms(&l, 7, 0, t0 + 1000) == 4000);
    PRUEFE(vermerk_warteliste_rest_ms(&l, 7, 0, t0 + 9000) == 0);

    /* zweiter Fehler: 10 s */
    vermerk_warteliste_fehler(&l, 7, 0, VERMERK_ERGEBNIS_SPAETER, t0 + 5000);
    PRUEFE(!vermerk_warteliste_bereit(&l, 7, 0, t0 + 14999));
    PRUEFE(vermerk_warteliste_bereit(&l, 7, 0, t0 + 15000));

    /* Erfolg setzt zurueck */
    vermerk_warteliste_erfolg(&l, 7, 0);
    PRUEFE(vermerk_warteliste_bereit(&l, 7, 0, t0 + 15000));
    vermerk_warteliste_fehler(&l, 7, 0, VERMERK_ERGEBNIS_SPAETER, t0);
    PRUEFE(vermerk_warteliste_rest_ms(&l, 7, 0, t0) == 5000);   /* wieder ab 5 s */

    /* Aufgeben: gleich die laengste Wartezeit */
    vermerk_warteliste_fehler(&l, 9, 1, VERMERK_ERGEBNIS_AUFGEBEN, t0);
    PRUEFE(vermerk_warteliste_rest_ms(&l, 9, 1, t0) == VERMERK_WARTEZEIT_MAX_MS);

    /* Fertig, kein Ziel und unterbrochen aendern nichts */
    vermerk_warteliste_fehler(&l, 11, 0, VERMERK_ERGEBNIS_KEIN_ZIEL, t0);
    vermerk_warteliste_fehler(&l, 11, 0, VERMERK_ERGEBNIS_UNTERBROCHEN, t0);
    vermerk_warteliste_fehler(&l, 11, 0, VERMERK_ERGEBNIS_FERTIG, t0);
    PRUEFE(vermerk_warteliste_bereit(&l, 11, 0, t0));

    /* Fehlversuche laufen nicht ueber */
    for (int i = 0; i < 400; i++) {
        vermerk_warteliste_fehler(&l, 12, 0, VERMERK_ERGEBNIS_SPAETER, t0);
    }
    PRUEFE(vermerk_warteliste_rest_ms(&l, 12, 0, t0) == VERMERK_WARTEZEIT_MAX_MS);

    /* Liste voll: der Eintrag, der am fruehesten wieder dran ist, wird ersetzt */
    vermerk_warteliste_leeren(&l);
    for (uint32_t n = 1; n <= VERMERK_WARTELISTE_PLAETZE; n++) {
        vermerk_warteliste_fehler(&l, n, 0, VERMERK_ERGEBNIS_SPAETER, t0 + n * 100);
    }
    for (uint32_t n = 1; n <= VERMERK_WARTELISTE_PLAETZE; n++) {
        PRUEFE(!vermerk_warteliste_bereit(&l, n, 0, t0 + n * 100));
    }
    vermerk_warteliste_fehler(&l, 100, 0, VERMERK_ERGEBNIS_SPAETER, t0 + 5000);
    PRUEFE(!vermerk_warteliste_bereit(&l, 100, 0, t0 + 5000));
    PRUEFE(vermerk_warteliste_bereit(&l, 1, 0, t0 + 100));      /* Nummer 1 war am fruehesten dran */
    PRUEFE(!vermerk_warteliste_bereit(&l, 2, 0, t0 + 200));

    /* NULL schadet nicht */
    vermerk_warteliste_leeren(NULL);
    vermerk_warteliste_fehler(NULL, 1, 0, VERMERK_ERGEBNIS_SPAETER, t0);
    vermerk_warteliste_erfolg(NULL, 1, 0);
    PRUEFE(vermerk_warteliste_bereit(NULL, 1, 0, t0));
}

int main(void)
{
    test_name();
    test_token();
    test_aufnahme_nummer();
    test_nummer_einfuegen();
    test_json_zahl();
    test_json_wahrheitswert();
    test_hallo();
    test_teil_bytes();
    test_hex();
    test_mac_hex();
    test_entscheiden();
    test_ergebnis_text();
    test_wartezeit();
    test_warteliste();

    if (fehler > 0) {
        fprintf(stderr, "%d von %d Pruefungen fehlgeschlagen\n", fehler, pruefungen);
        return 1;
    }
    printf("Alle %d Pruefungen bestanden\n", pruefungen);
    return 0;
}
