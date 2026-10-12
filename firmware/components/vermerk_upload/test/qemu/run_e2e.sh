#!/usr/bin/env bash
# Ende-zu-Ende-Test der Upload-Komponente: echter Firmware-Code (esp_http_client, mbedtls,
# vermerk_upload) in QEMU (ESP32) gegen den echten Empfang der Protokoll-Software - alles in EINEM
# Container. Empfang und Proxy lauschen nur auf 127.0.0.1 im Container, es wird kein Port nach
# aussen veroeffentlicht.
#
#   run_e2e.sh [<Ordner mit protokoll_assistent/> [<Ordner mit dem USB-Code der Anwendung>]]
#
# Ohne Angabe: das Repository, in dem dieses Skript liegt (so in der CI). Den Fall "Anwendung richtet ueber
# USB ein" (services/geraete_usb_service.py) gibt es nur, wenn dieser Code vorhanden ist.
# Lokal mit Docker, wenn der Empfang in einem anderen Arbeitsbaum liegt:
#   docker run --rm -v "<Firmware-Arbeitsbaum>:/project:ro" -v "<Empfang-Arbeitsbaum>:/empfang:ro" \
#     espressif/idf:v5.5.5 bash /project/firmware/components/vermerk_upload/test/qemu/run_e2e.sh /empfang
set -euo pipefail

HIER="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HIER/../../../../.." && pwd)"
EMPFANG_ROOT="${1:-$REPO}"
APP_ROOT="${2:-$EMPFANG_ROOT}"
BUILD="${E2E_BUILD:-/tmp/vermerk-e2e}"

if [ ! -f "$EMPFANG_ROOT/protokoll_assistent/services/geraete_empfang_service.py" ]; then
    echo "Empfang nicht gefunden: $EMPFANG_ROOT/protokoll_assistent/services/geraete_empfang_service.py" >&2
    exit 2
fi

# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" > /dev/null

# Build ausserhalb des Quellbaums (der darf schreibgeschuetzt eingebunden sein)
idf.py -C "$HIER" -B "$BUILD/app" -DSDKCONFIG="$BUILD/sdkconfig" build

python3 "$HIER/e2e_treiber.py" --empfang-root "$EMPFANG_ROOT" --build "$BUILD/app" --arbeit "$BUILD/lauf" --app-root "$APP_ROOT"
