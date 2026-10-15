#!/usr/bin/env bash
# Run the Claude Code CLI once and print the patch JSON.
#
#   claude-propose.sh SYSTEM_FILE SCHEMA_FILE < prompt.txt > patch.json
#
# Used by serve.py (matrix_ui/assistant.py: CliClient). Uses your Claude Code login. Set CLAUDE_BIN to pick a binary, MATRIX_AI_MODEL to pick a model.
set -euo pipefail
system_file=${1:?usage: claude-propose.sh SYSTEM_FILE SCHEMA_FILE}
schema_file=${2:?usage: claude-propose.sh SYSTEM_FILE SCHEMA_FILE}

find_claude() {
  if [ -n "${CLAUDE_BIN:-}" ]; then echo "$CLAUDE_BIN"; return; fi
  if command -v claude >/dev/null 2>&1; then command -v claude; return; fi
  # The VS Code extension bundles a binary; take the newest.
  ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | sort -V | tail -1
}
claude_bin=$(find_claude)
[ -x "${claude_bin:-}" ] || { echo "claude CLI not found; set CLAUDE_BIN" >&2; exit 1; }

# No tools: the model only answers. Run from a scratch dir so no project context is picked up.
cd "$(mktemp -d)"
out=$("$claude_bin" -p --tools "" --no-session-persistence --output-format json \
  ${MATRIX_AI_MODEL:+--model "$MATRIX_AI_MODEL"} \
  --system-prompt "$(cat "$system_file")" --json-schema "$(cat "$schema_file")")

# The CLI wraps the answer in a result envelope; the schema-conforming object is `structured_output`.
printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if d.get("is_error") or "structured_output" not in d:
    sys.exit("claude CLI gave no structured output: " + str(d.get("result", d))[:300])
print(json.dumps(d["structured_output"]))
'
