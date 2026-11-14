# Builder code declared in the Bazaar list vs code `a` in CDP settlement calldata (per receiver), and `a` vs `s` per settlement — method note

Status: version 3.1, 13 November 2026, evening. The fresh week W7b (6–12 Nov) turned out to have an incomplete first day (see "Fresh week W7b, 6–12 Nov: incomplete"); W7b numbers are not for headlines. Earlier: v3 of 13 November 2026 (adds W7b); v2 of 12 November 2026 (after a fresh-context hostile read with an independent recount and a first-party re-read by a separate run); measurement of 10 November 2026 plus the `a` × `s` table of 12 November 2026. Details under Revision history.

- Parent note: `erc8021-attribution-census-2026-11.en.md` (published together with this note, in the same directory and the same commit; version 3.4) defines the settlement population, the CDP signer list and the suffix parser. This note adds the join with what sellers declare in the list. The parent note explicitly does not measure declarations.
- Spec reference (immovable version): x402-foundation/x402 `docs/extensions/builder-code.mdx` @ `10b2d06b9472` (2026-10-06): `a` = app code, set by the resource server; `s` = service code(s), any party; `w` = wallet code, set by the facilitator; the facilitator reads `a` and `s` from the payment payload and adds `w`; on v1 payloads `a` is omitted. PR #3313 (merged 2026-08-31, description): the resource server rejects v2 payloads where `a` is present but not declared or does not match; "client-only s stays best-effort"; "Spec updated to make the resource server the authority for a".
- First author of the question: sukrutkrdg, x402-foundation/x402 #3045, comment of 2026-08-24T15:26:19Z: on one seller, 12 of 15 settlements carried `a`, exactly those sent by a client that echoed the extension; prediction "`a` present iff `s` present"; question whether the buyer's echo is the only channel for `a`.
- Earlier public cases: MikeyPetrillo, #2704 (2026-06-26): `{a, w}` without `s`, with 59 more of the same pattern; AUTHENSOR, #3299.
- Codes: attribution codes are not printed in this public version; the code that leads the receiver count is called "the leading code" (the parent note calls it code R).

## What it measures

1. Per receiver (unit = `payTo` address, hashed; not a seller, not a company): among receivers of CDP-settled USDC transfers on Base in the 0.0005–5 USDC band during a window, how many (a) are `payTo` addresses of list entries that declare a builder code (`extensions["builder-code"].info.a`), and (b) carry that code in the ERC-8021 suffix of at least one of up to three sampled settlements.
2. Matched base: the same share among receivers that are on the list without any builder-code extension, in the same activity strata (1 · 2–9 · 10–99 · ≥ 100 CDP settlements in the window).
3. Per settlement, declaring receivers only: presence of `a` and of `s` in the suffix (2 × 2 table), and whether `a` equals the declared code.

It does not measure: what a server declares in its live 402 (only what the list shows at the six-hourly reads), whether the buyer's client echoed the extension, the x402 version of the actual payment payload, receivers outside Base, settlements outside CDP or outside the band, or who a code belongs to.

## Data inputs (private) and what is public

- Private: our own six-hourly reads of the public Bazaar discovery list (SQLite, opened read-only), the receiver census of the parent note (sampled settlements per receiver, with parsed suffixes; `payTo` hashed) and our own payment ledger. These are not published.
- Public: the chain (every sampled settlement can be re-read by transaction hash), the specification and reference code at the commits named here, the script names and checksums below, and the result tables in this note.

## Sources and scripts (all read-only)

