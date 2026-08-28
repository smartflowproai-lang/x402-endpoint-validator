# x402 Endpoint Validator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![GitHub Action](https://img.shields.io/badge/GitHub_Action-v1-2088FF?logo=githubactions&logoColor=white)](https://github.com/marketplace/actions/x402-endpoint-validator)
[![Maintained 2026](https://img.shields.io/badge/Maintained-2026-brightgreen)](https://github.com/smartflowproai-lang)
[![x402 compatible](https://img.shields.io/badge/x402-compatible-purple)](https://smartflowproai.com)

A CI-native validator for x402 endpoints. Drops into any GitHub workflow, hits your endpoint with a real probe, reads the `402 Payment Required` quote against the x402 spec, and fails the build when a route stops returning a conformant quote or the response budget breaks.

A `/.well-known/x402` manifest defect is a **host-level finding**, not an endpoint failure: it is reported in `summary.manifest_defect_hosts` and per endpoint as `manifest_defect: true`, but it does not fail the build unless you ask for it with `fail-on: 'manifest'`. One broken manifest is one finding, not one finding per endpoint on the host.

If you ship x402 endpoints (paid APIs that quote a price in the `402` body and accept micropayments), this Action is the regression guard you've been writing by hand. Stop paste-curling probes into PR comments. Wire one job, watch the matrix, sleep at night.

---

## Free Tier (no key needed)

Out of the box, the Action runs **5 compliance checks**:
- Reachability — endpoint responds
- `/.well-known/x402` manifest format
- 402 response conformance
- Response time (P95)
- Payment-required behavior

```yaml
- uses: smartflowproai-lang/x402-endpoint-validator@v1.0.1
  with:
    endpoints: |
      https://api.example.com
      https://other.com/api
```

## Paid Tier (with `api-key`)

Get an API key from [hypersub.xyz/s/smartflow-scorecard](https://hypersub.xyz/s/smartflow-scorecard) ($15-$4999/mo).

Unlocks **enhanced intel per endpoint**:
- **Wash detection** — flag operator farms self-routing payments
- **Reputation score** — 0.0–1.0 based on 60-day behavioral history
- **Facilitator classification** — CDP-mediated vs P2P vs other
- **On-chain volume 30d** — USDC throughput tracked from our payments index

```yaml
- uses: smartflowproai-lang/x402-endpoint-validator@v1.0.1
  with:
    endpoints: ${{ github.event.repository.html_url }}
    api-key: ${{ secrets.SMARTFLOW_KEY }}
```

Output now includes `reputation_score`, `wash_flag`, `facilitator_mediated`, `on_chain_volume_30d` per endpoint.

---

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `endpoints` | yes | — | Single URL, inline JSON array (`'["https://a/x","https://b/y"]'`), or a workspace-relative path to a YAML/JSON config file. |
| `threshold-p95` | no | `1000` | P95 response time in milliseconds. Any endpoint above this fails the latency check. |
| `tier` | no | `free` | `free` for public repos. `pro` unlocks webhooks, trend tracking, custom thresholds, private-repo support. |
| `pro-license-key` | no | `''` | Required when `tier=pro`. Issued at smartflowproai.com/atlas. |
| `webhook-url` | no | `''` | Slack or Teams webhook for per-run notifications. Pro tier only. |
| `report-path` | no | `x402-validator-report.json` | Where the JSON report lands inside the workspace. Upload it as an artifact if you want history. |
| `fail-on` | no | `any` | `any` = fail on any endpoint that did not pass. `critical` = fail only on 402 payment-conformance defects. `manifest` = fail only on `/.well-known/x402` defects. `never` = report-only, never fails the workflow. Every mode is a subset of `endpoint.passed`. |
| `probe-method` | no | `auto` | Probe method for the unauthenticated payment-required check: `auto` tries GET then POST; `GET` or `POST` forces one method. |
| `strict-v2` | no | `false` | Opt into the strict-v2 contract: reproducible v2 verdicts, fresh probe timestamping, raw response archive, and body-only legacy placement as a strict failure. |

### Strict-v2 mode

`strict-v2` is wired as an Action input for the issue #1 strict-v2 contract. The
mode is designed for reproducible v2-only verdicts: each strict verdict is based
on a fresh probe, records `probed_at_utc`, archives the raw response used for
the decision, and treats body-only legacy placement as
`failure_class=legacy_placement`. See
`docs/superpowers/specs/2026-07-19-strict-v2-mode-design.md` for the locked
policy before validator enforcement lands.

---

## Outputs

| Name | Description |
|---|---|
| `report-path` | Absolute path to the JSON report inside the runner. Wire to `actions/upload-artifact` for history. |
| `pass-fail` | String `pass` if all endpoints clear thresholds, otherwise `fail`. Use in conditionals. |
| `endpoints-checked` | Integer count of endpoints validated this run. |
| `failures` | Integer count of endpoints with at least one failed check. Drive PR comments off this. |

---

## What gets checked

Each endpoint goes through five layers:

1. **Reachability** — the route answers *something* other than 404/410/5xx to at least one probe method. Liveness is decided by the method that produced the verdict: a `402` from POST proves a POST-only route is alive, so a GET `404` on that same route is not a "dead route".
2. **`/.well-known/x402` manifest** — discoverable, parses as JSON, advertises the same endpoint paths you claim. Host-level finding (see above), fetched once per host per run.
3. **402 conformance** — reads the v2 `PAYMENT-REQUIRED` header first, decodes its base64 `PaymentRequired` object, and validates `accepts[]`. Body JSON remains supported as the legacy placement for v1/body-only endpoints. `exact` is first-class, `network` is declared, the amount is parseable, `asset` and `payTo` are populated, and `resource` echoes the original URL when present.
4. **Response time** — p50/p95/p99 against your declared budget. Fail above `threshold-p95`.
5. **Payment-required behavior** — the endpoint actually returns `402` for unauthenticated probes. By default the probe is automatic: try GET, then POST, and record the method that produced the verdict (no silent `200` with empty body, no `401`, no `403`).

Findings land in the JSON report with a `severity` of `pass`, `info`, or `fail`, the endpoint URL, and a one-line remediation hint.

`info` means **there is nothing to convict here** — it never counts as a failure and never launders into a pass:

| `failure_class` | meaning |
|---|---|
| `free_route` | you declared this route `expect: free` and it answered without a 402 — documented behaviour, not a defect |
| `auth_gated` | `accepts: []` plus a recognised auth extension (`sign-in-with-x`, `siwe`, …): an authentication wall, out of payment-conformance scope |
| `unknown_network` | the `network` namespace is not in the validator's registry (`eip155`, `solana`), so the atomic-amount rule cannot be applied. Unverifiable, not cleared — a merchant cannot switch off the price check by renaming its network |

### Endpoint list format

Entries may be plain URL strings or objects with per-endpoint options:

```yaml
endpoints:
  - url: https://api.example.com/v1/paid          # probed GET then POST
  - url: https://api.example.com/api/place_call
    probe_method: POST                            # POST-only route
  - url: https://api.example.com/v1/discovery
    expect: free                                  # documented free; no 402 expected
```

Entries that do not parse as URLs — a sentence lifted from your docs, for
instance — are **rejected, not scanned**, and listed in
`summary.input_entries_rejected`.

### Strict-v2 contract

When `strict-v2: 'true'` is enforced by the validator, the v2 verdict must come
from a fresh unauthenticated probe with `probed_at_utc` and an archived
`raw_response`. Valid body-only responses remain visible as legacy placement,
but strict mode classifies them as `failure_class=legacy_placement` instead of a
passing v2 result.

The JSON report keeps the compatibility key `checks.body_conformance`, but the v2 path is header-canonical. That check may include:

| Field | Type | Meaning |
|---|---|---|
| `channel` | `header` \| `body` \| `both` | Where the decoded `PaymentRequired` was found. |
| `probe_method` | `GET` \| `POST` | Method whose response produced the verdict. |
| `schemes` | array of strings | Schemes observed in the canonical `accepts[]`. |
| `networks` | array of strings | Networks observed in the canonical `accepts[]`. |
| `failure_class` | string or null | Stable failure reason such as `v2_header_invalid`, `network_format`, or `l402_www_authenticate`. |
| `legacy_placement` | boolean | True when a body-only response passed through the legacy/body path. |
| `channel_mismatch` | boolean | True when header and body both exist but disagree on amount, network, or `payTo`. |
| `channel_mismatch_fields` | array of strings | The mismatched fields: `amount`, `network`, and/or `payTo`. |
| `caip2_in_header` | boolean | True when the canonical header includes CAIP-2 network identifiers. |

If a response only offers an L402/Lightning `WWW-Authenticate` challenge and no decodable JSON `PaymentRequired`, it is reported with the separate `l402_www_authenticate` failure class rather than treated as a passing x402 v2 header response.

---

## Usage examples

### Basic — validate one endpoint on push

```yaml
name: x402 validate
on: [push]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: smartflowproai-lang/x402-endpoint-validator@v1
        with:
          endpoints: 'https://api.yourdomain.com/v1/data'
```

### Advanced — config file, custom threshold, PR comment on failure

```yaml
name: x402 validate
on:
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - id: x402
        uses: smartflowproai-lang/x402-endpoint-validator@v1
        with:
          endpoints: '.github/x402-endpoints.yml'
          threshold-p95: '750'
          fail-on: 'critical'
          report-path: 'x402-report.json'

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: x402-report
          path: x402-report.json

      - name: Comment on PR if failures
        if: steps.x402.outputs.pass-fail == 'fail'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = JSON.parse(fs.readFileSync('x402-report.json', 'utf8'));
            const body = [
              '## x402 validator: ${{ steps.x402.outputs.failures }} failures',
              '',
              'See full report in workflow artifacts.',
              '',
              report.findings.slice(0, 5).map(f => `- **${f.severity}** \`${f.endpoint}\`: ${f.message}`).join('\n')
            ].join('\n');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body
            });
```

Companion config file `.github/x402-endpoints.yml`:

```yaml
endpoints:
  - url: https://api.yourdomain.com/v1/decision
    expected_amount: '0.005'
    expected_token: USDC
    network: base
  - url: https://api.yourdomain.com/v1/quality
    expected_amount: '0.01'
    expected_token: USDC
    network: base
```

### Matrix — validate N endpoints in parallel

```yaml
name: x402 validate (matrix)
on:
  schedule:
    - cron: '0 */6 * * *'   # every six hours
  workflow_dispatch:

jobs:
  validate:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        endpoint:
          - https://api.yourdomain.com/v1/decision
          - https://api.yourdomain.com/v1/quality
          - https://api.yourdomain.com/v1/signals
          - https://api.yourdomain.com/v1/snapshot
    steps:
      - uses: smartflowproai-lang/x402-endpoint-validator@v1
        with:
          endpoints: ${{ matrix.endpoint }}
          threshold-p95: '1000'
          fail-on: 'any'
```

Matrix mode gives you per-endpoint check rows in the GitHub UI, so when one endpoint regresses you see exactly which one without parsing JSON.

---

## Why x402?

x402 is the HTTP-native micropayments protocol introduced by Coinbase in 2025 and under formal, vendor-neutral Linux Foundation governance since July 2026. It revives the long-dormant `402 Payment Required` status code and gives it a real semantic: the server quotes a price in the body, the client (often an AI agent, sometimes a human) settles, the server returns the resource. No API keys, no signup flows, no Stripe webhook plumbing. Just a `402`, a settlement, and a `200`.

The model matters because the consumers of paid APIs are quietly stopping being humans. Agents probe, evaluate, transact, and move on. They don't fill out signup forms. They don't store keys. They read the `402`, decide if the price is worth it, pay, and consume. That's the entire flow, and it scales to millions of micro-transactions in a way that subscription APIs never could.

The trade-off is that x402 endpoints are fragile in subtle ways. Drop a field from the `402` body and 80% of agent clients will silently skip your endpoint instead of erroring loudly. Bump your p95 past the agent's budget and they'll route around you. Forget to keep `/.well-known/x402` in sync after a path rename and discovery breaks for everyone. None of these show up in your normal HTTP monitoring — they're spec-conformance bugs that only matter to clients that read the spec.

This Action is the conformance test. It speaks the spec, probes like a real agent, and tells you when you've drifted. Wire it into CI once and your `402` body stops rotting silently between deploys.

---

## Tiers

**Free** — public-repo defaults. All five validation layers. Single-endpoint or matrix. JSON report. Use it forever, no key required.

**Paid (Mapper API key)** — pass `api-key` to unlock enhanced per-endpoint intel: wash detection, reputation history, facilitator classification, on-chain 30d volume. Tiers run from Insider ($15/mo) up to Enterprise ($4,999/mo). Subscribe at [hypersub.xyz/s/smartflow-scorecard](https://hypersub.xyz/s/smartflow-scorecard).

You never need a key for normal CI conformance. The key exists for teams that want the underlying Mapper telemetry surfaced inline with their validation runs.

---

## Maintainer

Built and maintained by **Tom Smart** ([@TomSmart_ai](https://twitter.com/TomSmart_ai)).

- **Site:** [smartflowproai.com](https://smartflowproai.com)
- **Mapper API:** [smartflowproai.com/catalog](https://smartflowproai.com/catalog) — live index of x402 endpoints across Base + Ethereum.
- **Substack:** [smartflowproai.substack.com](https://smartflowproai.substack.com) — weekly x402 telemetry and methodology notes.
- **GitHub:** [github.com/smartflowproai-lang](https://github.com/smartflowproai-lang)

If you ship x402 endpoints, ping me on X. I keep a running list of endpoints that pass conformance and feature them in the weekly snapshot.

---

## Community + contributing

- **Issues:** [github.com/smartflowproai-lang/x402-endpoint-validator/issues](https://github.com/smartflowproai-lang/x402-endpoint-validator/issues)
- **Discord:** drop into the SmartFlow channel via [smartflowproai.com/discord](https://smartflowproai.com/discord) if you want async support
- **PRs welcome:** see `CONTRIBUTING.md` for the test harness setup. New scheme support (beyond `exact`) is the top contribution area right now.

If you find a real-world x402 endpoint that the validator gets wrong, open an issue with the URL and the response body — those bug reports are the most useful thing you can send.

---

## FAQ

**Does this Action transmit my endpoint URLs anywhere?**
No. It runs inside your GitHub runner, hits your endpoints, and writes the report locally. Pro tier adds an opt-in webhook send (you control the URL).

**Does it actually pay the endpoint?**
No. It performs the unauthenticated probe (the one that triggers `402`) and walks the response. No settlement happens. Your endpoint's price stays untouched.

**Does it support schemes other than `exact`?**
`exact` is first-class. Other schemes are not expanded by the header-channel pass and should be treated as report-only/lower-confidence until dedicated validators land. PRs welcome to expand.

**Will it support Solana / non-EVM networks?**
EVM is shipped. Solana is on the roadmap once the x402 Solana settlement primitive stabilizes. Track issue #1.

**Why Docker?**
So the validator dependency tree (Python + httpx + jsonschema) lives in the image, not in your repo. Pinning is on me.

---

## Contributors

- **Gael Leonardo Chulim Gongora** ([@MSSATANASS](https://github.com/MSSATANASS)) — v2 PAYMENT-REQUIRED header-canonical conformance (#3, #4), strict-v2 mode with the fresh-probe response archive (#1, #5), and the 1,098-endpoint failure triage that shaped the v2 check design. First external contributor to this repo.

## License

MIT © 2026 Tom Smart. See `LICENSE`.

---

*Built on the x402 protocol (introduced 2025; Linux Foundation governance since July 2026). Not affiliated with Coinbase, CDP, or the x402 Foundation — independent maintainer, open-source tooling.*
