#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Der C6 hat keine SD-Karte: Aufnahmen liegen in der FAT-Partition "storage" im Flash
 * (siehe partitions.csv), eingehaengt unter REC_DIR. */
#define REC_DIR   "/rec"
#define REC_EXT   "mp3"

extern bool g_storage_mounted;

void Storage_Init(void);                         /* beim ersten Start wird die Partition formatiert */
uint64_t Storage_Free_Bytes(void);               /* freier Platz in Bytes (0 bei Fehler) */
uint64_t Storage_Total_Bytes(void);
