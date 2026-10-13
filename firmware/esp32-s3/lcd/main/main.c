#include "ST77916.h"
#include "TCA9554PWR.h"
#include "LVGL_Driver.h"
#include "esp_board_init.h"
#include "vermerk_logo.h"
#include "SD_MMC.h"
#include "BAT_Driver.h"
#include "Wireless.h"
#include "vermerk_konfig.h"
#include "vermerk_protokoll.h"
#include "vermerk_konsole.h"
#include "vermerk_live.h"
#include "Rec_Codec.h"
#include "Gain_Control.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_partition.h"
#include "nvs.h"
#include "driver/usb_serial_jtag.h"
#include "esp_timer.h"

#include <stdint.h>
#include <string.h>
#include <strings.h>
#include <stdio.h>
#include <math.h>
#include <dirent.h>
#include <unistd.h>

#define AUDIO_RAW_CHANNELS   4
#define AUDIO_FRAMES         256

#define RECORD_SAMPLE_RATE   REC_SAMPLE_RATE   /* Aufnahme: Mono, 16 kHz, Opus (siehe Rec_Codec.h) */

#define UPLOAD_IDS_PER_PASS  32     /* Aufnahmen je Upload-Durchgang; ab welcher Nummer: VERMERK_UPLOAD_ERSTE_NUMMER */
#define WAVE_BARS            29
#define STORAGE_MIN_FREE_START    (256 * 1024)   /* darunter keine neue Aufnahme */
#define STORAGE_MIN_FREE_RUNNING  (64 * 1024)    /* darunter wird die laufende Aufnahme beendet */
#define AUDIO_TASK_STACK     28672   /* der Opus-Encoder rechnet auf dem Stack dieser Task */
#define Storage_Free_Bytes   SD_Free_Bytes

typedef enum {
    REC_IDLE = 0,
    REC_REQUESTED,
    REC_RECORDING,
    REC_PAUSED,
    REC_STOP_REQUESTED,
    REC_SAVING,
    REC_DONE,
    REC_ERROR
} rec_state_t;

static volatile uint16_t mic1_peak = 0;
static volatile uint16_t mic2_peak = 0;
static volatile TickType_t audio_first_ok_tick = 0;
static volatile TickType_t audio_last_ok_tick = 0;
static volatile TickType_t mic1_last_change_tick = 0;
static volatile TickType_t mic2_last_change_tick = 0;
static volatile TickType_t mic1_last_signal_tick = 0;
static volatile TickType_t mic2_last_signal_tick = 0;
static volatile uint32_t rec_percent = 0;
static volatile uint32_t rec_elapsed_seconds = 0;
static volatile rec_state_t rec_state = REC_IDLE;
static volatile uint16_t wave_peak = 0;          /* Max. Pegel seit letzter Abholung durch die UI */
static volatile uint32_t pending_uploads = 0;    /* Aufnahmen auf SD, die noch hochgeladen werden */
static volatile bool upload_active = false;
/* Die zuletzt aufgenommene Aufnahme (Nummer): Sie wird zuerst hochgeladen, und nur ihr Verarbeitungsstand wird
 * angezeigt. 0 = keine. Gesetzt, wenn eine Aufnahme beginnt; zurueckgesetzt, wenn sie angekommen ist. */
static volatile uint32_t upload_vorrang_id = 0;

/* Verarbeitung der zuletzt hochgeladenen Aufnahme bei der Software (GET .../status). Der Upload-Manager
 * fragt ab, die Anzeige liest nur. "Sichtbar", sobald die Software einen Zustand kennt. */
#define VERARBEITUNG_ANZEIGE_MS   (10u * 60u * 1000u)   /* Fehlermeldung so lange stehen lassen; "fertig" bleibt bis zur naechsten Aufnahme */
#define FERTIG_VOLLBILD_MS        4000u                  /* Haekchen ueber den ganzen Bildschirm */
static volatile vermerk_verarbeitung_t verarbeitung_zustand = VERMERK_VERARB_UNBEKANNT;
static volatile int verarbeitung_prozent = -1;
static volatile bool verarbeitung_sichtbar = false;
static volatile uint32_t verarbeitung_ende_ms = 0;      /* seit wann das Ergebnis feststeht (esp_timer, ms) */
static volatile bool storage_full_stop = false;   /* Aufnahme wegen vollem Speicher beendet */

static uint8_t wave_levels[WAVE_BARS];
static lv_color_t wave_color;

static lv_obj_t *waveform;
static lv_obj_t *pause_button;
static lv_obj_t *pause_button_label;
static lv_obj_t *pending_label;
static lv_obj_t *status_label;
static lv_obj_t *mic_status_label;
static lv_obj_t *record_indicator;
static lv_obj_t *record_button;
static lv_obj_t *record_button_label;
static lv_obj_t *battery_label;
static lv_obj_t *battery_charge_icon;
static lv_obj_t *connection_label;
static lv_obj_t *fertig_vollbild;                /* "Transkription erfolgreich" ueber den ganzen Bildschirm */
static uint32_t fertig_vollbild_start = 0;       /* lv_tick_get() beim Einblenden */
static bool fertig_vollbild_gezeigt = false;     /* fuer diese Verarbeitung schon gezeigt */

/* Pegel 0..100 fuer die Wellenform. Wurzel-Kennlinie, damit leise Sprache
 * noch sichtbar ist und laute Stellen nicht sofort anschlagen. */
static uint8_t peak_to_wave_level(uint16_t peak)
{
    if (peak < 30) return 0;
    float lin = (float)peak / 2000.0f;
    if (lin > 1.0f) lin = 1.0f;
    return (uint8_t)(sqrtf(lin) * 100.0f);
}

static int battery_voltage_to_percent(float v)
{
    if (v >= 4.05f) return 100;
    if (v >= 4.00f) return 90 + (int)((v - 4.00f) * 200.0f);
    if (v >= 3.90f) return 75 + (int)((v - 3.90f) * 150.0f);
    if (v >= 3.80f) return 55 + (int)((v - 3.80f) * 200.0f);
    if (v >= 3.70f) return 30 + (int)((v - 3.70f) * 250.0f);
    if (v >= 3.60f) return 15 + (int)((v - 3.60f) * 150.0f);
    if (v >= 3.50f) return 7 + (int)((v - 3.50f) * 80.0f);
    if (v >= 3.40f) return 3 + (int)((v - 3.40f) * 40.0f);
    if (v >= 3.30f) return (int)((v - 3.30f) * 30.0f);
    return 0;
}

static uint32_t next_record_id = 1;

/* Reihenfolge = Rang (fuer das Entprellen beim Auf-/Abstieg) */
typedef enum {
    TRANSFER_MODE_LOCAL = 0,
    TRANSFER_MODE_LINK,     /* WLAN oder USB am PC, aber kein Empfaenger -> kein Upload */
    TRANSFER_MODE_PC,       /* Empfaenger auf dem PC erreichbar */
    TRANSFER_MODE_SERVER    /* Server erreichbar (Vorrang vor PC) */
} transfer_mode_t;

static volatile transfer_mode_t transfer_mode = TRANSFER_MODE_LOCAL;

/* Modus automatisch aus der Verbindungslage ableiten.
 * usb_serial_jtag_is_connected() ist nur bei einem echten USB-Host (PC) true,
 * nicht bei Ladegeraet oder Powerbank. */
static transfer_mode_t detect_transfer_mode(void)
{
    if (SERVER_REACHABLE) {
        return TRANSFER_MODE_SERVER;
    }
    if (PC_REACHABLE) {
        return TRANSFER_MODE_PC;
    }
    if (WIFI_CONNECTED || usb_serial_jtag_is_connected()) {
        return TRANSFER_MODE_LINK;
    }
    return TRANSFER_MODE_LOCAL;
}


