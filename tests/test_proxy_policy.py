import asyncio
import pytest

from mcp_guardian.proxy import MCPProxy

class DummySignals:
    class Signal:
        def emit(self, value):
            pass
    request_pending = Signal()

@pytest.mark.asyncio
async def test_decision_is_correlated_to_request_id(tmp_path):
    proxy = MCPProxy(
        {"audit_file": str(tmp_path / "audit.jsonl"), "approval_timeout_seconds": 2},
        DummySignals(),
    )
    message = {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "tools/call",
        "params": {"name": "hello", "arguments": {"name": "Ada"}},
    }
    task = asyncio.create_task(proxy._approval(message))
    await asyncio.sleep(0.05)
    await proxy.decide("17", True)
    assert await task is True

@pytest.mark.asyncio
async def test_timeout_fails_closed(tmp_path):
    proxy = MCPProxy(
        {"audit_file": str(tmp_path / "audit.jsonl"), "approval_timeout_seconds": 0.01},
        DummySignals(),
    )
    message = {
        "jsonrpc": "2.0",
        "id": "x",
        "method": "tools/call",
        "params": {"name": "dangerous", "arguments": {}},
    }
    assert await proxy._approval(message) is False
