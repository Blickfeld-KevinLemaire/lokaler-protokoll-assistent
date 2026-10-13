/* Tests fuer den reinen C-Teil der Geraete-Schnittstelle (vermerk_protokoll.c), laufen auf dem PC:
 *   make test
 * Kein Test-Framework: PRUEFE zaehlt Fehler und meldet Datei und Zeile. */

#include "vermerk_protokoll.h"
#include "antworten_software.h"   /* echte Antworten des Empfangs, erzeugt von antworten_erzeugen.py */

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

/* Vertrag mit der Software: ihre echten Antworten (antworten_software.h) muessen genau so gelesen und
 * entschieden werden. Aendert die Software ihr Format, schlaegt das hier fehl. */
static void test_vertrag_mit_der_software(void)
{
    vermerk_entscheidung_t e;
    uint32_t teil = 0;

    PRUEFE(SW_HALLO_STATUS == 200);
    PRUEFE(hallo(SW_HALLO, &teil) && teil == 4194304u);
    PRUEFE(vermerk_teil_bytes(teil) == VERMERK_TEIL_BYTES);
    PRUEFE(!hallo(SW_TOKEN_401, &teil));

    e = entscheide(VERMERK_PHASE_STATUS, SW_STATUS_NEU_STATUS, SW_STATUS_NEU, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 0);
    e = entscheide(VERMERK_PHASE_STATUS, SW_STATUS_TEILSTAND_STATUS, SW_STATUS_TEILSTAND, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 10);
    e = entscheide(VERMERK_PHASE_TEIL, SW_TEIL_ANGEHAENGT_STATUS, SW_TEIL_ANGEHAENGT, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 10);

    /* 409: beim gemeldeten Byte weiter, egal ob Stueck oder Abschluss */
    PRUEFE(SW_VERSATZ_409_STATUS == 409);
    e = entscheide(VERMERK_PHASE_TEIL, SW_VERSATZ_409_STATUS, SW_VERSATZ_409, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 10);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, SW_VERSATZ_409_STATUS, SW_VERSATZ_409, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 10);

    /* fertig - auch beim zweiten Mal derselben Aufnahme; ohne Abschluss zaehlt "fertig" nie */
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, SW_ABSCHLUSS_FERTIG_STATUS, SW_ABSCHLUSS_FERTIG, false);
    PRUEFE(e.aktion == VERMERK_AKTION_FERTIG);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, SW_ABSCHLUSS_DOPPELT_STATUS, SW_ABSCHLUSS_DOPPELT, false);
    PRUEFE(e.aktion == VERMERK_AKTION_FERTIG);
    e = entscheide(VERMERK_PHASE_TEIL, SW_ABSCHLUSS_FERTIG_STATUS, SW_ABSCHLUSS_FERTIG, false);
    PRUEFE(e.aktion == VERMERK_AKTION_WEITER_AB && e.naechstes_byte == 10);

    /* 422: einmal von vorn, beim zweiten Mal spaeter */
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, SW_ABSCHLUSS_GROESSE_422_STATUS, SW_ABSCHLUSS_GROESSE_422, false);
    PRUEFE(e.aktion == VERMERK_AKTION_VON_VORN);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, SW_ABSCHLUSS_PRUEFSUMME_422_STATUS, SW_ABSCHLUSS_PRUEFSUMME_422, false);
    PRUEFE(e.aktion == VERMERK_AKTION_VON_VORN);
    e = entscheide(VERMERK_PHASE_ABSCHLUSS, SW_ABSCHLUSS_PRUEFSUMME_422_STATUS, SW_ABSCHLUSS_PRUEFSUMME_422, true);
    PRUEFE(e.aktion == VERMERK_AKTION_SPAETER);

    /* voruebergehend: spaeter */
    e = entscheide(VERMERK_PHASE_TEIL, SW_PLATTE_VOLL_507_STATUS, SW_PLATTE_VOLL_507, false);
    PRUEFE(SW_PLATTE_VOLL_507_STATUS == 507 && e.aktion == VERMERK_AKTION_SPAETER);
    e = entscheide(VERMERK_PHASE_STATUS, SW_UEBERLAST_503_STATUS, SW_UEBERLAST_503, false);
    PRUEFE(SW_UEBERLAST_503_STATUS == 503 && e.aktion == VERMERK_AKTION_SPAETER);

    /* dauerhaft: fuer jetzt aufgeben, Datei bleibt */
    const struct { int status; const char *text; } dauerhaft[] = {
        {SW_TOKEN_401_STATUS, SW_TOKEN_401},
        {SW_NAME_400_STATUS, SW_NAME_400},
        {SW_KOPF_400_STATUS, SW_KOPF_400},
        {SW_PFAD_404_STATUS, SW_PFAD_404},
        {SW_CHUNKED_411_STATUS, SW_CHUNKED_411},
        {SW_ZU_GROSS_413_STATUS, SW_ZU_GROSS_413},
        /* 400 "Stueck unvollstaendig" sieht das Geraet praktisch nie (die Verbindung ist dann weg) */
        {SW_STUECK_UNVOLLSTAENDIG_400_STATUS, SW_STUECK_UNVOLLSTAENDIG_400},
    };
    for (size_t i = 0; i < sizeof(dauerhaft) / sizeof(dauerhaft[0]); i++) {
        e = entscheide(VERMERK_PHASE_TEIL, dauerhaft[i].status, dauerhaft[i].text, false);
        PRUEFE(e.aktion == VERMERK_AKTION_AUFGEBEN);
        e = entscheide(VERMERK_PHASE_ABSCHLUSS, dauerhaft[i].status, dauerhaft[i].text, false);
        PRUEFE(e.aktion == VERMERK_AKTION_AUFGEBEN);
    }
    PRUEFE(SW_TOKEN_401_STATUS == 401 && SW_ZU_GROSS_413_STATUS == 413 && SW_CHUNKED_411_STATUS == 411);

    /* Jede Antwort mit naechstes_byte liest sich sauber; Fehlertexte stoeren die Suche nicht */
    uint64_t n = 99;
    PRUEFE(zahl(SW_STUECK_UNVOLLSTAENDIG_400, "naechstes_byte", &n) && n == 0);
    PRUEFE(wahr(SW_VERSATZ_409, "fertig") == 0);
    PRUEFE(wahr(SW_ABSCHLUSS_DOPPELT, "fertig") == 1);
}


