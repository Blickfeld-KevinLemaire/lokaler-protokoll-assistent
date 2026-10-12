#include "Wireless.h"
#include "vermerk_konfig.h"
#include "esp_event.h"
#include "esp_netif.h"
#include <stdlib.h>

volatile bool WIFI_CONNECTED = false;
volatile bool SERVER_REACHABLE = false;
volatile bool PC_REACHABLE = false;

/* Lesepuffer fuer den Upload im internen RAM. Ist es knapp (Opus-Encoder und sein Stack liegen
 * dauerhaft darin), nimmt der Upload den kleinen. */
#define UPLOAD_PUFFER_GROSS  (16 * 1024)
#define UPLOAD_PUFFER_KLEIN  (4 * 1024)

/* Von /api/v1/hallo gemeldete Stueckgroesse je Ziel (0 = Standard) */
static volatile uint32_t teil_max_bytes[2];

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    }
    else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        WIFI_CONNECTED = false;
        SERVER_REACHABLE = false;
        PC_REACHABLE = false;
        esp_wifi_connect();
    }
    else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        WIFI_CONNECTED = true;
    }
}

/* Fragt GET /api/v1/hallo eines Ziels ab (mit Token). Erreichbar nur, wenn dort wirklich die
 * Protokoll-Software antwortet. Aenderungen erscheinen einmal im Monitor. */
static bool probe_target(vermerk_ziel_t ziel, int *letzter_zustand)
{
    vermerk_hallo_t hallo = vermerk_hallo(ziel);
    int zustand = hallo.erreichbar ? 1000 : hallo.http_status;

    if (zustand != *letzter_zustand) {
        *letzter_zustand = zustand;
        const char *name = vermerk_konfig_ziel_name(ziel);
        if (hallo.erreichbar) {
            printf("VERMERK %s erreichbar (Stuecke bis %u KB)\n", name,
                   (unsigned)(vermerk_teil_bytes(hallo.teil_max_bytes) / 1024));
        } else if (hallo.http_status == -1) {
            /* Ziel nicht eingerichtet (leere Adresse oder kein Token): nichts melden */
        } else if (hallo.http_status == 0) {
            printf("VERMERK %s antwortet nicht\n", name);
        } else if (hallo.http_status == 401) {
            printf("VERMERK %s lehnt das Token ab (HTTP 401): Token in server_config.h pruefen\n", name);
        } else if (hallo.http_status == 200) {
            printf("VERMERK %s: dort antwortet nicht die Protokoll-Software (Schnittstelle 1)\n", name);
        } else {
            printf("VERMERK %s: HTTP %d auf /api/v1/hallo\n", name, hallo.http_status);
        }
    }

    teil_max_bytes[ziel] = hallo.teil_max_bytes;
    return hallo.erreichbar;
}

static void server_check_task(void *arg)
{
    int zustand_server = -2;
    int zustand_pc = -2;

    while (1) {
        if (WIFI_CONNECTED) {
            SERVER_REACHABLE = probe_target(VERMERK_ZIEL_SERVER, &zustand_server);
            PC_REACHABLE = probe_target(VERMERK_ZIEL_PC, &zustand_pc);
        } else {
            SERVER_REACHABLE = false;
            PC_REACHABLE = false;
            zustand_server = -2;
            zustand_pc = -2;
        }

        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}

void Wireless_Init(void)
{
    // Initialize NVS.
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK( ret );

    /* Einrichtung ueber USB aus dem NVS, sonst die einkompilierten Werte (vor dem WLAN-Start) */
    vermerk_konfig_laden();

    /* Kennung fuer die Zuordnung am USB-Monitor; geht auch mit jeder Anfrage an die Software */
    const char *geraete_id = vermerk_geraete_id();
    printf("VERMERK Geraete-Id: %s, Firmware: %s\n", geraete_id[0] != '\0' ? geraete_id : "unbekannt", vermerk_firmware());

    // WiFi
    xTaskCreatePinnedToCore(
        WIFI_Init,
        "WIFI task",
        4096,
        NULL,
        1,
        NULL,
        0);
    xTaskCreatePinnedToCore(
        server_check_task,
        "server_check",
        4096,
        NULL,
        1,
        NULL,
        0);
}

void WIFI_Init(void *arg)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_config_t wifi_config = {0};
    /* 32 Bytes ohne abschliessendes Nullbyte sind ein gueltiger WLAN-Name */
    memcpy(wifi_config.sta.ssid, vermerk_konfig_wlan_name(),
           strnlen(vermerk_konfig_wlan_name(), sizeof(wifi_config.sta.ssid)));
    strncpy((char *)wifi_config.sta.password, vermerk_konfig_wlan_passwort(), sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.pmf_cfg.capable = true;
    wifi_config.sta.pmf_cfg.required = false;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    vTaskDelete(NULL);
}

/* WLAN-Energiesparen (Standard: MIN_MODEM) bremst den Durchsatz stark,
 * weil das Funkmodul zwischen den Beacons schlaeft. Fuer Uploads abschalten. */
void VERMERK_Wifi_Fast_Mode(bool on)
{
    esp_err_t ps_err = esp_wifi_set_ps(on ? WIFI_PS_NONE : WIFI_PS_MIN_MODEM);
    if (on) {
        wifi_ap_record_t ap = {0};
        int rssi = (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) ? ap.rssi : 0;
        printf("VERMERK WLAN schnell: ps=%s, RSSI %d dBm, Kanal %d, 11%s%s%s\n",
               esp_err_to_name(ps_err), rssi, ap.primary,
               ap.phy_11b ? "b" : "", ap.phy_11g ? "g" : "", ap.phy_11n ? "n" : "");
    }
}

/* Eine Aufnahme hochladen (wiederaufnehmbar, siehe components/vermerk_upload). Ziel: Server hat Vorrang, sonst PC. */
vermerk_ergebnis_t VERMERK_Upload_File(const char *path, const char *filename, vermerk_abbrechen_t abbrechen)
{
    vermerk_ziel_t ziel;
    if (WIFI_CONNECTED && SERVER_REACHABLE) {
        ziel = VERMERK_ZIEL_SERVER;
    } else if (WIFI_CONNECTED && PC_REACHABLE) {
        ziel = VERMERK_ZIEL_PC;
    } else {
        return VERMERK_ERGEBNIS_KEIN_ZIEL;
    }

    return vermerk_upload_datei(ziel, teil_max_bytes[ziel], path, filename,
                                UPLOAD_PUFFER_GROSS, UPLOAD_PUFFER_KLEIN, abbrechen);
}
