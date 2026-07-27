"""x402 MCP server — expose the conformance engine over Model Context Protocol.

The server speaks JSON-RPC 2.0 over stdin/stdout. Currently registered tool:

    validate_endpoint(url: str, strict_mode: bool = False) -> dict

Typical usage from an MCP-aware agent (Claude Desktop, Cursor):

    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | x402-mcp
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from x402_validator._engine import X402Auditor


JSON_RPC_VERSION = "2.0"


def make_response(id: Any, result: Any = None, error: Any = None) -> dict:
    """Build a JSON-RPC response envelope."""
    msg: dict[str, Any] = {"jsonrpc": JSON_RPC_VERSION, "id": id}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def make_error(id: Any, code: int, message: str) -> dict:
    """Build a JSON-RPC error envelope."""
    return make_response(id, error={"code": code, "message": message})


TOOL_DEFINITION: dict[str, Any] = {
    "name": "validate_endpoint",
    "description": "Run a full x402 conformance audit against a URL and return a structured report.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Target URL to audit.",
            },
            "strict_mode": {
                "type": "boolean",
                "description": "Enable strict x402 v2 checks (currently informational only).",
                "default": False,
            },
        },
        "required": ["url"],
    },
}


async def run_validation(url: str, strict_mode: bool = False) -> dict[str, Any]:
    """Execute the conformance suite and return a JSON-friendly summary.

    The ``strict_mode`` argument is accepted for forward-compatibility but the
    underlying engine does not currently branch on it.
    """
    del strict_mode  # reserved for future strict checks
    async with X402Auditor() as auditor:
        report = await auditor.run_full_audit(url)

    checks: dict[str, Any] = {}
    for c in report.checks:
        checks[c.check_name] = {
            "status": c.status,
            "message": c.message,
            "details": c.details,
        }

    return {
        "endpoint": url,
        "overall_status": report.overall_status,
        "summary": report.summary,
        "checks": checks,
        "timestamp": report.timestamp.isoformat(),
    }


class MCPValidatorServer:
    """JSON-RPC 2.0 server over stdio implementing ``x402-mcp``."""

    def __init__(self) -> None:
        self._running = True

    async def handle_message(self, msg: dict) -> dict | None:
        """Dispatch one JSON-RPC message; return the response (``None`` is OK for notifications)."""
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "tools/list":
            return make_response(msg_id, {"tools": [TOOL_DEFINITION]})

        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})

            if name != "validate_endpoint":
                return make_error(msg_id, -32601, f"Unknown tool: {name}")

            url = args.get("url", "")
            if not url:
                return make_error(msg_id, -32602, "Missing required argument: url")

            strict_mode = bool(args.get("strict_mode", False))
            try:
                result = await run_validation(url, strict_mode=strict_mode)
                return make_response(msg_id, result)
            except Exception as e:  # noqa: BLE001 — surfaced to client
                return make_error(msg_id, -32603, f"Validation error: {e}")

        if method == "notifications/initialized":
            return None

        return make_error(msg_id, -32601, f"Unknown method: {method}")

    async def serve_stdio(self) -> None:
        """Read JSON-RPC messages from stdin and write responses to stdout."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        initialize_msg = json.dumps(
            {
                "jsonrpc": JSON_RPC_VERSION,
                "method": "server/initialized",
                "params": {"protocol_version": "0.1.0", "capabilities": {"tools": {}}},
            }
        )
        sys.stdout.write(initialize_msg + "\n")
        sys.stdout.flush()

        while self._running:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
                if not line:
                    break
                raw = line.decode("utf-8").strip()
                if not raw:
                    continue

                msg = json.loads(raw)
                response = await self.handle_message(msg)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except asyncio.TimeoutError:
                continue
            except json.JSONDecodeError:
                continue
            except EOFError:
                break


def main() -> None:
    server = MCPValidatorServer()
    asyncio.run(server.serve_stdio())


if __name__ == "__main__":
    main()
