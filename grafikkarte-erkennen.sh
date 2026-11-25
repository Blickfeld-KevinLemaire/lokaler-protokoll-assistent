#!/usr/bin/env bash
# Erkennt die Grafikkarte dieses Rechners und traegt die passenden Compose-Dateien
# in die .env ein. Danach startet ein einfaches 'docker compose up -d --build'
# den Servermodus mit der richtigen Karte (Compose liest COMPOSE_FILE aus der .env).
#
#   ./grafikkarte-erkennen.sh                  erkennen und .env schreiben
#   ./grafikkarte-erkennen.sh --anzeigen       nur anzeigen, nichts schreiben
#   ./grafikkarte-erkennen.sh --karte amd      Wahl vorgeben (nvidia, amd, intel, keine)
#
# Vorrang bei mehreren Karten: NVIDIA, dann AMD, dann Intel. Eine Karte, die
# erkannt wird, aber nicht nutzbar ist (Treiber oder Container Toolkit fehlt),
# ist ein Fehler -- das Skript schreibt dann nichts, statt still die
# Prozessor-Fassung einzutragen. Ob die Karte im Container wirklich rechnet,
# prueft der Dienst beim Start selbst (siehe protokoll_assistent/server/README.md).
#
# Fuer die Tests lassen sich die Pfade umlenken: GRAFIKKARTE_SYS (sonst /sys),
# GRAFIKKARTE_DEV (sonst /dev), GRAFIKKARTE_ARCH (sonst uname -m),
# GRAFIKKARTE_ENV (sonst .env), GRAFIKKARTE_OS (sonst uname -s), GRAFIKKARTE_GRUPPEN (sonst /etc/group),
# GRAFIKKARTE_OHNE_PROGRAMME=1 (nvidia-smi und nvidia-ctk nicht suchen).
set -eu

cd "$(dirname "$0")"
SYS="${GRAFIKKARTE_SYS:-/sys}"
DEV="${GRAFIKKARTE_DEV:-/dev}"
ARCH="${GRAFIKKARTE_ARCH:-$(uname -m)}"
SYSTEM="${GRAFIKKARTE_OS:-$(uname -s)}"
ENV_DATEI="${GRAFIKKARTE_ENV:-.env}"
GRUPPEN="${GRAFIKKARTE_GRUPPEN:-/etc/group}"
OHNE_PROGRAMME="${GRAFIKKARTE_OHNE_PROGRAMME:-0}"

anzeigen=0
vorgabe=""
while [ $# -gt 0 ]; do
    case "$1" in
        --anzeigen) anzeigen=1 ;;
        --karte)
            shift
            vorgabe="${1:-}"
            ;;
        -h | --help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unbekannte Angabe: $1 (siehe --help)" >&2
            exit 2
            ;;
    esac
    shift
done
case "$vorgabe" in
    "" | nvidia | amd | intel | keine) ;;
    *)
        echo "--karte: '$vorgabe' ist unbekannt (nvidia, amd, intel, keine)." >&2
        exit 2
        ;;
esac

fehler() {
    echo "FEHLER: $*" >&2
    echo "Die .env wurde nicht geaendert." >&2
    exit 1
}

programm_da() {
    [ "$OHNE_PROGRAMME" != "1" ] && command -v "$1" >/dev/null 2>&1
}

# Hersteller aller Grafikkarten: PCI-Geraete der Klasse "Anzeige" (0x03....) und die Karten unter
# /sys/class/drm. Beides, weil der NVIDIA-Treiber ohne nvidia_drm keinen DRM-Eintrag anlegt und
# Grafik in einem System-on-Chip nicht immer am PCI-Bus haengt.
hersteller_ids() {
    for geraet in "$SYS"/bus/pci/devices/*; do
        [ -f "$geraet/class" ] && [ -f "$geraet/vendor" ] || continue
        case "$(cat "$geraet/class")" in
            0x03*) cat "$geraet/vendor" ;;
        esac
    done
    for karte in "$SYS"/class/drm/card*; do
        case "${karte##*/}" in *-*) continue ;; esac # Anschluesse wie card0-HDMI-A-1
        [ -f "$karte/device/vendor" ] && cat "$karte/device/vendor"
    done
    return 0
}

ids="$(hersteller_ids 2>/dev/null | tr 'A-F' 'a-f' | sort -u)"
nvidia=0
amd=0
intel=0
case "$ids" in *0x10de*) nvidia=1 ;; esac
case "$ids" in *0x1002*) amd=1 ;; esac
case "$ids" in *0x8086*) intel=1 ;; esac
# Windows (Docker Desktop) und Rechner ohne nvidia_drm: nvidia-smi kennt die Karte trotzdem.
if [ "$nvidia" = 0 ] && programm_da nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
    nvidia=1
fi

gefunden=""
[ "$nvidia" = 1 ] && gefunden="$gefunden NVIDIA"
[ "$amd" = 1 ] && gefunden="$gefunden AMD"
[ "$intel" = 1 ] && gefunden="$gefunden Intel"
echo "Grafikkarten auf diesem Rechner:${gefunden:- keine}"
echo "Prozessor-Architektur: $ARCH"

if [ -n "$vorgabe" ]; then
    karte="$vorgabe"
    echo "Vorgegeben: $karte"
