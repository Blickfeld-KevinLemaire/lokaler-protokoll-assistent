#pragma once
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_err.h"
#include "esp_log.h"
#include "lvgl.h"

#include "ST7789.h"
#include "CST816.h"

/* Teilpuffer: 1/20 des Bildschirms, zweifach, im internen DMA-RAM (der C6 hat keinen PSRAM) */
#define LVGL_BUF_LEN  (EXAMPLE_LCD_WIDTH * EXAMPLE_LCD_HEIGHT / 20)
#define EXAMPLE_LVGL_TICK_PERIOD_MS    2

extern lv_disp_draw_buf_t disp_buf;
extern lv_disp_drv_t disp_drv;
extern lv_disp_t *disp;

void LVGL_Init(void);   /* nach LCD_Init() und esp_board_init() aufrufen */
