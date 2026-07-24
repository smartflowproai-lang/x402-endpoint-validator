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


class BazaarResult(CheckResult):
    check_name: Literal["bazaar_compliance"] = "bazaar_compliance"
    details: Optional[dict[str, Any]] = None


class ProductResult(CheckResult):
    check_name: Literal["product_check"] = "product_check"
    product_id: str = ""
    endpoint_url: str = ""
    details: Optional[dict[str, Any]] = None


class MarketplaceResult(CheckResult):
    check_name: Literal["marketplace_products"] = "marketplace_products"
    total_products: int = 0
    conformant_count: int = 0
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
            has_products = "products" in payload and isinstance(payload["products"], list) and len(payload["products"]) > 0
            
            if has_accepts:
                return ManifestResult(
                    status="PASS",
                    message="Manifest discovered and contains 'accepts' key",
                    details={"url": manifest_url, "status_code": status_code, "has_accepts": True, "has_products": False, "headers": dict(response.headers)},
                )
            elif has_products:
                return ManifestResult(
                    status="PASS",
                    message=f"Manifest discovered with {len(payload['products'])} products in marketplace catalog",
                    details={"url": manifest_url, "status_code": status_code, "has_accepts": False, "has_products": True, "product_count": len(payload["products"]), "headers": dict(response.headers)},
                )
            else:
                return ManifestResult(
                    status="FAIL",
                    message="Manifest JSON missing required 'accepts' key and has no 'products' array",
                    details={"url": manifest_url, "status_code": status_code, "has_accepts": False, "has_products": False, "headers": {}},
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

    @staticmethod
    def check_bazaar_compliance(response_body: dict[str, Any]) -> BazaarResult:
        extensions = response_body.get("extensions", {})
        bazaar = extensions.get("bazaar")

        if bazaar is None:
            return BazaarResult(
                status="FAIL",
                message="Missing required 'extensions.bazaar' block in HTTP 402 response",
                details={
                    "bazaar_present": False,
                    "bazaar_method": None,
                    "bazaar_service_name": None,
                    "bazaar_tags": None,
                    "missing_fields": ["extensions.bazaar"],
                },
            )

        missing: list[str] = []
        bazaar_method = bazaar.get("method")
        bazaar_service_name = bazaar.get("serviceName")
        bazaar_tags = bazaar.get("tags")

        if bazaar_method is None:
            missing.append("extensions.bazaar.method")
        elif bazaar_method != "POST":
            return BazaarResult(
                status="FAIL",
                message=f"extensions.bazaar.method is '{bazaar_method}' but should be 'POST'",
                details={
                    "bazaar_present": True,
                    "bazaar_method": bazaar_method,
                    "bazaar_service_name": bazaar_service_name,
                    "bazaar_tags": bazaar_tags,
                    "missing_fields": [],
                },
            )

        if bazaar_service_name is None or not isinstance(bazaar_service_name, str) or bazaar_service_name.strip() == "":
            missing.append("extensions.bazaar.serviceName")

        if bazaar_tags is None or not isinstance(bazaar_tags, list) or len(bazaar_tags) == 0:
            missing.append("extensions.bazaar.tags")

        if missing:
            return BazaarResult(
                status="FAIL",
                message=f"Missing or invalid fields in extensions.bazaar: {', '.join(missing)}",
                details={
                    "bazaar_present": True,
                    "bazaar_method": bazaar_method,
                    "bazaar_service_name": bazaar_service_name,
                    "bazaar_tags": bazaar_tags,
                    "missing_fields": missing,
                },
            )

        return BazaarResult(
            status="PASS",
            message="extensions.bazaar is complete and valid",
            details={
                "bazaar_present": True,
                "bazaar_method": bazaar_method,
                "bazaar_service_name": bazaar_service_name,
                "bazaar_tags": bazaar_tags,
                "missing_fields": [],
            },
        )

    async def check_marketplace_products(self, manifest_payload: dict[str, Any]) -> MarketplaceResult:
        products = manifest_payload.get("products", [])
        if not products:
            return MarketplaceResult(
                status="FAIL",
                message="Manifest has no 'products' array",
                total_products=0,
                conformant_count=0,
                details={"product_count": 0, "conformant": 0, "product_details": []},
            )

        product_details: list[dict[str, Any]] = []
        conformant = 0

        for i, product in enumerate(products):
            pid = product.get("id", f"product_{i}")
            name = product.get("name", pid)
            x402_block = product.get("x402")
            errors: list[str] = []

            if x402_block is None:
                errors.append("missing x402 block")
            else:
                scheme = x402_block.get("scheme")
                network = x402_block.get("network")
                pay_to = x402_block.get("pay_to") or x402_block.get("payTo")
                facilitator = x402_block.get("facilitator_url")

                if scheme != "exact":
                    errors.append(f"scheme should be 'exact', got '{scheme}'")
                if not network or not CAIP2_PATTERN.match(str(network)):
                    errors.append(f"invalid CAIP-2 network: {network}")
                if not pay_to:
                    errors.append("missing pay_to address")
                if not facilitator:
                    errors.append("missing facilitator_url")

            if product.get("method") and product["method"] != "GET":
                errors.append(f"method should be GET, got {product['method']}")

            product_status = "conformant" if not errors else "non_conformant"
            if product_status == "conformant":
                conformant += 1

            product_details.append({
                "product_id": pid,
                "name": name,
                "endpoint": product.get("endpoint", ""),
                "status": product_status,
                "errors": errors,
                "x402": x402_block,
            })

        total = len(products)
        all_ok = conformant == total

        return MarketplaceResult(
            status="PASS" if all_ok else "FAIL",
            message=f"{conformant}/{total} products conformant"
            if not all_ok
            else f"All {total} products conformant",
            total_products=total,
            conformant_count=conformant,
            details={"product_count": total, "conformant": conformant, "product_details": product_details},
        )

    async def walk_product_endpoints(
        self, manifest_payload: dict[str, Any]
    ) -> list[ProductResult]:
        products = manifest_payload.get("products", [])
        results: list[ProductResult] = []

        for product in products:
            endpoint = product.get("endpoint", "")
            pid = product.get("id", "unknown")
            name = product.get("name", pid)
            if not endpoint:
                results.append(
                    ProductResult(
                        status="ERROR",
                        message=f"Product {pid} has no endpoint",
                        product_id=pid,
                        endpoint_url="",
                        details={"error": "no endpoint defined"},
                    )
                )
                continue

            x402_block = product.get("x402")
            is_free = x402_block is None
            full_url = self._base_url.rstrip("/") + endpoint

            try:
                resp = await self._client.get(full_url)
                status = resp.status_code

                if is_free:
                    if status == 200:
                        results.append(
                            ProductResult(
                                status="PASS",
                                message=f"Free product '{name}' → HTTP 200",
                                product_id=pid,
                                endpoint_url=full_url,
                                details={"endpoint": endpoint, "status_code": status, "is_free": True},
                            )
                        )
                    else:
                        results.append(
                            ProductResult(
                                status="FAIL",
                                message=f"Free product '{name}' expected HTTP 200, got {status}",
                                product_id=pid,
                                endpoint_url=full_url,
                                details={"endpoint": endpoint, "status_code": status, "is_free": True},
                            )
                        )
                else:
                    if status == 402:
                        headers_lower = {k.lower(): v for k, v in resp.headers.items()}
                        has_pr = "payment-required" in headers_lower or "x-payment-required" in headers_lower
                        results.append(
                            ProductResult(
                                status="PASS" if has_pr else "FAIL",
                                message=f"Paid product '{name}' → HTTP 402" + (" with Payment-Required header" if has_pr else " (missing Payment-Required header)"),
                                product_id=pid,
                                endpoint_url=full_url,
                                details={
                                    "endpoint": endpoint,
                                    "status_code": status,
                                    "is_free": False,
                                    "has_payment_header": has_pr,
                                    "headers": dict(resp.headers),
                                },
                            )
                        )
                    elif status == 200:
                        results.append(
                            ProductResult(
                                status="FAIL",
                                message=f"Paid product '{name}' returned HTTP 200 (should be 402)",
                                product_id=pid,
                                endpoint_url=full_url,
                                details={"endpoint": endpoint, "status_code": status, "is_free": False},
                            )
                        )
                    else:
                        results.append(
                            ProductResult(
                                status="ERROR",
                                message=f"Paid product '{name}' returned unexpected HTTP {status}",
                                product_id=pid,
                                endpoint_url=full_url,
                                details={"endpoint": endpoint, "status_code": status, "is_free": False},
                            )
                        )
            except httpx.TimeoutException:
                results.append(
                    ProductResult(
                        status="ERROR",
                        message=f"Product '{name}' timed out",
                        product_id=pid,
                        endpoint_url=full_url,
                        details={"endpoint": endpoint, "error": "timeout"},
                    )
                )
            except httpx.ConnectError as e:
                results.append(
                    ProductResult(
                        status="ERROR",
                        message=f"Product '{name}' connection error: {e}",
                        product_id=pid,
                        endpoint_url=full_url,
                        details={"endpoint": endpoint, "error": str(e)},
                    )
                )
            except Exception as e:
                results.append(
                    ProductResult(
                        status="ERROR",
                        message=f"Product '{name}' error: {e}",
                        product_id=pid,
                        endpoint_url=full_url,
                        details={"endpoint": endpoint, "error": str(e)},
                    )
                )

        return results

    async def run_full_audit(self, target_url: str, mode: str = "standard") -> AuditReport:
        self._base_url = target_url
        timestamp = datetime.now(timezone.utc)
        checks: list[CheckResult] = []

        manifest_result = await self.check_manifest_discovery(target_url)
        checks.append(manifest_result)

        payment_headers = await self._get_payment_headers(target_url)

        caip2_result = await self.verify_caip2_compliance(payment_headers)
        checks.append(caip2_result)

        json_result = await self.test_json_resilience(target_url)
        checks.append(json_result)

        bazaar_result = await self._check_bazaar_from_response(target_url)
        checks.append(bazaar_result)

        if mode == "marketplace":
            manifest_url = target_url.rstrip("/") + "/.well-known/x402"
            try:
                resp = await self._client.get(manifest_url)
                manifest_payload = resp.json()
            except Exception:
                manifest_payload = {}

            marketplace_result = await self.check_marketplace_products(manifest_payload)
            checks.append(marketplace_result)

            product_results = await self.walk_product_endpoints(manifest_payload)
            checks.extend(product_results)

            for pr in product_results:
                if pr.details and not pr.details.get("is_free", False):
                    ep = pr.details.get("endpoint", "")
                    if ep:
                        body = await self._get_402_body_raw(target_url.rstrip("/") + ep)
                        if body is not None:
                            bazaar_check = self.check_bazaar_compliance(body)
                            bazaar_check.check_name = f"bazaar_{pr.product_id}"
                            checks.append(bazaar_check)

            manifest_network = manifest_payload.get("network", "")
            if manifest_network and CAIP2_PATTERN.match(str(manifest_network)):
                checks.append(
                    Caip2Result(
                        status="PASS",
                        message=f"CAIP-2 network from manifest: {manifest_network}",
                        details={"header_present": True, "header_name": "manifest.network", "caip2_value": manifest_network, "valid": True},
                    )
                )

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

    async def _get_402_body(self, target_url: str) -> dict[str, Any] | None:
        return await self._get_402_body_raw(target_url.rstrip("/") + "/")

    async def _get_402_body_raw(self, url: str) -> dict[str, Any] | None:
        try:
            response = await self._client.get(url)
            if response.status_code == 402:
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return None

    async def _check_bazaar_from_response(self, target_url: str) -> BazaarResult:
        body = await self._get_402_body(target_url)
        if body is None:
            return BazaarResult(
                status="PASS",
                message="No 402 response body to check for bazaar compliance",
                details={
                    "bazaar_present": False,
                    "bazaar_method": None,
                    "bazaar_service_name": None,
                    "bazaar_tags": None,
                    "missing_fields": [],
                },
            )
        return self.check_bazaar_compliance(body)


async def run_audit(url: str, timeout: float = 10.0, mode: str = "standard") -> AuditReport:
    async with X402Auditor(timeout=timeout) as auditor:
        return await auditor.run_full_audit(url, mode=mode)


def main() -> None:
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="x402 Conformance Engine")
    parser.add_argument("url", help="Target base URL to audit")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds")
    parser.add_argument("--mode", choices=["standard", "marketplace"], default="standard", help="Audit mode")
    args = parser.parse_args()
    
    try:
        report = asyncio.run(run_audit(args.url, args.timeout, args.mode))
        print(report.model_dump_json(indent=2))
    except KeyboardInterrupt:
        print("Audit interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()