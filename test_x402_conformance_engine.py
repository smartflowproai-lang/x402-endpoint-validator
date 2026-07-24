import base64
import json
import pytest
import httpx
from datetime import datetime, timezone, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from x402_conformance_engine import (
    X402Auditor,
    AuditReport,
    CheckResult,
    ManifestResult,
    Caip2Result,
    JsonResilienceResult,
    CAIP2_PATTERN,
    run_audit,
    main,
)


class TestCAIP2Pattern:
    def test_valid_eip155_base(self) -> None:
        assert CAIP2_PATTERN.match("eip155:8453")

    def test_valid_eip155_mainnet(self) -> None:
        assert CAIP2_PATTERN.match("eip155:1")

    def test_valid_eip155_goerli(self) -> None:
        assert CAIP2_PATTERN.match("eip155:5")

    def test_valid_solana(self) -> None:
        assert CAIP2_PATTERN.match("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp")

    def test_valid_polkadot(self) -> None:
        assert CAIP2_PATTERN.match("polkadot:91b171bb158e2d3848fa23a9f1c25182")

    def test_invalid_integer_only(self) -> None:
        assert not CAIP2_PATTERN.match("8453")

    def test_invalid_missing_colon(self) -> None:
        assert not CAIP2_PATTERN.match("eip1558453")

    def test_invalid_uppercase_namespace(self) -> None:
        assert not CAIP2_PATTERN.match("EIP155:8453")

    def test_invalid_empty_namespace(self) -> None:
        assert not CAIP2_PATTERN.match(":8453")

    def test_invalid_empty_chain_id(self) -> None:
        assert not CAIP2_PATTERN.match("eip155:")


class MockAsyncClient:
    def __init__(self) -> None:
        self.responses: dict[str, httpx.Response] = {}
        self.requests: list[tuple[str, str]] = []

    def add_response(self, url: str, response: httpx.Response) -> None:
        self.responses[url] = response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append(("GET", url))
        if url in self.responses:
            return self.responses[url]
        return httpx.Response(
            404, 
            text="Not Found", 
            request=httpx.Request("GET", url),
            headers={}
        )

    async def aclose(self) -> None:
        pass

    async def __aenter__(self) -> "MockAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.fixture
def mock_client() -> MockAsyncClient:
    return MockAsyncClient()


@pytest.fixture
def auditor(mock_client: MockAsyncClient) -> X402Auditor:
    auditor = X402Auditor()
    auditor._client = mock_client
    return auditor


