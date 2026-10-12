/* Einrichtung ueber USB: Konsole lesen, Anweisungen ausfuehren (siehe vermerk_konsole.h).
 * Lesen und Pruefen der Zeilen: vermerk_einrichtung.c (auf dem PC getestet). Hier nur Ein- und Ausgabe,
 * NVS und Neustart. */

#include "vermerk_konsole.h"
#include "vermerk_einrichtung.h"
#include "vermerk_konfig.h"

#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#elif CONFIG_ESP_CONSOLE_UART
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Gross genug fuer printf und die Zeilenpruefung (Hex-Puffer 256 B); siehe "Stack frei" im Monitor */
#define KONSOLE_STACK      3584
#define NEUSTART_NACH_MS   1000

typedef struct {
    vermerk_aufnahme_laeuft_t aufnahme_laeuft;
    char zeile[VERMERK_ZEILE_MAX + 1];
    char antwort[VERMERK_INFO_MAX + 32];
    vermerk_vormerkung_t vormerkung;
} konsole_t;

/* Ohne Treiber liest die Konsole nicht zuverlaessig (USB-Serial-JTAG) bzw. gar nicht blockierend (UART).
 * Mit Treiber blockiert printf nicht, wenn kein PC zuhoert: USB-Serial-JTAG verwirft dann die Ausgabe. */
static void konsole_vorbereiten(void)
{
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    if (!usb_serial_jtag_is_driver_installed()) {
        usb_serial_jtag_driver_config_t cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
        if (usb_serial_jtag_driver_install(&cfg) != ESP_OK) {
            printf("VERMERK Einrichtung: USB-Serial-JTAG-Treiber nicht installiert\n");
            return;
        }
    }
    usb_serial_jtag_vfs_use_driver();
#elif CONFIG_ESP_CONSOLE_UART
    if (!uart_is_driver_installed(CONFIG_ESP_CONSOLE_UART_NUM)) {
        if (uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 1024, 0, 0, NULL, 0) != ESP_OK) {
            printf("VERMERK Einrichtung: UART-Treiber nicht installiert\n");
            return;
        }
    }
    uart_vfs_dev_use_driver(CONFIG_ESP_CONSOLE_UART_NUM);
#endif
    setvbuf(stdin, NULL, _IONBF, 0);
}

static void senden(const char *zeile)
{
    printf("%s\n", zeile);
    fflush(stdout);
}

static void info_senden(konsole_t *k)
{
    vermerk_info_t info = {
        .geraete_id = vermerk_geraete_id(),
        .board = vermerk_board(),
        .firmware = VERMERK_FIRMWARE_VERSION,
        .eingerichtet = vermerk_konfig_eingerichtet(),
        .wlan_ssid = vermerk_konfig_wlan_name(),
        .pc_url = vermerk_konfig_pc_url(),
        .server_url = vermerk_konfig_server_url(),
        .token_pc = vermerk_konfig_pc_token()[0] != '\0',
        .token_server = vermerk_konfig_server_token()[0] != '\0',
    };
    static const char praefix[] = "#VERMERK INFO ";
    memcpy(k->antwort, praefix, sizeof(praefix));
    if (vermerk_info_json(&info, k->antwort + sizeof(praefix) - 1, sizeof(k->antwort) - (sizeof(praefix) - 1))) {
        senden(k->antwort);
    } else {
        senden("#VERMERK FEHLER INFO Antwort zu lang");
    }
}

static void neu_starten(konsole_t *k, const char *grund)
{
    vermerk_vormerkung_leeren(&k->vormerkung);   /* Passwort und Token aus dem RAM */
    printf("VERMERK Einrichtung: %s, Neustart (Stack frei %u B)\n", grund,
           (unsigned)uxTaskGetStackHighWaterMark(NULL));
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(NEUSTART_NACH_MS));
    esp_restart();
}

static void zeile_ausfuehren(konsole_t *k, size_t laenge, bool zu_lang)
{
    bool aufnahme = (k->aufnahme_laeuft != NULL) && k->aufnahme_laeuft();
    vermerk_zeile_t was = vermerk_zeile_verarbeiten(&k->vormerkung, k->zeile, laenge, zu_lang, aufnahme,
                                                    k->antwort, sizeof(k->antwort));
    switch (was) {
    case VERMERK_ZEILE_ANTWORT:
        senden(k->antwort);
        break;

    case VERMERK_ZEILE_INFO:
        info_senden(k);
        break;

    case VERMERK_ZEILE_SPEICHERN:
        if (vermerk_konfig_speichern(&k->vormerkung.werte)) {
            senden("#VERMERK OK SPEICHERN");
            neu_starten(k, "gespeichert");
        } else {
            senden("#VERMERK FEHLER SPEICHERN NVS nicht beschreibbar");
        }
        break;

    case VERMERK_ZEILE_LOESCHEN:
        if (vermerk_konfig_loeschen()) {
            senden("#VERMERK OK LOESCHEN");
            neu_starten(k, "geloescht, es gelten die einkompilierten Werte");
        } else {
            senden("#VERMERK FEHLER LOESCHEN NVS nicht beschreibbar");
        }
        break;

    case VERMERK_ZEILE_UEBERGEHEN:
    default:
        break;
    }
    memset(k->zeile, 0, sizeof(k->zeile));   /* kann ein Token enthalten haben */
}

static void konsole_task(void *arg)
{
    konsole_t *k = arg;
    size_t laenge = 0;
    bool zu_lang = false;

    konsole_vorbereiten();

    while (1) {
        int c = fgetc(stdin);
        if (c == EOF) {
            /* USB-Serial-JTAG ohne PC liefert sofort EOF: kurz warten statt im Kreis zu laufen */
            clearerr(stdin);
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }
        if (c == '\n' || c == '\r') {
            if (laenge > 0 || zu_lang) {
                k->zeile[laenge] = '\0';
                zeile_ausfuehren(k, laenge, zu_lang);
            }
            laenge = 0;
            zu_lang = false;
            continue;
        }
        if (laenge < VERMERK_ZEILE_MAX) {
            k->zeile[laenge++] = (char)c;
        } else {
            zu_lang = true;   /* Rest der Zeile verwerfen, am Zeilenende Fehler melden */
        }
    }
}

void vermerk_konsole_starten(vermerk_aufnahme_laeuft_t aufnahme_laeuft)
{
    konsole_t *k = calloc(1, sizeof(*k));
    if (k == NULL) {
        printf("VERMERK Einrichtung: zu wenig RAM, Einrichtung ueber USB nicht verfuegbar\n");
        return;
    }
    k->aufnahme_laeuft = aufnahme_laeuft;
    vermerk_vormerkung_leeren(&k->vormerkung);
    if (xTaskCreate(konsole_task, "vermerk_konsole", KONSOLE_STACK, k, 1, NULL) != pdPASS) {
        printf("VERMERK Einrichtung: Task nicht angelegt, Einrichtung ueber USB nicht verfuegbar\n");
        free(k);
    }
}
