# Deploy

## Home Assistant (podman)

- **On the Pi:** `deploy/homeassistant/homeassistant.container` is a rootless
  Quadlet unit. Copy it to `~/.config/containers/systemd/`, then
  `systemctl --user daemon-reload && systemctl --user start homeassistant`.
  Run `loginctl enable-linger $USER` so it starts at boot. UI on port 8123.
- **Locally (Mac/Linux):** `deploy/homeassistant/run-local.sh` starts it with
  `podman run`. Install podman first (`brew install podman && podman machine init && podman machine start`).

The matrix runner itself stays on the Pi host (it needs GPIO), not in a container.
