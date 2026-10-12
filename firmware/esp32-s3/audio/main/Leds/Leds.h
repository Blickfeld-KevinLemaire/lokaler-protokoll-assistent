#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Der LED-Ring (7 LEDs) ist die einzige Anzeige dieses Geraets ohne Bildschirm. */
typedef enum {
    LED_SCENE_BOOT = 0,      /* weisser Punkt kreist: Geraet startet */
    LED_SCENE_IDLE,          /* ruhig atmend; Farbe zeigt die Verbindung */
    LED_SCENE_RECORDING,     /* rot, Pegelanzeige; mindestens eine LED immer an */
    LED_SCENE_PAUSED,        /* orange blinkend */
    LED_SCENE_SAVING,        /* weiss, kurz beim Speichern */
    LED_SCENE_DONE,          /* gruen: gespeichert */
    LED_SCENE_FULL,          /* orange/rot im Wechsel: Speicher voll, Aufnahme gespeichert */
    LED_SCENE_ERROR,         /* rot schnell blinkend: Aufnahme nicht moeglich/fehlgeschlagen */
    LED_SCENE_MIC_ERROR      /* violett blinkend: Mikrofon liefert nichts */
} led_scene_t;

typedef enum {
    LED_LINK_LOCAL = 0,      /* kein WLAN: blau */
    LED_LINK_WIFI,           /* WLAN, aber kein Empfaenger erreichbar: tuerkis */
    LED_LINK_TARGET          /* Empfaenger (PC/Server) erreichbar: gruen */
} led_link_t;

void Leds_Init(void);
void Leds_Set_Scene(led_scene_t scene);
void Leds_Set_Level(uint8_t percent);                 /* Aufnahmepegel 0..100 */
void Leds_Set_Link(led_link_t link);
void Leds_Set_Upload(bool active, uint32_t pending);  /* Upload laeuft / Anzahl offener Aufnahmen */
void Leds_Set_Hold(uint8_t percent);                  /* Taste wird gehalten (z. B. zum Stoppen): Ring fuellt sich, 0 = aus */
void Leds_Show_Storage(uint8_t used_percent, bool is_sd);   /* KEY3: ca. 3 s Fuellstand anzeigen */
void Leds_Flash(uint8_t r, uint8_t g, uint8_t b, uint32_t ms);   /* kurzes Aufblitzen als Tastenquittung */
