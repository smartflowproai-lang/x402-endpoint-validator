# Settled-side daily: methodology

Daily file pairing catalog routes with what a settlement ledger actually saw for their payout
addresses. Published by SmartFlow Observatory (smartflowproai.com). This document is the
`methodology_url` referenced in every line of the file.

Figures in this document describe the file dated 2026-09-20 (as of `2026-09-20T06:00:00Z`) and
serve as a worked example. They are not constants. Each later file ships with a README that
carries its own figures.

## What this measures

For each pair (catalog route, Base payout address) the file reports how many settled USDC
transfer legs in the 0.0005-5 USDC band landed on that address in the 30 days up to T and were
not labeled wash, and the block time of the latest such leg. That is all it measures. It is a
read of on-chain settlement against a catalog snapshot, not a health score, not a liveness
signal and not a revenue statement.

One JSONL line per pair, eight keys in fixed order: `resource_url`, `pay_to`,
`payto_route_count`, `settled_count_30d`, `last_settled_block_time`, `snapshot_date`, `band`,
`methodology_url`. `payto_route_count` is how many distinct catalog routes have a Base leg
pointing at the same payout address in the same snapshot.

## The clock and the window

- T (`snapshot_date`) is 06:00 UTC of the day named in the file. The file is generated about
  two days later: T is the nominal 06:00 UTC run on the generation date minus 48 hours, floored
  to the hour. The file named for 2026-09-20 was generated on 2026-09-22. The delay exists so
  that late data and wash classification for the period can land first; whether
  classification actually reached the end of the window is checked on every run (see the
  classification-lag marker below).
- The window is the half open interval `(T - 30 days, T]`, held internally as 1,296,000 block
  heights ending at the last block at or before T (for the 2026-09-20 file,
  `2026-08-21T06:00:01Z` to `2026-09-20T05:59:59Z`). Once T is fixed, the window is pinned by
  block heights and nothing after T is counted.
- Block time is derived from block height against a fixed chain anchor at a fixed block
  interval, not from our ingest timestamp. The ingest clock runs behind the chain in hourly
  batches (median about 37 minutes for the 2026-09-20 window, measured 2026-09-22), so the
  window does not use it. Some wash rules still do; see Scope and limits.
- The catalog side comes from the newest catalog snapshot at or before T (for the 2026-09-20
  file, `2026-09-20T03:00:01Z`). If the newest snapshot is too old, no file is produced.

## Reading the numbers correctly

- Zero is a measurement, a missing row is not. A pair absent from the file was not measured:
  the route was not in the catalog snapshot, or it has no Base leg. Rendering a missing row as
  zero is a misread.
- Zero is not silence. `settled_count_30d = 0` means nothing survived the wash filter, not
  that nothing arrived. In the 2026-09-20 file, 309 lines on 148 payout addresses were zero.
  Of those, 35 lines (on 28 addresses) had no in-band settlement recorded in our ledger for
  the window; 274 lines (on 120 addresses) had in-band settlements that the wash rules
  excluded in full. The file does not tell these two apart, and it does not carry a wash
  versus clean split. Do not render a zero as "never paid".
- The counts are a small residue. For scale: in the 2026-09-20 window, 1,182,999 of the
  1,240,174 in-band settlements received by the file's payout addresses (95.4%) carried a wash
  label. The counts are the remaining 4.6%, so small changes in classification move them a
  lot.
- A zero after the filter does not predict delisting elsewhere. Other indexes count calls or
  payments without our wash filter, so they can see activity where we count none. A zero here
  is not a forecast that another index will drop the route.
- The counter is wallet-level, not route-level. Payout addresses are shared: in the
  2026-09-20 file 14,221 of the 14,744 lines (96.45%) sit on an address serving more than one
  route. Where `payto_route_count > 1`, "this route earned N" is not a supported claim; "this
  payout address received N in-band settlements" is. One address can also settle for several
  sellers, so it is not a seller-level count either. Summing the column over lines counts a
  shared address once per route, so an address behind a hundred routes shows the same count on all hundred lines; take one value per address. Counted once per address, the file's 1,282 payout addresses
  received 57,175 counted settlements.
- The count is attached to the address, not to the route's history: if a route started
  pointing at this address during the window, the count includes settlements from before it
  did, and if it moved to a new address, the old address's traffic is not carried over.
- The counter is a floor for dual-rail sellers. A seller that also settles on Solana or another network shows only its Base traffic here; one dual-rail seller's own books put more than half of its settlements outside Base.
- The counter is a floor for sellers with busy automated buyers. Two of the rules label exactly the pattern of an agent buying on a schedule: very small payments from a payer that sends a great many transfers in a day, and the same amount from the same payer repeated within a short burst. One seller whose payout address, by its own books, receives nothing but x402 settlements had more than four fifths of its in-band settlements labeled. From the next file, every line also carries the in-band count before the filter, so the labeled share of an address is visible next to the count.
- The counter is a floor. Settlements outside the band are invisible, and the ledger keeps at
  most one transfer per transaction hash, so a transaction carrying several in-band transfers
  is recorded for one of them only. Inside the band it counts every transfer, so it can
  include activity unrelated to x402.
