#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Akku ueber den Power-Chip AXP2101 (I2C). Der I2C-Bus muss schon laufen (esp_board_init). */
void BAT_Init(void);
float BAT_Get_Volts(void);          /* Akkuspannung in Volt, 0 wenn kein Akku/Chip */
bool BAT_Vbus_Present(void);        /* true, wenn USB/Ladegeraet anliegt */
bool BAT_Is_Charging(void);

#ifdef __cplusplus
}
#endif
