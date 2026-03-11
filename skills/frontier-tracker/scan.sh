#!/usr/bin/env bash
set -euo pipefail

# FrontierWildWatch safe wrapper
# - Single scan at a time (flock)
# - Respect cooldown_until_utc in state.json
# - Use temp config copy for route overrides

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DEFAULT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCK_FILE="/tmp/frontierwildwatch-scan.lock"
TMP_CONFIG="/tmp/frontier_scan_tmp.json"

REPO="$REPO_DEFAULT"
ORIGINS=""
DESTS=""
DRY_RUN=0
DUMP_JSON=0
PROBE=""
PROBE_OUT="probe.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --origins) ORIGINS="$2"; shift 2 ;;
    --destinations) DESTS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --dump-json) DUMP_JSON=1; shift ;;
    --probe) PROBE="$2 $3 $4"; shift 4 ;;
    --probe-output) PROBE_OUT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

CFG="$REPO/config.json"
if [[ ! -f "$CFG" ]]; then
  echo "Missing config: $CFG"
  exit 1
fi

# Single-scan lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another scan is already running. Refusing to start."
  exit 3
fi

# Cooldown check
STATE_FILE=$(python3 - <<PY
import json
cfg=json.load(open("$CFG"))
print(cfg.get("output",{}).get("state_file","state.json"))
PY
)
if [[ "$STATE_FILE" != /* ]]; then STATE_FILE="$REPO/$STATE_FILE"; fi

if [[ -f "$STATE_FILE" ]]; then
  python3 - <<PY
import json,sys
from datetime import datetime, timezone
p="$STATE_FILE"
st=json.load(open(p))
cd=((st.get("metrics") or {}).get("cooldown_until_utc") or "").strip()
if cd:
    now=datetime.now(timezone.utc)
    try:
        target=datetime.fromisoformat(cd.replace("Z","+00:00"))
    except Exception:
        target=None
    if target and target>now:
        mins=int((target-now).total_seconds()//60)
        print(f"Cooldown active until {cd} (~{mins}m). Refusing to scan.")
        sys.exit(4)
PY
fi

cp "$CFG" "$TMP_CONFIG"

if [[ -n "$ORIGINS" || -n "$DESTS" ]]; then
  python3 - <<PY
import json
p="$TMP_CONFIG"
cfg=json.load(open(p))
if "$ORIGINS".strip():
    cfg["origins"]=[x.strip().upper() for x in "$ORIGINS".split(",") if x.strip()]
if "$DESTS".strip():
    cfg["destinations"]=[x.strip().upper() for x in "$DESTS".split(",") if x.strip()]
json.dump(cfg, open(p,"w"), indent=2)
PY
fi

cd "$REPO"
PYTHON_BIN="python3"
if [[ -x "$REPO/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO/.venv/bin/python"
fi
CMD=("$PYTHON_BIN" scanner.py --config "$TMP_CONFIG")
[[ "$DRY_RUN" == "1" ]] && CMD+=(--dry-run)
[[ "$DUMP_JSON" == "1" ]] && CMD+=(--dump-json)
if [[ -n "$PROBE" ]]; then
  # shellcheck disable=SC2206
  ARR=($PROBE)
  CMD+=(--probe "${ARR[0]}" "${ARR[1]}" "${ARR[2]}" --probe-output "$PROBE_OUT")
fi

"${CMD[@]}"
