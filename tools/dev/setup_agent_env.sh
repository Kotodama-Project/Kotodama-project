#!/usr/bin/env bash
# SessionStart is cloud-only; explicit setup works on a Linux developer host.
set -u
if [[ "${1:-}" == "--hook" && "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
  exit 0
fi
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
for task_python in python3.12 python3 python; do
  if command -v "$task_python" >/dev/null 2>&1 &&
     "$task_python" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' 2>/dev/null; then
    exec "$task_python" "$task_root/tools/dev/setup_agent_env.py" "$@"
  fi
done
printf '%s\n' '[agent-env] INCOMPLETE: Python 3.12 is required (CI: 3.12.10). Provision it in the environment setup, then rerun bash tools/dev/setup_agent_env.sh.'
exit 0
