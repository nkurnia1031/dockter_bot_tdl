ARG TME3BOT_BASE_IMAGE=tme3bot-base:py310-tdl0203
FROM ${TME3BOT_BASE_IMAGE} AS runtime-base

WORKDIR /app

COPY bot.py /app/bot.py
COPY pkg_resources.py /app/pkg_resources.py
COPY tme3bot /app/tme3bot
COPY utility /app/utility

# The base image contains Python dependencies, tdl, and the fixed Go helper.
FROM runtime-base AS gateway
CMD ["python3", "/app/bot.py"]

FROM runtime-base AS worker
COPY requirements-tts.txt /app/requirements-tts.txt
RUN python3 -m pip install --no-cache-dir -r /app/requirements-tts.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends tor \
    && rm -rf /var/lib/apt/lists/*
CMD ["python3", "/app/bot.py"]
