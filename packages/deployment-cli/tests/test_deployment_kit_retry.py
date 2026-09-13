"""Online retries reverify retained artifacts without replacing deployment evidence."""

from __future__ import annotations

import errno
import io
import json
import os
import stat
import tarfile
import urllib.error

import pytest
from test_offline_prepare import release as release

from fdai_deployment_cli import deployment_kit


@pytest.fixture
def online_release(release, tmp_path, monkeypatch):
    kit, _key, public = release
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        archive.add(kit, arcname="kit")
    requests = []

    class Response(io.BytesIO):
        def geturl(self):
            return "https://release-assets.githubusercontent.com/example/kit.tar.gz"

    def download(request, *, timeout):
        requests.append(request.full_url)
        assert timeout == 30
        return Response(payload.getvalue())

    monkeypatch.setattr(deployment_kit.urllib.request, "urlopen", download)
    monkeypatch.setattr(deployment_kit, "deployment_release_root_pem", lambda: public)
    monkeypatch.setattr(deployment_kit, "deployment_bundle_root_pem", lambda: public)
    monkeypatch.setattr(deployment_kit, "runtime_platform_tag", lambda: "linux-x86_64")
    work = tmp_path / "online-work"
    work.mkdir(mode=0o700)
    return work, requests, payload.getvalue()


def _acquire(work, **kwargs):
    return deployment_kit.acquire_deployment_kit(
        work_dir=work, online=True, offline_kit=None, **kwargs
    )


def test_online_retry_reverifies_and_preserves_the_original_execution_copy(online_release):
    work, requests, _payload = online_release
    first = _acquire(work)
    residue = first.bundle_root / "__pycache__" / "example.pyc"
    residue.parent.mkdir(mode=0o700)
    residue.write_bytes(b"old bytecode must never be executed")
    state = first.bundle_root / "retained-state.json"
    state.write_bytes(b"old execution evidence must be preserved")
    archive_before = (work / "downloaded-kit.tar.gz").read_bytes()

    second = _acquire(work)

    assert len(requests) == 1
    assert first.root == second.root
    assert first.materialized_root == second.materialized_root
    assert first.verification == second.verification
    assert first.bundle_manifest_digest == second.bundle_manifest_digest
    assert first.bundle_root != second.bundle_root
    assert residue.read_bytes() == b"old bytecode must never be executed"
    assert state.read_bytes() == b"old execution evidence must be preserved"
    assert not (second.bundle_root / "__pycache__").exists()
    assert not (second.bundle_root / "retained-state.json").exists()
    assert (work / "downloaded-kit.tar.gz").read_bytes() == archive_before


def test_legacy_default_cache_is_reverified_without_a_network_request(online_release):
    work, requests, _payload = online_release
    first = _acquire(work)
    (work / "online-source.json").unlink()
    second = _acquire(work)
    assert len(requests) == 1
    assert first.verification == second.verification
    marker = json.loads((work / "online-source.json").read_text())
    assert marker["kind"] == "legacy-retained"
    assert stat.S_IMODE((work / "online-source.json").stat().st_mode) == 0o600


def test_archive_only_legacy_retry_verifies_and_materializes(online_release):
    work, requests, payload = online_release
    retained = work / "downloaded-kit.tar.gz"
    retained.write_bytes(payload)
    retained.chmod(0o600)
    result = _acquire(work)
    assert requests == []
    assert result.runtime.schema_version == "fdai.runtime-release.v2"
    assert retained.read_bytes() == payload


@pytest.mark.parametrize("legacy", [False, True])
def test_source_switch_never_reuses_another_cache(online_release, legacy):
    work, requests, _payload = online_release
    _acquire(work)
    if legacy:
        (work / "online-source.json").unlink()
    with pytest.raises(ValueError, match="source"):
        _acquire(work, online_url="https://github.com/example/another-kit.tar.gz")
    assert len(requests) == 1


def test_matching_explicit_source_can_resume_but_never_silently_change_to_default(online_release):
    work, requests, _payload = online_release
    url = "https://github.com/example/selected-kit.tar.gz"
    first = _acquire(work, online_url=url)
    second = _acquire(work, online_url=url)
    assert first.verification == second.verification
    assert requests == [url]
    with pytest.raises(ValueError, match="source"):
        _acquire(work)
    assert requests == [url]


