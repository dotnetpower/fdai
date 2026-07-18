#!/usr/bin/env python3
"""Full catalog + repo validation for overnight-safe runs.

Purpose
=======

One entry point that exhaustively re-runs every guarantee this repo
makes on itself, collects every failure (does not fail-fast), and
writes a machine-parseable report + a human log. Safe to run
unattended: no network calls, no writes outside ``logs/validation/``,
no changes to committed state.

What it runs (in order)
-----------------------

* env_snapshot          - python, git SHA, catalog counts
* hygiene_gates         - the 6 ``scripts/check-*.sh`` gates
* ruff_check            - ``ruff check .``
* ruff_format           - ``ruff format --check .``
* mypy_src              - ``mypy src`` (strict)
* pytest_full           - ``pytest -q --no-cov`` (full suite, incl. the
                          new L1/L4/L10 catalog tests)
* rule_deep             - schema + id-unique + provenance-pin +
                          action_type ref for every rule in
                          ``catalog/`` and ``collected/``
* profile_deep          - schema + strict resolve against real known
                          rule ids + extends dag for every profile
* action_type_deep      - schema + argument_schema is valid draft-2020-12
                          + shadow default => promotion_gate present
* remediation_deep      - schema + action_type_id points to an existing
                          action-type
* risk_classification   - ordering invariant (deny -> hil -> auto)
                          + every action_type_id reference is real
* source_manifests      - every ``rule-catalog/sources/*/manifest.yaml``
                          pins a real 40-hex revision (not all-zero)
* cross_check_azure     - (if /tmp/azure-policy-clone at pinned SHA)
                          every imported azure-builtin rule maps back
                          to a real upstream policy definition GUID
* cross_check_kube      - (if /tmp/kube-bench-clone at pinned SHA)
                          every imported kube-bench rule maps back to
                          a real upstream check id

Report
------

``logs/validation/<UTC timestamp>/report.json``  - one entry per step
``logs/validation/<UTC timestamp>/report.log``   - human-readable log
``logs/validation/<UTC timestamp>/pytest.out``   - full pytest output
``logs/validation/<UTC timestamp>/mypy.out``     - full mypy output

Only the ``--keep`` most recent timestamped runs under
``logs/validation/`` are kept; older ones are pruned automatically at
the start of the next run. Default keep count is 10. Disable pruning
with ``--keep 0`` or by passing ``--report-dir``.

Exit code: 0 when every step passes; 1 when at least one step
recorded a failure (details in ``report.json``).

Usage
-----

    .venv/bin/python scripts/catalog/validate-catalog-full.py

Optional::

    --skip pytest,mypy_src          # skip named steps
    --only rule_deep,profile_deep   # run only named steps
    --report-dir logs/my-run        # override report directory
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from catalog_validation import catalog_steps as _catalog_steps
from catalog_validation import common as _common
from catalog_validation.catalog_steps import (
    step_action_type_deep,
    step_profile_deep,
    step_remediation_deep,
    step_risk_classification,
    step_rule_deep,
)
from catalog_validation.common import (
    REPO_ROOT,
    Runner,
    StepResult,
)
from catalog_validation.cross_checks import (
    step_cross_check_azure,
    step_cross_check_kube,
    step_source_manifests,
)
from catalog_validation.tool_steps import (
    step_env_snapshot,
    step_hygiene_gates,
    step_mypy_src,
    step_pytest_full,
    step_ruff_check,
    step_ruff_format,
)

# Compatibility surface for file-based importers of the former monolithic script.
ACTION_TYPES_DIR = _common.ACTION_TYPES_DIR
CATALOG_DIRS = _common.CATALOG_DIRS
CATALOG_ROOT = _common.CATALOG_ROOT
PROFILES_DIR = _common.PROFILES_DIR
REMEDIATION_DIR = _common.REMEDIATION_DIR
RISK_CLASSIFICATION = _common.RISK_CLASSIFICATION
SCHEMA_ROOT = _common.SCHEMA_ROOT
SOURCES_DIR = _common.SOURCES_DIR
_FDAI_ID_RE = _catalog_steps._FDAI_ID_RE
_SHA_RE = _catalog_steps._SHA_RE
_ZERO_SHA = _catalog_steps._ZERO_SHA
_iter_rule_files = _common.iter_rule_files
_load_schema = _common.load_schema
_load_yaml = _common.load_yaml
_run_subprocess = _common.run_subprocess

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


ALL_STEPS: list[tuple[str, Callable[[Runner], StepResult]]] = [
    ("env_snapshot", step_env_snapshot),
    ("hygiene_gates", step_hygiene_gates),
    ("ruff_check", step_ruff_check),
    ("ruff_format", step_ruff_format),
    ("mypy_src", step_mypy_src),
    ("pytest_full", step_pytest_full),
    ("rule_deep", step_rule_deep),
    ("profile_deep", step_profile_deep),
    ("action_type_deep", step_action_type_deep),
    ("remediation_deep", step_remediation_deep),
    ("risk_classification", step_risk_classification),
    ("source_manifests", step_source_manifests),
    ("cross_check_azure", step_cross_check_azure),
    ("cross_check_kube", step_cross_check_kube),
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--only", default="", help="Comma-separated step names to run")
    p.add_argument("--skip", default="", help="Comma-separated step names to skip")
    p.add_argument(
        "--report-dir",
        default=None,
        help="Directory to write report.{json,log} into (default: logs/validation/<ts>)",
    )
    p.add_argument(
        "--keep",
        type=int,
        default=10,
        help="When using the default report dir, keep this many most-recent runs "
        "and delete older ones (default: 10; set to 0 to disable pruning)",
    )
    return p.parse_args()


_TS_RE = re.compile(r"^\d{8}T\d{6}Z$")


def _prune_old_reports(root: Path, keep: int) -> list[Path]:
    """Delete all but the most recent ``keep`` timestamped subdirs of ``root``.

    Only entries whose name matches the ``YYYYMMDDTHHMMSSZ`` format the runner
    itself emits are considered - foreign files or directories are left alone.
    Returns the list of directories that were removed.
    """

    if keep <= 0 or not root.is_dir():
        return []
    runs = sorted(
        (p for p in root.iterdir() if p.is_dir() and _TS_RE.match(p.name)),
        key=lambda p: p.name,
    )
    if len(runs) <= keep:
        return []
    removed: list[Path] = []
    for old in runs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old)
    return removed


def main() -> int:
    args = _parse_args()
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    skip = {n.strip() for n in args.skip.split(",") if n.strip()}
    unknown = (only | skip) - {name for name, _ in ALL_STEPS}
    if unknown:
        print(f"unknown step names: {sorted(unknown)}", file=sys.stderr)
        return 2

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    using_default_dir = args.report_dir is None
    default_root = REPO_ROOT / "logs" / "validation"
    report_dir = Path(args.report_dir) if args.report_dir else default_root / ts
    report_dir.mkdir(parents=True, exist_ok=True)
    if using_default_dir:
        removed = _prune_old_reports(default_root, args.keep)
        for old in removed:
            print(f"[retention] pruned old validation run {old.name}", flush=True)
    runner = Runner(report_dir=report_dir)

    # Ensure ruff / mypy / pytest are installed - fail early otherwise.
    for tool in [".venv/bin/ruff", ".venv/bin/mypy", ".venv/bin/pytest"]:
        if not (REPO_ROOT / tool).is_file():
            print(f"missing {tool} - run `uv sync --extra dev` first", file=sys.stderr)
            return 2
    if not shutil.which("git"):
        print("git not found on PATH", file=sys.stderr)
        return 2

    for name, fn in ALL_STEPS:
        if only and name not in only:
            continue
        if name in skip:
            runner.steps.append(
                StepResult(
                    name=name, ok=True, duration_s=0.0, skipped=True, skipped_reason="--skip"
                )
            )
            continue
        runner.run(name, fn)

    runner.write_report()
    print(f"\nreport written to {report_dir}")
    failed = sum(1 for s in runner.steps if not s.ok and not s.skipped)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
