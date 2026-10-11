#include "Buttons.h"
#include "Board_Pins.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_io_expander.h"
#include "esp_io_expander_tca95xx_16bit.h"

static const char *TAG = "KEYS";

#define EXIO_BIT(n)   (1u << (n))
#define POLL_MS       20
#define DEBOUNCE_POLLS 2          /* 2 x 20 ms stabil, bevor ein Wechsel gilt */

static esp_io_expander_handle_t s_exio = NULL;
static button_cb_t s_cb = NULL;

typedef struct {
    bool pressed;                 /* entprellter Zustand */
    bool raw_last;
    uint8_t stable_polls;
    int64_t press_start_ms;
    bool long_fired;
} key_state_t;

static key_state_t s_keys[KEY_COUNT];

uint32_t Buttons_Held_Ms(key_id_t key)
{
    if (key >= KEY_COUNT || !s_keys[key].pressed) {
        return 0;
    }
    return (uint32_t)(esp_timer_get_time() / 1000 - s_keys[key].press_start_ms);
}

static void buttons_task(void *arg)
{
    const uint32_t key_mask = EXIO_BIT(BOARD_KEY1_EXIO) | EXIO_BIT(BOARD_KEY2_EXIO) | EXIO_BIT(BOARD_KEY3_EXIO);

    /* Diagnose: jede Aenderung an den Expander-Eingaengen (Pin 2 und die drei Tasten) sofort ins Log schreiben,
     * damit sich die Tastenzuordnung am echten Board ueberpruefen laesst. */
    const uint32_t watch_mask = EXIO_BIT(2) | key_mask;
    uint32_t last_watch = 0xFFFFFFFF;
    int read_errors = 0;

    while (1) {
        uint32_t level = 0;
        bool exio_ok = (esp_io_expander_get_level(s_exio, 0xFFFF, &level) == ESP_OK);
        if (!exio_ok) {
            if (++read_errors == 1 || read_errors % 500 == 0) {
                ESP_LOGW(TAG, "Expander nicht lesbar (%d Fehler)", read_errors);
            }
        } else if ((level & watch_mask) != last_watch) {
            last_watch = level & watch_mask;
            ESP_LOGI(TAG, "Expander-Eingaenge: EXIO2=%d KEY1(EXIO9)=%d KEY2(EXIO10)=%d KEY3(EXIO11)=%d  (0 = gedrueckt)",
                     (int)((level >> 2) & 1), (int)((level >> BOARD_KEY1_EXIO) & 1),
                     (int)((level >> BOARD_KEY2_EXIO) & 1), (int)((level >> BOARD_KEY3_EXIO) & 1));
        }

        /* Tasten sind aktiv low */
        bool raw[KEY_COUNT];
        raw[KEY_1] = exio_ok && !(level & EXIO_BIT(BOARD_KEY1_EXIO));
        raw[KEY_2] = exio_ok && !(level & EXIO_BIT(BOARD_KEY2_EXIO));
        raw[KEY_3] = exio_ok && !(level & EXIO_BIT(BOARD_KEY3_EXIO));
        raw[KEY_BOOT] = (gpio_get_level(BOARD_BOOT_GPIO) == 0);

        int64_t now = esp_timer_get_time() / 1000;
        for (int k = 0; k < KEY_COUNT; k++) {
            key_state_t *ks = &s_keys[k];

            if (raw[k] == ks->raw_last) {
                if (ks->stable_polls < 255) ks->stable_polls++;
            } else {
                ks->raw_last = raw[k];
                ks->stable_polls = 0;
            }

            if (ks->stable_polls >= DEBOUNCE_POLLS && raw[k] != ks->pressed) {
                ks->pressed = raw[k];
                if (ks->pressed) {
                    ks->press_start_ms = now;
                    ks->long_fired = false;
                } else if (!ks->long_fired && s_cb) {
                    s_cb((key_id_t)k, KEY_EVENT_SHORT);
                }
            }

            if (ks->pressed && !ks->long_fired && (now - ks->press_start_ms) >= BUTTONS_LONG_MS) {
                ks->long_fired = true;
                if (s_cb) s_cb((key_id_t)k, KEY_EVENT_LONG);
            }
        }

        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

esp_err_t Buttons_Init(i2c_master_bus_handle_t bus, button_cb_t cb)
{
    s_cb = cb;

    esp_err_t ret = esp_io_expander_new_i2c_tca95xx_16bit(bus, ESP_IO_EXPANDER_I2C_TCA9555_ADDRESS_000, &s_exio);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "IO-Expander TCA9555 nicht gefunden: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Wie im Waveshare-Beispiel: Pins 0,1,5,6,8 sind Ausgaenge, 2 und 9..11 Eingaenge. Zusaetzlich ist
     * Pin 3 (SD-DAT3) ein Ausgang und bleibt hoch, damit die Karte im SD-Modus (nicht SPI-Modus) startet. */
    esp_io_expander_set_dir(s_exio,
        EXIO_BIT(0) | EXIO_BIT(1) | EXIO_BIT(BOARD_EXIO_SD_D3) | EXIO_BIT(5) | EXIO_BIT(6) | EXIO_BIT(BOARD_EXIO_PA_ENABLE),
        IO_EXPANDER_OUTPUT);
    esp_io_expander_set_dir(s_exio,
        EXIO_BIT(2) | EXIO_BIT(BOARD_KEY1_EXIO) | EXIO_BIT(BOARD_KEY2_EXIO) | EXIO_BIT(BOARD_KEY3_EXIO),
        IO_EXPANDER_INPUT);
    esp_io_expander_set_level(s_exio, EXIO_BIT(BOARD_EXIO_SD_D3), 1);
    esp_io_expander_set_level(s_exio, EXIO_BIT(BOARD_EXIO_PA_ENABLE), 0);   /* Lautsprecher-Verstaerker aus */

    gpio_config_t boot_cfg = {
        .pin_bit_mask = 1ULL << BOARD_BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&boot_cfg);

    xTaskCreate(buttons_task, "keys", 3072, NULL, 4, NULL);
    ESP_LOGI(TAG, "Tasten bereit: KEY1..KEY3 (Expander) und BOOT");
    return ESP_OK;
}
