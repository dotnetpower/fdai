"""``scan`` command: run the deterministic lane against one exact revision.

The command acquires the revision, runs each bound scanner in the bubblewrap sandbox, writes the
SARIF and coverage receipt under the work root, and builds the review package. With
``--kafka-bootstrap-servers`` it publishes the review through Heimdall. The SARIF files it writes
can be passed to ``export`` to build a remediation pack.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fdai.core.security.code_findings.review_signal import review_decision
from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.code_security_review_cli import pairs
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox
from fdai.delivery.code_security_scan_job import ScanJobConfig, run_scan_job, sarif_specs
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import Exposure, load_code_security_catalog
from fdai.rule_catalog.code_security_scanners import load_scanner_catalog


def add_scan_command(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    scan = sub.add_parser("scan", help="run the deterministic scanning lane in the sandbox")
    scan.add_argument("--repository", required=True, help="git URL or local path")
    scan.add_argument("--revision", required=True)
    scan.add_argument("--repo-alias", required=True)
    scan.add_argument("--work-root", required=True)
    scan.add_argument("--scanner-bin", action="append", default=[], help="SCANNER=EXECUTABLE")
    scan.add_argument("--required-scanner", action="append", default=[])
    scan.add_argument("--cache-dir")
    scan.add_argument("--exposure", choices=[e.value for e in Exposure], default="unknown")
    scan.add_argument("--bwrap", default="/usr/bin/bwrap")
    scan.add_argument("--kafka-bootstrap-servers")
    root = repo_asset_root() / "rule-catalog" / "code-security"
    scan.add_argument("--catalog-root", default=str(root))
    scan.add_argument("--rules-dir", default=str(root / "rules"))


async def run_scan(args: argparse.Namespace) -> dict[str, object]:
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
    result = await run_scan_job(
        ScanJobConfig(
            repository=args.repository,
            revision=args.revision,
            repository_alias=args.repo_alias,
            work_root=Path(args.work_root).resolve(),
            executables=executables,
            rules_dir=Path(args.rules_dir).resolve(),
            cache_dir=Path(args.cache_dir).resolve() if args.cache_dir else None,
            exposure=Exposure(args.exposure),
            required_scanners=frozenset(args.required_scanner) or None,
        ),
        catalog=load_code_security_catalog(catalog_root),
        scanners=scanners,
        acquirer=GitSourceAcquirer(Path(args.work_root).resolve()),
        sandbox=BubblewrapScannerSandbox(Path(args.bwrap)),
        publisher=publisher,
    )
    return {
        "ok": True,
        "revision": result.revision,
        "tree_id": result.tree_id,
        "issues": len(result.issues),
        "decision": review_decision(result.package),
        "coverage_complete": result.package["coverage_complete"],
        "coverage_limits": list(result.coverage_limits),
        "scanners": [
            {"scanner": run.scanner_id, "completed": run.completed, "exit_code": run.exit_code}
            for run in result.runs
        ],
        "published": result.published,
        "artifact_dir": str(result.artifact_dir),
        "export_sarif_args": list(sarif_specs(result)),
    }


__all__ = ["add_scan_command", "run_scan"]
