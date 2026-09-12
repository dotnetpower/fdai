from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_BINDER = _ROOT / "scripts" / "deployment" / "azure" / "bind_core_runtime_image.sh"
_SOURCE_DIGEST = f"sha256:{'a' * 64}"
_GHCR_CREDENTIAL = "synthetic-ghcr-credential"
_REGISTRY_BEARER = "synthetic-registry-bearer"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="ascii")
    path.chmod(0o755)


def _install_fakes(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_CURL_CALLS"
if [[ "$*" == *"https://ghcr.io/token?"* ]]; then
  printf '{"token":"%s"}\n' "$FAKE_REGISTRY_BEARER"
elif [[ "$*" == *"/manifests/sha-"* ]]; then
  printf 'HTTP/1.1 200 OK\r\ndocker-content-digest: %s\r\n\r\n' "$FAKE_SOURCE_DIGEST"
else
  exit 90
fi
""",
    )
    _write_executable(
        bin_dir / "gh",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" > "$FAKE_GH_ARGS"
{
  printf 'directory=%s\n' "$(stat -c '%a' "$DOCKER_CONFIG")"
  printf 'config=%s\n' "$(stat -c '%a' "$DOCKER_CONFIG/config.json")"
  grep -q '"ghcr.io"' "$DOCKER_CONFIG/config.json" && printf 'registry=true\n'
  grep -q '"auth"' "$DOCKER_CONFIG/config.json" && printf 'auth=true\n'
} > "$FAKE_DOCKER_METADATA"
exit "$FAKE_GH_EXIT"
""",
    )
    forbidden = """#!/usr/bin/env bash
set -euo pipefail
printf '%s %s\n' "$(basename "$0")" "$*" >> "$FAKE_FORBIDDEN_CALLS"
exit 97
"""
    _write_executable(bin_dir / "terraform", forbidden)
    _write_executable(bin_dir / "az", forbidden)
    _write_executable(bin_dir / "docker", forbidden)


