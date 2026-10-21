# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ARG UID=1000
ARG GID=1000

# mpv: reprodução; firefox-esr: necessário só para a fonte animesonlinecc;
# libpulse0: áudio via socket PulseAudio/PipeWire do host.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        mpv firefox-esr ca-certificates libpulse0 mesa-va-drivers libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g "$GID" ani && useradd -m -u "$UID" -g "$GID" -s /bin/bash ani \
    && mkdir -p /data /opt/selenium && chown ani:ani /data /opt/selenium

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=ani:ani . .

USER ani
ENV XDG_STATE_HOME=/data \
    SE_CACHE_PATH=/opt/selenium \
    PYTHONUNBUFFERED=1

# Baixa o geckodriver na construção, para o primeiro uso não depender do GitHub.
RUN sm="$(python -c 'import os,platform,selenium; arch = "linux-arm64" if platform.machine() in ("aarch64", "arm64") else "linux-x86_64"; print(os.path.join(os.path.dirname(selenium.__file__), "webdriver/common", arch, "selenium-manager"))')" \
    && "$sm" --browser firefox --cache-path /opt/selenium \
    || echo "aviso: geckodriver não pré-baixado"

VOLUME /data
ENTRYPOINT ["python", "/app/main.py"]
