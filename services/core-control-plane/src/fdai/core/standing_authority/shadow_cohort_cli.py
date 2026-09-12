"""Strictly local-only CLI over the A3-E shadow cohort runner.

Usage
-----

.. code-block:: shell

    python -m fdai.core.standing_authority.shadow_cohort_cli \\
        --corpus <path-to-local-corpus.json> \\
        --output-dir <explicit-artifact-dir>

The CLI is a thin, offline harness over
:func:`~fdai.core.standing_authority.shadow_cohort_runner.run_cohort`. It exists so a
developer can reproduce the deterministic local cohort without hand-writing a driver.
It is **not** a governed cohort runner.

Safety properties, each covered by a focused test:

- **Local only.** The corpus document must declare ``venue="local"`` and
  ``evidence_class="synthetic_development"``, and the emitted receipt is asserted to
  carry those same values before it is written. The CLI refuses to run otherwise, so it
  can never manufacture runtime or governed evidence.
- **No network, Azure, provider, or registry reach.** This module and its decoder import
  no socket, HTTP, Azure, database, delivery, executor, or ``ActionPromotionRegistry``
  path. A static import test enforces that. ``run_cohort`` only *reads* the registry
  source file to digest it and prove it was not mutated.
- **Explicit bounded output.** ``--output-dir`` is required. The directory and every
  parent component are rejected if any is a symlink, and the written receipt path is
  asserted to resolve inside the resolved directory.
- **Bounded work.** The corpus decoder caps document bytes, case count, review count,
  and per-case and total declared elapsed time, and the CLI enforces its own monotonic
  wall-clock deadline.

Exit codes
----------

- ``0`` - the cohort ran and the receipt is complete with zero policy escapes.
- ``2`` - usage or corpus validation failure; nothing ran and nothing was written.
- ``3`` - the cohort ran but the receipt is incomplete or recorded a policy escape.
- ``4`` - the CLI exceeded its own wall-clock deadline.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError
from fdai.core.standing_authority.shadow_cohort_corpus import (
    LOCAL_EVIDENCE_CLASS,
    LOCAL_VENUE,
    MAX_CORPUS_BYTES,
    decode_corpus_document,
)
from fdai.core.standing_authority.shadow_cohort_runner import (
    CohortArtifactWriter,
    CohortReceipt,
    run_cohort,
)

#: Wall-clock ceiling for one CLI invocation, independent of the runner's own
#: deterministic total, no-progress, and per-case bounds.
CLI_DEADLINE_S: Final[float] = 120.0

EXIT_OK: Final[int] = 0
EXIT_USAGE: Final[int] = 2
EXIT_INCOMPLETE: Final[int] = 3
EXIT_DEADLINE: Final[int] = 4


class LocalCohortCliError(Exception):
    """Usage or containment failure that must stop the CLI before any write."""


def _resolve_output_dir(raw: str) -> Path:
    """Reject symlinked components and return the resolved artifact directory."""

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise LocalCohortCliError(f"output-dir component MUST NOT be a symlink: {component}")
    resolved = candidate.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise LocalCohortCliError(f"output-dir MUST be a directory: {resolved}")
    return resolved


def _read_corpus(raw: str) -> str:
    """Read the corpus document with symlink and size guards."""

    path = Path(raw)
    if path.is_symlink():
        raise LocalCohortCliError(f"corpus path MUST NOT be a symlink: {path}")
    if not path.is_file():
        raise LocalCohortCliError(f"corpus path MUST be an existing file: {path}")
    if path.stat().st_size > MAX_CORPUS_BYTES:
        raise LocalCohortCliError(f"corpus file exceeds {MAX_CORPUS_BYTES} bytes")
    return path.read_text(encoding="utf-8")


def _require_local_receipt(receipt: CohortReceipt) -> None:
    """Refuse to write anything that does not declare local synthetic evidence."""

    if receipt.venue != LOCAL_VENUE or receipt.evidence_class != LOCAL_EVIDENCE_CLASS:
        raise LocalCohortCliError(
            "refusing to write a receipt that is not local synthetic_development evidence"
        )
    if receipt.execution_authority is not False or receipt.promotion_authority is not False:
        raise LocalCohortCliError("refusing to write a receipt that claims authority")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai-a3e-local-cohort",
        description=(
            "Run the deterministic local A3-E shadow cohort. Local development evidence "
            "only; it cannot satisfy governed runtime promotion."
        ),
    )
    parser.add_argument("--corpus", required=True, help="Path to a local corpus JSON document.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Explicit directory that will receive the cohort receipt.",
    )
    parser.add_argument(
        "--deadline-s",
        type=float,
        default=CLI_DEADLINE_S,
        help=f"Wall-clock ceiling for this invocation (default {CLI_DEADLINE_S}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one local cohort and write its receipt. Returns the process exit code."""

    args = _parser().parse_args(argv)
    started = time.monotonic()

    if not (0.0 < args.deadline_s <= CLI_DEADLINE_S):
        print(
            f"error: --deadline-s MUST be in (0, {CLI_DEADLINE_S}]",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        output_dir = _resolve_output_dir(args.output_dir)
        document = _read_corpus(args.corpus)
        decoded = decode_corpus_document(document)
    except (
        # `CohortCorpusError` subclasses `AuthorizationLifecycleError`, but the
        # decoder also invokes `LifecycleFence`, `build_candidate_record`, and
        # `build_manifest`, which raise the parent type directly. Catching only the
        # subclass would surface a traceback and exit 1 instead of the documented
        # exit 2 for an in-bounds but invalid corpus.
        LocalCohortCliError,
        AuthorizationLifecycleError,
        OSError,
        UnicodeDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    receipt = run_cohort(
        decoded.manifest,
        decoded.corpus,
        decoded.per_case_elapsed_s,
    )

    if time.monotonic() - started > args.deadline_s:
        print("error: local cohort exceeded its wall-clock deadline", file=sys.stderr)
        return EXIT_DEADLINE

    try:
        _require_local_receipt(receipt)
        written = CohortArtifactWriter(output_dir).write_receipt(receipt)
    except (LocalCohortCliError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if written.resolve().parent != output_dir:
        print("error: receipt escaped the declared output directory", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"venue={receipt.venue} evidence_class={receipt.evidence_class} "
        f"receipt={written} complete={receipt.complete} "
        f"zero_policy_escapes={receipt.zero_policy_escapes}"
    )
    if not receipt.complete or not receipt.zero_policy_escapes:
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())


__all__ = [
    "CLI_DEADLINE_S",
    "EXIT_DEADLINE",
    "EXIT_INCOMPLETE",
    "EXIT_OK",
    "EXIT_USAGE",
    "LocalCohortCliError",
    "main",
]
