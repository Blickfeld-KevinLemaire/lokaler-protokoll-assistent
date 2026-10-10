#include "Wireless.h"
#include "wifi_credentials.h"
#include "server_config.h"
#include "esp_http_client.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include <stdlib.h>

volatile bool WIFI_CONNECTED = false;
volatile bool SERVER_REACHABLE = false;
volatile bool PC_REACHABLE = false;

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

/* Fragt /vermerk-status.txt eines Ziels ab. Leere Basis-URL = nicht konfiguriert. */
static bool probe_target(const char *base_url)
{
    if (base_url[0] == '\0') {
        return false;
    }

    char url[128];
    snprintf(url, sizeof(url), "%s%s", base_url, VERMERK_STATUS_PATH);

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = 2000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        return false;
    }
    esp_err_t err = esp_http_client_perform(client);
    int status = (err == ESP_OK) ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    return err == ESP_OK && status == 200;
}

static void server_check_task(void *arg)
{
    while (1) {
        if (WIFI_CONNECTED) {
            SERVER_REACHABLE = probe_target(VERMERK_SERVER_BASE_URL);
            PC_REACHABLE = probe_target(VERMERK_PC_BASE_URL);
        } else {
            SERVER_REACHABLE = false;
            PC_REACHABLE = false;
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
    strncpy((char *)wifi_config.sta.ssid, VERMERK_WIFI_SSID, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, VERMERK_WIFI_PASSWORD, sizeof(wifi_config.sta.password) - 1);
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

#define UPLOAD_CHUNK_SIZE (16 * 1024)

esp_err_t VERMERK_Upload_File(const char *path, const char *filename)
{
    /* Ziel waehlen: Server hat Vorrang, sonst PC */
    const char *base_url;
    if (WIFI_CONNECTED && SERVER_REACHABLE) {
        base_url = VERMERK_SERVER_BASE_URL;
    } else if (WIFI_CONNECTED && PC_REACHABLE) {
        base_url = VERMERK_PC_BASE_URL;
    } else {
        return ESP_ERR_INVALID_STATE;
    }
    char upload_url[128];
    snprintf(upload_url, sizeof(upload_url), "%s%s", base_url, VERMERK_UPLOAD_PATH);

    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return ESP_ERR_NOT_FOUND;
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return ESP_FAIL;
    }

    long file_size = ftell(file);
    if (file_size <= 0) {
        fclose(file);
        return ESP_FAIL;
    }

    rewind(file);

    esp_http_client_config_t config = {
        .url = upload_url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 15000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        fclose(file);
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/octet-stream");
    esp_http_client_set_header(client, "X-Filename", filename);

    int64_t t_start = esp_timer_get_time();
    esp_err_t err = esp_http_client_open(client, (int)file_size);
    int64_t t_connected = esp_timer_get_time();
    int64_t sd_us = 0;
    int64_t net_us = 0;
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        fclose(file);
        return err;
    }

    /* Grosse Bloecke: weniger SD-Zugriffe und weniger Aufrufe in den TCP-Stack */
    uint8_t *buffer = heap_caps_malloc(UPLOAD_CHUNK_SIZE, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (buffer == NULL) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        fclose(file);
        return ESP_ERR_NO_MEM;
    }
    size_t total_sent = 0;

    while (!feof(file)) {
        int64_t t0 = esp_timer_get_time();
        size_t read_len = fread(buffer, 1, UPLOAD_CHUNK_SIZE, file);
        int64_t t1 = esp_timer_get_time();
        sd_us += t1 - t0;
        if (read_len == 0) {
            if (ferror(file)) {
                err = ESP_FAIL;
            }
            break;
        }

        size_t offset = 0;
        while (offset < read_len) {
            int written = esp_http_client_write(client, (const char *)buffer + offset, read_len - offset);
            if (written <= 0) {
                err = ESP_FAIL;
                break;
            }
            offset += (size_t)written;
        }

        net_us += esp_timer_get_time() - t1;

        if (err != ESP_OK) {
            break;
        }

        total_sent += read_len;
    }

    free(buffer);
    fclose(file);

    if (err == ESP_OK && total_sent == (size_t)file_size) {
        int64_t t_sent = esp_timer_get_time();
        esp_http_client_fetch_headers(client);
        int status = esp_http_client_get_status_code(client);
        int64_t t_done = esp_timer_get_time();
        int64_t total_ms = (t_done - t_start) / 1000;
        printf("VERMERK Upload-Diagnose %s: %u KB, gesamt %lld ms (%lld KB/s) | "
               "Verbinden %lld ms, SD lesen %lld ms, WLAN senden %lld ms, Serverantwort %lld ms\n",
               filename, (unsigned)(total_sent / 1024), (long long)total_ms,
               (long long)(total_ms > 0 ? (int64_t)(total_sent / 1024) * 1000 / total_ms : 0),
               (long long)((t_connected - t_start) / 1000), (long long)(sd_us / 1000),
               (long long)(net_us / 1000), (long long)((t_done - t_sent) / 1000));
        if (status != 200) {
            err = ESP_FAIL;
        }
    } else {
        err = ESP_FAIL;
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return err;
}

