/* VERMERK-Recorder fuer das Waveshare ESP32-S3-AUDIO-Board (ohne Bildschirm).
 *
 * Bedienung ueber Tasten, Rueckmeldung ueber den LED-Ring (siehe firmware/esp32-s3-audio/README.md):
 *   KEY1 oder BOOT  kurz: Aufnahme starten       lang (1 s halten): Aufnahme beenden und speichern
 *   KEY2            kurz: Pause / Weiter
 *   KEY3            kurz: Speicher-Fuellstand anzeigen
 * Aufnahme, Zaehler und Upload sind dieselbe Logik wie bei den Geraeten mit Bildschirm. */

#include "Audio_Board.h"
#include "Buttons.h"
#include "Leds.h"
#include "Storage.h"
#include "Rec_Codec.h"
#include "Wireless.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
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

#define UPLOAD_FIRST_ID      1      /* Das Geraet startet leer: alle Aufnahmen hochladen */
#define AUDIO_TASK_STACK     28672   /* der Opus-Encoder rechnet auf dem Stack dieser Task */
#define STORAGE_MIN_FREE_START    (256 * 1024)   /* darunter keine neue Aufnahme */
#define STORAGE_MIN_FREE_RUNNING  (64 * 1024)    /* darunter wird die laufende Aufnahme beendet */

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
static volatile uint16_t wave_peak = 0;          /* Max. Pegel seit letzter Abholung durch die LED-Anzeige */
static volatile uint32_t pending_uploads = 0;    /* Aufnahmen, die noch hochgeladen werden */
static volatile bool upload_active = false;
static volatile bool storage_full_stop = false;   /* Aufnahme wegen vollem Speicher beendet */

/* Pegel 0..100 fuer die Wellenform. Wurzel-Kennlinie, damit leise Sprache
 * noch sichtbar ist und laute Stellen nicht sofort anschlagen. */
