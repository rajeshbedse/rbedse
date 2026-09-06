#!/usr/bin/env bash
set -euo pipefail

# DEV Render build: expose the exact Render commit to the DEV test harness.
# RENDER_GIT_COMMIT and RENDER_GIT_BRANCH are provided by Render at build time.
mkdir -p portal/static
python - <<'PY'
import json
import os
from pathlib import Path

payload = {
    "branch": os.environ.get("RENDER_GIT_BRANCH", "unknown"),
    "commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
    "service": os.environ.get("RENDER_SERVICE_NAME", "ryb-finserv-dev"),
}
Path("portal/static/dev-build.json").write_text(
    json.dumps(payload, separators=(",", ":")),
    encoding="utf-8",
)
PY

python -m pip install -r requirements-web.txt
