#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Speicher fuer Aufnahmen. Beim Start wird zuerst eine SD-Karte versucht (/sdcard); ist keine
 * (lesbare) Karte gesteckt, wird im Flash aufgenommen (FAT-Partition "storage", /rec).
 * Der Upload sucht in allen eingehaengten Speichern, damit auch Aufnahmen vom jeweils anderen
 * Speicher noch hochgeladen werden (z. B. nach dem Einstecken einer Karte). */
#define REC_DIR_SD     "/sdcard"
#define REC_DIR_FLASH  "/rec"

extern bool g_storage_mounted;                   /* mindestens ein Speicher eingehaengt */

void Storage_Init(void);                         /* nach LCD_Init() aufrufen (gemeinsamer SPI-Bus) */
bool Storage_Is_Sd(void);                        /* Aufnahmen gehen auf die SD-Karte */
const char *Storage_Dir(void);                   /* Verzeichnis fuer neue Aufnahmen */
int Storage_Dir_Count(void);                     /* Anzahl eingehaengter Speicher (0..2) */
const char *Storage_Dir_At(int index);           /* Verzeichnis; Index 0 = aktiver Speicher */
uint64_t Storage_Free_Bytes(void);               /* freier Platz im aktiven Speicher (0 bei Fehler) */
uint64_t Storage_Total_Bytes(void);
