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
COPY bot.py /app/bot.py
COPY pkg_resources.py /app/pkg_resources.py
COPY tme3bot /app/tme3bot
COPY utility /app/utility
CMD ["python3", "/app/bot.py"]

FROM runtime-base AS worker
COPY requirements-tts.txt /tmp/requirements-tts.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements-tts.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends tor \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements-tts.txt
COPY bot.py /app/bot.py
COPY pkg_resources.py /app/pkg_resources.py
COPY tme3bot /app/tme3bot
COPY utility /app/utility
CMD ["python3", "/app/bot.py"]
