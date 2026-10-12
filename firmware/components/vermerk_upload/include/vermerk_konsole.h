#pragma once

/* Einrichtung ueber USB: liest Anweisungen der Software ("#VERMERK ...") von der seriellen Konsole
 * (USB-Serial-JTAG auf S3/C6, UART0 z. B. in QEMU) und antwortet dort. Die normale Ausgabe (printf)
 * laeuft weiter ueber dieselbe Konsole. Ablauf: GERAETE-SCHNITTSTELLE.md, "Einrichtung ueber USB". */

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* true, solange eine Aufnahme laeuft: dann werden SPEICHERN und LOESCHEN abgelehnt (beide starten neu) */
typedef bool (*vermerk_aufnahme_laeuft_t)(void);

/* Einmal beim Start aufrufen, nach vermerk_konfig_laden(). Legt eine kleine Task an. */
void vermerk_konsole_starten(vermerk_aufnahme_laeuft_t aufnahme_laeuft);

#ifdef __cplusplus
}
#endif
