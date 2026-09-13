"""Exercise actual acquisition boundaries without provider or artifact network access."""

from __future__ import annotations

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
