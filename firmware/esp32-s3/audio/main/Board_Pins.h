#pragma once

/* Waveshare ESP32-S3-AUDIO-Board (Schaltplan V1.1, Beispielcode "factory_01" von Waveshare) */

/* I2C: ES7210 (Mikrofone), ES8311, TCA9555 (IO-Expander), PCF85063 (RTC) */
#define BOARD_I2C_PORT        (0)
#define BOARD_I2C_SDA         (11)
#define BOARD_I2C_SCL         (10)

/* I2S: ES7210 (Mikrofone) und ES8311 (Lautsprecher) */
#define BOARD_I2S_MCLK        (12)
#define BOARD_I2S_BCLK        (13)
#define BOARD_I2S_WS          (14)
#define BOARD_I2S_DIN         (15)     /* Mikrofone -> ESP32 */
#define BOARD_I2S_DOUT        (16)     /* ESP32 -> Lautsprecher */

/* SD-Karte (SDMMC, 1 Bit). DAT3 haengt am IO-Expander (EXIO3) und muss hoch sein. */
#define BOARD_SD_CLK          (40)
#define BOARD_SD_CMD          (42)
#define BOARD_SD_D0           (41)

/* 7 RGB-LEDs (WS2812) im Ring */
#define BOARD_LED_PIN         (38)
#define BOARD_LED_COUNT       (7)

/* Tasten: KEY1..KEY3 am IO-Expander TCA9555 (aktiv low), BOOT direkt am GPIO0 */
#define BOARD_KEY1_EXIO       (9)
#define BOARD_KEY2_EXIO       (10)
#define BOARD_KEY3_EXIO       (11)
#define BOARD_BOOT_GPIO       (0)

/* Weitere Expander-Pins (laut Waveshare-Beispiel) */
#define BOARD_EXIO_SD_D3      (3)      /* Ausgang, hoch lassen */
#define BOARD_EXIO_PA_ENABLE  (8)      /* Lautsprecher-Verstaerker; niedrig = aus */
