import argparse
import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from x402_validator.conformance import run_audit, AuditReport


def read_urls_from_file(path: str) -> list[str]:
    urls: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            comment_pos = line.find("  # ")
            if comment_pos != -1:
                line = line[:comment_pos].strip()
            urls.append(line)
    return urls


def report_to_row(report: AuditReport) -> dict[str, str]:
    checks = {c.check_name: c.status for c in report.checks}
    row: dict[str, str] = {
        "url": report.target_url,
        "overall_status": report.overall_status,
        "manifest_discovery": checks.get("manifest_discovery", "ERROR"),
        "caip2_compliance": checks.get("caip2_compliance", "ERROR"),
        "json_resilience": checks.get("json_resilience", "ERROR"),
        "bazaar_compliance": checks.get("bazaar_compliance", "PASS"),
        "timestamp": report.timestamp.isoformat(),
    }
    if "marketplace_products" in checks:
        row["marketplace_products"] = checks["marketplace_products"]
    product_i = 1
    for c in report.checks:
        if c.check_name == "product_check":
            row.setdefault("product_checks", "")
            row["product_checks"] += f"{c.status} " if len(row.get("product_checks", "")) < 50 else ""
    return row


def write_csv(results: list[AuditReport], path: str) -> None:
    rows = [report_to_row(r) for r in results]
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(results: list[AuditReport], path: str) -> None:
    from collections import Counter
    gap_counter: Counter = Counter()
    for r in results:
        for c in r.checks:
            if c.status not in ("PASS", ""):
                gap_counter[c.check_name] += 1
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "summary": {
            "pass": sum(1 for r in results if r.overall_status == "PASS"),
            "warn": sum(1 for r in results if r.overall_status == "WARN"),
            "fail": sum(1 for r in results if r.overall_status in ("FAIL", "CRITICAL_FAIL")),
            "error": sum(1 for r in results if r.overall_status == "ERROR"),
            "common_gaps": [{"check": n, "count": c} for n, c in gap_counter.most_common(10)],
        },
        "results": [r.model_dump(mode="json") for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_html(results: list[AuditReport], path: str) -> None:
    rows_html = ""
    for r in results:
        checks_str = ", ".join(f"{c.check_name}: {c.status}" for c in r.checks)
        status_class = r.overall_status.lower()
        rows_html += (
            f'<tr class="{status_class}">'
            f"<td>{r.target_url}</td>"
            f'<td><span class="badge {status_class}">{r.overall_status}</span></td>'
            f"<td>{checks_str}</td>"
            f"<td>{r.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>"
            f"</tr>\n"
        )

    passed = sum(1 for r in results if r.overall_status == "PASS")
    failed = sum(1 for r in results if r.overall_status in ("FAIL", "CRITICAL_FAIL"))
    errors = sum(1 for r in results if r.overall_status == "ERROR")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>x402 Audit Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; background: #0d1117; color: #c9d1d9; }}
h1 {{ color: #58a6ff; }}
.summary {{ display: flex; gap: 1rem; margin: 1rem 0; }}
.summary-card {{ padding: 1rem 1.5rem; border-radius: 8px; background: #161b22; border: 1px solid #30363d; }}
.summary-card .count {{ font-size: 2rem; font-weight: bold; }}
.pass .count {{ color: #3fb950; }}
.fail .count {{ color: #f85149; }}
.error .count {{ color: #d29922; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
th, td {{ padding: 0.5rem 1rem; text-align: left; border-bottom: 1px solid #30363d; }}
th {{ background: #161b22; color: #8b949e; text-transform: uppercase; font-size: 0.8rem; }}
tr:hover {{ background: #1c2128; }}
tr.pass td:first-child {{ border-left: 3px solid #3fb950; }}
tr.fail td:first-child {{ border-left: 3px solid #f85149; }}
tr.critical_fail td:first-child {{ border-left: 3px solid #f85149; }}
tr.error td:first-child {{ border-left: 3px solid #d29922; }}
.badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }}
.badge.pass {{ background: rgba(63,185,80,0.15); color: #3fb950; }}
.badge.fail {{ background: rgba(248,81,73,0.15); color: #f85149; }}
.badge.critical_fail {{ background: rgba(248,81,73,0.15); color: #f85149; }}
.badge.error {{ background: rgba(210,153,34,0.15); color: #d29922; }}
.footer {{ margin-top: 2rem; color: #8b949e; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>x402 Audit Report</h1>
<div class="summary">
<div class="summary-card pass"><div class="count">{passed}</div><div>Passed</div></div>
<div class="summary-card fail"><div class="count">{failed}</div><div>Failed</div></div>
<div class="summary-card error"><div class="count">{errors}</div><div>Errors</div></div>
<div class="summary-card"><div class="count">{len(results)}</div><div>Total</div></div>
</div>
<table>
<thead><tr><th>URL</th><th>Status</th><th>Checks</th><th>Timestamp</th></tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
<div class="footer">Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | x402 Validator v0.2.0</div>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def print_summary(results: list[AuditReport]) -> None:
    passed = sum(1 for r in results if r.overall_status == "PASS")
    failed = sum(1 for r in results if r.overall_status in ("FAIL", "CRITICAL_FAIL"))
    errors = sum(1 for r in results if r.overall_status == "ERROR")
    total = len(results)

    print(f"\n{'='*60}")
    print(f"  x402 AUDIT COMPLETE — {total} endpoints")
    print(f"{'='*60}")
    print(f"  PASS: {passed:>4}")
    print(f"  FAIL: {failed:>4}")
    print(f"  ERROR:{errors:>4}")
    print(f"{'='*60}")

    for r in results:
        if r.overall_status != "PASS":
            failed_checks = [c for c in r.checks if c.status != "PASS"]
            reasons = "; ".join(f"{c.check_name}: {c.message}" for c in failed_checks)
            status_icon = "❌" if r.overall_status in ("FAIL", "CRITICAL_FAIL") else "⚠️"
            print(f"  {status_icon} {r.target_url}")
            print(f"     {reasons}")
    print()


async def run_batch(
    urls: list[str],
    parallel: int = 5,
    timeout: float = 10.0,
    mode: str = "standard",
) -> list[AuditReport]:
    semaphore = asyncio.Semaphore(parallel)
    total = len(urls)

    async def process(url: str) -> AuditReport:
        async with semaphore:
            return await run_audit(url, timeout=timeout, mode=mode)

    results: list[AuditReport] = []
    completed = 0
    start = time.monotonic()

    for coro in asyncio.as_completed([process(u) for u in urls]):
        report = await coro
        results.append(report)
        completed += 1
        if completed % 10 == 0 or completed == total:
            elapsed = time.monotonic() - start
            rate = completed / elapsed if elapsed > 0 else 0
            print(f"  Progress: {completed}/{total} ({rate:.1f} URLs/sec)", file=sys.stderr)

    elapsed = time.monotonic() - start
    print(f"\nCompleted {total} URLs in {elapsed:.1f}s ({total/elapsed:.1f} URLs/sec avg)", file=sys.stderr)
    return results


async def audit_async(
    urls: list[str],
    parallel: int = 5,
    timeout: float = 10.0,
    mode: str = "standard",
) -> list[AuditReport]:
    return await run_batch(urls, parallel=parallel, timeout=timeout, mode=mode)


def audit_command(
    input_file: str,
    output: list[str] | None = None,
    parallel: int = 5,
    timeout: float = 10.0,
    output_path: str | None = None,
    results: list[AuditReport] | None = None,
    mode: str = "standard",
) -> None:
    if output is None:
        output = ["csv"]
    if results is None:
        urls = read_urls_from_file(input_file)
        if not urls:
            print("Error: no URLs found in input file", file=sys.stderr)
            sys.exit(1)
        print(f"Read {len(urls)} URLs from {input_file}", file=sys.stderr)
        results = asyncio.run(run_batch(urls, parallel=parallel, timeout=timeout, mode=mode))

    writers = {"csv": write_csv, "json": write_json, "html": write_html}
    base = os.path.splitext(input_file)[0]
    for fmt in output:
        if output_path and len(output) == 1:
            path = output_path
        else:
            path = f"{base}_results.{fmt}"
        writers[fmt](results, path)
        print(f"Results written to: {path}", file=sys.stderr)

    print_summary(results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="x402 Mass Audit CLI — validate endpoints against x402 strict-v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  x402-validate endpoints.txt\n"
            "  x402-validate endpoints.txt --output json --parallel 20\n"
            "  x402-validate urls.txt --output html --parallel 10\n"
        ),
    )
    parser.add_argument("input_file", help="File with one URL per line")
    parser.add_argument("--output", nargs="*", choices=["csv", "json", "html"], default=["csv"], help="Output format(s): csv, json, html")
    parser.add_argument("--parallel", type=int, default=5, help="Concurrent workers (default: 5)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds")
    parser.add_argument("--output-path", help="Output file path (default: <input>_results.<ext>)")
    parser.add_argument("--mode", choices=["standard", "marketplace"], default="standard", help="Audit mode: standard (single endpoint) or marketplace (multi-product)")
    args = parser.parse_args()

    audit_command(
        input_file=args.input_file,
        output=args.output,
        parallel=args.parallel,
        timeout=args.timeout,
        output_path=args.output_path,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()