- The ledger reads the chain head without waiting for finality and does not remove transfers
  dropped by a reorganisation. On Base such reorganisations are rare and shallow, so we treat
  the effect as negligible, but a counted settlement is not proof of a finalized one.
- Volume is not reported; the counter counts legs, deliberately.
- Counts are dated. A count belongs to its `snapshot_date`. Labels can be added to
  settlements inside an old window after the file ships, so do not diff counts across files as
  a time series.

## Scope and limits

1. Base mainnet only (`eip155:8453`; catalog legs labeled `base` are read as the same
   network), and only USDC transfer legs from 0.0005 to 5 USDC. Counted in accepts legs
   (distinct route, payout address and network combinations in the catalog snapshot), most of
   the catalog is outside this scope: on the snapshot behind the 2026-09-20 file, 16,521 of
   31,395 legs (52.6%) were on networks we do not index. Counted in routes, very little is
   absent, because most routes also accept on Base: 14,741 of the snapshot's 14,957 routes
   (98.6%) are in the file, and the other 216 have no Base leg. A route that also accepts
   elsewhere is in the file, but its count covers only its Base traffic.
2. "Clean" is a negative definition: a leg counts when it carries no wash label at all. What
   the rules target is described below; how they decide is not published.
3. Labels move counts in one direction. Classification keeps running after a file ships. In
   routine operation labels are only ever added, never removed, and later history can add
   them to settlements inside an old window. Counts for a past date can therefore only move
   down; a manual correction that raises a past count would ship with a note.
4. Some wash rules read the ingest clock. The burst test and the per day activity counts used
   by the rules time payments by our ingest clock, not by block time. Because that clock
   batches hourly, payments spread over much of an hour on chain can be judged one burst and
   excluded, which can take a paid address to zero; a real burst split across two batches can
   also be missed. A fix is planned: those tests move to block time, with a note.
5. Block time assumes a fixed block interval from the anchor. A chain-level deviation from
   that interval would shift `last_settled_block_time` and the window edges. The anchor is not
   re-checked against the chain on every run.

### What the wash rules target

Without thresholds and without the order in which rules are checked, which we do not publish
because publishing them invites shaping against them. The rules label:

- payments from an address to itself;
- repeated payments from one payer to one payee that look automated rather than used;
- very small payments from very high-volume payers;
- circular flows between addresses;
- long-running, very high-volume, very low-value channels on a maintained list, which is
  reviewed periodically.

A settlement carries at most one label, and any label excludes it from the count. The rules
look at a payer's history across the whole ledger, not only the 30 day window, so a label can
depend on activity outside the window. Labels are applied per settlement, not per payer and
payee relationship (see the fourth way to break this measurement).

## How the pipeline protects the numbers

- Determinism, of the code, not the data: before each drop the same date is generated twice
  and the two files must be byte-identical (sha256). Once T is fixed, the code is
  deterministic. The data under a past date is not frozen: labels added later lower counts for
  a date already shipped, so regenerating a past date can produce a different file and a
  different checksum; in routine operation only towards lower counts. A reissued date keeps
  its name and arrives together with a dated note and a new `.sha256`; a file whose digest
  differs from the one we sent, without such a note, is a real signal.
- Independent validation: a separate validator re-derives the pair set twice (once in SQL,
  once by parsing the catalog JSON in Python), recomputes a small sample of rows with
  single-address queries, checks window and date ranges, and re-probes the classification
  frontier on one address. It shares the generator's clean definition and block-time anchor,
  so it catches implementation errors, not definitional ones.
- Classification-lag marker: an unclassified settlement looks clean in our ledger, so lagging
  classification would let tail-of-window wash count. Each run therefore observes a
  classification frontier: the newest block inside the window that carries any wash label,
  across the ten busiest payout addresses. The frontier is observed by us, not reported by the
  classifier. Its gap to the window end sets a flag: `OK`; `LAG_WARN` above half of the 48 hour
  limit; `WINDOW_UNCLASSIFIED` above the limit; `NO_DATA` when no labeled block is found.
  `WINDOW_UNCLASSIFIED` and `NO_DATA` mean no file is produced. For the 2026-09-20 file the flag
  was `OK`, gap 0.0 hours. This shows that at least one of our rules has labeled settlements
  up to the end of the window on the busiest addresses. It does not show that every rule ran,
  nor that every settlement in the window was classified: a settlement reaching the ledger
  after the classifier's last pass would not show, nor would labels added later.
- No file rather than a wrong file: besides the marker, a run publishes nothing when the
  ledger does not yet extend past the end of the window, when the newest catalog snapshot is
  too old, when the share of lines with a non-zero count collapses (the signature of an
  address normalisation regression) or moves sharply against recent runs, or when output
  addresses are not normalised. These checks look at the ledger's head, not at its
  continuity: a block range the ledger skipped inside the window would lower counts without
  stopping the file. Continuity is not checked on every run. A missing file is readable; a
  partial or knowingly wrong one is not.