- List: table of list reads, every query `INDEXED BY idx_bazaar_snapshots_date` with `snapshot_date = ?` (plan printed before the run: `SEARCH … USING INDEX idx_bazaar_snapshots_date (snapshot_date=?)`). Windows: W7 = 29 reads 2026-10-28 03Z to 2026-11-04 03Z (settlement window ends at the 2026-11-03 21Z read); D1 = 6 reads 2026-11-06 21Z to 2026-11-08 03Z.
- Settlements: receiver census of 2026-11-09 (files `calldata-recv-<window>.jsonl`, `listed-hashes-<window>.json`, `recv-<window>.tsv`). W7: 3,228 receivers, 6,242 sampled settlements; D1: 889 receivers, 1,632 sampled settlements. Up to 3 draws per receiver.
- Join: `t3b_join.py` (137 s, 35 list reads, 2,777,053 rows); per-receiver details and summary hold hashed ids only. Second road for the declaring set, meaning the same set computed by separately written code: `e_check.py` (SQLite `json_each` / `json_extract`, population from the `.tsv`, join by `sort | comm -12`).
- `a` × `s` table (2026-11-12 11:3xZ): inline Python over `calldata-recv-<window>.jsonl` restricted to the receiver hashes of the join (`<window>/LAST`); a field counts as present when it is non-empty; counts only, no addresses read out.

## Scripts

The scripts and the database are not public. The checksums were computed on 13 Nov on the copies kept from the runs; agreement with the version of the run day is confirmed only for the K0 copy of `t3b_join.py`, whose first 16 hex characters of the checksum were recorded on its run day (13 Nov); the checksum of the other copy (the 10 Nov join) was computed on 13 Nov; no checksum was recorded on 10 Nov. Internal file names that name an internal role or are not in English are withheld; the checksum still identifies the file. K0 (used below) is a positive control: run before the W7b join, it has to reproduce every number of the 10 Nov summary. K0 is a copy of the 10 Nov join code; it differs from the copy kept from 10 Nov in two of 202 lines (the working directory and a read-only setting on the database connection), hence the two checksums.

| name in this note | file name in the run | role | SHA-256 |
|---|---|---|---|
| `t3b_join.py` | `t3b_join.py` | the copy kept from the 10 Nov join (W7, D1); checksum computed 13 Nov; no checksum was recorded on 10 Nov | `eb02d06e66513aee7767485b7f7f613584c091b65ed6acc5c02417b88db8f83e` |
| `e_check.py` | `e_check.py` | second road for the declaring set, W7 and D1 | `657b169f2c6ee090ef7625005ea5ec8ec7b9ae7d41ecc2c5cd8da1ac2bd76547` |
| inline code of the `a` × `s` table | (no file) | `a` × `s` counts | checksum not recorded |
| `w_label_and_ceiling_check.py` | internal name withheld | `w` label at listed receivers; upper bound by a third route | `25af0edaf98ff9216a742f367a11f93f13c7cde667d2125558eadb5d99c654e5` |
| `block_at.py` | `block_at.py` | window bounds from block timestamps (parent note) | `69b07168947dbaf3910922347d3f563e05315f5067e350f7239af8002f7c2f3c` |
| `receivers_extract_w7b.py` | `receivers_extract_w7b.py` | W7b ledger extraction, read-only; a copy of the 8 Nov extractor with only the output directory, the window, the payer column and a side file of own-activity flags changed | `79bcf4f6c2f315a4e1a259d109e9a13dce4437859322843a614ae5eb7b853b36` |
| `run-fetch.sh` | `run-fetch.sh` | W7b wrapper around `fetch_calldata.py` | `9897b96f40d09537fa4765929d291c58287332fc0bcba8ed9f93af2c1d362014` |
| `fetch_calldata.py` | `fetch_calldata.py` | calldata by transaction hash (parent note) | `060f92bc7ea6e9997cff01d9d83378df13806eab1c96c43a4aad569d53c5150c` |
| `w7b_join.py` | `w7b_join.py` | join, W7b | `6356d8053e318260a785d280393df493745f5cffd2dd00011f8d051cdbdc2bb1` |
| `e_check_w7b.py` | `e_check_w7b.py` | second road for the declaring set, W7b | `4edb4abff1c9b53ab86d4c528d92baf1b8318664cc901cea92ffbcf14881a8ea` |
| `snaps_probe.py` | `snaps_probe.py` | list read probes, W7b | `ea8675c8faec1f272180497a9bf1df60faf8eb1dd9c3fee37854e8bd128c9e03` |
| `t3b_join.py` (K0 copy) | `t3b_join.py` | K0: a copy of the 10 Nov join code (two of 202 lines differ, see above); first 16 hex characters of the checksum equal those recorded on its run day (13 Nov) | `009672e55bf42264a53159407043395c82ab285364a8edfb4c7a2d218524d9f2` |
| `recount_from_definitions.py` | internal name withheld | recount from the definitions, written before reading the join result | `1f32af0aaa323d287c5c1407b51e469aa18d2d29d8b76d2ba1a053b977763e96` |
| `gap_count.py` | internal name withheld | W7b counting run (rows without a sender, late-written rows, signer split) | `29775f2ed383e8e9aa2879ce6d63d86fc768a1b0d50ef50abbd313b65a63cade` |

