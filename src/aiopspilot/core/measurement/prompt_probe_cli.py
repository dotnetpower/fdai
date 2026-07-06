"""Recognition-probe CLI entry point (Wave 3 step D-2b-ii-gamma-2).

Loads scenarios from a catalog root, wires a default composer, and
delegates to :func:`run_scenarios` with a fork-supplied responder
(or the upstream :class:`AbstainResponder`). The report gets emitted
as one JSON row per KPI on stdout so a shipping runner can pipe it
into any metric sink without re-serialising.

Usage
-----

.. code-block:: shell

    AIOPSPILOT_CATALOG_ROOT=/path/to/rule-catalog \\
        python -m aiopspilot.core.measurement.prompt_probe_cli

Exit codes
----------

- ``0`` - run completed. Passing / failing scenarios are recorded in
  the emitted KPI rows; a scenario failure is a data outcome, not an
  operational error, so the CLI still exits ``0``.
- ``2`` - catalog root not resolvable (env var missing AND no
  walk-up found a ``rule-catalog`` sibling).
- ``3`` - unexpected exception; the traceback is on stderr for the
  container's log surface.

Contract with the composition root
----------------------------------

A fork wires its own responder by importing :func:`run_from_catalog`
and passing a live :class:`ScenarioResponder`; the upstream CLI is
smoke-only and never touches an Azure endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Final

from aiopspilot.core.measurement.prompt_probe_emit import emit_kpi_rows
from aiopspilot.core.measurement.prompt_probe_loader import load_scenarios
from aiopspilot.core.measurement.prompt_probe_runner import (
    RecognitionRunReport,
    ScenarioResponder,
    run_scenarios,
)
from aiopspilot.core.measurement.prompt_probe_testing import AbstainResponder
from aiopspilot.core.prompts import (
    DefaultPromptComposer,
    FileSystemPromptRegistry,
)

_LOGGER = logging.getLogger("aiopspilot.core.measurement.prompt_probe_cli")
_ENV_CATALOG_ROOT: Final[str] = "AIOPSPILOT_CATALOG_ROOT"


def resolve_catalog_root() -> Path:
    """Locate the ``rule-catalog/`` tree.

    Discovery order:
      1. ``AIOPSPILOT_CATALOG_ROOT`` env var, if it points at a real dir.
      2. Walk up from this module until a ``rule-catalog/`` sibling with a
         ``prompts/`` subdirectory is found.
      3. Raise :class:`FileNotFoundError` - the CLI cannot proceed without
         a catalog.
    """

    override = os.environ.get(_ENV_CATALOG_ROOT)
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"{_ENV_CATALOG_ROOT}={override!r} is not a directory")
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / "rule-catalog"
        if (cand / "prompts").is_dir():
            return cand
    raise FileNotFoundError(
        "could not locate rule-catalog/. Set AIOPSPILOT_CATALOG_ROOT to point "
        "at the tree explicitly."
    )


async def run_from_catalog(
    catalog_root: Path,
    *,
    responder: ScenarioResponder,
) -> RecognitionRunReport:
    """Wire a composer + registry from ``catalog_root`` and run every scenario.

    Kept exported so a fork's test suite can drive the same pipeline
    without shelling out to the CLI.
    """

    prompt_registry = FileSystemPromptRegistry(catalog_root)
    composer = DefaultPromptComposer(registry=prompt_registry)
    scenarios = load_scenarios(catalog_root)
    return await run_scenarios(composer=composer, responder=responder, scenarios=scenarios)


def _row_to_json_line(row: object) -> str:
    """Render one :class:`KpiRow` as a canonical JSON line."""

    # ``row.metric`` etc. are attributes on a frozen dataclass;
    # ``row.unit.value`` unwraps the StrEnum so the JSON is
    # renderer-portable (no Python type in the wire).
    return json.dumps(
        {
            "metric": row.metric,  # type: ignore[attr-defined]
            "value": row.value,  # type: ignore[attr-defined]
            "unit": row.unit.value,  # type: ignore[attr-defined]
            "dimensions": dict(row.dimensions),  # type: ignore[attr-defined]
        },
        sort_keys=True,
    )


async def _main() -> int:
    try:
        catalog_root = resolve_catalog_root()
    except FileNotFoundError as exc:
        _LOGGER.error("prompt_probe_catalog_not_found: %s", exc)
        return 2

    responder = AbstainResponder()
    report = await run_from_catalog(catalog_root, responder=responder)
    rows = emit_kpi_rows(report, dimensions={"cli": "prompt_probe"})
    for row in rows:
        sys.stdout.write(_row_to_json_line(row))
        sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def main() -> int:
    """Synchronous entrypoint for ``python -m ...`` and test invocations."""

    try:
        return asyncio.run(_main())
    except Exception:  # noqa: BLE001 - CLI top-level: log + exit code
        _LOGGER.exception("prompt_probe_cli_unexpected_error")
        return 3


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    sys.exit(main())