## Four ways to break this measurement

1. "Your share of rows with a non-zero counter is inflated by shared addresses." Correct
   instinct. In the 2026-09-20 file 96.45% of lines sit on a shared address, so any line-level
   share weights busy shared addresses many times over. That is why `payto_route_count`
   travels in every line and why totals in the README count each payout address once. In the
   2026-09-20 file, 97.9% of lines carry a non-zero count, against 88.5% of payout addresses
   counted once; quote the second when you mean payout addresses; neither is a seller count.
2. "Zero means the route earns nothing." No. Zero means nothing was counted after the wash
   filter, in one band, on one network, in one window. It does not mean nothing arrived: in
   the 2026-09-20 file, 274 of the 309 zero lines sat on addresses that did receive in-band
   settlements in the window, all of them labeled wash, and 35 on addresses with none
   recorded in our ledger. Larger payments, other networks and anything outside the ledger's
   coverage are invisible here, and a zero after our filter does not predict that another
   index will drop the route. The `band` field exists so nobody has to guess the scope from
   context.
3. "48 hours is not enough for classification to settle, so 'clean' is overstated." That is
   what the classification-lag marker checks on every run, with the failure mode set to "no
   file" rather than "wrong file". What it does not catch: a settlement ingested after the
   classifier's last pass, labels added later from new history, and a single rule failing on
   a night while another has labeled up to the window end. Labels added later only lower
   counts for a past date in routine operation, which is why counts are dated and not a time
   series. A change to the rules themselves comes with a note.
4. "Wash leaks through in relationships the classifier only partly labels." Exclusion is per
   settlement, not per relationship: when the classifier labels part of one payer's traffic to
   an address, that payer's unlabeled settlements to it still count. In the 2026-09-20 file,
   16,328 of the 57,175 counted settlements (28.6%, each payout address counted once) sit in
   payer relationships where labeled settlements are the majority. They land on 386 of the
   1,282 payout addresses; five of those payout addresses (recipients, not payers) carry 9,205
   of them (56.4%). The payers are spread out: 2,255 distinct paying addresses, the top five
   carrying 17.2%. By line, 1,840 lines (12.5% of the file) sit on 103 addresses where more
   than half of the count comes from such relationships. There, labeled and unlabeled
   settlements interleave: about half of the unlabeled ones sit close in time to a labeled one
   from the same payer. The labels there come from two rules that by design mark only part of
   a payer's traffic (repeated payments from one payer to one payee that look automated rather
   than used, and very small payments from very high-volume payers). The ledger cannot tell
   whether the unlabeled remainder is wash the rules missed or the labeled part is ordinary
   repeated use; the figure says where that ambiguity sits, not how much wash got through. It
   depends on the cut-off: 7.3% if only relationships at least 90% labeled count, 56.1% if any
   label counts. Dropping majority-labeled relationships entirely would take 32 more payout
   addresses (327 lines) to zero, on top of the 148 addresses (309 lines) already at zero. We
   have not, because relationship-level exclusion would also multiply whatever the labels get
   wrong. We will re-measure this share once the burst test runs on block time, and any change
   of rule will come with a note.

## Contact

info@smartflowproai.com. check the numbers. especially mine.

## Revision history

- **v3** (2026-09-23)
  - Stated as a floor for dual-rail sellers and for sellers with busy automated buyers, with a partner's own books as the worked example; the in-band count before the filter announced for the next file.
  - All figures re-dated to the file of 2026-09-20 and marked as a worked example; later files
    carry their own figures in their README.
  - Zero is no longer described as silence: zero lines are split into "no in-band settlement
    recorded in our ledger" and "all in-band settlements labeled wash", and a zero is stated
    not to predict delisting by another index.
  - New subsection "What the wash rules target", describing the behaviour each rule labels,
    without thresholds, check order or mechanism.
  - New limit: the burst test and per day activity counts read the ingest clock, not block
    time; fix planned.
  - Determinism reworded: the code is deterministic, the data under a past date is not frozen,
    and in routine operation a regenerated past date can only move counts down. A reissued
    date keeps its name and comes with a dated note and a new `.sha256`. The reference to a
    versioned filter was removed (the file carries no filter version).
  - Classification-lag marker described as an observed frontier with its flags; it is stated
    to show that at least one rule labeled up to the window end, not that every rule ran. The
    claim that the reported lag can never be understated was removed.
  - Independent validation described as it is: it shares the generator's clean definition and
    block-time anchor, so it catches implementation errors, not definitional ones.
  - Scope split into accepts legs and routes; ingest lag quantified; the counter is stated as a
    floor because the ledger keeps one transfer per transaction hash; `payto_route_count`
    defined; the wash-labeled share of in-band traffic stated for scale; the count stated as
    attached to the address, not the route's history or a seller; reorganisations and ledger
    continuity stated as unchecked.
  - Added a fourth way to break this measurement: residue in partly labeled payer
    relationships. Section renamed "Four ways to break this measurement".
- Earlier versions carried no revision history.