@pytest.mark.parametrize("location", ["kit", "verified"])
@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "symlink", "hardlink"])
def test_cached_payload_damage_blocks_without_redownload_or_replacement(
    online_release, location, damage
):
    work, requests, _payload = online_release
    _acquire(work)
    target = work / location / "bin/opa"
    if damage == "changed":
        target.write_bytes(b"tampered")
    elif damage == "missing":
        target.unlink()
    elif damage == "extra":
        (work / location / "extra-file").write_bytes(b"not signed")
    elif damage == "symlink":
        target.unlink()
        target.symlink_to(work / "downloaded-kit.tar.gz")
    else:
        os.link(target, work / "foreign-linked-artifact")
    with pytest.raises(ValueError):
        _acquire(work)
    assert len(requests) == 1
    assert (work / "downloaded-kit.tar.gz").is_file()


def test_bad_signature_cannot_use_a_previously_materialized_payload(online_release):
    work, requests, _payload = online_release
    _acquire(work)
    signature = work / "kit/offline-kit.json.sig"
    signature.write_bytes(b"x" * 64)
    with pytest.raises(ValueError, match="signature"):
        _acquire(work)
    assert len(requests) == 1
    assert signature.read_bytes() == b"x" * 64


@pytest.mark.parametrize("damage", ["truncated", "symlink", "hardlink", "public-mode"])
def test_unsafe_retained_archive_is_preserved_and_rejected(online_release, damage):
    work, requests, payload = online_release
    target = work / "downloaded-kit.tar.gz"
    original = work / "original.tar.gz"
    original.write_bytes(payload)
    original.chmod(0o600)
    if damage == "symlink":
        target.symlink_to(original)
    elif damage == "hardlink":
        os.link(original, target)
    else:
        target.write_bytes(b"truncated archive" if damage == "truncated" else payload)
        target.chmod(0o600 if damage == "truncated" else 0o644)
    with pytest.raises(ValueError, match="archive"):
        _acquire(work)
    assert requests == []
    assert target.lstat()
    assert original.read_bytes() == payload


def test_existing_download_destination_is_local_error_before_network(tmp_path, monkeypatch):
    target = tmp_path / "downloaded-kit.tar.gz"
    target.write_bytes(b"retained")

    def forbidden(*_args, **_kwargs):
        pytest.fail("a known destination conflict must not open the network")

    monkeypatch.setattr(deployment_kit.urllib.request, "urlopen", forbidden)
    with pytest.raises(ValueError, match="destination already exists"):
        deployment_kit._download("https://github.com/example/kit.tar.gz", target)
    assert target.read_bytes() == b"retained"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_http_download_errors_report_status_without_url_or_provider_text(
    tmp_path, monkeypatch, status
):
    error = urllib.error.HTTPError(
        "https://github.com/example/kit.tar.gz?token=private-marker",
        status,
        "private-provider-marker",
        {},
        None,
    )

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(deployment_kit.urllib.request, "urlopen", fail)
    with pytest.raises(ValueError, match=f"HTTP {status}") as captured:
        deployment_kit._download(
            "https://github.com/example/kit.tar.gz", tmp_path / "download.tar.gz"
        )
    assert "private-marker" not in str(captured.value)
    assert "private-provider-marker" not in str(captured.value)
    assert "https://" not in str(captured.value)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionError(errno.EACCES, "private-path"), "permission"),
        (OSError(errno.ENOSPC, "private-path"), "storage"),
        (urllib.error.URLError("private-proxy"), "connection"),
        (TimeoutError("private-host"), "timed out"),
    ],
)
def test_download_errors_keep_network_and_local_failures_distinct(
    tmp_path, monkeypatch, error, expected
):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(deployment_kit.urllib.request, "urlopen", fail)
    with pytest.raises(ValueError, match=expected) as captured:
        deployment_kit._download(
            "https://github.com/example/kit.tar.gz", tmp_path / "download.tar.gz"
        )
    assert "private-" not in str(captured.value)


