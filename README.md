# MCP Guardian

**A human-in-the-loop approval proxy for MCP tool calls on Windows 11.**

MCP Guardian is a local Python stdio proxy. It launches a configured upstream MCP server, forwards normal JSON-RPC/MCP traffic, and pauses each `tools/call` request until the user chooses **Allow** or **Block** in a native, always-on-top PySide6 window.

> Current scope: the included implementation targets Claude Desktop's **local stdio MCP servers**. It does not transparently intercept arbitrary Claude Web requests. Claude Web requires a separately hosted remote MCP gateway and a secure channel to the local approval agent; that is a future extension, not a capability claimed by this build.

## Features

- Intercepts JSON-RPC requests with method `tools/call`.
- Shows server name, tool name, request ID, and arguments in a Windows desktop approval window.
- Keeps the request pending until a decision is made.
- Forwards approved calls to the upstream MCP server.
- Returns JSON-RPC error `-32001` for blocked calls.
- Fails closed: approval timeout and shutdown resolve as blocked.
- Uses per-request `asyncio.Future` objects, correlated by JSON-RPC request ID.
- Writes an append-only JSONL audit log.
- Runs a system-tray resident Qt application while the MCP client process remains connected.

## Architecture

```text
Claude Desktop
    |
    | MCP stdio (newline-delimited JSON-RPC)
    v
MCP Guardian (Python process)
    |                         |
    | tools/call              +--> PySide6 approval window
    |                         |       Allow / Block
    |                         |
    |<------ decision --------+
    |
    | approved request only
    v
Configured upstream MCP server
```

The proxy is the MCP server process Claude Desktop launches. It starts the real MCP server as a child process and relays protocol messages. Only `tools/call` requests are gated; initialization, tool discovery, notifications, and tool results are relayed. This keeps the proxy transparent for the common stdio request/response flow.

## Requirements

- Windows 11
- Python 3.11 or newer
- Node.js and `npx` if using the example Filesystem MCP server
- Claude Desktop

## Install

Open PowerShell in this repository:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

Copy and edit the configuration:

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

Replace `YOUR_USER` with your Windows username and choose the directory the Filesystem server is permitted to expose. The MCP server's own filesystem restrictions remain an important second security boundary.

## Configure Claude Desktop

Find Claude Desktop's `claude_desktop_config.json` (commonly `%APPDATA%\Claude\claude_desktop_config.json`) and add a server entry. Use the absolute path to the Python executable in this project's virtual environment and the absolute path to `config.json`.

```json
{
  "mcpServers": {
    "guardian-filesystem": {
      "command": "C:\\path\\to\\mcp-guardian\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "mcp_guardian",
        "--config",
        "C:\\path\\to\\mcp-guardian\\config.json"
      ]
    }
  }
}
```

Restart Claude Desktop. When Claude invokes a tool, MCP Guardian should show an approval window. Choose Allow to forward the call, or Block to return a denial error.

**Important:** Keep stdout reserved for MCP protocol messages. This implementation writes diagnostics to stderr. Do not add `print()` debugging to stdout.

## Configuration

`config.example.json`:

- `server.command`: executable to launch.
- `server.args`: arguments passed to the upstream MCP server.
- `server.env`: optional environment variables.
- `server.name`: optional friendly name shown in the popup.
- `approval_timeout_seconds`: how long to wait for a decision.
- `deny_on_timeout`: reserved for explicit policy documentation; current behavior always denies on timeout.
- `show_full_arguments`: reserved; current UI displays the arguments with a size cap.
- `audit_file`: JSONL audit log path.

## Test

```powershell
pip install -e ".[dev]"
pytest -q
```

## Security notes and limitations

1. **Local stdio scope:** This proxy can only govern MCP traffic routed through it. It cannot intercept a different server configuration or a direct connection that bypasses it.
2. **Claude Web:** Claude Web runs remote connectors in Anthropic's infrastructure. A local stdio proxy cannot see those requests. Supporting Web requires a hosted remote MCP gateway and an authenticated, encrypted bridge to the local approval UI.
3. **Transport framing:** The proxy handles newline-delimited JSON-RPC messages used by MCP stdio. It does not implement HTTP/SSE transport.
4. **Multiple requests:** Each approval has a separate future keyed by the JSON-RPC ID. The current desktop window presents one request at a time; a later request can replace the visible request if several arrive concurrently. The approval futures remain independent, but production readiness requires a visible queue and per-item decision controls. Do not treat the current UI as a complete concurrent-request UX.
5. **Audit privacy:** Tool arguments may contain personal or confidential data. Protect the audit file and avoid sharing it publicly.
6. **Fail closed:** Timeouts and proxy shutdown block pending calls. If the upstream process crashes, the client receives an error for calls that cannot be forwarded.
7. **No blanket security guarantee:** This is an interception prototype, not a sandbox. Keep upstream MCP server permissions narrowly scoped.

## Demo recording plan

1. Start Claude Desktop with the Guardian-configured Filesystem server.
2. Ask Claude to list files in the permitted test directory.
3. Show the approval popup and click **Allow**; demonstrate the tool result.
4. Ask Claude to read a test file and click **Block**; demonstrate the denial.
5. Show `guardian-audit.jsonl` with pending/allowed/blocked events.
6. State clearly that this demo covers Claude Desktop local stdio. Explain the remote gateway requirement for Claude Web.

## Project status

This is an initial take-home implementation. Before presenting it as production-ready, complete the concurrency queue, end-to-end integration test against the current MCP SDK/server, robust process supervision, and the remote gateway/agent design if Claude Web compatibility is required.
