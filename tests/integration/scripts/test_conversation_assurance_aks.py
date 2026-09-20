from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from scripts.automation.conversation_assurance_aks import (
    AksSeriesUnavailableError,
    bind_private_runtime_corpus,
    build_private_aks_corpora,
    build_private_aks_runtime_corpus,
    discover_aks_business_service_bindings,
)


def _clusters() -> list[dict[str, object]]:
    return [
        {
            "id": "/subscriptions/private/resourceGroups/private/providers/"
            "Microsoft.ContainerService/managedClusters/cluster-private",
            "name": "cluster-private",
            "type": "Microsoft.ContainerService/managedClusters",
        }
    ]


def test_discovery_requires_reviewed_business_service_path() -> None:
    with pytest.raises(AksSeriesUnavailableError, match="binding_unavailable"):
        discover_aks_business_service_bindings(
            azure_clusters=_clusters,
            operating_graph=lambda _refs: (),
        )


def test_private_builder_writes_three_real_target_questions_without_name_in_paths(
    tmp_path: Path,
) -> None:
    bindings = discover_aks_business_service_bindings(
        azure_clusters=_clusters,
        operating_graph=lambda refs: (
            {
                "provider_ref": refs[0],
                "resource_id": "resource-private",
                "business_service_name": "checkout-private",
            },
        ),
    )

    paths = build_private_aks_corpora(
        output_directory=tmp_path / "private",
        run_prefix="aks-improvement",
        bindings=bindings,
    )

    assert len(paths) == 3
    questions = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions.append(payload["cases"][0]["question"])
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "cluster-private" not in path.name
        assert "checkout-private" not in path.name
    assert len(set(questions)) == 3
    assert all("cluster-private" in question for question in questions)
    assert all("checkout-private" in question for question in questions)

    runtime_path = build_private_aks_runtime_corpus(
        corpus_paths=paths,
        output_path=tmp_path / "private/runtime.json",
    )
    runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert len(runtime_payload["cases"]) == 3
    assert stat.S_IMODE(runtime_path.stat().st_mode) == 0o600


def test_runtime_binding_preserves_unrelated_private_environment(tmp_path: Path) -> None:
    environment = tmp_path / "runtime.env"
    corpus = tmp_path / "runtime.json"
    environment.write_text("FDAI_OTHER=value\n", encoding="utf-8")
    corpus.write_text('{"schema_version":"1.0.0","cases":[]}\n', encoding="utf-8")
    environment.chmod(0o600)
    corpus.chmod(0o600)

    bind_private_runtime_corpus(
        runtime_env_path=environment,
        corpus_path=corpus,
        corpus_digest="a" * 64,
    )

    content = environment.read_text(encoding="utf-8")
    assert "FDAI_OTHER=value" in content
    assert f"FDAI_CONVERSATION_ASSURANCE_CORPUS_FILE={corpus.resolve()}" in content
    assert f"FDAI_CONVERSATION_ASSURANCE_CORPUS_DIGEST={'a' * 64}" in content

    with pytest.raises(AksSeriesUnavailableError, match="digest_invalid"):
        bind_private_runtime_corpus(
            runtime_env_path=environment,
            corpus_path=corpus,
            corpus_digest="not-a-digest",
        )
