#!/usr/bin/env python3
"""Keep venue selection inside one contract.

FDAI-CONST-001 allows a venue to differ only in credentials, endpoints, scale, and provider
scope. That is provable only while every venue-selected binding is enumerated in one place.
Before `fdai_service_contracts/venue.py` existed, each service read `FDAI_EXECUTION_VENUE`
with its own default and compared its own literals, so a new venue-sensitive capability could
appear anywhere and no check would fail.

This gate fails when the environment variable is read, or a venue literal is compared,
anywhere under a scanned source tree except that tree's declared contract module. The core
control plane's `runtime/venue.py` re-exports the shared contract, so it is exempt in the
same way the shared module is.

Its detection is textual and therefore deliberately narrow: it catches the two shapes that
actually existed before the contract (an environment read and an equality comparison). A
sufficiently indirect reintroduction can evade it, which is why the contract also exposes
the only supported entry points rather than relying on this gate alone.

Exit codes: 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: Every source tree that composes an FDAI process, mapped to the one module allowed to
#: resolve the venue inside it, or ``None`` when the tree has no exempt module and must read
#: the shared contract. A service absent from this mapping is unscanned, so a new service
#: must be added here when it is created.
SCANNED_TREES: dict[Path, Path | None] = {
    ROOT / "packages/service-contracts/src/fdai_service_contracts": (
        ROOT / "packages/service-contracts/src/fdai_service_contracts/venue.py"
    ),
    ROOT / "services/core-control-plane/src/fdai": (
        ROOT / "services/core-control-plane/src/fdai/runtime/venue.py"
    ),
    ROOT / "services/operator-service/src/fdai_operator_service": None,
    ROOT / "services/document-ingestion-api/src/fdai_ingestion_api_service": None,
    ROOT / "services/document-processing-worker/src/fdai_document_worker_service": None,
    ROOT / "services/isolated-executor/src/fdai_executor_service": None,
}

_ENV_READ = re.compile(r"FDAI_EXECUTION_VENUE")
_VENUE_COMPARISON = re.compile(r"""(?:==|!=)\s*["'](?:local|deployed)["']""")


def _display(path: Path) -> str:
    """Return a repo-relative path when possible, so findings stay readable."""

    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _violations(source_root: Path, contract: Path | None) -> list[str]:
    findings: list[str] = []
    contract_hint = (
        _display(contract) if contract is not None else "fdai_service_contracts/venue.py"
    )
    for path in sorted(source_root.rglob("*.py")):
        if path == contract or "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            relative = _display(path)
            if _ENV_READ.search(line):
                findings.append(
                    f"{relative}:{number}: reads FDAI_EXECUTION_VENUE directly; "
                    f"use resolve_execution_venue() from {contract_hint}"
                )
            if _VENUE_COMPARISON.search(line):
                findings.append(
                    f"{relative}:{number}: compares a venue literal; "
                    f"use ExecutionVenue and select_capability() instead"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Scan one directory instead of every declared source tree.",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="The one module allowed to resolve the venue in --source-root.",
    )
    args = parser.parse_args(argv)

    if args.source_root is not None:
        trees = {args.source_root.resolve(): args.contract.resolve() if args.contract else None}
    else:
        trees = {root: contract for root, contract in SCANNED_TREES.items()}

    findings: list[str] = []
    for root, contract in trees.items():
        if not root.is_dir():
            print(f"venue-capability-contract: FAILED - missing source tree {_display(root)}")
            return 1
        if contract is not None and not contract.exists():
            print(
                f"venue-capability-contract: FAILED - missing contract module {_display(contract)}"
            )
            return 1
        findings.extend(_violations(root, contract))

    if findings:
        for finding in findings:
            print(f"venue-capability-contract: {finding}")
        print(f"venue-capability-contract: FAILED with {len(findings)} violation(s).")
        return 1
    print(f"venue-capability-contract: OK across {len(trees)} source tree(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