## Definitions

- `payTo` on the list: any `accepts[]` entry with network `eip155:8453` or `base`, lower-cased, hashed as in `receivers_extract.py`. Declaring `payTo`: at least one list entry with `extensions["builder-code"].info.a` points at it on Base. Entries with the extension but without `info.a` (in practice `info.s` only) are counted separately and are not "declaring".
- List variant used in public numbers: LAST = the last read of the window (W7: 2026-11-04 03Z; D1: 2026-11-08 03Z). The union of all reads and the end-of-window read give the same join results within 1–3 receivers in the denominators.
- `a` on a receiver: at least one of the up to three sampled settlements carries `a`. For receivers with more than three settlements this is a lower bound.

## Results (state as of the runs above)

| | W7 (7 days to 3 Nov) | D1 (1 day, 7 Nov) |
|---|---|---|
| `payTo` declaring a code in the last list read | 84 | 86 |
| of these, receivers in the settlement population | 75 | 37 |
| declaring receivers with `a` on ≥ 1 sampled settlement | 64 of 75 (85.3%) (a floor; at most 70) | 30 of 37 (81.1%) |
| … where `a` is a code other than the declared one | 0 | 0 |
| listed receivers without any declaration, same strata, with `a` | 0 of 1,433 | 0 of 482 |
| sampled settlements at declaring receivers | 183 | 93 |
| … `a` and `s` / `a` without `s` / `s` without `a` / neither | 28 / 115 / 1 / 39 | 15 / 54 / 0 / 24 |
| … settlements with `a` where `a` = declared code | 143 of 143 | 69 of 69 |
| declaring receivers with ≥ 1 settlement carrying `a` and no `s` | 55 of 75 | 24 of 37 |

Whole sampled population for scale (all receivers, not only declaring): W7 6,242 settlements: `a` and `s` 37, `a` without `s` 1,014, `s` without `a` 316, neither 4,875; D1 1,632: 18 / 336 / 91 / 1,187. Most of the `a`-without-`s` mass here belongs to receivers that are not on the list at all (see the parent note), so it says nothing about seller declarations.

Distribution, not only the total: among the 75 declaring receivers of W7, `a` is on every draw at 51, on some draws at 13, on none at 11. Receivers with a complete read (≤ 3 settlements in the window): 31, of which 26 carry `a`.

Floor and ceiling. 64 of 75 is a floor. Of the 11 declaring receivers with no `a`, 5 have one settlement in the window and one sample (complete read, no `a`), 6 have 8, 33, 44, 119, 551 and 1,035 settlements with 3 samples each. So the true count lies between 64 and 70; public wording: "(a floor; at most 70)".

Denominators of the base. 1,433 = listed receivers with no builder-code extension at all (last list read, 4 Nov 03Z); 1,434 = receivers flagged as listed in the census minus the 75 (recount by the reviewer of 12 Nov, a fresh-context review described under Revision history); 1,468 = the union-of-reads variant. Public text uses 1,433 and names the definition.

## Who writes `a` (primary sources, read 2026-11-12)

