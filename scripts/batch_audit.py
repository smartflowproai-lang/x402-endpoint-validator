import asyncio
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from x402_validator.cli import read_urls_from_file, run_batch, write_csv, write_json, write_html
from x402_validator.conformance import run_audit, AuditReport, ManifestResult


def detect_mode(url: str, manifest_payload: dict | None = None) -> str:
    mkt_indicators = ["market", "catalog", "farm", "shop", "ecosystem", "x402-farm"]
    if manifest_payload:
        if "products" in manifest_payload:
            return "marketplace"
    for ind in mkt_indicators:
        if ind in url.lower():
            return "marketplace"
    return "standard"


async def run_multi_audit(urls: list[str], parallel: int = 10, timeout: float = 15.0) -> list[AuditReport]:
    semaphore = asyncio.Semaphore(parallel)
    total = len(urls)
    results: list[AuditReport] = []
    completed = 0
    start = time.monotonic()

    async def detect_and_audit(url: str, sem: asyncio.Semaphore, timeout: float) -> AuditReport:
        async with sem:
            try:
                import httpx
                manifest_url = url.rstrip("/") + "/.well-known/x402"
                client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
                resp = await client.get(manifest_url)
                payload = {}
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                    except Exception:
                        pass
                await client.aclose()

                has_products = "products" in payload and isinstance(payload.get("products"), list) and len(payload["products"]) > 0
                has_resources = "resources" in payload and isinstance(payload.get("resources"), list) and len(payload["resources"]) > 0

                if has_products:
                    return await run_audit(url, timeout=timeout, mode="marketplace")
                elif has_resources:
                    return await run_audit(url, timeout=timeout, mode="resources")
                else:
                    report = await run_audit(url, timeout=timeout, mode="standard")
                    if payload:
                        report.checks.insert(0, ManifestResult(
                            status="FAIL",
                            message=f"Manifest found but unrecognized format (keys: {list(payload.keys())[:6]})",
                            details={"keys": list(payload.keys())},
                        ))
                    return report
            except Exception as e:
                return await run_audit(url, timeout=timeout, mode="standard")

    async def process(url: str) -> AuditReport:
        return await detect_and_audit(url, semaphore, timeout)

    for coro in asyncio.as_completed([process(u) for u in urls]):
        report = await coro
        results.append(report)
        completed += 1
        if completed % 5 == 0 or completed == total:
            elapsed = time.monotonic() - start
            rate = completed / elapsed if elapsed > 0 else 0
            print(f"  Progress: {completed}/{total} ({rate:.1f}/s)", file=sys.stderr)

    elapsed = time.monotonic() - start
    print(f"\nCompleted {total} URLs in {elapsed:.1f}s ({total/elapsed:.1f}/s avg)", file=sys.stderr)
    return results


