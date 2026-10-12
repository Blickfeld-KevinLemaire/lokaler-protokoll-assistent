#pragma once

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "esp_wifi.h"
#include "nvs_flash.h" 
#include "esp_log.h"

#include <stdio.h>
#include <string.h>  // For memcpy
#include "esp_system.h"
#include "vermerk_upload.h"



extern volatile bool WIFI_CONNECTED;
extern volatile bool SERVER_REACHABLE;
extern volatile bool PC_REACHABLE;

void Wireless_Init(void);
void WIFI_Init(void *arg);
vermerk_ergebnis_t VERMERK_Upload_File(const char *path, const char *filename, vermerk_abbrechen_t abbrechen);
void VERMERK_Wifi_Fast_Mode(bool on);
