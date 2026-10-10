#include "ST7789.h"
#include "Board_Pins.h"

#include "esp_log.h"
#include "esp_check.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "esp_lcd_panel_st7789.h"

#define LCD_PIXEL_CLK_HZ     (40 * 1000 * 1000)

#define LEDC_TIMER           LEDC_TIMER_0
#define LEDC_MODE            LEDC_LOW_SPEED_MODE
#define LEDC_CHANNEL         LEDC_CHANNEL_0
#define LEDC_RESOLUTION      LEDC_TIMER_13_BIT
#define LEDC_MAX_DUTY        ((1 << LEDC_RESOLUTION) - 1)

static const char *TAG = "ST7789";

esp_lcd_panel_handle_t panel_handle = NULL;
esp_lcd_panel_io_handle_t panel_io_handle = NULL;

static void backlight_init(void)
{
    ledc_timer_config_t timer = {
        .duty_resolution = LEDC_RESOLUTION,
        .freq_hz = 5000,
        .speed_mode = LEDC_MODE,
        .timer_num = LEDC_TIMER,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&timer);

    ledc_channel_config_t channel = {
        .channel = LEDC_CHANNEL,
        .duty = 0,
        .gpio_num = BOARD_LCD_BL,
        .speed_mode = LEDC_MODE,
        .timer_sel = LEDC_TIMER,
    };
    ledc_channel_config(&channel);
}

void Set_Backlight(uint8_t Light)
{
    if (Light > Backlight_MAX) Light = Backlight_MAX;
    uint32_t duty = LEDC_MAX_DUTY - (81 * (Backlight_MAX - Light));
    if (Light == 0) duty = 0;
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, duty);
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

void LCD_Init(void)
{
    backlight_init();

    /* Nur Senden an das Display; dieses Board hat keine SD-Karte */
    const spi_bus_config_t buscfg = {
        .sclk_io_num = BOARD_SPI_SCLK,
        .mosi_io_num = BOARD_SPI_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_SPI_MAX_TRANSFER,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(BOARD_SPI_HOST, &buscfg, SPI_DMA_CH_AUTO));

    const esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = BOARD_LCD_DC,
        .cs_gpio_num = BOARD_LCD_CS,
        .pclk_hz = LCD_PIXEL_CLK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)BOARD_SPI_HOST, &io_config, &panel_io_handle));

    const esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = BOARD_LCD_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(panel_io_handle, &panel_config, &panel_handle));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel_handle, true));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_handle, true));

    Set_Backlight(Backlight_MAX);
    ESP_LOGI(TAG, "Display %dx%d bereit", EXAMPLE_LCD_WIDTH, EXAMPLE_LCD_HEIGHT);
}
