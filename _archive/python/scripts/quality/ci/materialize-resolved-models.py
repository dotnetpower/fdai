#!/usr/bin/env python3
"""Materialize the local-only resolved model manifest for CI."""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    raw = os.environ.get("RESOLVED_MODELS_JSON", "").strip()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if not raw:
        if event_name != "pull_request":
            raise SystemExit("RESOLVED_MODELS_JSON repository variable is required")
        payload: object = {
            "schema_version": "1.0.0",
            "capabilities": [],
            "mixed_model_mode": "hil-only",
        }
    else:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise SystemExit("RESOLVED_MODELS_JSON must contain a JSON object")
        if not isinstance(payload.get("capabilities"), list):
            raise SystemExit("RESOLVED_MODELS_JSON.capabilities must be an array")
    Path("resolved-models.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
