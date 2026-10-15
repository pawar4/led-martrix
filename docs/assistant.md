# Assistant service

`serve.py` lets you change the matrix in plain English, e.g. from Home Assistant. It edits the global model file
(`matrix.json`); `run.py` reloads it, so the two run side by side.

```
request ──> serve.py ──> Assistant.ask ──> Claude (query + current model + screen list) ──> patch
                                              │ apply to a copy, validate, retry once on error
                                              └──> matrix.json (atomic write) ──> run.py reloads
```

```bash
python serve.py                                            # 127.0.0.1:8099
MATRIX_TOKEN=secret python serve.py --host 0.0.0.0         # LAN / container access; a token is required off loopback
curl -s localhost:8099/ask -d '{"query": "show the weather and dim it"}'
```

| endpoint | |
|---|---|
| `POST /ask` `{"query", "dry_run"?}` | returns `{reply, changed, applied, model}`; `dry_run` validates without writing |
| `POST /undo` | restores the previous model (the last 10 are kept in memory, lost on restart) |
| `GET /model` | the current global model |
| `GET /health` | no auth needed |

With `MATRIX_TOKEN` set, send `Authorization: Bearer <token>`. Errors return `{"error"}`: 400 bad request, 401 auth,
422 the AI's patch couldn't be applied or the CLI call failed.

## What the AI can change

Only the global-model keys ([screen-config.md](screen-config.md#global-model)): `power`, `brightness`, `screen` (pin or
unpin), `rotation`, and per-screen source params (`screens.<name>.sources.<mount>`, e.g. a market symbol). It never
edits screen layouts. The patch is a structured output (JSON schema, `null` = unchanged); source params travel as a JSON
string (`params_json`) because the schema can't describe free-form objects.

The prompt lists every `screens/*.json` with its sources. A patch naming an unknown screen or mount, or params the
source rejects, fails validation (`load_surface`, the same loader the runner uses) before anything is written. The
error goes back to Claude once; if the second try fails, `/ask` returns 422 and the file is untouched.

## How it asks Claude

`scripts/claude-propose.sh` runs `claude -p` (no tools, structured output) with your Claude Code login and prints the
patch (`CliClient` in `matrix_ui/assistant.py`). There is no API key or SDK. The script finds `claude` via `$CLAUDE_BIN`, `PATH`, or the VS Code
extension's bundled binary.

```bash
python serve.py --once "put the weather on and dim it"           # dry run, prints the result
python serve.py --once "put the weather on and dim it" --apply   # writes matrix.json
python serve.py                                                                 # the HTTP service
```

Each request starts a CLI process, so expect several seconds.

## Config

`--config`, `--screens`, `--host`, `--port`, `--model`. The model defaults to `$MATRIX_AI_MODEL`, else `claude-opus-5-5`
at `low` effort; a smaller model (e.g. `claude-haiku-5-5`) is faster for voice use.

## Home Assistant

HA in podman (see [deploy/README.md](../deploy/README.md)) calls the service with a `rest_command`. Off the Pi, use
`http://host.containers.internal:8099/ask` from inside the container. Send HA's text input as `query`, and speak or
show the `reply`.
