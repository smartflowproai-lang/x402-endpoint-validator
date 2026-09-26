# 402 requirements channel: methodology

Where servers answering HTTP 402 put their x402 payment requirements: in a header, in the body,
in both, or nowhere our parser can read. Published by SmartFlow Observatory (smartflowproai.com).
Author: Tom Smart.

Figures in this document describe one reading: the catalog scanner's daily pass of 2026-09-25.
They are not a trend and not constants, and they are not refreshed automatically.

## What it measures

For every catalog entry (one URL) that answered HTTP 402 in the scanner's last full daily pass,
the channel in which the server gives its payment requirements:

- header only: the requirements arrive in a header (`PAYMENT-REQUIRED`, `X-PAYMENT-REQUIRED` or
  `WWW-Authenticate`) and the body carries none;
- body only: the requirements sit in a JSON body (v1 or v2 shape) and no header carries them;
- both: header and body;
- none: the scanner's parser found no requirements on either side.

The result is an interval per category. The floor counts the classes that are resolved; the
ceiling adds the unresolved classes compatible with that category. The unit is the catalog
entry. It is not a host, not an operator and not a service: a host with thousands of URLs
weighs in proportion to its URL count.

It measures what servers send, not what clients read. The question came up in the x402 channel
of the CDP Discord on 2026-09-24, where a builder reported that agent tooling on the older
`x402-fetch` reads the requirements from the 402 body, where v1 puts them, so a server that
sends only the v2 header gets no payment from those clients. That report was not checked here:
whether a given `x402-fetch` version reads only the body is outside this measurement.

## Data and window

- Source: the catalog scanner's SQLite database, table `endpoints` (current state, overwritten
  at every probe), with `endpoint_history` used to check the window. Read-only
  (`sqlite3 -readonly`); no new probes were sent for this measurement.
- Catalog entries come from public registries: the x402scan crawl, `.well-known` discovery, the
  CDP Bazaar and 402index.
- `endpoints` holds no single snapshot. The scanner works through the scannable set (entries
  with at most five consecutive failures) in about one day. Every scannable entry was last
  probed between 01:55 and 15:45 UTC on 2026-09-25, so that window is the last full reading.
- Denominator: entries in the scannable set whose last probe returned HTTP 402, 21,080 entries.
  402 rows from entries that stopped answering (more than five consecutive failures) date from
  April and May 2026. They are old state, not a reading, and are excluded.
- The probe: GET first; after a 401 or 405, or when the entry declares POST, a POST with a `{}`
  JSON body (`Content-Type: application/json`). No payment header is sent. For entries without
  a declared method the scanner also tries helper paths and stores the first 402 under the
  entry's URL.

## Classification rule

What the scanner keeps. It does not store response headers or the raw 402 body. Its parser reads
the payload from the header first and takes the body only when the body scores better; at a
tie the header wins, because it is scored first under a strict comparison. Only the winning
payload is stored (`raw_accepts`, cut at 2,000 characters), so the other side of the response
is lost. Two traces of the body survive: `response_shape_hash`, a hash of the body's JSON key
paths (NULL when the body is not JSON), and `response_size_bytes`. Comparing the body's hash
with the hash of the winning payload tells which side won, without a new probe.

Notation: `sh` is `response_shape_hash`; `EMPTY` is `e3b0c44298fc1c14`, the hash of an empty
key list (`{}`, `[]` or a scalar); `P` is the winning payload (`raw_accepts`); `R` is the set of
key-path hashes of every stored payload with a non-empty `accepts` (or `paymentRequirements`)
list of objects, taken from the whole table, any period, any channel.

Per row:

1. `payment_required_valid = 0` gives class 4, none.
2. `sh IS NULL` or `sh = EMPTY` gives class 1, header only. Requirements exist and the body does
   not carry them, so they came from a header.
3. `P` parses as JSON. If `keyhash(P) = sh`, class 2: body certain (the winner is the body, or a
   header identical to the body). Otherwise the winner is not the body and the header is
   certain; then `sh` in `R` gives class 3, both, and anything else gives class 1b (header
   certain, JSON body without a recognised requirements shape).
