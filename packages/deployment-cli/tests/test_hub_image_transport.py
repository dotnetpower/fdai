"""Bound the public distribution transport independently of catalog verification."""

from __future__ import annotations

from email.message import Message

import pytest

from fdai_deployment_cli import hub_image_deploy


@pytest.mark.parametrize("status", [200, 301, 302, 307, 308, 401, 503])
def test_transport_never_redirects_retries_or_sends_credentials(monkeypatch, status):
    calls = []

    class Response:
        headers = Message()

        def __init__(self):
            self.status = status
            self.sent = False

        def getheader(self, name, default=None):
            return {"Content-Length": "2"}.get(name, default)

        def read1(self, count):
            assert count <= 65_536
            if self.sent:
                return b""
            self.sent = True
            return b"{}"

    class Connection:
        sock = None

        def __init__(self, host, port, *, timeout, context):
            calls.append(("connect", host, port, timeout))
            assert context.check_hostname

        def request(self, method, path, *, body, headers):
            calls.append(("request", method, path))
            assert body is None
            assert set(headers) == {"Accept", "Connection"}

        def getresponse(self):
            return Response()

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(hub_image_deploy.http.client, "HTTPSConnection", Connection)
    if status == 200:
        result = hub_image_deploy.hub_request("https://hub.example.com", "/v1/catalog/export")
        assert result[0] == 200
        assert result[2] == b"{}"
    else:
        with pytest.raises(ValueError, match="refused"):
            hub_image_deploy.hub_request("https://hub.example.com", "/v1/catalog/export")
    assert len([call for call in calls if call[0] == "request"]) == 1
    assert calls[-1] == ("close",)


@pytest.mark.parametrize("failure", ["size", "encoding", "duplicate-signature", "incomplete"])
def test_transport_rejects_unbounded_or_ambiguous_bodies(monkeypatch, failure):
    class Response:
        status = 200

        def __init__(self):
            self.headers = Message()
            self.sent = False
            if failure == "duplicate-signature":
                self.headers.add_header("X-FDAI-Export-Signature", "one")
                self.headers.add_header("X-FDAI-Export-Signature", "two")

        def getheader(self, name, default=None):
            values = {
                "Content-Length": str(hub_image_deploy.MAX_EXPORT_BYTES + 1)
                if failure == "size"
                else "3"
                if failure == "incomplete"
                else "2",
                "Content-Encoding": "gzip" if failure == "encoding" else "identity",
            }
            return values.get(name, default)

        def read1(self, count):
            if self.sent:
                return b""
            self.sent = True
            return b"{}"

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(hub_image_deploy.http.client, "HTTPSConnection", Connection)
    with pytest.raises(ValueError):
        hub_image_deploy.hub_request("https://hub.example.com", "/v1/catalog/export")


@pytest.mark.parametrize("mode", ["--source", "--offline-kit"])
def test_hub_work_directory_cannot_drift_to_another_artifact_mode(
    monkeypatch, tmp_path, capsys, mode
):
    from fdai_deployment_cli import cli

    work = tmp_path / "run"
    (work / "hub-images").mkdir(parents=True)
    monkeypatch.setattr(
        cli, "ensure_azure_session", lambda: pytest.fail("mode drift reached Azure")
    )
    assert (
        cli.main(
            [
                "provision",
                "azure",
                mode,
                "." if mode == "--source" else "kit.tar.gz",
                "--work-dir",
                str(work),
            ]
        )
        == 3
    )
    assert "artifact mode cannot reuse a Hub-image work directory" in capsys.readouterr().err