def extract_metrics(r: AuditReport) -> dict:
    checks = {c.check_name: c for c in r.checks}
    statuses = {c.check_name: c.status for c in r.checks}

    manifest_ok = statuses.get("manifest_discovery", "") == "PASS"
    payment_terms = checks.get("payment_terms_coverage")
    resource_cov = checks.get("resource_coverage")
    caip2_dist = checks.get("caip2_distribution")

    resources_total = 0
    resources_with_terms = 0
    coverage_pct = 0.0
    caip2_in_resources = 0
    gaps_list = []

    if payment_terms and payment_terms.details:
        resources_total = payment_terms.details.get("total", 0)
        resources_with_terms = payment_terms.details.get("with_terms", 0)

    if resource_cov and resource_cov.details:
        coverage_pct = resource_cov.details.get("coverage_pct", 0.0)
        with_x402 = resource_cov.details.get("with_x402", 0)
        caip2_in_resources = with_x402

    if caip2_dist and caip2_dist.details:
        caip2_count = caip2_dist.details.get("count", 0)
        if caip2_count > 0:
            caip2_in_resources = caip2_count

    for c in r.checks:
        if c.status not in ("PASS", ""):
            gaps_list.append(f"{c.check_name}: {c.message[:80]}")

    return {
        "url": r.target_url,
        "overall": r.overall_status,
        "manifest_ok": manifest_ok,
        "manifest": statuses.get("manifest_discovery", ""),
        "caip2": statuses.get("caip2_compliance", ""),
        "caip2_distribution": statuses.get("caip2_distribution", ""),
        "payment_terms": statuses.get("payment_terms_coverage", ""),
        "coverage_pct": coverage_pct,
        "resources_total": resources_total,
        "resources_with_terms": resources_with_terms,
        "bazaar": statuses.get("bazaar_compliance", ""),
        "gaps": "; ".join(gaps_list),
        "gaps_count": len(gaps_list),
        "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }


def gen_detailed_csv(results: list[AuditReport], path: str) -> None:
    fieldnames = [
        "url", "overall", "manifest_ok", "manifest", "caip2", "caip2_distribution",
        "payment_terms", "coverage_pct", "resources_total", "resources_with_terms",
        "bazaar", "gaps_count", "gaps", "timestamp",
    ]
    rows = [extract_metrics(r) for r in results]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def gen_detailed_html(results: list[AuditReport], path: str) -> None:
    rows_html = ""
    for r in sorted(results, key=lambda x: (x.overall_status != "PASS", x.overall_status)):
        met = extract_metrics(r)
        checks_str = ", ".join(
            f'<span class="chk {c.status.lower()}">{c.check_name}: {c.status}</span>'
            for c in r.checks
        )
        status_class = r.overall_status.lower()
        non_pass = [c for c in r.checks if c.status not in ("PASS", "")]
        gaps_html = "<ul>" + "".join(
            f"<li><b>{c.check_name}</b>: {c.message[:120]}</li>" for c in non_pass[:5]
        ) + "</ul>" if non_pass else "<span class='ok'>None</span>"

        icon = {"pass": "✅", "fail": "❌", "critical_fail": "🚨", "error": "⚠️"}.get(status_class, "❓")

        cov_bar = ""
        if met["coverage_pct"] > 0:
            pct = int(met["coverage_pct"])
            cov_bar = f'<div class="cov-bar"><div class="cov-fill" style="width:{pct}%"></div></div><small>{pct}%</small>'

        rows_html += f"""<tr class="{status_class}">
<td><a href="{r.target_url}" target="_blank">{r.target_url}</a></td>
<td><span class="badge {status_class}">{icon} {r.overall_status}</span></td>
<td>{checks_str}</td>
<td>{met["payment_terms"]}</td>
<td>{met["caip2_distribution"]}</td>
<td>{cov_bar}</td>
<td>{gaps_html}</td>
<td>{r.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>
</tr>\n"""

    passed = sum(1 for r in results if r.overall_status == "PASS")
    failed = sum(1 for r in results if r.overall_status in ("FAIL", "CRITICAL_FAIL"))
    warned = sum(1 for r in results if r.overall_status == "WARN")
    errors = sum(1 for r in results if r.overall_status == "ERROR")

    gap_counter: Counter = Counter()
    for r in results:
        for c in r.checks:
            if c.status not in ("PASS", ""):
                gap_counter[c.check_name] += 1

    common_gaps = gap_counter.most_common(10)
    gaps_table = "".join(
        f"<tr><td>{name}</td><td>{cnt}</td><td>{cnt/len(results)*100:.0f}%</td></tr>"
        for name, cnt in common_gaps
    )

    metrics = [extract_metrics(r) for r in results]
    avg_coverage = sum(m["coverage_pct"] for m in metrics) / len(metrics) if metrics else 0
    total_resources = sum(m["resources_total"] for m in metrics)
    total_with_terms = sum(m["resources_with_terms"] for m in metrics)
    resourced_endpoints = sum(1 for m in metrics if m["resources_total"] > 0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>x402 Mass Audit Report — {len(results)} endpoints</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; background: #0d1117; color: #c9d1d9; }}
h1, h2 {{ color: #58a6ff; }}
.summary {{ display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }}
.summary-card {{ padding: 1rem 1.5rem; border-radius: 8px; background: #161b22; border: 1px solid #30363d; min-width: 100px; }}
.summary-card .count {{ font-size: 2rem; font-weight: bold; }}
.pass .count {{ color: #3fb950; }}
.warn .count {{ color: #d29922; }}
.fail .count {{ color: #f85149; }}
.error .count {{ color: #d29922; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; }}
th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #30363d; font-size: 0.85rem; }}
th {{ background: #161b22; color: #8b949e; text-transform: uppercase; font-size: 0.75rem; }}
tr:hover {{ background: #1c2128; }}
tr.pass td:first-child {{ border-left: 3px solid #3fb950; }}
tr.warn td:first-child {{ border-left: 3px solid #d29922; }}
tr.fail td:first-child {{ border-left: 3px solid #f85149; }}
tr.critical_fail td:first-child {{ border-left: 3px solid #f85149; }}
tr.error td:first-child {{ border-left: 3px solid #d29922; }}
.badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }}
.badge.pass {{ background: rgba(63,185,80,0.15); color: #3fb950; }}
.badge.warn {{ background: rgba(210,153,34,0.15); color: #d29922; }}
.badge.fail {{ background: rgba(248,81,73,0.15); color: #f85149; }}
.badge.critical_fail {{ background: rgba(248,81,73,0.15); color: #f85149; }}
.badge.error {{ background: rgba(210,153,34,0.15); color: #d29922; }}
.chk {{ display: inline-block; margin: 1px; padding: 0 4px; border-radius: 4px; font-size: 0.75rem; }}
.chk.pass {{ color: #3fb950; }}
.chk.warn {{ color: #d29922; }}
.chk.fail {{ color: #f85149; }}
.chk.critical_fail {{ color: #f85149; text-decoration: underline; }}
.chk.error {{ color: #d29922; }}
.ok {{ color: #3fb950; }}
a {{ color: #58a6ff; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
ul {{ margin: 0; padding-left: 1rem; }}
li {{ margin: 2px 0; }}
.footer {{ margin-top: 2rem; color: #8b949e; font-size: 0.85rem; }}
.section {{ margin-top: 2rem; }}
.cov-bar {{ width: 80px; height: 10px; background: #30363d; border-radius: 5px; overflow: hidden; display: inline-block; vertical-align: middle; }}
.cov-fill {{ height: 100%; background: #58a6ff; border-radius: 5px; transition: width 0.3s; }}
</style>
</head>
<body>
<h1>x402 Mass Audit Report</h1>
<p>{len(results)} endpoints · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

<div class="summary">
<div class="summary-card pass"><div class="count">{passed}</div><div>Pass</div></div>
<div class="summary-card warn"><div class="count">{warned}</div><div>Warn</div></div>
<div class="summary-card fail"><div class="count">{failed}</div><div>Fail</div></div>
<div class="summary-card error"><div class="count">{errors}</div><div>Error</div></div>
<div class="summary-card"><div class="count">{len(results)}</div><div>Total</div></div>
</div>

<div class="section">
<h2>Ecosystem Metrics</h2>
<table>
<thead><tr><th>Metric</th><th>Value</th></tr></thead>
<tbody>
<tr><td>Endpoints with resources[]</td><td>{resourced_endpoints}/{len(results)}</td></tr>
<tr><td>Total resources declared</td><td>{total_resources}</td></tr>
<tr><td>Resources with x402 payment terms</td><td>{total_with_terms} ({total_with_terms/total_resources*100:.0f}% of declared resources)</td></tr>
<tr><td>Average coverage per endpoint</td><td>{avg_coverage:.0f}%</td></tr>
</tbody>
</table>
</div>

<div class="section">
<h2>Most Common Gaps</h2>
<table>
<thead><tr><th>Check</th><th>Failures</th><th>% of total</th></tr></thead>
<tbody>{gaps_table}</tbody>
</table>
</div>

<div class="section">
<h2>Per-Endpoint Results</h2>
<table>
<thead><tr><th>URL</th><th>Status</th><th>Checks</th><th>Payment&nbsp;Terms</th><th>CAIP-2&nbsp;Dist</th><th>Coverage</th><th>Gaps</th><th>Timestamp</th></tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>

<div class="footer">Generated by x402-validator v0.2.0 | Open source: github.com/smartflowproai-lang/x402-endpoint-validator</div>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def print_detailed_summary(results: list[AuditReport]):
    passed = sum(1 for r in results if r.overall_status == "PASS")
    failed = sum(1 for r in results if r.overall_status in ("FAIL", "CRITICAL_FAIL"))
    errors = sum(1 for r in results if r.overall_status == "ERROR")
    total = len(results)

    gap_counter: Counter = Counter()
    for r in results:
        for c in r.checks:
            if c.status not in ("PASS", ""):
                gap_counter[c.check_name] += 1

    networks: Counter = Counter()
    for r in results:
        for c in r.checks:
            if c.check_name == "caip2_compliance" and c.status == "PASS" and c.details:
                net = c.details.get("caip2_value") or c.details.get("network") or "unknown"
                networks[str(net)] += 1
            elif c.check_name == "caip2_compliance" and c.status == "FAIL":
                networks["no-caip2"] += 1

    print(f"\n{'='*60}")
    print(f"  x402 MASS AUDIT COMPLETE — {total} endpoints")
    print(f"{'='*60}")
    print(f"  ✅ PASS:            {passed:>3}  ({passed/total*100:.0f}%)")
    print(f"  ❌ FAIL:            {failed:>3}  ({failed/total*100:.0f}%)")
    print(f"  ⚠️  ERROR:          {errors:>3}  ({errors/total*100:.0f}%)")
    print(f"{'='*60}")

    print(f"\n  Most Common Gaps:")
    for name, cnt in gap_counter.most_common(8):
        bar = "█" * cnt + "░" * max(0, 10 - cnt)
        print(f"    {bar}  {name:<25s}  {cnt:>2}  ({cnt/total*100:.0f}%)")

    print(f"\n  Network Distribution:")
    for net, cnt in networks.most_common(8):
        bar = "█" * cnt + "░" * max(0, 10 - cnt)
        print(f"    {bar}  {net:<25s}  {cnt:>2}")

    print(f"\n  Non-conformant Endpoints:")
    for r in results:
        if r.overall_status not in ("PASS",):
            non_pass = [c for c in r.checks if c.status not in ("PASS", "")]
            reasons = "; ".join(f"{c.check_name}: {c.message[:70]}" for c in non_pass[:4])
            icon = "❌" if r.overall_status in ("FAIL", "CRITICAL_FAIL") else "⚠️"
            print(f"    {icon} {r.target_url}")
            print(f"       {reasons}")

    print()


async def main():
    input_file = "endpoints_to_audit.txt"
    urls = read_urls_from_file(input_file)
    print(f"Read {len(urls)} URLs from {input_file}", file=sys.stderr)

    print(f"Running parallel audit (10 workers)...", file=sys.stderr)
    results = await run_multi_audit(urls, parallel=10, timeout=15.0)

    print(f"Writing results...", file=sys.stderr)
    write_json(results, "audit_results.json")
    gen_detailed_csv(results, "audit_results.csv")
    gen_detailed_html(results, "audit_results.html")

    print(f"\nFiles generated:")
    print(f"  audit_results.json   — raw data (for dashboard)")
    print(f"  audit_results.csv    — table (for analysis)")
    print(f"  audit_results.html   — visual report (for humans)")

    print_detailed_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
