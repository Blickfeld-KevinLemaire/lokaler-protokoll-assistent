#include "Opus_Encoder.h"

#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_heap_caps.h"
#include "esp_opus_enc.h"

static const char *TAG = "OPUS";

#define FRAME_SAMPLES        (OPUS_SAMPLE_RATE / 1000 * OPUS_FRAME_MS)   /* Samples je Frame (640) */
#define FRAME_GRANULE        (48000 / 1000 * OPUS_FRAME_MS)              /* Ogg zaehlt Opus immer in 48 kHz */
#define OPUS_PRE_SKIP        312                                         /* Encoder-Vorlauf in 48-kHz-Samples */

#define PAGE_MAX_SEGMENTS    200
#define PAGE_MAX_DATA        3072
#define PAGE_BUF_SIZE        (27 + 255 + PAGE_MAX_DATA)

static void *s_enc = NULL;
static FILE *s_file = NULL;

static int16_t *s_pcm = NULL;          /* ein Frame Eingangsdaten */
static int s_pcm_fill = 0;
static uint8_t *s_pkt = NULL;          /* Ausgangspuffer fuer ein Opus-Paket */
static int s_pkt_size = 0;

/* Ogg-Zustand */
static uint32_t s_serial = 0;
static uint32_t s_seq = 0;
static uint64_t s_granule = 0;         /* 48-kHz-Samples bis zum Ende des letzten Pakets */
static uint8_t s_seg[PAGE_MAX_SEGMENTS + 1];
static int s_nseg = 0;
static uint8_t s_data[PAGE_MAX_DATA];
static int s_data_len = 0;
static uint8_t s_page[PAGE_BUF_SIZE];

static int64_t s_encode_us = 0;
static int64_t s_audio_samples = 0;

/* CRC-32 nach Ogg-Vorgabe (Polynom 0x04C11DB7, ohne Spiegelung, Startwert 0) */
static uint32_t ogg_crc(const uint8_t *p, int len)
{
    uint32_t crc = 0;
    for (int i = 0; i < len; i++) {
        crc ^= (uint32_t)p[i] << 24;
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80000000u) ? (crc << 1) ^ 0x04C11DB7u : (crc << 1);
        }
    }
    return crc;
}

