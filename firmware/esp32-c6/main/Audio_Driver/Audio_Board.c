/* Audio fuer Waveshare ESP32-C6-Touch-LCD-1.83.
 * Gleiche Aufnahmekette wie beim S3 (ES7210, 16 kHz, I2S-Stereo mit 32-Bit-Slots,
 * vier Rohkanaele a 16 Bit pro Frame); nur Pins und I2S-Port sind anders. */
#include <stdlib.h>
#include "esp_log.h"
#include "esp_check.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"

#include "Audio_Board.h"
#include "Board_Pins.h"

#define ADC_I2S_CHANNEL   4
#define RECORD_VOLUME     (37.5)
#define PLAYER_VOLUME     (50)
#define I2S_SAMPLE_RATE   16000
/* I2S-DMA-Puffer: 12 x 240 Frames = ca. 180 ms, damit die Aufnahme kurze SD-/Display-Pausen
 * auf dem gemeinsamen SPI-Bus uebersteht (der C6 hat nur einen Kern). */
#define I2S_DMA_DESC_NUM  12
#define I2S_DMA_FRAME_NUM 240

static const char *TAG = "board";

static i2c_master_bus_handle_t i2c_handle = NULL;
static i2s_chan_handle_t tx_handle = NULL;
static i2s_chan_handle_t rx_handle = NULL;

static audio_codec_data_if_t *record_data_if = NULL;
static audio_codec_ctrl_if_t *record_ctrl_if = NULL;
static audio_codec_if_t *record_codec_if = NULL;
static esp_codec_dev_handle_t record_dev = NULL;

static audio_codec_data_if_t *play_data_if = NULL;
static audio_codec_ctrl_if_t *play_ctrl_if = NULL;
static audio_codec_gpio_if_t *play_gpio_if = NULL;
static audio_codec_if_t *play_codec_if = NULL;
static esp_codec_dev_handle_t play_dev = NULL;

i2c_master_bus_handle_t esp_ret_i2c_handle(void)
{
    return i2c_handle;
}

static esp_err_t i2c_master_init(void)
{
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = BOARD_I2C_PORT,
        .sda_io_num = BOARD_I2C_SDA,
        .scl_io_num = BOARD_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };

    esp_err_t ret = i2c_new_master_bus(&bus_config, &i2c_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to initialize I2C bus: %s", esp_err_to_name(ret));
    }
    return ret;
}

static esp_err_t i2s_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = I2S_DMA_DESC_NUM;
    chan_cfg.dma_frame_num = I2S_DMA_FRAME_NUM;

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(I2S_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = BOARD_I2S_MCLK,
            .bclk = BOARD_I2S_BCLK,
            .ws   = BOARD_I2S_WS,
            .dout = BOARD_I2S_DOUT,
            .din  = BOARD_I2S_DIN,
        },
    };

    /* Nur der Aufnahme-Kanal: Der Lautsprecher wird nicht genutzt, und ein Sende-Kanal
     * kostet allein 23 KB DMA-Puffer, die der C6 (ohne PSRAM) fuer den Upload braucht. */
    esp_err_t ret = i2s_new_channel(&chan_cfg, NULL, &rx_handle);
    ret |= i2s_channel_init_std_mode(rx_handle, &std_cfg);
    ret |= i2s_channel_enable(rx_handle);
    return ret;
}

static esp_err_t codec_adc_init(void)
{
    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = I2S_NUM_0,
        .rx_handle = rx_handle,
        .tx_handle = NULL,
    };
    record_data_if = audio_codec_new_i2s_data(&i2s_cfg);

    audio_codec_i2c_cfg_t i2c_cfg = {.addr = ES7210_CODEC_DEFAULT_ADDR, .bus_handle = i2c_handle};
    record_ctrl_if = audio_codec_new_i2c_ctrl(&i2c_cfg);

    es7210_codec_cfg_t es7210_cfg = {
        .ctrl_if = record_ctrl_if,
        .mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2 | ES7210_SEL_MIC3 | ES7210_SEL_MIC4,
    };
    record_codec_if = es7210_codec_new(&es7210_cfg);

    esp_codec_dev_cfg_t dev_cfg = {
        .codec_if = record_codec_if,
        .data_if = record_data_if,
        .dev_type = ESP_CODEC_DEV_TYPE_IN,
    };
    record_dev = esp_codec_dev_new(&dev_cfg);

    esp_codec_dev_sample_info_t fs = {
        .sample_rate = I2S_SAMPLE_RATE,
        .channel = 2,
        .bits_per_sample = 32,
    };
    esp_codec_dev_open(record_dev, &fs);
    for (int ch = 0; ch < 4; ch++) {
        esp_codec_dev_set_in_channel_gain(record_dev, ESP_CODEC_DEV_MAKE_CHANNEL_MASK(ch), RECORD_VOLUME);
    }
    return ESP_OK;
}

__attribute__((unused)) static esp_err_t codec_dac_init(int sample_rate, int channel_format, int bits_per_chan)
{
    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = I2S_NUM_0,
        .rx_handle = NULL,
        .tx_handle = tx_handle,
    };
    play_data_if = audio_codec_new_i2s_data(&i2s_cfg);

    audio_codec_i2c_cfg_t i2c_cfg = {.addr = ES8311_CODEC_DEFAULT_ADDR, .bus_handle = i2c_handle};
    play_ctrl_if = audio_codec_new_i2c_ctrl(&i2c_cfg);
    play_gpio_if = audio_codec_new_gpio();

    es8311_codec_cfg_t es8311_cfg = {
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .ctrl_if = play_ctrl_if,
        .gpio_if = play_gpio_if,
        .pa_pin = -1,
        .use_mclk = false,
    };
    play_codec_if = es8311_codec_new(&es8311_cfg);

    esp_codec_dev_cfg_t dev_cfg = {
        .codec_if = play_codec_if,
        .data_if = play_data_if,
        .dev_type = ESP_CODEC_DEV_TYPE_OUT,
    };
    play_dev = esp_codec_dev_new(&dev_cfg);

    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = bits_per_chan,
        .sample_rate = sample_rate,
        .channel = channel_format,
    };
    esp_codec_dev_set_out_vol(play_dev, PLAYER_VOLUME);
    esp_codec_dev_open(play_dev, &fs);
    return ESP_OK;
}

esp_err_t esp_get_feed_data(bool is_get_raw_channel, int16_t *buffer, int buffer_len)
{
    esp_err_t ret = esp_codec_dev_read(record_dev, (void *)buffer, buffer_len);

    if (!is_get_raw_channel) {
        int frames = buffer_len / (sizeof(int16_t) * ADC_I2S_CHANNEL);
        for (int i = 0; i < frames; i++) {
            int16_t ref = buffer[4 * i + 0];
            buffer[3 * i + 0] = buffer[4 * i + 1];
            buffer[3 * i + 1] = buffer[4 * i + 3];
            buffer[3 * i + 2] = ref;
        }
    }
    return ret;
}

esp_err_t esp_board_init(uint32_t sample_rate, int channel_format, int bits_per_chan)
{
    (void)sample_rate;
    (void)channel_format;
    (void)bits_per_chan;

    ESP_RETURN_ON_ERROR(i2c_master_init(), TAG, "I2C init failed");

    /* Aufnahme und Wiedergabe teilen sich denselben I2S-Port (wie beim S3) */
    ESP_RETURN_ON_ERROR(i2s_init(), TAG, "I2S init failed");
    codec_adc_init();
    return ESP_OK;
}
