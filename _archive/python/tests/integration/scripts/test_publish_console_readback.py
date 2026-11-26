"""Behavioral tests for the Console publisher's bounded static readback."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from fdai_deployment_cli.standalone_console_publish import _publisher_failure_reason

ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = ROOT / "scripts/deployment/azure/publish-console.sh"
HOSTNAME = "calm-field-012345678.3.azurestaticapps.net"
NOT_CONVERGED = "published Console content did not converge within the readback window"

_CURL_STUB = r"""#!/usr/bin/env bash
set -u
url="" output=""
while (($#)); do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    https://*) url="$1"; shift ;;
    *) shift ;;
  esac
done
calls=$(( $(cat "$STUB_STATE/curl-calls" 2>/dev/null || echo 0) + 1 ))
echo "$calls" > "$STUB_STATE/curl-calls"
path="${url#https://*/}"
[[ "$path" == ontology ]] && path=index.html
if (( calls <= STUB_UNSETTLED_CALLS )); then
  if [[ "$STUB_UNSETTLED_MODE" == missing ]]; then
    echo "curl: (22) The requested URL returned error: 404" >&2
    exit 22
  fi
  printf 'placeholder\n' > "$output"
  exit 0
fi
cp "$CONSOLE_PREBUILT_DIRECTORY/$path" "$output"
"""


def _run_publisher(tmp_path: Path, *, unsettled_calls: int, mode: str) -> tuple[int, str, Path]:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in {
        "curl": _CURL_STUB,
        "az": '#!/usr/bin/env bash\nprintf "%s\\n" "$CONSOLE_DEFAULT_HOSTNAME"\n',
        "terraform": "#!/usr/bin/env bash\nexit 1\n",
        "sleep": '#!/usr/bin/env bash\necho "$1" >> "$STUB_STATE/sleeps"\n',
    }.items():
        stub = stubs / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o700)
    console = tmp_path / "console"
    (console / "assets").mkdir(parents=True)
    (console / "index.html").write_text(
        '<script type="module" src="/assets/index-abc123.js"></script>\n', encoding="utf-8"
    )
    (console / "fdai-config.js").write_text(
        'globalThis.__FDAI_CONSOLE_CONFIG__ = {"schema_version":"fdai.console-runtime.v1"};\n',
        encoding="utf-8",
    )
    (console / "assets/index-abc123.js").write_text("console.log('ready');\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    environment = {
        **os.environ,
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "EXPECTED_AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000002",
        "ENTRA_CONSOLE_SPA_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
        "ENTRA_CONSOLE_API_SCOPE": "api://00000000-0000-0000-0000-000000000004/access",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "CONSOLE_DEFAULT_HOSTNAME": HOSTNAME,
        "CONSOLE_STATIC_WEB_APP_ID": (
            "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example"
            "/providers/Microsoft.Web/staticSites/stapp-example"
        ),
        "BROWSER_GATEWAY_OPERATOR_URL": "https://apim-example.azure-api.net",
        "BROWSER_GATEWAY_INGESTION_URL": "https://apim-example.azure-api.net/ingestion",
        "CONSOLE_PREBUILT_DIRECTORY": str(console),
        "FDAI_CONSOLE_VERIFY_ONLY": "1",
        "FDAI_CONSOLE_VERIFY_SERVICE_CONTRACTS": "0",
        "STUB_STATE": str(state),
        "STUB_UNSETTLED_CALLS": str(unsettled_calls),
        "STUB_UNSETTLED_MODE": mode,
    }
    environment.pop("ARM_SUBSCRIPTION_ID", None)
    completed = subprocess.run(  # noqa: S603 - fixed repository script, stubbed transport
        ["/bin/bash", str(PUBLISHER), str(tmp_path / "workloads")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return completed.returncode, completed.stderr, state


@pytest.mark.parametrize("mode", ["placeholder", "missing"])
def test_static_readback_waits_for_published_content_to_converge(tmp_path: Path, mode: str) -> None:
    returncode, stderr, state = _run_publisher(tmp_path, unsettled_calls=3, mode=mode)

    assert returncode == 0, stderr
    assert (state / "sleeps").read_text(encoding="utf-8").split() == ["5", "5", "5"]
    assert int((state / "curl-calls").read_text(encoding="utf-8")) == 7


def test_static_readback_fails_closed_after_its_bounded_attempts(tmp_path: Path) -> None:
    returncode, stderr, state = _run_publisher(tmp_path, unsettled_calls=1000, mode="placeholder")

    assert returncode == 1
    assert stderr.splitlines()[-1] == NOT_CONVERGED
    assert int((state / "curl-calls").read_text(encoding="utf-8")) == 60
    assert len((state / "sleeps").read_text(encoding="utf-8").split()) == 59


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        pytest.param(f"curl: (22) error: 404\n{NOT_CONVERGED}\n", NOT_CONVERGED, id="fixed"),
        pytest.param(
            "Operator API browser authorization preflight failed\n",
            "Operator API browser authorization preflight failed",
            id="fixed-api",
        ),
        pytest.param(
            "curl: (6) Could not resolve host: apim-example.azure-api.net\n",
            None,
            id="variable-host-diagnostic",
        ),
        pytest.param(
            "browser_gateway_operator_url is not a valid HTTPS base URL\n",
            None,
            id="variable-gateway-diagnostic",
        ),
        pytest.param("", None, id="empty"),
    ],
)
def test_publisher_failure_reason_surfaces_only_literal_reasons(
    stderr: str, expected: str | None
) -> None:
    assert _publisher_failure_reason(PUBLISHER, stderr) == expected
