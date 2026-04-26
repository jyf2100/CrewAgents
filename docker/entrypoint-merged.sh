#!/bin/bash
# Docker entrypoint: bootstrap config files into the mounted volume, then run hermes gateway + dashboard.
set -e

HERMES_HOME="/opt/data"
INSTALL_DIR="/opt/hermes"

# --- Privilege dropping via gosu ---
if [ "$(id -u)" = "0" ]; then
    if [ -n "$HERMES_UID" ] && [ "$HERMES_UID" != "$(id -u hermes)" ]; then
        echo "Changing hermes UID to $HERMES_UID"
        usermod -u "$HERMES_UID" hermes
    fi

    if [ -n "$HERMES_GID" ] && [ "$HERMES_GID" != "$(id -g hermes)" ]; then
        echo "Changing hermes GID to $HERMES_GID"
        groupmod -g "$HERMES_GID" hermes
    fi

    actual_hermes_uid=$(id -u hermes)
    if [ "$(stat -c %u "$HERMES_HOME" 2>/dev/null)" != "$actual_hermes_uid" ]; then
        echo "$HERMES_HOME is not owned by $actual_hermes_uid, fixing"
        chown -R hermes:hermes "$HERMES_HOME"
    fi

    echo "Dropping root privileges"
    exec gosu hermes "$0" "$@"
fi

# --- Running as hermes from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# .env
if [ ! -f "$HERMES_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"
fi

# config.yaml
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml"
fi

# SOUL.md
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md"
fi

# Sync bundled skills
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py"
fi

# Install web dependencies if not present
python3 -c "import fastapi" 2>/dev/null || uv pip install --system --break-system-packages 'hermes-agent[web]' -i https://pypi.tuna.tsinghua.edu.cn/simple

# Start gateway in background
echo "Starting Hermes Gateway..."
hermes gateway &
GATEWAY_PID=$!

# Wait a moment for gateway to initialize
sleep 5

# Start dashboard in background
echo "Starting Hermes Dashboard..."
python3 -m hermes_cli.main dashboard --host 0.0.0.0 --port 9119 --insecure &
DASHBOARD_PID=$!

# Handle shutdown gracefully
cleanup() {
    echo "Shutting down..."
    kill -TERM $GATEWAY_PID $DASHBOARD_PID 2>/dev/null
    wait
    exit 0
}
trap cleanup SIGTERM SIGINT

# Wait for both processes
echo "Hermes Gateway (PID $GATEWAY_PID) and Dashboard (PID $DASHBOARD_PID) running..."
wait $GATEWAY_PID $DASHBOARD_PID
