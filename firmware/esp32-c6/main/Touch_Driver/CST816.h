#pragma once

#include "esp_lcd_touch.h"

extern esp_lcd_touch_handle_t tp;

void Touch_Init(void);   /* nach esp_board_init() aufrufen (nutzt dessen I2C-Bus) */