def test_acquisition_lock_blocks_overlap_then_releases(online_release):
    from fdai_deployment_cli.deployment_kit_cache import acquisition_lock

    work, requests, _payload = online_release
    with acquisition_lock(work):
        with pytest.raises(ValueError, match="already active"):
            _acquire(work)
    assert requests == []
    assert not list(work.iterdir())
    assert _acquire(work).source_commit
    assert len(requests) == 1


@pytest.mark.parametrize("location", ["kit", "verified"])
def test_writable_cached_directory_is_not_reused(online_release, location):
    work, requests, _payload = online_release
    _acquire(work)
    (work / location / "runtime").chmod(0o777)
    with pytest.raises(ValueError, match="directory is unsafe"):
        _acquire(work)
    assert len(requests) == 1


def test_source_record_never_contains_the_raw_url(online_release):
    work, _requests, _payload = online_release
    url = "https://github.com/example/kit.tar.gz?release=opaque-local-marker"
    _acquire(work, online_url=url)
    text = (work / "online-source.json").read_text()
    assert url not in text
    assert "opaque-local-marker" not in text
    assert len(json.loads(text)["source_sha256"]) == 64


@pytest.mark.parametrize("record", ['{"schema_version": "wrong"}', '{"kind": []}', "invalid"])
def test_invalid_source_record_never_falls_back_to_network(online_release, record):
    work, requests, _payload = online_release
    marker = work / "online-source.json"
    marker.write_text(record)
    marker.chmod(0o600)
    with pytest.raises(ValueError):
        _acquire(work)
    assert requests == []
    assert marker.read_text() == record


def test_cached_tree_metadata_walk_is_bounded(online_release, monkeypatch):
    from fdai_deployment_cli import deployment_kit_cache

    work, requests, _payload = online_release
    _acquire(work)
    monkeypatch.setattr(deployment_kit_cache, "_MAX_CACHE_ENTRIES", 1)
    with pytest.raises(ValueError, match="entry limit"):
        _acquire(work)
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("../escape", tarfile.REGTYPE),
        ("kit/../../escape", tarfile.REGTYPE),
        ("other/payload", tarfile.REGTYPE),
        ("kit/link", tarfile.SYMTYPE),
        ("kit/link", tarfile.LNKTYPE),
        ("kit/device", tarfile.CHRTYPE),
        ("kit/pipe", tarfile.FIFOTYPE),
    ],
)
def test_retry_extraction_preserves_archive_safety(tmp_path, name, kind):
    archive_path = tmp_path / "input.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = "../outside"
        archive.addfile(info)
    original = archive_path.read_bytes()
    with pytest.raises(ValueError, match="archive member"):
        deployment_kit._extract_kit_archive(archive_path, tmp_path / "kit")
    assert archive_path.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.tar.gz"]


@pytest.mark.parametrize("limit", ["_MAX_ARCHIVE_BYTES", "_MAX_MEMBER_BYTES", "_MAX_ARCHIVE_FILES"])
def test_retry_extraction_retains_the_original_bounds(tmp_path, monkeypatch, limit):
    archive_path = tmp_path / "input.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in ("kit/first", "kit/second"):
            info = tarfile.TarInfo(name)
            info.size = 5
            archive.addfile(info, io.BytesIO(b"bytes"))
    monkeypatch.setattr(deployment_kit, limit, 1)
    with pytest.raises(ValueError):
        deployment_kit._extract_kit_archive(archive_path, tmp_path / "kit")
    assert not (tmp_path / "kit").exists()
    assert archive_path.is_file()


def test_retry_extraction_never_follows_an_archive_symlink(tmp_path):
    original = tmp_path / "original.tar.gz"
    original.write_bytes(b"untrusted")
    linked = tmp_path / "linked.tar.gz"
    linked.symlink_to(original)
    with pytest.raises(OSError):
        deployment_kit._extract_kit_archive(linked, tmp_path / "kit")
    assert original.read_bytes() == b"untrusted"
    assert linked.is_symlink()
    assert not (tmp_path / "kit").exists()
