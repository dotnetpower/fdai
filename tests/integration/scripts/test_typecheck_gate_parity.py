"""Static contract keeping local type checks aligned with CI."""

import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]


def test_strict_mypy_runs_in_ci_fast_verify_and_central_queue() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    verify = (_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    pre_commit = (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    validation_queue = "\n".join(
        (_ROOT / "scripts" / "automation" / path).read_text(encoding="utf-8")
        for path in ("validation_queue.py", "validation_queue_runner.py")
    )
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "uv run mypy" in ci
    assert 'run_gate_scoped "mypy (strict)"' in verify
    assert verify.index('if [[ "$MODE" == "full" ]]') < verify.index(
        'run_gate_scoped "mypy (strict)"'
    )
    assert "- id: mypy-strict" not in pre_commit
    assert '"scripts/verify.sh",' in validation_queue
    assert '"--fast",' in validation_queue
    assert '"--diff",' in validation_queue
    assert '"scripts/**" = ["N999", "S603", "S607"]' in pyproject


def test_ruff_uses_the_same_monorepo_roots_in_ci_and_local_gates() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    verify = (_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    roots = "services packages tests extensions/code-assurance"

    for command in (f"ruff format --check {roots}", f"ruff check {roots}"):
        assert command in ci
        assert command in makefile
        assert command in verify
    assert "ruff format --check src tests" not in ci
    assert "ruff check src tests" not in ci


def test_pre_push_ruff_uses_locked_development_dependencies() -> None:
    pre_push = (_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")

    assert 'python3 scripts/automation/local_validation_cache.py command -- "$@"' in pre_push
    assert 'uv run --extra dev ruff check "$@"' in pre_push
    assert 'uv run --extra dev ruff format --check "$@"' in pre_push
    assert "run_project bash -c" in pre_push


def test_opa_downloads_are_bounded_and_checksum_verified() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = yaml.safe_load(ci)["jobs"]
    action = (_ROOT / ".github" / "actions" / "setup-opa" / "action.yml").read_text(
        encoding="utf-8"
    )

    assert {
        job_id
        for job_id, job in jobs.items()
        if any(step.get("uses") == "./.github/actions/setup-opa" for step in job.get("steps", ()))
    } == {
        "python-tests",
        "python-tests-ssd",
        "python-tests-elastic",
        "python-coverage-shards",
        "governance-runtime-contracts",
        "db-integration",
    }
    assert "openpolicyagent.org/downloads" not in ci
    assert action.count("openpolicyagent.org/downloads/v0.68.0/opa_linux_amd64_static") == 1
    assert action.count("--retry 3 --retry-delay 2 --retry-all-errors") == 1
    assert action.count("--retry-max-time 120 --connect-timeout 10 --max-time 90") == 1
    assert action.count("dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa") == 1


def test_opa_setup_is_job_local_and_does_not_require_sudo() -> None:
    action = yaml.safe_load(
        (_ROOT / ".github/actions/setup-opa/action.yml").read_text(encoding="utf-8")
    )
    script = action["runs"]["steps"][0]["run"]
    assert 'opa_dir="$RUNNER_TEMP/fdai-opa/bin"' in script
    assert '-o "$opa_dir/opa"' in script
    assert 'chmod +x "$opa_dir/opa"' in script
    assert 'echo "$opa_dir" >> "$GITHUB_PATH"' in script
    assert '"$opa_dir/opa" version' in script
    assert "sudo" not in script
    assert "/tmp/opa" not in script  # noqa: S108 - forbid the old shared download path
    assert "/usr/local/bin" not in script


def test_opa_setup_executes_with_five_separate_job_directories(tmp_path: Path) -> None:
    action = yaml.safe_load(
        (_ROOT / ".github/actions/setup-opa/action.yml").read_text(encoding="utf-8")
    )
    script = action["runs"]["steps"][0]["run"]
    assert "sudo" not in script
    fixture = tmp_path / "opa-fixture"
    payload = b'#!/usr/bin/env bash\nset -eu\ntest "$1" = version\necho opa-fixture\n'
    fixture.write_bytes(payload)
    # Keep network out of this execution test; the real archive pin is asserted separately.
    script = script.replace(
        "dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa",
        hashlib.sha256(payload).hexdigest(),
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    curl = tools / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "target = Path(sys.argv[sys.argv.index('-o') + 1]).resolve()\n"
        "root = Path(os.environ['RUNNER_TEMP']).resolve()\n"
        "if not target.is_relative_to(root):\n"
        "    raise SystemExit('download escaped the job directory')\n"
        "target.write_bytes(Path(os.environ['OPA_FIXTURE']).read_bytes())\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    def install(slot: int) -> str:
        job = tmp_path / f"job {slot}"
        job.mkdir()
        github_path = job / "github-path"
        environment = {
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "OPA_FIXTURE": str(fixture),
            "RUNNER_TEMP": str(job),
            "GITHUB_PATH": str(github_path),
        }
        result = subprocess.run(  # noqa: S603 - checked repository action, synthetic download
            ["/usr/bin/bash", "-c", script],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "opa-fixture" in result.stdout
        directory = job / "fdai-opa" / "bin"
        assert github_path.read_text() == str(directory) + "\n"
        assert (directory / "opa").read_bytes() == payload
        return str(directory)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        directories = list(executor.map(install, range(1, 6)))
    assert len(set(directories)) == 5


def test_every_retrying_deploy_curl_declares_a_cumulative_retry_window() -> None:
    """A retry count times a per-request cap is a product, not a declared envelope."""
    for relative in ("deploy-dev.yml", "service-deploy.yml", "ci.yml"):
        workflow = (_ROOT / ".github" / "workflows" / relative).read_text(encoding="utf-8")
        command: list[str] | None = None
        for line in workflow.splitlines():
            stripped = line.strip()
            if command is None and "curl " not in stripped:
                continue
            if command is None:
                command = []
            command.append(stripped.removesuffix("\\"))
            if stripped.endswith("\\"):
                continue
            joined = " ".join(command)
            command = None
            if "--retry " not in joined:
                continue
            assert "--retry-max-time " in joined, f"{relative}: unbounded retry envelope: {joined}"


def test_container_opa_build_overrides_vulnerable_go_modules() -> None:
    dockerfile_paths = (
        _ROOT / "benchmarks" / "sregym" / "Dockerfile",
        _ROOT / "extensions" / "cost-governance" / "docker" / "Dockerfile",
        _ROOT / "services" / "core-control-plane" / "docker" / "Dockerfile",
    )
    for path in dockerfile_paths:
        content = path.read_text(encoding="utf-8")
        assert "ARG OPA_GRPC_VERSION=v1.83.2" in content, path
        assert "ARG OPA_X_CRYPTO_VERSION=v0.57.0" in content, path
        assert "ARG OPA_X_TEXT_VERSION=v0.42.0" in content, path
        assert "ARG OPA_GO_VERSION=go1.27.3" in content, path
        assert "ARG OPA_X_NET_VERSION=v0.60.0" in content, path
        assert "ARG OPA_KLAUSPOST_COMPRESS_VERSION=v1.18.7" in content, path
        assert "ENV GOTOOLCHAIN=local" in content, path
        assert "GOEXPERIMENT=nojsonv2" in content, path
        assert (
            "golang@sha256:f2c872bcee949b7be9c490efd02b48a8a2fbf947cdf533f1c58525ec9d8170fd"
            in content
        )
        assert 'go mod edit -require="golang.org/x/net@${OPA_X_NET_VERSION}"' in content
        assert (
            'go mod edit -require="github.com/klauspost/compress@${OPA_KLAUSPOST_COMPRESS_VERSION}"'
            in content
        )
        assert "awk '$2 == \"golang.org/x/net\" {print $3}'" in content
        assert "awk '$2 == \"github.com/klauspost/compress\" {print $3}'" in content
        assert "awk '$2 == \"golang.org/x/crypto\" {print $3}'" in content
        assert "awk '$2 == \"golang.org/x/text\" {print $3}'" in content
        assert 'test "$(/usr/local/go/bin/go env GOVERSION)" = "${OPA_GO_VERSION}"' in content

    dockerfile = dockerfile_paths[-1].read_text(encoding="utf-8")

    assert "ARG OPA_VERSION=v1.18.2" in dockerfile
    assert "ARG OPA_X_TEXT_VERSION=v0.42.0" in dockerfile
    assert "ARG OPA_ORAS_VERSION=v2.6.2" in dockerfile
    assert 'go mod edit -require="google.golang.org/grpc@${OPA_GRPC_VERSION}"' in dockerfile
    assert 'go mod edit -require="golang.org/x/crypto@${OPA_X_CRYPTO_VERSION}"' in dockerfile
    assert 'go mod edit -require="golang.org/x/text@${OPA_X_TEXT_VERSION}"' in dockerfile
    assert 'go mod edit -require="oras.land/oras-go/v2@${OPA_ORAS_VERSION}"' in dockerfile
    assert "go build -mod=mod -o /go/bin/opa ." in dockerfile
    assert "awk '$2 == \"google.golang.org/grpc\" {print $3}'" in dockerfile
    assert "awk '$2 == \"golang.org/x/text\" {print $3}'" in dockerfile
    assert "awk '$2 == \"oras.land/oras-go/v2\" {print $3}'" in dockerfile


def test_console_test_types_run_in_the_enforced_operator_gate() -> None:
    runner = (_ROOT / "scripts" / "quality" / "ci" / "run-operator-surfaces.sh").read_text(
        encoding="utf-8"
    )
    package = (_ROOT / "console" / "package.json").read_text(encoding="utf-8")
    tests_project = (_ROOT / "console" / "tsconfig.tests.json").read_text(encoding="utf-8")

    assert "npm --prefix console exec -- tsc --noEmit -p console/tsconfig.tests.json" in runner
    # `npm exec` keeps the caller's directory, so a bare project path would abort the whole gate.
    assert "-p tsconfig.tests.json" not in runner
    assert "tsc --noEmit -p tsconfig.tests.json" in package
    assert '"include": ["tests", "scripts"]' in tests_project
    # The gate must keep the application typecheck without paying for it twice.
    assert "npm --prefix console run typecheck" not in runner
    assert json.loads(package)["scripts"]["build"].startswith("tsc --noEmit")
