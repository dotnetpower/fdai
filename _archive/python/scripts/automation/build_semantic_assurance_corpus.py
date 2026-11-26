#!/usr/bin/env python3
"""Build a content-free, source-bound semantic assurance denominator."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fdai.core.conversation.question_perspectives import QuestionEvidencePosture
from fdai.core.conversation.question_universe import (
    QuestionUniverseGrammar,
    generate_question_universe,
)
from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.delivery.golden_question_dataset import load_golden_question_dataset
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release

_DATASET = Path("eval/golden-dataset")
_OUTPUT = _DATASET / "corpus-manifest.json"
_GOLDEN_FILES = (
    "coverage.json",
    "expectations.json",
    "questions.source.yaml",
    "questions.en.json",
    "questions.ko.json",
)
_OVERLAYS = (
    ("semantic_judgment", "semantic-judgment-assurance.json"),
    ("incident_intent", "azure-incident-intent-golden.yaml"),
)


def _digest(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _partition(kind: str, ids: list[str], **counts: object) -> dict[str, Any]:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{kind} contains duplicate case identities")
    return {
        "kind": kind,
        "case_count": len(ids),
        "case_ids_digest": _digest(sorted(ids)),
        **counts,
    }


def _overlay(root: Path, kind: str, name: str) -> dict[str, Any]:
    path = root / _DATASET / name
    payload = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.suffix == ".json"
        else yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError(f"{kind} overlay lacks cases")
    rows = payload["cases"]
    if not rows:
        raise ValueError(f"{kind} overlay has no cases")
    ids: list[str] = []
    locales: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError(f"{kind} overlay has an invalid case identity")
        locale = row.get("locale", "unclassified")
        if not isinstance(locale, str) or not locale:
            raise ValueError(f"{kind} overlay has an invalid locale")
        ids.append(f"{kind}:{row['id']}")
        locales[locale] += 1
    return _partition(kind, ids, locales=dict(sorted(locales.items())))


def _golden(root: Path) -> dict[str, Any]:
    corpus = load_golden_question_dataset(root / _DATASET)
    ids = [f"golden:{case.case_id}" for case in corpus.cases]
    locales = Counter(case.locale for case in corpus.cases)
    postures = Counter(case.evidence_posture.value for case in corpus.cases)
    styles = Counter(case.semantic_pair_id.rsplit(".", 1)[-1] for case in corpus.cases)
    expectations = {case.semantic_pair_id.split(".")[0] for case in corpus.cases}
    if len(styles) * len(locales) * len(expectations) != len(ids):
        raise ValueError("golden corpus does not cover each wording and locale")
    if any(
        {
            (case.semantic_pair_id.rsplit(".", 1)[-1], case.locale)
            for case in corpus.cases
            if case.semantic_pair_id.split(".")[0] == expectation
        }
        != {(style, locale) for style in styles for locale in locales}
        for expectation in expectations
    ):
        raise ValueError("golden corpus has a missing wording or locale")
    return _partition(
        "golden",
        ids,
        locales=dict(sorted(locales.items())),
        evidence_postures=dict(sorted(postures.items())),
        wording_styles=dict(sorted(styles.items())),
        source_digest=corpus.source_digest,
    )


def _declarations(root: Path) -> dict[str, Any]:
    catalog_root = root / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    functions = operational_function_types(catalog.function_types)
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=functions,
    )
    manifest = CatalogQueryManifestProvider(
        release=release,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interfaces=catalog.interface_types,
        functions=functions,
    ).manifest_for(
        principal=Principal(id="assurance-source-reader", role=Role.READER),
        purpose="operations-review",
    )
    if not manifest.coverage_receipt.complete:
        raise ValueError("semantic assurance declaration manifest is incomplete")
    ids: list[str] = []
    exclusions: set[str] = set()
    exclusions_by_posture: set[str] | None = None
    by_posture: dict[str, int] = {}
    grammar_digests: dict[str, str] = {}
    locales: Counter[str] = Counter()
    # The universe has a per-generation safety cap. Each posture is generated
    # independently so the complete denominator cannot be silently sampled.
    for posture in sorted(QuestionEvidencePosture, key=lambda item: item.value):
        grammar = QuestionUniverseGrammar.build(
            locales=("en", "ko"),
            evidence_postures=(posture,),
        )
        universe = generate_question_universe(manifests=(manifest,), grammar=grammar)
        grammar_digests[posture.value] = grammar.digest
        by_posture[posture.value] = len(universe.cases)
        for case in universe.cases:
            ids.append(f"declaration:{case.case_id}")
            locales[case.locale] += 1
        current_exclusions = {f"declaration:{item.case_id}" for item in universe.exclusions}
        if len(current_exclusions) != len(universe.exclusions):
            raise ValueError("declaration exclusions contain duplicate identities")
        if exclusions_by_posture is not None and exclusions_by_posture != current_exclusions:
            raise ValueError("declaration exclusions differ across evidence postures")
        exclusions_by_posture = current_exclusions
        exclusions.update(current_exclusions)
    return _partition(
        "declarations",
        ids,
        locales=dict(sorted(locales.items())),
        evidence_postures=by_posture,
        exclusion_count=len(exclusions),
        excluded_case_ids_digest=_digest(sorted(exclusions)),
        grammar_digests=grammar_digests,
        ontology_release_digest=release.digest,
        principal_manifest_digest=manifest.manifest_digest,
        readable_declaration_count=manifest.coverage_receipt.readable_declaration_count,
    )


def build_manifest(root: Path) -> dict[str, Any]:
    """Derive every repository-owned case partition without running a model."""

    dataset = root / _DATASET
    paths = (*_GOLDEN_FILES, *(name for _, name in _OVERLAYS))
    partitions = [_golden(root), _declarations(root)]
    partitions.extend(_overlay(root, kind, name) for kind, name in _OVERLAYS)
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "semantic_assurance_corpus_manifest",
        "evidence_kind": "repository_source_only",
        "operational_validation": False,
        "source_digests": {
            str((_DATASET / path).as_posix()): _file_digest(dataset / path) for path in paths
        },
        "partitions": partitions,
        "total_case_count": sum(int(part["case_count"]) for part in partitions),
        "total_exclusion_count": sum(int(part.get("exclusion_count", 0)) for part in partitions),
    }
    return {**body, "manifest_digest": _digest(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    payload = build_manifest(root)
    output = root / _OUTPUT
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != rendered:
            print("semantic-assurance-corpus: stale manifest", file=sys.stderr)
            return 1
    else:
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(output)
    print(
        "semantic-assurance-corpus: OK "
        f"(cases={payload['total_case_count']}, exclusions={payload['total_exclusion_count']}; "
        "repository source only)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
