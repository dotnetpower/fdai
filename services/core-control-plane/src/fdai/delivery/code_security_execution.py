"""Select local bubblewrap or externally observed, credential-free AKS Kata scanner Jobs."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.code_security_kata_client import InClusterKataClient
from fdai.delivery.code_security_kata_job import KataScanConfig
from fdai.delivery.code_security_kata_sandbox import KataScannerSandbox
from fdai.delivery.code_security_prepared_source import (
    PreparedSource,
    export_prepared_source,
    source_tree_digest,
)
from fdai.delivery.code_security_result_acceptance import accept_prepared_scan
from fdai.delivery.code_security_scan_job import ScanJobConfig, ScanJobResult, run_scan_job
from fdai.rule_catalog.code_security import CodeSecurityCatalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog
from fdai.rule_catalog.code_security_verifiers import VerifierCatalog


def add_execution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scanner-runtime", choices=("local", "kata"), default="local")
    parser.add_argument("--scanner-namespace")
    parser.add_argument("--scanner-image", help="immutable IMAGE@sha256:DIGEST for Kata Jobs")
    parser.add_argument("--scanner-source-pvc")
    parser.add_argument("--scanner-source-mount", help="controller mount of the shared source PVC")
    parser.add_argument("--scanner-cache-pvc")
    parser.add_argument("--scanner-cache-subpath", default="cache")


def kata_config(args: argparse.Namespace) -> KataScanConfig | None:
    runtime = getattr(args, "scanner_runtime", "local")
    required = (
        getattr(args, "scanner_namespace", None),
        getattr(args, "scanner_image", None),
        getattr(args, "scanner_source_pvc", None),
        getattr(args, "scanner_source_mount", None),
    )
    if runtime == "local":
        if any(required) or getattr(args, "scanner_cache_pvc", None):
            raise ValueError("Kata bindings require --scanner-runtime kata")
        return None
    if not all(isinstance(value, str) and value for value in required):
        raise ValueError("Kata scanning requires namespace, image, source PVC and mount bindings")
    if getattr(args, "state_access", "restricted") != "restricted":
        raise ValueError("Kata scan workers require --state-access restricted")
    if getattr(args, "prove", False) or getattr(args, "lens_model", []):
        raise ValueError("Kata scanner Jobs support the deterministic lane only")
    return KataScanConfig(
        namespace=args.scanner_namespace,
        image=args.scanner_image,
        source_pvc=args.scanner_source_pvc,
        source_mount=Path(args.scanner_source_mount),
        cache_pvc=args.scanner_cache_pvc,
        cache_subpath=args.scanner_cache_subpath,
        cache_mount=Path(args.cache_dir).resolve() if args.cache_dir else None,
    )


async def run_kata_scan(
    config: ScanJobConfig,
    *,
    runtime: KataScanConfig,
    catalog: CodeSecurityCatalog,
    scanners: ScannerCatalog,
    verifier_catalog: VerifierCatalog,
    acquirer: GitSourceAcquirer | None,
    prepared: PreparedSource | None = None,
) -> ScanJobResult:
    """Acquire outside the VM, observe each process through TLS, then independently rebuild it."""
    if config.source is None:
        raise ValueError("Kata scanning requires explicit source attribution")
    if prepared is None:
        if acquirer is None:
            raise ValueError("Kata scanning requires prepared source or an acquirer")
        acquired = (
            acquirer.acquire_path(config.local_path, include_uncommitted=config.include_uncommitted)
            if config.local_path is not None
            else acquirer.acquire(config.repository, config.revision)
        )
        prepared = export_prepared_source(
            acquired,
            runtime.source_mount / "prepared" / uuid4().hex,
            repository_alias=config.repository_alias,
            source=config.source,
        )
    prepared_config = replace(
        config,
        repository="",
        revision=prepared.acquired.revision,
        local_path=None,
        source=prepared.source,
        include_uncommitted=False,
    )
    rule_digest: str | None = None
    if any("rules" in spec.mounts for spec in scanners.scanners.values()):
        rule_digest = source_tree_digest(config.rules_dir)
        rule_path = runtime.source_mount / "rulepacks" / uuid4().hex
        rule_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copytree(config.rules_dir, rule_path, symlinks=True)
        if source_tree_digest(rule_path) != rule_digest:
            raise ValueError("Kata rule pack changed while preparing the handoff")
        runtime = replace(
            runtime,
            rules_subpath=rule_path.relative_to(runtime.source_mount).as_posix(),
        )
        prepared_config = replace(prepared_config, rules_dir=rule_path)
    client = InClusterKataClient.from_environment()
    try:
        sandbox = KataScannerSandbox(
            runtime, client, journal_directory=config.work_root / "job-attempts"
        )
        result = await run_scan_job(
            prepared_config,
            catalog=catalog,
            scanners=scanners,
            acquirer=None,
            sandbox=sandbox,
            prepared_source=prepared,
            verifier_catalog=verifier_catalog,
        )
        if rule_digest is not None and (
            source_tree_digest(prepared_config.rules_dir) != rule_digest
        ):
            raise ValueError("Kata rule pack changed during scanning")
        await accept_prepared_scan(
            result,
            prepared=prepared,
            observations=sandbox.observations,
            config=prepared_config,
            catalog=catalog,
            scanners=scanners,
            verifier_catalog=verifier_catalog,
            verification_work_root=config.work_root / "acceptance",
        )
        return result
    finally:
        await client.aclose()