4. `P` was cut and does not parse. If `response_size_bytes < 1000`, the winner cannot have come
   from the body (assuming a body under 1,000 bytes stays under 2,000 characters once
   serialised; see limit 9), so the header is certain and the `R` test of step 3 decides
   between class 3 and 1b. Otherwise
   `sh` in `R` gives class 2b (body with requirements, header unknown), and anything else gives
   class 5, undetermined.

`keyhash` is a copy of the production scanner's `compute_response_shape_hash`: sorted key paths,
only the first element of each list, SHA-256, first 16 hex characters.

How classes map onto the four categories:

| Class | Counts toward |
|---|---|
| 1 | header only (certain) |
| 1b | header only, or both |
| 3 | both (certain, but see limit 6) |
| 2 | body only, or both with an identical payload |
| 2b | body only, or both |
| 5 | header only, both or body only |
| 4 | none |

The floor of a category is its certain class; the ceiling adds every class that may belong to
it.

## SQL

The five queries and the classifier below are the ones that produced the figures in this
document. Labels and comments are translated from the working copy; the logic is unchanged.

Columns used: in `endpoints`, `status` (HTTP status of the last probe), `consecutive_fails`,
`last_scanned_at`, `provider_inferred` (host of the entry's URL), `payment_required_valid`
(1 when the parser found valid payment requirements), `raw_accepts`, `response_shape_hash` and
`response_size_bytes`; `scan_runs` is the scanner's run log.

What each query does:

- Q1 checks the read window: how many entries are scannable and the first and last probe time
  among them, then lists the latest scanner runs.
- Q2 counts the denominator (current 402s in the scannable set) and its hosts, and separately
  the stale 402 rows excluded from it.
- Q3 gives the size and share of the largest host in the denominator, without its name.
- Q4 settles in plain SQL the two classes that need no hash comparison, 1 (header only) and
  4 (none), and counts the rest.
- Q5 extracts the rows the classifier needs: the denominator (flag `cur = 1`) plus every other
  row with a stored payload, which builds the shape dictionary `R`.
- The classifier reads Q5 as JSON on stdin and prints aggregates only: counts per class and per
  detail (payload version, or the body's shape), the same without the largest host, and the
  largest host's share within each class.

```sql
-- 402-requirements-channel.sql. Run read-only: sqlite3 -readonly mapper.db < 402-requirements-channel.sql
.headers on
.mode column

-- Q1. Read window: was the scannable set covered in full, and when
SELECT COUNT(*)                                       AS scannable,
       MIN(last_scanned_at)                           AS first_scan,
       MAX(last_scanned_at)                           AS last_scan
FROM endpoints
WHERE consecutive_fails IS NULL OR consecutive_fails <= 5;

SELECT run_id, started_at, completed_at, total_endpoints, live_402, notes
FROM scan_runs ORDER BY started_at DESC LIMIT 4;

-- Q2. Denominator: current 402s in the read window; stale 402s, excluded from it, counted separately
SELECT COUNT(*) AS denominator_402, COUNT(DISTINCT lower(provider_inferred)) AS hosts,
       MIN(last_scanned_at) AS first_scan, MAX(last_scanned_at) AS last_scan
FROM endpoints
WHERE status = 402 AND (consecutive_fails IS NULL OR consecutive_fails <= 5);

SELECT COUNT(*) AS excluded_stale_402, MIN(last_scanned_at), MAX(last_scanned_at)
FROM endpoints
WHERE status = 402 AND consecutive_fails > 5;

-- Q3. Concentration: share of the largest host (the name is not reported when under 20%)
WITH d AS (SELECT lower(provider_inferred) h FROM endpoints
           WHERE status = 402 AND (consecutive_fails IS NULL OR consecutive_fails <= 5))
SELECT COUNT(*) AS n_top1,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM d), 2) AS pct_top1
FROM d GROUP BY h ORDER BY n_top1 DESC LIMIT 1;

-- Q4. Classes decidable in plain SQL (1 = header only, 4 = none); the rest needs the hash (Q5 + script)
SELECT CASE
         WHEN payment_required_valid = 0 THEN '4_none'
         WHEN response_shape_hash IS NULL
           OR response_shape_hash = 'e3b0c44298fc1c14' THEN '1_header_only'
         ELSE 'needs_hash_classification'
       END AS class,
       COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM endpoints
WHERE status = 402 AND (consecutive_fails IS NULL OR consecutive_fails <= 5)
GROUP BY 1 ORDER BY 1;

-- Q5. Extract for the classifier (JSON on the script's stdin; nothing is written to disk):
--   sqlite3 -readonly -json mapper.db "<Q5>" | python3 classify.py
-- cur = 1 marks a row in the denominator; the other rows with raw_accepts build the shape dictionary R.
SELECT lower(provider_inferred)                                        AS h,
       response_shape_hash,
       raw_accepts,
       payment_required_valid,
       response_size_bytes,
       (status = 402 AND (consecutive_fails IS NULL OR consecutive_fails <= 5)) AS cur
FROM endpoints
WHERE raw_accepts IS NOT NULL
   OR (status = 402 AND (consecutive_fails IS NULL OR consecutive_fails <= 5));
```

```python
#!/usr/bin/env python3
"""402 requirements channel, from the stored state of `endpoints` (no probes). Aggregates only on stdout.
stdin: JSON (sqlite3 -readonly -json) of every row with raw_accepts (shape dictionary R)
       + flag cur=1 for the denominator (current 402s, scannable)."""
import sys, json, hashlib, collections, re

EMPTY = hashlib.sha256(b"").hexdigest()[:16]

def keyhash(obj):  # 1:1 copy of the scanner's compute_response_shape_hash
    def ek(o, p=""):
        ks = []
        if isinstance(o, dict):
            for k in sorted(o.keys()):
                f = f"{p}.{k}" if p else k
                ks.append(f); ks.extend(ek(o[k], f))
        elif isinstance(o, list) and o:
            ks.extend(ek(o[0], f"{p}[]"))
        return ks
    return hashlib.sha256("|".join(ek(obj)).encode()).hexdigest()[:16]

def ver(raw):
    m = re.search(r'"x402Version": (\d)', raw or "")
    return {"1": "v1", "2": "v2"}.get(m.group(1), "other") if m else "no_version"

def has_req(o):
    if not isinstance(o, dict):
        return False
    for k in ("accepts", "paymentRequirements"):
        v = o.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return True
    return False

rows = json.load(sys.stdin)
# R: shapes (hash of key paths) of known payloads carrying requirements -> version
R = collections.defaultdict(collections.Counter)
for r in rows:
    try:
        o = json.loads(r["raw_accepts"])
    except Exception:
        continue
    if has_req(o):
        a0 = (o.get("accepts") or o.get("paymentRequirements"))[0]
        shape = ("v1-shape" if "maxAmountRequired" in a0 else
                 "v2-shape" if "amount" in a0 else "other-shape")
        R[keyhash(o)][shape] += 1

def classify(r):
    sh, raw, valid, sz = r["response_shape_hash"], r["raw_accepts"], r["payment_required_valid"], r["response_size_bytes"]
    body_json = sh is not None and sh != EMPTY
    body_req = body_json and sh in R
    bver = (R[sh].most_common(1)[0][0] if body_req else "-")
    if not valid:
        return ("4_none", "JSON body with requirements?!" if body_req else "-")
    if not body_json:
        return ("1_header_only", "hdr " + ver(raw))
    try:
        o = json.loads(raw); trunc = False
    except Exception:
        o = None; trunc = True
    if o is not None:
        header_won = keyhash(o) != sh
    elif sz is not None and sz < 1000:      # a payload cut at 2000 chars cannot come from a body under 1000 B
        header_won = True
    else:
        header_won = None
    if header_won is True:
        if body_req:
            return ("3_both", f"hdr {ver(raw)} / body {bver}")
        return ("1b_header_body_json_without_requirements_shape", "hdr " + ver(raw))
    if header_won is False:
        return ("2_body_certain_header_unknown", "body " + ver(raw))
    # truncated, large body: the winner's channel is unknown
    if body_req:
        return ("2b_body_with_requirements_header_unknown", "body " + bver)
    return ("5_undetermined", ver(raw))

cur = [r for r in rows if r["cur"] == 1]
top = collections.Counter(r["h"] for r in cur).most_common(1)[0][0]
print(f"R: {len(R)} payload shapes carrying requirements")
for label, sub in (("ALL", cur), ("WITHOUT_TOP1_HOST", [r for r in cur if r["h"] != top])):
    n = len(sub)
    c = collections.Counter(classify(r) for r in sub)
    cat = collections.Counter()
    for (k, _), v in c.items():
        cat[k] += v
    print(f"== {label} n={n}")
    for k, v in sorted(cat.items()):
        print(f"  {k:46s} {v:6d} {100*v/n:6.2f}%")
        for (k2, d), v2 in sorted(c.items()):
            if k2 == k:
                print(f"      {d:32s} {v2:6d} {100*v2/n:6.2f}%")
print("== concentration by class (ALL): class | hosts | top1 host share within class")
byc = collections.defaultdict(collections.Counter)
for r in cur:
    byc[classify(r)[0]][r["h"]] += 1
for k in sorted(byc):
    hc = byc[k]; n = sum(hc.values())
    print(f"  {k:46s} hosts={len(hc):5d} top1={100*hc.most_common(1)[0][1]/n:6.2f}%")
```

## Results

Reading of the scanner's daily pass of 2026-09-25. The paragraph below is the reference
wording; a shorter quote keeps every figure and every caveat in it.

In the scanner's daily pass of 2026-09-25, at least 39.7% of catalog entries answering 402 give
the payment requirements only in the header (v2 payload), and at least 10.2% have a v1 shape in
the body. We count catalog entries, not services: nearly half of the header-only entries belong
to one host, and with equal weight for every host the share is 32 to 67% instead of 40 to 74%.
The scanner records neither the header name nor the path at which the 402 came back, and nearly
40% of the challenges were obtained with a POST, so the number says where servers put the
requirements, not what a given client will see.

Concentration. 21.87% of the denominator sits under one registrable domain, vercel.app. It is a
hosting platform spread over many hosts, not a single host or operator. We name it because it
is above the 20% line at which we name any single entity in a denominator; the largest single
host is below that line and is not named.

### Classification counts

| Class | Entries | % of 21,080 |
|---|---:|---:|
| 1 header only: body of 0 to 4 bytes (empty, `{}`, `[]`, `null`); 8,370 carry `x402Version: 2`, 2 carry no version field | 8,372 | 39.72 |
| 1b header certain, JSON body without a recognised requirements shape | 2,904 | 13.78 |
| 3 header certain, body with a requirements shape | 2,090 | 9.91 |
| of which the body has the v1 shape | 2,011 | 9.54 |
| of which the body has the v2 shape | 79 | 0.37 |
| 2 body certain, header unknown | 887 | 4.21 |
| of which `x402Version: 1` | 136 | 0.65 |
| of which `x402Version: 2` | 751 | 3.56 |
| 2b body with requirements (payload cut), header unknown | 2 | 0.01 |
| 5 undetermined (payload cut, body of 1,000 bytes or more) | 4,354 | 20.65 |
| 4 none (the parser found no requirements) | 2,471 | 11.72 |
| Total | 21,080 | 100.00 |

These are classification counts, not quotable shares. Class 3 is a weak floor for "both": the
shape dictionary is blind by construction to the bodies of servers that send both (limit 6),
so its share must not be quoted as the share of dual-channel entries. No entry can be classed
"body only" with certainty, because the scanner never records that a header was absent; a
body-only floor of zero is a property of the record, not a finding. Quote the paragraph above.

How the 10.2% is built: class 3 entries whose body has the v1 shape (`maxAmountRequired` in the
first `accepts` item), 9.54%, plus class 2 entries whose payload carries `x402Version: 1`,
0.65%. In class 2 the stored payload is the body itself, so its version field is read
directly. It is a floor: a v1 body whose exact shape never won anywhere in the table lands in
1b or 5.

## Limits and assumptions

1. The unit is the catalog entry. Hosts with thousands of URLs weigh in proportion: nearly half
   of the header-only entries sit on one host, and with equal weight for every host the
   header-only interval is 32 to 67%. Weighting by registrable domain, or by payout address as
   a stand-in for the operator, moves the interval again. No weighting is the true one, which
   is why the entry-weighted and host-weighted intervals travel together.
2. The probe is GET, and after a 401 or 405, or when the entry declares POST, a POST with a
   `{}` JSON body. Nearly 40% of the challenges came from a POST. Header only is far more
   common among POST challenges than among GET challenges, most likely because of which hosts
   need a POST rather than because of the method; not resolved. A client sending GET may never
   see a response counted here.
3. For entries without a declared method the scanner tries helper paths and stores the first
   402 under the entry's URL. The path is not stored, so some 402s come from a path next to the
   entry rather than from the entry. The red-team pass found a small share of rows whose
   payload points at such a path; that is a floor, because cut payloads cannot be read.
4. "None" means none according to the scanner's parser. Almost all of these entries return a
   short `text/plain` body mentioning payment, with no base64 and no x402 fields: another
   protocol, or an x402 header the parser does not recognise. Not resolved, because header
   presence is not recorded.
5. Class 1 treats a non-JSON body as carrying no requirements, so a body that is itself base64
   JSON, or HTML with JSON inside, would be misfiled as header only. No row in the denominator
   has that signature (valid requirements, no body hash, non-empty body): class 1 consists of
   bodies of 0 to 4 bytes. The label is broader than the content; the floor is not affected.
6. The shape dictionary `R` is sufficient, not necessary, and blind by construction to
   dual-channel bodies. At a scoring tie the header wins, so the body of a server that sends
   both is never stored as the winner, and its shape enters `R` only if the same shape won
   somewhere else. Such bodies land in 1b instead of 3. The floor for "both" is therefore weak
   and is not quoted; the "both" ceiling already includes 1b.
7. A header identical to the body is invisible: both sides hash the same, so class 2 holds
   "body only" and "both with an identical payload" together. A server that mirrors its v2
   `PAYMENT-REQUIRED` payload key for key in the body, a third pattern reported in the CDP
   channel after the first figures went out, lands in class 2 next to body-only servers. If the
   mirrored body adds keys (an error message, for example), the class depends on which side
   the parser keeps: 2 if it keeps the body, 3 or 1b if it keeps the header.
8. The header name is not recorded: `PAYMENT-REQUIRED`, `X-PAYMENT-REQUIRED` and
   `WWW-Authenticate` land in the same field. `x402Version: 2` in the payload points to
   `PAYMENT-REQUIRED` but does not prove it, and the parser also accepts a parametric
   `WWW-Authenticate` from another protocol when it carries an amount, a currency and a
   recipient. The version is read from the payload, not from the header name.
9. The 1,000-byte rule assumes that a body under 1,000 bytes stays under 2,000 characters once
   serialised. A body with many non-ASCII characters (escaped as `\u` sequences) could break
   it; in this pass the ratio of payload length to body size stays far below the break point.
   It does not touch the header-only floor.
10. The stored payload is cut at 2,000 characters, which leaves class 5 (20.65%) undetermined.
    The header-only ceiling cannot be narrowed without a parser change.
11. One reading, one day. The history table does not keep payloads, so there is no trend.
    Against the previous day's pass, almost every class 1 and class 4 entry kept its class.
12. Client behaviour (`x402-fetch` or any other client) was not tested. This measures only what
    servers send.

## How to break this

Ten ways, from the red-team pass, ordered by severity.

1. "You count URLs, not services." Correct, and the most serious objection for anyone quoting
   the figure. One host holds nearly half of the header-only entries. With equal weight for
   every host the header-only interval is 32 to 67% instead of 40 to 74%, and weighting by
   registrable domain or by payout address moves it again. That is why the quoted wording
   names the unit and carries both intervals.
2. "Your POST probe is not what clients send." Nearly 40% of the denominator answered 402 to a
   POST with a `{}` JSON body. Header only is far more common among POST challenges than among
   GET ones. Most likely host mix rather than method; not resolved. Hence "where servers put the
   requirements, not what a given client will see".
3. "You don't know which header." True. The three header names land in one field. A version 2
   payload points to `PAYMENT-REQUIRED` without proving it, and a parametric `WWW-Authenticate`
   from another protocol can pass as x402. For a question about clients (does this client read
   the v2 header), this is a gap in meaning, not in the count.
4. "Your shape dictionary misses dual-channel bodies." True by construction (limit 6).
   Synthetic cases with a v2 body plus extra fields, or with `accepts` as an object instead of
   a list, land in 1b instead of 3. This weakens the floor for "both", which is why that floor
   is not quoted. The header-only floor does not change.
5. "Truncation hides a fifth of the denominator." It does: class 5 is 20.65%, every row in it
   has a payload cut at exactly 2,000 characters, and closing the cut JSON settles almost none
   of them. The ceiling of 74% cannot narrow until the parser records which side won.
6. "The 402 may come from a helper path, not from the entry." It can: a synthetic entry whose
   URL returns 200 and whose helper path returns 402 is recorded as a 402 under the entry's
   URL. The data show at least a small share of such rows; the true share is unknown.
7. "Non-ASCII bodies break the 1,000-byte rule." A synthetic v1 body with Cyrillic text crosses
   2,000 characters once serialised and lands in "both" instead of "body only". In the data the
   ratio of payload length to body size stays far below what it takes to break the rule, and
   reconstructing cut payloads found no body winner in classes 3 or 1b. Low risk, and not on
   the header-only floor.
8. "'None' hides x402 the parser cannot read." Possibly. Almost all "none" entries are short
   `text/plain` bodies mentioning payment, without base64 or x402 fields. Another protocol, or
   an x402 header the parser misses: not resolved, because header presence is not stored. It
   does not move the header-only figure.
9. "A base64 or HTML body with requirements would be read as header only." It would, and
   synthetic cases confirm it. The signature (valid requirements, no body hash, non-empty body)
   has no rows in the denominator, so the floor holds.
10. "A reading built from an overwritten table is not a snapshot." Against the previous day's
    pass almost every class 1 and class 4 entry kept its class, and the flows between classes
    are small. This objection failed.

Three tests that would overturn the header-only floor:

1. Synthetic responses through the production parser. The first set (v2 header with an empty
   body; with `{}`; v1 in the body only; v2 header with a v1 body; v2 header with an identical
   v2 body; v2 header with an error body; HTML without requirements) all landed in the expected
   class, including the blindness described in limit 7. The red team's new edge cases mostly
   landed in the wrong class, and most of their signatures are absent or rare in this pass. The
   real risks are those in limits 6 and 9, which sit outside the header-only floor, and helper
   paths (limit 3), which can touch it. To break the floor, find rows in the denominator with
   those signatures in numbers that move it.
2. Direct measurement once the parser records both sides of a 402: whether each header was
   present and decodable, whether the body carries a non-empty `accepts` list, the body's
   version and its v1 or v2 fields, and the path that answered. If after one full pass the
   header-only share falls outside 40 to 74% by more than the normal drift between passes, the
   hash inference is wrong.
3. Version consistency. Class 1 assumes the requirements came through a header. None of its
   8,372 rows carries `x402Version: 1` (8,370 carry version 2, 2 carry no version field). A v1
   payload, which v1 places in the body, showing up there would mean the rule confuses
   channels. In class 3, 2,011 of the 2,090 bodies are v1 under a v2 header, different shapes,
   as the rule assumes; identical shapes there would mean `R` catches rows that belong in
   class 2.

## Red-team pass, 2026-09-25

A separate session with fresh context, read-only on the same database state, set out to break
the first internal write-up of this measurement.

- Reproduction: the denominator (21,080), class 1 (8,372) and class 4 (2,471) came out
  identical from the current table and, independently, from the history table (last row per
  URL in the window).
- Findings: the ten ways listed above. High severity, for anyone quoting the figure: the unit
  and the concentration (1). Medium: the POST probe (2), the header name (3), the shape
  dictionary (4), truncation (5). Low to medium: helper paths (6). Low: the 1,000-byte rule
  (7), "none" (8), non-JSON bodies (9), the overwritten table (10).
- Every hole can be closed by a parser change or by re-weighting, without new requests.
- Verdict: publishable after correction. The first internal wording described the entries as if
  each were a service and stated the floor for "both" as a finding. The quoted paragraph names
  the unit, adds the host-weighted interval, the POST share and the missing header name and
  path, and drops the floors for "both" and "body only".
- Planned before version 2 of this measurement: the parser records, for each 402, whether
  `PAYMENT-REQUIRED`, `X-PAYMENT-REQUIRED` or an x402 `WWW-Authenticate` was present, whether
  the body carries a non-empty `accepts` list, the body's version and v1 or v2 fields, and the
  path that answered.

## Contact

info@smartflowproai.com. check the numbers. especially mine.

## Revision history

- **v1** (2026-09-26)
  - First public version. Figures from the scanner's daily pass of 2026-09-25, reproduced from
    the database and checked by a fresh-context red-team pass the same day.
