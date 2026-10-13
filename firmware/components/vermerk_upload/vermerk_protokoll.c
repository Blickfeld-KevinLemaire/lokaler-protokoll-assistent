/* Reiner C-Teil der Geraete-Schnittstelle, siehe vermerk_protokoll.h. Keine ESP-IDF-Includes. */

#include "vermerk_protokoll.h"

#include <string.h>

/* ---- kleine Helfer (ohne Locale, ohne ctype: gleiches Verhalten auf PC und Geraet) ---- */

static bool ist_ziffer(char c)
{
    return c >= '0' && c <= '9';
}

static bool ist_buchstabe(char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

static char klein(char c)
{
    return (c >= 'A' && c <= 'Z') ? (char)(c - 'A' + 'a') : c;
}

/* Sucht "\"<schluessel>\":" in text[0..laenge), davor muss '{' oder ',' stehen.
 * Gibt die Position direkt hinter dem ':' zurueck, sonst NULL. */
static const char *finde_wert(const char *text, size_t laenge, const char *schluessel)
{
    if (text == NULL || schluessel == NULL) {
        return NULL;
    }
    size_t s_len = strlen(schluessel);
    if (s_len == 0) {
        return NULL;
    }
    size_t muster_len = s_len + 3;   /* "schluessel": */
    if (laenge < muster_len + 1) {
        return NULL;
    }

    for (size_t i = 1; i + muster_len <= laenge; i++) {
        if (text[i] != '"' || (text[i - 1] != '{' && text[i - 1] != ',')) {
            continue;
        }
        if (memcmp(text + i + 1, schluessel, s_len) == 0 &&
            text[i + 1 + s_len] == '"' &&
            text[i + 2 + s_len] == ':') {
            return text + i + muster_len;
        }
    }
    return NULL;
}

static bool ist_wertende(const char *p, const char *ende)
{
    return p < ende && (*p == ',' || *p == '}');
}

/* ---- Pruefungen ---- */

bool vermerk_name_gueltig(const char *name)
{
    static const char *const endungen[] = {".opus", ".ogg", ".wav", ".mp3"};

    if (name == NULL) {
        return false;
    }
    size_t stamm = 0;
    while (name[stamm] != '\0' && name[stamm] != '.') {
        char c = name[stamm];
        if (!ist_buchstabe(c) && !ist_ziffer(c) && c != '_' && c != '-') {
            return false;
        }
        stamm++;
        if (stamm > VERMERK_NAME_MAX_STAMM) {
            return false;
        }
    }
    if (stamm == 0 || name[stamm] != '.') {
        return false;
    }
    for (size_t e = 0; e < sizeof(endungen) / sizeof(endungen[0]); e++) {
        if (strcmp(name + stamm, endungen[e]) == 0) {
            return true;
        }
    }
    return false;
}

bool vermerk_token_gueltig(const char *token)
{
    if (token == NULL) {
        return false;
    }
    size_t n = 0;
    while (token[n] != '\0') {
        unsigned char c = (unsigned char)token[n];
        if (c <= 0x20 || c >= 0x7F) {   /* keine Steuerzeichen, kein Leerzeichen, kein Nicht-ASCII */
            return false;
        }
        n++;
        if (n > VERMERK_TOKEN_MAX) {
            return false;
        }
    }
    return n > 0;
}

bool vermerk_aufnahme_nummer(const char *dateiname, const char *endung, uint32_t *nummer)
{
    if (dateiname == NULL || endung == NULL || nummer == NULL) {
        return false;
    }
    if ((dateiname[0] != 'H' && dateiname[0] != 'h') || dateiname[1] != '5' || dateiname[2] != '_') {
        return false;
    }
    const char *p = dateiname + 3;
    uint32_t wert = 0;
    int ziffern = 0;
    while (ist_ziffer(*p)) {
        if (ziffern == 9) {
            return false;   /* hoechstens 9 Ziffern: kein Ueberlauf, Nummer + 1 passt immer */
        }
        wert = wert * 10u + (uint32_t)(*p - '0');
        ziffern++;
        p++;
    }
    if (ziffern == 0 || *p != '.') {
        return false;
    }
    p++;
    size_t e_len = strlen(endung);
    if (e_len == 0) {
        return false;
    }
    for (size_t i = 0; i < e_len; i++) {
        if (p[i] == '\0' || klein(p[i]) != klein(endung[i])) {
            return false;
        }
    }
    if (p[e_len] != '\0') {
        return false;
    }
    *nummer = wert;
    return true;
}

void vermerk_nummer_einfuegen(uint32_t *liste, int *anzahl, int max, uint32_t nummer)
{
    if (liste == NULL || anzahl == NULL || max <= 0 || *anzahl < 0 || *anzahl > max) {
        return;
    }
    int pos = 0;
    while (pos < *anzahl && liste[pos] < nummer) {
        pos++;
    }
    if (pos < *anzahl && liste[pos] == nummer) {
        return;   /* schon drin */
    }
    if (pos >= max) {
        return;   /* Liste voll und alle sind kleiner */
    }
    int letzte = (*anzahl < max) ? *anzahl : max - 1;   /* bei voller Liste faellt die groesste heraus */
    memmove(&liste[pos + 1], &liste[pos], (size_t)(letzte - pos) * sizeof(liste[0]));
    liste[pos] = nummer;
    if (*anzahl < max) {
        (*anzahl)++;
    }
}

/* ---- Antworten lesen ---- */

bool vermerk_json_zahl(const char *text, size_t laenge, const char *schluessel, uint64_t *wert)
{
    const char *p = finde_wert(text, laenge, schluessel);
    if (p == NULL || wert == NULL) {
        return false;
    }
    const char *ende = text + laenge;
    if (p >= ende || !ist_ziffer(*p)) {
        return false;   /* auch '-' und '+' landen hier */
    }
    if (*p == '0' && p + 1 < ende && ist_ziffer(p[1])) {
        return false;   /* fuehrende Null */
    }
    uint64_t v = 0;
    while (p < ende && ist_ziffer(*p)) {
        uint64_t ziffer = (uint64_t)(*p - '0');
        if (v > (UINT64_MAX - ziffer) / 10u) {
            return false;   /* Ueberlauf */
        }
        v = v * 10u + ziffer;
        p++;
    }
    if (!ist_wertende(p, ende)) {
        return false;   /* z. B. 1.5, 1e3, 12abc oder abgeschnitten */
    }
    *wert = v;
    return true;
}

int vermerk_json_wahrheitswert(const char *text, size_t laenge, const char *schluessel)
{
    const char *p = finde_wert(text, laenge, schluessel);
    if (p == NULL) {
        return -1;
    }
    const char *ende = text + laenge;
    size_t rest = (size_t)(ende - p);
    if (rest >= 4 && memcmp(p, "true", 4) == 0 && ist_wertende(p + 4, ende)) {
        return 1;
    }
    if (rest >= 5 && memcmp(p, "false", 5) == 0 && ist_wertende(p + 5, ende)) {
        return 0;
    }
    return -1;
}

bool vermerk_json_text(const char *text, size_t laenge, const char *schluessel, char *ziel, size_t ziel_groesse)
{
    if (ziel == NULL || ziel_groesse == 0) {
        return false;
    }
    ziel[0] = '\0';
    const char *p = finde_wert(text, laenge, schluessel);
    if (p == NULL) {
        return false;
    }
    const char *ende = text + laenge;
    if (p >= ende || *p != '"') {
        return false;
    }
    p++;
    size_t n = 0;
    while (p < ende && *p != '"') {
        char c = *p;
        if (!ist_buchstabe(c) && !ist_ziffer(c) && c != '_' && c != '-') {
            ziel[0] = '\0';
            return false;
        }
        if (n + 1 >= ziel_groesse) {
            ziel[0] = '\0';
            return false;   /* zu lang fuer den Puffer */
        }
        ziel[n++] = c;
        p++;
    }
    if (p >= ende || !ist_wertende(p + 1, ende)) {
        ziel[0] = '\0';
        return false;   /* nicht abgeschlossen oder nicht am Ende des Werts */
    }
    ziel[n] = '\0';
    return n > 0;
}

bool vermerk_json_promille(const char *text, size_t laenge, const char *schluessel, uint32_t *promille)
{
    const char *p = finde_wert(text, laenge, schluessel);
    if (p == NULL || promille == NULL) {
        return false;
    }
    const char *ende = text + laenge;
    if (p >= ende || !ist_ziffer(*p)) {
        return false;
    }
    uint32_t ganz = (uint32_t)(*p - '0');
    p++;
    if (p < ende && ist_ziffer(*p)) {
        return false;   /* keine zweistellige oder fuehrende-Null-Zahl: der Fortschritt ist 0 bis 1 */
    }
    uint32_t wert = ganz * 1000u;
    if (p < ende && *p == '.') {
        p++;
        uint32_t stelle = 100u;
        int stellen = 0;
        while (p < ende && ist_ziffer(*p)) {
            if (++stellen > 3) {
                return false;
            }
            wert += (uint32_t)(*p - '0') * stelle;
            stelle /= 10u;
            p++;
        }
        if (stellen == 0) {
            return false;   /* "1." */
        }
    }
    if (!ist_wertende(p, ende) || wert > 1000u) {
        return false;
    }
    *promille = wert;
    return true;
}

bool vermerk_hallo_pruefen(const char *text, size_t laenge, uint32_t *teil_max_bytes)
{
    static const char dienst[] = "\"protokoll-assistent\"";

    if (teil_max_bytes != NULL) {
        *teil_max_bytes = 0;
    }

    const char *p = finde_wert(text, laenge, "dienst");
    if (p == NULL) {
        return false;
    }
    const char *ende = text + laenge;
    size_t d_len = sizeof(dienst) - 1;
    if ((size_t)(ende - p) < d_len || memcmp(p, dienst, d_len) != 0 || !ist_wertende(p + d_len, ende)) {
        return false;
    }

    uint64_t version = 0;
    if (!vermerk_json_zahl(text, laenge, "schnittstelle", &version) || version != 1) {
        return false;
    }

    uint64_t teil = 0;
    if (teil_max_bytes != NULL && vermerk_json_zahl(text, laenge, "teil_max_bytes", &teil) &&
        teil > 0 && teil <= UINT32_MAX) {
        *teil_max_bytes = (uint32_t)teil;
    }
    return true;
}

uint32_t vermerk_teil_bytes(uint32_t teil_max_server)
{
    if (teil_max_server == 0 || teil_max_server >= VERMERK_TEIL_BYTES) {
        return VERMERK_TEIL_BYTES;
    }
    return teil_max_server;
}

bool vermerk_hex(const uint8_t *daten, size_t laenge, char *ziel, size_t ziel_groesse)
{
    static const char ziffern[] = "0123456789abcdef";

    if (ziel == NULL || ziel_groesse == 0) {
        return false;
    }
    if ((daten == NULL && laenge > 0) || laenge > (ziel_groesse - 1) / 2) {
        ziel[0] = '\0';
        return false;
    }
    for (size_t i = 0; i < laenge; i++) {
        ziel[2 * i] = ziffern[daten[i] >> 4];
        ziel[2 * i + 1] = ziffern[daten[i] & 0x0F];
    }
    ziel[2 * laenge] = '\0';
    return true;
}

bool vermerk_mac_hex(const uint8_t mac[6], char *ziel, size_t ziel_groesse)
{
    if (mac == NULL) {
        if (ziel != NULL && ziel_groesse > 0) {
            ziel[0] = '\0';
        }
        return false;
    }
    return vermerk_hex(mac, 6, ziel, ziel_groesse);
}

/* ---- Verarbeitungsstand ---- */

bool vermerk_status_pruefen(const char *text, size_t laenge, vermerk_status_t *status)
{
    static const struct {
        const char *name;
        vermerk_verarbeitung_t zustand;
    } zustaende[] = {
        {"empfang", VERMERK_VERARB_EMPFANG},
        {"wartet", VERMERK_VERARB_WARTET},
        {"transkription", VERMERK_VERARB_TRANSKRIPTION},
        {"auswertung", VERMERK_VERARB_AUSWERTUNG},
        {"fertig", VERMERK_VERARB_FERTIG},
        {"fehler", VERMERK_VERARB_FEHLER},
    };
    if (status == NULL) {
        return false;
    }
    status->zustand = VERMERK_VERARB_UNBEKANNT;
    status->fortschritt_prozent = -1;

    char name[24];
    if (!vermerk_json_text(text, laenge, "zustand", name, sizeof(name))) {
        return false;
    }
    for (size_t i = 0; i < sizeof(zustaende) / sizeof(zustaende[0]); i++) {
        if (strcmp(name, zustaende[i].name) == 0) {
            status->zustand = zustaende[i].zustand;
        }
    }
    uint32_t promille = 0;
    if (vermerk_json_promille(text, laenge, "fortschritt", &promille)) {
        status->fortschritt_prozent = (int)((promille + 5u) / 10u);   /* gerundet */
    }
    return true;
}

bool vermerk_verarbeitung_beendet(vermerk_verarbeitung_t zustand)
{
    return zustand == VERMERK_VERARB_FERTIG || zustand == VERMERK_VERARB_FEHLER;
}

const char *vermerk_verarbeitung_text(vermerk_verarbeitung_t zustand)
{
    switch (zustand) {
    case VERMERK_VERARB_EMPFANG:       return "empfang";
    case VERMERK_VERARB_WARTET:        return "wartet";
    case VERMERK_VERARB_TRANSKRIPTION: return "transkription";
    case VERMERK_VERARB_AUSWERTUNG:    return "auswertung";
    case VERMERK_VERARB_FERTIG:        return "fertig";
    case VERMERK_VERARB_FEHLER:        return "fehler";
    default:                           return "unbekannt";
    }
}

vermerk_statusabfrage_t vermerk_status_entscheiden(int http_status, const char *text, size_t laenge,
                                                   vermerk_status_t *status)
{
    if (status != NULL) {
        status->zustand = VERMERK_VERARB_UNBEKANNT;
        status->fortschritt_prozent = -1;
    }
    if (http_status == 200) {
        return vermerk_status_pruefen(text, laenge, status) ? VERMERK_STATUSABFRAGE_ZUSTAND
                                                              : VERMERK_STATUSABFRAGE_SPAETER;
    }
    if (http_status == 0 || http_status == 408 || http_status == 429 ||
        (http_status >= 500 && http_status <= 599)) {
        return VERMERK_STATUSABFRAGE_SPAETER;   /* Netz weg, Software ueberlastet: in ein paar Sekunden wieder */
    }
    /* 400, 401, 403, 404, Umleitungen, alles Unbekannte: Wiederholen aendert nichts (aeltere Software ohne
     * .../status, Token widerrufen). Sonst fragte das Geraet bis zur Hoechstdauer alle paar Sekunden. */
    return VERMERK_STATUSABFRAGE_ENDE;
}

/* ---- Senden waehrend der Aufnahme ---- */

vermerk_live_entscheidung_t vermerk_live_entscheiden(int http_status, const char *text, size_t laenge,
                                                     uint64_t bestaetigt, uint64_t geschrieben)
{
    vermerk_live_entscheidung_t e = {VERMERK_LIVE_SPAETER, 0};
    vermerk_entscheidung_t a = vermerk_entscheiden(VERMERK_PHASE_TEIL, http_status, text, laenge, true);

    switch (a.aktion) {
    case VERMERK_AKTION_WEITER_AB:
        /* Die Software kennt nur Stand N. Davor liegt nichts mehr im Ringpuffer (schon bestaetigt und
         * verworfen), dahinter gibt es nichts: Dann laesst sich die Luecke nicht fuellen. */
        if (a.naechstes_byte < bestaetigt || a.naechstes_byte > geschrieben) {
            e.aktion = VERMERK_LIVE_AUFGEBEN;
        } else {
            e.aktion = VERMERK_LIVE_WEITER;
            e.naechstes_byte = a.naechstes_byte;
        }
        break;
    case VERMERK_AKTION_SPAETER:
        e.aktion = VERMERK_LIVE_SPAETER;
        break;
    default:   /* AUFGEBEN (401, 413 ...), VON_VORN und FERTIG kommen hier nicht sinnvoll vor */
        e.aktion = VERMERK_LIVE_AUFGEBEN;
        break;
    }
    return e;
}

/* ---- Ablauf ---- */

static vermerk_entscheidung_t entscheidung(vermerk_aktion_t aktion, uint64_t naechstes_byte)
{
    vermerk_entscheidung_t e;
    e.aktion = aktion;
    e.naechstes_byte = naechstes_byte;
    return e;
}

vermerk_entscheidung_t vermerk_entscheiden(vermerk_phase_t phase, int http_status,
                                           const char *text, size_t laenge, bool von_vorn_versucht)
{
    uint64_t n = 0;
    bool hat_n = (text != NULL) && vermerk_json_zahl(text, laenge, "naechstes_byte", &n);

    switch (http_status) {
    case 200:
        if (phase == VERMERK_PHASE_ABSCHLUSS) {
            /* Nur ein geprueftes "fertig":true erlaubt das Loeschen. Ein Abschluss, der nicht
             * fertig meldet, ist unerwartet: nicht weiterbohren, spaeter neu ansetzen. */
            if (text != NULL && vermerk_json_wahrheitswert(text, laenge, "fertig") == 1) {
                return entscheidung(VERMERK_AKTION_FERTIG, 0);
            }
            return entscheidung(VERMERK_AKTION_SPAETER, 0);
        }
        /* Status und Teil: "fertig" zaehlt hier nicht (nichts geprueft), nur naechstes_byte */
        return hat_n ? entscheidung(VERMERK_AKTION_WEITER_AB, n) : entscheidung(VERMERK_AKTION_SPAETER, 0);

    case 409:   /* X-Offset passte nicht: ab dem gemeldeten Byte weiter */
        return hat_n ? entscheidung(VERMERK_AKTION_WEITER_AB, n) : entscheidung(VERMERK_AKTION_SPAETER, 0);

    case 422:   /* Groesse oder Pruefsumme falsch, Teilstand verworfen: einmal von vorn */
        return von_vorn_versucht ? entscheidung(VERMERK_AKTION_SPAETER, 0)
                                 : entscheidung(VERMERK_AKTION_VON_VORN, 0);

    case 0:     /* keine Antwort: Verbindung weg, Zeitueberschreitung */
    case 408:
    case 429:
    case 503:   /* zu viele gleichzeitige Verbindungen */
    case 507:   /* Platte voll */
        return entscheidung(VERMERK_AKTION_SPAETER, 0);

    default:
        if (http_status >= 500 && http_status <= 599) {
            return entscheidung(VERMERK_AKTION_SPAETER, 0);
        }
        /* 400, 401, 403, 404, 411, 413, Umleitungen, alles Unbekannte: Wiederholen aendert so
         * nichts (falsches Token, Datei zu gross, falsche Adresse). Die Datei bleibt liegen. */
        return entscheidung(VERMERK_AKTION_AUFGEBEN, 0);
    }
}

const char *vermerk_ergebnis_text(vermerk_ergebnis_t ergebnis)
{
    switch (ergebnis) {
    case VERMERK_ERGEBNIS_FERTIG:    return "fertig";
    case VERMERK_ERGEBNIS_SPAETER:   return "spaeter erneut";
    case VERMERK_ERGEBNIS_AUFGEBEN:  return "abgelehnt, spaeter erneut";
    case VERMERK_ERGEBNIS_KEIN_ZIEL: return "kein Ziel erreichbar";
    case VERMERK_ERGEBNIS_UNTERBROCHEN: return "unterbrochen";
    default:                         return "?";
    }
}

uint32_t vermerk_wartezeit_ms(uint32_t fehlversuche)
{
    if (fehlversuche == 0) {
        return 0;
    }
    uint32_t ms = VERMERK_WARTEZEIT_START_MS;
    for (uint32_t i = 1; i < fehlversuche; i++) {
        if (ms >= VERMERK_WARTEZEIT_MAX_MS / 2) {
            return VERMERK_WARTEZEIT_MAX_MS;
        }
        ms *= 2;
    }
    return ms < VERMERK_WARTEZEIT_MAX_MS ? ms : VERMERK_WARTEZEIT_MAX_MS;
}

/* ---- Warteliste ---- */

static int finde_eintrag(const vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art)
{
    for (int i = 0; i < VERMERK_WARTELISTE_PLAETZE; i++) {
        const vermerk_wartend_t *e = &liste->eintrag[i];
        if (e->fehlversuche > 0 && e->nummer == nummer && e->art == art) {
            return i;
        }
    }
    return -1;
}

void vermerk_warteliste_leeren(vermerk_warteliste_t *liste)
{
    if (liste != NULL) {
        memset(liste, 0, sizeof(*liste));
    }
}

uint32_t vermerk_warteliste_rest_ms(const vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art, uint64_t jetzt_ms)
{
    if (liste == NULL) {
        return 0;
    }
    int i = finde_eintrag(liste, nummer, art);
    if (i < 0 || jetzt_ms >= liste->eintrag[i].naechster_versuch_ms) {
        return 0;
    }
    uint64_t rest = liste->eintrag[i].naechster_versuch_ms - jetzt_ms;
    return rest > UINT32_MAX ? UINT32_MAX : (uint32_t)rest;
}

bool vermerk_warteliste_bereit(const vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art, uint64_t jetzt_ms)
{
    return vermerk_warteliste_rest_ms(liste, nummer, art, jetzt_ms) == 0;
}

void vermerk_warteliste_fehler(vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art,
                               vermerk_ergebnis_t ergebnis, uint64_t jetzt_ms)
{
    if (liste == NULL || (ergebnis != VERMERK_ERGEBNIS_SPAETER && ergebnis != VERMERK_ERGEBNIS_AUFGEBEN)) {
        return;
    }
    int i = finde_eintrag(liste, nummer, art);
    if (i < 0) {
        /* freien Platz suchen, sonst den Eintrag ersetzen, der am fruehesten wieder dran ist */
        int frei = -1;
        int fruehester = 0;
        for (int k = 0; k < VERMERK_WARTELISTE_PLAETZE; k++) {
            if (liste->eintrag[k].fehlversuche == 0) {
                frei = k;
                break;
            }
            if (liste->eintrag[k].naechster_versuch_ms < liste->eintrag[fruehester].naechster_versuch_ms) {
                fruehester = k;
            }
        }
        i = (frei >= 0) ? frei : fruehester;
        liste->eintrag[i].nummer = nummer;
        liste->eintrag[i].art = art;
        liste->eintrag[i].fehlversuche = 0;
    }

    vermerk_wartend_t *e = &liste->eintrag[i];
    if (e->fehlversuche < UINT8_MAX) {
        e->fehlversuche++;
    }
    uint32_t warte = (ergebnis == VERMERK_ERGEBNIS_AUFGEBEN) ? VERMERK_WARTEZEIT_MAX_MS
                                                              : vermerk_wartezeit_ms(e->fehlversuche);
    e->naechster_versuch_ms = jetzt_ms + warte;
}

void vermerk_warteliste_erfolg(vermerk_warteliste_t *liste, uint32_t nummer, uint8_t art)
{
    if (liste == NULL) {
        return;
    }
    int i = finde_eintrag(liste, nummer, art);
    if (i >= 0) {
        memset(&liste->eintrag[i], 0, sizeof(liste->eintrag[i]));
    }
}
