FROM golang:1.25 AS leave-builder
WORKDIR /src
COPY leave-helper/go.mod /src/go.mod
COPY leave-helper/main.go /src/main.go
RUN go mod tidy && CGO_ENABLED=1 GOOS=linux go build -trimpath -ldflags='-s -w' -o /out/tdl-leave .

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/data/root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python3 \
        python3-pip \
        tar \
        util-linux \
        p7zip-full \
        unar \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --home-dir /home/user1 --shell /usr/sbin/nologin user1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /app/requirements.txt

ARG TARGETARCH
ARG TDL_FALLBACK_VERSION=0.20.3
COPY .docker/tdl/ /tmp/host-tdl/
RUN set -eu; \
    use_host_tdl=0; \
    if [ -s /tmp/host-tdl/tdl ]; then \
        echo "Trying tdl copied from the Docker host"; \
        install -m 0755 /tmp/host-tdl/tdl /usr/local/bin/tdl; \
        if tdl version; then \
            use_host_tdl=1; \
        else \
            echo "Host tdl is not compatible with this image; using fallback"; \
            rm -f /usr/local/bin/tdl; \
        fi; \
    fi; \
    if [ "${use_host_tdl}" -eq 0 ]; then \
        host_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
        case "${host_arch}" in \
            amd64|x86_64) tdl_arch="64bit" ;; \
            arm64|aarch64) tdl_arch="arm64" ;; \
            *) echo "Unsupported Docker architecture for tdl: ${host_arch}"; exit 1 ;; \
        esac; \
        echo "Host tdl unavailable; downloading fallback v${TDL_FALLBACK_VERSION} for ${host_arch}"; \
        curl -fsSL "https://github.com/iyear/tdl/releases/download/v${TDL_FALLBACK_VERSION}/tdl_Linux_${tdl_arch}.tar.gz" -o /tmp/tdl.tar.gz; \
        tar -xzf /tmp/tdl.tar.gz -C /usr/local/bin tdl; \
        chmod 0755 /usr/local/bin/tdl; \
    fi; \
    rm -rf /tmp/host-tdl /tmp/tdl.tar.gz; \
    tdl version

COPY bot.py /app/bot.py
COPY tme3bot /app/tme3bot
COPY utility /app/utility
COPY --from=leave-builder /out/tdl-leave /usr/local/bin/tdl-leave
RUN chmod 0755 /usr/local/bin/tdl-leave

RUN mkdir -p /data/root /data/user1 /data/download /data/exports /data/tmp

CMD ["python3", "/app/bot.py"]