static void test_json_text_und_promille(void)
{
    size_t n;
    char *t;
    char ziel[24];

    t = ohne_null("{\"zustand\":\"auswertung\",\"fortschritt\":0.8}", &n);
    PRUEFE(vermerk_json_text(t, n, "zustand", ziel, sizeof(ziel)) && strcmp(ziel, "auswertung") == 0);
    PRUEFE(!vermerk_json_text(t, n, "fehlt", ziel, sizeof(ziel)) && ziel[0] == 0);
    PRUEFE(!vermerk_json_text(t, n, "zustand", ziel, 10));        /* "auswertung" (10 Zeichen) passt nicht in 10 */
    PRUEFE(vermerk_json_text(t, n, "zustand", ziel, 11));
    PRUEFE(!vermerk_json_text(t, n, "zustand", NULL, 4) && !vermerk_json_text(t, n, "zustand", ziel, 0));
    PRUEFE(!vermerk_json_text(t, n, "fortschritt", ziel, sizeof(ziel)));   /* kein Text */
    free(t);

    /* Grenzfaelle: leer, nicht abgeschlossen, Sonderzeichen, Schluessel nur als Text in einem Wert */
    t = ohne_null("{\"zustand\":\"\"}", &n);
    PRUEFE(!vermerk_json_text(t, n, "zustand", ziel, sizeof(ziel)));
    free(t);
    t = ohne_null("{\"zustand\":\"fertig", &n);
    PRUEFE(!vermerk_json_text(t, n, "zustand", ziel, sizeof(ziel)));
    free(t);
    t = ohne_null("{\"zustand\":\"fer tig\"}", &n);
    PRUEFE(!vermerk_json_text(t, n, "zustand", ziel, sizeof(ziel)));
    free(t);
    t = ohne_null("{\"meldung\":\"x \\\"zustand\\\":\\\"fertig\\\"\",\"y\":1}", &n);
    PRUEFE(!vermerk_json_text(t, n, "zustand", ziel, sizeof(ziel)));
    free(t);
    t = ohne_null("{\"zustand\":\"fertig\"x}", &n);
    PRUEFE(!vermerk_json_text(t, n, "zustand", ziel, sizeof(ziel)));
    free(t);

    uint32_t pm = 0;
    const struct { const char *text; bool ok; uint32_t wert; } faelle[] = {
        {"{\"f\":0}", true, 0},
        {"{\"f\":0.0}", true, 0},
        {"{\"f\":0.457}", true, 457},
        {"{\"f\":0.5}", true, 500},
        {"{\"f\":0.05}", true, 50},
        {"{\"f\":0.001}", true, 1},
        {"{\"f\":1}", true, 1000},
        {"{\"f\":1.0}", true, 1000},
        {"{\"f\":1.000,\"g\":1}", true, 1000},
        {"{\"f\":1.001}", false, 0},     /* ueber 1 */
        {"{\"f\":2}", false, 0},
        {"{\"f\":0.1234}", false, 0},    /* mehr als drei Nachkommastellen */
        {"{\"f\":1.}", false, 0},
        {"{\"f\":.5}", false, 0},
        {"{\"f\":-0.5}", false, 0},
        {"{\"f\":01}", false, 0},
        {"{\"f\":1e0}", false, 0},
        {"{\"f\":\"0.5\"}", false, 0},
        {"{\"f\":0.5", false, 0},        /* abgeschnitten */
        {"{\"g\":0.5}", false, 0},       /* anderer Schluessel */
    };
    for (size_t i = 0; i < sizeof(faelle) / sizeof(faelle[0]); i++) {
        t = ohne_null(faelle[i].text, &n);
        pm = 12345;
        bool ok = vermerk_json_promille(t, n, "f", &pm);
        PRUEFE(ok == faelle[i].ok);
        if (faelle[i].ok) {
            PRUEFE(pm == faelle[i].wert);
        } else {
            PRUEFE(pm == 12345);   /* bei Fehler unveraendert */
        }
        free(t);
    }
    PRUEFE(!vermerk_json_promille("{\"f\":1}", 7, "f", NULL));
}

