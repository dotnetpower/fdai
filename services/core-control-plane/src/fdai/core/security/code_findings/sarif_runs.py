"""Per-run SARIF metadata used to judge whether two scans have equivalent coverage.

A finding's absence proves nothing unless the rescan used the same (or explicitly newer) tool and
rules, completed, was not truncated, and analyzed the file. This module extracts those facts from
each SARIF run without trusting any of them more than the document can support:

- ``execution_successful`` is ``None`` when the producer does not report it;
- ``analyzed_paths`` is empty when the producer does not list artifacts, which means coverage of
  any specific file is unknown rather than complete.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

_MAX_ARTIFACTS = 50_000


@dataclass(frozen=True, slots=True)
class RunMetadata:
    producer: str
    version: str
    declared_rules_digest: str
    execution_successful: bool | None
    truncated: bool
    analyzed_paths: tuple[str, ...]


def run_metadata(
    run: Mapping[str, object],
    producer: str,
    version: str,
    rule_ids: Sequence[str],
    normalize: Callable[[object], str | None],
) -> RunMetadata:
    """Return coverage facts for one SARIF run.

    ``rule_ids`` are the rules the driver declares, never the rules that produced results, so the
    digest does not change when findings change. Some producers declare only rules with results;
    the digest is therefore informative, and equivalence uses the caller-asserted rules version.
    ``normalize`` is the ingestion path normalizer, so artifact paths obey the same traversal and
    source-root rules as result locations.
    """
    invocations = run.get("invocations")
    successes = [
        invocation.get("executionSuccessful")
        for invocation in (invocations if isinstance(invocations, list) else [])[:16]
        if isinstance(invocation, Mapping)
    ]
    reported = [value for value in successes if isinstance(value, bool)]
    execution_successful = all(reported) if reported else None
    properties = run.get("properties")
    truncated = bool(isinstance(properties, Mapping) and properties.get("truncated") is True)
    artifacts = run.get("artifacts")
    paths: list[str] = []
    for artifact in (artifacts if isinstance(artifacts, list) else [])[:_MAX_ARTIFACTS]:
        location = artifact.get("location") if isinstance(artifact, Mapping) else None
        uri = location.get("uri") if isinstance(location, Mapping) else None
        path = normalize(uri)
        if path is not None:
            paths.append(path)
    if isinstance(artifacts, list) and len(artifacts) > _MAX_ARTIFACTS:
        truncated = True
    digest = hashlib.sha256("\n".join(sorted(set(rule_ids))).encode("utf-8")).hexdigest()
    return RunMetadata(
        producer=producer,
        version=version,
        declared_rules_digest=digest,
        execution_successful=execution_successful,
        truncated=truncated,
        analyzed_paths=tuple(sorted(set(paths))),
    )


__all__ = ["RunMetadata", "run_metadata"]
