#include "Storage.h"
#include "Board_Pins.h"

#include <string.h>
#include "esp_log.h"
#include "esp_vfs_fat.h"
#include "wear_levelling.h"
#include "sdmmc_cmd.h"
#include "driver/sdmmc_host.h"

static const char *TAG = "STORAGE";

bool g_storage_mounted = false;

static bool s_sd_mounted = false;
static bool s_flash_mounted = false;
static sdmmc_card_t *s_sd_card = NULL;
static wl_handle_t s_wl_handle = WL_INVALID_HANDLE;

/* SD-Karte im 1-Bit-SDMMC-Modus (Pins siehe Board_Pins.h) */
static bool mount_sd(void)
{
    esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = false,      /* eine fremde Karte nie ungefragt formatieren */
        .max_files = 5,
        .allocation_unit_size = 16 * 1024
    };

    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    sdmmc_slot_config_t slot_config = SDMMC_SLOT_CONFIG_DEFAULT();
    slot_config.width = 1;
    slot_config.clk = BOARD_SD_CLK;
    slot_config.cmd = BOARD_SD_CMD;
    slot_config.d0 = BOARD_SD_D0;
    slot_config.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;

    esp_err_t ret = esp_vfs_fat_sdmmc_mount(REC_DIR_SD, &host, &slot_config, &mount_config, &s_sd_card);
    if (ret != ESP_OK) {
        if (ret == ESP_FAIL) {
            ESP_LOGW(TAG, "SD-Karte gefunden, aber das Dateisystem ist nicht lesbar (FAT32?) - nutze Flash");
        } else {
            ESP_LOGI(TAG, "Keine SD-Karte (%s) - nutze Flash", esp_err_to_name(ret));
        }
        s_sd_card = NULL;
        return false;
    }

    uint64_t mb = ((uint64_t)s_sd_card->csd.capacity) * s_sd_card->csd.sector_size / (1024 * 1024);
    ESP_LOGI(TAG, "SD-Karte erkannt: %s, %llu MB", s_sd_card->cid.name, (unsigned long long)mb);
    return true;
}

static bool mount_flash(void)
{
    const esp_vfs_fat_mount_config_t mount_config = {
        .format_if_mount_failed = true,
        .max_files = 5,
        .allocation_unit_size = 4096,
    };

    esp_err_t ret = esp_vfs_fat_spiflash_mount_rw_wl(REC_DIR_FLASH, "storage", &mount_config, &s_wl_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Flash-Speicher nicht eingehaengt: %s", esp_err_to_name(ret));
        return false;
    }
    return true;
}

void Storage_Init(void)
{
    s_sd_mounted = mount_sd();
    s_flash_mounted = mount_flash();      /* immer, damit dort liegende Aufnahmen hochgeladen werden */
    g_storage_mounted = s_sd_mounted || s_flash_mounted;

    ESP_LOGI(TAG, "Aufnahmen gehen auf: %s", Storage_Is_Sd() ? "SD-Karte" : "Flash");
    uint64_t total = Storage_Total_Bytes();
    uint64_t free_b = Storage_Free_Bytes();
    ESP_LOGI(TAG, "Platz: %llu MB gesamt, %llu MB frei",
             (unsigned long long)(total / (1024 * 1024)), (unsigned long long)(free_b / (1024 * 1024)));
}

bool Storage_Is_Sd(void)
{
    return s_sd_mounted;
}

const char *Storage_Dir(void)
{
    return Storage_Dir_At(0);
}

int Storage_Dir_Count(void)
{
    return (s_sd_mounted ? 1 : 0) + (s_flash_mounted ? 1 : 0);
}

const char *Storage_Dir_At(int index)
{
    /* Index 0 ist der aktive Speicher: SD, wenn vorhanden, sonst Flash */
    if (s_sd_mounted) {
        if (index == 0) return REC_DIR_SD;
        if (index == 1 && s_flash_mounted) return REC_DIR_FLASH;
    } else if (s_flash_mounted && index == 0) {
        return REC_DIR_FLASH;
    }
    return REC_DIR_FLASH;   /* ungueltiger Index: harmlos, Aufrufer pruefen Storage_Dir_Count() */
}

uint64_t Storage_Free_Bytes(void)
{
    uint64_t total = 0, free_b = 0;
    if (!g_storage_mounted || esp_vfs_fat_info(Storage_Dir(), &total, &free_b) != ESP_OK) {
        return 0;
    }
    return free_b;
}

uint64_t Storage_Total_Bytes(void)
{
    uint64_t total = 0, free_b = 0;
    if (!g_storage_mounted || esp_vfs_fat_info(Storage_Dir(), &total, &free_b) != ESP_OK) {
        return 0;
    }
    return total;
}
