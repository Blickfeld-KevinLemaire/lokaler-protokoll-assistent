/* Ende-zu-Ende-Test der Upload-Komponente in QEMU (ESP32, Ethernet ueber OpenCores/open_eth).
 *
 * Laeuft gegen den echten Empfang der Protokoll-Software (services/geraete_empfang_service.py), den
 * e2e_treiber.py im selben Container startet. Aus QEMU heraus ist der Container unter 10.0.2.2
 * erreichbar (QEMU-User-Netz): Port 8765 = Empfang direkt, Port 8766 = Proxy des Treibers, der eine
 * Verbindung kappen bzw. vor einer Antwort den Stand der Software veraendern kann.
 *
 * Jeder Fall schreibt eine Testdatei (Pseudozufall mit fester Saat, gleiche Folge wie im Treiber) ins
 * FAT im Flash und laedt sie mit vermerk_upload_datei() hoch - derselbe Code wie auf den Geraeten.
 * Ausgabe: je Fall "E2E <Fall>: OK|FEHLER ...", am Ende "E2E ERGEBNIS: PASS|FAIL". */

#include "vermerk_upload.h"
#include "vermerk_konfig_test.h"

#include "esp_event.h"
#include "esp_netif.h"
#include "esp_vfs_fat.h"
#include "nvs_flash.h"
#include "protocol_examples_common.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#define BASIS            "/daten"
#define URL_DIREKT       "http://10.0.2.2:8765"
#define URL_PROXY        "http://10.0.2.2:8766"
/* Test-Token, nur fuer diesen Test (der Treiber traegt seinen Hash ein). Kein Geheimnis. */
#define TOKEN_RICHTIG    "nur-fuer-den-qemu-test-kein-echtes-token-0"
#define TOKEN_FALSCH     "nur-fuer-den-qemu-test-falsches-token-000"
#define PUFFER_GROSS     (16 * 1024)
#define PUFFER_KLEIN     (4 * 1024)

static int s_ok = 0;
static int s_fehler = 0;

static void melden(const char *fall, bool ok, const char *text)
{
    printf("E2E %s: %s %s\n", fall, ok ? "OK" : "FEHLER", text);
    if (ok) {
        s_ok++;
    } else {
        s_fehler++;
    }
}

/* xorshift32, ein Byte je Schritt; e2e_treiber.py rechnet dieselbe Folge */
static uint32_t xorshift(uint32_t x)
{
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x;
}

static bool datei_schreiben(const char *pfad, uint32_t groesse, uint32_t saat)
{
    static uint8_t puffer[4096];
    FILE *f = fopen(pfad, "wb");
    if (f == NULL) {
        return false;
    }
    uint32_t x = saat;
    uint32_t rest = groesse;
    bool ok = true;
    while (rest > 0 && ok) {
        uint32_t n = rest < sizeof(puffer) ? rest : sizeof(puffer);
        for (uint32_t i = 0; i < n; i++) {
            x = xorshift(x);
            puffer[i] = (uint8_t)(x & 0xFF);
        }
        ok = fwrite(puffer, 1, n, f) == n;
        rest -= n;
    }
    return (fclose(f) == 0) && ok;
}

static bool existiert(const char *pfad)
{
    struct stat st;
    return stat(pfad, &st) == 0;
}

static vermerk_ergebnis_t hochladen(vermerk_ziel_t ziel, const char *pfad, const char *name, vermerk_abbrechen_t abbrechen)
{
    vermerk_ergebnis_t e = vermerk_upload_datei(ziel, 0, pfad, name, PUFFER_GROSS, PUFFER_KLEIN, abbrechen);
    printf("E2E   %s -> %s\n", name, vermerk_ergebnis_text(e));
    return e;
}

/* Datei anlegen, einmal hochladen, Ergebnis pruefen, lokale Kopie wie auf dem Geraet erst nach "fertig" loeschen */
static void fall_einfach(const char *fall, const char *name, uint32_t groesse, uint32_t saat, vermerk_ziel_t ziel)
{
    char pfad[64];
    snprintf(pfad, sizeof(pfad), BASIS "/%s", name);
    if (!datei_schreiben(pfad, groesse, saat)) {
        melden(fall, false, "Testdatei nicht geschrieben");
        return;
    }
    vermerk_ergebnis_t e = hochladen(ziel, pfad, name, NULL);
    melden(fall, e == VERMERK_ERGEBNIS_FERTIG, vermerk_ergebnis_text(e));
    if (e == VERMERK_ERGEBNIS_FERTIG) {
        remove(pfad);
    }
}

