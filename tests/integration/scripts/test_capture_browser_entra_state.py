from __future__ import annotations

import http.client
import importlib.util
import json
import stat
import threading
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/automation/capture_browser_entra_state.py"
    spec = importlib.util.spec_from_file_location("capture_browser_entra_state", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_storage_state_uses_session_bootstrap_contract() -> None:
    module = _load_module()

    state = module.build_storage_state(
        {
            "origin": module.DEFAULT_ORIGIN,
            "sessionStorage": [["account", "signed-in"]],
        },
        module.DEFAULT_ORIGIN,
    )

    origin = state["origins"][0]
    bootstrap = origin["localStorage"][0]
    assert origin["origin"] == module.DEFAULT_ORIGIN
    assert bootstrap["name"] == module.BOOTSTRAP_KEY
    assert json.loads(bootstrap["value"]) == [["account", "signed-in"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"origin": "http://example.com", "sessionStorage": []},
        {"origin": "http://localhost:5273", "sessionStorage": [["key"]]},
        {"origin": "http://localhost:5273", "sessionStorage": [["key", 1]]},
    ],
)
def test_build_storage_state_rejects_untrusted_payloads(payload: object) -> None:
    module = _load_module()

    with pytest.raises(module.CaptureContractError):
        module.build_storage_state(payload, module.DEFAULT_ORIGIN)


def test_loopback_receiver_writes_owner_only_state(tmp_path: Path) -> None:
    module = _load_module()
    destination = tmp_path / "browser-entra-storage-state.json"
    server = module.CaptureServer(("127.0.0.1", 0), module.DEFAULT_ORIGIN, destination)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    host, port = server.server_address
    payload = json.dumps(
        {
            "origin": module.DEFAULT_ORIGIN,
            "sessionStorage": [["account", "signed-in"]],
        }
    ).encode()
    connection = http.client.HTTPConnection(host, port)

    try:
        connection.request(
            "POST",
            "/",
            body=payload,
            headers={
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": module.DEFAULT_ORIGIN,
            },
        )
        assert connection.getresponse().status == 204
    finally:
        connection.close()
        thread.join(timeout=5)
        server.server_close()

    assert not thread.is_alive()
    assert server.capture_succeeded is True
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    state = json.loads(destination.read_text(encoding="utf-8"))
    assert state["origins"][0]["origin"] == module.DEFAULT_ORIGIN
