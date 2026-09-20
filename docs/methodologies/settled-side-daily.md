# settled-side-daily: methodology

Daily file pairing catalog routes with what a settlement ledger actually saw for their payout
addresses. Published by SmartFlow Observatory (smartflowproai.com). This document is the
`methodology_url` referenced in every line of the file.

## What this measures

For each pair (catalog route, Base payout address) the file reports how many settled USDC
transfer legs in the 0.0005-5 USDC band landed on that address in the 30 days up to T, and the
block time of the latest such leg. That is all it measures. It is a read of on-chain settlement
against a catalog snapshot, not a health score and not a revenue statement.

One JSONL line per pair, eight keys in fixed order: `resource_url`, `pay_to`,
`payto_route_count`, `settled_count_30d`, `last_settled_block_time`, `snapshot_date`, `band`,
`methodology_url`.

## The clock and the window

- T is 06:00 UTC of the day named in the file, chosen with a 48 hour rollback from production
  time. A file named for the 17th is produced on the 19th. The rollback exists so the wash
  classifier has time to catch up with the window; that catch-up is measured on every run, not
  assumed (see the lag marker below).
- The 30 day window is resolved to a block range at 2 seconds per block from an anchored block;
  the anchor method was cross-checked against two independent RPC nodes on 13 blocks (zero
  seconds of drift).
- Catalog side comes from the latest catalog sweep at or before T.

## Reading the numbers correctly

- **Zero is a measurement, a missing row is not.** `settled_count_30d = 0` means the ledger
  watched the band and saw silence. A pair absent from the file means out of scope (for example
  a non-Base accept). Rendering a missing row as zero is a misread.
- **The counter is wallet-level, not route-level.** Payout addresses are shared: in the current
  file 96.95% of rows sit on an address serving more than one route (median `payto_route_count`
  is 67). Where `payto_route_count > 1`, "this route earned N" is not a supported claim; "this
  payout address settled N" is.
- Volume is not reported; the counter counts legs, deliberately.

## Scope and limits

1. Base mainnet only, and only USDC transfer legs from 0.0005 to 5 USDC. At the current
   snapshot, 25,168 of 40,828 catalog accept legs (61.6%) are outside this scope; other
   networks are invisible to this file, and so are payments above or below the band.
2. "Clean" is a negative definition: legs carrying no wash classification. Classification is
   revised over time under a versioned filter; comparisons across files must respect filter
   versions.
3. The block-time clock assumes 2 seconds per block from the anchor; a chain-level deviation
   would shift `last_settled_block_time`.

## How the pipeline protects the numbers

- **Determinism:** two independent runs for the same T must produce byte-identical files
  (verified by sha256) before anything ships. The ledger head moving between runs must not move
  a single measured line.
- **Independent validation:** a validator that deliberately reuses none of the generator's query
  shapes (different JSON parsing, per-address probes, separate block-time arithmetic) re-derives
  the pair set and re-computes sample rows. Current suite: 26 checks across structure, SQL
  agreement, row recomputation, date ranges, and the lag marker.
- **Classification-lag marker (fail-closed):** each run measures how far wash classification
  lags behind the end of the window. Past 48 hours the file is not produced at all: the
  pipeline prefers no file to a silently overstated "clean". The probe measures the frontier on
  a subset of the busiest addresses, so the reported lag can only be overstated, never
  understated: the failure mode is a false alarm, not a false all-clear.

## Three ways to break this measurement

1. **"Your share of rows with a non-zero counter is inflated by shared addresses."** Correct
   instinct, and it is why the row-level share and the address-level share are both published
   (currently 98.1% of rows vs 90.2% of addresses), with the full distribution, and why
   `payto_route_count` travels in every line.
2. **"Zero means the route earns nothing."** No. Zero means silence in one band, on one network,
   in one window. Larger payments, other networks, and anything outside the ledger's coverage
   are invisible here. The `band` field exists so nobody has to guess this from context.
3. **"48 hours is not enough for classification to settle, so 'clean' is overstated."** That is
   exactly what the lag marker checks on every run, with the failure mode set to "no file"
   rather than "wrong file". What the marker does not catch is a retroactive change of the
   filter rules themselves; that is handled by filter versioning, not by the marker.

## Contact

info@smartflowproai.com. check the numbers. especially mine.
