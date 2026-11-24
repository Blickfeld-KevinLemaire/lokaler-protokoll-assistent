# Servermodus: Aufnahmen im Eingangsordner werden automatisch transkribiert und
# zusammengefasst (siehe protokoll_assistent/server/README.md).
#
# Standard ist ein reiner Prozessor-Build (klein, laeuft ueberall). Fuer eine
# NVIDIA-Grafikkarte baut 'docker-compose.gpu.yml' mit CUDA-Basis und den
# CUDA-Bibliotheken von PyTorch:
#   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

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
# Dienst
# ---------------------------------------------------------------------------
FROM ${BASIS_IMAGE}

# Index fuer PyTorch: CPU-Pakete (Standard) oder leer lassen fuer die CUDA-Pakete von PyPI.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

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
        python3 -m pip install --index-url "$TORCH_INDEX_URL" "torch~=2.11.0" "torchaudio~=2.11.0"; \
    fi \
    && python3 -m pip install -r /tmp/requirements-server.txt

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
    PROTOKOLL_AUSGANG=/daten/ausgang
RUN mkdir -p /daten/eingang /daten/ausgang /daten/intern /daten/modelle \
    && chmod -R a+rwX /daten /app/protokoll_assistent/einstellungen
USER 1000:1000

# Programmschnittstelle + Oberflaeche fuer Browser (Anmeldung noetig), Eingangsordner und -- falls in der
# Oberflaeche eingeschaltet -- Empfang fuer Aufnahmegeraete. Erster Admin:
#   docker compose exec protokoll python3 -m protokoll_assistent.api nutzer-anlegen <Name> --admin
EXPOSE 8780
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8780/api/gesundheit', timeout=4)"
CMD ["python3", "-m", "protokoll_assistent.api", "--rolle", "server"]
