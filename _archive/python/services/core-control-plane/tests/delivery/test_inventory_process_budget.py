"""Enforce memory in a disposable child process, never the test runner or local services."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest


@pytest.mark.parametrize(
    "condition",
    [
        "default",
        "configured",
        "stricter",
        "headroom",
        "bad",
        "negative",
        "small",
        "large",
        "unicode",
        "entrypoint",
    ],
)
async def test_inventory_process_memory_limit_in_fresh_process(condition):
    value = {
        "configured": "256",
        "stricter": "512",
        "headroom": "256",
        "bad": "invalid",
        "negative": "-1",
        "small": "255",
        "large": "4097",
        "unicode": "２５６",
    }.get(condition, "2048")
    code = """
import os, resource
from fdai.delivery.inventory_process_budget import (
    apply_inventory_memory_limit, run_inventory_process,
)
condition=os.environ['MEMORY_TEST_CONDITION']
if condition == 'stricter':
    resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,resource.RLIM_INFINITY))
if condition == 'headroom':
    resource.setrlimit(resource.RLIMIT_AS,(32*1024*1024,resource.RLIM_INFINITY))
if condition in {'bad','negative','small','large','unicode','headroom'}:
    try:
        apply_inventory_memory_limit()
    except (ValueError,RuntimeError):
        print('blocked')
    else:
        raise AssertionError('invalid or unavailable memory accepted')
elif condition == 'entrypoint':
    async def operation():
        assert resource.getrlimit(resource.RLIMIT_AS)==(2048*1024*1024,)*2
    run_inventory_process(operation)
    print('bounded')
else:
    limit=apply_inventory_memory_limit()
    assert resource.getrlimit(resource.RLIMIT_AS)==(limit,limit)
    assert limit==(256 if condition in {'configured','stricter'} else 2048)*1024*1024
    try:
        bytearray(limit)
    except MemoryError:
        print('bounded')
    else:
        raise AssertionError('address-space ceiling was not enforced')
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        env={
            **os.environ,
            "FDAI_INVENTORY_MEMORY_LIMIT_MIB": value,
            "MEMORY_TEST_CONDITION": condition,
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == 0, stderr.decode()
    assert stdout.decode().strip() in {"bounded", "blocked"}


@pytest.mark.parametrize(
    "entrypoint,arguments", [("main", ["--initial"]), ("container_main", ["once"])]
)
async def test_production_entrypoints_use_memory_guard_before_operation(
    monkeypatch, entrypoint, arguments
):
    from unittest.mock import AsyncMock

    from fdai.delivery import inventory_sync_cli

    guarded = []
    operation = AsyncMock()
    monkeypatch.setattr(inventory_sync_cli, "_main", operation)
    monkeypatch.setattr(inventory_sync_cli, "run_inventory_process", guarded.append)
    monkeypatch.setattr(sys, "argv", ["inventory", *arguments])
    getattr(inventory_sync_cli, entrypoint)()
    operation.assert_not_called()
    await guarded[0]()
    operation.assert_awaited_once_with(arguments if entrypoint == "main" else [])
