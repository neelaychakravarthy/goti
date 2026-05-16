"""One-off helper: list Bright Data datasets so the dev can pick the
FB Marketplace one.

Usage:
    cd api && source .venv/bin/activate
    BRIGHT_DATA_API_KEY=... python -m api.integrations.bright_data.discover_datasets

Prints id + name + description for each dataset the API key can see, then
exits. Copy the FB-Marketplace dataset id into `.env.example`
(`BRIGHT_DATA_FB_DATASET_ID=...`) + SPEC.md Deployment env vars.

TODO(dev): the exact catalog endpoint depends on which Bright Data product
the team is on (Web Scraper API vs Datasets vs Marketplace). The two most
common endpoints are listed below; the script tries them in order and
prints whichever responds. If both fail, fall back to the Bright Data
dashboard (Datasets -> ID column) to fetch the id manually.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

# Candidate catalog endpoints, in order of preference.
_CANDIDATE_ENDPOINTS = [
    "https://api.brightdata.com/datasets/v3/list",
    "https://api.brightdata.com/dca/datasets",
]


def main() -> int:
    api_key = os.environ.get("BRIGHT_DATA_API_KEY")
    if not api_key:
        print("ERROR: BRIGHT_DATA_API_KEY env var not set.", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {api_key}"}
    last_err: Exception | None = None

    for url in _CANDIDATE_ENDPOINTS:
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 — best-effort discovery
            last_err = exc
            print(f"[discover_datasets] {url} -> {exc!r}", file=sys.stderr)
            continue

        print(f"# Datasets from {url}:")
        print(json.dumps(data, indent=2))
        print()
        print(
            "# Pick the FB Marketplace dataset id and set it in your shell + .env.example:"
        )
        print("#   export BRIGHT_DATA_FB_DATASET_ID=<id>")
        return 0

    print(
        "ERROR: could not list datasets from any known catalog endpoint.",
        file=sys.stderr,
    )
    if last_err is not None:
        print(f"Last error: {last_err!r}", file=sys.stderr)
    print(
        "Fallback: open Bright Data dashboard -> Datasets, copy the id of the "
        "FB Marketplace dataset, paste it into .env.example.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