/* Gibt es schon eine Aufnahme mit dieser Nummer (neu als .opus oder alt als .wav)? */
static bool recording_exists(uint32_t id)
{
    static const char *const exts[] = {REC_EXT, REC_EXT_LEGACY};
    char path[64];

    for (int e = 0; e < 2; e++) {
        snprintf(path, sizeof(path), REC_DIR "/H5_%03u.%s", (unsigned)id, exts[e]);
        FILE *f = fopen(path, "rb");
        if (f != NULL) {
            fclose(f);
            return true;
        }
    }
    return false;
}

/* Naechste freie Nummer nach der hoechsten Aufnahme auf der SD (Verzeichnisliste, ohne Obergrenze) */
static uint32_t find_next_sd_record_id(void)
{
    uint32_t highest = 0;

    DIR *dir = opendir(REC_DIR);
    if (dir != NULL) {
        struct dirent *entry;
        while ((entry = readdir(dir)) != NULL) {
            uint32_t id = 0;
            if ((vermerk_aufnahme_nummer(entry->d_name, REC_EXT, &id) ||
                 vermerk_aufnahme_nummer(entry->d_name, REC_EXT_LEGACY, &id)) && id > highest) {
                highest = id;
            }
        }
        closedir(dir);
    }

    return highest + 1;
}

static esp_err_t save_next_record_id(uint32_t id)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open("vermerk", NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;

    err = nvs_set_u32(handle, "next_rec_id", id);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    return err;
}

static void recording_counter_init(void)
{
    uint32_t sd_next = find_next_sd_record_id();
    uint32_t stored_next = 1;
    nvs_handle_t handle;

    if (nvs_open("vermerk", NVS_READONLY, &handle) == ESP_OK) {
        if (nvs_get_u32(handle, "next_rec_id", &stored_next) != ESP_OK) {
            stored_next = 1;
        }
        nvs_close(handle);
    }

    next_record_id = (stored_next > sd_next) ? stored_next : sd_next;
    save_next_record_id(next_record_id);
    printf("VERMERK naechste Aufnahme-ID: %u\n", (unsigned)next_record_id);
}

static FILE *open_new_recording(char *path, size_t path_len)
{
    for (uint32_t attempt = 0; attempt < 1000; attempt++) {
        uint32_t id = next_record_id;

        if (recording_exists(id)) {
            next_record_id++;
            continue;
        }
        snprintf(path, path_len, REC_DIR "/H5_%03u." REC_EXT, (unsigned)id);

        FILE *f = fopen(path, "wb");
        if (f == NULL) {
            return NULL;
        }

        /* Vor den Kopfseiten: Das Senden waehrend der Aufnahme braucht die Datei ab Byte 0. Gelingt es nicht
         * (kein PSRAM ...), wird die Aufnahme nach dem Ende wie bisher hochgeladen. */
        char live_name[32];
        snprintf(live_name, sizeof(live_name), "H5_%03u." REC_EXT, (unsigned)id);
        vermerk_live_beginnen(live_name);

        if (!rec_enc_begin(f)) {
            vermerk_live_beenden();
            fclose(f);
            remove(path);
            return NULL;
        }

        esp_err_t err = save_next_record_id(id + 1);
        if (err != ESP_OK) {
            vermerk_live_beenden();
            fclose(f);
            remove(path);
            return NULL;
        }

        next_record_id = id + 1;
        upload_vorrang_id = id;   /* nach dem Stopp zuerst hochladen, ihr Ergebnis anzeigen */
        printf("VERMERK Aufnahme-ID reserviert: %u\n", (unsigned)id);
        return f;
    }

    return NULL;
}

static esp_err_t finalize_recording(FILE *f)
{
    if (f == NULL) {
        return ESP_FAIL;
    }

    /* Restpuffer des Encoders in die Datei schreiben, dann sauber schliessen */
    bool ok = rec_enc_end();
    vermerk_live_beenden();   /* die letzte Seite ist raus; was fehlt, holt der normale Upload nach */
    fflush(f);
    fsync(fileno(f));
    ok = (fclose(f) == 0) && ok;
    return ok ? ESP_OK : ESP_FAIL;
}

static void audio_task(void *arg)
{
    static int16_t raw[AUDIO_FRAMES * AUDIO_RAW_CHANNELS];
    static int16_t mono[AUDIO_FRAMES];

    FILE *record_file = NULL;
    uint64_t recorded_frames = 0;
    char record_path[64];
    bool paused_flushed = false;

    while (1) {
        esp_err_t err = esp_get_feed_data(true, raw, sizeof(raw));

        if (err != ESP_OK) {
            mic1_peak = 0;
            mic2_peak = 0;
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        uint16_t p1 = 0;
        uint16_t p2 = 0;

        for (int i = 0; i < AUDIO_FRAMES; i++) {
            int32_t v1 = raw[i * 4 + 1];
            int32_t v2 = raw[i * 4 + 3];

            if (v1 < 0) v1 = -v1;
            if (v2 < 0) v2 = -v2;

            if ((uint32_t)v1 > p1) p1 = (uint16_t)v1;
            if ((uint32_t)v2 > p2) p2 = (uint16_t)v2;

            /* Beide Mikrofone zu Mono mischen, so wie es die Transkription ohnehin macht */
            mono[i] = (int16_t)(((int32_t)raw[i * 4 + 1] + (int32_t)raw[i * 4 + 3]) / 2);
        }
        /* Leise Sprache anheben, laute Stellen begrenzen (Pegelanzeige und Mikrofonpruefung nutzen die Rohwerte oben) */
        agc_process(mono, AUDIO_FRAMES);

        mic1_peak = p1;
        mic2_peak = p2;
        uint16_t p_max = (p1 > p2) ? p1 : p2;
        if (p_max > wave_peak) {
            wave_peak = p_max;
        }
        TickType_t health_now = xTaskGetTickCount();
        audio_last_ok_tick = health_now;
        if (audio_first_ok_tick == 0) {
            audio_first_ok_tick = health_now;
        }

        static uint16_t last_health_p1 = 0;
        static uint16_t last_health_p2 = 0;

        uint16_t diff1 = (p1 > last_health_p1) ? (p1 - last_health_p1) : (last_health_p1 - p1);
        uint16_t diff2 = (p2 > last_health_p2) ? (p2 - last_health_p2) : (last_health_p2 - p2);

        if (diff1 >= 2) {
            mic1_last_change_tick = health_now;
        }
        if (diff2 >= 2) {
            mic2_last_change_tick = health_now;
        }

        if (p1 >= 2) mic1_last_signal_tick = health_now;
        if (p2 >= 2) mic2_last_signal_tick = health_now;
        last_health_p1 = p1;
        last_health_p2 = p2;

        if (rec_state == REC_REQUESTED) {
            recorded_frames = 0;
            rec_elapsed_seconds = 0;
            storage_full_stop = false;

            if (Storage_Free_Bytes() < STORAGE_MIN_FREE_START) {
                /* Kein Platz fuer eine sinnvolle Aufnahme */
                record_file = NULL;
                rec_state = REC_ERROR;
            } else {
                record_file = open_new_recording(record_path, sizeof(record_path));
                rec_state = (record_file == NULL) ? REC_ERROR : REC_RECORDING;
            }
        }

        if (rec_state == REC_RECORDING) {
            if (!rec_enc_push(mono, AUDIO_FRAMES)) {
                /* Schreiben fehlgeschlagen (Speicher voll): bisherigen Stand sauber abschliessen */
                storage_full_stop = true;
                rec_state = REC_STOP_REQUESTED;
            }

            recorded_frames += AUDIO_FRAMES;
            rec_elapsed_seconds =
                (uint32_t)(recorded_frames / RECORD_SAMPLE_RATE);

            /* Alle 5 s freien Platz pruefen: lieber sauber stoppen als mitten in der Datei scheitern */
            if ((recorded_frames % (RECORD_SAMPLE_RATE * 5ULL)) < AUDIO_FRAMES) {
                if (Storage_Free_Bytes() < STORAGE_MIN_FREE_RUNNING) {
                    storage_full_stop = true;
                    rec_state = REC_STOP_REQUESTED;
                }
            }

            /* Alle 30 s auf den Flash sichern, damit bei Stromverlust nur wenig fehlt */
            if ((recorded_frames % (RECORD_SAMPLE_RATE * 30ULL)) < AUDIO_FRAMES) {
                fflush(record_file);
                fsync(fileno(record_file));
            }

            /* Rechenlast des Encoders alle 10 s ausgeben (Messung fuer die Bitrate-Wahl) */
            if ((recorded_frames % (RECORD_SAMPLE_RATE * 10ULL)) < AUDIO_FRAMES) {
                printf("VERMERK REC: Encoder-Last %d %%, AGC-Gain x%d.%d, Speicher frei %llu KB, RAM frei %u (Minimum %u) Bytes, Stack-Reserve %u Bytes\n",
                       rec_enc_load_percent(),
                       agc_gain_x10() / 10, agc_gain_x10() % 10,
                       (unsigned long long)(Storage_Free_Bytes() / 1024),
                       (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                       (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                       (unsigned)uxTaskGetStackHighWaterMark(NULL));
            }
            paused_flushed = false;
        }

        if (rec_state == REC_PAUSED && !paused_flushed && record_file != NULL) {
            /* In der Pause nichts schreiben, aber bisherigen Stand sichern */
            fflush(record_file);
            fsync(fileno(record_file));
            paused_flushed = true;
        }

        if (rec_state == REC_STOP_REQUESTED) {
            rec_state = REC_SAVING;

            if (finalize_recording(record_file) == ESP_OK) {
                record_file = NULL;
                rec_state = REC_DONE;
            } else {
                record_file = NULL;
                rec_state = REC_ERROR;
            }
        }
    }
}

static void record_button_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) {
        return;
    }

    if (rec_state == REC_IDLE ||
        rec_state == REC_DONE ||
        rec_state == REC_ERROR) {
        rec_elapsed_seconds = 0;
        rec_state = REC_REQUESTED;
    } else if (rec_state == REC_RECORDING || rec_state == REC_PAUSED) {
        rec_state = REC_STOP_REQUESTED;
    }
}

static void pause_button_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) {
        return;
    }

    if (rec_state == REC_RECORDING) {
        rec_state = REC_PAUSED;
    } else if (rec_state == REC_PAUSED) {
        rec_state = REC_RECORDING;
    }
}