static vermerk_status_t status_lesen(const char *text, bool *ok)
{
    size_t n;
    char *t = ohne_null(text, &n);
    vermerk_status_t s;
    *ok = vermerk_status_pruefen(t, n, &s);
    free(t);
    return s;
}

static void test_status(void)
{
    bool ok;
    vermerk_status_t s;

    /* Echte Antworten der Software (antworten_software.h) */
    s = status_lesen(SW_STATUS_EMPFANG, &ok);
    PRUEFE(SW_STATUS_EMPFANG_STATUS == 200 && ok && s.zustand == VERMERK_VERARB_EMPFANG && s.fortschritt_prozent == -1);
    s = status_lesen(SW_STATUS_WARTET, &ok);
    PRUEFE(ok && s.zustand == VERMERK_VERARB_WARTET && s.fortschritt_prozent == -1);
    s = status_lesen(SW_STATUS_TRANSKRIPTION, &ok);   /* mit Umlaut in der Meldung */
    PRUEFE(ok && s.zustand == VERMERK_VERARB_TRANSKRIPTION && s.fortschritt_prozent == 46);   /* 0.457 gerundet */
    s = status_lesen(SW_STATUS_AUSWERTUNG, &ok);
    PRUEFE(ok && s.zustand == VERMERK_VERARB_AUSWERTUNG && s.fortschritt_prozent == 80);
    s = status_lesen(SW_STATUS_FERTIG, &ok);
    PRUEFE(ok && s.zustand == VERMERK_VERARB_FERTIG && s.fortschritt_prozent == 100);
    s = status_lesen(SW_STATUS_FEHLER, &ok);
    PRUEFE(ok && s.zustand == VERMERK_VERARB_FEHLER && s.fortschritt_prozent == -1);
    s = status_lesen(SW_STATUS_UNBEKANNT, &ok);
    PRUEFE(ok && s.zustand == VERMERK_VERARB_UNBEKANNT && s.fortschritt_prozent == -1);

    /* Ein zukuenftiger, hier unbekannter Zustand ist kein Fehler, sondern "unbekannt" */
    s = status_lesen("{\"zustand\":\"neuer-zustand\"}", &ok);
    PRUEFE(ok && s.zustand == VERMERK_VERARB_UNBEKANNT);
    /* Kein Zustand: keine Antwort der Software */
    s = status_lesen(SW_TOKEN_401, &ok);
    PRUEFE(!ok && s.zustand == VERMERK_VERARB_UNBEKANNT && s.fortschritt_prozent == -1);
    s = status_lesen(SW_STATUS_NEU, &ok);   /* Antwort des Upload-Stands, kein Verarbeitungsstand */
    PRUEFE(!ok);
    s = status_lesen("", &ok);
    PRUEFE(!ok);
    PRUEFE(!vermerk_status_pruefen("{}", 2, NULL));

    PRUEFE(!vermerk_verarbeitung_beendet(VERMERK_VERARB_UNBEKANNT));
    PRUEFE(!vermerk_verarbeitung_beendet(VERMERK_VERARB_EMPFANG));
    PRUEFE(!vermerk_verarbeitung_beendet(VERMERK_VERARB_WARTET));
    PRUEFE(!vermerk_verarbeitung_beendet(VERMERK_VERARB_TRANSKRIPTION));
    PRUEFE(!vermerk_verarbeitung_beendet(VERMERK_VERARB_AUSWERTUNG));
    PRUEFE(vermerk_verarbeitung_beendet(VERMERK_VERARB_FERTIG));
    PRUEFE(vermerk_verarbeitung_beendet(VERMERK_VERARB_FEHLER));
    PRUEFE(strcmp(vermerk_verarbeitung_text(VERMERK_VERARB_FERTIG), "fertig") == 0);
    PRUEFE(strcmp(vermerk_verarbeitung_text(VERMERK_VERARB_UNBEKANNT), "unbekannt") == 0);
}

