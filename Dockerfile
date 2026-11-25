# Servermodus: Aufnahmen im Eingangsordner werden automatisch transkribiert und
# zusammengefasst (siehe protokoll_assistent/server/README.md).
#
# Standard ist ein reiner Prozessor-Build (klein, laeuft ueberall). Fuer eine
# Grafikkarte gibt es je Hersteller eine Zusatzdatei, die dieses Image mit den
# passenden Build-Argumenten baut und die Karte in die Container reicht.
# './grafikkarte-erkennen.sh' waehlt sie selbst (COMPOSE_FILE in der .env); von Hand:
#   NVIDIA: docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
#   AMD:    docker compose -f docker-compose.yml -f docker-compose.amd.yml up -d --build
#   Intel:  docker compose -f docker-compose.yml -f docker-compose.intel.yml up -d --build
# Mit einer Grafikkarte startet der Dienst nur, wenn er sie auch nutzen kann
# (PROTOKOLL_GRAFIKKARTE_PFLICHT, siehe services/grafikkarte_service.py).

ARG BASIS_IMAGE=ubuntu:22.04

# ---------------------------------------------------------------------------
# Oberflaeche (SvelteKit, statisch gebaut). Der Dienst liefert sie an Browser aus.
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS oberflaeche
WORKDIR /bau
COPY oberflaeche/package.json oberflaeche/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY oberflaeche/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# CTranslate2 mit CUDA fuer ARM64 (z. B. NVIDIA DGX Spark, GH200). Die Pakete auf
# PyPI sind fuer aarch64 nur fuer den Prozessor gebaut -- Whisper liefe dort
# still auf der CPU. Nur bei GRAFIKKARTE=nvidia auf arm64 wird hier aus dem
# Quelltext gebaut (dauert einige Minuten); sonst bleibt die Stufe leer.
# ---------------------------------------------------------------------------
FROM ${BASIS_IMAGE} AS ctranslate2
ARG GRAFIKKARTE=keine
ARG TARGETARCH
ARG CTRANSLATE2_VERSION=4.9.0
# Rechenfaehigkeiten, fuer die gebaut wird: GH200 (90), GB200 (100), DGX Spark/GB10 (121). CMake-Schreibweise
# (CMAKE_CUDA_ARCHITECTURES); ohne Angabe baute CTranslate2 nur fuer 52.
ARG CTRANSLATE2_CUDA_ARCH="90;100;121"
# Das Basis-Image haelt cuBLAS und cuDNN fest (apt-mark hold); die Entwicklerpakete kommen deshalb in genau
# dieser Fassung dazu (dpkg-query).
RUN mkdir -p /opt/ctranslate2/lib /opt/ctranslate2/raeder \
    && if [ "$GRAFIKKARTE" = "nvidia" ] && [ "$TARGETARCH" = "arm64" ]; then \
        set -eux; \
        cuda="$(echo "$CUDA_VERSION" | cut -d. -f1-2 | tr . -)"; \
        cublas="$(dpkg-query -W -f='${Version}' "libcublas-$cuda")"; \
        cudnn="$(dpkg-query -W -f='${Version}' "libcudnn9-cuda-${cuda%%-*}")"; \
        apt-get update; \
        apt-get install -y --no-install-recommends git g++ make python3 python3-dev python3-pip \
            "cuda-nvcc-$cuda" "cuda-cudart-dev-$cuda" "cuda-cccl-$cuda" "libcurand-dev-$cuda" \
            "libcublas-dev-$cuda=$cublas" \
            "libcudnn9-dev-cuda-${cuda%%-*}=$cudnn" "libcudnn9-headers-cuda-${cuda%%-*}=$cudnn"; \
        python3 -m pip install --upgrade pip "cmake<4"; \
        git clone --depth 1 --recursive --branch "v$CTRANSLATE2_VERSION" https://github.com/OpenNMT/CTranslate2.git /bau; \
        cmake -S /bau -B /bau/build -DCMAKE_BUILD_TYPE=Release -DBUILD_CLI=OFF \
            -DWITH_MKL=OFF -DWITH_RUY=ON -DOPENMP_RUNTIME=COMP \
            -DWITH_CUDA=ON -DWITH_CUDNN=ON -DCUDA_DYNAMIC_LOADING=ON -DCMAKE_CUDA_ARCHITECTURES="$CTRANSLATE2_CUDA_ARCH" \
            -DCMAKE_INSTALL_PREFIX=/opt/ctranslate2; \
        cmake --build /bau/build -j"$(nproc)"; \
        cmake --install /bau/build; \
        cd /bau/python; \
        python3 -m pip install -r install_requirements.txt; \
        CTRANSLATE2_ROOT=/opt/ctranslate2 python3 -m pip wheel . --no-deps -w /opt/ctranslate2/raeder; \
        rm -rf /bau /var/lib/apt/lists/*; \
    fi

# ---------------------------------------------------------------------------
# Dienst
# ---------------------------------------------------------------------------
FROM ${BASIS_IMAGE}

# Index fuer PyTorch: CPU-Pakete (Standard), CUDA 12.8 (NVIDIA, docker-compose.gpu.yml), CUDA 12.9 (NVIDIA auf
# ARM64) oder ROCm 7.2 (AMD). Leer: PyPI -- dort ist es CUDA 13 und braucht einen Treiber ab 580.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
# Fuer welche Grafikkarte das Image gebaut wird: keine | nvidia | amd | intel. Daraus folgt, welche Schritte
# auf der Karte laufen muessen (grafikkarte_service.ERWARTUNGEN).
ARG GRAFIKKARTE=keine
# Nur AMD: CTranslate2 mit ROCm von der Release-Seite (PyPI hat nur CPU und CUDA). Dieselbe Fassung wie fuer
# die Windows-Anwendung (services/rocm_laufzeit_service.py); bei einer neuen Fassung URL und SHA-256 zusammen
# aendern.
ARG CTRANSLATE2_ROCM_URL=https://github.com/OpenNMT/CTranslate2/releases/download/v4.9.0/rocm-python-wheels-Linux.zip
ARG CTRANSLATE2_ROCM_SHA256=0a9ad24145fe671628d7524602241b3743a12d1487489f075f5de91f68aa2837

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ffmpeg ca-certificates libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY protokoll_assistent/requirements-server.txt /tmp/requirements-server.txt
# Das pip von Ubuntu 22.04 (22.0.2) bricht bei dieser Paketmenge mit einem
# AssertionError im Aufloeser ab -- deshalb zuerst ein aktuelles pip.
RUN python3 -m pip install --upgrade pip \
    && if [ -n "$TORCH_INDEX_URL" ]; then \
        python3 -m pip install --index-url "$TORCH_INDEX_URL" "torch~=2.11.0" "torchaudio==2.11.0"; \
    fi \
    && python3 -m pip install -r /tmp/requirements-server.txt

COPY tools/ctranslate2_rocm_einbauen.py /tmp/ctranslate2_rocm_einbauen.py
RUN if [ "$GRAFIKKARTE" = "amd" ]; then \
        python3 /tmp/ctranslate2_rocm_einbauen.py "$CTRANSLATE2_ROCM_URL" "$CTRANSLATE2_ROCM_SHA256"; \
    fi \
    && rm /tmp/ctranslate2_rocm_einbauen.py

# NVIDIA auf ARM64: das selbst gebaute CTranslate2 ersetzt das von PyPI (sonst ist die Stufe leer).
COPY --from=ctranslate2 /opt/ctranslate2 /opt/ctranslate2
RUN if ls /opt/ctranslate2/raeder/*.whl >/dev/null 2>&1; then \
        python3 -m pip install --no-deps --force-reinstall /opt/ctranslate2/raeder/*.whl \
        && echo /opt/ctranslate2/lib > /etc/ld.so.conf.d/ctranslate2.conf && ldconfig; \
    fi \
    && rm -rf /opt/ctranslate2/raeder

COPY protokoll_assistent /app/protokoll_assistent
COPY --from=oberflaeche /bau/build /app/oberflaeche/build

# Daten liegen in Volumes unter /daten; der Dienst laeuft ohne Root-Rechte.
# Die Modelle (Hugging Face) und die Zwischenstaende gehoeren ebenfalls dorthin.
# Der Benutzer aus 'user:' in der docker-compose.yml hat keinen Eintrag in /etc/passwd:
# PyTorch fragt dann 'getpass.getuser()' und bricht mit einem KeyError ab, solange
# USER/LOGNAME nicht gesetzt sind. HOME zeigt auf einen beschreibbaren Ort.
ENV USER=protokoll \
    LOGNAME=protokoll \
    HOME=/daten/intern \
    PROTOKOLL_DATEN_DIR=/daten/intern \
    VERMERK_ANWENDUNGSORDNER=/daten/intern \
    HF_HOME=/daten/modelle \
    PROTOKOLL_EINGANG=/daten/eingang \
    PROTOKOLL_AUSGANG=/daten/ausgang \
    PROTOKOLL_GRAFIKKARTE=${GRAFIKKARTE}
RUN mkdir -p /daten/eingang /daten/ausgang /daten/intern /daten/modelle \
    && chmod -R a+rwX /daten /app/protokoll_assistent/einstellungen
USER 1000:1000

# Programmschnittstelle + Oberflaeche fuer Browser (Anmeldung noetig), Eingangsordner und -- falls in der
# Oberflaeche eingeschaltet -- Empfang fuer Aufnahmegeraete. Erster Admin:
#   docker compose exec protokoll python3 -m protokoll_assistent.api nutzer-anlegen <Name> --admin
# Grafikkarte pruefen:
#   docker compose exec protokoll python3 -m protokoll_assistent.api grafikkarte-pruefen
EXPOSE 8780
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8780/api/gesundheit', timeout=4)"
CMD ["python3", "-m", "protokoll_assistent.api", "--rolle", "server"]
