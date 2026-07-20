#!/usr/bin/env python3
"""Validate the machine-readable architecture-review readiness contract."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_READINESS_MODULE_PATH = (
    _REPO_ROOT / "src" / "fdai" / "core" / "architecture_review" / "readiness.py"
)


def _load_validator() -> Callable[[Any, Path, bool], None]:
    spec = importlib.util.spec_from_file_location(
        "_fdai_arb_readiness",
        _READINESS_MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the shared ARB readiness evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    validator = module.validate_contract
    if not callable(validator):
        raise RuntimeError("shared ARB readiness evaluator has no validator")
    return validator


validate_contract = _load_validator()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("config/architecture-review.yaml"),
        help="architecture-review manifest path",
    )
    parser.add_argument(
        "--require-production-ready",
        action="store_true",
        help="fail unless every production approval requirement is satisfied",
    )
    args = parser.parse_args()
    manifest_path = args.file if args.file.is_absolute() else _REPO_ROOT / args.file
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        validate_contract(raw, _REPO_ROOT, args.require_production_ready)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"check-arb-readiness: FAIL: {exc}")
        return 1

    mode = "production" if args.require_production_ready else "structure"
    print(f"check-arb-readiness: OK ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