static vermerk_statusabfrage_t status_e(int http_status, const char *text, vermerk_status_t *s)
{
    if (text == NULL) {
        return vermerk_status_entscheiden(http_status, NULL, 0, s);
    }
    size_t n;
    char *t = ohne_null(text, &n);
    vermerk_statusabfrage_t a = vermerk_status_entscheiden(http_status, t, n, s);
    free(t);
    return a;
}

static void test_status_entscheiden(void)
{
    vermerk_status_t s;

    /* 200 mit Zustand: anzeigen (auch "unbekannt" - wie oft das hingenommen wird, entscheidet der Aufrufer) */
    PRUEFE(status_e(SW_STATUS_FERTIG_STATUS, SW_STATUS_FERTIG, &s) == VERMERK_STATUSABFRAGE_ZUSTAND &&
           s.zustand == VERMERK_VERARB_FERTIG && s.fortschritt_prozent == 100);
    PRUEFE(status_e(SW_STATUS_TRANSKRIPTION_STATUS, SW_STATUS_TRANSKRIPTION, &s) == VERMERK_STATUSABFRAGE_ZUSTAND &&
           s.zustand == VERMERK_VERARB_TRANSKRIPTION && s.fortschritt_prozent == 46);
    PRUEFE(status_e(SW_STATUS_UNBEKANNT_STATUS, SW_STATUS_UNBEKANNT, &s) == VERMERK_STATUSABFRAGE_ZUSTAND &&
           s.zustand == VERMERK_VERARB_UNBEKANNT);

    /* voruebergehend: weiter fragen */
    PRUEFE(status_e(0, NULL, &s) == VERMERK_STATUSABFRAGE_SPAETER && s.zustand == VERMERK_VERARB_UNBEKANNT &&
           s.fortschritt_prozent == -1);
    PRUEFE(status_e(SW_UEBERLAST_503_STATUS, SW_UEBERLAST_503, &s) == VERMERK_STATUSABFRAGE_SPAETER);
    PRUEFE(status_e(SW_PLATTE_VOLL_507_STATUS, SW_PLATTE_VOLL_507, &s) == VERMERK_STATUSABFRAGE_SPAETER);
    PRUEFE(status_e(500, "", &s) == VERMERK_STATUSABFRAGE_SPAETER);
    PRUEFE(status_e(408, NULL, &s) == VERMERK_STATUSABFRAGE_SPAETER);
    PRUEFE(status_e(429, NULL, &s) == VERMERK_STATUSABFRAGE_SPAETER);
    PRUEFE(status_e(200, "{}", &s) == VERMERK_STATUSABFRAGE_SPAETER);           /* 200 ohne Zustand */
    PRUEFE(status_e(200, SW_STATUS_NEU, &s) == VERMERK_STATUSABFRAGE_SPAETER);  /* Upload-Stand statt Verarbeitung */

    /* dauerhaft: fuer diese Aufnahme nicht mehr fragen */
    PRUEFE(status_e(SW_PFAD_404_STATUS, SW_PFAD_404, &s) == VERMERK_STATUSABFRAGE_ENDE);   /* Software ohne .../status */
    PRUEFE(status_e(SW_TOKEN_401_STATUS, SW_TOKEN_401, &s) == VERMERK_STATUSABFRAGE_ENDE); /* Token widerrufen */
    PRUEFE(status_e(SW_NAME_400_STATUS, SW_NAME_400, &s) == VERMERK_STATUSABFRAGE_ENDE);
    PRUEFE(status_e(403, NULL, &s) == VERMERK_STATUSABFRAGE_ENDE);
    PRUEFE(status_e(302, NULL, &s) == VERMERK_STATUSABFRAGE_ENDE);
    PRUEFE(status_e(-1, NULL, &s) == VERMERK_STATUSABFRAGE_ENDE);   /* Name oder Ziel ungueltig */
    /* Ein Zustand im Text einer Fehlerantwort zaehlt nicht */
    PRUEFE(status_e(404, "{\"zustand\":\"fertig\"}", &s) == VERMERK_STATUSABFRAGE_ENDE &&
           s.zustand == VERMERK_VERARB_UNBEKANNT);
}

