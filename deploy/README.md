# Deploy

## Everything on the Pi

`./install.sh` (repo root) sets up the runner and the web page service (`serve.py`, ports 8099 and 80). Logs:
`journalctl -u led-matrix -f`, `journalctl -u led-matrix-assistant -f`.

## Deploying from your laptop

`./deploy.sh` (repo root) rsyncs the repo to `~/led-matrix-src` on `$PI_HOST` (default `john@john.local`), backs up and
edits root's crontab to drop the old `new_subway.py` `@reboot` line, stops that process (it and `run.py` can't share the
panel), and runs `install.sh` there. Flags: `--dry-run`, `--keep-old`, `--push-config` (replace the Pi's `matrix.json` with yours, keeping the old one as `matrix.json.bak`; without it the Pi's copy is left alone since the web page edits it). Run `ssh-copy-id` once to avoid
password prompts.

## Who can reach the web page

Only devices on your own network. The service enforces this itself: it refuses (403) any request that doesn't come from
a private, loopback or link-local address, that arrives through a proxy or tunnel, or that names the Pi by anything
other than an IP address or a local name (`raspberrypi.local`), so a router port forward, a tunnel or a web page you
visit can't reach it. Details and limits are in
[Local network only](../docs/web.md#local-network-only). If your router gives the Pi a name that isn't `.local`
or `.lan`, list it in `MATRIX_ALLOWED_HOSTS` in `/etc/led-matrix.env`.

There is no password: anything on that network, guests on your wifi included, can load the page and change the matrix.
The connection is plain HTTP. Don't port-forward 80 or 8099 on your router, and don't run a tunnel or reverse
proxy on the Pi.

The matrix runner itself stays on the Pi host (it needs GPIO), not in a container.
