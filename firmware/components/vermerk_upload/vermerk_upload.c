/* Upload nach protokoll_assistent/GERAETE-SCHNITTSTELLE.md, siehe vermerk_upload.h.
 *
 * Ablauf je Datei:
 *   GET /api/v1/aufnahmen/<Name>          -> naechstes_byte N
 *   erste N Bytes in die SHA-256 einrechnen (Datei von vorn lesen)
 *   PUT ab N in Stuecken (256 KiB, gestreamt aus einem kleinen Puffer), dabei weiter hashen
 *   PUT mit Content-Length 0, X-Gesamtgroesse und X-SHA256 -> "fertig":true
 * Was nach jeder Antwort passiert, entscheidet vermerk_entscheiden() (auf dem PC getestet). */

#include "vermerk_upload.h"

#include "esp_http_client.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define VERMERK_URL_MAX          192    /* 96 Bytes Adresse + /api/v1/aufnahmen/ + Dateiname (69) */
#define VERMERK_AUTH_MAX         (sizeof("Bearer ") + VERMERK_TOKEN_MAX)
#define VERMERK_ANTWORT_MAX      256    /* die Antworten sind kurz; mehr wird nicht gelesen */
#define VERMERK_HALLO_TIMEOUT_MS 2000
#define VERMERK_UPLOAD_TIMEOUT_MS 15000
#define VERMERK_OHNE_FORTSCHRITT_MAX 3  /* so oft hintereinander kein Fortschritt: spaeter erneut */

#define HASH_UNBEKANNT UINT64_MAX

/* Arbeitsspeicher eines Aufrufs. Liegt im Heap, damit die aufrufenden Tasks (4 bzw. 8 KB Stack)
 * nicht wachsen muessen. */
typedef struct {
    esp_http_client_handle_t client;
    char url[VERMERK_URL_MAX];
    char auth[VERMERK_AUTH_MAX];
    char antwort[VERMERK_ANTWORT_MAX];
    int antwort_laenge;
    char zahl[24];
    char sha_hex[VERMERK_SHA256_HEX_GROESSE];
    mbedtls_sha256_context sha;
    uint64_t gehasht;            /* so viele Bytes vom Dateianfang stecken in sha; HASH_UNBEKANNT = neu rechnen */
    /* Diagnose */
    int64_t verbinden_us;
    int64_t sd_us;
    int64_t netz_us;
    int64_t antwort_us;
    uint64_t gesendet;
    uint32_t stuecke;
} vermerk_arbeit_t;

static bool ziel_lesen(vermerk_ziel_t ziel, const char **url, const char **token)
{
    *url = vermerk_konfig_url(ziel);
    *token = vermerk_konfig_token(ziel);
    return *url != NULL && (*url)[0] != '\0' && vermerk_token_gueltig(*token);
}

/* Client mit Token und Kennung anlegen. Das Token wird nie ausgegeben. */
static bool client_anlegen(vermerk_arbeit_t *a, const char *token, int timeout_ms)
{
    esp_http_client_config_t config = {
        .url = a->url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = timeout_ms,
    };
    a->client = esp_http_client_init(&config);
    if (a->client == NULL) {
        return false;
    }
    snprintf(a->auth, sizeof(a->auth), "Bearer %s", token);
    esp_http_client_set_header(a->client, "Authorization", a->auth);
    memset(a->auth, 0, sizeof(a->auth));   /* der Client hat seine eigene Kopie */
    if (vermerk_geraete_id()[0] != '\0') {
        esp_http_client_set_header(a->client, "X-Geraete-Id", vermerk_geraete_id());
    }
    esp_http_client_set_header(a->client, "X-Firmware", vermerk_firmware());
    return true;
}

static esp_err_t anfrage_oeffnen(vermerk_arbeit_t *a, esp_http_client_method_t methode, int laenge)
{
    esp_http_client_set_url(a->client, a->url);
    esp_http_client_set_method(a->client, methode);
    int64_t t0 = esp_timer_get_time();
    esp_err_t err = esp_http_client_open(a->client, laenge);
    a->verbinden_us += esp_timer_get_time() - t0;
    return err;
}

