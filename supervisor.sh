#!/bin/bash
# The Ones AI Feed — Flask process supervisor
PROJECT_DIR="/projects/active/feedtheones"
LOG_DIR="/home/vizi/feed.theones.io/logs"
FLASK_LOG="$LOG_DIR/feed-flask.log"
SUP_LOG="$LOG_DIR/feed-sup.log"
VENV="/home/vizi/feed.theones.io/venv"
PORT_NUM=5101

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$SUP_LOG"; }

start_flask() {
    if pgrep -f 'feedtheones/backend/app.py' >/dev/null; then return; fi
    log "Starting Flask on port $PORT_NUM..."
    cd "$PROJECT_DIR" && PORT=$PORT_NUM setsid nohup "$VENV/bin/python" backend/app.py >> "$FLASK_LOG" 2>&1 < /dev/null &
    sleep 2
}

case "${1:-supervise}" in
    start) start_flask ;;
    stop)
        log "Stopping..."
        pkill -9 -f 'feedtheones/backend/app.py' 2>/dev/null || true
        ;;
    restart)
        pkill -9 -f 'feedtheones/backend/app.py' 2>/dev/null || true
        sleep 1; start_flask ;;
    status)
        echo '=== Flask ==='; pgrep -af 'feedtheones/backend/app.py' || echo 'NOT RUNNING'
        echo "=== port $PORT_NUM ==="; ss -tlnp 2>/dev/null | grep ":$PORT_NUM " || echo 'NOT LISTENING'
        ;;
    supervise)
        log "Supervisor started, checking every 30s"
        while true; do start_flask; sleep 30; done ;;
esac
