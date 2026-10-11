#!/usr/bin/env bash
# Try Home Assistant locally with plain `podman run` (e.g. on a Mac).
# On macOS podman runs in a VM, so host networking does not reach the Mac:
# HA is published on :8123 and reaches a service on the Mac at
# http://host.containers.internal:<port>.
set -euo pipefail
CONFIG_DIR="${HA_CONFIG_DIR:-$(cd "$(dirname "$0")" && pwd)/config}"
mkdir -p "$CONFIG_DIR"
podman rm -f homeassistant >/dev/null 2>&1 || true
exec podman run -d --name homeassistant \
  -p 8123:8123 \
  -v "$CONFIG_DIR:/config:Z" \
  -e TZ="${TZ:-America/New_York}" \
  ghcr.io/home-assistant/home-assistant:stable
