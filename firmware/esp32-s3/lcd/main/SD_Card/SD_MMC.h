
#pragma once

#include <string.h>
#include <sys/unistd.h>
#include <sys/stat.h>
#include "esp_vfs_fat.h"
#include "dirent.h"
#include "sdmmc_cmd.h"
#include "driver/sdmmc_host.h"
#include "esp_log.h" 
#include <errno.h>
#include <stdbool.h>

#include "esp_flash.h"    

#define CONFIG_EXAMPLE_PIN_CLK  14
#define CONFIG_EXAMPLE_PIN_CMD  17
#define CONFIG_EXAMPLE_PIN_D0   16
#define CONFIG_EXAMPLE_PIN_D1   -1
#define CONFIG_EXAMPLE_PIN_D2   -1
#define CONFIG_EXAMPLE_PIN_D3   -1  

#define CONFIG_SD_Card_D3       21  


esp_err_t SD_Card_CS_EN(void);
esp_err_t SD_Card_CS_Dis(void);

esp_err_t s_example_write_file(const char *path, char *data);
esp_err_t s_example_read_file(const char *path);

extern uint32_t SDCard_Size;
extern uint32_t Flash_Size;
extern sdmmc_card_t *g_sd_card;
extern bool g_sd_mounted;
void SD_Init(void);
uint64_t SD_Free_Bytes(void);   /* freier Platz auf der Karte in Bytes (0 bei Fehler) */
void Flash_Searching(void);
FILE* Open_File(const char *file_path);
uint16_t Folder_retrieval(const char* directory, const char* fileExtension, char File_Name[][100],uint16_t maxFiles);