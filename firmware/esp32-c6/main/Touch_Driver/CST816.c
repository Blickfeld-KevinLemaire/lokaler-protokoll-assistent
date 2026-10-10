#include "CST816.h"
#include "Board_Pins.h"
#include "ST7789.h"
#include "Audio_Board.h"

#include "esp_log.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_touch_cst816s.h"

static const char *TAG = "CST816";

esp_lcd_touch_handle_t tp = NULL;

void Touch_Init(void)
{
    esp_lcd_panel_io_handle_t tp_io_handle = NULL;

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = EXAMPLE_LCD_WIDTH,
        .y_max = EXAMPLE_LCD_HEIGHT,
        .rst_gpio_num = BOARD_TOUCH_RST,
        .int_gpio_num = BOARD_TOUCH_INT,
        .levels = {
            .reset = 0,
            .interrupt = 0,
        },
        .flags = {
            .swap_xy = 0,
            .mirror_x = 0,
            .mirror_y = 0,
        },
    };

    esp_lcd_panel_io_i2c_config_t tp_io_config = ESP_LCD_TOUCH_IO_I2C_CST816S_CONFIG();
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(esp_ret_i2c_handle(), &tp_io_config, &tp_io_handle));
    ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_cst816s(tp_io_handle, &tp_cfg, &tp));
    ESP_LOGI(TAG, "Touch bereit");
}
