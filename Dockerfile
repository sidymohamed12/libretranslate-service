# syntax=docker/dockerfile:1
# ═══════════════════════════════════════════════════════════════════════
# LibreTranslate multi-architecture (amd64, arm64, s390x…), français ⇄ anglais
# ═══════════════════════════════════════════════════════════════════════
#
# L'image officielle libretranslate/libretranslate n'existe qu'en amd64/arm64.
# Ce Dockerfile construit la même image pour toutes les architectures ; sur
# s390x (IBM Z / LinuxONE), trois blocages sont levés (détails dans README.md) :
#
#  1. CTranslate2 (moteur d'inférence) n'a pas de wheel s390x
#     → compilé depuis les sources, avec OpenBLAS (pas de MKL hors x86).
#  2. s390x est big-endian ; CTranslate2 lit model.bin sans conversion
#     → les modèles téléchargés sont réécrits en big-endian au build
#       (scripts/ct2_big_endian.py).
#  3. minisbd (découpage en phrases) et PyMuPDF (traduction de PDF) exigent
#     onnxruntime, sans wheel s390x → minisbd remplacé par un découpage par
#     expressions régulières (minisbd-regex/), PyMuPDF par un module vide
#     (pymupdf-desactive/ ; traduction de fichiers désactivée).
#
# Sur amd64/arm64, CTranslate2 vient de sa wheel officielle et la conversion
# big-endian est sans effet : l'image est équivalente à l'officielle (sans la
# traduction de fichiers).
#
#   docker build -t <registre>/libretranslate-service:1.9.6 .        # architecture de la machine
#   docker buildx build --platform linux/amd64,linux/arm64,linux/s390x \
#       -t <registre>/libretranslate-service:1.9.6 --push .           # image multi-architecture
# ═══════════════════════════════════════════════════════════════════════

# Nom complet : évite que Buildah/Podman (OpenShift) essaie d'abord les registres Red Hat.
ARG PYTHON_IMAGE=docker.io/library/python:3.11.14-slim-bookworm

# ── Étape 1 : compilation ───────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS builder

ARG LIBRETRANSLATE_VERSION=v1.9.6
# argos-translate-lt 1.12.1 (dépendance de LibreTranslate 1.9.6) exige ctranslate2 >=4,<5.
ARG CTRANSLATE2_VERSION=v4.8.3
# auto : wheel officielle sur x86_64/aarch64, compilation ailleurs (cf. plus bas).
ARG CTRANSLATE2_SOURCE=auto
# Compilation seulement : Ruy apporte les calculs int8 (plus rapides, moins de
# mémoire) mais n'est pas validé sur s390x — désactivé, float32 par défaut.
ARG CTRANSLATE2_WITH_RUY=OFF

ARG DEBIAN_FRONTEND=noninteractive
# Réseau lent ou instable : délais et nouvelles tentatives plus généreux.
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN printf 'Acquire::Retries "10";\nAcquire::http::Timeout "300";\n' > /etc/apt/apt.conf.d/80reseau-lent \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
    build-essential cmake git pkg-config ca-certificates libopenblas-dev \
    libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# LibreTranslate, à l'emplacement attendu par son entrypoint (/app, venv dans /app/venv)
RUN for essai in 1 2 3 4 5; do \
    git clone --depth 1 --branch "${LIBRETRANSLATE_VERSION}" \
    https://github.com/LibreTranslate/LibreTranslate.git /app && break; \
    rm -rf /app; echo "échec ($essai/5), nouvel essai dans 30 s"; sleep 30; \
    done; test -f /app/VERSION
WORKDIR /app
RUN python -m venv venv && ./venv/bin/pip install --no-cache-dir --upgrade pip

# numpy 1.x (exigé par LibreTranslate sous Python ≤ 3.12) : wheel sur
# amd64/arm64, compilé depuis les sources ailleurs (s390x, ppc64le).
RUN ./venv/bin/pip install --no-cache-dir "numpy<2"

# CTranslate2, selon l'architecture (CTRANSLATE2_SOURCE=auto) :
# - x86_64, aarch64 : wheel officielle (MKL/oneDNN sur x86, Ruy sur ARM : int8, rapide) ;
# - autres (s390x, ppc64le…) : compilé depuis les sources avec OpenBLAS.
# Forcer avec --build-arg CTRANSLATE2_SOURCE=wheel ou =source.
# Compilation : seuls les sous-modules utiles au CPU sont clonés (spdlog, ruy si
# demandé, cpu_features sur x86) — jamais cutlass/thrust, propres au GPU et très lourds.
RUN set -eux; \
    reessayer() { for essai in 1 2 3 4 5; do "$@" && return 0; echo "échec ($essai/5), nouvel essai dans 30 s"; sleep 30; done; return 1; }; \
    arch="$(uname -m)"; mode="${CTRANSLATE2_SOURCE}"; \
    if [ "$mode" = auto ]; then \
    case "$arch" in x86_64|aarch64) mode=wheel ;; *) mode=source ;; esac; \
    fi; \
    mkdir -p /opt/ctranslate2/lib; \
    if [ "$mode" = wheel ]; then \
    ./venv/bin/pip install --no-cache-dir "ctranslate2==${CTRANSLATE2_VERSION#v}"; \
    else \
    case "$arch" in x86_64|aarch64) dispatch=ON ;; *) dispatch=OFF ;; esac; \
    reessayer git clone --depth 1 --branch "${CTRANSLATE2_VERSION}" \
    https://github.com/OpenNMT/CTranslate2.git /src/ctranslate2; \
    modules="third_party/spdlog"; \
    [ "${CTRANSLATE2_WITH_RUY}" = ON ] && modules="$modules third_party/ruy"; \
    [ "$arch" = x86_64 ] && modules="$modules third_party/cpu_features"; \
    reessayer git -C /src/ctranslate2 submodule update --init --depth 1 $modules; \
    cmake -S /src/ctranslate2 -B /src/ctranslate2/build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/opt/ctranslate2 \
    -DWITH_MKL=OFF \
    -DWITH_DNNL=OFF \
    -DWITH_OPENBLAS=ON \
    -DWITH_RUY="${CTRANSLATE2_WITH_RUY}" \
    -DOPENMP_RUNTIME=COMP \
    -DENABLE_CPU_DISPATCH="$dispatch" \
    -DBUILD_CLI=OFF; \
    cmake --build /src/ctranslate2/build --parallel "$(nproc)"; \
    cmake --install /src/ctranslate2/build; \
    cd /src/ctranslate2/python; \
    /app/venv/bin/pip install --no-cache-dir -r install_requirements.txt; \
    CTRANSLATE2_ROOT=/opt/ctranslate2 /app/venv/bin/pip install --no-cache-dir --no-build-isolation .; \
    fi; \
    echo "ctranslate2 ${CTRANSLATE2_VERSION} : $mode ($arch)" | tee /opt/ctranslate2/PROVENANCE

