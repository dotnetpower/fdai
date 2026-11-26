"""Prepare private AKS conversation cases from current read-only evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

_MAX_AZURE_OUTPUT_BYTES: Final[int] = 2 * 1024 * 1024
_MAX_TARGETS: Final[int] = 100
_QUESTION_COUNT: Final[int] = 3
_AKS_TYPE: Final[str] = "microsoft.containerservice/managedclusters"
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_CORPUS_FILE_KEY: Final[str] = "FDAI_CONVERSATION_ASSURANCE_CORPUS_FILE"
_CORPUS_DIGEST_KEY: Final[str] = "FDAI_CONVERSATION_ASSURANCE_CORPUS_DIGEST"


class AksSeriesUnavailableError(RuntimeError):
    """The current read-only sources cannot support an AKS question series."""


@dataclass(frozen=True, slots=True)
class AksBusinessServiceBinding:
    """One exact private AKS-to-BusinessService graph binding."""

    cluster_name: str
    provider_ref: str
    resource_id: str
    business_service_name: str

    def __post_init__(self) -> None:
        for value in (
            self.cluster_name,
            self.provider_ref,
            self.resource_id,
            self.business_service_name,
        ):
            if not value.strip() or len(value) > 2_048:
                raise ValueError("AKS assurance binding values MUST be non-empty and bounded")


AzureClusterReader = Callable[[], Sequence[Mapping[str, object]]]
OperatingGraphReader = Callable[[tuple[str, ...]], Sequence[Mapping[str, object]]]


def discover_aks_business_service_bindings(
    *,
    azure_clusters: AzureClusterReader,
    operating_graph: OperatingGraphReader,
) -> tuple[AksBusinessServiceBinding, ...]:
    """Join Azure CLI clusters to reviewed local operating-graph service paths."""

    clusters = tuple(azure_clusters())
    if not 1 <= len(clusters) <= _MAX_TARGETS:
        raise AksSeriesUnavailableError("aks_target_count_unavailable")
    normalized: dict[str, str] = {}
    for cluster in clusters:
        provider_ref = cluster.get("id")
        name = cluster.get("name")
        resource_type = str(cluster.get("type") or _AKS_TYPE).casefold()
        if (
            not isinstance(provider_ref, str)
            or not isinstance(name, str)
            or not provider_ref.strip()
            or not name.strip()
            or resource_type != _AKS_TYPE
        ):
            raise AksSeriesUnavailableError("aks_target_shape_invalid")
        key = provider_ref.casefold()
        if key in normalized:
            raise AksSeriesUnavailableError("aks_target_identity_ambiguous")
        normalized[key] = name
    graph_rows = operating_graph(tuple(sorted(normalized)))
    bindings: list[AksBusinessServiceBinding] = []
    seen: set[tuple[str, str]] = set()
    for row in graph_rows:
        provider_ref = row.get("provider_ref")
        resource_id = row.get("resource_id")
        service_name = row.get("business_service_name")
        if not all(
            isinstance(item, str) and item.strip()
            for item in (provider_ref, resource_id, service_name)
        ):
            raise AksSeriesUnavailableError("operating_graph_binding_invalid")
        provider_key = str(provider_ref).casefold()
        if provider_key not in normalized:
            raise AksSeriesUnavailableError("operating_graph_target_mismatch")
        identity = (provider_key, str(service_name).casefold())
        if identity in seen:
            continue
        seen.add(identity)
        bindings.append(
            AksBusinessServiceBinding(
                cluster_name=normalized[provider_key],
                provider_ref=str(provider_ref),
                resource_id=str(resource_id),
                business_service_name=str(service_name),
            )
        )
    if not bindings:
        raise AksSeriesUnavailableError("aks_business_service_binding_unavailable")
    return tuple(
        sorted(
            bindings,
            key=lambda item: (
                item.business_service_name.casefold(),
                item.cluster_name.casefold(),
            ),
        )
    )


def azure_cli_aks_clusters() -> tuple[Mapping[str, object], ...]:
    """Read AKS identities through the existing Azure CLI login without printing them."""

    try:
        result = subprocess.run(  # noqa: S603 - fixed Azure CLI read command
            (
                "az",
                "aks",
                "list",
                "--query",
                "[].{id:id,name:name,type:type}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AksSeriesUnavailableError("azure_cli_aks_read_unavailable") from error
    if len(result.stdout) > _MAX_AZURE_OUTPUT_BYTES:
        raise AksSeriesUnavailableError("azure_cli_aks_response_oversized")
    try:
        value = json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AksSeriesUnavailableError("azure_cli_aks_response_invalid") from error
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AksSeriesUnavailableError("azure_cli_aks_response_invalid")
    return tuple({str(key): item for key, item in row.items()} for row in value)


def local_operating_graph_reader(
    *,
    runtime_env_path: Path,
) -> OperatingGraphReader:
    """Build a local PostgreSQL graph reader without exposing its service-owned DSN."""

    dsn = _runtime_dsn(runtime_env_path)

    def read(provider_refs: tuple[str, ...]) -> Sequence[Mapping[str, object]]:
        query = """
            WITH target_resource AS (
                SELECT resource.resource_id, resource.provider_ref
                FROM inventory_active active
                JOIN inventory_snapshot_resource resource
                  ON resource.snapshot_id = active.snapshot_id
                WHERE active.singleton = TRUE
                  AND lower(resource.provider_ref) = ANY(%s::text[])
                  AND lower(resource.resource_type) = %s
            ), service_path AS (
                SELECT target.resource_id, target.provider_ref, service.from_id AS service_id
                FROM target_resource target
                JOIN ontology_link workload
                  ON workload.link_type = 'workload_runs_on'
                 AND workload.to_id = target.resource_id
                JOIN ontology_link service
                  ON service.link_type = 'implemented_by'
                 AND service.to_id = workload.from_id
            )
            SELECT path.resource_id, path.provider_ref,
                   COALESCE(NULLIF(service.properties->>'name', ''), service.id)
                     AS business_service_name
            FROM service_path path
            JOIN ontology_resource service
              ON service.id = path.service_id
             AND service.object_type = 'BusinessService'
            ORDER BY business_service_name, path.provider_ref
            LIMIT %s
        """
        try:
            with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, (list(provider_refs), _AKS_TYPE, _MAX_TARGETS))
                    return tuple(dict(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise AksSeriesUnavailableError("local_operating_graph_unavailable") from error

    return read


def build_private_aks_corpora(
    *,
    output_directory: Path,
    run_prefix: str,
    bindings: Sequence[AksBusinessServiceBinding],
) -> tuple[Path, ...]:
    """Write exactly three owner-only corpora without returning target names."""

    if not bindings:
        raise AksSeriesUnavailableError("aks_business_service_binding_unavailable")
    if output_directory.is_symlink():
        raise AksSeriesUnavailableError("aks_private_corpus_directory_invalid")
    output_directory.mkdir(parents=True, exist_ok=True)
    os.chmod(output_directory, 0o700)
    templates = (
        "What is the current evidence-backed operational state of BusinessService "
        "'{service}' on AKS cluster '{cluster}', including unavailable workload evidence?",
        "For BusinessService '{service}' on AKS cluster '{cluster}', which observed workloads "
        "have complete current-state evidence, and which relationships or states remain unknown?",
        "Does current evidence show any degraded or unavailable Resource supporting "
        "BusinessService "
        "'{service}' on AKS cluster '{cluster}'? Include the evidence cutoff and limitations.",
    )
    paths: list[Path] = []
    for index, template in enumerate(templates, start=1):
        binding = bindings[(index - 1) % len(bindings)]
        question = template.format(
            service=binding.business_service_name,
            cluster=binding.cluster_name,
        )
        if len(question) > 400:
            raise AksSeriesUnavailableError("aks_private_question_oversized")
        target_digest = hashlib.sha256(
            f"{binding.provider_ref}\0{binding.business_service_name}\0{index}".encode()
        ).hexdigest()[:16]
        case_id = f"aks-business-state-{target_digest}-{index}"
        corpus = {
            "schema_version": "1.0.0",
            "cases": [
                {
                    "case_id": case_id,
                    "suite": "external",
                    "locale": "en",
                    "question": question,
                    "expected_primary_agent": "Heimdall",
                    "expected_routing_method": "semantic_judgment",
                    "allowed_contributors": [],
                    "expected_handoff": False,
                    "expected_handoff_owner": None,
                    "t2_expectation": "forbidden",
                }
            ],
        }
        path = output_directory / f"{run_prefix}-{index}.json"
        _write_private_json(path, corpus)
        paths.append(path)
    return tuple(paths)


def build_private_aks_runtime_corpus(
    *,
    corpus_paths: Sequence[Path],
    output_path: Path,
) -> Path:
    """Combine the three private cases into the corpus loaded by Core."""

    if len(corpus_paths) != _QUESTION_COUNT:
        raise AksSeriesUnavailableError("aks_runtime_corpus_count_invalid")
    cases: list[Mapping[str, Any]] = []
    case_ids: set[str] = set()
    for path in corpus_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AksSeriesUnavailableError("aks_private_corpus_unavailable") from error
        entries = payload.get("cases") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list) or len(entries) != 1:
            raise AksSeriesUnavailableError("aks_private_corpus_case_invalid")
        case = entries[0]
        case_id = case.get("case_id") if isinstance(case, Mapping) else None
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise AksSeriesUnavailableError("aks_private_corpus_identity_invalid")
        cases.append(dict(case))
        case_ids.add(case_id)
    _write_private_json(
        output_path,
        {"schema_version": "1.0.0", "cases": cases},
    )
    return output_path


def bind_private_runtime_corpus(
    *,
    runtime_env_path: Path,
    corpus_path: Path,
    corpus_digest: str,
) -> None:
    """Atomically bind one private corpus without changing unrelated runtime values."""

    if _SHA256.fullmatch(corpus_digest) is None:
        raise AksSeriesUnavailableError("aks_runtime_corpus_digest_invalid")
    if (
        runtime_env_path.is_symlink()
        or not runtime_env_path.is_file()
        or runtime_env_path.stat().st_mode & 0o077
    ):
        raise AksSeriesUnavailableError("local_runtime_environment_not_private")
    if corpus_path.is_symlink() or not corpus_path.is_file() or corpus_path.stat().st_mode & 0o077:
        raise AksSeriesUnavailableError("aks_runtime_corpus_not_private")
    try:
        lines = runtime_env_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise AksSeriesUnavailableError("local_runtime_environment_unavailable") from error
    keys = (_CORPUS_FILE_KEY, _CORPUS_DIGEST_KEY)
    if any(sum(line.startswith(f"{key}=") for line in lines) > 1 for key in keys):
        raise AksSeriesUnavailableError("local_runtime_corpus_binding_ambiguous")
    retained = [line for line in lines if not any(line.startswith(f"{key}=") for key in keys)]
    retained.extend(
        (
            f"{_CORPUS_FILE_KEY}={corpus_path.resolve()}",
            f"{_CORPUS_DIGEST_KEY}={corpus_digest}",
        )
    )
    temporary = runtime_env_path.with_name(f".{runtime_env_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text("\n".join(retained) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(runtime_env_path)
    finally:
        temporary.unlink(missing_ok=True)


def _runtime_dsn(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise AksSeriesUnavailableError("local_runtime_environment_not_private")
    prefix = "FDAI_STATE_STORE_DSN="
    try:
        values = [
            line.removeprefix(prefix).strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith(prefix)
        ]
    except (OSError, UnicodeError) as error:
        raise AksSeriesUnavailableError("local_runtime_environment_unavailable") from error
    if len(values) != 1 or not values[0].startswith("postgresql://"):
        raise AksSeriesUnavailableError("local_runtime_dsn_unavailable")
    return values[0]


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise AksSeriesUnavailableError("aks_private_corpus_exists")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "AksBusinessServiceBinding",
    "AksSeriesUnavailableError",
    "azure_cli_aks_clusters",
    "bind_private_runtime_corpus",
    "build_private_aks_corpora",
    "build_private_aks_runtime_corpus",
    "discover_aks_business_service_bindings",
    "local_operating_graph_reader",
]