static void put_le32(uint8_t *p, uint32_t v)
{
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

static void put_le64(uint8_t *p, uint64_t v)
{
    put_le32(p, (uint32_t)v);
    put_le32(p + 4, (uint32_t)(v >> 32));
}

/* Sammelt die Pakete der aktuellen Seite als eine Seite in die Datei. */
static bool write_page(uint8_t header_type, uint64_t granule)
{
    int hdr = 27 + s_nseg;
    memcpy(s_page, "OggS", 4);
    s_page[4] = 0;                       /* Version */
    s_page[5] = header_type;             /* 0x02 = Anfang, 0x04 = Ende */
    put_le64(s_page + 6, granule);
    put_le32(s_page + 14, s_serial);
    put_le32(s_page + 18, s_seq++);
    put_le32(s_page + 22, 0);            /* CRC folgt */
    s_page[26] = (uint8_t)s_nseg;
    memcpy(s_page + 27, s_seg, s_nseg);
    memcpy(s_page + hdr, s_data, s_data_len);
    put_le32(s_page + 22, ogg_crc(s_page, hdr + s_data_len));

    bool ok = fwrite(s_page, 1, hdr + s_data_len, s_file) == (size_t)(hdr + s_data_len);
    s_nseg = 0;
    s_data_len = 0;
    return ok;
}

/* Ein Paket an die offene Seite anhaengen; Seite vorher schreiben, wenn sie voll wuerde. */
static bool add_packet(const uint8_t *pkt, int len)
{
    int need_seg = len / 255 + 1;
    if (s_nseg + need_seg > PAGE_MAX_SEGMENTS || s_data_len + len > PAGE_MAX_DATA) {
        if (!write_page(0, s_granule)) return false;
    }
    int rest = len;
    while (rest >= 255) {
        s_seg[s_nseg++] = 255;
        rest -= 255;
    }
    s_seg[s_nseg++] = (uint8_t)rest;
    memcpy(s_data + s_data_len, pkt, len);
    s_data_len += len;
    return true;
}

static bool write_header_pages(void)
{
    /* Seite 1: OpusHead (RFC 7845) */
    uint8_t head[19];
    memcpy(head, "OpusHead", 8);
    head[8] = 1;                         /* Version */
    head[9] = 1;                         /* Kanaele: Mono */
    head[10] = OPUS_PRE_SKIP & 0xFF;
    head[11] = OPUS_PRE_SKIP >> 8;
    put_le32(head + 12, OPUS_SAMPLE_RATE);
    head[16] = 0; head[17] = 0;          /* Ausgangspegel 0 dB */
    head[18] = 0;                        /* Kanalzuordnung: Mono/Stereo */
    s_nseg = 0; s_data_len = 0;
    if (!add_packet(head, sizeof(head)) || !write_page(0x02, 0)) return false;

    /* Seite 2: OpusTags */
    static const char vendor[] = "VERMERK-C6";
    uint8_t tags[8 + 4 + sizeof(vendor) - 1 + 4];
    memcpy(tags, "OpusTags", 8);
    put_le32(tags + 8, sizeof(vendor) - 1);
    memcpy(tags + 12, vendor, sizeof(vendor) - 1);
    put_le32(tags + 12 + sizeof(vendor) - 1, 0);   /* keine Kommentare */
    return add_packet(tags, sizeof(tags)) && write_page(0, 0);
}

static bool encode_frame(void)
{
    esp_audio_enc_in_frame_t in = {.buffer = (uint8_t *)s_pcm, .len = FRAME_SAMPLES * sizeof(int16_t)};
    esp_audio_enc_out_frame_t out = {.buffer = s_pkt, .len = s_pkt_size, .encoded_bytes = 0};

    int64_t t0 = esp_timer_get_time();
    esp_audio_err_t err = esp_opus_enc_process(s_enc, &in, &out);
    s_encode_us += esp_timer_get_time() - t0;
    s_audio_samples += FRAME_SAMPLES;
    if (err != ESP_AUDIO_ERR_OK) {
        ESP_LOGE(TAG, "Encoder-Fehler %d", (int)err);
        return false;
    }

    s_granule += FRAME_GRANULE;
    return out.encoded_bytes == 0 || add_packet(s_pkt, (int)out.encoded_bytes);
}

bool opus_enc_init(void)
{
    if (s_enc != NULL) return true;

    esp_opus_enc_config_t cfg = ESP_OPUS_ENC_CONFIG_DEFAULT();
    cfg.sample_rate = OPUS_SAMPLE_RATE;
    cfg.channel = ESP_AUDIO_MONO;
    cfg.bits_per_sample = ESP_AUDIO_BIT16;
    cfg.bitrate = OPUS_BITRATE_BPS;
    cfg.frame_duration = (OPUS_FRAME_MS == 20) ? ESP_OPUS_ENC_FRAME_DURATION_20_MS
                       : (OPUS_FRAME_MS == 40) ? ESP_OPUS_ENC_FRAME_DURATION_40_MS
                                               : ESP_OPUS_ENC_FRAME_DURATION_60_MS;
    cfg.application_mode = ESP_OPUS_ENC_APPLICATION_VOIP;   /* auf Sprache abgestimmt */
    cfg.complexity = OPUS_COMPLEXITY;
    cfg.enable_fec = false;
    cfg.enable_dtx = false;
    cfg.enable_vbr = true;

    size_t heap_before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    esp_audio_err_t err = esp_opus_enc_open(&cfg, sizeof(cfg), &s_enc);
    if (err != ESP_AUDIO_ERR_OK || s_enc == NULL) {
        ESP_LOGE(TAG, "Encoder nicht startbar (Fehler %d, frei %u Bytes, groesster Block %u Bytes)", (int)err,
                 (unsigned)heap_before, (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
        s_enc = NULL;
        return false;
    }

    int in_size = 0, out_size = 0;
    esp_opus_enc_get_frame_size(s_enc, &in_size, &out_size);
    if (in_size != FRAME_SAMPLES * (int)sizeof(int16_t)) {
        ESP_LOGE(TAG, "Unerwartete Frame-Groesse %d (erwartet %d)", in_size, FRAME_SAMPLES * 2);
    }
    s_pkt_size = out_size > 0 ? out_size : 1500;
    s_pcm = heap_caps_malloc(FRAME_SAMPLES * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    s_pkt = heap_caps_malloc(s_pkt_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (s_pcm == NULL || s_pkt == NULL) {
        ESP_LOGE(TAG, "Puffer: zu wenig Speicher");
        return false;
    }

    ESP_LOGI(TAG, "Encoder bereit: %d bit/s mono %d Hz, %d ms Frames, Komplexitaet %d, dauerhaft %u Bytes RAM",
             OPUS_BITRATE_BPS, OPUS_SAMPLE_RATE, OPUS_FRAME_MS, OPUS_COMPLEXITY,
             (unsigned)(heap_before - heap_caps_get_free_size(MALLOC_CAP_INTERNAL)));
    return true;
}

bool opus_enc_begin(FILE *f)
{
    if (!opus_enc_init()) return false;
    if (esp_opus_enc_reset(s_enc) != ESP_AUDIO_ERR_OK) return false;

    s_file = f;
    s_pcm_fill = 0;
    s_seq = 0;
    s_granule = 0;
    s_nseg = 0;
    s_data_len = 0;
    s_serial = esp_random();
    s_encode_us = 0;
    s_audio_samples = 0;

    if (!write_header_pages()) {
        s_file = NULL;
        return false;
    }
    return true;
}

bool opus_enc_push(const int16_t *mono, int count)
{
    if (s_enc == NULL || s_file == NULL) return false;

    while (count > 0) {
        int n = FRAME_SAMPLES - s_pcm_fill;
        if (n > count) n = count;
        memcpy(s_pcm + s_pcm_fill, mono, n * sizeof(int16_t));
        s_pcm_fill += n;
        mono += n;
        count -= n;

        if (s_pcm_fill == FRAME_SAMPLES) {
            s_pcm_fill = 0;
            if (!encode_frame()) return false;
        }
    }
    return true;
}

bool opus_enc_end(void)
{
    if (s_enc == NULL || s_file == NULL) return false;
    bool ok = true;

    /* Angefangenes Frame mit Stille auffuellen */
    if (s_pcm_fill > 0) {
        memset(s_pcm + s_pcm_fill, 0, (FRAME_SAMPLES - s_pcm_fill) * sizeof(int16_t));
        s_pcm_fill = 0;
        ok = encode_frame();
    }

    /* Letzte Seite mit Ende-Markierung (auch leer erlaubt) */
    if (ok) ok = write_page(0x04, s_granule);

    opus_enc_abort();
    return ok;
}

void opus_enc_abort(void)
{
    s_file = NULL;
    s_pcm_fill = 0;
    s_nseg = 0;
    s_data_len = 0;
}

int opus_enc_load_percent(void)
{
    if (s_audio_samples <= 0) return 0;
    int64_t audio_us = s_audio_samples * 1000000LL / OPUS_SAMPLE_RATE;
    return (int)(s_encode_us * 100 / audio_us);
}
