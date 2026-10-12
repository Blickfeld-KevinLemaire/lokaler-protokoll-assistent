#pragma once

#include <stdint.h>
#include "esp_err.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"

#define EXAMPLE_LCD_WIDTH        (240)
#define EXAMPLE_LCD_HEIGHT       (284)

#define Backlight_MAX            100

/* Maximale SPI-Uebertragung am Display (Bytes) */
#define LCD_SPI_MAX_TRANSFER     (16 * 1024)

extern esp_lcd_panel_handle_t panel_handle;
extern esp_lcd_panel_io_handle_t panel_io_handle;

void LCD_Init(void);                  /* SPI-Bus, Panel und Hintergrundbeleuchtung starten */
void Set_Backlight(uint8_t Light);    /* 0..100 */