/* Antwort abholen (Status und hoechstens VERMERK_ANTWORT_MAX - 1 Bytes Text), Verbindung schliessen.
 * Rueckgabe: HTTP-Status, 0 = keine Antwort. */
static int anfrage_beenden(vermerk_arbeit_t *a)
{
    int64_t t0 = esp_timer_get_time();
    int status = 0;
    a->antwort_laenge = 0;
    a->antwort[0] = '\0';

    if (esp_http_client_fetch_headers(a->client) >= 0) {
        status = esp_http_client_get_status_code(a->client);
        int n = esp_http_client_read_response(a->client, a->antwort, VERMERK_ANTWORT_MAX - 1);
        if (n > 0) {
            a->antwort_laenge = n;
            a->antwort[n] = '\0';
        }
    }
    esp_http_client_close(a->client);
    a->antwort_us += esp_timer_get_time() - t0;
    return status;
}

/* ---- GET /api/v1/hallo ---- */

vermerk_hallo_t vermerk_hallo(vermerk_ziel_t ziel)
{
    vermerk_hallo_t ergebnis = {.erreichbar = false, .http_status = -1, .teil_max_bytes = 0};
    const char *url;
    const char *token;
    if (!ziel_lesen(ziel, &url, &token)) {
        return ergebnis;
    }

    vermerk_arbeit_t *a = calloc(1, sizeof(*a));
    if (a == NULL) {
        ergebnis.http_status = 0;
        return ergebnis;
    }
    ergebnis.http_status = 0;

    int n = snprintf(a->url, sizeof(a->url), "%s/api/v1/hallo", url);
    if (n > 0 && (size_t)n < sizeof(a->url) && client_anlegen(a, token, VERMERK_HALLO_TIMEOUT_MS)) {
        if (anfrage_oeffnen(a, HTTP_METHOD_GET, 0) == ESP_OK) {
            ergebnis.http_status = anfrage_beenden(a);
            ergebnis.erreichbar = ergebnis.http_status == 200 &&
                                  vermerk_hallo_pruefen(a->antwort, (size_t)a->antwort_laenge,
                                                        &ergebnis.teil_max_bytes);
        }
        esp_http_client_cleanup(a->client);
    }
    free(a);
    return ergebnis;
}

/* ---- Upload ---- */

static bool lesen(vermerk_arbeit_t *a, FILE *f, uint8_t *puffer, size_t n)
{
    int64_t t0 = esp_timer_get_time();
    size_t gelesen = fread(puffer, 1, n, f);
    a->sd_us += esp_timer_get_time() - t0;
    return gelesen == n;
}

/* SHA-256 der ersten bis Bytes neu berechnen (nach Wiederaufnahme, 409 oder Abbruch mitten im Stueck) */
static bool praefix_hashen(vermerk_arbeit_t *a, FILE *f, uint8_t *puffer, size_t puffer_groesse, uint64_t bis)
{
    a->gehasht = HASH_UNBEKANNT;
    if (mbedtls_sha256_starts(&a->sha, 0) != 0 || fseek(f, 0, SEEK_SET) != 0) {
        return false;
    }
    uint64_t pos = 0;
    while (pos < bis) {
        size_t n = (bis - pos < puffer_groesse) ? (size_t)(bis - pos) : puffer_groesse;
        if (!lesen(a, f, puffer, n) || mbedtls_sha256_update(&a->sha, puffer, n) != 0) {
            return false;
        }
        pos += n;
    }
    a->gehasht = bis;
    return true;
}

