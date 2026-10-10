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

uint16_t BLE_NUM = 0;
uint16_t WIFI_NUM = 0;
bool Scan_finish = 0;

bool WiFi_Scan_Finish = 0;
bool BLE_Scan_Finish = 0;
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

    // // BLE
    // xTaskCreatePinnedToCore(
    //     BLE_Init, 
    //     "BLE task",
    //     4096, 
    //     NULL, 
    //     2, 
    //     NULL, 
    //     0);
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

uint16_t WIFI_Scan(void)
{
    uint16_t ap_count = 0;
    esp_wifi_scan_start(NULL, true);
    ESP_ERROR_CHECK(esp_wifi_scan_get_ap_num(&ap_count));
    esp_wifi_scan_stop();
    WiFi_Scan_Finish =1;
    if(BLE_Scan_Finish == 1)
        Scan_finish = 1;
    if(WiFi_Scan_Finish == 1)
        Scan_finish = 1;
    return ap_count;
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
    size_t chunk_size = UPLOAD_CHUNK_SIZE;
    uint8_t *buffer = heap_caps_malloc(chunk_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (buffer == NULL) {
        /* Internes RAM ist knapp (Opus-Encoder und sein Stack liegen dauerhaft darin): kleiner Puffer */
        chunk_size = 4 * 1024;
        buffer = heap_caps_malloc(chunk_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    if (buffer == NULL) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        fclose(file);
        return ESP_ERR_NO_MEM;
    }
    size_t total_sent = 0;

    while (!feof(file)) {
        int64_t t0 = esp_timer_get_time();
        size_t read_len = fread(buffer, 1, chunk_size, file);
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

#define GATTC_TAG "GATTC_TAG"
#define SCAN_DURATION 5  
#define MAX_DISCOVERED_DEVICES 100 

typedef struct {
    uint8_t address[6];
    bool is_valid;
} discovered_device_t;

static discovered_device_t discovered_devices[MAX_DISCOVERED_DEVICES];
static size_t num_discovered_devices = 0;
static size_t num_devices_with_name = 0; 

static bool is_device_discovered(const uint8_t *addr) {
    for (size_t i = 0; i < num_discovered_devices; i++) {
        if (memcmp(discovered_devices[i].address, addr, 6) == 0) {
            return true;
        }
    }
    return false;
}

static void add_device_to_list(const uint8_t *addr) {
    if (num_discovered_devices < MAX_DISCOVERED_DEVICES) {
        memcpy(discovered_devices[num_discovered_devices].address, addr, 6);
        discovered_devices[num_discovered_devices].is_valid = true;
        num_discovered_devices++;
    }
}

static bool extract_device_name(const uint8_t *adv_data, uint8_t adv_data_len, char *device_name, size_t max_name_len) {
    size_t offset = 0;
    while (offset < adv_data_len) {
        if (adv_data[offset] == 0) break; 

        uint8_t length = adv_data[offset];
        if (length == 0 || offset + length > adv_data_len) break; 

        uint8_t type = adv_data[offset + 1];
        if (type == ESP_BLE_AD_TYPE_NAME_CMPL || type == ESP_BLE_AD_TYPE_NAME_SHORT) {
            if (length > 1 && length - 1 < max_name_len) {
                memcpy(device_name, &adv_data[offset + 2], length - 1);
                device_name[length - 1] = '\0'; 
                return true;
            } else {
                return false;
            }
        }
        offset += length + 1;
    }
    return false;
}

static void esp_gap_cb(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
    static char device_name[100]; 

    switch (event) {
        case ESP_GAP_BLE_SCAN_RESULT_EVT:
            if (param->scan_rst.search_evt == ESP_GAP_SEARCH_INQ_RES_EVT) {
                if (!is_device_discovered(param->scan_rst.bda)) {
                    add_device_to_list(param->scan_rst.bda);
                    BLE_NUM++; 

                    if (extract_device_name(param->scan_rst.ble_adv, param->scan_rst.adv_data_len, device_name, sizeof(device_name))) {
                        num_devices_with_name++;
                        // printf("Found device: %02X:%02X:%02X:%02X:%02X:%02X\n        Name: %s\n        RSSI: %d\r\n",
                        //          param->scan_rst.bda[0], param->scan_rst.bda[1],
                        //          param->scan_rst.bda[2], param->scan_rst.bda[3],
                        //          param->scan_rst.bda[4], param->scan_rst.bda[5],
                        //          device_name, param->scan_rst.rssi);
                        // printf("\r\n");
                    } else {
                        // printf("Found device: %02X:%02X:%02X:%02X:%02X:%02X\n        Name: Unknown\n        RSSI: %d\r\n",
                        //          param->scan_rst.bda[0], param->scan_rst.bda[1],
                        //          param->scan_rst.bda[2], param->scan_rst.bda[3],
                        //          param->scan_rst.bda[4], param->scan_rst.bda[5],
                        //          param->scan_rst.rssi);
                        // printf("\r\n");
                    }
                }
            }
            break;
        case ESP_GAP_BLE_SCAN_STOP_COMPLETE_EVT:
            ESP_LOGI(GATTC_TAG, "Scan complete. Total devices found: %d (with names: %d)", BLE_NUM, num_devices_with_name);
            break;
        default:
            break;
    }
}

void BLE_Init(void *arg)
{
    ESP_ERROR_CHECK(esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT));
    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    esp_err_t ret = esp_bt_controller_init(&bt_cfg);                                            
    if (ret) {
        printf("%s initialize controller failed: %s\n", __func__, esp_err_to_name(ret));        
        return;}
    ret = esp_bt_controller_enable(ESP_BT_MODE_BLE);                                            
    if (ret) {
        printf("%s enable controller failed: %s\n", __func__, esp_err_to_name(ret));            
        return;}
    ret = esp_bluedroid_init();                                                                 
    if (ret) {
        printf("%s init bluetooth failed: %s\n", __func__, esp_err_to_name(ret));               
        return;}
    ret = esp_bluedroid_enable();                                                               
    if (ret) {
        printf("%s enable bluetooth failed: %s\n", __func__, esp_err_to_name(ret));             
        return;}

    //register the  callback function to the gap module
    ret = esp_ble_gap_register_callback(esp_gap_cb);                                            
    if (ret){
        printf("%s gap register error, error code = %x\n", __func__, ret);                      
        return;
    }
    BLE_Scan();
    // while(1)
    // {
    //     vTaskDelay(pdMS_TO_TICKS(150));
    // }
    
    vTaskDelete(NULL);

}
uint16_t BLE_Scan(void)
{
    esp_ble_scan_params_t scan_params = {
        .scan_type = BLE_SCAN_TYPE_ACTIVE,
        .own_addr_type = BLE_ADDR_TYPE_RPA_PUBLIC,
        .scan_filter_policy = BLE_SCAN_FILTER_ALLOW_ALL,
        .scan_interval = 0x50,     
        .scan_window = 0x30,        
        .scan_duplicate         = BLE_SCAN_DUPLICATE_DISABLE
    };
    ESP_ERROR_CHECK(esp_ble_gap_set_scan_params(&scan_params));

    printf("Starting BLE scan...\n");
    ESP_ERROR_CHECK(esp_ble_gap_start_scanning(SCAN_DURATION));
    
    // Set scanning duration
    vTaskDelay(SCAN_DURATION * 1000 / portTICK_PERIOD_MS);
    
    printf("Stopping BLE scan...\n");
    // ESP_ERROR_CHECK(esp_ble_gap_stop_scanning());
    ESP_ERROR_CHECK(esp_ble_dtm_stop());
    BLE_Scan_Finish = 1;
    if(WiFi_Scan_Finish == 1)
        Scan_finish = 1;
    return BLE_NUM;
}