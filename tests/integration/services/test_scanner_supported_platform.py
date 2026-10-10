from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = _ROOT / "services/core-control-plane/docker/code-security-scanner.Dockerfile"


def _stage(content: str, name: str) -> str:
    return content.split(f" AS {name}\n", 1)[1].split("\nFROM ", 1)[0]


def test_scanner_uses_authenticated_same_python_on_supported_platform() -> None:
    content = _DOCKERFILE.read_text()
    assert (
        "mcr.microsoft.com/azurelinux/base/core@sha256:"
        "a66ca12ae8c8c464e00cc6cc7f9deff5d2dfcd0f1314ba5dac22034ef171d3ae"
    ) in content
    assert "tdnf install -y ca-certificates" in _stage(content, "platform")
    assert "--insecure" not in content and "curl -k" not in content
    python = _stage(content, "python-builder")
    assert "ARG PYTHON_VERSION=3.13.16" in python
    assert (
        "ARG PYTHON_SHA256=f4b1bfb3c79b5bb11b8d228a12504163b4c0dab4d679828d8f5f26b6cb6ab35d"
        in python
    )
    assert '"${PYTHON_SHA256}  Python.tar.xz" | sha256sum -c -' in python
    assert "--enable-shared" in python and "--with-system-expat" in python
    assert "--with-ensurepip=no" in python
    assert "make -j4" in python and "COMPILEALL_OPTS=-j4" in python
    runtime = _stage(content, "python-runtime")
    assert "/usr/lib/libpython3.13.so.1.0" in runtime
    assert "--inhibit-cache" in runtime
    assert 'assert importlib.util.find_spec("pip") is None' in runtime
    assert "glibc-devel" not in runtime and "kernel-headers" not in runtime
    assert " gcc " not in runtime and "dotnet" not in runtime


def test_application_is_rebuilt_from_frozen_current_source_not_old_image() -> None:
    content = _DOCKERFILE.read_text()
    builder = _stage(content, "builder")
    assert "COPY services/core-control-plane/ ./services/core-control-plane/" in builder
    assert "uv sync --frozen --package fdai-core-control-plane" in builder
    assert "--build-constraints /build/build-constraints.txt --require-hashes" in builder
    assert "UV_HTTP_RETRIES=0" in builder
    assert "UV_CONCURRENT_BUILDS=4" in builder
    assert "UV_COMPILE_BYTECODE=0" in builder
    assert "compileall -q -j4" in builder
    assert "FROM fdai-code-security-scanner:" not in content
    assert "COPY --from=portable" not in content
    full = _stage(content, "prover")
    assert "gcc gcc-c++ binutils glibc-devel kernel-headers icu" in full
    assert "/usr/lib/jvm/msopenjdk-21/" in full
    assert "/usr/lib/dotnet/" in full
    assert "msopenjdk-21-21.0.12.1-1" in full
    assert "sha256sum -c /tmp/jdk-content.sha256" in full
    assert "COPY --from=jdk /usr/lib/jvm/" not in full