def _run_verification(
    tmp_path: Path,
    *,
    gh_exit: int,
    profile: str = "core-control-plane",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Path], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_fakes(bin_dir)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    paths = {
        "curl_calls": tmp_path / "curl-calls",
        "docker_metadata": tmp_path / "docker-metadata",
        "forbidden_calls": tmp_path / "forbidden-calls",
        "gh_args": tmp_path / "gh-args",
        "github_env": tmp_path / "github-env",
        "runner_temp": runner_temp,
    }
    paths["github_env"].write_text("", encoding="ascii")
    git = shutil.which("git")
    assert git is not None
    revision = subprocess.run(  # noqa: S603 - resolved host Git reads this checkout only
        [git, "rev-parse", "HEAD"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = subprocess.run(  # noqa: S603 - controlled repository script and fake PATH
        [str(_BINDER), "--verify-only"],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ATTESTATION_SIGNER_WORKFLOW": (
                "example/fdai/.github/workflows/container-supply-chain.yml"
            ),
            "FAKE_CURL_CALLS": str(paths["curl_calls"]),
            "FAKE_DOCKER_METADATA": str(paths["docker_metadata"]),
            "FAKE_FORBIDDEN_CALLS": str(paths["forbidden_calls"]),
            "FAKE_GH_ARGS": str(paths["gh_args"]),
            "FAKE_GH_EXIT": str(gh_exit),
            "FAKE_REGISTRY_BEARER": _REGISTRY_BEARER,
            "FAKE_SOURCE_DIGEST": _SOURCE_DIGEST,
            "GITHUB_ACTOR": "example-actor",
            "GITHUB_ENV": str(paths["github_env"]),
            "GITHUB_REPOSITORY": "example/fdai",
            "GHCR_TOKEN": _GHCR_CREDENTIAL,
            "RUNNER_TEMP": str(runner_temp),
            "RUNTIME_IMAGE_REVISION": revision,
            "RUNTIME_IMAGE_PROFILE": profile,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, paths, revision


def test_verifies_registry_bundle_with_exact_provenance_contract(tmp_path: Path) -> None:
    result, paths, revision = _run_verification(tmp_path, gh_exit=0)

    assert result.returncode == 0, result.stderr
    assert paths["gh_args"].read_text(encoding="ascii").strip() == " ".join(
        (
            "attestation verify",
            f"oci://ghcr.io/example/fdai/fdai-core-control-plane@{_SOURCE_DIGEST}",
            "--bundle-from-oci",
            "--repo example/fdai",
            f"--source-digest {revision}",
            "--predicate-type https://slsa.dev/provenance/v1",
            "--signer-workflow example/fdai/.github/workflows/container-supply-chain.yml",
        )
    )
    assert paths["docker_metadata"].read_text(encoding="ascii") == (
        "directory=700\nconfig=600\nregistry=true\nauth=true\n"
    )
    assert paths["github_env"].read_text(encoding="ascii").splitlines() == [
        "FDAI_VERIFIED_RUNTIME_IMAGE_REPOSITORY=example/fdai/fdai-core-control-plane",
        f"FDAI_VERIFIED_RUNTIME_IMAGE_REVISION={revision}",
        f"FDAI_VERIFIED_RUNTIME_IMAGE_DIGEST={_SOURCE_DIGEST}",
        "FDAI_VERIFIED_RUNTIME_IMAGE_PROFILE=core-control-plane",
    ]
    assert not paths["forbidden_calls"].exists()
    assert not list(paths["runner_temp"].glob("fdai-core-image.*"))
    assert not list(paths["runner_temp"].glob("fdai-ghcr-docker.*"))


def test_attestation_failure_stops_before_terraform_or_acr(tmp_path: Path) -> None:
    result, paths, _revision = _run_verification(tmp_path, gh_exit=17)

    assert result.returncode == 1
    assert "Core runtime image provenance verification failed." in result.stderr
    assert paths["github_env"].read_text(encoding="ascii") == ""
    assert not paths["forbidden_calls"].exists()
    assert not list(paths["runner_temp"].glob("fdai-core-image.*"))
    assert not list(paths["runner_temp"].glob("fdai-ghcr-docker.*"))
    captured = "\n".join(
        (
            result.stdout,
            result.stderr,
            paths["curl_calls"].read_text(encoding="ascii"),
            paths["gh_args"].read_text(encoding="ascii"),
        )
    )
    assert _GHCR_CREDENTIAL not in captured
    assert _REGISTRY_BEARER not in captured


def _install_binding_fakes(bin_dir: Path) -> None:
    forbidden = """#!/usr/bin/env bash
set -euo pipefail
printf '%s %s\n' "$(basename "$0")" "$*" >> "$FAKE_FORBIDDEN_CALLS"
exit 97
"""
    for name in ("curl", "docker", "gh", "terraform"):
        _write_executable(bin_dir / name, forbidden)
    _write_executable(
        bin_dir / "az",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZ_CALLS"
case "${1:-} ${2:-}" in
  "acr show")
    printf '%s\n' "$FAKE_ACR_ID"
    ;;
  "rest --method")
    exit "$FAKE_IMPORT_EXIT"
    ;;
  "acr manifest")
    printf '%s\n' "$FAKE_SOURCE_DIGEST"
    ;;
  *)
    exit 96
    ;;
