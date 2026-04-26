FROM tianon/gosu:1.19-trixie@sha256:3b176695959c71e123eb390d427efc665eeb561b1540e82679c15e992006b8b9 AS gosu_source

FROM debian:13.4

# Disable Python stdout buffering to ensure logs are printed immediately
ENV PYTHONUNBUFFERED=1

# Use China mirrors for faster downloads (HTTPS)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# Install system dependencies in one layer, clear APT cache
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential nodejs npm python3 python3-pip ripgrep ffmpeg gcc python3-dev libffi-dev git \
        openssh-client curl cowsay boxes toilet toilet-fonts jp2a && \
    rm -rf /var/lib/apt/lists/*

# Non-root user for runtime; UID can be overridden via HERMES_UID at runtime
RUN useradd -u 10000 -m -d /opt/data hermes

COPY --chmod=0755 --from=gosu_source /gosu /usr/local/bin/

COPY . /opt/hermes
WORKDIR /opt/hermes

# Use China PyPI mirror and npm mirror
RUN pip install --no-cache-dir uv --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    uv venv && \
    uv pip install --no-cache -e ".[all]" -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    uv pip install --no-cache pyfiglet Pillow scipy -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    npm config set registry https://registry.npmmirror.com && \
    npm install --prefer-offline --no-audit && \
    npx playwright install --with-deps chromium --only-shell && \
    cd /opt/hermes/scripts/whatsapp-bridge && \
    find . -name package-lock.json -exec sed -i 's|ssh://git@github.com/|https://github.com/|g' {} + && \
    find . -name package.json -exec sed -i 's|ssh://git@github.com/|https://github.com/|g' {} + && \
    npm install --prefer-offline --no-audit && \
    npm cache clean --force

WORKDIR /opt/hermes
RUN chown -R hermes:hermes /opt/hermes && \
    chmod +x /opt/hermes/docker/entrypoint.sh

ENV HERMES_HOME=/opt/data
VOLUME [ "/opt/data" ]
ENTRYPOINT [ "/opt/hermes/docker/entrypoint.sh" ]
