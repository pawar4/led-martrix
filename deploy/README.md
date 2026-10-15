# Deploy

## Everything on the Pi

`./install.sh` (repo root) sets up the runner, the assistant service and, with `--with-homeassistant`, Home Assistant
as a systemd user unit running `podman run` (works on podman < 4.4, which has no Quadlet). The Quadlet file below is
the alternative for podman >= 4.4. Logs: `journalctl -u led-matrix -f`, `journalctl -u led-matrix-assistant -f`.

## Home Assistant (podman)

- **On the Pi:** `deploy/homeassistant/homeassistant.container` is a rootless
  Quadlet unit. Copy it to `~/.config/containers/systemd/`, then
  `systemctl --user daemon-reload && systemctl --user start homeassistant`.
  Run `loginctl enable-linger $USER` so it starts at boot. UI on port 8123.
- **Locally (Mac/Linux):** `deploy/homeassistant/run-local.sh` starts it with
  `podman run`. Install podman first (`brew install podman && podman machine init && podman machine start`).

The matrix runner itself stays on the Pi host (it needs GPIO), not in a container.

## Connecting Home Assistant to the matrix

Follow the steps at the top of `deploy/homeassistant/matrix.yaml` (a package file: a `rest_command` that calls
`serve.py`'s `/ask`, and an Assist sentence `matrix <anything>` that sends the text and speaks or shows the `reply`).
