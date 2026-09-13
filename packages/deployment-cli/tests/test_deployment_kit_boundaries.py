"""Exercise actual acquisition boundaries without provider or artifact network access."""

from __future__ import annotations

import io
import os
import tarfile
import urllib.request
import urllib.response
from email.message import Message
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import deployment_kit


@pytest.mark.parametrize("system", ["Darwin", "FreeBSD"])
def test_non_linux_posix_hosts_are_not_reported_as_linux(monkeypatch, system):
    monkeypatch.setattr(deployment_kit.platform, "system", lambda: system)
    monkeypatch.setattr(deployment_kit.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="Linux x86_64"):
        deployment_kit.runtime_platform_tag()


@pytest.mark.parametrize("online", [False, True])
def test_unsupported_host_stops_before_any_acquisition(tmp_path, monkeypatch, online):
    monkeypatch.setattr(deployment_kit.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(deployment_kit.platform, "machine", lambda: "x86_64")

    def forbidden(**_kwargs):
        pytest.fail("unsupported hosts must stop before reading or downloading artifacts")

    monkeypatch.setattr(deployment_kit, "_acquire_deployment_kit", forbidden)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="Linux x86_64"):
        deployment_kit.acquire_deployment_kit(
            work_dir=work,
            online=online,
            offline_kit=None if online else tmp_path / "absent.tar.gz",
        )
    assert list(work.iterdir()) == []


def test_linux_x86_64_remains_supported(monkeypatch):
    monkeypatch.setattr(deployment_kit.platform, "system", lambda: "Linux")
    monkeypatch.setattr(deployment_kit.platform, "machine", lambda: "x86_64")
    assert deployment_kit.runtime_platform_tag() == "linux-x86_64"


def test_open_archive_descriptor_survives_path_replacement(tmp_path, monkeypatch):
    archive = tmp_path / "kit.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        member = tarfile.TarInfo("kit/payload")
        member.size = len(b"original bytes")
        stream.addfile(member, io.BytesIO(b"original bytes"))
    original_inode = archive.stat().st_ino
    extract = deployment_kit._extract_kit_members

    def replace_after_open(raw, temporary):
        archive.unlink()
        archive.write_bytes(b"replacement is not an archive")
        assert os.fstat(raw.fileno()).st_ino == original_inode
        assert archive.stat().st_ino != original_inode
        extract(raw, temporary)

    monkeypatch.setattr(deployment_kit, "_extract_kit_members", replace_after_open)
    destination = tmp_path / "extracted"
    deployment_kit._extract_kit_archive(archive, destination)
    assert (destination / "payload").read_bytes() == b"original bytes"
    assert archive.read_bytes() == b"replacement is not an archive"


@pytest.mark.parametrize(
    ("redirect", "allowed"),
    [
        ("https://example.com/kit", False),
        ("http://github.com/kit", False),
        ("https://github.com:444/kit", False),
        ("https://release-assets.githubusercontent.com/example/kit", True),
    ],
)
def test_download_rejects_redirect_before_contacting_disallowed_target(
    tmp_path, monkeypatch, redirect, allowed
):
    requested = []
    original = urllib.request.build_opener

    class SyntheticTransport(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
        def http_open(self, request):
            requested.append(request.full_url)
            headers = Message()
            code = 200
            if len(requested) == 1:
                headers["Location"] = redirect
                code = 302
            response = urllib.response.addinfourl(
                io.BytesIO(b"test"), headers, request.full_url, code
            )
            response.msg = "synthetic response"
            return response

        https_open = http_open

    def opener(*handlers):
        return original(SyntheticTransport(), *handlers)

    monkeypatch.setattr(urllib.request, "build_opener", opener)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, *, timeout: opener().open(request, timeout=timeout),
    )
    if allowed:
        deployment_kit._download("https://github.com/example/kit", tmp_path / "archive.tar.gz")
        assert requested == ["https://github.com/example/kit", redirect]
        assert (tmp_path / "archive.tar.gz").read_bytes() == b"test"
    else:
        with pytest.raises(ValueError, match="redirect"):
            deployment_kit._download("https://github.com/example/kit", tmp_path / "archive.tar.gz")
        assert requested == ["https://github.com/example/kit"]
        assert list(tmp_path.iterdir()) == []


def test_trickling_download_cannot_reset_total_transfer_budget(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(
        deployment_kit, "time", SimpleNamespace(monotonic=lambda: clock[0]), raising=False
    )

    class Trickle:
        def read(self, _size):
            clock[0] += 301
            return b"x" if clock[0] < 1500 else b""

    destination = tmp_path / "partial-download"
    with pytest.raises(TimeoutError, match="remaining budget"):
        deployment_kit._write_bounded_stream(Trickle(), destination)
    assert not destination.exists()
