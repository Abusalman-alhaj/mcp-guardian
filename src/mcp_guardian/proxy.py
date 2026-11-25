"""
Minimal newline-delimited JSON-RPC stdio proxy.

MCP stdio messages are JSON-RPC messages terminated by newlines. This proxy
forwards normal traffic and pauses tools/call requests until the desktop UI
resolves the matching request ID. It intentionally does not inspect or rewrite
tool arguments beyond displaying them to the user.
"""
import asyncio
import json
import os
import sys
import uuid
from typing import Any

from .audit import AuditLog
from .models import PendingRequest

class MCPProxy:
    def __init__(self, config: dict, signals):
        self.config = config
        self.signals = signals
        self.pending: dict[str, asyncio.Future] = {}
        self.pending_lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()
        self.upstream_write_lock = asyncio.Lock()
        self.client_tasks: set[asyncio.Task] = set()
        self.process = None
        self.audit = AuditLog(config.get("audit_file", "guardian-audit.jsonl"))
        self.timeout = float(config.get("approval_timeout_seconds", 120))
        self.server_name = config.get("server", {}).get("name", "Configured MCP server")

    async def _write_client(self, message: dict):
        raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
        async with self.write_lock:
            sys.stdout.write(raw)
            sys.stdout.flush()

    async def _write_upstream(self, message: dict):
        if not self.process or not self.process.stdin:
            raise RuntimeError("Upstream MCP server is not running")
        raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
        async with self.upstream_write_lock:
            self.process.stdin.write(raw.encode("utf-8"))
            await self.process.stdin.drain()

    async def _read_stdin(self):
        # Blocking stdin read is isolated from the asyncio event loop.
        return await asyncio.to_thread(sys.stdin.buffer.readline)

    async def _approval(self, message: dict) -> bool:
        request_id = str(message.get("id", uuid.uuid4().hex))
        params = message.get("params") or {}
        tool_name = str(params.get("name", "unknown"))
        arguments = params.get("arguments", {})
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        async with self.pending_lock:
            self.pending[request_id] = future

        preview = json.dumps(arguments, indent=2, ensure_ascii=False, default=str)
        if len(preview) > 12000:
            preview = preview[:12000] + "\n… [truncated in approval window]"
        pending = PendingRequest(
            request_id=request_id,
            server_name=self.server_name,
            tool_name=tool_name,
            arguments=arguments,
            preview=preview,
        )
        self.audit.write("pending", request_id, tool_name, arguments)
        self.signals.request_pending.emit(pending)

        try:
            approved = await asyncio.wait_for(future, timeout=self.timeout)
            self.audit.write("allowed" if approved else "blocked", request_id, tool_name)
            return bool(approved)
        except asyncio.TimeoutError:
            self.audit.write("timeout_blocked", request_id, tool_name)
            return False
        finally:
            async with self.pending_lock:
                self.pending.pop(request_id, None)

    async def decide(self, request_id: str, allow: bool):
        async with self.pending_lock:
            future = self.pending.get(str(request_id))
            if future and not future.done():
                future.set_result(bool(allow))

    async def _upstream_reader(self):
        assert self.process and self.process.stdout
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8"))
                await self._write_client(message)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Upstream stdout must contain protocol messages only. Do not
                # leak malformed output into the MCP client's protocol stream.
                print("Ignoring malformed upstream stdout line", file=sys.stderr)

    async def _handle_client_message(self, message: dict):
        is_tool_call = (
            message.get("method") == "tools/call"
            and "id" in message
            and self.config.get("approval_required", True)
        )
        if is_tool_call:
            try:
                allowed = await self._approval(message)
            except Exception as exc:
                print(f"Approval engine error: {exc}", file=sys.stderr)
                allowed = False
            if not allowed:
                await self._write_client({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {
                        "code": -32001,
                        "message": "Request blocked by MCP Guardian user policy"
                    }
                })
                return
        try:
            await self._write_upstream(message)
        except Exception as exc:
            if "id" in message:
                await self._write_client({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32000, "message": f"Upstream unavailable: {exc}"}
                })

    async def run(self):
        server = self.config["server"]
        command = server["command"]
        args = server.get("args", [])
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in server.get("env", {}).items()})
        try:
            self.process = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,
                env=env,
            )
        except Exception as exc:
            await self._write_client({
                "jsonrpc": "2.0", "id": "mcp-guardian-startup",
                "error": {"code": -32000, "message": f"Could not start MCP server: {exc}"}
            })
            raise

        reader_task = asyncio.create_task(self._upstream_reader())
        try:
            while True:
                line = await self._read_stdin()
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    print("Ignoring malformed client message", file=sys.stderr)
                    continue

                # Dispatch each message independently so multiple tool calls can
                # wait for user decisions concurrently.
                task = asyncio.create_task(self._handle_client_message(message))
                self.client_tasks.add(task)
                task.add_done_callback(self.client_tasks.discard)

        finally:
            if self.client_tasks:
                await asyncio.gather(*self.client_tasks, return_exceptions=True)
            # Resolve outstanding decisions as denied during shutdown.
            async with self.pending_lock:
                for future in self.pending.values():
                    if not future.done():
                        future.set_result(False)
            if self.process and self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
