#pragma once

/* Aufnahmeformat des C6: Opus (.opus) oder MP3 (.mp3). Beide Encoder haben dieselbe Schnittstelle,
 * main.c nutzt nur die rec_enc_*-Namen. Umschalten durch REC_CODEC_OPUS 1 bzw. 0. */
#define REC_CODEC_OPUS   1

#if REC_CODEC_OPUS
#include "Opus_Encoder.h"
#define REC_EXT                 "opus"
#define REC_SAMPLE_RATE         OPUS_SAMPLE_RATE
#define rec_enc_init            opus_enc_init
#define rec_enc_begin           opus_enc_begin
#define rec_enc_push            opus_enc_push
#define rec_enc_end             opus_enc_end
#define rec_enc_abort           opus_enc_abort
#define rec_enc_load_percent    opus_enc_load_percent
#else
#include "MP3_Encoder.h"
#define REC_EXT                 "mp3"
#define REC_SAMPLE_RATE         MP3_SAMPLE_RATE
#define rec_enc_init            mp3_enc_init
#define rec_enc_begin           mp3_enc_begin
#define rec_enc_push            mp3_enc_push
#define rec_enc_end             mp3_enc_end
#define rec_enc_abort           mp3_enc_abort
#define rec_enc_load_percent    mp3_enc_load_percent
#endif