esac
""",
    )


def _run_binding(
    tmp_path: Path,
    *,
    acr_id: str = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example/providers/Microsoft.ContainerRegistry/registries/example"
    ),
    import_exit: int = 0,
    profile: str = "core-control-plane",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Path], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_binding_fakes(bin_dir)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    github_env = tmp_path / "github-env"
    github_env.write_text("", encoding="ascii")
    az_calls = tmp_path / "az-calls"
    forbidden_calls = tmp_path / "forbidden-calls"
    git = shutil.which("git")
    assert git is not None
    revision = subprocess.run(  # noqa: S603 - resolved host Git reads this checkout only
        [git, "rev-parse", "HEAD"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = subprocess.run(  # noqa: S603 - controlled repository script and fake PATH
        [str(_BINDER), "--bind-verified"],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_ACR_ID": acr_id,
            "FAKE_AZ_CALLS": str(az_calls),
            "FAKE_FORBIDDEN_CALLS": str(forbidden_calls),
            "FAKE_GHCR_CREDENTIAL": _GHCR_CREDENTIAL,
            "FAKE_IMPORT_EXIT": str(import_exit),
            "FAKE_SOURCE_DIGEST": _SOURCE_DIGEST,
            "FDAI_ACR_LOGIN_SERVER": "example.azurecr.io",
            "FDAI_VERIFIED_RUNTIME_IMAGE_DIGEST": _SOURCE_DIGEST,
            "FDAI_VERIFIED_RUNTIME_IMAGE_REPOSITORY": (
                "example/fdai/fdai-cost-governance"
                if profile == "cost-governance"
                else "example/fdai/fdai-core-control-plane"
            ),
            "FDAI_VERIFIED_RUNTIME_IMAGE_REVISION": revision,
            "FDAI_VERIFIED_RUNTIME_IMAGE_PROFILE": profile,
            "GITHUB_ACTOR": "example-actor",
            "GITHUB_ENV": str(github_env),
            "GITHUB_REPOSITORY": "example/fdai",
            "GHCR_TOKEN": _GHCR_CREDENTIAL,
            "PROMOTE_RUNTIME_IMAGE": "true",
            "RUNNER_TEMP": str(runner_temp),
            "RUNTIME_IMAGE_REVISION": revision,
            "RUNTIME_IMAGE_PROFILE": profile,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        result,
        {
            "az_calls": az_calls,
            "forbidden_calls": forbidden_calls,
            "github_env": github_env,
            "runner_temp": runner_temp,
        },
        revision,
    )


def test_binds_verified_digest_after_exact_acr_import(tmp_path: Path) -> None:
    result, paths, revision = _run_binding(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "Resolved the target ACR login host.",
        "Resolved the target ACR resource.",
        "Accepted the exact runtime image import request.",
        "Verified the exact runtime image digest in ACR.",
    ]
    assert paths["github_env"].read_text(encoding="ascii").splitlines() == [
        f"TF_VAR_core_image=example.azurecr.io/fdai@{_SOURCE_DIGEST}",
        "FDAI_RUNTIME_IMAGE_PROFILE=core-control-plane",
        f"FDAI_RUNTIME_IMAGE_REVISION={revision}",
        f"FDAI_RUNTIME_IMAGE_DIGEST={_SOURCE_DIGEST}",
    ]
    assert not paths["forbidden_calls"].exists()
    assert not list(paths["runner_temp"].glob("fdai-core-image.*"))
    assert not list(paths["runner_temp"].glob("fdai-ghcr-docker.*"))


def test_cost_governance_profile_binds_one_digest_to_core_and_jobs(tmp_path: Path) -> None:
    verify_root = tmp_path / "verify"
    verify_root.mkdir()
    verification, verify_paths, revision = _run_verification(
        verify_root,
        gh_exit=0,
        profile="cost-governance",
    )

    assert verification.returncode == 0, verification.stderr
    assert f"oci://ghcr.io/example/fdai/fdai-cost-governance@{_SOURCE_DIGEST}" in verify_paths[
        "gh_args"
    ].read_text(encoding="ascii")

    bind_root = tmp_path / "bind"
    bind_root.mkdir()
    binding, bind_paths, _ = _run_binding(bind_root, profile="cost-governance")

    assert binding.returncode == 0, binding.stderr
    assert bind_paths["github_env"].read_text(encoding="ascii").splitlines() == [
        f"TF_VAR_core_image=example.azurecr.io/fdai-cost-governance@{_SOURCE_DIGEST}",
        f"TF_VAR_cost_governance_image=example.azurecr.io/fdai-cost-governance@{_SOURCE_DIGEST}",
        "FDAI_RUNTIME_IMAGE_PROFILE=cost-governance",
        f"FDAI_RUNTIME_IMAGE_REVISION={revision}",
        f"FDAI_RUNTIME_IMAGE_DIGEST={_SOURCE_DIGEST}",
    ]
    assert "--name fdai-cost-governance" in bind_paths["az_calls"].read_text(encoding="ascii")


def test_invalid_acr_id_stops_before_import(tmp_path: Path) -> None:
    result, paths, _revision = _run_binding(tmp_path, acr_id="invalid")

    assert result.returncode == 1
    assert "target ACR lookup returned an invalid resource id." in result.stderr
    assert "rest --method" not in paths["az_calls"].read_text(encoding="ascii")
    assert paths["github_env"].read_text(encoding="ascii") == ""
    assert not paths["forbidden_calls"].exists()


def test_import_failure_is_explicit_and_stops_before_readback(tmp_path: Path) -> None:
    result, paths, _revision = _run_binding(tmp_path, import_exit=23)

    assert result.returncode == 1
    assert "exact runtime image import request failed." in result.stderr
    assert "acr manifest" not in paths["az_calls"].read_text(encoding="ascii")
    assert paths["github_env"].read_text(encoding="ascii") == ""
    assert _GHCR_CREDENTIAL not in result.stdout + result.stderr
    assert not paths["forbidden_calls"].exists()
