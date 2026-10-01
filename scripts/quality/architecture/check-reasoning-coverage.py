#!/usr/bin/env python3
"""Ratchet the deterministic ontology reasoning coverage receipt.

The receipt compiles every closed question-form factor cell against the reviewed
production manifest. The gate fails when the set of compiled cells or the
unsupported-reason histogram differs from the committed baseline, so coverage
changes are always reviewed. ``--write-baseline`` refreshes the baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/core-control-plane/src"))
sys.path.insert(0, str(ROOT / "packages/service-contracts/src"))

import yaml  # noqa: E402
from fdai.composition.semantic_query_instance_candidates import (  # noqa: E402
    declare_instance_candidate_query,
)
from fdai.composition.semantic_query_value_domains import (  # noqa: E402
    resource_type_value_domains,
)
from fdai.core.conversation.semantic_manifest import ConceptVocabularies  # noqa: E402
from fdai.core.conversation.semantic_reasoning_coverage import (  # noqa: E402
    reasoning_coverage_receipt,
)
from fdai.core.ontology_platform import OntologyQueryPlanVerifier  # noqa: E402
from fdai.core.ontology_platform.operational_functions import (  # noqa: E402
    operational_function_types,
)
from fdai.core.ontology_platform.query_manifest import build_query_manifest  # noqa: E402
from fdai.core.ontology_platform.query_metric_handlers import (  # noqa: E402
    METRIC_ARGUMENT_SCHEMAS,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog  # noqa: E402
from fdai.rule_catalog.schema.resource_type import (  # noqa: E402
    load_resource_type_registry_from_mapping,
)
from fdai.runtime.metric_semantic_catalog import load_metric_semantic_registry  # noqa: E402
from fdai.shared.contracts.models import CeilingRole  # noqa: E402
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402
from fdai.shared.ontology.release import build_ontology_release  # noqa: E402
from fdai_service_contracts.ontology_query import QueryNodeKind  # noqa: E402

BASELINE = ROOT / "scripts/quality/architecture/reasoning-coverage-baseline.json"
EVALUATION_TIME = datetime(2026, 9, 28, 12, tzinfo=UTC)
DEFAULT_LOOKBACK_SECONDS = 86_400


def _receipt() -> dict[str, object]:
    root = ROOT / "rule-catalog"
    catalog = declare_instance_candidate_query(
        load_ontology_catalog(
            root,
            schema_registry=PackageResourceSchemaRegistry(),
            probes_root=root / "probes" if (root / "probes").is_dir() else None,
        )
    )
    functions = operational_function_types(catalog.function_types)
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=functions,
    )
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load((root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8"))
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        interfaces=catalog.interface_types,
        action_types=catalog.action_types,
        functions=functions,
        bound_function_names=tuple(function.name for function in functions),
        property_values=resource_type_value_domains(registry),
        property_reads=ConceptVocabularies(
            property_semantics=catalog.property_semantics
        ).property_reads(),
    )
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            QueryNodeKind.TYPED_PATH,
            QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
            QueryNodeKind.FUNCTION,
            QueryNodeKind.UNION,
            QueryNodeKind.AGGREGATE,
            QueryNodeKind.PROJECT,
            QueryNodeKind.METRIC_SCOPE_SERIES,
            QueryNodeKind.METRIC_COMPARISON,
        ),
        reviewed_metric_concepts=tuple(
            sorted(
                load_metric_semantic_registry(
                    root / "vocabulary" / "metric-semantics.yaml"
                ).definitions
            )
        ),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
                QueryNodeKind.METRIC_SCOPE_SERIES
            ],
            QueryNodeKind.METRIC_COMPARISON: METRIC_ARGUMENT_SCHEMAS[
                QueryNodeKind.METRIC_COMPARISON
            ],
        },
    )
    receipt = reasoning_coverage_receipt(
        manifest=manifest,
        verifier=verifier,
        purpose="operations-review",
        evaluation_time=EVALUATION_TIME,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )
    return {
        "version": 1,
        "cells": len(receipt.cells),
        "status_counts": receipt.status_counts,
        "reason_counts": receipt.reason_counts,
        "compiled_cells": list(receipt.compiled_cells),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    current = _receipt()
    if args.write_baseline:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"reasoning-coverage: baseline written ({current['cells']} cells)")
        return 0
    try:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"reasoning-coverage: ERROR: baseline unreadable: {type(exc).__name__}")
        return 1
    lost = sorted(set(baseline.get("compiled_cells", ())) - set(current["compiled_cells"]))  # type: ignore[arg-type]
    gained = sorted(set(current["compiled_cells"]) - set(baseline.get("compiled_cells", ())))  # type: ignore[arg-type]
    if lost:
        print("reasoning-coverage: ERROR: cells no longer compile: " + ", ".join(lost[:20]))
        return 1
    if current != baseline:
        detail = f"; newly compiled: {', '.join(gained[:20])}" if gained else ""
        print(
            "reasoning-coverage: ERROR: coverage changed; review it and run "
            f"--write-baseline{detail}"
        )
        return 1
    counts = current["status_counts"]
    print(f"reasoning-coverage: OK ({current['cells']} cells; {counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
