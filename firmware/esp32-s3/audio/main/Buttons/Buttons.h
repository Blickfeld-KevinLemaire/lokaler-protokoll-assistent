#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "driver/i2c_master.h"

/* Die vier nutzbaren Tasten. RESET startet nur neu und ist nicht abfragbar. */
typedef enum {
    KEY_1 = 0,      /* KEY1 (Expander) */
    KEY_2,          /* KEY2 (Expander) */
    KEY_3,          /* KEY3 (Expander) */
    KEY_BOOT,       /* BOOT (GPIO0) */
    KEY_COUNT
} key_id_t;

typedef enum {
    KEY_EVENT_SHORT,    /* losgelassen vor Ablauf der Lang-Schwelle */
    KEY_EVENT_LONG      /* so lange gehalten, wie BUTTONS_LONG_MS (einmalig beim Erreichen) */
} key_event_t;

#define BUTTONS_LONG_MS   1000

typedef void (*button_cb_t)(key_id_t key, key_event_t event);

/* IO-Expander einrichten (SD-DAT3 hoch, Verstaerker aus) und die Tasten abfragen. Vor Storage_Init() aufrufen. */
esp_err_t Buttons_Init(i2c_master_bus_handle_t bus, button_cb_t cb);

/* Wie lange ist die Taste gerade schon gedrueckt (ms), 0 wenn nicht gedrueckt. Fuer eine Fortschrittsanzeige. */
uint32_t Buttons_Held_Ms(key_id_t key);
