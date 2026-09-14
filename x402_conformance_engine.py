import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, Field


CAIP2_PATTERN = re.compile(r'^[a-z0-9-]+:[a-zA-Z0-9_-]+$')


class CheckResult(BaseModel):
    check_name: str
    status: Literal["PASS", "FAIL", "CRITICAL_FAIL", "ERROR"]
    message: str
    details: Optional[dict[str, Any]] = None


class ManifestResult(CheckResult):
    check_name: Literal["manifest_discovery"] = "manifest_discovery"
    details: Optional[dict[str, Any]] = None


class Caip2Result(CheckResult):
    check_name: Literal["caip2_compliance"] = "caip2_compliance"
    details: Optional[dict[str, Any]] = None


class JsonResilienceResult(CheckResult):
    check_name: Literal["json_resilience"] = "json_resilience"
    details: Optional[dict[str, Any]] = None


class AuditReport(BaseModel):
    target_url: str
    timestamp: datetime
    overall_status: Literal["PASS", "FAIL", "CRITICAL_FAIL", "ERROR"]
    checks: list[CheckResult]
    summary: str


class X402Auditor:
    def __init__(
        self,
        timeout: float = 10.0,
        default_headers: Optional[dict[str, str]] = None,
        follow_redirects: bool = True,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=default_headers or {},
            follow_redirects=follow_redirects,
        )

    async def __aenter__(self) -> "X402Auditor":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def check_manifest_discovery(self, base_url: str) -> ManifestResult:
        manifest_url = base_url.rstrip("/") + "/.well-known/x402"
        
        try:
            response = await self._client.get(manifest_url)
            status_code = response.status_code
            
            if status_code != 200:
                return ManifestResult(
                    status="FAIL",
                    message=f"Manifest endpoint returned HTTP {status_code}",
                    details={"url": manifest_url, "status_code": status_code, "has_accepts": False, "headers": {}},
                )
            
            try:
                payload = response.json()
            except json.JSONDecodeError:
                return ManifestResult(
                    status="FAIL",
                    message="Manifest response is not valid JSON",
                    details={"url": manifest_url, "status_code": status_code, "has_accepts": False, "headers": {}},
                )
            
            has_accepts = "accepts" in payload
            if not has_accepts:
                return ManifestResult(
                    status="FAIL",
                    message="Manifest JSON missing required 'accepts' key",
                    details={"url": manifest_url, "status_code": status_code, "has_accepts": False, "headers": {}},
                )
            
            return ManifestResult(
                status="PASS",
                message="Manifest discovered and contains 'accepts' key",
                details={"url": manifest_url, "status_code": status_code, "has_accepts": True, "headers": dict(response.headers)},
            )
            
        except httpx.TimeoutException:
            return ManifestResult(
                status="ERROR",
                message="Request timed out",
                details={"url": manifest_url, "status_code": None, "has_accepts": False, "headers": {}},
            )
        except httpx.ConnectError as e:
            return ManifestResult(
                status="ERROR",
                message=f"Connection error: {str(e)}",
                details={"url": manifest_url, "status_code": None, "has_accepts": False, "headers": {}},
            )
        except httpx.HTTPStatusError as e:
            return ManifestResult(
                status="ERROR",
                message=f"HTTP error: {str(e)}",
                details={"url": manifest_url, "status_code": e.response.status_code, "has_accepts": False, "headers": {}},
            )
        except Exception as e:
            return ManifestResult(
                status="ERROR",
                message=f"Unexpected error: {str(e)}",
                details={"url": manifest_url, "status_code": None, "has_accepts": False, "headers": {}},
            )

    async def verify_caip2_compliance(self, headers: dict[str, str]) -> Caip2Result:
        target_headers = [
            "x-payment-required",
            "x-402-accepts",
            "www-authenticate",
        ]
        
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        for header_name in target_headers:
            header_value = headers_lower.get(header_name)
            if not header_value:
                continue
            
            try:
                if header_name == "www-authenticate":
                    if not header_value.lower().startswith("x402 "):
                        continue
                    encoded_part = header_value[5:].strip()
                else:
                    encoded_part = header_value
                
                decoded = base64.b64decode(encoded_part).decode("utf-8")
                payload = json.loads(decoded)
                
                network = payload.get("network") or payload.get("chainId")
                if not network:
                    continue
                
                network_str = str(network)
                is_valid = bool(CAIP2_PATTERN.match(network_str))
                
                display_name = header_name.replace("x-payment-required", "X-Payment-Required") \
                    .replace("x-402-accepts", "x-402-accepts") \
                    .replace("www-authenticate", "WWW-Authenticate")
                
                return Caip2Result(
                    status="PASS" if is_valid else "FAIL",
                    message=f"CAIP-2 validation {'passed' if is_valid else 'failed'} for header {display_name}",
                    details={
                        "header_present": True,
                        "header_name": display_name,
                        "caip2_value": network_str,
                        "valid": is_valid,
                    },
                )
                
            except (base64.binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
                continue
            except Exception:
                continue
        
        return Caip2Result(
            status="FAIL",
            message="No valid CAIP-2 network identifier found in payment headers",
            details={
                "header_present": False,
                "header_name": None,
                "caip2_value": None,
                "valid": False,
            },
        )

    async def test_json_resilience(self, endpoint_url: str) -> JsonResilienceResult:
        try:
            response = await self._client.get(endpoint_url)
            status_code = response.status_code
            
            if status_code != 402:
                return JsonResilienceResult(
                    status="PASS",
                    message=f"Endpoint returned HTTP {status_code} (not 402, check not applicable)",
                    details={"status_code": status_code, "payload_type": None, "is_dict": None},
                )
            
            try:
                payload = response.json()
            except json.JSONDecodeError:
                return JsonResilienceResult(
                    status="CRITICAL_FAIL",
                    message="HTTP 402 response body is not valid JSON",
                    details={"status_code": 402, "payload_type": "invalid_json", "is_dict": False},
                )
            
            payload_type = type(payload).__name__
            is_dict = type(payload) is dict
            
            if is_dict:
                return JsonResilienceResult(
                    status="PASS",
                    message="HTTP 402 response is a valid JSON object (dict)",
                    details={"status_code": 402, "payload_type": payload_type, "is_dict": True},
                )
            else:
                sample = str(payload)[:100] if payload is not None else "null"
                return JsonResilienceResult(
                    status="CRITICAL_FAIL",
                    message=f"HTTP 402 response is a JSON primitive ({payload_type}), not an object. This crashes the reference verifier.",
                    details={"status_code": 402, "payload_type": payload_type, "is_dict": False, "sample": sample},
                )
                
        except httpx.TimeoutException:
            return JsonResilienceResult(
                status="ERROR",
                message="Request timed out",
                details={"status_code": None, "payload_type": None, "is_dict": None},
            )
        except httpx.ConnectError as e:
            return JsonResilienceResult(
                status="ERROR",
                message=f"Connection error: {str(e)}",
                details={"status_code": None, "payload_type": None, "is_dict": None},
            )
        except Exception as e:
            return JsonResilienceResult(
                status="ERROR",
                message=f"Unexpected error: {str(e)}",
                details={"status_code": None, "payload_type": None, "is_dict": None},
            )

    async def run_full_audit(self, target_url: str) -> AuditReport:
        timestamp = datetime.now(timezone.utc)
        checks: list[CheckResult] = []
        
        manifest_result = await self.check_manifest_discovery(target_url)
        checks.append(manifest_result)
        
        payment_headers = await self._get_payment_headers(target_url)
        
        caip2_result = await self.verify_caip2_compliance(payment_headers)
        checks.append(caip2_result)
        
        json_result = await self.test_json_resilience(target_url)
        checks.append(json_result)
        
        has_critical = any(c.status == "CRITICAL_FAIL" for c in checks)
        has_fail = any(c.status == "FAIL" for c in checks)
        has_error = any(c.status == "ERROR" for c in checks)
        
        if has_critical:
            overall_status = "CRITICAL_FAIL"
        elif has_fail:
            overall_status = "FAIL"
        elif has_error:
            overall_status = "ERROR"
        else:
            overall_status = "PASS"
        
        passed = sum(1 for c in checks if c.status == "PASS")
        total = len(checks)
        summary = f"{passed}/{total} checks passed. Overall: {overall_status}"
        
        return AuditReport(
            target_url=target_url,
            timestamp=timestamp,
            overall_status=overall_status,
            checks=checks,
            summary=summary,
        )

    async def _get_payment_headers(self, target_url: str) -> dict[str, str]:
        try:
            url = target_url.rstrip("/") + "/"
            response = await self._client.get(url)
            if response.status_code == 402:
                return dict(response.headers)
        except Exception:
            pass
        return {}


async def run_audit(url: str, timeout: float = 10.0) -> AuditReport:
    async with X402Auditor(timeout=timeout) as auditor:
        return await auditor.run_full_audit(url)


def main() -> None:
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="x402 Conformance Engine")
    parser.add_argument("url", help="Target base URL to audit")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds")
    args = parser.parse_args()
    
    try:
        report = asyncio.run(run_audit(args.url, args.timeout))
        print(report.model_dump_json(indent=2))
    except KeyboardInterrupt:
        print("Audit interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()