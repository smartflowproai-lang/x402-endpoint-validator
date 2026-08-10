import argparse
import asyncio
import csv
import sys
import time
from typing import Any

from x402_conformance_engine import AuditReport, X402Auditor, run_audit


async def audit_single_url(
    url: str,
    semaphore: asyncio.Semaphore,
    timeout: float = 10.0,
) -> dict[str, str]:
    async with semaphore:
        try:
            report = await run_audit(url, timeout=timeout)
            checks = {c.check_name: c.status for c in report.checks}
            return {
                "url": url,
                "overall_status": report.overall_status,
                "manifest_status": checks.get("manifest_discovery", "ERROR"),
                "caip2_status": checks.get("caip2_compliance", "ERROR"),
                "json_resilience_status": checks.get("json_resilience", "ERROR"),
            }
        except Exception as e:
            return {
                "url": url,
                "overall_status": "ERROR",
                "manifest_status": "ERROR",
                "caip2_status": "ERROR",
                "json_resilience_status": "ERROR",
            }


def read_urls_from_csv(input_path: str, url_column: str = "url") -> list[str]:
    urls: list[str] = []
    with open(input_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if url_column not in (reader.fieldnames or []):
            available = ", ".join(reader.fieldnames or [])
            print(f"Error: Column '{url_column}' not found. Available columns: {available}", file=sys.stderr)
            raise SystemExit(1)
        for row in reader:
            url = row[url_column].strip()
            if url:
                urls.append(url)
    return urls


def write_results_to_csv(results: list[dict[str, str]], output_path: str) -> None:
    fieldnames = ["url", "overall_status", "manifest_status", "caip2_status", "json_resilience_status"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def print_summary(results: list[dict[str, str]]) -> None:
    total = len(results)
    statuses = {"PASS": 0, "FAIL": 0, "CRITICAL_FAIL": 0, "ERROR": 0}
    for r in results:
        status = r["overall_status"]
        statuses[status] = statuses.get(status, 0) + 1

    print(f"\n{'='*60}")
    print(f"  BATCH VALIDATION COMPLETE — {total} endpoints audited")
    print(f"{'='*60}")
    print(f"  ✅ PASS:          {statuses['PASS']:>4}")
    print(f"  ⚠️  FAIL:          {statuses['FAIL']:>4}")
    print(f"  🔴 CRITICAL_FAIL: {statuses['CRITICAL_FAIL']:>4}")
    print(f"  ❌ ERROR:         {statuses['ERROR']:>4}")
    print(f"{'='*60}")

    criticals = [r for r in results if r["overall_status"] == "CRITICAL_FAIL"]
    if criticals:
        print(f"\n  ⚠️  CRITICAL FAILURES (crash strict-v2 verifier):")
        for r in criticals[:10]:
            print(f"    • {r['url']}")
        if len(criticals) > 10:
            print(f"    ... and {len(criticals) - 10} more")
        print()


async def run_batch(
    urls: list[str],
    concurrency: int = 50,
    timeout: float = 10.0,
    output_path: str = "batch_results.csv",
) -> list[dict[str, str]]:
    semaphore = asyncio.Semaphore(concurrency)
    total = len(urls)

    print(f"Starting batch validation of {total} URLs (concurrency={concurrency})...")

    start_time = time.monotonic()

    tasks = [audit_single_url(url, semaphore, timeout=timeout) for url in urls]

    completed = 0
    results: list[dict[str, str]] = []

    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        completed += 1
        if completed % 10 == 0 or completed == total:
            elapsed = time.monotonic() - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            print(f"  Progress: {completed}/{total} ({rate:.1f} URLs/sec)")

    elapsed = time.monotonic() - start_time
    print(f"\nBatch completed in {elapsed:.1f}s ({total/elapsed:.1f} URLs/sec avg)")

    write_results_to_csv(results, output_path)
    print(f"Results written to: {output_path}")

    print_summary(results)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="x402 Batch Conformance Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example usage:\n"
            "  python batch_validator.py strictv2-breakdown.csv\n"
            "  python batch_validator.py strictv2-breakdown.csv --concurrency 25 --output results.csv\n"
        ),
    )
    parser.add_argument("input_csv", help="Path to input CSV file with a 'url' column")
    parser.add_argument("--url-column", default="url", help="Name of the column containing URLs (default: url)")
    parser.add_argument("--concurrency", type=int, default=50, help="Max concurrent requests (default: 50)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10.0)")
    parser.add_argument("--output", default="batch_results.csv", help="Output CSV path (default: batch_results.csv)")
    args = parser.parse_args()

    urls = read_urls_from_csv(args.input_csv, args.url_column)
    if not urls:
        print("Error: No URLs found in the input CSV.", file=sys.stderr)
        raise SystemExit(1)

    print(f"Read {len(urls)} URLs from {args.input_csv}")

    asyncio.run(
        run_batch(
            urls,
            concurrency=args.concurrency,
            timeout=args.timeout,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