# Paquets de remplacement, installés AVANT LibreTranslate pour que pip
# considère ses dépendances satisfaites et n'aille pas chercher onnxruntime :
# - minisbd (même nom, même version que la dépendance figée) : découpage en phrases par regex ;
# - PyMuPDF : module vide, la traduction de fichiers PDF est désactivée.
COPY minisbd-regex /src/minisbd-regex
COPY pymupdf-desactive /src/pymupdf-desactive
RUN ./venv/bin/pip install --no-cache-dir /src/minisbd-regex /src/pymupdf-desactive

# lxml n'a pas de wheel s390x : il est compilé et a besoin de zlib (-lz).
# Couche volontairement placée ici, après la compilation de CTranslate2, pour
# ne pas invalider son cache (plusieurs heures sous QEMU).
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# LibreTranslate lui-même (mêmes commandes que son Dockerfile officiel)
RUN ./venv/bin/pip install --no-cache-dir Babel==2.12.1 \
    && ./venv/bin/python scripts/compile_locales.py \
    && ./venv/bin/pip install --no-cache-dir gunicorn==23.0.0 \
    && ./venv/bin/pip install --no-cache-dir . \
    && ./venv/bin/pip check \
    && ! ./venv/bin/pip show onnxruntime >/dev/null 2>&1 \
    && ./venv/bin/python -c "import ctranslate2, minisbd, argostranslate.translate; print('ctranslate2', ctranslate2.__version__)"

# ── Étape 2 : image d'exécution ─────────────────────────────────────────
FROM ${PYTHON_IMAGE}

ARG MODELES=fr,en
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends libopenblas0 libgomp1 libxml2 libxslt1.1 \
    && apt-get upgrade -qq -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/ctranslate2/lib /opt/ctranslate2/lib
RUN echo /opt/ctranslate2/lib > /etc/ld.so.conf.d/ctranslate2.conf && ldconfig

ENV HOME=/home/libretranslate
RUN addgroup --system --gid 1032 libretranslate \
    && adduser --system --uid 1032 --gid 1032 --home /home/libretranslate libretranslate \
    && mkdir -p /home/libretranslate/.local/share \
    && chown -R 1032:0 /home/libretranslate

COPY --from=builder --chown=1032:0 /app /app
COPY --chown=1032:0 scripts/ct2_big_endian.py /usr/local/bin/ct2_big_endian.py
WORKDIR /app

USER 1032

# Modèles inclus dans l'image (aucun téléchargement au démarrage, pod sans
# accès Internet), puis réécrits en big-endian si la machine l'est (s390x).
RUN ./venv/bin/python scripts/install_models.py --load_only_lang_codes "${MODELES}" \
    && ./venv/bin/python -I /usr/local/bin/ct2_big_endian.py /home/libretranslate/.local/share/argos-translate/packages

# Test de fumée sur l'architecture cible : un modèle mal converti ou un calcul
# faux (boutisme, OpenBLAS) fait échouer le build plutôt que la production.
RUN ./venv/bin/python -c "\
    import argostranslate.translate as t; \
    r = t.translate('Bonjour. La nouvelle ligne de bus ouvre lundi.', 'fr', 'en'); \
    print('fr→en :', r); \
    assert 'bus' in r.lower() and ('monday' in r.lower() or 'opens' in r.lower()), r"

# OpenShift lance les pods avec un UID arbitraire du groupe 0 (Kubernetes
# avec l'UID 1032, cf. kubernetes/deployment.yaml) : HOME, /app/db
# (clés d'API, métriques) et les caches doivent être accessibles en écriture au groupe.
USER 0
RUN chgrp -R 0 /home/libretranslate /app \
    && chmod -R g=u /home/libretranslate /app
USER 1032

# Valeurs par défaut adaptées à un service interne appelé par une application
# (surchargées dans kubernetes/configmap.yaml).
ENV LT_LOAD_ONLY=fr,en \
    LT_UPDATE_MODELS=false \
    LT_DISABLE_WEB_UI=true \
    LT_DISABLE_FILES_TRANSLATION=true \
    LT_CHAR_LIMIT=5000 \
    LT_BATCH_LIMIT=16 \
    LT_THREADS=2 \
    ARGOS_CHUNK_TYPE=MINISBD

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s \
    CMD ["./venv/bin/python", "scripts/healthcheck.py"]
ENTRYPOINT ["./scripts/entrypoint.sh"]
