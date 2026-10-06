from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from fdai_deployment_cli import source_host_tools as tools

_REPO = Path(__file__).resolve().parents[3]
_KUBECTL = b"kubectl-binary"
_KUBELOGIN = b"kubelogin-binary"


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, content in members.items():
            bundle.writestr(name, content)
    return buffer.getvalue()


_ARCHIVE = _zip({"bin/linux_amd64/kubelogin": _KUBELOGIN})


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    responses = {"kubectl": _KUBECTL, "kubelogin": _ARCHIVE}
    monkeypatch.setattr(tools, "KUBECTL_SHA256", hashlib.sha256(_KUBECTL).hexdigest())
    monkeypatch.setattr(tools, "KUBELOGIN_ARCHIVE_SHA256", hashlib.sha256(_ARCHIVE).hexdigest())
    monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tools.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        tools,
        "_download",
        lambda url, _deadline: responses["kubectl" if url.endswith("/kubectl") else "kubelogin"],
    )
    return responses


def test_pins_match_the_offline_kit_build() -> None:
    script = (_REPO / "scripts/deployment/release/stage-offline-kit.sh").read_text("utf-8")
    amd64 = script[script.index("linux_amd64)") : script.index("linux_arm64)")]

    def value(name: str, text: str) -> str:
        match = re.search(rf'^\s*{name}="([^"]+)"', text, re.MULTILINE)
        assert match is not None, name
        return match.group(1)

    assert tools.KUBECTL_VERSION == value("KUBECTL_VERSION", script)
    assert tools.KUBELOGIN_VERSION == value("KUBELOGIN_VERSION", script)
    assert tools.KUBECTL_SHA256 == value("KUBECTL_SHA256", amd64)
    assert tools.KUBELOGIN_ARCHIVE_SHA256 == value("KUBELOGIN_SHA256", amd64)


def test_installs_verified_tools_privately_and_reuses_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned: dict[str, bytes]
) -> None:
    tmp_path.chmod(0o700)
    directory = tools.install_kubernetes_tools(tmp_path / "source-tools")

    assert (directory / "kubectl").read_bytes() == _KUBECTL
    assert (directory / "kubelogin").read_bytes() == _KUBELOGIN
    assert (directory / "kubectl").stat().st_mode & 0o777 == 0o700
    receipt = json.loads((directory / "kubernetes-tools.json").read_text())
    assert receipt["binary_sha256"]["kubelogin"] == hashlib.sha256(_KUBELOGIN).hexdigest()

    monkeypatch.setattr(
        tools, "_download", lambda *_args: pytest.fail("verified tools were downloaded again")
    )
    assert tools.install_kubernetes_tools(directory) == directory


def test_replaces_a_changed_retained_tool(tmp_path: Path, pinned: dict[str, bytes]) -> None:
    tmp_path.chmod(0o700)
    directory = tools.install_kubernetes_tools(tmp_path / "source-tools")
    (directory / "kubelogin").write_bytes(b"tampered")

    tools.install_kubernetes_tools(directory)

    assert (directory / "kubelogin").read_bytes() == _KUBELOGIN


@pytest.mark.parametrize("tool", ["kubectl", "kubelogin"])
def test_refuses_a_download_that_does_not_match_its_pin(
    tmp_path: Path, pinned: dict[str, bytes], tool: str
) -> None:
    tmp_path.chmod(0o700)
    pinned[tool] = b"changed"
    with pytest.raises(ValueError, match="does not match the committed digest"):
        tools.install_kubernetes_tools(tmp_path / "source-tools")
    assert not (tmp_path / "source-tools/kubernetes-tools.json").exists()


@pytest.mark.parametrize(
    "members",
    [
        {"bin/linux_amd64/kubelogin": _KUBELOGIN, "bin/linux_amd64/extra": b"x"},
        {"bin/linux_amd64/kubectl": _KUBELOGIN},
    ],
)
def test_refuses_an_unexpected_kubelogin_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pinned: dict[str, bytes],
    members: dict[str, bytes],
) -> None:
    tmp_path.chmod(0o700)
    archive = _zip(members)
    pinned["kubelogin"] = archive
    monkeypatch.setattr(tools, "KUBELOGIN_ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest())
    with pytest.raises(ValueError, match="member set is invalid"):
        tools.install_kubernetes_tools(tmp_path / "source-tools")


def test_refuses_other_platforms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools.platform, "machine", lambda: "aarch64")
    with pytest.raises(ValueError, match="linux_amd64 only"):
        tools.install_kubernetes_tools(tmp_path / "source-tools")


def test_redirects_must_stay_on_https() -> None:
    handler = tools._HttpsOnlyRedirect()
    with pytest.raises(ValueError, match="HTTPS redirects only"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://example.invalid/kubectl")
