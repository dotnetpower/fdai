"""CLI validator for exemption artifacts.

Used by CI (`.github/workflows/ci.yml`) to validate every JSON file under
``rule-catalog/exemptions/`` against the schema + model invariants.

Non-zero exit code on any invalid file; prints every issue for every file
before exiting so a reviewer can fix them all at once.

Usage
-----

.. code-block:: shell

    python -m fdai.rule_catalog.schema.exemption_cli \\
        rule-catalog/exemptions/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .exemption import ExemptionError, load_exemption_from_mapping


def _load_json_file(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fdai-exemption-check",
        description=__doc__,
    )
    parser.add_argument("files", nargs="+", type=Path, help="Exemption JSON files.")
    args = parser.parse_args(argv)

    failures = 0
    for path in args.files:
        try:
            raw = _load_json_file(path)
            load_exemption_from_mapping(raw)
        except FileNotFoundError:
            print(f"[FAIL] {path}: file not found", file=sys.stderr)
            failures += 1
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"[FAIL] {path}: {exc}", file=sys.stderr)
            failures += 1
        except ExemptionError as exc:
            print(f"[FAIL] {path}: exemption validation failed", file=sys.stderr)
            for issue in exc.issues:
                print(f"    - {issue.key}: {issue.message}", file=sys.stderr)
            failures += 1
        else:
            print(f"[OK] {path}")

    if failures:
        print(f"\nexemption-check: FAILED - {failures} file(s) invalid.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - invoked via `python -m`
    raise SystemExit(main())
