#!/usr/bin/env bash
# entrypoint.sh — parse positional GitHub Action inputs, invoke validator.py.
#
# Argument order is fixed by action.yml `runs.args`:
#   $1 endpoints (URL | JSON array | path to YAML/JSON config)
#   $2 threshold-p95 (integer, ms)
#   $3 tier (free | pro)
#   $4 pro-license-key (string; required when tier=pro)
#   $5 webhook-url (Slack/Teams URL; pro only)
#   $6 report-path (relative to workspace)
#   $7 fail-on (any | critical | never)
#   $8 probe-method (auto | GET | POST)
#   $9 strict-v2 (true | false)
#
# Output contract: writes "report-path", "pass-fail", "endpoints-checked"
# and "failures" to $GITHUB_OUTPUT when present, then exits with the code
# returned by validator.py.

set -euo pipefail

ENDPOINTS_RAW="${1:-}"
THRESHOLD_P95="${2:-1000}"
TIER="${3:-free}"
PRO_LICENSE_KEY="${4:-}"
WEBHOOK_URL="${5:-}"
REPORT_PATH="${6:-x402-validator-report.json}"
FAIL_ON="${7:-any}"
PROBE_METHOD="${8:-auto}"
STRICT_V2="${9:-false}"

if [[ -z "${ENDPOINTS_RAW}" ]]; then
  echo "::error::Input 'endpoints' is required" >&2
  exit 2
fi

# When workspace is mounted at /github/workspace (default for Docker actions),
# resolve report path relative to it; otherwise use the current directory.
if [[ -d "/github/workspace" ]]; then
  WORKSPACE="/github/workspace"
else
  WORKSPACE="$(pwd)"
fi

cd "${WORKSPACE}"

# Forward parsed inputs to validator.py via env to avoid shell-quoting issues
# with JSON payloads in $1.
export X402V_ENDPOINTS="${ENDPOINTS_RAW}"
export X402V_THRESHOLD_P95="${THRESHOLD_P95}"
export X402V_TIER="${TIER}"
export X402V_PRO_LICENSE_KEY="${PRO_LICENSE_KEY}"
export X402V_WEBHOOK_URL="${WEBHOOK_URL}"
export X402V_REPORT_PATH="${REPORT_PATH}"
export X402V_FAIL_ON="${FAIL_ON}"
export X402V_PROBE_METHOD="${PROBE_METHOD}"
export X402V_STRICT_V2="${STRICT_V2}"
export X402V_WORKSPACE="${WORKSPACE}"

python3 /action/validator.py
EXIT_CODE=$?

# Best-effort output emission for the calling workflow.
if [[ -n "${GITHUB_OUTPUT:-}" && -f "${REPORT_PATH}" ]]; then
  REPORT_ABS="$(cd "$(dirname "${REPORT_PATH}")" && pwd)/$(basename "${REPORT_PATH}")"
  {
    echo "report-path=${REPORT_ABS}"
    python3 - <<'PY'
import json, os, sys
path = os.environ.get("X402V_REPORT_PATH", "x402-validator-report.json")
try:
    with open(path) as f:
        data = json.load(f)
except Exception as e:
    sys.stderr.write(f"warn: could not parse report for outputs: {e}\n")
    sys.exit(0)
summary = data.get("summary", {})
print(f"pass-fail={'pass' if summary.get('all_passed') else 'fail'}")
print(f"endpoints-checked={summary.get('endpoints_checked', 0)}")
print(f"failures={summary.get('failures', 0)}")
PY
  } >> "${GITHUB_OUTPUT}"
fi

exit "${EXIT_CODE}"
