"""``scan`` command: run the deterministic lane against one exact revision or a local folder.

The command acquires the revision, runs each bound scanner in the bubblewrap sandbox, writes the
SARIF and coverage receipt under the work root, and builds the review package. ``--path`` scans a
local folder instead: its ``HEAD`` commit, or with ``--include-uncommitted`` a snapshot of its
working files. ``--report`` writes Markdown, HTML, and JSON reports. With
``--kafka-bootstrap-servers`` it publishes the review through Heimdall. The SARIF files it writes
can be passed to ``export`` to build a remediation pack.
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.security.code_findings.review_signal import ReviewSource, review_decision
from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.code_security_review_cli import pairs
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox
from fdai.delivery.code_security_scan_job import (
    ReviewPublisher,
    ScanJobConfig,
    ScanJobResult,
    run_scan_job,
    sarif_specs,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import Exposure, load_code_security_catalog
from fdai.rule_catalog.code_security_lenses import LensCatalog, load_lens_catalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog, load_scanner_catalog
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog
from fdai.shared.providers.code_security_lens import CodeSecurityLensModel


def add_scan_command(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    scan = sub.add_parser("scan", help="run the deterministic scanning lane in the sandbox")
    scan.add_argument("--repository", help="git URL or local repository to scan at --revision")
    scan.add_argument("--revision", help="full commit id, branch, or tag of --repository")
    scan.add_argument("--path", help="local folder to scan instead of --repository")
    scan.add_argument(
        "--include-uncommitted",
        action="store_true",
        help="with --path, scan a snapshot of the working files instead of the HEAD commit",
    )
    scan.add_argument("--repo-alias", help="display alias; defaults to the --path folder name")
    scan.add_argument(
        "--source-provider",
        help="source provider token, such as github; defaults from the repository location",
    )
    scan.add_argument("--work-root", default=str(default_work_root()))
    scan.add_argument("--report", help="write report.md, report.html, and report.json here")
    scan.add_argument("--report-locale", choices=["en", "ko"], default="en")
    scan.add_argument("--scanner-bin", action="append", default=[], help="SCANNER=EXECUTABLE")
    scan.add_argument("--required-scanner", action="append", default=[])
    scan.add_argument("--cache-dir")
    scan.add_argument("--exposure", choices=[e.value for e in Exposure], default="unknown")
    scan.add_argument("--bwrap", default="/usr/bin/bwrap")
    scan.add_argument("--kafka-bootstrap-servers")
    scan.add_argument(
        "--lens-identity",
        choices=["managed-identity", "azure-cli"],
        default="managed-identity",
        help="identity for lens model calls; azure-cli is for local development only",
    )
    scan.add_argument(
        "--prove",
        action="store_true",
        help="opt in to the proof lane: run verified Python findings in a disposable sandbox",
    )
    scan.add_argument("--prove-python", default="/usr/bin/python3")
    scan.add_argument(
        "--prove-node",
        help="Node.js executable; with --prove, also reproduce verified JavaScript issues",
    )
    scan.add_argument(
        "--prove-cc",
        help="C or C++ compiler with sanitizers; with --prove, also reproduce native issues",
    )
    scan.add_argument(
        "--record-state",
        action="store_true",
        help="record the review for the Console in the state store from FDAI_STATE_STORE_DSN",
    )
    scan.add_argument(
        "--lens-model",
        action="append",
        default=[],
        help="FAMILY=ENDPOINT|DEPLOYMENT; two or more distinct families enable the LLM lens lane",
    )
    root = repo_asset_root() / "rule-catalog" / "code-security"
    scan.add_argument("--catalog-root", default=str(root))
    scan.add_argument("--rules-dir", default=str(root / "rules"))


_ALIAS_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def default_work_root() -> Path:
    """Return the private default work root under the user's cache directory."""
    cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    return (Path(cache) if cache else Path.home() / ".cache") / "fdai-code-security"


def derive_alias(folder: Path) -> str:
    """Return a valid repository alias from a folder name."""
    alias = _ALIAS_CHARS.sub("-", folder.resolve().name).strip("-._")[:64]
    return alias or "local-folder"


def scan_target(args: argparse.Namespace) -> tuple[str, ReviewSource]:
    """Validate the target arguments and return the alias and review source."""
    if args.path:
        if args.repository or args.revision:
            raise ValueError("--path cannot be combined with --repository or --revision")
        return args.repo_alias or derive_alias(Path(args.path)), ReviewSource(
            kind="local_path", provider=args.source_provider or "local", trigger="cli"
        )
    if args.include_uncommitted:
        raise ValueError("--include-uncommitted needs --path")
    if not args.repository or not args.revision or not args.repo_alias:
        raise ValueError("scan needs --path, or --repository, --revision, and --repo-alias")
    provider = args.source_provider or (
        "github" if "github.com" in args.repository.lower() else "git"
    )
    return args.repo_alias, ReviewSource(kind="git_repository", provider=provider, trigger="cli")