static vermerk_live_entscheidung_t live_e(int status, const char *text, uint64_t bestaetigt, uint64_t geschrieben)
{
    return vermerk_live_entscheiden(status, text, text != NULL ? strlen(text) : 0, bestaetigt, geschrieben);
}

static void test_live_entscheiden(void)
{
    vermerk_live_entscheidung_t e;

    /* Stueck angehaengt: neuer Stand */
    e = live_e(SW_TEIL_ANGEHAENGT_STATUS, SW_TEIL_ANGEHAENGT, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_WEITER && e.naechstes_byte == 10);
    /* Die Software hat schon mehr, als wir als bestaetigt wissen (Antwort ging verloren): auch gut */
    e = live_e(SW_TEIL_ANGEHAENGT_STATUS, SW_TEIL_ANGEHAENGT, 4, 12);
    PRUEFE(e.aktion == VERMERK_LIVE_WEITER && e.naechstes_byte == 10);
    /* 409: ab dem Stand der Software weiter, solange der noch im Ringpuffer liegt */
    e = live_e(SW_VERSATZ_409_STATUS, SW_VERSATZ_409, 4, 12);
    PRUEFE(e.aktion == VERMERK_LIVE_WEITER && e.naechstes_byte == 10);
    /* ... nicht, wenn sie weniger hat als schon verworfen ist (Luecke) oder mehr als je geschrieben wurde */
    e = live_e(SW_VERSATZ_409_STATUS, SW_VERSATZ_409, 11, 20);
    PRUEFE(e.aktion == VERMERK_LIVE_AUFGEBEN);
    e = live_e(SW_VERSATZ_409_STATUS, SW_VERSATZ_409, 0, 9);
    PRUEFE(e.aktion == VERMERK_LIVE_AUFGEBEN);
    /* vorruebergehend: spaeter dieselben Bytes noch einmal */
    e = live_e(0, NULL, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_SPAETER);
    e = live_e(SW_UEBERLAST_503_STATUS, SW_UEBERLAST_503, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_SPAETER);
    e = live_e(SW_PLATTE_VOLL_507_STATUS, SW_PLATTE_VOLL_507, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_SPAETER);
    e = live_e(200, "{}", 0, 10);   /* 200 ohne Stand: unerwartet, spaeter */
    PRUEFE(e.aktion == VERMERK_LIVE_SPAETER);
    /* dauerhaft: aufgeben (Token, Name, Groesse ...) */
    e = live_e(SW_TOKEN_401_STATUS, SW_TOKEN_401, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_AUFGEBEN);
    e = live_e(SW_ZU_GROSS_413_STATUS, SW_ZU_GROSS_413, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_AUFGEBEN);
    e = live_e(SW_NAME_400_STATUS, SW_NAME_400, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_AUFGEBEN);
    e = live_e(SW_PFAD_404_STATUS, SW_PFAD_404, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_AUFGEBEN);
    /* 422 gibt es nur beim Abschluss; kommt es doch, wird nicht weitergebohrt */
    e = live_e(SW_ABSCHLUSS_GROESSE_422_STATUS, SW_ABSCHLUSS_GROESSE_422, 0, 10);
    PRUEFE(e.aktion == VERMERK_LIVE_SPAETER || e.aktion == VERMERK_LIVE_AUFGEBEN);
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
    test_vertrag_mit_der_software();
    test_json_text_und_promille();
    test_status();
    test_status_entscheiden();
    test_live_entscheiden();
    test_wartezeit();
    test_warteliste();

    if (fehler > 0) {
        fprintf(stderr, "%d von %d Pruefungen fehlgeschlagen\n", fehler, pruefungen);
        return 1;
    }
    printf("Alle %d Pruefungen bestanden\n", pruefungen);
    return 0;
}