/* Idle: ein breiter Start-Button. Aufnahme/Pause: STOPP links, PAUSE/WEITER rechts. */
static void set_record_layout(bool recording)
{
    if (recording) {
        lv_obj_set_size(record_button, 130, 52);
        lv_obj_align(record_button, LV_ALIGN_TOP_MID, -45, 234);
        lv_obj_set_style_bg_color(record_button, lv_color_hex(0xFF453A), LV_PART_MAIN);
        lv_obj_set_style_text_color(record_button_label, lv_color_hex(0xFFFFFF), 0);
        lv_label_set_text(record_button_label, LV_SYMBOL_STOP "  STOPP");
        lv_obj_clear_flag(pause_button, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_set_size(record_button, 220, 52);
        lv_obj_align(record_button, LV_ALIGN_TOP_MID, 0, 234);
        lv_obj_set_style_bg_color(record_button, lv_color_hex(0x4AB7F4), LV_PART_MAIN);
        lv_obj_set_style_text_color(record_button_label, lv_color_hex(0x000000), 0);
        lv_obj_add_flag(pause_button, LV_OBJ_FLAG_HIDDEN);
    }
}

static void waveform_draw_cb(lv_event_t *e)
{
    lv_obj_t *obj = lv_event_get_target(e);
    lv_draw_ctx_t *draw_ctx = lv_event_get_draw_ctx(e);

    lv_area_t coords;
    lv_obj_get_coords(obj, &coords);
    lv_coord_t w = lv_area_get_width(&coords);
    lv_coord_t h = lv_area_get_height(&coords);

    const lv_coord_t bar_w = 4;
    const lv_coord_t min_h = 4;
    lv_coord_t step = w / WAVE_BARS;
    lv_coord_t x0 = coords.x1 + (w - step * (WAVE_BARS - 1) - bar_w) / 2;
    lv_coord_t cy = coords.y1 + h / 2;

    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.bg_color = wave_color;
    dsc.bg_opa = LV_OPA_COVER;
    dsc.radius = LV_RADIUS_CIRCLE;

    for (int i = 0; i < WAVE_BARS; i++) {
        /* Enden sanft auslaufen lassen wie im Vorbild */
        int edge = (i < WAVE_BARS - 1 - i) ? i : (WAVE_BARS - 1 - i);
        int level = wave_levels[i];
        if (edge < 5) {
            level = level * (edge + 1) / 6;
        }

        lv_coord_t bh = min_h + (lv_coord_t)(level * (h - min_h) / 100);
        lv_area_t a;
        a.x1 = x0 + i * step;
        a.x2 = a.x1 + bar_w - 1;
        a.y1 = cy - bh / 2;
        a.y2 = a.y1 + bh - 1;
        lv_draw_rect(draw_ctx, &dsc, &a);
    }
}

static void fertig_vollbild_ausblenden(void)
{
    if (fertig_vollbild != NULL) {
        lv_obj_add_flag(fertig_vollbild, LV_OBJ_FLAG_HIDDEN);
    }
}

static void fertig_vollbild_klick(lv_event_t *e)
{
    (void)e;
    fertig_vollbild_ausblenden();
}

/* Der Haken ist gezeichnet (Linienzug), nicht als Schriftzeichen: Es gibt ihn so in jeder Groesse. */
static void fertig_vollbild_erstellen(void)
{
    static const lv_point_t haken_punkte[] = {{34, 74}, {62, 102}, {108, 42}};

    fertig_vollbild = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(fertig_vollbild);
    lv_obj_set_size(fertig_vollbild, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(fertig_vollbild, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(fertig_vollbild, LV_OPA_COVER, 0);
    lv_obj_add_flag(fertig_vollbild, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_clear_flag(fertig_vollbild, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(fertig_vollbild, fertig_vollbild_klick, LV_EVENT_CLICKED, NULL);

    lv_obj_t *kreis = lv_obj_create(fertig_vollbild);
    lv_obj_remove_style_all(kreis);
    lv_obj_set_size(kreis, 140, 140);
    lv_obj_set_style_radius(kreis, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(kreis, lv_color_hex(0x59D65C), 0);
    lv_obj_set_style_bg_opa(kreis, LV_OPA_COVER, 0);
    lv_obj_align(kreis, LV_ALIGN_TOP_MID, 0, 55);

    lv_obj_t *haken = lv_line_create(kreis);
    lv_line_set_points(haken, haken_punkte, sizeof(haken_punkte) / sizeof(haken_punkte[0]));
    lv_obj_set_style_line_width(haken, 14, 0);
    lv_obj_set_style_line_color(haken, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_line_rounded(haken, true, 0);
    lv_obj_set_pos(haken, 0, 0);

    lv_obj_t *text = lv_label_create(fertig_vollbild);
    lv_label_set_text(text, "TRANSKRIPTION\nERFOLGREICH");
    lv_obj_set_style_text_font(text, &lv_font_montserrat_28, 0);
    lv_obj_set_style_text_color(text, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_text_align(text, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(text, LV_ALIGN_TOP_MID, 0, 215);

    lv_obj_add_flag(fertig_vollbild, LV_OBJ_FLAG_HIDDEN);
}

static void update_ui(void)
{
    static uint32_t last_update = 0;
    static uint32_t last_battery_update = 0;
    static uint32_t last_wifi_update = 0;
    static uint32_t last_mic_update = 0;
    static rec_state_t last_state = (rec_state_t)-1;

    uint32_t now = lv_tick_get();
    if ((now - last_update) < 50) {
        return;
    }
    last_update = now;

    if ((now - last_battery_update) >= 1000) {
        static float slow_voltage = 0.0f;   /* ~20 s Zeitkonstante, fuer die Prozentanzeige */
        static float fast_voltage = 0.0f;   /* ~3 s Zeitkonstante, fuer Neusynchronisation */
        static float previous_raw_voltage = 0.0f;
        static float power_reference_voltage = 0.0f;
        static int displayed_percent = -1;
        static bool external_power = false;
        static bool resync_percent = false;
        static uint8_t power_up_hits = 0;
        static uint8_t power_down_hits = 0;
        static uint32_t power_change_tick = 0;
        static uint32_t last_percent_step = 0;
        static int shown_percent = -2;
        static bool shown_charging = false;

        float v = BAT_Get_Volts();

        if (v >= 3.0f && v <= 4.35f) {
            if (slow_voltage <= 0.0f) {
                slow_voltage = v;
                fast_voltage = v;
            }
            slow_voltage += (v - slow_voltage) * 0.05f;
            fast_voltage += (v - fast_voltage) * 0.30f;

            if (previous_raw_voltage > 0.0f) {
                float raw_delta = v - previous_raw_voltage;

                if (!external_power) {
                    if (power_up_hits == 0 && raw_delta >= 0.060f) {
                        power_reference_voltage = previous_raw_voltage;
                        power_up_hits = 1;
                    } else if (power_up_hits > 0) {
                        if (v >= power_reference_voltage + 0.050f) {
                            power_up_hits++;
                            if (power_up_hits >= 2) {
                                external_power = true;
                                power_change_tick = now;
                                resync_percent = true;
                                power_up_hits = 0;
                                power_down_hits = 0;
                                printf("VERMERK USB/Power erkannt\n");
                            }
                        } else {
                            power_up_hits = 0;
                        }
                    }
                } else {
                    if (power_down_hits == 0 && raw_delta <= -0.060f) {
                        power_reference_voltage = previous_raw_voltage;
                        power_down_hits = 1;
                    } else if (power_down_hits > 0) {
                        if (v <= power_reference_voltage - 0.050f) {
                            power_down_hits++;
                            if (power_down_hits >= 2) {
                                external_power = false;
                                power_change_tick = now;
                                power_down_hits = 0;
                                power_up_hits = 0;
                                resync_percent = true;
                                printf("VERMERK USB/Power entfernt\n");
                            }
                        } else {
                            power_down_hits = 0;
                        }
                    }
                }
            }

            previous_raw_voltage = v;

            if (displayed_percent < 0) {
                displayed_percent = battery_voltage_to_percent(v);
                last_percent_step = now;
            } else if (!external_power && (now - power_change_tick) >= 30000) {
                if (resync_percent) {
                    /* Nach Ein-/Ausstecken einmalig direkt auf den neuen Wert springen */
                    slow_voltage = fast_voltage;
                    displayed_percent = battery_voltage_to_percent(slow_voltage);
                    resync_percent = false;
                    last_percent_step = now;
                } else if ((now - last_percent_step) >= 10000) {
                    /* Max. 1 % pro 10 s; nach oben erst ab +3 % (Erholung nach Last) */
                    int target = battery_voltage_to_percent(slow_voltage);
                    if (target < displayed_percent) {
                        displayed_percent--;
                        last_percent_step = now;
                    } else if (target >= displayed_percent + 3) {
                        displayed_percent++;
                        last_percent_step = now;
                    }
                }
            }

            if (displayed_percent != shown_percent) {
                lv_label_set_text_fmt(battery_label, "AKKU %d%%", displayed_percent);
                shown_percent = displayed_percent;
            }
            if (external_power != shown_charging) {
                if (external_power) {
                    lv_obj_clear_flag(battery_charge_icon, LV_OBJ_FLAG_HIDDEN);
                } else {
                    lv_obj_add_flag(battery_charge_icon, LV_OBJ_FLAG_HIDDEN);
                }
                shown_charging = external_power;
            }
            lv_obj_align_to(battery_charge_icon, battery_label, LV_ALIGN_OUT_LEFT_MID, -4, 0);
        }

        last_battery_update = now;
    }

    if ((now - last_wifi_update) >= 500) {
        static transfer_mode_t pending_mode = TRANSFER_MODE_LOCAL;
        static uint32_t pending_since = 0;
        static int shown_mode = -1;

        /* Entprellen: Aufstieg (z. B. LOKAL -> SERVER) nach 1 s,
         * Abstieg erst nach 6 s, damit ein einzelner verpasster Server-Check
         * oder kurzer WLAN-Aussetzer den Modus nicht flackern laesst. */
        transfer_mode_t detected = detect_transfer_mode();
        if (detected == transfer_mode) {
            pending_mode = detected;
            pending_since = now;
        } else {
            if (detected != pending_mode) {
                pending_mode = detected;
                pending_since = now;
            }
            uint32_t hold_ms = (detected > transfer_mode) ? 1000 : 6000;
            if ((now - pending_since) >= hold_ms) {
                transfer_mode = detected;
                printf("VERMERK Modus: %d\n", (int)detected);
            }
        }

        bool sending = upload_active &&
                       (transfer_mode == TRANSFER_MODE_PC || transfer_mode == TRANSFER_MODE_SERVER);
        bool wifi = WIFI_CONNECTED;
        int mode_key = (int)transfer_mode * 4 + (sending ? 1 : 0) + (wifi ? 2 : 0);
        if (mode_key != shown_mode) {
            const char *text;
            lv_color_t color;
            if (transfer_mode == TRANSFER_MODE_LOCAL) {
                text = "LOKAL";
                color = lv_color_hex(0x8E8E93);
            } else if (transfer_mode == TRANSFER_MODE_LINK) {
                text = wifi ? "WLAN" : "USB";
                color = lv_color_hex(0x4AB7F4);
            } else if (transfer_mode == TRANSFER_MODE_PC) {
                text = sending ? LV_SYMBOL_UPLOAD " PC" : "PC";
                color = lv_color_hex(0x64D2FF);
            } else {
                text = sending ? LV_SYMBOL_UPLOAD " SERVER" : "SERVER";
                color = lv_color_hex(0x34C759);
            }
            lv_label_set_text(connection_label, text);
            lv_obj_set_style_text_color(connection_label, color, 0);
            lv_obj_set_style_border_color(connection_label, color, 0);
            shown_mode = mode_key;
        }

        static int shown_pending = -1;
        int pending = (int)pending_uploads;
        if (pending != shown_pending) {
            if (pending <= 0) {
                lv_obj_add_flag(pending_label, LV_OBJ_FLAG_HIDDEN);
            } else {
                if (pending == 1) {
                    lv_label_set_text(pending_label, "1 AUFNAHME OFFEN");
                } else {
                    lv_label_set_text_fmt(pending_label, "%d AUFNAHMEN OFFEN", pending);
                }
                lv_obj_clear_flag(pending_label, LV_OBJ_FLAG_HIDDEN);
            }
            shown_pending = pending;
        }

        last_wifi_update = now;
    }

    if ((now - last_mic_update) >= 500) {
        TickType_t mic_now = xTaskGetTickCount();
        bool mic_grace = audio_first_ok_tick != 0 &&
                         (mic_now - audio_first_ok_tick) < pdMS_TO_TICKS(5000);
        bool mic_stream_ok = audio_last_ok_tick != 0 &&
                             (mic_now - audio_last_ok_tick) < pdMS_TO_TICKS(1500);
        bool mic1_signal_ok = mic1_last_signal_tick != 0 &&
                              (mic_now - mic1_last_signal_tick) < pdMS_TO_TICKS(5000);
        bool mic2_signal_ok = mic2_last_signal_tick != 0 &&
                              (mic_now - mic2_last_signal_tick) < pdMS_TO_TICKS(5000);
        bool mic1_change_ok = mic1_last_change_tick != 0 &&
                              (mic_now - mic1_last_change_tick) < pdMS_TO_TICKS(30000);
        bool mic2_change_ok = mic2_last_change_tick != 0 &&
                              (mic_now - mic2_last_change_tick) < pdMS_TO_TICKS(30000);

        bool both_quiet = !mic1_signal_ok && !mic2_signal_ok;
        bool both_channels_active = mic1_change_ok && mic2_change_ok;

        /* Im Normalfall zeigt die Wellenform den Pegel; der Hinweis erscheint
         * nur noch bei einem Fehler (z. B. ein Mikrofon liefert nichts). */
        bool mic_ok = mic_stream_ok && (mic_grace || both_quiet || both_channels_active);
        bool mic_starting = audio_first_ok_tick == 0 || mic_grace;
        if (mic_ok || mic_starting) {
            lv_obj_add_flag(mic_status_label, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_label_set_text(mic_status_label, "MIKROFON PRUEFEN");
            lv_obj_clear_flag(mic_status_label, LV_OBJ_FLAG_HIDDEN);
        }

        last_mic_update = now;
    }
    rec_state_t state = rec_state;

    /* Wellenform: alle 50 ms einen neuen Balken rechts anhaengen, in der Pause einfrieren */
    uint16_t peak = wave_peak;
    wave_peak = 0;
    if (state != REC_PAUSED) {
        memmove(wave_levels, wave_levels + 1, WAVE_BARS - 1);
        wave_levels[WAVE_BARS - 1] = peak_to_wave_level(peak);
    }
    if (state == REC_RECORDING) {
        wave_color = lv_color_hex(0xA8E1FF);
    } else if (state == REC_PAUSED) {
        wave_color = lv_color_hex(0x5A5A5E);
    } else {
        wave_color = lv_color_hex(0x3A7FA8);
    }
    lv_obj_invalidate(waveform);

    if (state == REC_RECORDING || state == REC_PAUSED) {
        uint32_t total = rec_elapsed_seconds;
        uint32_t hours = total / 3600;
        uint32_t minutes = (total % 3600) / 60;
        uint32_t seconds = total % 60;

        if (state == REC_RECORDING) {
            if (((now / 500) % 2) == 0) {
                lv_obj_clear_flag(record_indicator, LV_OBJ_FLAG_HIDDEN);
            } else {
                lv_obj_add_flag(record_indicator, LV_OBJ_FLAG_HIDDEN);
            }
        } else {
            lv_obj_add_flag(record_indicator, LV_OBJ_FLAG_HIDDEN);
        }

        lv_label_set_text_fmt(
            status_label,
            "%s %02u:%02u:%02u",
            (state == REC_PAUSED) ? "PAUSE" : "AUFNAHME",
            (unsigned)hours,
            (unsigned)minutes,
            (unsigned)seconds
        );

        if (state != last_state) {
            set_record_layout(true);
            if (state == REC_PAUSED) {
                lv_label_set_text(pause_button_label, LV_SYMBOL_PLAY);
                lv_obj_set_style_text_color(status_label, lv_color_hex(0xFF9F0A), 0);
            } else {
                lv_label_set_text(pause_button_label, LV_SYMBOL_PAUSE);
                lv_obj_set_style_text_color(status_label, lv_color_hex(0xFFFFFF), 0);
            }
            lv_obj_clear_state(record_button, LV_STATE_DISABLED);
            lv_obj_clear_state(pause_button, LV_STATE_DISABLED);
            last_state = state;
        }
        return;
    }

    lv_obj_add_flag(record_indicator, LV_OBJ_FLAG_HIDDEN);

    if (state != last_state) {
        lv_obj_set_style_text_color(status_label, lv_color_hex(0xFFFFFF), 0);
        switch (state) {
            case REC_IDLE:
                set_record_layout(false);
                lv_label_set_text(status_label, "BEREIT");
                lv_label_set_text(record_button_label, "AUFNAHME STARTEN");
                lv_obj_clear_state(record_button, LV_STATE_DISABLED);
                break;

            case REC_REQUESTED:
                lv_label_set_text(status_label, "Starte Aufnahme...");
                lv_obj_add_state(record_button, LV_STATE_DISABLED);
                break;

            case REC_STOP_REQUESTED:
                lv_label_set_text(status_label, "Stoppe Aufnahme...");
                lv_obj_add_state(record_button, LV_STATE_DISABLED);
                lv_obj_add_state(pause_button, LV_STATE_DISABLED);
                break;

            case REC_SAVING:
                lv_label_set_text(status_label, "Speichere...");
                lv_obj_add_state(record_button, LV_STATE_DISABLED);
                lv_obj_add_state(pause_button, LV_STATE_DISABLED);
                break;

            case REC_DONE:
                set_record_layout(false);
                if (storage_full_stop) {
                    lv_label_set_text(status_label, "VOLL - GESPEICHERT");
                    lv_obj_set_style_text_color(status_label, lv_color_hex(0xFF9F0A), 0);
                } else {
                    lv_label_set_text(status_label, "GESPEICHERT");
                    lv_obj_set_style_text_color(status_label, lv_color_hex(0x59D65C), 0);
                }
                lv_label_set_text(record_button_label, "NEU AUFNEHMEN");
                lv_obj_clear_state(record_button, LV_STATE_DISABLED);
                break;

            case REC_ERROR:
                set_record_layout(false);
                lv_label_set_text(status_label, "FEHLER SD/AUFNAHME");
                lv_label_set_text(record_button_label, "ERNEUT VERSUCHEN");
                lv_obj_clear_state(record_button, LV_STATE_DISABLED);
                break;

            default:
                break;
        }

        last_state = state;
    }

    /* Verarbeitung der zuletzt hochgeladenen Aufnahme: waehrend sie laeuft "TRANSKRIPTION WIRD VERARBEITET", am Ende
     * einmal ca. 4 s das gruene Haekchen ueber den ganzen Bildschirm, danach dauerhaft "TRANSKRIPTION ERFOLGREICH",
     * bis eine neue Aufnahme beginnt. Ersetzt nur den Statustext, solange nicht aufgenommen wird. */
    {
        const bool ruhe = (state == REC_IDLE || state == REC_DONE);
        if (!verarbeitung_sichtbar || verarbeitung_zustand != VERMERK_VERARB_FERTIG) {
            fertig_vollbild_gezeigt = false;   /* die naechste fertige Verarbeitung zeigt es wieder */
        }
        if (fertig_vollbild != NULL && !lv_obj_has_flag(fertig_vollbild, LV_OBJ_FLAG_HIDDEN) &&
            (!ruhe || lv_tick_elaps(fertig_vollbild_start) >= FERTIG_VOLLBILD_MS)) {
            fertig_vollbild_ausblenden();   /* Zeit um, oder eine Aufnahme beginnt */
        }
        if (fertig_vollbild != NULL && ruhe && verarbeitung_sichtbar && verarbeitung_zustand == VERMERK_VERARB_FERTIG &&
            !fertig_vollbild_gezeigt) {
            fertig_vollbild_gezeigt = true;
            fertig_vollbild_start = lv_tick_get();
            lv_obj_clear_flag(fertig_vollbild, LV_OBJ_FLAG_HIDDEN);
        }
    }
    {
        static int shown_key = -2;
        static rec_state_t shown_state = (rec_state_t)-1;
        int key = -1;   /* -1 = nichts Besonderes anzeigen */

        if ((state == REC_IDLE || state == REC_DONE) && verarbeitung_sichtbar) {
            vermerk_verarbeitung_t z = verarbeitung_zustand;
            bool abgelaufen = (z == VERMERK_VERARB_FEHLER) &&
                              ((uint32_t)(esp_timer_get_time() / 1000) - verarbeitung_ende_ms) > VERARBEITUNG_ANZEIGE_MS;
            if (!abgelaufen && z >= VERMERK_VERARB_WARTET) {
                key = (int)z * 1000;
            }
        }
        if (state != shown_state) {
            shown_state = state;
            shown_key = -2;   /* der Statustext wurde oben neu gesetzt: noch einmal darueberschreiben */
        }
        if (key != shown_key) {
            int vorher = shown_key;
            shown_key = key;
            if (key >= 0) {
                switch (verarbeitung_zustand) {
                    case VERMERK_VERARB_FERTIG:
                        lv_label_set_text(status_label, LV_SYMBOL_OK " TRANSKRIPTION ERFOLGREICH");
                        lv_obj_set_style_text_color(status_label, lv_color_hex(0x59D65C), 0);
                        break;
                    case VERMERK_VERARB_FEHLER:
                        lv_label_set_text(status_label, "VERARBEITUNG FEHLGESCHLAGEN");
                        lv_obj_set_style_text_color(status_label, lv_color_hex(0xFF6B6B), 0);
                        break;
                    default:   /* WARTET, TRANSKRIPTION, AUSWERTUNG: fuer das Geraet ein einziger Zustand */
                        lv_label_set_text(status_label, "TRANSKRIPTION WIRD VERARBEITET");
                        lv_obj_set_style_text_color(status_label, lv_color_hex(0x4AB7F4), 0);
                        break;
                }
            } else if (vorher >= 0) {
                last_state = (rec_state_t)-1;   /* Anzeige vorbei: normalen Statustext (BEREIT, GESPEICHERT) wieder setzen */
            }
        }
    }
}

static lv_obj_t *make_label(lv_obj_t *parent, const char *text, lv_color_t color)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_color(label, color, 0);
    return label;
}
static void vermerk_h3_ui_create(void)
{
    lv_obj_t *scr = lv_scr_act();

    lv_obj_set_style_bg_color(scr, lv_color_hex(0x000000), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_scrollbar_mode(scr, LV_SCROLLBAR_MODE_OFF);

    lv_obj_t *logo = lv_img_create(scr);
    lv_img_set_src(logo, &vermerk_logo);
    lv_obj_set_size(logo, 96, 96);
    lv_img_set_pivot(logo, 48, 48);
    lv_img_set_zoom(logo, 171);
    lv_obj_align(logo, LV_ALIGN_TOP_MID, 0, -8);

    lv_obj_t *brand = make_label(scr, "VERMERK", lv_color_hex(0xFFFFFF));
    lv_obj_align(brand, LV_ALIGN_TOP_MID, 0, 73);
    mic_status_label = make_label(scr, "MIKROFON PRUEFEN", lv_color_hex(0xFF6B6B));
    lv_obj_add_flag(mic_status_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align(mic_status_label, LV_ALIGN_TOP_MID, 0, 92);

    connection_label = make_label(scr, "LOKAL", lv_color_hex(0x8E8E93));
    lv_obj_align(connection_label, LV_ALIGN_TOP_LEFT, 42, 108);

    lv_obj_set_size(connection_label, 145, 36);
    lv_obj_set_style_text_align(connection_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_pad_top(connection_label, 8, 0);

    lv_obj_set_style_bg_color(connection_label, lv_color_hex(0x111111), 0);
    lv_obj_set_style_bg_opa(connection_label, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(connection_label, lv_color_hex(0x8E8E93), 0);
    lv_obj_set_style_border_width(connection_label, 1, 0);
    lv_obj_set_style_radius(connection_label, 18, 0);

    battery_label = make_label(scr, "AKKU --%", lv_color_hex(0x4AB7F4));
    lv_obj_align(battery_label, LV_ALIGN_TOP_RIGHT, -42, 108);

    battery_charge_icon = make_label(scr, LV_SYMBOL_CHARGE, lv_color_hex(0xFFD60A));
    lv_obj_align_to(battery_charge_icon, battery_label, LV_ALIGN_OUT_LEFT_MID, -4, 0);
    lv_obj_add_flag(battery_charge_icon, LV_OBJ_FLAG_HIDDEN);

    status_label = make_label(scr, "BEREIT", lv_color_hex(0xFFFFFF));
    lv_obj_align(status_label, LV_ALIGN_TOP_MID, 0, 151);
    fertig_vollbild_erstellen();
    record_indicator = lv_obj_create(scr);
    lv_obj_set_size(record_indicator, 10, 10);
    lv_obj_set_style_radius(record_indicator, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(record_indicator, lv_color_hex(0xFF2D2D), 0);
    lv_obj_set_style_bg_opa(record_indicator, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(record_indicator, 0, 0);
    lv_obj_align(record_indicator, LV_ALIGN_TOP_MID, -92, 155);
    lv_obj_add_flag(record_indicator, LV_OBJ_FLAG_HIDDEN);

    /* Mikrofon-Pegel als Wellenform in der Bildschirmmitte */
    wave_color = lv_color_hex(0x3A7FA8);
    waveform = lv_obj_create(scr);
    lv_obj_remove_style_all(waveform);
    lv_obj_set_size(waveform, 240, 52);
    lv_obj_align(waveform, LV_ALIGN_TOP_MID, 0, 174);
    lv_obj_clear_flag(waveform, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(waveform, waveform_draw_cb, LV_EVENT_DRAW_MAIN, NULL);

    record_button = lv_btn_create(scr);
    lv_obj_set_size(record_button, 220, 52);
    lv_obj_align(record_button, LV_ALIGN_TOP_MID, 0, 234);
    lv_obj_set_style_bg_color(record_button, lv_color_hex(0x4AB7F4), LV_PART_MAIN);
    lv_obj_set_style_radius(record_button, 8, LV_PART_MAIN);
    lv_obj_add_event_cb(record_button, record_button_cb, LV_EVENT_CLICKED, NULL);

    record_button_label = lv_label_create(record_button);
    lv_label_set_text(record_button_label, "AUFNAHME STARTEN");
    lv_obj_set_style_text_color(record_button_label, lv_color_hex(0x000000), 0);
    lv_obj_center(record_button_label);

    pause_button = lv_btn_create(scr);
    lv_obj_set_size(pause_button, 80, 52);
    lv_obj_align(pause_button, LV_ALIGN_TOP_MID, 70, 234);
    lv_obj_set_style_bg_color(pause_button, lv_color_hex(0x3A3A3C), LV_PART_MAIN);
    lv_obj_set_style_radius(pause_button, 8, LV_PART_MAIN);
    lv_obj_add_event_cb(pause_button, pause_button_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_add_flag(pause_button, LV_OBJ_FLAG_HIDDEN);

    pause_button_label = lv_label_create(pause_button);
    lv_label_set_text(pause_button_label, LV_SYMBOL_PAUSE);
    lv_obj_set_style_text_color(pause_button_label, lv_color_hex(0xFFFFFF), 0);
    lv_obj_center(pause_button_label);

    pending_label = make_label(scr, "", lv_color_hex(0xAAAAAA));
    lv_obj_align(pending_label, LV_ALIGN_TOP_MID, 0, 300);
    lv_obj_add_flag(pending_label, LV_OBJ_FLAG_HIDDEN);
}

/* Upload: Wartezeit je Datei, nur im RAM. Eine Datei, die scheitert, wartet (5 s, doppelt so lang
 * bis 5 min); die anderen gehen weiter. */
static const char *const upload_exts[] = {REC_EXT, REC_EXT_LEGACY};   /* Index = Art in der Warteliste */
static vermerk_warteliste_t upload_warteliste;
static bool upload_fast_mode = false;

static uint64_t upload_now_ms(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000);
}

/* Neue Aufnahme hat Vorrang: der Upload hoert zwischen zwei Stuecken auf und macht spaeter dort weiter */
static bool recording_has_priority(void)
{
    rec_state_t s = rec_state;
    return s != REC_IDLE && s != REC_DONE && s != REC_ERROR;
}

/* Zaehlt H5_xxx.opus und H5_xxx.wav auf der SD, die der Upload-Manager noch senden wuerde
 * (gleicher Nummernbereich wie dort). Hochgeladene Dateien werden geloescht. */
static uint32_t count_pending_recordings(void)
{
    DIR *dir = opendir(REC_DIR);
    if (dir == NULL) {
        return 0;
    }

    uint32_t count = 0;
    uint32_t first = vermerk_konfig_erste_nummer();
    uint32_t limit = next_record_id;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        uint32_t id = 0;
        if ((vermerk_aufnahme_nummer(entry->d_name, REC_EXT, &id) ||
             vermerk_aufnahme_nummer(entry->d_name, REC_EXT_LEGACY, &id)) &&
            id >= first && id < limit) {
            count++;
        }
    }
    closedir(dir);
    return count;
}

/* Die kleinsten Nummern (hoechstens max) mit Aufnahme oder uebrig gebliebenem .sent-Marker sammeln,
 * aufsteigend. Kostet eine Verzeichnisliste, egal wie hoch die Nummern sind. */
static int collect_upload_ids(uint32_t *ids, int max)
{
    DIR *dir = opendir(REC_DIR);
    if (dir == NULL) {
        return 0;
    }

    int count = 0;
    uint32_t first = vermerk_konfig_erste_nummer();
    uint32_t limit = next_record_id;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        uint32_t id = 0;
        if ((vermerk_aufnahme_nummer(entry->d_name, REC_EXT, &id) ||
             vermerk_aufnahme_nummer(entry->d_name, REC_EXT_LEGACY, &id) ||
             vermerk_aufnahme_nummer(entry->d_name, "sent", &id)) &&
            id >= first && id < limit) {
            vermerk_nummer_einfuegen(ids, &count, max, id);
        }
    }
    closedir(dir);
    return count;
}

/* Verarbeitungsstand beobachten: Nach einem erfolgreichen Upload fragt der Manager alle paar Sekunden
 * GET .../status ab, bis die Software "fertig" oder "fehler" meldet. Kennt sie die Aufnahme nicht (dreimal
 * "unbekannt": Neustart der Software, Live-Verarbeitung aus, Server statt PC) oder lehnt sie die Abfrage ab
 * (4xx, z. B. eine aeltere Software ohne .../status), bleibt die Anzeige aus. */
#define STATUS_ABFRAGE_MS     3000u
#define STATUS_MAX_DAUER_MS   (3ULL * 60ULL * 60ULL * 1000ULL)   /* laenger wird nicht gewartet */
#define STATUS_UNBEKANNT_MAX  3
static char status_name[32] = "";
static uint64_t status_start_ms = 0;
static uint64_t status_naechste_ms = 0;
static int status_unbekannt = 0;

static void status_beobachten(const char *dateiname)
{
    snprintf(status_name, sizeof(status_name), "%s", dateiname);
    status_start_ms = upload_now_ms();
    status_naechste_ms = status_start_ms;
    status_unbekannt = 0;
    verarbeitung_sichtbar = false;
    verarbeitung_zustand = VERMERK_VERARB_UNBEKANNT;
    verarbeitung_prozent = -1;
}

/* Eine neue Aufnahme beginnt: der alte Stand ist uninteressant */
static void status_beenden(void)
{
    status_name[0] = '\0';
    verarbeitung_sichtbar = false;
}

static void status_schritt(void)
{
    if (status_name[0] == '\0') {
        return;
    }
    uint64_t jetzt = upload_now_ms();
    if (jetzt < status_naechste_ms) {
        return;
    }
    status_naechste_ms = jetzt + STATUS_ABFRAGE_MS;
    if (jetzt - status_start_ms > STATUS_MAX_DAUER_MS) {
        status_beenden();
        return;
    }

    vermerk_status_t st;
    vermerk_statusabfrage_t abfrage = VERMERK_Status_Abfragen(status_name, &st);
    if (abfrage == VERMERK_STATUSABFRAGE_SPAETER) {
        return;   /* Netz oder Software gerade nicht erreichbar: weiter versuchen */
    }
    if (abfrage == VERMERK_STATUSABFRAGE_ENDE) {
        /* 4xx (aeltere Software ohne .../status, Token widerrufen ...): wie "unbekannt", nicht weiter fragen */
        printf("VERMERK Verarbeitung %s: die Software lehnt die Abfrage ab, keine Anzeige\n", status_name);
        status_beenden();
        return;
    }
    if (st.zustand == VERMERK_VERARB_UNBEKANNT) {
        if (++status_unbekannt >= STATUS_UNBEKANNT_MAX) {
            printf("VERMERK Verarbeitung %s: der Software ist nichts bekannt, keine Anzeige\n", status_name);
            status_beenden();
        }
        return;
    }
    status_unbekannt = 0;
    if (st.zustand != verarbeitung_zustand || st.fortschritt_prozent / 5 != verarbeitung_prozent / 5) {
        if (st.fortschritt_prozent >= 0) {
            printf("VERMERK Verarbeitung %s: %s %d %%\n", status_name, vermerk_verarbeitung_text(st.zustand),
                   st.fortschritt_prozent);
        } else {
            printf("VERMERK Verarbeitung %s: %s\n", status_name, vermerk_verarbeitung_text(st.zustand));
        }
    }
    verarbeitung_zustand = st.zustand;
    verarbeitung_prozent = st.fortschritt_prozent;
    verarbeitung_sichtbar = true;
    if (vermerk_verarbeitung_beendet(st.zustand)) {
        verarbeitung_ende_ms = (uint32_t)jetzt;
        status_name[0] = '\0';   /* fertig: nichts mehr abzufragen, die Anzeige bleibt */
    }
}

/* Wird zwischen zwei Stuecken eines Uploads gefragt: Auch waehrend einer langen Datei den Verarbeitungsstand der
 * zuletzt aufgenommenen Aufnahme aktuell halten (eigene, kurze Anfrage), dann: aufhoeren, wenn eine Aufnahme beginnt. */
static bool upload_abbrechen(void)
{
    status_schritt();
    return recording_has_priority();
}

/* Eine Aufnahme (Endung upload_exts[art]) hochladen.
 * 0 = nichts zu tun oder diese Datei spaeter, 1 = erledigt, -1 = Durchgang beenden (kein Ziel, neue Aufnahme) */
static int upload_one(uint32_t i, uint8_t art)
{
    const char *ext = upload_exts[art];
    char path[64];
    char sent_path[64];
    char filename[32];

    snprintf(path, sizeof(path), REC_DIR "/H5_%03u.%s", (unsigned)i, ext);
    snprintf(sent_path, sizeof(sent_path), REC_DIR "/H5_%03u.sent", (unsigned)i);

    FILE *wav = fopen(path, "rb");
    FILE *sent = fopen(sent_path, "rb");

    if (sent != NULL) {
        fclose(sent);

        if (wav != NULL) {
            fclose(wav);
            if (remove(path) == 0) {
                remove(sent_path);
                printf("VERMERK lokale Kopie entfernt: H5_%03u.%s\n", (unsigned)i, ext);
            }
        } else {
            remove(sent_path);
        }
        return 0;
    }

    if (wav == NULL) {
        return 0;
    }
    /* Leere Datei (Reset oder Stromverlust waehrend der Aufnahme): nie hochladbar, also entfernen. */
    if (fseek(wav, 0, SEEK_END) == 0 && ftell(wav) <= 0) {
        fclose(wav);
        remove(path);
        printf("VERMERK leere Aufnahme entfernt: %s\n", path);
        return 0;
    }
    fclose(wav);

    if (!vermerk_warteliste_bereit(&upload_warteliste, i, art, upload_now_ms())) {
        return 0;   /* diese Datei wartet noch, die naechste ist dran */
    }

    /* WLAN-Energiesparen erst abschalten, wenn wirklich gesendet wird */
    if (!upload_fast_mode) {
        VERMERK_Wifi_Fast_Mode(true);
        upload_fast_mode = true;
    }

    snprintf(filename, sizeof(filename), "H5_%03u.%s", (unsigned)i, ext);
    printf("VERMERK Upload: %s\n", filename);

    upload_active = true;
    int64_t upload_start_us = esp_timer_get_time();
    vermerk_ergebnis_t result = VERMERK_Upload_File(path, filename, upload_abbrechen);
    upload_active = false;
    printf("VERMERK Upload-Dauer: %s %lld ms\n", filename,
           (long long)((esp_timer_get_time() - upload_start_us) / 1000));
    if (result == VERMERK_ERGEBNIS_KEIN_ZIEL || result == VERMERK_ERGEBNIS_UNTERBROCHEN) {
        printf("VERMERK Upload angehalten: %s (%s)\n", filename, vermerk_ergebnis_text(result));
        return -1;
    }
    if (result != VERMERK_ERGEBNIS_FERTIG) {
        vermerk_warteliste_fehler(&upload_warteliste, i, art, result, upload_now_ms());
        printf("VERMERK Upload FEHLER: %s (%s), naechster Versuch in %u s\n", filename,
               vermerk_ergebnis_text(result),
               (unsigned)(vermerk_warteliste_rest_ms(&upload_warteliste, i, art, upload_now_ms()) / 1000));
        return 0;
    }
    vermerk_warteliste_erfolg(&upload_warteliste, i, art);
    if (i == upload_vorrang_id) {
        /* Die zuletzt aufgenommene Aufnahme ist angekommen: Die Software verarbeitet sie jetzt, Stand abfragen und anzeigen */
        upload_vorrang_id = 0;
        status_beobachten(filename);
    }

    /* Die Software hat die Datei geprueft ("fertig"). Marker zuerst: stirbt das Geraet beim Loeschen,
     * raeumt der naechste Durchgang auf, statt die Datei noch einmal zu senden. */
    FILE *marker = fopen(sent_path, "wb");
    if (marker == NULL) {
        printf("VERMERK Marker FEHLER: %s\n", filename);
        return -1;
    }

    fprintf(marker, "uploaded\n");
    fclose(marker);

    if (remove(path) == 0) {
        remove(sent_path);
        if (pending_uploads > 0) {
            pending_uploads--;
        }
        printf("VERMERK Upload + Loeschen erfolgreich: %s\n", filename);
    } else {
        printf("VERMERK Upload OK, lokale Datei noch vorhanden: %s\n", filename);
    }

    vTaskDelay(pdMS_TO_TICKS(20));
    return 1;
}

static void upload_manager_task(void *arg)
{
    uint32_t ids[UPLOAD_IDS_PER_PASS];

    vermerk_warteliste_leeren(&upload_warteliste);

    while (1) {
        rec_state_t s = rec_state;
        bool recording_busy = (s == REC_REQUESTED ||
                               s == REC_RECORDING ||
                               s == REC_PAUSED ||
                               s == REC_STOP_REQUESTED ||
                               s == REC_SAVING);

        /* Zaehlen nur ausserhalb einer Aufnahme, damit der SD-Zugriff
         * das Schreiben der Aufnahme nicht ausbremst */
        if (!recording_busy) {
            pending_uploads = count_pending_recordings();
        }

        bool target_ok = (transfer_mode == TRANSFER_MODE_PC && PC_REACHABLE) ||
                         (transfer_mode == TRANSFER_MODE_SERVER && SERVER_REACHABLE);
        if (recording_busy) {
            status_beenden();
            if (target_ok) {
                VERMERK_Live_Schritt();   /* waehrend der Aufnahme: neue Bytes an die Software senden (alle 15 s) */
            }
            vTaskDelay(pdMS_TO_TICKS(2000));
            continue;
        }
        if (!target_ok) {
            vTaskDelay(pdMS_TO_TICKS(2000));
            continue;
        }

        /* Aelteste zuerst. Eine Datei, die scheitert, wartet; die naechste ist trotzdem dran. */
        int count = collect_upload_ids(ids, UPLOAD_IDS_PER_PASS);

        /* Die gerade aufgenommene Aufnahme zuerst: Wer auf das Ergebnis wartet, soll nicht hinter allen
         * aelteren Dateien anstehen (bei Live-Senden ist sie ohnehin fast vollstaendig am Ziel). */
        uint32_t vorrang = upload_vorrang_id;
        if (vorrang != 0 && recording_exists(vorrang)) {
            int pos = -1;
            for (int k = 0; k < count; k++) {
                if (ids[k] == vorrang) {
                    pos = k;
                }
            }
            if (pos < 0) {
                /* Nicht unter den kleinsten Nummern (viele aeltere Dateien warten): Ist die Liste voll, macht die
                 * groesste der aelteren Platz - sie kommt im naechsten Durchgang dran. */
                pos = (count < UPLOAD_IDS_PER_PASS) ? count++ : count - 1;
            }
            if (pos > 0) {
                memmove(&ids[1], &ids[0], (size_t)pos * sizeof(ids[0]));
                ids[0] = vorrang;
            } else if (pos == 0) {
                ids[0] = vorrang;
            }
        }
        bool stop = false;
        for (int k = 0; k < count && !stop; k++) {
            if (recording_has_priority()) {
                break;  /* Neue Aufnahme hat Vorrang vor dem Upload */
            }

            for (uint8_t art = 0; art < 2; art++) {
                if (upload_one(ids[k], art) < 0) {
                    stop = true;
                    break;
                }
            }
        }

        if (upload_fast_mode) {
            VERMERK_Wifi_Fast_Mode(false);
            upload_fast_mode = false;
        }

        status_schritt();

        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(esp_board_init(16000, 2, 16));
    rec_enc_init();   /* Encoder frueh anlegen, solange noch ein grosser RAM-Block frei ist */
    opus_enc_seiten_haken(vermerk_live_seite);   /* jede Ogg-Seite auch fuer das Senden waehrend der Aufnahme */
    BAT_Init();
    SD_Init();

    EXIO_Init();
    LCD_Init();
    LVGL_Init();

    vermerk_h3_ui_create();
    Wireless_Init();
    vermerk_konsole_starten(recording_has_priority);   /* Einrichtung ueber USB; nie waehrend einer Aufnahme speichern */
    recording_counter_init();

    xTaskCreatePinnedToCore(
        audio_task,
        "h3_audio",
        AUDIO_TASK_STACK,
        NULL,
        5,
        NULL,
        1
    );

    xTaskCreatePinnedToCore(
        upload_manager_task,
        "upload_manager",
        8192,
        NULL,
        2,
        NULL,
        0);

    while (1) {
        update_ui();
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