elif [ "$nvidia" = 1 ]; then
    karte=nvidia
elif [ "$amd" = 1 ]; then
    karte=amd
elif [ "$intel" = 1 ]; then
    karte=intel
else
    karte=keine
fi

windows=0
case "$SYSTEM" in MINGW* | MSYS* | CYGWIN*) windows=1 ;; esac

dateien="docker-compose.yml"
video_gid=""
render_gid=""
case "$karte" in
    nvidia)
        # Docker Desktop (Windows) bringt die Anbindung selbst mit; unter Linux braucht es das Toolkit.
        if [ "$windows" = 0 ] && [ "$OHNE_PROGRAMME" != "1" ] \
            && ! programm_da nvidia-ctk && ! programm_da nvidia-container-cli; then
            fehler "NVIDIA-Karte gefunden, aber das NVIDIA Container Toolkit fehlt. Installieren:
  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
und das Skript danach noch einmal ausfuehren."
        fi
        dateien="$dateien:docker-compose.gpu.yml"
        case "$ARCH" in aarch64 | arm64) dateien="$dateien:docker-compose.gpu-arm.yml" ;; esac
        ;;
    amd)
        [ -e "$DEV/kfd" ] || fehler "AMD-Karte gefunden, aber $DEV/kfd fehlt: Der amdgpu-Treiber des Kernels
laeuft ohne Rechenschnittstelle (KFD). Kernel und Treiber pruefen (siehe server/README.md, Grafikkarten)."
        render="$(ls "$DEV"/dri/renderD* 2>/dev/null | head -n 1)"
        [ -n "$render" ] || fehler "AMD-Karte gefunden, aber $DEV/dri/renderD* fehlt."
        # Gruppen genau der Geraete, die der Container braucht -- die Nummern unterscheiden sich je Distribution.
        # Compose verlangt zwei verschiedene Eintraege in 'group_add'. Gehoeren /dev/kfd und renderD* derselben
        # Gruppe (Fedora, neuere Ubuntu: beide 'render'), kommt als zweite die der Karte bzw. 'video' dazu.
        render_gid="$(stat -c %g "$render")"
        video_gid=""
        for kandidat in "$(stat -c %g "$DEV/kfd")" \
            "$(stat -c %g "$DEV"/dri/card[0-9]* 2>/dev/null | head -n 1)" \
            "$(awk -F: '$1 == "video" { print $3 }' "$GRUPPEN" 2>/dev/null)"; do
            if [ -n "$kandidat" ] && [ "$kandidat" != "$render_gid" ]; then
                video_gid="$kandidat"
                break
            fi
        done
        [ -n "$video_gid" ] || fehler "Fuer VIDEO_GID fand sich keine zweite Gruppe neben $render_gid
(weder /dev/kfd noch /dev/dri/card* noch die Gruppe 'video'). Bitte in der .env von Hand setzen."
        dateien="$dateien:docker-compose.amd.yml"
        ;;
    intel)
        ls "$DEV"/dri/renderD* >/dev/null 2>&1 || fehler "Intel-Grafik gefunden, aber $DEV/dri/renderD* fehlt
(Treiber i915 oder xe nicht geladen)."
        dateien="$dateien:docker-compose.intel.yml"
        ;;
esac

echo
echo "Gewaehlt: $karte"
echo "  COMPOSE_FILE=$dateien"
[ -n "$video_gid" ] && echo "  VIDEO_GID=$video_gid  RENDER_GID=$render_gid"
case "$karte" in
    intel) echo "  (Transkription und Sprechertrennung rechnen bei Intel auf dem Prozessor, die Zusammenfassung auf der Karte.)" ;;
    keine) echo "  (Alles rechnet auf dem Prozessor.)" ;;
esac
if programm_da getenforce && [ "$(getenforce 2>/dev/null)" = "Enforcing" ]; then
    echo "  SELinux ist aktiv; die Compose-Dateien setzen ':z' bzw. 'label:disable' bereits."
fi

if [ "$anzeigen" = 1 ]; then
    echo
    echo "--anzeigen: .env nicht geaendert."
    exit 0
fi

if [ ! -f "$ENV_DATEI" ]; then
    if [ -f .env.beispiel ]; then
        cp .env.beispiel "$ENV_DATEI"
        echo
        echo "$ENV_DATEI aus .env.beispiel angelegt -- HF_TOKEN dort noch eintragen."
    else
        : >"$ENV_DATEI"
    fi
fi

setze() {
    if grep -q "^$1=" "$ENV_DATEI"; then
        sed -i "s|^$1=.*|$1=$2|" "$ENV_DATEI"
    else
        printf '%s=%s\n' "$1" "$2" >>"$ENV_DATEI"
    fi
}

# ':' als Trenner, auch unter Windows (dort waere sonst ';' Vorgabe).
setze COMPOSE_PATH_SEPARATOR ":"
setze COMPOSE_FILE "$dateien"
if [ -n "$video_gid" ]; then
    setze VIDEO_GID "$video_gid"
    setze RENDER_GID "$render_gid"
fi

echo
echo "$ENV_DATEI aktualisiert. Starten mit:"
echo "  docker compose up -d --build"
echo "Danach pruefen, ob alles auf der Karte rechnet:"
echo "  docker compose exec protokoll python3 -m protokoll_assistent.api grafikkarte-pruefen"