class TestManifestDiscovery:
    @pytest.mark.asyncio
    async def test_success_with_accepts(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        manifest_payload = {"accepts": [{"scheme": "exact", "network": "eip155:8453"}]}
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                200, 
                json=manifest_payload, 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={"content-type": "application/json"}
            ),
        )
        
        result = await auditor.check_manifest_discovery("https://api.example.com")
        
        assert result.status == "PASS"
        assert "accepts" in result.message.lower()
        assert result.details is not None
        assert result.details["has_accepts"] is True

    @pytest.mark.asyncio
    async def test_fail_404(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                404, 
                text="Not Found", 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={}
            ),
        )
        
        result = await auditor.check_manifest_discovery("https://api.example.com")
        
        assert result.status == "FAIL"
        assert "404" in result.message

    @pytest.mark.asyncio
    async def test_fail_no_accepts_key(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        manifest_payload = {"version": "1.0"}
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                200, 
                json=manifest_payload, 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={}
            ),
        )
        
        result = await auditor.check_manifest_discovery("https://api.example.com")
        
        assert result.status == "FAIL"
        assert "missing" in result.message.lower()
        assert result.details is not None
        assert result.details["has_accepts"] is False

    @pytest.mark.asyncio
    async def test_fail_invalid_json(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                200, 
                text="not json", 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={}
            ),
        )
        
        result = await auditor.check_manifest_discovery("https://api.example.com")
        
        assert result.status == "FAIL"
        assert "not valid json" in result.message.lower()

    @pytest.mark.asyncio
    async def test_error_connection_timeout(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        async def timeout_get(*args: Any, **kwargs: Any) -> None:
            raise httpx.TimeoutException("Timeout")
        
        mock_client.get = timeout_get
        
        result = await auditor.check_manifest_discovery("https://api.example.com")
        
        assert result.status == "ERROR"
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_error_connect_error(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        async def connect_error_get(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("Connection refused")
        
        mock_client.get = connect_error_get
        
        result = await auditor.check_manifest_discovery("https://api.example.com")
        
        assert result.status == "ERROR"
        assert "connection" in result.message.lower()


class TestCAIP2Compliance:
    @pytest.mark.asyncio
    async def test_valid_x_payment_required(self, auditor: X402Auditor) -> None:
        payload = {"network": "eip155:8453", "maxAmountRequired": "1000", "resource": "test"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        headers = {"X-Payment-Required": encoded}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "PASS"
        assert result.details is not None
        assert result.details["caip2_value"] == "eip155:8453"
        assert result.details["valid"] is True

    @pytest.mark.asyncio
    async def test_valid_x_402_accepts(self, auditor: X402Auditor) -> None:
        payload = {"network": "eip155:1", "description": "Payment required"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        headers = {"x-402-accepts": encoded}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "PASS"
        assert result.details is not None
        assert result.details["caip2_value"] == "eip155:1"

    @pytest.mark.asyncio
    async def test_valid_www_authenticate(self, auditor: X402Auditor) -> None:
        payload = {"network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "resource": "api"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        headers = {"WWW-Authenticate": f"x402 {encoded}"}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "PASS"
        assert result.details is not None
        assert result.details["caip2_value"] == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

    @pytest.mark.asyncio
    async def test_invalid_integer_chainid(self, auditor: X402Auditor) -> None:
        payload = {"network": "8453"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        headers = {"X-Payment-Required": encoded}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "FAIL"
        assert result.details is not None
        assert result.details["caip2_value"] == "8453"
        assert result.details["valid"] is False

    @pytest.mark.asyncio
    async def test_missing_header(self, auditor: X402Auditor) -> None:
        headers = {"Content-Type": "application/json"}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "FAIL"
        assert "no valid" in result.message.lower()

    @pytest.mark.asyncio
    async def test_malformed_base64(self, auditor: X402Auditor) -> None:
        headers = {"X-Payment-Required": "not-base64!"}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "FAIL"

    @pytest.mark.asyncio
    async def test_chainid_field_fallback(self, auditor: X402Auditor) -> None:
        payload = {"chainId": "eip155:5"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        headers = {"X-Payment-Required": encoded}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "PASS"
        assert result.details is not None
        assert result.details["caip2_value"] == "eip155:5"

    @pytest.mark.asyncio
    async def test_www_authenticate_wrong_scheme(self, auditor: X402Auditor) -> None:
        payload = {"network": "eip155:8453"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        headers = {"WWW-Authenticate": f"Bearer {encoded}"}
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "FAIL"


class TestJSONResilience:
    @pytest.mark.asyncio
    async def test_pass_dict_payload(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        payload = {"error": "Payment required", "accepts": []}
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, json=payload, request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "PASS"
        assert result.details is not None
        assert result.details["is_dict"] is True

    @pytest.mark.asyncio
    async def test_critical_fail_string_payload(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, content=b'"Payment required"', request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "CRITICAL_FAIL"
        assert result.details is not None
        assert result.details["payload_type"] == "str"
        assert result.details["is_dict"] is False

    @pytest.mark.asyncio
    async def test_critical_fail_null_payload(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, content=b"null", request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "CRITICAL_FAIL"
        assert result.details is not None
        assert result.details["payload_type"] == "NoneType"
        assert result.details["is_dict"] is False

    @pytest.mark.asyncio
    async def test_critical_fail_array_payload(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, json=[{"error": "Payment required"}], request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "CRITICAL_FAIL"
        assert result.details is not None
        assert result.details["payload_type"] == "list"
        assert result.details["is_dict"] is False

    @pytest.mark.asyncio
    async def test_pass_not_402(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(200, json={"data": "ok"}, request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "PASS"
        assert "not 402" in result.message

    @pytest.mark.asyncio
    async def test_critical_fail_invalid_json(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, content=b"not json", request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "CRITICAL_FAIL"
        assert "not valid json" in result.message.lower()

    @pytest.mark.asyncio
    async def test_error_timeout(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        async def timeout_get(*args: Any, **kwargs: Any) -> None:
            raise httpx.TimeoutException("Timeout")
        
        mock_client.get = timeout_get
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "ERROR"

    @pytest.mark.asyncio
    async def test_error_connect(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        async def connect_get(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("Connection refused")
        
        mock_client.get = connect_get
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "ERROR"


class TestFullAudit:
    @pytest.mark.asyncio
    async def test_all_pass(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        manifest_payload = {"accepts": [{"scheme": "exact", "network": "eip155:8453"}]}
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                200,
                json=manifest_payload,
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={"content-type": "application/json"}
            ),
        )
        
        payment_payload = {"network": "eip155:8453"}
        encoded = base64.b64encode(json.dumps(payment_payload).encode()).decode()
        
        bazaar_block = {
            "method": "POST",
            "serviceName": "example-service",
            "tags": ["x402"],
        }
        
        # Mock base URL with trailing slash (for payment headers + bazaar check)
        mock_client.add_response(
            "https://api.example.com/",
            httpx.Response(
                402,
                headers={"X-Payment-Required": encoded, "content-type": "application/json"},
                json={"error": "Payment required", "accepts": [], "extensions": {"bazaar": bazaar_block}},
                request=httpx.Request("GET", "https://api.example.com/"),
            ),
        )
        # Mock base URL without trailing slash (for json resilience check)
        mock_client.add_response(
            "https://api.example.com",
            httpx.Response(
                402,
                headers={"X-Payment-Required": encoded, "content-type": "application/json"},
                json={"error": "Payment required", "accepts": [], "extensions": {"bazaar": bazaar_block}},
                request=httpx.Request("GET", "https://api.example.com"),
            ),
        )
        
        report = await auditor.run_full_audit("https://api.example.com")
        
        assert isinstance(report, AuditReport)
        assert report.overall_status == "PASS"
        assert report.target_url == "https://api.example.com"
        assert len(report.checks) == 4
        assert all(c.status == "PASS" for c in report.checks)

    @pytest.mark.asyncio
    async def test_critical_fail_dominates(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                404, 
                text="Not Found", 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={}
            ),
        )
        
        # Mock base URL (for payment headers check)
        mock_client.add_response(
            "https://api.example.com",
            httpx.Response(
                402,
                content=b'"string payload"',
                request=httpx.Request("GET", "https://api.example.com"),
                headers={}
            ),
        )
        # Mock resource endpoint (for json resilience check)
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(
                402,
                content=b'"string payload"',
                request=httpx.Request("GET", "https://api.example.com/resource"),
                headers={}
            ),
        )
        
        report = await auditor.run_full_audit("https://api.example.com")
        
        assert report.overall_status == "CRITICAL_FAIL"

    @pytest.mark.asyncio
    async def test_fail_dominates_over_error(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                404, 
                text="Not Found", 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={}
            ),
        )
        
        async def connect_error(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("Connection refused")
        
        original_get = mock_client.get
        async def error_get(url: str, **kwargs: Any) -> httpx.Response:
            if "/resource" in url or url == "https://api.example.com":
                raise httpx.ConnectError("Connection refused")
            return await original_get(url, **kwargs)
        
        mock_client.get = error_get
        
        report = await auditor.run_full_audit("https://api.example.com")
        
        assert report.overall_status == "FAIL"

    @pytest.mark.asyncio
    async def test_error_only(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/.well-known/x402",
            httpx.Response(
                200, 
                json={"accepts": []}, 
                request=httpx.Request("GET", "https://api.example.com/.well-known/x402"),
                headers={"content-type": "application/json"}
            ),
        )
        
        async def connect_error(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("Connection refused")
        
        mock_client.get = connect_error
        
        report = await auditor.run_full_audit("https://api.example.com")
        
        # manifest=PASS, caip2=FAIL (no headers due to connection error), json=ERROR
        # Overall = FAIL (FAIL dominates)
        assert report.overall_status == "FAIL"


class TestRunAuditFunction:
    @pytest.mark.asyncio
    async def test_run_audit_returns_report(self) -> None:
        with patch("x402_conformance_engine.X402Auditor") as mock_auditor_class:
            mock_auditor = AsyncMock()
            mock_report = AuditReport(
                target_url="https://api.example.com",
                timestamp=datetime.now(timezone.utc),
                overall_status="PASS",
                checks=[],
                summary="3/3 checks passed. Overall: PASS",
            )
            mock_auditor.run_full_audit = AsyncMock(return_value=mock_report)
            mock_auditor_class.return_value.__aenter__.return_value = mock_auditor
            
            report = await run_audit("https://api.example.com")
            
            assert report == mock_report


class TestCLI:
    def test_main_outputs_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("x402_conformance_engine.run_audit") as mock_run_audit:
            mock_report = AuditReport(
                target_url="https://api.example.com",
                timestamp=datetime.now(timezone.utc),
                overall_status="PASS",
                checks=[],
                summary="3/3 checks passed. Overall: PASS",
            )
            mock_run_audit.return_value = mock_report
            
            import sys
            sys.argv = ["x402_conformance_engine.py", "https://api.example.com"]
            
            main()
            
            captured = capsys.readouterr()
            output = captured.out.strip()
            
            assert output.startswith("{")
            assert '"target_url"' in output
            assert '"overall_status": "PASS"' in output

    def test_main_handles_keyboard_interrupt(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("x402_conformance_engine.run_audit") as mock_run_audit:
            mock_run_audit.side_effect = KeyboardInterrupt()
            
            import sys
            sys.argv = ["x402_conformance_engine.py", "https://api.example.com"]
            
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 130

    def test_main_handles_exception(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("x402_conformance_engine.run_audit") as mock_run_audit:
            mock_run_audit.side_effect = Exception("Fatal error")
            
            import sys
            sys.argv = ["x402_conformance_engine.py", "https://api.example.com"]
            
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Fatal error" in captured.err


class TestContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self) -> None:
        async with X402Auditor() as auditor:
            assert auditor._client is not None
            assert isinstance(auditor._client, httpx.AsyncClient)
        
        assert auditor._client.is_closed


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_caip2_multiple_headers_first_wins(self, auditor: X402Auditor) -> None:
        payload1 = {"network": "eip155:8453"}
        encoded1 = base64.b64encode(json.dumps(payload1).encode()).decode()
        
        payload2 = {"network": "8453"}
        encoded2 = base64.b64encode(json.dumps(payload2).encode()).decode()
        
        headers = {
            "X-Payment-Required": encoded1,
            "x-402-accepts": encoded2,
        }
        
        result = await auditor.verify_caip2_compliance(headers)
        
        assert result.status == "PASS"
        assert result.details is not None
        assert result.details["header_name"] == "X-Payment-Required"

    @pytest.mark.asyncio
    async def test_json_resilience_number_payload(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, content=b"402", request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "CRITICAL_FAIL"
        assert result.details is not None
        assert result.details["payload_type"] == "int"

    @pytest.mark.asyncio
    async def test_json_resilience_boolean_payload(self, auditor: X402Auditor, mock_client: MockAsyncClient) -> None:
        mock_client.add_response(
            "https://api.example.com/resource",
            httpx.Response(402, content=b"true", request=httpx.Request("GET", "https://api.example.com/resource")),
        )
        
        result = await auditor.test_json_resilience("https://api.example.com/resource")
        
        assert result.status == "CRITICAL_FAIL"
        assert result.details is not None
        assert result.details["payload_type"] == "bool"