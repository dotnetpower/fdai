from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_acr_publish import (
    REFRESH,
    REGISTRY,
    REPOSITORY,
    RecordingTransport,
    make_archive,
    responses_for,
)

from fdai_deployment_cli.acr_publish import (
    AcrPublishError,
    RegistryResponse,
    publish_dependency_oci_archive,
)
from fdai_deployment_cli.oci_archive import OciArchiveError


def _publish(fixture, transport, **overrides: Any):
    expected = fixture.expectations()
    expected.pop("expected_source_commit")
    return publish_dependency_oci_archive(
        fixture.path,
        **{
            **expected,
            "registry": REGISTRY,
            "repository": REPOSITORY,
            "credential_provider": lambda: REFRESH,
            "transport": transport,
            **overrides,
        },
    )


@pytest.mark.parametrize("existing", [False, True])
def test_dependency_publication_requires_independent_digest_readback(tmp_path: Path, existing):
    fixture = make_archive(tmp_path / "dependency.tar", config_updates={"config": {}})
    transport = RecordingTransport(responses_for(fixture, existing=existing))
    receipt = _publish(fixture, transport)
    assert receipt.manifest_digest == fixture.manifest_digest
    assert receipt.source_commit is None
    assert receipt.requests == (5 if existing else 9)
    assert not transport.responses
    put, get = transport.requests[-2:]
    assert put.method == "PUT" and get.method == "GET"
    assert put.target == get.target
    assert put.body == fixture.manifest_bytes
    assert get.body == b""


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_archive_sha256": "b" * 64},
        {"expected_manifest_digest": "sha256:" + "b" * 64},
        {"expected_platform_tag": "linux-aarch64"},
    ],
)
def test_dependency_content_checks_precede_credentials_and_http(tmp_path: Path, overrides):
    fixture = make_archive(tmp_path / "dependency.tar", config_updates={"config": {}})
    transport = RecordingTransport([])

    def forbidden():
        pytest.fail("invalid dependency must not acquire credentials")

    with pytest.raises(OciArchiveError):
        _publish(fixture, transport, credential_provider=forbidden, **overrides)
    assert not transport.requests


@pytest.mark.parametrize(("index", "status"), [(0, 429), (3, 503), (8, 307), (8, 500)])
def test_dependency_http_failure_stops_without_retry(tmp_path: Path, index: int, status: int):
    fixture = make_archive(tmp_path / "dependency.tar", config_updates={"config": {}})
    responses = responses_for(fixture)
    responses[index] = RegistryResponse(
        status, {"Location": "https://foreign.example.com/"}, b"private-provider-marker"
    )
    transport = RecordingTransport(responses)
    with pytest.raises(AcrPublishError, match="http-error") as captured:
        _publish(fixture, transport)
    assert captured.value.http_status == status
    assert len(transport.requests) == index + 1
    assert "private-provider-marker" not in str(captured.value)
    assert all(request.host == REGISTRY for request in transport.requests)


@pytest.mark.parametrize("mismatch", ["header", "body"])
def test_dependency_upload_acceptance_is_not_success(tmp_path: Path, mismatch: str):
    fixture = make_archive(tmp_path / "dependency.tar", config_updates={"config": {}})
    responses = responses_for(fixture)
    responses[-1] = RegistryResponse(
        200,
        {
            "Docker-Content-Digest": "sha256:" + "b" * 64
            if mismatch == "header"
            else fixture.manifest_digest
        },
        b"different content" if mismatch == "body" else fixture.manifest_bytes,
    )
    transport = RecordingTransport(responses)
    with pytest.raises(AcrPublishError, match="manifest-readback: digest-mismatch"):
        _publish(fixture, transport)
    assert len(transport.requests) == 9


@pytest.mark.parametrize(
    "overrides",
    [
        {"registry": "registry.example.com"},
        {"repository": "../another-repository"},
        {"total_timeout": 0},
    ],
)
def test_dependency_target_and_budget_checks_precede_credentials(tmp_path: Path, overrides):
    fixture = make_archive(tmp_path / "dependency.tar", config_updates={"config": {}})
    transport = RecordingTransport([])

    def forbidden():
        pytest.fail("invalid target must not acquire credentials")

    with pytest.raises(AcrPublishError, match="target"):
        _publish(fixture, transport, credential_provider=forbidden, **overrides)
    assert not transport.requests


def test_dependency_upload_uses_validated_snapshot_after_path_replacement(tmp_path: Path):
    fixture = make_archive(tmp_path / "dependency.tar", config_updates={"config": {}})
    transport = RecordingTransport(responses_for(fixture))

    def credential():
        fixture.path.write_bytes(b"changed after verification")
        return REFRESH

    receipt = _publish(fixture, transport, credential_provider=credential)
    assert receipt.manifest_digest == fixture.manifest_digest
    assert transport.requests[-2].body == fixture.manifest_bytes
