#include "Leds.h"
#include "Board_Pins.h"

#include <math.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"

static const char *TAG = "LEDS";

#define FRAME_MS     33
#define BRIGHTNESS   48          /* 0..255: die LEDs sind sonst blendend hell */

static led_strip_handle_t s_strip = NULL;

static volatile led_scene_t s_scene = LED_SCENE_BOOT;
static volatile uint8_t s_level = 0;
static volatile led_link_t s_link = LED_LINK_LOCAL;
static volatile bool s_uploading = false;
static volatile uint32_t s_pending = 0;
static volatile uint8_t s_hold = 0;
static volatile int64_t s_status_until_ms = 0;
static volatile uint8_t s_status_used = 0;
static volatile bool s_status_sd = false;
static volatile int64_t s_flash_until_ms = 0;
static volatile uint8_t s_flash_r, s_flash_g, s_flash_b;

void Leds_Set_Scene(led_scene_t scene) { s_scene = scene; }
void Leds_Set_Level(uint8_t percent) { s_level = percent > 100 ? 100 : percent; }
void Leds_Set_Link(led_link_t link) { s_link = link; }
void Leds_Set_Upload(bool active, uint32_t pending) { s_uploading = active; s_pending = pending; }
void Leds_Set_Hold(uint8_t percent) { s_hold = percent > 100 ? 100 : percent; }

void Leds_Show_Storage(uint8_t used_percent, bool is_sd)
{
    s_status_used = used_percent > 100 ? 100 : used_percent;
    s_status_sd = is_sd;
    s_status_until_ms = esp_timer_get_time() / 1000 + 3000;
}

void Leds_Flash(uint8_t r, uint8_t g, uint8_t b, uint32_t ms)
{
    s_flash_r = r; s_flash_g = g; s_flash_b = b;
    s_flash_until_ms = esp_timer_get_time() / 1000 + ms;
}

static void px(int i, int r, int g, int b)
{
    led_strip_set_pixel(s_strip, i,
                        (uint32_t)r * BRIGHTNESS / 255,
                        (uint32_t)g * BRIGHTNESS / 255,
                        (uint32_t)b * BRIGHTNESS / 255);
}

static void fill(int r, int g, int b)
{
    for (int i = 0; i < BOARD_LED_COUNT; i++) px(i, r, g, b);
}

static void link_color(int *r, int *g, int *b)
{
    switch (s_link) {
        case LED_LINK_TARGET: *r = 0;  *g = 255; *b = 40;  break;
        case LED_LINK_WIFI:   *r = 0;  *g = 170; *b = 190; break;
        default:              *r = 20; *g = 60;  *b = 255; break;
    }
}

static void render(int64_t t)
{
    led_strip_clear(s_strip);

    /* 1) Kurzes Aufblitzen als Tastenquittung hat Vorrang */
    if (t < s_flash_until_ms) {
        fill(s_flash_r, s_flash_g, s_flash_b);
        return;
    }

    /* 2) Taste wird gehalten: Ring fuellt sich weiss */
    if (s_hold > 0) {
        int lit = (s_hold * BOARD_LED_COUNT + 99) / 100;
        for (int i = 0; i < lit && i < BOARD_LED_COUNT; i++) px(i, 255, 255, 255);
        return;
    }

    /* 3) KEY3: Fuellstand des Speichers (gruen / orange / rot), erste LED blau = SD, tuerkis = Flash */
    if (t < s_status_until_ms) {
        int lit = (s_status_used * BOARD_LED_COUNT + 99) / 100;
        if (lit < 1 && s_status_used > 0) lit = 1;
        int r = 0, g = 255, b = 40;
        if (s_status_used >= 90) { r = 255; g = 20; b = 0; }
        else if (s_status_used >= 70) { r = 255; g = 120; b = 0; }
        for (int i = 0; i < lit && i < BOARD_LED_COUNT; i++) px(i, r, g, b);
        if (lit < BOARD_LED_COUNT) {
            /* Die naechste LED zeigt die Speicherart */
            if (s_status_sd) px(lit, 20, 60, 255); else px(lit, 0, 170, 190);
        }
        return;
    }

    switch (s_scene) {
        case LED_SCENE_BOOT: {
            int pos = (int)((t / 120) % BOARD_LED_COUNT);
            px(pos, 255, 255, 255);
            break;
        }
        case LED_SCENE_IDLE: {
            int r, g, b;
            link_color(&r, &g, &b);
            float breath = 0.25f + 0.2f * (1.0f + sinf((float)t / 600.0f)) * 0.5f * 2.0f;   /* 0,25 .. 0,65 */
            if (s_uploading) {
                /* Upload: gruener Punkt wandert */
                int pos = (int)((t / 90) % BOARD_LED_COUNT);
                for (int i = 0; i < BOARD_LED_COUNT; i++) px(i, r / 10, g / 10, b / 10);
                px(pos, 0, 255, 40);
            } else {
                for (int i = 0; i < BOARD_LED_COUNT; i++) {
                    px(i, (int)(r * breath * 0.35f), (int)(g * breath * 0.35f), (int)(b * breath * 0.35f));
                }
                if (s_pending > 0) px(3, 255, 120, 0);     /* offene Aufnahmen: orange Punkt oben */
            }
            break;
        }
        case LED_SCENE_RECORDING: {
            int lit = (s_level * BOARD_LED_COUNT + 50) / 100;
            if (lit < 1) lit = 1;
            for (int i = 0; i < BOARD_LED_COUNT; i++) {
                if (i < lit) px(i, 255, 0, 0); else px(i, 28, 0, 0);
            }
            break;
        }
        case LED_SCENE_PAUSED:
            if (((t / 500) % 2) == 0) fill(255, 130, 0);
            break;
        case LED_SCENE_SAVING:
            fill(255, 255, 255);
            break;
        case LED_SCENE_DONE:
            fill(0, 255, 40);
            break;
        case LED_SCENE_FULL:
            if (((t / 400) % 2) == 0) fill(255, 120, 0); else fill(255, 0, 0);
            break;
        case LED_SCENE_ERROR:
            if (((t / 125) % 2) == 0) fill(255, 0, 0);
            break;
        case LED_SCENE_MIC_ERROR:
            if (((t / 300) % 2) == 0) fill(200, 0, 255);
            break;
    }
}

static void leds_task(void *arg)
{
    while (1) {
        render(esp_timer_get_time() / 1000);
        led_strip_refresh(s_strip);
        vTaskDelay(pdMS_TO_TICKS(FRAME_MS));
    }
}

void Leds_Init(void)
{
    led_strip_config_t strip_config = {
        .strip_gpio_num = BOARD_LED_PIN,
        .max_leds = BOARD_LED_COUNT,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_RGB,
        .flags = {.invert_out = false},
    };
    led_strip_rmt_config_t rmt_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 0,
        .flags = {.with_dma = 0},
    };
    if (led_strip_new_rmt_device(&strip_config, &rmt_config, &s_strip) != ESP_OK) {
        ESP_LOGE(TAG, "LED-Ring nicht startbar");
        return;
    }
    led_strip_clear(s_strip);
    xTaskCreate(leds_task, "leds", 3072, NULL, 3, NULL);
    ESP_LOGI(TAG, "LED-Ring bereit (%d LEDs)", BOARD_LED_COUNT);
}
