"""Operator CLI for code-security findings and remediation packs.

Commands:

``export``        ingest SARIF, build canonical issues, check the coding-agent provider gate,
                  sign the pack when a key is given, write it, and record it in the registry;
``revoke``        revoke a pack so FDAI rejects its results;
``import-result`` validate a returned result against the registry record;
``verify-fixes``  verify fix claims with a coverage-equivalent rescan;
``adjudicate``    record a human decision on a false-positive claim;
``publish-review`` publish a scan review through Heimdall and plan notifications;
``scan``          run the deterministic lane in the sandbox against one revision;
``evaluate``      measure dedup, severity, and rescan matching on a labeled corpus;
``evaluate-verifiers`` measure weakness-verifier precision on pinned public projects;
``public-key``    print the pack-signing public key that developers pin.

Example::

    python -m fdai.delivery.code_security_cli export \\
        --sarif mdash.sarif:external --sarif opengrep.sarif:deterministic \\
        --revision <40-hex commit> --repo-alias payments-api \\
        --provider example-coding-agent --provider-policy providers.yaml \\
        --signing-key pack-signing.pem --registry ./registry --out ./packs

Apart from the opt-in ``scan --lens-model`` review, the CLI performs no network calls. It grants
no execution authority.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from fdai.core.security.code_findings import (
    AnalysisContext,
    Lane,
    Occurrence,
    PackMode,
    PackRecord,
    PackRequest,
    ProjectRoot,
    RemediationResultRejectedError,
    SarifIngestContext,
    SarifIngestError,
    SarifIngestResult,
    build_issues,
    ingest_sarif,
    render_remediation_pack,
)
from fdai.core.security.code_findings.adjudication import AdjudicationError
from fdai.core.security.code_findings.evaluation import (
    EvaluationCorpusError,
    acceptance_failures,
    corpus_from_mapping,
    evaluate,
    split_corpus,
)
from fdai.core.security.code_findings.export_gate import (
    AgentProviderPolicy,
    ExportDeniedError,
    authorize_export,
)
from fdai.core.security.code_findings.receipts import (
    baseline_to_dict,
    build_receipt,
    receipt_to_dict,
)
from fdai.core.security.code_findings.verifier import (
    taint_rule_verifications,
    verified_confidence,
    verify_issues,
)
from fdai.core.security.code_findings.verifier_evaluation import VerifierCorpusError
from fdai.delivery.code_security_acquire import GitSourceAcquirer, SourceAcquisitionError
from fdai.delivery.code_security_publish_cli import add_publish_command, publish_review
from fdai.delivery.code_security_review_cli import (
    add_review_commands,
    adjudicate,
    import_result,
    pairs,
    verify_fixes,
)
from fdai.delivery.code_security_scan_cli import add_scan_command, run_scan
from fdai.delivery.code_security_signing import Ed25519PackSigner
from fdai.delivery.code_security_verifier_eval import (
    add_verifier_evaluation_command,
    evaluate_verifiers,
)
from fdai.delivery.persistence.state_store_code_security_registry import open_pack_registry
from fdai.delivery.persistence.state_store_code_security_review import (
    CodeSecurityReviewConflictError,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import (
    CodeSecurityCatalogError,
    Exposure,
    load_code_security_catalog,
)
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog
from fdai.shared.providers.remediation_pack import PackRegistryError

_REGISTRY_HELP = "registry directory, or `state-store` for FDAI_STATE_STORE_DSN"
_UPLOAD = (
    "Return result/remediation-result.json to your FDAI operator. The operator validates it with "
    "`python -m fdai.delivery.code_security_cli import-result`."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-code-security")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="build a remediation pack from SARIF")
    export.add_argument("--sarif", action="append", required=True, help="FILE:LANE")
    export.add_argument("--revision", required=True)
    export.add_argument("--repo-alias", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--registry", required=True, help=_REGISTRY_HELP)
    export.add_argument("--provider", required=True, help="approved coding-agent provider id")
    export.add_argument(
        "--provider-policy",
        default=str(repo_asset_root() / "config" / "code-security-agent-providers.yaml"),
    )
    export.add_argument("--signing-key", help="owner-only Ed25519 PEM private key")
    export.add_argument("--mode", choices=[mode.value for mode in PackMode], default="minimized")
    export.add_argument("--exposure", choices=[item.value for item in Exposure], default="unknown")
    export.add_argument("--known-exploited", help="file with one advisory id per line")
    export.add_argument("--projects", help="JSON list of project roots")
    export.add_argument("--source-root", action="append", default=[])
    export.add_argument("--coverage-limit", action="append", default=[])
    export.add_argument("--rules-version", action="append", default=[], help="PRODUCER=VERSION")
    export.add_argument("--full-repository", action="append", default=[], help="PRODUCER")
    export.add_argument(
        "--catalog-root", default=str(repo_asset_root() / "rule-catalog" / "code-security")
    )
    export.add_argument(
        "--verify-repository",
        help="git repository to acquire at --revision and run the weakness verifiers against",
    )
    export.add_argument("--work-root", help="private work directory for --verify-repository")
    revoke = sub.add_parser("revoke", help="revoke an exported pack")
    revoke.add_argument("--registry", required=True, help=_REGISTRY_HELP)
    revoke.add_argument("--pack-id", required=True)
    revoke.add_argument("--reason", required=True)
    add_review_commands(sub)
    add_publish_command(sub)
    add_scan_command(sub)
    add_verifier_evaluation_command(sub)
    evaluation = sub.add_parser("evaluate", help="measure dedup and severity on a labeled corpus")
    evaluation.add_argument(
        "--corpus",
        default=str(
            repo_asset_root()
            / "rule-catalog"
            / "code-security"
            / "evaluation"
            / "synthetic-corpus.yaml"
        ),
    )
    evaluation.add_argument("--output", help="write the evaluation receipt to this file")
    evaluation.add_argument(
        "--catalog-root", default=str(repo_asset_root() / "rule-catalog" / "code-security")
    )
    key = sub.add_parser("public-key", help="print the pack-signing public key")
    key.add_argument("--signing-key", required=True)
    return parser


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _ingest(
    args: argparse.Namespace,
) -> tuple[list[Occurrence], dict[str, int], list[SarifIngestResult]]:
    occurrences: list[Occurrence] = []
    dropped: dict[str, int] = {}
    results: list[SarifIngestResult] = []
    for spec in args.sarif:
        file_name, _, lane = spec.rpartition(":")
        ingested = ingest_sarif(
            Path(file_name).read_bytes(),
            SarifIngestContext(
                lane=Lane(lane), revision=args.revision, source_roots=tuple(args.source_root)
            ),
        )
        results.append(ingested)
        occurrences.extend(ingested.occurrences)
        for item in ingested.dropped:
            dropped[item.reason] = dropped.get(item.reason, 0) + 1
    return occurrences, dropped, results


def _export(args: argparse.Namespace) -> dict[str, object]:
    now = datetime.now(UTC)
    mode = PackMode(args.mode)
    policy_document = yaml.safe_load(Path(args.provider_policy).read_text(encoding="utf-8"))
    policy = AgentProviderPolicy.from_mapping(policy_document or {})
    provider = authorize_export(policy, args.provider, mode, now.date())
    catalog = load_code_security_catalog(Path(args.catalog_root))
    signer = Ed25519PackSigner(Path(args.signing_key)) if args.signing_key else None
    occurrences, dropped, ingested = _ingest(args)
    known = frozenset(
        line.strip()
        for line in (
            Path(args.known_exploited).read_text().splitlines() if args.known_exploited else []
        )
        if line.strip()
    )
    context = AnalysisContext(
        revision=args.revision, exposure=Exposure(args.exposure), known_exploited=known
    )
    issues = build_issues(occurrences, catalog, context)
    verifier_catalog = load_verifier_catalog(
        Path(args.catalog_root), frozenset(catalog.weakness_classes.classes)
    )
    results = list(taint_rule_verifications(issues, occurrences, verifier_catalog))
    if args.verify_repository:
        if not args.work_root:
            raise ValueError("--verify-repository requires --work-root")
        source = GitSourceAcquirer(Path(args.work_root).resolve()).acquire(
            args.verify_repository, args.revision
        )
        results += verify_issues(source.path, issues, verifier_catalog, revision=args.revision)
    verifications = verified_confidence(results)
    verified = len(verifications)
    if verifications:
        issues = build_issues(occurrences, catalog, replace(context, verifications=verifications))
    projects = tuple(
        ProjectRoot(**entry)
        for entry in (json.loads(Path(args.projects).read_text()) if args.projects else [])
    )
    limits = list(args.coverage_limit)
    if dropped:
        limits.append(
            "Scanner results not ingested: "
            + ", ".join(f"{reason}={count}" for reason, count in sorted(dropped.items()))
        )
    pack = render_remediation_pack(
        issues,
        catalog,
        PackRequest(
            repository_alias=args.repo_alias,
            base_commit=args.revision,
            created_at=now,
            mode=mode,
            coverage_limits=tuple(limits),
            project_roots=projects,
            target_provider=provider.provider_id,
            upload_instructions=_UPLOAD,
        ),
        signer,
    )
    registry = open_pack_registry(args.registry)
    asyncio.run(
        registry.record(
            PackRecord(
                pack_id=pack.pack_id,
                manifest_sha256=pack.manifest_sha256,
                base_commit=args.revision,
                issue_ids=frozenset(pack.issue_ids),
                expires_at=pack.expires_at,
            )
        )
    )
    included = set(pack.issue_ids)
    receipt = build_receipt(
        args.revision,
        catalog.version_stamp(),
        ingested,
        rules_versions=pairs(args.rules_version),
        full_repository=frozenset(args.full_repository),
    )
    asyncio.run(
        registry.record_baseline(
            pack.pack_id,
            {
                "receipt": receipt_to_dict(receipt),
                "issues": baseline_to_dict([i for i in issues if i.issue_id in included]),
            },
        )
    )
    root = Path(args.out) / pack.directory_name
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for relative, data in pack.files.items():
        _write_private(root / relative, data)
    return {
        "ok": True,
        "pack_id": pack.pack_id,
        "pack_dir": str(root),
        "provider": provider.provider_id,
        "mode": mode.value,
        "signed": signer is not None,
        "signing_key_id": pack.signing_key_id,
        "occurrences": len(occurrences),
        "issues": len(issues),
        "issues_in_pack": len(pack.issue_ids),
        "verified": verified,
        "dropped": dropped,
    }


def _revoke(args: argparse.Namespace) -> dict[str, object]:
    record = asyncio.run(open_pack_registry(args.registry).revoke(args.pack_id, args.reason))
    return {"ok": True, "pack_id": record.pack_id, "revoked": record.revoked}


def _evaluate(args: argparse.Namespace) -> dict[str, object]:
    catalog = load_code_security_catalog(Path(args.catalog_root))
    corpus = corpus_from_mapping(yaml.safe_load(Path(args.corpus).read_text(encoding="utf-8")))
    metrics = evaluate(corpus, catalog)
    failures = acceptance_failures(metrics, corpus.acceptance)
    splits: dict[str, object] = {}
    for name in ("dev", "holdout"):
        subset = split_corpus(corpus, name)
        if subset is not None and len(subset.cases) < len(corpus.cases):
            split_metrics = evaluate(subset, catalog)
            splits[name] = split_metrics.as_dict()
            failures += [
                f"{name}:{item}" for item in acceptance_failures(split_metrics, corpus.acceptance)
            ]
    receipt: dict[str, object] = {
        "ok": not failures,
        "kind": "fdai.code-security.evaluation-receipt",
        "corpus": {
            "id": corpus.corpus_id,
            "version": corpus.version,
            "provenance": corpus.provenance,
            "digest": corpus.digest,
        },
        "catalog_versions": catalog.version_stamp(),
        "metrics": metrics.as_dict(),
        "splits": splits,
        "acceptance": dict(corpus.acceptance),
        "failures": failures,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    if args.output:
        Path(args.output).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "export":
            output = _export(args)
        elif args.command == "revoke":
            output = _revoke(args)
        elif args.command == "import-result":
            output = import_result(args)
        elif args.command == "verify-fixes":
            output = verify_fixes(args)
        elif args.command == "adjudicate":
            output = adjudicate(args)
        elif args.command == "publish-review":
            output = asyncio.run(publish_review(args))
        elif args.command == "scan":
            output = asyncio.run(run_scan(args))
        elif args.command == "evaluate":
            output = _evaluate(args)
        elif args.command == "evaluate-verifiers":
            output = evaluate_verifiers(args)
        else:
            signer = Ed25519PackSigner(Path(args.signing_key))
            output = {
                "ok": True,
                "key_id": signer.key_id,
                "public_key_pem": signer.public_key_pem().decode("ascii"),
            }
    except RemediationResultRejectedError as exc:
        output = {"ok": False, "reason": exc.reason, "error": str(exc)}
    except AdjudicationError as exc:
        output = {"ok": False, "reason": "adjudication_rejected", "error": str(exc)}
    except SourceAcquisitionError as exc:
        output = {"ok": False, "reason": "source_unavailable", "error": str(exc)}
    except CodeSecurityReviewConflictError as exc:
        output = {"ok": False, "reason": "review_conflict", "error": str(exc)}
    except ExportDeniedError as exc:
        output = {"ok": False, "reason": "export_denied", "error": str(exc)}
    except (
        EvaluationCorpusError,
        VerifierCorpusError,
        CodeSecurityCatalogError,
        SarifIngestError,
        PackRegistryError,
        ValueError,
        OSError,
        KeyError,
    ) as exc:
        output = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(output, indent=2))
    return 0 if output.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