/* PUT eines Stuecks [ab, ab + laenge). Rueckgabe: HTTP-Status, 0 = Verbindung/Lesen gescheitert. */
static int teil_senden(vermerk_arbeit_t *a, FILE *f, uint8_t *puffer, size_t puffer_groesse,
                       uint64_t ab, uint32_t laenge)
{
    if (fseek(f, (long)ab, SEEK_SET) != 0) {
        return 0;
    }
    snprintf(a->zahl, sizeof(a->zahl), "%llu", (unsigned long long)ab);
    esp_http_client_set_header(a->client, "X-Offset", a->zahl);
    esp_http_client_set_header(a->client, "Content-Type", "application/octet-stream");
    esp_http_client_delete_header(a->client, "X-Gesamtgroesse");
    esp_http_client_delete_header(a->client, "X-SHA256");

    if (anfrage_oeffnen(a, HTTP_METHOD_PUT, (int)laenge) != ESP_OK) {
        return 0;
    }
    a->stuecke++;

    uint32_t rest = laenge;
    while (rest > 0) {
        size_t n = (rest < puffer_groesse) ? rest : puffer_groesse;
        if (!lesen(a, f, puffer, n)) {
            esp_http_client_close(a->client);
            return 0;
        }
        /* nur weiterhashen, wenn der Hash genau bis hierher reicht */
        if (a->gehasht == ab + (laenge - rest)) {
            if (mbedtls_sha256_update(&a->sha, puffer, n) == 0) {
                a->gehasht += n;
            } else {
                a->gehasht = HASH_UNBEKANNT;
            }
        }

        int64_t t0 = esp_timer_get_time();
        size_t versatz = 0;
        while (versatz < n) {
            int geschrieben = esp_http_client_write(a->client, (const char *)puffer + versatz, (int)(n - versatz));
            if (geschrieben <= 0) {
                a->netz_us += esp_timer_get_time() - t0;
                esp_http_client_close(a->client);
                return 0;
            }
            versatz += (size_t)geschrieben;
        }
        a->netz_us += esp_timer_get_time() - t0;
        a->gesendet += n;
        rest -= (uint32_t)n;
    }
    return anfrage_beenden(a);
}

/* Abschluss: leeres PUT mit Gesamtgroesse und Pruefsumme */
static int abschluss_senden(vermerk_arbeit_t *a, uint64_t ab, uint64_t groesse)
{
    uint8_t sha[32];
    int fehler = mbedtls_sha256_finish(&a->sha, sha);
    a->gehasht = HASH_UNBEKANNT;   /* der Zustand ist verbraucht */
    if (fehler != 0 || !vermerk_hex(sha, sizeof(sha), a->sha_hex, sizeof(a->sha_hex))) {
        return 0;
    }

    snprintf(a->zahl, sizeof(a->zahl), "%llu", (unsigned long long)ab);
    esp_http_client_set_header(a->client, "X-Offset", a->zahl);
    snprintf(a->zahl, sizeof(a->zahl), "%llu", (unsigned long long)groesse);
    esp_http_client_set_header(a->client, "X-Gesamtgroesse", a->zahl);
    esp_http_client_set_header(a->client, "X-SHA256", a->sha_hex);

    if (anfrage_oeffnen(a, HTTP_METHOD_PUT, 0) != ESP_OK) {
        return 0;
    }
    return anfrage_beenden(a);
}

static vermerk_ergebnis_t ergebnis_aus(vermerk_aktion_t aktion)
{
    return (aktion == VERMERK_AKTION_AUFGEBEN) ? VERMERK_ERGEBNIS_AUFGEBEN : VERMERK_ERGEBNIS_SPAETER;
}

static void fehler_melden(const vermerk_arbeit_t *a, const char *name, const char *wobei, int status)
{
    if (status == 0) {
        printf("VERMERK Upload %s: keine Antwort bei %s\n", name, wobei);
    } else {
        printf("VERMERK Upload %s: HTTP %d bei %s %.*s\n", name, status, wobei, a->antwort_laenge, a->antwort);
    }
}