async def run_scan(args: argparse.Namespace) -> dict[str, object]:
    alias, source = scan_target(args)
    args.repo_alias = alias
    catalog_root = Path(args.catalog_root)
    executables = {key: Path(value).resolve() for key, value in pairs(args.scanner_bin).items()}
    scanners = load_scanner_catalog(catalog_root)
    unknown = set(executables) - set(scanners.scanners)
    if unknown:
        raise ValueError(f"unknown scanners: {', '.join(sorted(unknown))}")
    publisher = None
    if args.kafka_bootstrap_servers:
        from fdai.delivery.code_security_publish_cli import heimdall_publisher

        publisher = heimdall_publisher(args.kafka_bootstrap_servers)
    lens_catalog = load_lens_catalog(catalog_root) if args.lens_model else None
    async with open_lens_models(args.lens_model, lens_catalog, args.lens_identity) as lens_models:
        result = await _run(
            args, catalog_root, executables, scanners, publisher, lens_catalog, lens_models, source
        )
    lens = result.lens_report
    recorded = False
    if args.record_state:
        from fdai.delivery.persistence.state_store_code_security_review import (
            record_review_from_environment,
        )

        recorded = await record_review_from_environment(result.package)
    report: dict[str, str] | None = None
    if args.report:
        from fdai.delivery.code_security_report import write_scan_report

        paths = write_scan_report(
            result,
            Path(args.report).resolve(),
            repository_alias=alias,
            source_label=f"{source.kind}:{source.provider}",
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            locale=args.report_locale,
        )
        report = {"markdown": str(paths.markdown), "html": str(paths.html), "json": str(paths.json)}
    return {
        "ok": True,
        "repository_alias": alias,
        "source": source.kind,
        "revision": result.revision,
        "revision_kind": result.revision_kind,
        "tree_id": result.tree_id,
        "issues": len(result.issues),
        "decision": review_decision(result.package),
        "coverage_complete": result.package["coverage_complete"],
        "coverage_limits": list(result.coverage_limits),
        "scanners": [
            {"scanner": run.scanner_id, "completed": run.completed, "exit_code": run.exit_code}
            for run in result.runs
        ],
        "lens": None
        if lens is None
        else {"kept": lens.kept, "model_calls": lens.model_calls, "notes": list(lens.notes)},
        "verified": sum(1 for item in result.verifier_results if item.outcome.value == "verified"),
        "published": result.published,
        "recorded": recorded,
        "proven": sum(1 for item in result.proof_results if item.outcome == "proven"),
        "artifact_dir": str(result.artifact_dir),
        "export_sarif_args": list(sarif_specs(result)),
        "report": report,
    }


@asynccontextmanager
async def open_lens_models(
    specs: list[str], catalog: LensCatalog | None, identity_kind: str = "managed-identity"
) -> AsyncIterator[list[CodeSecurityLensModel]]:
    """Build Azure lens models from ``FAMILY=ENDPOINT|DEPLOYMENT`` specs inside one client.

    ``azure-cli`` uses the operator's existing ``az`` login for local development; deployments
    use the attached managed identity.
    """
    if not specs or catalog is None:
        yield []
        return
    import httpx

    from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
    from fdai.delivery.azure.llm.code_security_lens import (
        AzureOpenAICodeSecurityLensModel,
        AzureOpenAILensModelConfig,
    )
    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
    from fdai.shared.providers.workload_identity import WorkloadIdentity

    async with httpx.AsyncClient() as client:
        identity: WorkloadIdentity = (
            AsyncAzureCliWorkloadIdentity.from_env()
            if identity_kind == "azure-cli"
            else ManagedIdentityWorkloadIdentity.from_env(http_client=client)
        )
        models: list[CodeSecurityLensModel] = []
        for family, target in pairs(specs).items():
            endpoint, _, deployment = target.partition("|")
            if not endpoint or not deployment:
                raise ValueError("--lens-model expects FAMILY=ENDPOINT|DEPLOYMENT")
            models.append(
                AzureOpenAICodeSecurityLensModel(
                    identity=identity,
                    http_client=client,
                    config=AzureOpenAILensModelConfig(
                        endpoint=endpoint,
                        deployment=deployment,
                        family=family,
                        system_prompt=catalog.system_prompt,
                    ),
                )
            )
        yield models


async def _run(
    args: argparse.Namespace,
    catalog_root: Path,
    executables: dict[str, Path],
    scanners: ScannerCatalog,
    publisher: ReviewPublisher | None,
    lens_catalog: LensCatalog | None,
    lens_models: list[CodeSecurityLensModel],
    source: ReviewSource,
) -> ScanJobResult:
    catalog = load_code_security_catalog(catalog_root)
    known = frozenset(catalog.weakness_classes.classes)
    acquirer = GitSourceAcquirer(Path(args.work_root).resolve())
    local_path = Path(args.path).resolve() if args.path else None
    revision = "" if local_path else acquirer.resolve_revision(args.repository, args.revision)
    return await run_scan_job(
        ScanJobConfig(
            repository=args.repository or "",
            revision=revision,
            repository_alias=args.repo_alias,
            work_root=Path(args.work_root).resolve(),
            executables=executables,
            rules_dir=Path(args.rules_dir).resolve(),
            cache_dir=Path(args.cache_dir).resolve() if args.cache_dir else None,
            exposure=Exposure(args.exposure),
            required_scanners=frozenset(args.required_scanner) or None,
            local_path=local_path,
            include_uncommitted=args.include_uncommitted,
            source=source,
        ),
        catalog=catalog,
        scanners=scanners,
        acquirer=acquirer,
        sandbox=BubblewrapScannerSandbox(Path(args.bwrap)),
        publisher=publisher,
        lens_catalog=lens_catalog,
        lens_models=lens_models,
        verifier_catalog=load_verifier_catalog(catalog_root, known),
        prove_python=Path(args.prove_python).resolve() if args.prove else None,
        prove_runtimes=_prove_runtimes(args),
    )


def _prove_runtimes(args: argparse.Namespace) -> dict[str, Path] | None:
    if not args.prove:
        return None
    runtimes = {
        language: Path(value).resolve()
        for language, value in (("javascript", args.prove_node), ("native", args.prove_cc))
        if value
    }
    return runtimes or None


__all__ = [
    "add_scan_command",
    "default_work_root",
    "derive_alias",
    "open_lens_models",
    "run_scan",
    "scan_target",
]
