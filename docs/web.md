# Web page and model service

`serve.py` is the one HTTP service that edits the global model file (`matrix.json`); `run.py` reloads it, so the two
run side by side. It has two ways in: the [web page](#web-page) and a plain JSON API. It answers the local network
only ([see below](#local-network-only)), and it makes no outgoing connections.

```
request ──> serve.py ──> ModelStore.update ──> apply to a copy, validate (validate_model)
                                                  └──> matrix.json (atomic write) ──> run.py reloads
```

```bash
python serve.py                                            # 127.0.0.1:8099
python serve.py --host 0.0.0.0                             # LAN / container access, no password
MATRIX_TOKEN=secret python serve.py --host 0.0.0.0         # same, but every request needs the token
curl -s -X PATCH localhost:8099/model -d '{"brightness": 20}'
```

| endpoint | |
|---|---|
| `GET /` | the web page; no auth needed (it holds no data) |
| `PATCH /model` `{key: value, ...}` | merges top-level keys into the model (`null` removes a key), validates, writes; returns `{reply, changed, applied, model}`. `{"brightness": 20, "screen": null}` |
| `POST /undo` | restores the previous model (the last 10 are kept in memory, lost on restart; the page and `PATCH` share the history) |
| `GET /model` | the current global model |
| `GET /screens` | `{screen: [source specs]}` for every screen file, as written in the file |
| `GET /cron?at=<expr>&count=3` | the next firings of a cron expression in the Pi's local time, `{"next": ["Thu Oct 15 14:15", ...]}`; 400 if it doesn't parse |
| `GET /health` | no auth needed; `{"ok": true}` |

There is no password unless you set `MATRIX_TOKEN` (see [Access](#access)); then send `Authorization: Bearer <token>`.
Errors return `{"error"}`: 400 bad request, 401 auth, 403 not the local network or a browser page on another origin
tried to write, 422 the change isn't a valid model.

## Web page

Open `http://<pi>.local/` (or `http://localhost:8099/` when you run `python serve.py` yourself). The installed service
listens on port 80 for that short address and on 8099. It is one static file, `web/index.html`, with no build step and no
external requests: the service sends it with a `Content-Security-Policy` that lets it talk to the service only, and a
test fails if the page ever references another host. Behind a password it asks for it once and keeps it in the
browser's local storage (see [Access](#access)).

Forms for the global-model keys ([screen-config.md](screen-config.md#global-model)): power, brightness and the pinned
screen; the schedule rules (add, delete, reorder, with the next three firings of each cron expression shown under it);
rotation; sleep windows (none, every day, or weekdays and weekends apart); and, per screen, the params of each data source
(only values that differ from the screen's own are saved, and **Reset** drops a source's overrides). A **Raw JSON** panel edits the same
draft as the forms. **Undo** sits at the top.

Edits stay in the page until you press **Save** (or Ctrl/Cmd+S), which sends only the top-level keys you changed, so a
change made meanwhile from another tab or a script isn't overwritten. The page checks for outside changes every few seconds
and keeps your unsaved edits on top of them. A rejected save shows the validation message under the Save button and
writes nothing.

## Local network only

Binding to `0.0.0.0` listens on every interface, so the service checks each request itself, before the token and before
anything is read or written. A request gets a 403 unless all of these hold:

- **It comes from a local address**: loopback, private (`10/8`, `172.16/12`, `192.168/16`, IPv6 `fc00::/7`) or link-local.
  A router port forward, or a tunnel that doesn't run on the Pi itself, shows up as a public address and is refused. Carrier-grade NAT space
  (`100.64/10`, which Tailscale uses) is not counted as local.
- **Its `Host` header is a local name**: an IP address, `localhost`, a one-word name (`raspberrypi`), or a name ending in
  `.local`, `.lan`, `.localdomain`, `.home.arpa` or `.internal`. This stops DNS rebinding, where a web page you visit on
  the internet points its own domain at the Pi's address so your browser, which is on your network, makes requests the
  page's script can then read. The browser sends that page's domain as `Host`, so it is refused. If your router gives the Pi
  another name (say `pi.fritz.box`), list it in `MATRIX_ALLOWED_HOSTS` (comma separated) in `/etc/led-matrix.env`.
- **It carries no forwarding headers** (`Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`,
  `CF-Connecting-IP`, `True-Client-IP`). A tunnel or reverse proxy running on the Pi itself (cloudflared, ngrok,
  `tailscale serve`, Caddy) connects from `127.0.0.1`, which passes the address check, but they add these headers, so the
  request is refused. This is a heuristic: a proxy configured to strip them would get through, so don't run one.

The installed unit adds a second layer in the kernel: `IPAddressDeny=any` with `IPAddressAllow=` for loopback, link-local,
`10/8`, `172.16/12`, `192.168/16` and `fc00::/7`, so systemd drops packets to or from any other address before they reach
the service (and it can't open a connection to one). It uses cgroup BPF filtering, which Raspberry Pi OS (Bookworm and
later) supports; remove the two lines from `/etc/systemd/system/led-matrix-assistant.service` if your Pi doesn't.

The connection is plain HTTP, so anyone who can sniff your network sees the traffic and the token.

## Access

By default there is no password: anyone on the local network can use the page and the API, which is fine on a home
network ([who can reach it](../deploy/README.md#who-can-reach-the-web-page)). To require one, run
`sudo /opt/led-matrix/scripts/set-password.sh` on the Pi: it asks twice (6 to 64 letters, digits or `. _ ~ @ % + = : , / ! ^ * -`),
writes `MATRIX_TOKEN` to `/etc/led-matrix.env` and restarts `led-matrix-assistant`; run it again to change the password.
The page then asks for it once and sends it as `Authorization: Bearer <token>`, as does curl. `install.sh` doesn't
generate one, and leaves an existing one in place.

Even without a password, `POST` and `PATCH` from a browser page on a different origin get a 403, so a web page you visit
can't change the matrix. Curl and the matrix's own page aren't affected.
(A page in another tab can't read the responses either, since the service sends no CORS headers.)

## What a write must satisfy

Every write, from the page or `PATCH`, goes through `validate_model` (`matrix_ui/model_store.py`). It is stricter
than the runner, which skips what it can't read and logs: unknown top-level keys, a non-boolean `power`, a `brightness`
outside 1 to 100, a bad `rotation`, a schedule rule with an unparsable cron expression or a non-positive `for`, a sleep
window that isn't `"HH:MM"`, and source overrides the screen rejects are all errors that name the problem. Every screen
named by `screen`, `rotation`, `schedule` or `screens` must load.

A write can override the params of a screen's data sources (`screens.<name>.sources.<mount>`), including a `url` on an
`http_json` source or a `path` on a `file` source, if the screen has one. No shipped screen does. If you add one, anyone
who can use the API can point it at any address the Pi can reach, so keep such screens out or put a token on the service.

## Config

`--config`, `--screens`, `--host`, `--port`. `--port` can repeat (the service runs `--port 8099 --port 80`): the
first must bind, and a later one that can't (in use, or no permission) is skipped with a warning, so the service still
comes up on 8099. Port 80 works for the non-root service user through `AmbientCapabilities=CAP_NET_BIND_SERVICE`.
Environment: `MATRIX_TOKEN` (optional password), `MATRIX_ALLOWED_HOSTS` (extra host names, see above).
