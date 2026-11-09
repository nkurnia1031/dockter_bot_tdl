ARG TME3BOT_BASE_IMAGE=tme3bot-base:py310-tdl0203
FROM ${TME3BOT_BASE_IMAGE} AS runtime-base

WORKDIR /app

# Install application dependencies in the application image as well as the
# optional immutable base so an existing base image cannot omit new packages.
COPY requirements.txt /tmp/tme3bot-requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/tme3bot-requirements.txt \
    && rm -f /tmp/tme3bot-requirements.txt

# The base image contains Python dependencies, tdl, and the fixed Go helper.
# Copy application source after dependency installation so source-only updates
# preserve the expensive dependency layers in the gateway and worker images.
FROM runtime-base AS gateway
COPY requirements-verifier.txt /tmp/requirements-verifier.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements-verifier.txt \
    && rm -f /tmp/requirements-verifier.txt
COPY bot.py /app/bot.py
COPY pkg_resources.py /app/pkg_resources.py
COPY tools/verify_profile_backup.py /app/tools/verify_profile_backup.py
COPY tme3bot /app/tme3bot
COPY utility /app/utility
CMD ["python3", "/app/bot.py"]

FROM runtime-base AS worker
ARG ARIANG_VERSION=1.3.14
COPY requirements-tts.txt /tmp/requirements-tts.txt
COPY requirements-verifier.txt /tmp/requirements-verifier.txt
RUN python3 -m pip install --no-cache-dir \
        -r /tmp/requirements-tts.txt \
        -r /tmp/requirements-verifier.txt \
    && python3 -c "import py7zr" \
    && apt-get update \
    && apt-get install -y --no-install-recommends tor aria2 ca-certificates curl unzip \
    && mkdir -p /opt/ariang \
    && curl -fsSL "https://github.com/mayswind/AriaNg/releases/download/${ARIANG_VERSION}/AriaNg-${ARIANG_VERSION}.zip" -o /tmp/ariang.zip \
    && unzip -q /tmp/ariang.zip -d /tmp/ariang \
    && ariang_index="$(find /tmp/ariang -type f -name index.html -print -quit)" \
    && test -n "${ariang_index}" \
    && cp -a "$(dirname "${ariang_index}")"/. /opt/ariang/ \
    && rm -rf /tmp/ariang /tmp/ariang.zip \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements-tts.txt /tmp/requirements-verifier.txt
COPY docker/aria2/aria2-retry-on-low-speed.py /usr/local/bin/aria2-retry-on-low-speed.py
RUN chmod 0755 /usr/local/bin/aria2-retry-on-low-speed.py
COPY bot.py /app/bot.py
COPY pkg_resources.py /app/pkg_resources.py
COPY tme3bot /app/tme3bot
COPY utility /app/utility
CMD ["python3", "/app/bot.py"]
