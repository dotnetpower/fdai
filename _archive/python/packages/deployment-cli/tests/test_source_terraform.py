"""The source path fetches only the committed Terraform release and verifies both digests."""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from fdai_deployment_cli import source_terraform

BINARY = b"pinned terraform binary"


def _archive(content: bytes = BINARY, name: str = "terraform") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, content)
    return buffer.getvalue()


def _toolchain(archive: bytes, binary: bytes = BINARY) -> dict[str, str]:
    return {
        "terraform_version": "1.9.8",
        "terraform_sha256": hashlib.sha256(archive).hexdigest(),
        "terraform_binary_sha256": hashlib.sha256(binary).hexdigest(),
    }


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def served(monkeypatch):
    urls: list[str] = []

    def serve(payload: bytes) -> list[str]:
        class Opener:
            def open(self, url, timeout):
                urls.append(url)
                return _Response(payload)

        monkeypatch.setattr(source_terraform.urllib.request, "build_opener", lambda *_: Opener())
        monkeypatch.setattr(source_terraform.platform, "system", lambda: "Linux")
        monkeypatch.setattr(source_terraform.platform, "machine", lambda: "x86_64")
        return urls

    return serve


def test_pinned_release_is_written_private_and_executable(tmp_path, served):
    archive = _archive()
    urls = served(archive)
    target = source_terraform.download_pinned_terraform(
        toolchain=_toolchain(archive), destination=tmp_path / "terraform"
    )
    assert target.read_bytes() == BINARY
    assert target.stat().st_mode & 0o777 == 0o700
    assert urls == [
        "https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip"
    ]


@pytest.mark.parametrize(
    "case,message",
    [
        ("archive-digest", "archive does not match"),
        ("binary-digest", "binary does not match"),
        ("no-member", "has no terraform binary"),
    ],
)
def test_mismatched_release_is_never_written(tmp_path, served, case, message):
    archive = _archive(name="other" if case == "no-member" else "terraform")
    toolchain = _toolchain(archive)
    if case == "archive-digest":
        toolchain["terraform_sha256"] = "0" * 64
    if case == "binary-digest":
        toolchain["terraform_binary_sha256"] = "0" * 64
    served(archive)
    with pytest.raises(ValueError, match=message):
        source_terraform.download_pinned_terraform(
            toolchain=toolchain, destination=tmp_path / "terraform"
        )
    assert not (tmp_path / "terraform").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("terraform_version", "latest"),
        ("terraform_sha256", None),
        ("terraform_binary_sha256", "ABC"),
    ],
)
def test_unpinned_toolchain_never_downloads(tmp_path, served, field, value):
    archive = _archive()
    urls = served(archive)
    toolchain = {**_toolchain(archive), field: value}
    with pytest.raises(ValueError, match="does not pin"):
        source_terraform.download_pinned_terraform(
            toolchain=toolchain, destination=tmp_path / "terraform"
        )
    assert urls == []


def test_unpinned_platform_asks_for_a_local_install(tmp_path, served, monkeypatch):
    archive = _archive()
    urls = served(archive)
    monkeypatch.setattr(source_terraform.platform, "machine", lambda: "aarch64")
    with pytest.raises(ValueError, match="install Terraform 1.9.8 on PATH"):
        source_terraform.download_pinned_terraform(
            toolchain=_toolchain(archive), destination=tmp_path / "terraform"
        )
    assert urls == []


def test_unavailable_release_is_not_retried(tmp_path, monkeypatch):
    calls = []

    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            raise OSError("offline")

    monkeypatch.setattr(source_terraform.urllib.request, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(source_terraform.platform, "system", lambda: "Linux")
    monkeypatch.setattr(source_terraform.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="download unavailable"):
        source_terraform.download_pinned_terraform(
            toolchain=_toolchain(_archive()), destination=tmp_path / "terraform"
        )
    assert len(calls) == 1


def test_release_redirects_are_never_followed():
    with pytest.raises(ValueError, match="redirects"):
        source_terraform._NoRedirect().redirect_request(None, None, None, None, None, None)
