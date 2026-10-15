#!/usr/bin/env bash
# Deploy this repo to the Raspberry Pi from your laptop: sync the code, retire the old new_subway.py
# (@reboot cron job + running process), and run install.sh on the Pi.
#
#   ./deploy.sh                 # deploy to $PI_HOST (default john@john.local)
#   ./deploy.sh --dry-run       # show what would change on the Pi, change nothing
#   ./deploy.sh --keep-old      # leave the old new_subway.py cron job/process alone
#   ./deploy.sh --push-config   # also overwrite the Pi's matrix.json with yours (old one saved as matrix.json.bak)
#   ./deploy.sh --with-homeassistant   # passed through to install.sh
#
# Env: PI_HOST=user@host, PI_SRC=<staging dir on the Pi> (default ~/led-matrix-src).
# Auth: one SSH connection is shared by every step, so you type the password once.
# Better: ssh-copy-id "$PI_HOST" and you won't be asked at all.
set -euo pipefail

PI_HOST=${PI_HOST:-john@john.local}
PI_SRC=${PI_SRC:-led-matrix-src}   # relative to the Pi user's home
OLD_SCRIPT=new_subway.py
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

DRY=0; KEEP_OLD=0; PUSH_CONFIG=0; INSTALL_ARGS=()
for arg in "$@"; do
  case $arg in
    --dry-run) DRY=1; INSTALL_ARGS+=(--dry-run) ;;
    --keep-old) KEEP_OLD=1 ;;
    --push-config) PUSH_CONFIG=1 ;;
    --with-homeassistant) INSTALL_ARGS+=("$arg") ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }

SOCK=$(mktemp -d)/ssh
SSH_OPTS=(-o ControlMaster=auto -o ControlPath="$SOCK" -o ControlPersist=10m -o StrictHostKeyChecking=accept-new)
trap 'ssh "${SSH_OPTS[@]}" -O exit "$PI_HOST" 2>/dev/null || true' EXIT
pi() { ssh "${SSH_OPTS[@]}" "$@"; }

step "Connect to $PI_HOST"
pi "$PI_HOST" 'echo "connected to $(hostname) ($(tr -d "\0" </proc/device-tree/model 2>/dev/null))"'

step "Sync code -> ~/$PI_SRC"
pi "$PI_HOST" 'command -v rsync >/dev/null || sudo apt-get install -y rsync'
rsync -az --delete $([ $DRY = 1 ] && echo --dry-run) -e "ssh ${SSH_OPTS[*]}" \
  --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude .env --exclude 'deploy/homeassistant/config' \
  "$HERE"/ "$PI_HOST:$PI_SRC"/

if [ $KEEP_OLD = 0 ]; then
  step "Retire the old $OLD_SCRIPT (cron @reboot entry + running process)"
  # Both it and run.py drive the same panel, so only one may run. The crontab is backed up first.
  pi "$PI_HOST" bash -s -- "$OLD_SCRIPT" "$DRY" <<'REMOTE'
set -eu
old=$1 dry=$2
if sudo crontab -l 2>/dev/null | grep -q "$old"; then
  if [ "$dry" = 1 ]; then echo "+ would remove '$old' from root's crontab and kill the process"; exit 0; fi
  sudo crontab -l > "$HOME/root-crontab.backup.$(date +%Y%m%d%H%M%S)"
  sudo crontab -l | grep -v "$old" | sudo crontab -
  echo "removed from root's crontab (backup in ~)"
else
  echo "no cron entry for $old"
fi
# Anchor on "python" so the pattern can't match this shell, whose arguments also contain the script name.
pat="python[0-9.]* .*$old"
if pgrep -f "$pat" >/dev/null; then
  [ "$dry" = 1 ] || { sudo pkill -f "$pat" || true; sleep 1; echo "stopped running $old"; }
else
  echo "$old not running"
fi
REMOTE
fi

step "Run install.sh on the Pi"
if [ $DRY = 1 ]; then echo "(dry run: skipping; run 'ssh $PI_HOST \"cd ~/$PI_SRC && ./install.sh --dry-run\"' after a real sync to preview it)"; exit 0; fi
pi -t "$PI_HOST" "cd ~/$PI_SRC && ./install.sh ${INSTALL_ARGS[*]:-}"

if [ $PUSH_CONFIG = 1 ]; then
  step "Push matrix.json (the runner follows the edit; no restart needed)"
  # install.sh never overwrites it: the assistant and Home Assistant edit it on the Pi.
  pi "$PI_HOST" 'sudo cp -p /opt/led-matrix/matrix.json /opt/led-matrix/matrix.json.bak 2>/dev/null || true'
  rsync -az -e "ssh ${SSH_OPTS[*]}" --rsync-path="sudo rsync" --no-owner --no-group "$HERE/matrix.json" "$PI_HOST:/opt/led-matrix/matrix.json"
fi

echo
echo "Deployed. Logs: ssh $PI_HOST journalctl -u led-matrix -f"
