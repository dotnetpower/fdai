"""Static contract keeping local type checks aligned with CI."""

import json
from pathlib import Path

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

    assert "- name: mypy --strict\n        run: uv run mypy" in ci
    assert 'run_gate_scoped "mypy (strict)"' in verify
    assert verify.index('run_gate_scoped "mypy (strict)"') < verify.index(
        'if [[ "$MODE" == "full" ]]'
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

    assert 'uv run --extra dev ruff check "${py[@]}"' in pre_push
    assert 'uv run --extra dev ruff format --check "${py[@]}"' in pre_push


def test_opa_downloads_are_bounded_and_checksum_verified() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    downloads = ci.count("openpolicyagent.org/downloads/v0.68.0/opa_linux_amd64_static")
    assert downloads == 4
    assert ci.count("--retry 3 --retry-delay 2 --retry-all-errors") == downloads
    assert ci.count("--retry-max-time 120 --connect-timeout 10 --max-time 90") == downloads
    assert ci.count("dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa") == downloads


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
    dockerfile = (_ROOT / "services" / "core-control-plane" / "docker" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "ARG OPA_VERSION=v1.18.2" in dockerfile
    assert "ARG OPA_GRPC_VERSION=v1.82.1" in dockerfile
    assert "ARG OPA_X_TEXT_VERSION=v0.39.0" in dockerfile
    assert "ARG OPA_ORAS_VERSION=v2.6.2" in dockerfile
    assert 'go mod edit -require="google.golang.org/grpc@${OPA_GRPC_VERSION}"' in dockerfile
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