- Specification `specs/extensions/builder_code.md` @ `1566e13f3dbe`: line 96: when the server declared `builder-code` in `PaymentRequired`, the buyer's client also echoes the server's app code (`a`) (paraphrase); line 148 "Echo server value (via core merge)"; line 171 the facilitator "Reads `a` (app code) and `s` (service codes) from the payment payload extensions"; line 319 "The resource server is the authority for `a`. … MUST reject the payment (`extension_echo_mismatch`) when … `a` is present and does not exactly match".
- Reference TypeScript code @ `da08c7001ccf`: `x402Client.ts` merges the server-declared extensions into the payload without any registration (`mergeExtensions`, "if (!clientExtensions) return serverExtensions"); `builder-code/client.ts` adds only `s`; in `x402ResourceServer.validateExtensions`, validation passes when a buyer's client omits extensions entirely (paraphrase).
- So in the reference SDK the buyer's echo is the channel: a stock client echoes `a` by default and adds its own `s` only when `BuilderCodeClientExtension` is registered (a server may also declare service codes through `declareBuilderCodeExtension(appCode, serviceCodes)`; those are echoed by the core merge like `a`), and the reference server adds nothing: `builderCodeResourceServerExtension` is `{ key }` only, and at settle the server forwards the buyer's payload, enriched only by the scheme-level `enrichSettlementPayload` hook, which touches `payload`, not `extensions` (`x402ResourceServer.ts` lines 1502–1513 @ `da08c7001ccf`).
- The specification file is byte-identical at `1566e13f3dbe` and `da08c7001ccf` (last change 2026-10-06, #3666). Nothing in the specification says a server may write `a` itself; ours does.

`a` without `s` is the normal shape, not a change since August. Base rate: `s` is present in 353 of 6,242 sampled settlements (5.7%). First public case of `{a, w}` without `s`: #2704, 2026-06-26, with 59 more of the same pattern. Receiver-level number for public use: 55 of the 75 declaring receivers have at least one sample with `a` and no `s`.

## First-party data point (one settlement, with a positive control)

Our own resource server (own implementation, CDP facilitator) has declared a builder code since 11 Nov 2026. For x402 v2 payloads it writes `info.a` into the payment payload's builder-code extension itself, unconditionally: a payload without `a` gets the server's code, and a different echoed `a` is rejected (`extension_echo_mismatch`).

| claim | evidence level |
|---|---|
| our own test settlement of 11 Nov ends with `{a: <our code>, w: cdp_facil1}` | read from two RPC servers, two independent decoders: confirmed |
| the server wrote `a` itself | from the deployed code (unconditional for x402 v2 payloads); the request payload of that payment was not logged |
| the buyer sent no extensions | from the code of our test buyer script (payload built without an `extensions` key; file unchanged since 6 Nov); not from a request record |
| one earlier settlement on the same server (6 Nov), before any declaration, ends with `{w: cdp_facil1}` only | read from two RPC servers: confirmed |

A second 6 Nov settlement of ours also carries `w` only, but it went through a different own server speaking x402 v1, so it is not a control for this server. Earlier wording "two settlements on the same rail" was wrong in half.

## Limits and assumptions

- A receiver is an address. One business can use many `payTo` addresses and one `payTo` can serve many hosts; nothing here counts sellers.
- Three draws per receiver: absence of `a` on three draws does not exclude `a` on other settlements, in both groups.
- The list lags the live 402 (per route) and the crawler can miss entries (offset pagination: up to 0.57% of routes in the 3 Nov 21Z read, per the parent note).
- Declaration and `a` co-occur; the measurement does not show that the list entry causes `a` (the same server can add `a` by another channel, and does in our own case).
- W7 and D1 are not independent: 34 of the 37 declaring receivers of D1 are also declaring receivers of W7.
- The `a` × `s` table says what is in calldata, not who put it there. A buyer that skipped the echo, a v1 payload and a facilitator that dropped the field look the same.
- The first-party data point is one settlement on one server through one facilitator.
- Code values are replaced by labels ("the leading code", "our code"), so without them a reader cannot reproduce the claims about specific codes.

## Ways this can be refuted

1. Definition of "`payTo` on the list". With the census definition (column `pay_to` = first `accepts[]`, any network) the denominators move (1,963 vs 1,892 `payTo` at the W7 end read). If a different definition put `a` at a material number of receivers without a declaration, "0 of 1,433" would be a definition artifact. Checked only indirectly: all 64 listed receivers with `a` under the census definition are declaring receivers.
2. Three draws. A receiver without a declaration that carries `a` rarely (one settlement in a hundred) passes as "no `a`". A full read of all settlements of the large base receivers (≥ 100 settlements; 108–110 receivers in W7) could find `a` and refute the zero.
3. Window and composition. 85% (64 of 75; a floor; at most 70 of 75) and 81% stand on 75 and 37 receivers; one large issuer of codes could move the share by several points, and another window can look different. For the `a` × `s` table: a parser that drops `s` when it sits after `a` in the map would manufacture "`a` without `s`"; the parser is the one validated in the parent note on our own settlements, but `s` itself has no first-party positive control yet.
4. Full read (added 12 Nov): a full read of all settlements of the 75 (not three samples) turns the 64 floor into a count and shows whether the 11 receivers without `a` ever carry it.

## Fresh week W7b, 6–12 Nov: incomplete

The gap. W7b is the window of settlements in blocks 53,664,122 (inclusive, 6 Nov 00:00:00Z) to 56,688,122 (exclusive, 13 Nov 00:00:00Z). A counting run of 2026-11-13 17:15–17:16Z (a separate run, read-only, counts only) found 317,645 rows of the window in the band with no sending address recorded, all of them in block-day 6 Nov: 4.38% of the 7,248,315 rows of the window in the band, and 0 on each of 7–12 Nov. The extraction keeps only rows whose sender is in the facilitator table (69 addresses, parent note), so these rows drop out silently. 317,645 is an upper bound on missing legs, not an estimate: the ledger cannot say how many of them were settlements on this route. Rows with a block in the window written after the 8-hour margin (the extraction selects ledger rows by their write time, from one hour before the window to eight hours after it; this margin is a setting of the extraction, described in the parent note): 0 (a completeness check, not a result; checked up to the counting run of 13 Nov, over a range that was not empty; the lower margin was not checked). All legs that the extraction kept were sent by the 20 signer addresses the operator publishes (read 10 Nov, parent note); none were sent by the other 49 addresses in the facilitator table (69 addresses, parent note) (this window's population is defined by the sending address, not by the `w` label used for W7 and D1). The parent note names the 5–6 Nov period without a recorded sender; this window included its last day.

The rule and its effect. A rule written before the result (author's notes, 2026-11-13 17:07Z) set the threshold at more sender-less rows than 5% of the population's legs. The gap is above it, so W7b carries no headline number, every W7b figure is "incomplete", and only two of them are quoted here.

The two numbers (both incomplete). Among the 76 declaring receivers of W7b (list read of 13 Nov 03:00:01Z), 70 carry `a` on at least one of up to three sampled settlements (incomplete; a floor; at most 71). Among listed receivers with no builder-code extension, in the same strata, 0 of 1,298 carry `a` on up to three sampled settlements (incomplete). 65 of these 76 (incomplete window) are the same addresses as declaring receivers of W7 (28 Oct–3 Nov), and 7 Nov, the whole D1 window, lies inside W7b. A control of the read by a second public node on 60 draws of this window came out 60 of 60; it concerns an incomplete window.

Next measurement. Fixed in writing on 2026-11-13 before any number was computed on it: blocks 54,096,122 (inclusive, 7 Nov 00:00Z) to 56,688,122 (exclusive, 13 Nov 00:00Z), same population definition, same list variants. The numbers of the seven-day window that contains these six days have been seen. The extraction script gets a gate before that run: count sender-less rows per block-day of the window and stop if any day is above zero.

The list size, mostly explained by one host leaving. This is a fact about the catalogue, not a W7b result. The 4 Nov 03Z read held 112,200 entries (distinct resource URLs), the 13 Nov 03:00:01Z read 34,078. One host held 77,078 entries on 4 Nov and has 0 entries in 29 of the 29 six-hourly reads from 6 Nov 03:00:02Z to 13 Nov 03:00:01Z. It explains 77,078 of the 78,122-entry difference, not all of it.

Limits added by this window: the settlement side is one extraction from the ledger by the author, which the separate run checked only on files (counts and parser), and a list read outside the :00–:02 minute grid of the six-hourly slots would not have been found.

Ways 1–3 under Ways this can be refuted apply also to the two numbers of the incomplete week.

## Checks that travelled a different road

- Join controls (2026-11-10): hash function equality 1,963 = 1,963; `w` on 6,240 of 6,242; second road for the declaring set 84 → 75 and 86 → 37.
- `a` × `s` table, internal consistency (2026-11-12 11:3xZ): 28 + 115 + 1 + 39 = 183; receivers without `a` = 10 with neither + 1 with `s` only = 11 = 75 − 64.
- Independent recount from the raw files (review of 2026-11-12, fresh context): 75 declaring receivers, 64 with `a`, 0 with another code, 11 with none; 183 samples = 28 / 115 / 1 / 39; 143 of 143 `a` equal to the declared code; base by the census list flag 0 of 1,434 (the note's 1,433 uses the narrower "no builder-code extension at all" definition; the difference of one is explained in the review).
- Parser control (same review): records carrying both `a` and `s` exist (37 in W7, 18 in D1), `s` is always a list, never empty; for 113 of 113 direct calls with `a` and no `s` the calldata length leaves no room for an `s`.
- The `w` label at listed receivers (2026-11-12 ~12:50Z, raw sample file, counts only): the two W7 samples without `w` have no ERC-8021 marker at all and both belong to one receiver that is not on the list (stratum flag 0; 1,509 receivers are listed, 1,719 are not). So at every listed receiver (the 75 and the 1,433) every sample carries `w=cdp_facil1` (183 of 183 at the 75).
- Upper bound by a third route (2026-11-12 ~12:52Z, own code on the raw sample; re-run 2026-11-12 ~13:50Z, same numbers): the 5 / 6 split of the 11 declaring receivers without `a` given under Floor and ceiling.
- W7b controls: K0 passed (`t3b_join.py` reproduces every number of the 10 Nov summary); the old window through the new extraction code reproduces the 8 Nov files line for line, 6,242 lines; the author's recount from the definitions, written before reading the join result, is equal in every number of the join summary. These controls concern an incomplete window.

## Last validated

- 2026-11-10: join run; controls of hash equality, `w` and the second road (Checks that travelled a different road).
- 2026-11-12 11:3xZ: `a` × `s` table and its internal consistency.
- 2026-11-12 ~11:55Z (independent recount), 12:15Z (first-party re-read), ~12:25Z (reference code and specification re-read at source).
- 2026-11-13 ~15:53Z (author's recount), 15:59Z (W7b join by a separate run, K0 pass), 16:06Z (list decomposition by host), 16:44Z (second-node control), 17:16Z (counting run: first day of W7b incomplete).

## Revision history

- Draft v1 (measurement of 2026-11-10, `a` × `s` table of 2026-11-12) → review of 2026-11-12 (fresh context, own code): not ready. Twenty claims: 9 confirmed, 2 wrong, 3 too strong, 6 unresolved (first-party facts and set membership, which the reviewer could not read). Wrong: "that fits #3313" (#3313 is echo validation, it adds no server-side channel) and "whether that is intended, I can't say" (the specification names the buyer's echo as the channel). Too strong: "`a` iff `s` fails now" (`a` without `s` was already public in #2704, same library version) and treating the sample counts 143 and 115 as traffic share. Missing: first authors #2704 and #3299, payer concentration, the 64–70 interval.
- v2 (2026-11-12): who writes `a` re-read at the primary sources; `a` without `s` placed against its base rate; the 64–70 interval and the base denominators added; first-party data point re-read by a separate run, and its earlier wording ("two settlements on the same rail") corrected. A payer table was computed in one run and withheld from public use (no matched base rate, not recounted by a second route).
- Final narrow read of the public text (2026-11-12, same reviewer): ten changed sentences, 8 confirmed at source, 2 too strong; the first-party sentence now says that our own test buyer, whose code sends no extensions, paid it; the `w`-defined population label was checked at the listed receivers (Checks that travelled a different road).
- v3 (2026-11-13): fresh week W7b added with the same code, for a window that ends in the week of publication; nothing in the W7 and D1 results changed.
- v3.1 (2026-11-13 evening): the counting run showed an incomplete first day of W7b; by the rule written before the result, W7b carries no headline number, and the clean window 7–12 Nov was fixed before computing anything on it.
