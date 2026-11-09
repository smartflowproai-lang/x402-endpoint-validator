# Probe of one host's catalogue routes, 5 November 2026 (x402 issue #3844)

Per-request results behind the probe reported in issue #3844 (5 Nov) and in Weekly #20. One host only (the host discussed in #3844, "C1" in Weekly #20); the control group of other hosts is not included.

## What was sent
- 800 routes of the host, drawn at random (seed 20261105) from three groups defined from my Bazaar reads: `relisted_by_3nov_listed_5nov` (400 of the 40,732 routes that left on 1 Nov and were back by 3 Nov 09:00 UTC, and still listed at 5 Nov 03:00 UTC), `absent_7_reads_listed_5nov` (255) and `absent_7_reads_not_listed_5nov` (145), the last two from the 11,493 routes absent in all seven reads from 2 Nov 03:00 to 3 Nov 15:00 UTC.
- Per route: one GET without payment and one POST with an empty body. 5 Nov 04:04:51 to 04:10:50 UTC, at most 5 requests per second, 4 workers, timeout 10 s, no redirects, no payment headers, one retry after 30 s for transport failures only (none needed). User-Agent: `x402-network-mapper/0.1 (+research; contact: info@smartflowproai.com)`.

## Files
- `probe-3844-2026-11-05-c1-per-request.csv`: 1,600 rows, one per request (800 URLs, GET and POST). Columns: `url`, `group`, `method`, `ts_utc` (request time), `status` (HTTP status), `class` (see below), `server` (response Server header, as sent), `body_1033` (`yes` if the first 240 characters of the body contain "1033"), `ms` (response time).
- `probe-3844-2026-11-05-c1-recheck-0933z.csv`: 20 rows, a GET recheck of 20 URLs from the first group at 09:33:34 UTC. Columns: `url`, `method`, `ts_utc`, `status`, `ms`. The recheck stored the status and timing, not the body; an undocumented Cloudflare flag in the raw file is left out.
- `probe3844.py`: the probe as run (comments in Polish).

## Classes
Keyed on the HTTP status code only: 402 with a PAYMENT-REQUIRED header, `x402Version` or `"accepts"` in the body → `402_x402`, other 402 → `402_other`; 2xx → `2xx`; 3xx → `3xx`; 530 → `530` (checked before the 4xx and 5xx rules); other 4xx → `4xx_other`; other 5xx → `5xx_other`; network failure → `transport`; anything else → `other`. The class does not record who emitted the status: Cloudflare's other edge errors (52x, or its own 502) would fall in `5xx_other` together with origin 5xx, and a 530 sent by an origin would fall in `530`. Edge versus origin is read from the body.

## Result
All 1,600 responses: status 530, class `530`, `body_1033` = `yes`, with the same body prefix on every response:
`{"type":"https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1033/","title":"Error 1033: Cloudflare Tunnel error","status":530,"detail":"The host is configured as a Cloudflare Tunnel, but`
The recheck: 20 of 20 GETs returned 530 (body not stored, so 1033 is not shown for it).

## Not checked
Any route of this host outside the sample; any time outside the two windows above; what a paid request would have returned.
