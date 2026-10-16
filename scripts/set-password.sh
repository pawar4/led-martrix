#!/usr/bin/env bash
# Set or change the password for the web page: writes MATRIX_TOKEN into the service's env file and restarts the service.
#
#   sudo /opt/led-matrix/scripts/set-password.sh     # asks twice; nothing is shown, nothing lands in shell history
#
# Env: ENV_FILE (default /etc/led-matrix.env). The page asks for the password once per browser; scripts send it as
# `Authorization: Bearer <password>`.
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/led-matrix.env}
SERVICE=led-matrix-assistant

die() { echo "error: $*" >&2; exit 1; }

[ -w "$ENV_FILE" ] || die "can't write $ENV_FILE; run with sudo: sudo $0"

read -rsp "New password: " password || true; echo >&2
read -rsp "Again: " again || true; echo >&2

[ "$password" = "$again" ] || die "the two entries differ"
# Letters, digits and a few symbols: nothing systemd's env file parser or a shell would treat specially.
valid='^[A-Za-z0-9._~@%+=:,/!^*-]{6,64}$'
[[ $password =~ $valid ]] || die "the password must be 6 to 64 characters: letters, digits or . _ ~ @ % + = : , / ! ^ * -"

# Keep every other line, replace an active MATRIX_TOKEN= (a commented one stays), and write in place so the file keeps
# its owner and mode (600).
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
{ grep -v '^MATRIX_TOKEN=' "$ENV_FILE" || true; printf 'MATRIX_TOKEN=%s\n' "$password"; } > "$tmp"
cat "$tmp" > "$ENV_FILE"

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart "$SERVICE" || echo "warning: couldn't restart $SERVICE; restart it yourself" >&2
else
  echo "systemctl not found: restart $SERVICE yourself" >&2
fi
echo "Password set."