static uint8_t peak_to_wave_level(uint16_t peak)
{
    if (peak < 30) return 0;
    float lin = (float)peak / 2000.0f;
    if (lin > 1.0f) lin = 1.0f;
    return (uint8_t)(sqrtf(lin) * 100.0f);
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


/* Gibt es die Aufnahme mit dieser Nummer (egal in welchem Speicher)? Mit Pfad des Fundes. */
static bool find_recording(uint32_t id, const char *ext, char *path, size_t path_len)
{
    for (int d = 0; d < Storage_Dir_Count(); d++) {
        snprintf(path, path_len, "%s/H5_%03u.%s", Storage_Dir_At(d), (unsigned)id, ext);
        FILE *f = fopen(path, "rb");
        if (f != NULL) {
            fclose(f);
            return true;
        }
    }
    return false;
}

static uint32_t find_next_sd_record_id(void)
{
    uint32_t highest = 0;
    char path[96];

    for (uint32_t i = 1; i <= 999; i++) {
        if (find_recording(i, REC_EXT, path, sizeof(path))) {
            highest = i;
        }
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
        char found[96];
        if (find_recording(id, REC_EXT, found, sizeof(found))) {
            next_record_id++;
            continue;
        }
        snprintf(path, path_len, "%s/H5_%03u." REC_EXT, Storage_Dir(), (unsigned)id);

        FILE *f = fopen(path, "wb");
        if (f == NULL) {
            return NULL;
        }

        if (!rec_enc_begin(f)) {
            fclose(f);
            remove(path);
            return NULL;
        }

        esp_err_t err = save_next_record_id(id + 1);
        if (err != ESP_OK) {
            fclose(f);
            remove(path);
            return NULL;
        }

        next_record_id = id + 1;
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
                printf("VERMERK REC: Encoder-Last %d %%, Speicher frei %llu KB, RAM frei %u (Minimum %u) Bytes, Stack-Reserve %u Bytes\n",
                       rec_enc_load_percent(),
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

/* Zaehlt die Aufnahmen (H5_xxx) im Flash-Speicher, die der Upload-Manager noch senden wuerde
 * (gleicher ID-Bereich wie dort). Hochgeladene Dateien werden geloescht. */
static uint32_t count_pending_recordings(void)
{
    uint32_t count = 0;
    uint32_t limit = next_record_id;

    for (int d = 0; d < Storage_Dir_Count(); d++) {
        DIR *dir = opendir(Storage_Dir_At(d));
        if (dir == NULL) {
            continue;
        }

        struct dirent *entry;
        while ((entry = readdir(dir)) != NULL) {
            unsigned id = 0;
            char ext[4] = {0};
            if (sscanf(entry->d_name, "%*1[Hh]5_%3u.%3s", &id, ext) == 2 &&
                strcasecmp(ext, REC_EXT) == 0 &&
                id >= UPLOAD_FIRST_ID && id < limit) {
                count++;
            }
        }
        closedir(dir);
    }
    return count;
}

/* Eine Aufnahme aus einem Speicher hochladen. 0 = nichts zu tun, 1 = erledigt, -1 = Fehler (abbrechen) */
static int upload_one(uint32_t i, const char *dir)
{
    char path[96];
    char sent_path[96];
    char filename[32];

    snprintf(path, sizeof(path), "%s/H5_%03u." REC_EXT, dir, (unsigned)i);
    snprintf(sent_path, sizeof(sent_path), "%s/H5_%03u.sent", dir, (unsigned)i);

    FILE *wav = fopen(path, "rb");
    FILE *sent = fopen(sent_path, "rb");

    if (sent != NULL) {
        fclose(sent);

        if (wav != NULL) {
            fclose(wav);
            if (remove(path) == 0) {
                remove(sent_path);
                printf("VERMERK lokale Kopie entfernt: H5_%03u." REC_EXT "\n", (unsigned)i);
            }
        } else {
            remove(sent_path);
        }
        return 0;
    }

    if (wav == NULL) {
        return 0;
    }
    /* Leere Datei (Reset oder Stromverlust waehrend der Aufnahme): nie hochladbar und wuerde die
     * Warteschlange fuer alle spaeteren Aufnahmen blockieren, also entfernen. */
    if (fseek(wav, 0, SEEK_END) == 0 && ftell(wav) <= 0) {
        fclose(wav);
        remove(path);
        printf("VERMERK leere Aufnahme entfernt: %s\n", path);
        return 0;
    }
    fclose(wav);

    snprintf(filename, sizeof(filename), "H5_%03u." REC_EXT, (unsigned)i);
    printf("VERMERK Upload: %s (%s)\n", filename, dir);

    upload_active = true;
    int64_t upload_start_us = esp_timer_get_time();
    esp_err_t err = VERMERK_Upload_File(path, filename);
    upload_active = false;
    printf("VERMERK Upload-Dauer: %s %lld ms\n", filename,
           (long long)((esp_timer_get_time() - upload_start_us) / 1000));
    if (err != ESP_OK) {
        printf("VERMERK Upload FEHLER: %s (%s)\n", filename, esp_err_to_name(err));
        return -1;
    }

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
    while (1) {
        rec_state_t s = rec_state;
        bool recording_busy = (s == REC_REQUESTED ||
                               s == REC_RECORDING ||
                               s == REC_PAUSED ||
                               s == REC_STOP_REQUESTED ||
                               s == REC_SAVING);

        /* Zaehlen nur ausserhalb einer Aufnahme, damit der Flash-Zugriff
         * das Schreiben der Aufnahme nicht ausbremst */
        if (!recording_busy) {
            pending_uploads = count_pending_recordings();
        }

        bool target_ok = (transfer_mode == TRANSFER_MODE_PC && PC_REACHABLE) ||
                         (transfer_mode == TRANSFER_MODE_SERVER && SERVER_REACHABLE);
        if (!target_ok || recording_busy) {
            vTaskDelay(pdMS_TO_TICKS(2000));
            continue;
        }

        uint32_t current_limit = next_record_id;

        /* WLAN-Energiesparen nur abschalten, wenn wirklich etwas zu senden ist */
        bool fast_mode = pending_uploads > 0;
        if (fast_mode) {
            VERMERK_Wifi_Fast_Mode(true);
        }

        bool failed = false;
        for (uint32_t i = UPLOAD_FIRST_ID; i < current_limit && !failed; i++) {
            if (rec_state != REC_IDLE && rec_state != REC_DONE && rec_state != REC_ERROR) {
                break;  /* Neue Aufnahme hat Vorrang vor dem Upload */
            }

            for (int d = 0; d < Storage_Dir_Count(); d++) {
                if (upload_one(i, Storage_Dir_At(d)) < 0) {
                    failed = true;
                    break;
                }
            }
        }

        if (fast_mode) {
            VERMERK_Wifi_Fast_Mode(false);
        }

        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}


/* ---- Tasten ---- */

static void start_recording(void)
{
    rec_elapsed_seconds = 0;
    rec_state = REC_REQUESTED;
    Leds_Flash(255, 255, 255, 120);
}

static void stop_recording(void)
{
    rec_state = REC_STOP_REQUESTED;
}

static void on_key(key_id_t key, key_event_t ev)
{
    static const char *const names[KEY_COUNT] = {"KEY1", "KEY2", "KEY3", "BOOT"};
    rec_state_t st = rec_state;
    bool recording = (st == REC_RECORDING || st == REC_PAUSED);
    bool idle = (st == REC_IDLE || st == REC_DONE || st == REC_ERROR);

    printf("VERMERK Taste %s %s\n", names[key], ev == KEY_EVENT_LONG ? "lang" : "kurz");

    switch (key) {
    case KEY_1:
    case KEY_BOOT:
        if (idle) {
            /* Starten mit kurzem Druck; wer laenger haelt, startet ebenfalls */
            start_recording();
        } else if (recording && ev == KEY_EVENT_LONG) {
            stop_recording();           /* Beenden nur durch Halten: schuetzt vor versehentlichem Stoppen */
        } else if (recording) {
            Leds_Flash(255, 120, 0, 250);   /* kurzer Druck waehrend der Aufnahme: nur Hinweis "halten zum Beenden" */
        }
        break;

    case KEY_2:
        if (ev == KEY_EVENT_SHORT) {
            if (st == REC_RECORDING) {
                rec_state = REC_PAUSED;
            } else if (st == REC_PAUSED) {
                rec_state = REC_RECORDING;
            }
        }
        break;

    case KEY_3:
        if (ev == KEY_EVENT_SHORT) {
            uint64_t total = Storage_Total_Bytes();
            uint64_t free_b = Storage_Free_Bytes();
            uint8_t used = (total > 0) ? (uint8_t)(100 - (free_b * 100 / total)) : 100;
            Leds_Show_Storage(used, Storage_Is_Sd());
            printf("VERMERK Speicher: %s, %llu von %llu MB frei\n", Storage_Is_Sd() ? "SD-Karte" : "Flash",
                   (unsigned long long)(free_b / (1024 * 1024)), (unsigned long long)(total / (1024 * 1024)));
        }
        break;

    default:
        break;
    }
}

/* ---- Anzeige: Aufnahmezustand -> LED-Ring ---- */

static void update_leds(void)
{
    static rec_state_t last_state = (rec_state_t)-1;
    static int64_t state_since_ms = 0;
    static uint8_t level_smooth = 0;

    int64_t now = esp_timer_get_time() / 1000;
    rec_state_t st = rec_state;
    if (st != last_state) {
        state_since_ms = now;
        last_state = st;
    }

    /* Pegel: schnell hoch, langsam runter */
    uint16_t peak = wave_peak;
    wave_peak = 0;
    uint8_t level = peak_to_wave_level(peak);
    level_smooth = (level > level_smooth) ? level : (uint8_t)(level_smooth * 7 / 10);
    Leds_Set_Level(level_smooth);

    /* Verbindung */
    if (SERVER_REACHABLE || PC_REACHABLE) {
        Leds_Set_Link(LED_LINK_TARGET);
    } else if (WIFI_CONNECTED) {
        Leds_Set_Link(LED_LINK_WIFI);
    } else {
        Leds_Set_Link(LED_LINK_LOCAL);
    }
    Leds_Set_Upload(upload_active, pending_uploads);

    /* Haltedruck zum Beenden: Ring fuellt sich */
    uint32_t held = Buttons_Held_Ms(KEY_1);
    uint32_t held_boot = Buttons_Held_Ms(KEY_BOOT);
    if (held_boot > held) held = held_boot;
    bool recording = (st == REC_RECORDING || st == REC_PAUSED);
    Leds_Set_Hold((recording && held > 150) ? (uint8_t)((held * 100) / BUTTONS_LONG_MS) : 0);

    /* Mikrofon: kein Datenstrom mehr */
    TickType_t tick = xTaskGetTickCount();
    bool mic_started = audio_first_ok_tick != 0;
    bool mic_stream_ok = audio_last_ok_tick != 0 && (tick - audio_last_ok_tick) < pdMS_TO_TICKS(1500);

    switch (st) {
    case REC_RECORDING:
        Leds_Set_Scene(LED_SCENE_RECORDING);
        break;
    case REC_PAUSED:
        Leds_Set_Scene(LED_SCENE_PAUSED);
        break;
    case REC_REQUESTED:
    case REC_STOP_REQUESTED:
    case REC_SAVING:
        Leds_Set_Scene(LED_SCENE_SAVING);
        break;
    case REC_DONE:
        if ((now - state_since_ms) < 2500) {
            Leds_Set_Scene(storage_full_stop ? LED_SCENE_FULL : LED_SCENE_DONE);
        } else {
            Leds_Set_Scene(LED_SCENE_IDLE);
        }
        break;
    case REC_ERROR:
        Leds_Set_Scene((now - state_since_ms) < 5000 ? LED_SCENE_ERROR : LED_SCENE_IDLE);
        break;
    case REC_IDLE:
    default:
        Leds_Set_Scene((mic_started && !mic_stream_ok) ? LED_SCENE_MIC_ERROR : LED_SCENE_IDLE);
        break;
    }
}

void app_main(void)
{
    Leds_Init();
    Leds_Set_Scene(LED_SCENE_BOOT);

    ESP_ERROR_CHECK(esp_board_init(16000, 2, 16));
    rec_enc_init();   /* grossen RAM-Block fuer den Encoder sichern, bevor WLAN ihn zerstueckelt */
    Buttons_Init(esp_ret_i2c_handle(), on_key);   /* richtet auch den IO-Expander ein (SD-DAT3 hoch) */
    Storage_Init();   /* SD-Karte, wenn eine steckt, sonst Flash */
    Wireless_Init();
    recording_counter_init();

    xTaskCreatePinnedToCore(audio_task, "audio", AUDIO_TASK_STACK, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(upload_manager_task, "upload_manager", 8192, NULL, 2, NULL, 0);

    printf("VERMERK bereit: KEY1/BOOT = Start (Halten = Stopp), KEY2 = Pause, KEY3 = Speicherstand\n");

    while (1) {
        update_leds();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}
