#include "MP3_Encoder.h"

#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "layer3.h"

static const char *TAG = "MP3";

/* Der Encoder wird einmal beim Start angelegt und bleibt im RAM: Spaeter ist der freie
 * Speicher durch WLAN und Display so zerstueckelt, dass kein grosser Block mehr zu haben waere. */
static shine_t s_shine = NULL;
static shine_config_t s_cfg;
static FILE *s_file = NULL;
static int s_pass_samples = 0;       /* Samples pro MP3-Frame (576 bei 16 kHz) */
static int16_t *s_pcm = NULL;        /* Sammelpuffer fuer ein Frame */
static int s_pcm_fill = 0;

static int64_t s_encode_us = 0;
static int64_t s_audio_samples = 0;

/* Kleiner Schreibpuffer: wenige groessere Schreibzugriffe schonen den Flash */
#define OUT_BUF_SIZE  4096
static uint8_t s_out[OUT_BUF_SIZE];
static int s_out_fill = 0;

static bool out_flush(void)
{
    if (s_out_fill == 0) return true;
    size_t n = fwrite(s_out, 1, s_out_fill, s_file);
    bool ok = (n == (size_t)s_out_fill);
    s_out_fill = 0;
    return ok;
}

static bool out_write(const uint8_t *data, int len)
{
    while (len > 0) {
        int room = OUT_BUF_SIZE - s_out_fill;
        int n = (len < room) ? len : room;
        memcpy(s_out + s_out_fill, data, n);
        s_out_fill += n;
        data += n;
        len -= n;
        if (s_out_fill == OUT_BUF_SIZE && !out_flush()) return false;
    }
    return true;
}

static bool encode_frame(const int16_t *pcm)
{
    int written = 0;
    int64_t t0 = esp_timer_get_time();
    unsigned char *mp3 = shine_encode_buffer_interleaved(s_shine, (int16_t *)pcm, &written);
    s_encode_us += esp_timer_get_time() - t0;
    s_audio_samples += s_pass_samples;
    return (written <= 0) || out_write(mp3, written);
}

bool mp3_enc_init(void)
{
    if (s_shine != NULL) return true;

    shine_set_config_mpeg_defaults(&s_cfg.mpeg);
    s_cfg.wave.channels = PCM_MONO;
    s_cfg.wave.samplerate = MP3_SAMPLE_RATE;
    s_cfg.mpeg.mode = MONO;
    s_cfg.mpeg.bitr = MP3_BITRATE_KBPS;

    if (shine_check_config(s_cfg.wave.samplerate, s_cfg.mpeg.bitr) < 0) {
        ESP_LOGE(TAG, "Bitrate %d kbit/s bei %d Hz nicht erlaubt", MP3_BITRATE_KBPS, MP3_SAMPLE_RATE);
        return false;
    }

    size_t heap_before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    s_shine = shine_initialise(&s_cfg);
    if (s_shine == NULL) {
        ESP_LOGE(TAG, "Encoder: zu wenig Speicher (frei %u Bytes, groesster Block %u Bytes)",
                 (unsigned)heap_before,
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
        return false;
    }
    s_pass_samples = shine_samples_per_pass(s_shine);
    s_pcm = heap_caps_malloc(s_pass_samples * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (s_pcm == NULL) {
        shine_close(s_shine);
        s_shine = NULL;
        return false;
    }
    ESP_LOGI(TAG, "Encoder bereit: %d kbit/s mono %d Hz, %d Samples/Frame, dauerhaft %u Bytes RAM",
             MP3_BITRATE_KBPS, MP3_SAMPLE_RATE, s_pass_samples,
             (unsigned)(heap_before - heap_caps_get_free_size(MALLOC_CAP_INTERNAL)));
    return true;
}

bool mp3_enc_begin(FILE *f)
{
    if (!mp3_enc_init()) return false;
    if (shine_restart(s_shine, &s_cfg) != 0) return false;

    s_file = f;
    s_pcm_fill = 0;
    s_out_fill = 0;
    s_encode_us = 0;
    s_audio_samples = 0;
    return true;
}

bool mp3_enc_push(const int16_t *mono, int count)
{
    if (s_shine == NULL || s_file == NULL) return false;

    while (count > 0) {
        int n = s_pass_samples - s_pcm_fill;
        if (n > count) n = count;
        memcpy(s_pcm + s_pcm_fill, mono, n * sizeof(int16_t));
        s_pcm_fill += n;
        mono += n;
        count -= n;

        if (s_pcm_fill == s_pass_samples) {
            s_pcm_fill = 0;
            if (!encode_frame(s_pcm)) return false;
        }
    }
    return true;
}

bool mp3_enc_end(void)
{
    if (s_shine == NULL || s_file == NULL) return false;
    bool ok = true;

    /* Angefangenes Frame mit Stille auffuellen */
    if (s_pcm_fill > 0) {
        memset(s_pcm + s_pcm_fill, 0, (s_pass_samples - s_pcm_fill) * sizeof(int16_t));
        ok = encode_frame(s_pcm);
        s_pcm_fill = 0;
    }

    int written = 0;
    unsigned char *tail = shine_flush(s_shine, &written);
    if (ok && written > 0) ok = out_write(tail, written);
    if (ok) ok = out_flush();

    mp3_enc_abort();
    return ok;
}

void mp3_enc_abort(void)
{
    /* Der Encoder selbst bleibt im RAM, nur die Datei wird losgelassen */
    s_file = NULL;
    s_out_fill = 0;
    s_pcm_fill = 0;
}

int mp3_enc_load_percent(void)
{
    if (s_audio_samples <= 0) return 0;
    int64_t audio_us = s_audio_samples * 1000000LL / MP3_SAMPLE_RATE;
    return (int)(s_encode_us * 100 / audio_us);
}