/* (f) Abbruch zwischen zwei Stuecken: nach dem ersten Stueck "Aufnahme startet" */
static int s_abbruch_fragen = 0;
static bool abbrechen_nach_erstem_stueck(void)
{
    return ++s_abbruch_fragen >= 2;
}

static void e2e_task(void *arg)
{
    char pfad[64];

    printf("E2E KENNUNG: id=%s firmware=%s\n", vermerk_geraete_id(), vermerk_firmware());

    /* hallo: echte Software, richtiges Token */
    vermerk_konfig_test_ziel(VERMERK_ZIEL_SERVER, URL_DIREKT, TOKEN_RICHTIG);
    vermerk_hallo_t h = vermerk_hallo(VERMERK_ZIEL_SERVER);
    char text[96];
    snprintf(text, sizeof(text), "HTTP %d, erreichbar %d, teil_max_bytes %u", h.http_status, h.erreichbar,
             (unsigned)h.teil_max_bytes);
    melden("hallo", h.erreichbar && h.http_status == 200 && h.teil_max_bytes == 4194304u, text);

    /* (a) sauberer Upload in mehreren Stuecken (600000 B = 256 KiB + 256 KiB + Rest) */
    fall_einfach("a", "E2E_A.opus", 600000, 0xA1u, VERMERK_ZIEL_SERVER);

    /* (b) Wiederaufnahme: der Treiber hat die ersten 300000 Bytes schon hochgeladen */
    fall_einfach("b", "E2E_B.opus", 600000, 0xB2u, VERMERK_ZIEL_SERVER);

    /* (c) falsches Token: Ziel nicht erreichbar, Upload abgelehnt, Datei bleibt */
    vermerk_konfig_test_ziel(VERMERK_ZIEL_PC, URL_DIREKT, TOKEN_FALSCH);
    vermerk_hallo_t hf = vermerk_hallo(VERMERK_ZIEL_PC);
    snprintf(pfad, sizeof(pfad), BASIS "/E2E_C.opus");
    bool geschrieben = datei_schreiben(pfad, 10000, 0xC3u);
    vermerk_ergebnis_t ec = hochladen(VERMERK_ZIEL_PC, pfad, "E2E_C.opus", NULL);
    snprintf(text, sizeof(text), "hallo HTTP %d erreichbar %d, Upload %s, Datei da %d", hf.http_status, hf.erreichbar,
             vermerk_ergebnis_text(ec), existiert(pfad));
    melden("c", geschrieben && !hf.erreichbar && hf.http_status == 401 && ec == VERMERK_ERGEBNIS_AUFGEBEN &&
                    existiert(pfad), text);

    /* (d) dieselbe Aufnahme zweimal: beide Male "fertig", die Software legt nur eine Datei ab */
    snprintf(pfad, sizeof(pfad), BASIS "/E2E_D.opus");
    if (datei_schreiben(pfad, 100000, 0xD4u)) {
        vermerk_ergebnis_t d1 = hochladen(VERMERK_ZIEL_SERVER, pfad, "E2E_D.opus", NULL);
        vermerk_ergebnis_t d2 = hochladen(VERMERK_ZIEL_SERVER, pfad, "E2E_D.opus", NULL);
        snprintf(text, sizeof(text), "1. %s, 2. %s", vermerk_ergebnis_text(d1), vermerk_ergebnis_text(d2));
        melden("d", d1 == VERMERK_ERGEBNIS_FERTIG && d2 == VERMERK_ERGEBNIS_FERTIG, text);
        remove(pfad);
    } else {
        melden("d", false, "Testdatei nicht geschrieben");
    }

    /* (e) Verbindung reisst mitten im zweiten Stueck ab (Proxy kappt): erst "spaeter", dann fertig */
    vermerk_konfig_test_ziel(VERMERK_ZIEL_SERVER, URL_PROXY, TOKEN_RICHTIG);
    snprintf(pfad, sizeof(pfad), BASIS "/E2E_E.opus");
    if (datei_schreiben(pfad, 600000, 0xE5u)) {
        vermerk_ergebnis_t e1 = hochladen(VERMERK_ZIEL_SERVER, pfad, "E2E_E.opus", NULL);
        vermerk_ergebnis_t e2 = hochladen(VERMERK_ZIEL_SERVER, pfad, "E2E_E.opus", NULL);
        snprintf(text, sizeof(text), "1. %s, 2. %s", vermerk_ergebnis_text(e1), vermerk_ergebnis_text(e2));
        melden("e", e1 == VERMERK_ERGEBNIS_SPAETER && e2 == VERMERK_ERGEBNIS_FERTIG, text);
        if (e2 == VERMERK_ERGEBNIS_FERTIG) {
            remove(pfad);
        }
    } else {
        melden("e", false, "Testdatei nicht geschrieben");
    }

    /* (i) 409 auf ein volles Stueck: Der Proxy laesst die Software vor der Antwort auf die Statusabfrage
     * schon 256 KiB annehmen; das Geraet sendet ab 0, bekommt 409 und macht beim gemeldeten Byte weiter. */
    fall_einfach("i", "E2E_I.opus", 600000, 0x19u, VERMERK_ZIEL_SERVER);

    /* ab hier wieder direkt */
    vermerk_konfig_test_ziel(VERMERK_ZIEL_SERVER, URL_DIREKT, TOKEN_RICHTIG);

    /* (f) Abbruch nach dem ersten Stueck (neue Aufnahme), danach Fortsetzung */
    snprintf(pfad, sizeof(pfad), BASIS "/E2E_F.opus");
    if (datei_schreiben(pfad, 600000, 0xF6u)) {
        vermerk_ergebnis_t f1 = hochladen(VERMERK_ZIEL_SERVER, pfad, "E2E_F.opus", abbrechen_nach_erstem_stueck);
        vermerk_ergebnis_t f2 = hochladen(VERMERK_ZIEL_SERVER, pfad, "E2E_F.opus", NULL);
        snprintf(text, sizeof(text), "1. %s, 2. %s", vermerk_ergebnis_text(f1), vermerk_ergebnis_text(f2));
        melden("f", f1 == VERMERK_ERGEBNIS_UNTERBROCHEN && f2 == VERMERK_ERGEBNIS_FERTIG, text);
        if (f2 == VERMERK_ERGEBNIS_FERTIG) {
            remove(pfad);
        }
    } else {
        melden("f", false, "Testdatei nicht geschrieben");
    }

    /* (g) 422: Der Treiber hat 300000 falsche Bytes vorgelegt; Pruefsumme passt nicht, einmal von vorn */
    fall_einfach("g", "E2E_G.opus", 600000, 0x67u, VERMERK_ZIEL_SERVER);

    /* (h) Die Software hat mehr als die Datei (150000 von 100000): Abschluss, 422, von vorn */
    fall_einfach("h", "E2E_H.opus", 100000, 0x48u, VERMERK_ZIEL_SERVER);

    printf("E2E Stack frei: %u B, Heap frei: %u B\n", (unsigned)uxTaskGetStackHighWaterMark(NULL),
           (unsigned)esp_get_free_heap_size());
    printf("E2E ERGEBNIS: %s (%d OK, %d FEHLER)\n", s_fehler == 0 ? "PASS" : "FAIL", s_ok, s_fehler);
    fflush(stdout);
    vTaskDelete(NULL);
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_vfs_fat_mount_config_t fat = {
        .format_if_mount_failed = true,
        .max_files = 4,
        .allocation_unit_size = 4096,
    };
    wl_handle_t wl = WL_INVALID_HANDLE;
    if (esp_vfs_fat_spiflash_mount_rw_wl(BASIS, "daten", &fat, &wl) != ESP_OK) {
        printf("E2E ERGEBNIS: FAIL (FAT nicht eingehaengt)\n");
        return;
    }

    ESP_ERROR_CHECK(example_connect());   /* Ethernet (open_eth), DHCP aus dem QEMU-User-Netz */

    /* Upload in einer eigenen Task mit demselben Stack wie auf den Geraeten (upload_manager: 8192) */
    xTaskCreate(e2e_task, "e2e", 8192, NULL, 2, NULL);
}
