"""Serve one execution bundle over a source-bound ephemeral TLS relay."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import ssl
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol, cast

MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_RECEIVER_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 16 * 1024


class _ByteWriter(Protocol):
    def write(self, value: bytes) -> object: ...


@dataclass(slots=True)
class _HeldFile:
    descriptor: int
    size: int
    digest: str
    inode: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def open(cls, path: Path, *, expected_digest: str, maximum: int) -> _HeldFile:
        details = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or not 0 < details.st_size <= maximum
        ):
            raise ValueError("private relay input is invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        digest = hashlib.sha256()
        try:
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            opened = os.fstat(descriptor)
            if (
                opened.st_ino != details.st_ino
                or opened.st_size != details.st_size
                or opened.st_mtime_ns != details.st_mtime_ns
                or opened.st_ctime_ns != details.st_ctime_ns
                or digest.hexdigest() != expected_digest
            ):
                raise ValueError("private relay input differs from its digest")
            return cls(
                descriptor=descriptor,
                size=opened.st_size,
                digest=expected_digest,
                inode=opened.st_ino,
                modified_ns=opened.st_mtime_ns,
                changed_ns=opened.st_ctime_ns,
            )
        except BaseException:
            os.close(descriptor)
            raise

    def write_to(self, output: _ByteWriter) -> None:
        before = os.fstat(self.descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_ino != self.inode
            or before.st_size != self.size
            or before.st_mtime_ns != self.modified_ns
            or before.st_ctime_ns != self.changed_ns
        ):
            raise ValueError("private relay input metadata changed")
        digest = hashlib.sha256()
        offset = 0
        while offset < self.size:
            chunk = os.pread(self.descriptor, min(1024 * 1024, self.size - offset), offset)
            if not chunk:
                raise ValueError("private relay input became incomplete")
            output.write(chunk)
            digest.update(chunk)
            offset += len(chunk)
        after = os.fstat(self.descriptor)
        if (
            digest.hexdigest() != self.digest
            or after.st_ino != self.inode
            or stat.S_IMODE(after.st_mode) != 0o600
            or after.st_uid != os.geteuid()
            or after.st_nlink != 1
            or after.st_size != self.size
            or after.st_mtime_ns != self.modified_ns
            or after.st_ctime_ns != self.changed_ns
        ):
            raise ValueError("private relay input changed while being served")

    def close(self) -> None:
        os.close(self.descriptor)


@dataclass(slots=True)
class _RelayState:
    operation_id: str
    allowed_source: str
    certificate: bytes
    receiver: _HeldFile
    bundle: _HeldFile
    lock: threading.Lock
    claimed: set[str]
    fetched: set[str]
    result_claimed: bool = False
    result: bytes | None = None


class _RelayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], state: _RelayState) -> None:
        self.state = state
        self.failure: BaseException | None = None
        super().__init__(address, _RelayHandler, bind_and_activate=False)

    def handle_error(self, _request: object, _client_address: object) -> None:
        self.failure = RuntimeError("private relay request failed")


class _RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        state = cast(_RelayServer, self.server).state
        if not self._source_allowed(state):
            self.send_error(403)
            return
        prefix = f"/{state.operation_id}/"
        name = self.path.removeprefix(prefix) if self.path.startswith(prefix) else ""
        if name not in {"certificate.pem", "receiver.pyz", "bundle.tar.gz"}:
            self.send_error(404)
            return
        with state.lock:
            if name in state.claimed:
                self.send_error(409)
                return
            state.claimed.add(name)
        if name == "certificate.pem":
            self._send_bytes(state.certificate, "application/x-pem-file")
        else:
            held = state.receiver if name == "receiver.pyz" else state.bundle
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(held.size))
            self.end_headers()
            held.write_to(self.wfile)
            self.wfile.flush()
        with state.lock:
            state.fetched.add(name)

    def do_PUT(self) -> None:  # noqa: N802
        state = cast(_RelayServer, self.server).state
        if not self._source_allowed(state):
            self.send_error(403)
            return
        if self.path != f"/{state.operation_id}/host-result.json":
            self.send_error(409)
            return
        with state.lock:
            if state.result_claimed:
                self.send_error(409)
                return
            state.result_claimed = True
        if self.headers.get("Transfer-Encoding") is not None:
            self.send_error(400)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < length <= MAX_RESULT_BYTES:
            self.send_error(413)
            return
        content = self.rfile.read(length)
        if len(content) != length:
            self.send_error(400)
            return
        with state.lock:
            state.result = content
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _source_allowed(self, state: _RelayState) -> bool:
        return self.client_address[0] == state.allowed_source

    def _send_bytes(self, content: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        self.wfile.flush()


class PrivateRelay:
    """Hold exact files and expose them only during one bounded invocation."""

    def __init__(
        self,
        *,
        relay_host: str,
        relay_port: int,
        allowed_source: str,
        operation_id: str,
        bundle: Path,
        bundle_digest: str,
        receiver: Path,
        receiver_digest: str,
        require_bundle: bool = True,
    ) -> None:
        self._bundle = _HeldFile.open(
            bundle, expected_digest=bundle_digest, maximum=MAX_BUNDLE_BYTES
        )
        try:
            self._receiver = _HeldFile.open(
                receiver,
                expected_digest=receiver_digest,
                maximum=MAX_RECEIVER_BYTES,
            )
        except BaseException:
            self._bundle.close()
            raise
        try:
            self._certificate_fd, self._key_fd, certificate = _certificate(relay_host)
        except BaseException:
            self._receiver.close()
            self._bundle.close()
            raise
        self.certificate_digest = hashlib.sha256(certificate).hexdigest()
        state = _RelayState(
            operation_id=operation_id,
            allowed_source=allowed_source,
            certificate=certificate,
            receiver=self._receiver,
            bundle=self._bundle,
            lock=threading.Lock(),
            claimed=set(),
            fetched=set(),
        )
        self._server = _RelayServer((relay_host, relay_port), state)
        self._required_downloads = {"certificate.pem", "receiver.pyz"}
        if require_bundle:
            self._required_downloads.add("bundle.tar.gz")
        self.port = relay_port
        self._thread: threading.Thread | None = None
        self._closed = False
        try:
            self._server.server_bind()
            self.port = int(self._server.server_address[1])
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(
                certfile=f"/proc/self/fd/{self._certificate_fd}",
                keyfile=f"/proc/self/fd/{self._key_fd}",
            )
            self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        except BaseException:
            self.close()
            raise

    def start(self) -> None:
        if self._thread is not None or self._closed:
            raise ValueError("private relay lifecycle is invalid")
        self._server.server_activate()
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()

    def result(self) -> bytes:
        state = self._server.state
        if self._server.failure is not None:
            raise ValueError("private relay request failed") from self._server.failure
        with state.lock:
            if state.fetched != self._required_downloads:
                raise ValueError("private relay downloads are incomplete")
            if state.result is None:
                raise ValueError("private relay host result is missing")
            return state.result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        stopped = True
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
            stopped = not self._thread.is_alive()
        self._server.server_close()
        self._receiver.close()
        self._bundle.close()
        os.close(self._certificate_fd)
        os.close(self._key_fd)
        if not stopped:
            raise ValueError("private relay did not stop")


def _certificate(host: str) -> tuple[int, int, bytes]:
    address = ipaddress.ip_address(host)
    if address.version != 4:
        raise ValueError("private relay host must be IPv4")
    certificate_fd = _anonymous_file("fdai-relay-certificate")
    key_fd = _anonymous_file("fdai-relay-key")
    os.fchmod(certificate_fd, 0o600)
    os.fchmod(key_fd, 0o600)
    try:
        completed = subprocess.run(
            (
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-sha256",
                "-days",
                "1",
                "-subj",
                f"/CN={host}",
                "-addext",
                f"subjectAltName=IP:{host}",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-keyout",
                f"/proc/self/fd/{key_fd}",
                "-out",
                f"/proc/self/fd/{certificate_fd}",
            ),
            check=True,
            capture_output=True,
            timeout=30,
            pass_fds=(certificate_fd, key_fd),
        )
        if completed.stdout:
            raise ValueError("private relay certificate command returned output")
        os.lseek(certificate_fd, 0, os.SEEK_SET)
        certificate = os.read(certificate_fd, 64 * 1024)
        if not certificate.startswith(b"-----BEGIN CERTIFICATE-----"):
            raise ValueError("private relay certificate is invalid")
        return certificate_fd, key_fd, certificate
    except (OSError, subprocess.SubprocessError) as exc:
        os.close(certificate_fd)
        os.close(key_fd)
        raise ValueError("private relay certificate generation failed") from exc
    except BaseException:
        os.close(certificate_fd)
        os.close(key_fd)
        raise


def _anonymous_file(name: str) -> int:
    """Create one non-inheritable anonymous file descriptor.

    Some portable CPython builds omit ``memfd_create`` even on Linux. The fallback creates
    one mode-0600 file with ``O_EXCL`` semantics and unlinks it before returning, so
    certificate and key bytes never remain addressable by a filesystem path.
    """

    memfd_create = getattr(os, "memfd_create", None)
    if memfd_create is not None:
        return int(memfd_create(name, flags=getattr(os, "MFD_CLOEXEC", 0)))
    descriptor, path = tempfile.mkstemp(prefix=f"{name}-")
    try:
        os.unlink(path)
        os.set_inheritable(descriptor, False)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
