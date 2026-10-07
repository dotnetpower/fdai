"""Measure LLM lens hypothesis precision on a labeled public benchmark and write a receipt.

The source is acquired at its exact commit, read-only, with the scan job's acquirer. Only the
deterministic sample of labeled test files is copied into an owner-only scratch root, so the lens
lane cannot select excerpts from unlabeled code. The lens catalog is narrowed to the corpus's
lenses; prompts, hints, and limits are unchanged. ``--dry-run`` selects candidates and reports the
model calls a live run would need without calling any model. Every kept hypothesis is labeled in
the receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from fdai.core.security.code_findings.lens import LensLaneReport, run_lens_lane, select_candidates
from fdai.core.security.code_findings.lens_evaluation import (
    LabeledFile,
    LensCorpus,
    LensCorpusError,
    label_hypotheses,
    lens_corpus_from_mapping,
    lens_metrics,
    parse_labels,
    select_sample,
)
from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.code_security_scan_cli import open_lens_models
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security_lenses import LensCatalog, load_lens_catalog

_MAX_LABEL_BYTES = 2_000_000


def add_lens_evaluation_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    root = repo_asset_root() / "rule-catalog" / "code-security"
    command = sub.add_parser(
        "evaluate-lens", help="measure LLM lens precision on a labeled public benchmark"
    )
    command.add_argument("--corpus", default=str(root / "evaluation" / "lens-corpus.yaml"))
    command.add_argument("--work-root", required=True)
    command.add_argument(
        "--lens-model",
        action="append",
        default=[],
        help="FAMILY=ENDPOINT|DEPLOYMENT; two or more distinct families are required",
    )
    command.add_argument(
        "--lens-identity",
        choices=["managed-identity", "azure-cli"],
        default="managed-identity",
        help="identity for lens model calls; azure-cli is for local development only",
    )
    command.add_argument(
        "--dry-run",
        action="store_true",
        help="select candidates and count model calls without calling any model",
    )
    command.add_argument("--output", help="write the receipt to this file")
    command.add_argument("--catalog-root", default=str(root))


def narrow_catalog(catalog: LensCatalog, corpus: LensCorpus) -> LensCatalog:
    """Return the lens catalog restricted to the corpus lenses, otherwise unchanged."""
    return catalog.model_copy(
        update={"lenses": {lens: catalog.lenses[lens] for lens in corpus.lenses}}
    )


def stage_sample(source: Path, sample: tuple[LabeledFile, ...], stage: Path) -> None:
    """Copy exactly the sampled files into ``stage`` under their repository paths."""
    for item in sample:
        origin = (source / item.path).resolve()
        if not origin.is_relative_to(source.resolve()) or not origin.is_file():
            raise LensCorpusError(f"labels: sampled file {item.path} is missing")
        target = stage / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)


def _read_labels(source: Path, corpus: LensCorpus) -> str:
    path = (source / corpus.labels_path).resolve()
    if not path.is_relative_to(source.resolve()) or not path.is_file():
        raise LensCorpusError(f"source: label file {corpus.labels_path} is missing")
    if path.stat().st_size > _MAX_LABEL_BYTES:
        raise LensCorpusError("source: label file exceeds the size limit")
    return path.read_text(encoding="utf-8")


async def _measure(
    args: argparse.Namespace, corpus: LensCorpus, catalog: LensCatalog
) -> dict[str, object]:
    acquired = GitSourceAcquirer(Path(args.work_root).resolve()).acquire(
        corpus.repository, corpus.commit
    )
    sample = select_sample(parse_labels(_read_labels(acquired.path, corpus), corpus), corpus)
    lens_classes = {lens_id: lens.weakness_class for lens_id, lens in catalog.lenses.items()}
    stage = Path(tempfile.mkdtemp(prefix="fdai-lens-eval-"))
    try:
        stage.chmod(0o700)
        stage_sample(acquired.path, sample, stage)
        if args.dry_run:
            report = LensLaneReport()
            candidates = select_candidates(stage, catalog, report)
            return {
                "dry_run": True,
                "sample_files": len(sample),
                "candidates": len(candidates),
                "model_calls_needed_per_model": len(candidates),
                "max_model_calls": catalog.limits.max_model_calls,
                "candidates_dropped_by_limit": report.candidates_dropped_by_limit,
            }
        async with open_lens_models(args.lens_model, catalog, args.lens_identity) as models:
            occurrences, report = await run_lens_lane(
                stage, catalog, models, revision=corpus.commit
            )
            families = sorted({model.identity.family for model in models})
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    labels = label_hypotheses(occurrences, sample, lens_classes)
    metrics = lens_metrics(labels, sample, list(lens_classes.values()))
    true_positives = sum(1 for item in labels if item.true_positive)
    return {
        "dry_run": False,
        "model_families": families,
        "sample_files": len(sample),
        "lane": {
            "complete": report.complete,
            "candidates_selected": report.candidates_selected,
            "candidates_reviewed": report.candidates_reviewed,
            "model_calls": report.model_calls,
            "model_errors": report.model_errors,
            "rejected_ungrounded": report.rejected_ungrounded,
            "rejected_cwe": report.rejected_cwe,
            "rejected_quorum": report.rejected_quorum,
            "kept": report.kept,
            "notes": list(report.notes),
        },
        "overall": {
            "kept": len(labels),
            "true_positives": true_positives,
            "false_positives": len(labels) - true_positives,
            "precision": round(true_positives / len(labels), 4) if labels else None,
        },
        "classes": [item.as_dict() for item in metrics],
        "hypotheses": [item.as_dict() for item in labels],
    }


def evaluate_lens(args: argparse.Namespace) -> dict[str, object]:
    """Run the lens precision evaluation and return the receipt."""
    full = load_lens_catalog(Path(args.catalog_root))
    lens_classes = {lens_id: lens.weakness_class for lens_id, lens in full.lenses.items()}
    corpus = lens_corpus_from_mapping(
        yaml.safe_load(Path(args.corpus).read_text(encoding="utf-8")), lens_classes
    )
    catalog = narrow_catalog(full, corpus)
    measured = asyncio.run(_measure(args, corpus, catalog))
    lane = measured.get("lane")
    complete = isinstance(lane, dict) and bool(lane.get("complete"))
    receipt: dict[str, object] = {
        "ok": bool(measured["dry_run"]) or complete,
        "kind": "fdai.code-security.lens-evaluation-receipt",
        "corpus": {
            "id": corpus.corpus_id,
            "version": corpus.version,
            "digest": corpus.digest,
            "source": corpus.source_id,
            "commit": corpus.commit,
            "license": corpus.license,
        },
        "lens_catalog_version": catalog.version,
        "lenses": list(corpus.lenses),
        **measured,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    if args.output:
        Path(args.output).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


__all__ = ["add_lens_evaluation_command", "evaluate_lens", "narrow_catalog", "stage_sample"]
