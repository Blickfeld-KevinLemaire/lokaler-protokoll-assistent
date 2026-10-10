#include "Storage.h"

#include "esp_log.h"
#include "esp_vfs_fat.h"
#include "wear_levelling.h"

static const char *TAG = "STORAGE";

bool g_storage_mounted = false;
static wl_handle_t s_wl_handle = WL_INVALID_HANDLE;

void Storage_Init(void)
{
    const esp_vfs_fat_mount_config_t mount_config = {
        .format_if_mount_failed = true,
        .max_files = 5,
        .allocation_unit_size = 4096,
    };

    esp_err_t ret = esp_vfs_fat_spiflash_mount_rw_wl(REC_DIR, "storage", &mount_config, &s_wl_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Flash-Speicher nicht eingehaengt: %s", esp_err_to_name(ret));
        return;
    }
    g_storage_mounted = true;

    uint64_t total = 0, free_b = 0;
    if (esp_vfs_fat_info(REC_DIR, &total, &free_b) == ESP_OK) {
        ESP_LOGI(TAG, "Flash-Speicher bereit: %llu KB gesamt, %llu KB frei",
                 (unsigned long long)(total / 1024), (unsigned long long)(free_b / 1024));
    }
}

uint64_t Storage_Free_Bytes(void)
{
    uint64_t total = 0, free_b = 0;
    if (!g_storage_mounted || esp_vfs_fat_info(REC_DIR, &total, &free_b) != ESP_OK) {
        return 0;
    }
    return free_b;
}

uint64_t Storage_Total_Bytes(void)
{
    uint64_t total = 0, free_b = 0;
    if (!g_storage_mounted || esp_vfs_fat_info(REC_DIR, &total, &free_b) != ESP_OK) {
        return 0;
    }
    return total;
}
