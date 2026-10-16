#!/usr/bin/env bash
# Set up the whole project on a Raspberry Pi (Raspberry Pi OS / Debian). Run as your normal user; it uses sudo.
#
#   ./install.sh                       # matrix runner + web page service
#   ./install.sh --dry-run             # print what would happen, change nothing (works off-Pi too)
#
# Safe to re-run: it re-syncs the code, keeps matrix.json and /etc/led-matrix.env, and restarts services.
# Installs to /opt/led-matrix (override with INSTALL_DIR=...). Services:
#   led-matrix.service            run.py --live, as root (GPIO needs it; the library drops privileges after init)
#   led-matrix-assistant.service  serve.py: the web page and its JSON API on ports 8099 and 80, as you. It answers the
#                                 local network only (private addresses and local names), whatever the router does.
set -euo pipefail

INSTALL_DIR=${INSTALL_DIR:-/opt/led-matrix}
BINDINGS_DIR=${BINDINGS_DIR:-/opt/rpi-rgb-led-matrix}
ENV_FILE=/etc/led-matrix.env
SRC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUN_USER=$USER
VENV=$INSTALL_DIR/.venv

DRY=0
for arg in "$@"; do
  case $arg in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
run() { if [ $DRY = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
sudo_run() { if [ "$(id -u)" = 0 ]; then run "$@"; else run sudo "$@"; fi; }
# write_root PATH MODE < content   (root-owned file, content on stdin)
write_root() {
  if [ $DRY = 1 ]; then printf '+ write %s (mode %s)\n' "$1" "$2"; cat >/dev/null; return; fi
  if [ "$(id -u)" = 0 ]; then install -m "$2" /dev/stdin "$1"; else sudo install -m "$2" /dev/stdin "$1"; fi
}

# write_user PATH < content   (file owned by the current user)
write_user() {
  if [ $DRY = 1 ]; then printf '+ write %s\n' "$1"; cat >/dev/null; else cat > "$1"; fi
}

# ---- preflight ----
if [ $DRY = 0 ]; then
  [ "$(uname -s)" = Linux ] || { echo "This installs onto a Raspberry Pi (Linux). Use --dry-run to preview." >&2; exit 1; }
  [ "$(id -u)" != 0 ] || { echo "Run as your normal user, not root or sudo; it calls sudo itself and the services run as you." >&2; exit 1; }
  command -v apt-get >/dev/null || { echo "apt-get not found; this script targets Raspberry Pi OS / Debian." >&2; exit 1; }
  grep -qi "raspberry pi\|bcm2" /proc/cpuinfo /proc/device-tree/model 2>/dev/null \
    || echo "warning: this doesn't look like a Raspberry Pi; continuing anyway."
fi

# ---- 1. system packages ----
step "System packages"
sudo_run apt-get update
sudo_run apt-get install -y git build-essential python3-dev python3-venv python3-pip rsync curl

# ---- 2. project files ----
step "Project files -> $INSTALL_DIR"
sudo_run mkdir -p "$INSTALL_DIR"
sudo_run chown "$RUN_USER": "$INSTALL_DIR"
if [ "$SRC_DIR" != "$INSTALL_DIR" ]; then
  # Keep local state: the model file, the venv, and git/cache dirs.
  run rsync -a --delete \
    --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
    --exclude matrix.json \
    "$SRC_DIR"/ "$INSTALL_DIR"/
  [ -e "$INSTALL_DIR/matrix.json" ] || run cp "$SRC_DIR/matrix.json" "$INSTALL_DIR/matrix.json"
fi

# ---- 3. python environment ----
step "Python environment"
[ -x "$VENV/bin/python" ] || run python3 -m venv "$VENV"
run "$VENV/bin/pip" install --quiet --upgrade pip
# The emulator in requirements.txt is only used off-Pi, but it is small and the backend prefers rgbmatrix anyway.
run "$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ---- 4. rgbmatrix bindings (hzeller/rpi-rgb-led-matrix) ----
step "rgbmatrix bindings"
if [ $DRY = 0 ] && "$VENV/bin/python" -c "import rgbmatrix" 2>/dev/null; then
  echo "already installed"
else
  [ -d "$BINDINGS_DIR/.git" ] || { sudo_run mkdir -p "$BINDINGS_DIR"; sudo_run chown "$RUN_USER": "$BINDINGS_DIR"
    run git clone --depth 1 https://github.com/hzeller/rpi-rgb-led-matrix.git "$BINDINGS_DIR"; }
  # Upstream's bindings are pip-installable (scikit-build-core + cmake; pip fetches the build tools itself).
  run "$VENV/bin/pip" install "$BINDINGS_DIR"
fi

# The panel driver needs the Pi's sound hardware off (they share the PWM peripheral).
step "Disable onboard sound (conflicts with the matrix driver)"
if [ $DRY = 1 ] || [ ! -f /etc/modprobe.d/blacklist-rgb-matrix.conf ]; then
  echo "blacklist snd_bcm2835" | write_root /etc/modprobe.d/blacklist-rgb-matrix.conf 644
  REBOOT_NEEDED=1
fi

# ---- 5. config for the web page service ----
step "Web page config ($ENV_FILE)"
if [ $DRY = 1 ] || [ ! -f "$ENV_FILE" ]; then
  write_root "$ENV_FILE" 600 <<EOF
# Read by led-matrix-assistant.service. Edit, then: sudo systemctl restart led-matrix-assistant
# The service only answers the local network. There is no password: anyone on that network can use the web page.
# Requests must name the Pi by IP address, a one-word name (raspberrypi) or a .local/.lan name. If your router gives it
# another name, list it here (comma separated).
#MATRIX_ALLOWED_HOSTS=pi.example.box
EOF
  echo "wrote $ENV_FILE"
else
  echo "keeping existing $ENV_FILE"
  if sudo grep -q '^MATRIX_TOKEN=' "$ENV_FILE" 2>/dev/null; then
    echo "note: it sets MATRIX_TOKEN, which is no longer used: the web page has no password now, so anyone on the"
    echo "      local network can use it. To tidy up: sudo sed -i '/^MATRIX_TOKEN=/d' $ENV_FILE"
  fi
fi

# ---- 6. services ----
step "systemd services"
write_root /etc/systemd/system/led-matrix.service 644 <<EOF
[Unit]
Description=LED matrix runner
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python run.py --live
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
write_root /etc/systemd/system/led-matrix-assistant.service 644 <<EOF
[Unit]
Description=LED matrix web page (serve.py)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/python serve.py --host 0.0.0.0 --port 8099 --port 80
AmbientCapabilities=CAP_NET_BIND_SERVICE
# A second layer under serve.py's own check: the kernel drops packets to or from any non-local address.
IPAddressDeny=any
IPAddressAllow=localhost link-local 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 fc00::/7
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo_run systemctl daemon-reload
sudo_run systemctl enable led-matrix.service
sudo_run systemctl restart led-matrix.service

sudo_run systemctl enable led-matrix-assistant.service
sudo_run systemctl restart led-matrix-assistant.service

# ---- done ----
HOST=$(hostname -s).local
step "Done"
cat <<EOF
Matrix runner:  sudo systemctl status led-matrix        (logs: journalctl -u led-matrix -f)
Model file:     $INSTALL_DIR/matrix.json  (the runner follows edits)
Web page:       http://$HOST/   (also :8099; local network only, no password: anyone on it can use the page)
EOF
if [ "${REBOOT_NEEDED:-0}" = 1 ] && [ $DRY = 0 ]; then
  echo
  echo "Reboot once (sudo reboot) so the onboard sound driver is unloaded; the matrix may flicker or fail until then."
fi
