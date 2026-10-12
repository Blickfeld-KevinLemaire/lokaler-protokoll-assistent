/* Erzeugt von antworten_erzeugen.py aus dem echten Empfang der Protokoll-Software
 * (protokoll_assistent/services/geraete_empfang_service.py). Nicht von Hand aendern. */
#pragma once

#define SW_HALLO_STATUS 200
#define SW_HALLO "{\"dienst\":\"protokoll-assistent\",\"schnittstelle\":1,\"geraet\":\"Vertrag\",\"teil_max_bytes\":4194304}"
#define SW_STATUS_NEU_STATUS 200
#define SW_STATUS_NEU "{\"naechstes_byte\":0,\"fertig\":false}"
#define SW_TEIL_ANGEHAENGT_STATUS 200
#define SW_TEIL_ANGEHAENGT "{\"naechstes_byte\":10,\"fertig\":false}"
#define SW_STATUS_TEILSTAND_STATUS 200
#define SW_STATUS_TEILSTAND "{\"naechstes_byte\":10,\"fertig\":false}"
#define SW_VERSATZ_409_STATUS 409
#define SW_VERSATZ_409 "{\"naechstes_byte\":10,\"fertig\":false,\"fehler\":\"X-Offset passt nicht zum Stand.\"}"
#define SW_ABSCHLUSS_FERTIG_STATUS 200
#define SW_ABSCHLUSS_FERTIG "{\"naechstes_byte\":10,\"fertig\":true,\"datei\":\"Vertrag_H5_007.opus\"}"
#define SW_ABSCHLUSS_DOPPELT_STATUS 200
#define SW_ABSCHLUSS_DOPPELT "{\"naechstes_byte\":10,\"fertig\":true,\"datei\":\"Vertrag_H5_007.opus\"}"
#define SW_ABSCHLUSS_GROESSE_422_STATUS 422
#define SW_ABSCHLUSS_GROESSE_422 "{\"naechstes_byte\":0,\"fertig\":false,\"fehler\":\"Groesse stimmt nicht (10 statt 11 Bytes).\"}"
#define SW_ABSCHLUSS_PRUEFSUMME_422_STATUS 422
#define SW_ABSCHLUSS_PRUEFSUMME_422 "{\"naechstes_byte\":0,\"fertig\":false,\"fehler\":\"Pruefsumme stimmt nicht.\"}"
#define SW_NAME_400_STATUS 400
#define SW_NAME_400 "{\"fehler\":\"Ungueltiger Dateiname.\"}"
#define SW_KOPF_400_STATUS 400
#define SW_KOPF_400 "{\"fehler\":\"Content-Length, X-Offset und X-Gesamtgroesse muessen Zahlen sein.\"}"
#define SW_PFAD_404_STATUS 404
#define SW_PFAD_404 "{\"fehler\":\"Unbekannter Pfad.\"}"
#define SW_TOKEN_401_STATUS 401
#define SW_TOKEN_401 "{\"fehler\":\"Token fehlt oder ist unbekannt.\"}"
#define SW_CHUNKED_411_STATUS 411
#define SW_CHUNKED_411 "{\"fehler\":\"Content-Length fehlt (Chunked Transfer wird nicht angenommen).\"}"
#define SW_ZU_GROSS_413_STATUS 413
#define SW_ZU_GROSS_413 "{\"fehler\":\"Ein Stueck darf hoechstens 4194304 Bytes haben.\"}"
#define SW_PLATTE_VOLL_507_STATUS 507
#define SW_PLATTE_VOLL_507 "{\"fehler\":\"Zu wenig Platz auf der Platte.\"}"
#define SW_STUECK_UNVOLLSTAENDIG_400_STATUS 400
#define SW_STUECK_UNVOLLSTAENDIG_400 "{\"naechstes_byte\":0,\"fertig\":false,\"fehler\":\"Das Stueck kam nicht vollstaendig an.\"}"
#define SW_UEBERLAST_503_STATUS 503
#define SW_UEBERLAST_503 "{\"fehler\":\"Zu viele gleichzeitige Verbindungen.\"}"
