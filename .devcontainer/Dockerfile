FROM mcr.microsoft.com/devcontainers/universal:5.1-linux

USER root

# GUI prerequisites are baked into the Codespace so the real Ubuntu setup
# wrapper can open its Tk window without asking the beginner for terminal work.
RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dbus-x11 \
        desktop-file-utils \
        git \
        gnupg \
        pcmanfm \
        procps \
        python3-tk \
        python3-venv \
        x11-utils \
        xdg-utils \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

USER codespace
