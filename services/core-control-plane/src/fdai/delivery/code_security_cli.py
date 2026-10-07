"""Operator CLI for code-security findings and remediation packs.

Commands:

``export``        ingest SARIF, build canonical issues, check the coding-agent provider gate,
                  sign the pack when a key is given, write it, and record it in the registry;
``revoke``        revoke a pack so FDAI rejects its results;
``import-result`` validate a returned result against the registry record;
``verify-fixes``  verify fix claims with a coverage-equivalent rescan;
``adjudicate``    record a human decision on a false-positive claim;
``public-key``    print the pack-signing public key that developers pin.

Example::

    python -m fdai.delivery.code_security_cli export \\
        --sarif mdash.sarif:external --sarif opengrep.sarif:deterministic \\
        --revision <40-hex commit> --repo-alias payments-api \\
        --provider example-coding-agent --provider-policy providers.yaml \\
        --signing-key pack-signing.pem --registry ./registry --out ./packs

The CLI performs no network calls and grants no execution authority.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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
from fdai.delivery.code_security_registry import FileRemediationPackRegistry
from fdai.delivery.code_security_review_cli import (
    add_review_commands,
    adjudicate,
    import_result,
    pairs,
    verify_fixes,
)
from fdai.delivery.code_security_signing import Ed25519PackSigner
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import (
    CodeSecurityCatalogError,
    Exposure,
    load_code_security_catalog,
)
from fdai.shared.providers.remediation_pack import PackRegistryError

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
    export.add_argument("--registry", required=True)
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
    revoke = sub.add_parser("revoke", help="revoke an exported pack")
    revoke.add_argument("--registry", required=True)
    revoke.add_argument("--pack-id", required=True)
    revoke.add_argument("--reason", required=True)
    add_review_commands(sub)
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
    issues = build_issues(
        occurrences,
        catalog,
        AnalysisContext(
            revision=args.revision, exposure=Exposure(args.exposure), known_exploited=known
        ),
    )
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
    registry = FileRemediationPackRegistry(Path(args.registry))
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
        "dropped": dropped,
    }


def _revoke(args: argparse.Namespace) -> dict[str, object]:
    record = asyncio.run(
        FileRemediationPackRegistry(Path(args.registry)).revoke(args.pack_id, args.reason)
    )
    return {"ok": True, "pack_id": record.pack_id, "revoked": record.revoked}


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
    except ExportDeniedError as exc:
        output = {"ok": False, "reason": "export_denied", "error": str(exc)}
    except (
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
