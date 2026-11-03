"""Cross-version Zstandard runtime binding (Python 3.14 ``compression.zstd`` + ``libzstd`` shim).

Uses PEP 784 ``compression.zstd`` on Python 3.14+ and falls back transparently to
the system ``libzstd.so.1`` shared library via ``ctypes`` on Python 3.12 and 3.13
so CI and local environments share identical RFC 8878 frame and dictionary behavior
without external PyPI dependencies.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from collections.abc import Sequence
from typing import Any


class _CtypesInBuffer(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class _CtypesOutBuffer(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class CtypesZstdError(Exception):
    """Raised when ``libzstd`` reports a compression, decompression, or dictionary error."""


def _load_libzstd() -> ctypes.CDLL:
    lib_name = ctypes.util.find_library("zstd") or "libzstd.so.1"
    lib = ctypes.CDLL(lib_name)
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
    lib.ZSTD_getErrorName.restype = ctypes.c_char_p
    lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    lib.ZSTD_compressBound.restype = ctypes.c_size_t
    lib.ZSTD_compress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    lib.ZSTD_createCCtx.argtypes = []
    lib.ZSTD_createCCtx.restype = ctypes.c_void_p
    lib.ZSTD_freeCCtx.argtypes = [ctypes.c_void_p]
    lib.ZSTD_freeCCtx.restype = ctypes.c_size_t
    lib.ZSTD_compress_usingDict.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    lib.ZSTD_compress_usingDict.restype = ctypes.c_size_t
    lib.ZSTD_createDCtx.argtypes = []
    lib.ZSTD_createDCtx.restype = ctypes.c_void_p
    lib.ZSTD_freeDCtx.argtypes = [ctypes.c_void_p]
    lib.ZSTD_freeDCtx.restype = ctypes.c_size_t
    lib.ZSTD_DCtx_loadDictionary.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    lib.ZSTD_DCtx_loadDictionary.restype = ctypes.c_size_t
    lib.ZSTD_decompressStream.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_CtypesOutBuffer),
        ctypes.POINTER(_CtypesInBuffer),
    ]
    lib.ZSTD_decompressStream.restype = ctypes.c_size_t
    lib.ZDICT_trainFromBuffer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_uint,
    ]
    lib.ZDICT_trainFromBuffer.restype = ctypes.c_size_t
    lib.ZDICT_isError.argtypes = [ctypes.c_size_t]
    lib.ZDICT_isError.restype = ctypes.c_uint
    lib.ZDICT_getDictID.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    lib.ZDICT_getDictID.restype = ctypes.c_uint
    return lib


_LIBZSTD: ctypes.CDLL | None = None


def _get_libzstd() -> ctypes.CDLL:
    global _LIBZSTD
    if _LIBZSTD is None:
        _LIBZSTD = _load_libzstd()
    return _LIBZSTD


def _err_msg(lib: ctypes.CDLL, code: int) -> str:
    raw_name = lib.ZSTD_getErrorName(code)
    return raw_name.decode("utf-8", errors="replace") if raw_name else f"zstd error {code}"


class CtypesZstdDict:
    """PEP 784-compatible ``ZstdDict`` wrapper backed by ``libzstd``."""

    def __init__(self, dict_content: bytes, *, is_raw: bool = False) -> None:
        del is_raw
        if not isinstance(dict_content, (bytes, bytearray)) or not dict_content:
            raise CtypesZstdError("dictionary content MUST be non-empty bytes")
        self._content = bytes(dict_content)
        lib = _get_libzstd()
        self._dict_id = int(lib.ZDICT_getDictID(self._content, len(self._content)))

    @property
    def dict_content(self) -> bytes:
        return self._content

    @property
    def dict_id(self) -> int:
        return self._dict_id


class CtypesZstdDecompressor:
    """PEP 784-compatible streaming single-frame ``ZstdDecompressor`` backed by ``libzstd``."""

    def __init__(self, zstd_dict: Any | None = None) -> None:
        self._dict_bytes = bytes(zstd_dict.dict_content) if zstd_dict is not None else None
        self.eof = False
        self.needs_input = True
        self.unused_data = b""

    def decompress(self, data: bytes, max_length: int = -1) -> bytes:
        if self.eof:
            raise EOFError("End of stream already reached")
        if not data:
            self.needs_input = True
            return b""
        lib = _get_libzstd()
        dctx = lib.ZSTD_createDCtx()
        if not dctx:
            raise CtypesZstdError("failed to allocate ZSTD_DCtx")
        try:
            if self._dict_bytes is not None:
                rc = int(
                    lib.ZSTD_DCtx_loadDictionary(dctx, self._dict_bytes, len(self._dict_bytes))
                )
                if lib.ZSTD_isError(rc):
                    raise CtypesZstdError(_err_msg(lib, rc))
            in_mem = ctypes.create_string_buffer(data, len(data))
            in_buf = _CtypesInBuffer(ctypes.cast(in_mem, ctypes.c_void_p), len(data), 0)
            limit = max_length if max_length >= 0 else 64 * 1024 * 1024
            chunk_cap = min(max(limit, 1), 65536)
            out_mem = ctypes.create_string_buffer(chunk_cap)
            chunks: list[bytes] = []
            total = 0
            ret = 1
            while total < limit:
                step = min(chunk_cap, limit - total)
                out_buf = _CtypesOutBuffer(ctypes.cast(out_mem, ctypes.c_void_p), step, 0)
                ret = int(
                    lib.ZSTD_decompressStream(dctx, ctypes.byref(out_buf), ctypes.byref(in_buf))
                )
                if lib.ZSTD_isError(ret):
                    raise CtypesZstdError(_err_msg(lib, ret))
                if out_buf.pos > 0:
                    chunks.append(out_mem.raw[: out_buf.pos])
                    total += int(out_buf.pos)
                if ret == 0 or (in_buf.pos == in_buf.size and out_buf.pos == 0):
                    break
            self.eof = ret == 0
            self.needs_input = not self.eof and int(in_buf.pos) >= int(in_buf.size)
            self.unused_data = data[int(in_buf.pos) :] if self.eof else b""
            return b"".join(chunks)
        finally:
            lib.ZSTD_freeDCtx(dctx)


def ctypes_compress(data: bytes, level: int = 3, zstd_dict: Any | None = None) -> bytes:
    """PEP 784-compatible ``zstd.compress`` backed by ``libzstd``."""
    lib = _get_libzstd()
    raw = bytes(data)
    bound = int(lib.ZSTD_compressBound(len(raw)))
    out_buf = ctypes.create_string_buffer(bound)
    if zstd_dict is not None:
        dict_bytes = bytes(zstd_dict.dict_content)
        cctx = lib.ZSTD_createCCtx()
        if not cctx:
            raise CtypesZstdError("failed to allocate ZSTD_CCtx")
        try:
            written = int(
                lib.ZSTD_compress_usingDict(
                    cctx,
                    out_buf,
                    bound,
                    raw,
                    len(raw),
                    dict_bytes,
                    len(dict_bytes),
                    level,
                )
            )
        finally:
            lib.ZSTD_freeCCtx(cctx)
    else:
        written = int(lib.ZSTD_compress(out_buf, bound, raw, len(raw), level))
    if lib.ZSTD_isError(written):
        raise CtypesZstdError(_err_msg(lib, written))
    return out_buf.raw[:written]


def ctypes_train_dict(samples: Sequence[bytes], dict_size: int) -> CtypesZstdDict:
    """PEP 784-compatible ``zstd.train_dict`` backed by ``ZDICT_trainFromBuffer``."""
    lib = _get_libzstd()
    concat = b"".join(samples)
    sizes = (ctypes.c_size_t * len(samples))(*(len(s) for s in samples))
    dict_buf = ctypes.create_string_buffer(dict_size)
    written = int(lib.ZDICT_trainFromBuffer(dict_buf, dict_size, concat, sizes, len(samples)))
    if lib.ZDICT_isError(written):
        raise CtypesZstdError(_err_msg(lib, written))
    return CtypesZstdDict(dict_buf.raw[:written])


class _CtypesZstdModule:
    ZstdError = CtypesZstdError
    ZstdDict = CtypesZstdDict
    ZstdDecompressor = CtypesZstdDecompressor
    compress = staticmethod(ctypes_compress)
    train_dict = staticmethod(ctypes_train_dict)


try:
    from compression import zstd as _stdlib_zstd  # type: ignore[import-not-found]

    zstd_runtime: Any = _stdlib_zstd
except ImportError:
    zstd_runtime = _CtypesZstdModule()

__all__ = [
    "CtypesZstdDecompressor",
    "CtypesZstdDict",
    "CtypesZstdError",
    "ctypes_compress",
    "ctypes_train_dict",
    "zstd_runtime",
]