vermerk_ergebnis_t vermerk_upload_datei(vermerk_ziel_t ziel, uint32_t teil_max_bytes,
                                        const char *pfad, const char *name,
                                        size_t puffer_gross, size_t puffer_klein,
                                        vermerk_abbrechen_t abbrechen)
{
    const char *url;
    const char *token;
    if (!ziel_lesen(ziel, &url, &token)) {
        return VERMERK_ERGEBNIS_KEIN_ZIEL;
    }
    if (!vermerk_name_gueltig(name)) {
        printf("VERMERK Upload %s: Dateiname passt nicht zur Schnittstelle\n", name);
        return VERMERK_ERGEBNIS_AUFGEBEN;
    }

    FILE *f = fopen(pfad, "rb");
    if (f == NULL) {
        return VERMERK_ERGEBNIS_SPAETER;
    }
    long dateigroesse = (fseek(f, 0, SEEK_END) == 0) ? ftell(f) : -1;
    if (dateigroesse <= 0) {
        fclose(f);
        return VERMERK_ERGEBNIS_AUFGEBEN;
    }
    const uint64_t groesse = (uint64_t)dateigroesse;

    vermerk_arbeit_t *a = calloc(1, sizeof(*a));
    /* Grosse Bloecke: weniger SD-Zugriffe und weniger Aufrufe in den TCP-Stack. Ist das interne RAM
     * knapp (Encoder und sein Stack liegen dauerhaft darin), reicht auch ein kleiner Puffer. */
    size_t puffer_groesse = puffer_gross;
    uint8_t *puffer = heap_caps_malloc(puffer_groesse, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (puffer == NULL && puffer_klein < puffer_gross) {
        puffer_groesse = puffer_klein;
        puffer = heap_caps_malloc(puffer_groesse, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    if (a == NULL || puffer == NULL) {
        free(puffer);
        free(a);
        fclose(f);
        printf("VERMERK Upload %s: zu wenig RAM\n", name);
        return VERMERK_ERGEBNIS_SPAETER;
    }

    vermerk_ergebnis_t ergebnis = VERMERK_ERGEBNIS_SPAETER;
    int n = snprintf(a->url, sizeof(a->url), "%s/api/v1/aufnahmen/%s", url, name);
    if (n <= 0 || (size_t)n >= sizeof(a->url) || !client_anlegen(a, token, VERMERK_UPLOAD_TIMEOUT_MS)) {
        printf("VERMERK Upload %s: Adresse zu lang oder kein HTTP-Client\n", name);
        free(puffer);
        free(a);
        fclose(f);
        return VERMERK_ERGEBNIS_AUFGEBEN;
    }

    mbedtls_sha256_init(&a->sha);
    a->gehasht = HASH_UNBEKANNT;
    const uint32_t teil = vermerk_teil_bytes(teil_max_bytes);
    /* Obergrenze fuer Anfragen: alle Stuecke + reichlich Spielraum fuer 409/422 */
    const uint64_t max_schritte = groesse / teil + 16;

    int64_t t_start = esp_timer_get_time();
    bool von_vorn = false;
    int ohne_fortschritt = 0;
    uint64_t letztes_n = 0;
    bool hat_letztes_n = false;
    uint64_t start_byte = 0;
    bool hat_start = false;
    uint64_t schritte = 0;

    int status = 0;
    if (anfrage_oeffnen(a, HTTP_METHOD_GET, 0) == ESP_OK) {
        status = anfrage_beenden(a);
    }
    vermerk_phase_t phase = VERMERK_PHASE_STATUS;
    vermerk_entscheidung_t e = vermerk_entscheiden(phase, status, a->antwort, (size_t)a->antwort_laenge, von_vorn);

    for (;;) {
        if (e.aktion == VERMERK_AKTION_FERTIG) {
            ergebnis = VERMERK_ERGEBNIS_FERTIG;
            break;
        }
        if (e.aktion == VERMERK_AKTION_SPAETER || e.aktion == VERMERK_AKTION_AUFGEBEN) {
            fehler_melden(a, name, phase == VERMERK_PHASE_STATUS ? "Statusabfrage" :
                                   phase == VERMERK_PHASE_TEIL ? "Stueck" : "Abschluss", status);
            ergebnis = ergebnis_aus(e.aktion);
            break;
        }
        if (e.aktion == VERMERK_AKTION_VON_VORN) {
            printf("VERMERK Upload %s: Groesse oder Pruefsumme passten nicht, beginne von vorn\n", name);
            von_vorn = true;
            hat_letztes_n = false;
            ohne_fortschritt = 0;
            e.aktion = VERMERK_AKTION_WEITER_AB;
            e.naechstes_byte = 0;
        }

        /* VERMERK_AKTION_WEITER_AB */
        uint64_t ab = e.naechstes_byte;
        if (!hat_start) {
            start_byte = ab;
            hat_start = true;
        }
        if (hat_letztes_n && ab <= letztes_n) {
            if (++ohne_fortschritt >= VERMERK_OHNE_FORTSCHRITT_MAX) {
                printf("VERMERK Upload %s: kein Fortschritt (Byte %llu), spaeter erneut\n",
                       name, (unsigned long long)ab);
                ergebnis = VERMERK_ERGEBNIS_SPAETER;
                break;
            }
        } else {
            ohne_fortschritt = 0;
        }
        letztes_n = ab;
        hat_letztes_n = true;
        if (++schritte > max_schritte) {
            printf("VERMERK Upload %s: zu viele Anfragen, spaeter erneut\n", name);
            ergebnis = VERMERK_ERGEBNIS_SPAETER;
            break;
        }
        if (abbrechen != NULL && abbrechen()) {
            ergebnis = VERMERK_ERGEBNIS_UNTERBROCHEN;
            break;
        }

        /* Hat die Software mehr als die Datei (z. B. alter Teilstand unter gleichem Namen), geht es
         * direkt zum Abschluss ab ihrem Byte: Die Groesse passt dann nicht, sie antwortet 422 und
         * verwirft den Teilstand, danach beginnt die Datei von vorn. */
        uint64_t praefix = (ab < groesse) ? ab : groesse;
        if (a->gehasht != praefix && !praefix_hashen(a, f, puffer, puffer_groesse, praefix)) {
            printf("VERMERK Upload %s: Lesefehler\n", name);
            ergebnis = VERMERK_ERGEBNIS_SPAETER;
            break;
        }

        if (ab < groesse) {
            uint64_t rest = groesse - ab;
            uint32_t laenge = (rest < teil) ? (uint32_t)rest : teil;
            phase = VERMERK_PHASE_TEIL;
            status = teil_senden(a, f, puffer, puffer_groesse, ab, laenge);
        } else {
            phase = VERMERK_PHASE_ABSCHLUSS;
            status = abschluss_senden(a, ab, groesse);
        }
        e = vermerk_entscheiden(phase, status, a->antwort, (size_t)a->antwort_laenge, von_vorn);
    }

    int64_t t_ende = esp_timer_get_time();
    int64_t gesamt_ms = (t_ende - t_start) / 1000;
    printf("VERMERK Upload-Diagnose %s (%s): ab Byte %llu, %u KB in %u Stuecken, gesamt %lld ms (%lld KB/s) | "
           "Verbinden %lld ms, SD lesen %lld ms, WLAN senden %lld ms, Serverantwort %lld ms | "
           "Puffer %u B, Stack frei %u B, Ergebnis: %s\n",
           name, vermerk_konfig_ziel_name(ziel), (unsigned long long)start_byte,
           (unsigned)(a->gesendet / 1024), (unsigned)a->stuecke, (long long)gesamt_ms,
           (long long)(gesamt_ms > 0 ? (int64_t)(a->gesendet / 1024) * 1000 / gesamt_ms : 0),
           (long long)(a->verbinden_us / 1000), (long long)(a->sd_us / 1000),
           (long long)(a->netz_us / 1000), (long long)(a->antwort_us / 1000),
           (unsigned)puffer_groesse, (unsigned)uxTaskGetStackHighWaterMark(NULL),
           vermerk_ergebnis_text(ergebnis));

    mbedtls_sha256_free(&a->sha);
    esp_http_client_cleanup(a->client);
    free(puffer);
    free(a);
    fclose(f);
    return ergebnis;
}
