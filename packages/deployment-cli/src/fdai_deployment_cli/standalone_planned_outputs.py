"""Read shared-root Terraform outputs that targeted applies do not persist.

Terraform writes a root output during ``apply -target`` only when that output depends on a
targeted resource. Outputs derived only from variables and locals, such as logical topic names,
stay absent from state even though their values are fully determined by the verified
configuration. When state lacks such an output, this module evaluates one refresh-free,
lock-free, non-targeted plan of the same root and accepts only outputs whose planned values are
known. Unknown values mean the backing resource was never applied, so readback fails closed.
The plan is read-only, private, cached per process, and deleted after evaluation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_MISSING = "not found"


@dataclass(frozen=True, slots=True)
class _Source:
    variables: Path
    data_dir: Path


_SOURCES: dict[Path, _Source] = {}
_CACHE: dict[Path, dict[str, object]] = {}


def bind(infra: Path, *, variables: Path, data_dir: Path) -> None:
    """Allow planned-output evaluation for one shared root with its exact inputs."""

    _SOURCES[infra.resolve()] = _Source(variables=variables, data_dir=data_dir)


def read_output(infra: Path, name: str, *, raw: bool, reason: str) -> object:
    """Return a state output, or a known planned value when state never recorded it."""

    command = ("terraform", "output", "-raw" if raw else "-json", name)
    result = subprocess.run(
        command, cwd=infra, check=False, capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        return result.stdout.strip() if raw else _json(result.stdout)
    source = _SOURCES.get(infra.resolve())
    if source is None or _MISSING not in result.stderr:
        raise ValueError(reason)
    outputs = _CACHE.get(infra.resolve())
    if outputs is None:
        outputs = _planned_outputs(infra, source)
        _CACHE[infra.resolve()] = outputs
    if name not in outputs:
        raise ValueError(f"{reason}: output is unknown until its resource is applied")
    value = outputs[name]
    if not raw:
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | float):
        return str(value)
    raise ValueError(f"{reason}: output is not a primitive value")


def _planned_outputs(infra: Path, source: _Source) -> dict[str, object]:
    environment = {**os.environ, "TF_DATA_DIR": str(source.data_dir)}
    scratch = Path(tempfile.mkdtemp(prefix="planned-outputs-", dir=source.variables.parent))
    plan = scratch / "outputs.tfplan"
    try:
        planned = subprocess.run(
            (
                "terraform",
                "plan",
                "-refresh=false",
                "-lock=false",
                "-input=false",
                "-no-color",
                f"-var-file={source.variables}",
                f"-out={plan}",
            ),
            cwd=infra,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if planned.returncode != 0:
            raise ValueError("planned Terraform output evaluation failed")
        shown = subprocess.run(
            ("terraform", "show", "-json", str(plan)),
            cwd=infra,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if shown.returncode != 0:
            raise ValueError("planned Terraform output evaluation failed")
        document = _json(shown.stdout)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if not isinstance(document, dict):
        raise ValueError("planned Terraform output document is invalid")
    return known_planned_outputs(document)


def known_planned_outputs(document: dict[str, object]) -> dict[str, object]:
    """Select planned root outputs whose values are fully known."""

    planned = document.get("planned_values")
    changes = document.get("output_changes")
    outputs = planned.get("outputs") if isinstance(planned, dict) else None
    if not isinstance(outputs, dict) or not isinstance(changes, dict):
        raise ValueError("planned Terraform output document is invalid")
    known: dict[str, object] = {}
    for name, output in outputs.items():
        change = changes.get(name)
        if not isinstance(output, dict) or "value" not in output:
            continue
        if isinstance(change, dict) and _has_unknown(change.get("after_unknown")):
            continue
        known[str(name)] = output["value"]
    return known


def _has_unknown(marker: object) -> bool:
    if isinstance(marker, dict):
        return any(_has_unknown(item) for item in marker.values())
    if isinstance(marker, list):
        return any(_has_unknown(item) for item in marker)
    return marker is True


def _json(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Terraform JSON output is invalid") from exc


__all__ = ["bind", "known_planned_outputs", "read_output"]
