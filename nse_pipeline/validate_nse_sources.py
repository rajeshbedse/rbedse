"""Validate NSE-first enrichment against the fields used by the current model.

This is intentionally a validation utility, not part of the production scoring
path. It fetches first-party NSE datasets and writes a compact, auditable JSON
snapshot for a supplied list of symbols. The production analyzer remains
unchanged until the NSE field mapping has been verified.

Usage:
    python -m nse_pipeline.validate_nse_sources APLLTD GANDHAR

The output contains the raw NSE payloads needed to map:
    - promoter holding / shareholding
    - financial results
    - results comparison / historical periods
    - current quote

NSE is the only external data source used here.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .nse_enrichment import fetch_nse_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture NSE-first validation snapshots")
    parser.add_argument("symbols", nargs="+", help="NSE equity symbols")
    parser.add_argument("--output", default="output/nse_validation", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "NSE India",
        "symbols": [s.upper() for s in args.symbols],
        "files": [],
    }

    for symbol in manifest["symbols"]:
        try:
            snapshot = fetch_nse_snapshot(symbol)
            path = out_dir / f"{symbol}.json"
            path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
            manifest["files"].append({"symbol": symbol, "path": str(path), "status": "ok"})
            print(f"NSE validation: {symbol} -> {path}")
        except Exception as exc:
            manifest["files"].append({"symbol": symbol, "status": "error", "error": str(exc)})
            print(f"NSE validation: {symbol} -> ERROR: {exc}")

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    return 0 if all(x["status"] == "ok" for x in manifest["files"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
