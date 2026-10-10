#pragma once

/* Aufnahmeformat des S3: Ogg-Opus (.opus), Mono, 16 kHz, auf der SD-Karte.
 * Aeltere Aufnahmen (.wav, Stereo) auf der Karte werden weiterhin hochgeladen. */
#include "Opus_Encoder.h"

#define REC_DIR                 "/sdcard"
#define REC_EXT                 "opus"
#define REC_EXT_LEGACY          "wav"
#define REC_SAMPLE_RATE         OPUS_SAMPLE_RATE
#define rec_enc_init            opus_enc_init
#define rec_enc_begin           opus_enc_begin
#define rec_enc_push            opus_enc_push
#define rec_enc_end             opus_enc_end
#define rec_enc_abort           opus_enc_abort
#define rec_enc_load_percent    opus_enc_load_percent
