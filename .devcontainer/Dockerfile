FROM mcr.microsoft.com/devcontainers/universal:5.1-linux

USER root

# Codespaces Web Mode is terminal + forwarded browser only. No remote desktop,
# no VNC, no noVNC, and no container Chrome are installed.
RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        procps \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

USER codespace
