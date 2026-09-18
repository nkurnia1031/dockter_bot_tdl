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
CMD ["python3", "/app/bot.py"]
