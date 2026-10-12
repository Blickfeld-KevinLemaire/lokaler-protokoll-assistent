#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "driver/i2c_master.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Gleiche Schnittstelle wie esp_board_init.h beim S3-Projekt */
esp_err_t esp_board_init(uint32_t sample_rate, int channel_format, int bits_per_chan);
esp_err_t esp_get_feed_data(bool is_get_raw_channel, int16_t *buffer, int buffer_len);

/* I2C-Bus des Boards (fuer Touch und Akku-Chip) */
i2c_master_bus_handle_t esp_ret_i2c_handle(void);

#ifdef __cplusplus
}
#endif
