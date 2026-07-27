import json
import pytest
from unittest.mock import AsyncMock, patch

from x402_validator.mcp_server import MCPValidatorServer
from x402_validator._engine import (
    AuditReport,
    ManifestResult,
    Caip2Result,
    JsonResilienceResult,
    BazaarResult,
)
from datetime import datetime, timezone


def make_report(url: str) -> AuditReport:
    return AuditReport(
        target_url=url,
        timestamp=datetime.now(timezone.utc),
        overall_status="PASS",
        checks=[
            ManifestResult(status="PASS", message="ok"),
            Caip2Result(status="PASS", message="ok"),
            JsonResilienceResult(status="PASS", message="ok"),
            BazaarResult(status="PASS", message="ok"),
        ],
        summary=f"4/4 checks passed. Overall: PASS",
    )


@pytest.fixture
def server() -> MCPValidatorServer:
    return MCPValidatorServer()


@pytest.mark.asyncio
async def test_tools_list(server: MCPValidatorServer) -> None:
    response = await server.handle_message({"id": 1, "method": "tools/list"})
    assert response["id"] == 1
    assert "result" in response
    assert len(response["result"]["tools"]) == 1
    assert response["result"]["tools"][0]["name"] == "validate_endpoint"


@pytest.mark.asyncio
async def test_tools_call_succeeds(server: MCPValidatorServer) -> None:
    with patch(
        "x402_validator.mcp_server.run_validation",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = {
            "endpoint": "https://example.com",
            "overall_status": "PASS",
            "summary": "4/4 checks passed. Overall: PASS",
            "checks": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response = await server.handle_message(
            {
                "id": 2,
                "method": "tools/call",
                "params": {"name": "validate_endpoint", "arguments": {"url": "https://example.com"}},
            }
        )
    assert response["id"] == 2
    assert "result" in response
    assert response["result"]["overall_status"] == "PASS"


@pytest.mark.asyncio
async def test_tools_call_unknown_tool(server: MCPValidatorServer) -> None:
    response = await server.handle_message(
        {
            "id": 3,
            "method": "tools/call",
            "params": {"name": "unknown", "arguments": {}},
        }
    )
    assert "error" in response
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_tools_call_missing_url(server: MCPValidatorServer) -> None:
    response = await server.handle_message(
        {
            "id": 4,
            "method": "tools/call",
            "params": {"name": "validate_endpoint", "arguments": {}},
        }
    )
    assert "error" in response
    assert response["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_unknown_method(server: MCPValidatorServer) -> None:
    response = await server.handle_message({"id": 5, "method": "foo/bar"})
    assert "error" in response
    assert response["error"]["code"] == -32601
