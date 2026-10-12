#pragma once

/* Waveshare ESP32-C6-Touch-LCD-1.83 (Schaltplan Rev1.2) */

/* I2C-Bus: Touch (CST816D), ES7210, ES8311, AXP2101, PCF85063, QMI8658 */
#define BOARD_I2C_PORT        (0)
#define BOARD_I2C_SDA         (7)
#define BOARD_I2C_SCL         (8)

/* SPI2: Display (ST7789P) und SD-Karte teilen sich den Bus */
#define BOARD_SPI_HOST        (SPI2_HOST)
#define BOARD_SPI_SCLK        (1)
#define BOARD_SPI_MOSI        (2)
#define BOARD_SPI_MISO        (16)

#define BOARD_LCD_DC          (3)
#define BOARD_LCD_RST         (4)
#define BOARD_LCD_CS          (5)
#define BOARD_LCD_BL          (6)

#define BOARD_SD_CS           (17)

#define BOARD_TOUCH_INT       (11)
#define BOARD_TOUCH_RST       (-1)

/* I2S: ES7210 (Mikrofone) und ES8311 (Lautsprecher) */
#define BOARD_I2S_MCLK        (19)
#define BOARD_I2S_BCLK        (20)
#define BOARD_I2S_DIN         (21)
#define BOARD_I2S_WS          (22)
#define BOARD_I2S_DOUT        (23)
