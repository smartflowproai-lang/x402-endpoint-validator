# Catalogue concentration: method

Status: method note. It reports no results.

## Scope

The catalogue is the public discovery listing that Coinbase serves for x402 resources. I read it every 6 h and store each read as a snapshot. Coinbase's seller guide, as read on 29 October 2026, says a resource leaves the listing after 30 days without a settlement (docs.cdp.coinbase.com/x402/seller/get-discovered). It documents other exits.

A listing is not demand. A listed route says a seller published it and the listing still shows it. Coinbase links staying listed to settlement; I do not know what its field counts as a call.

## Definitions

- Snapshot: all rows stored from one read, keyed by `snapshot_date`, the time the read started.
- Healthy snapshot: duplicate rows, counted as rows minus distinct routes, are below 1 % of distinct routes, and distinct routes are at least 50 % of the median of the 3 previous snapshots. This one-sided form is new in this version. It can reject a real exit of a host that held most of the listing, so query 1b lists every rejected read with the numbers that failed it.
- Route: a distinct `resource_url` within one snapshot.
- Host: `urlsplit(resource_url).hostname`, which Python returns lowercased and without port. A host is not an operator. One operator can run many hosts, and one platform domain can carry many operators.
- Host share: routes of the host divided by all routes in the same snapshot, printed as numerator and denominator.
- Top-N share: routes of the N largest hosts divided by all routes in the same snapshot.
- lastCalledAt age: `snapshot_date` minus `quality.lastCalledAt` in the stored response, in days. Coinbase sets the field and how late it updates. Older reads may lack it.

Every definition here belongs to definition_version 2026-10-30. The internal notes behind them are not public.

## Procedure

The database is opened with `mode=ro`. Step zero builds a table `routes(snapshot_date, resource_url, host)` from the stored rows, host parsed in Python. The parser must report rows whose URL does not parse; this note defines no host for them. END is the `snapshot_date` of the last healthy snapshot, pinned before any count.

The queries are in `catalogue-concentration-2026-10.sql` next to this note: the healthy-snapshot filter and its complement, routes per host at END with numerator and denominator, a histogram of routes per host by order of magnitude, and the series of one host across healthy snapshots with zero where absent.

In the filter, the median runs over all previous reads, healthy or not, and the sort is textual, so all dates must share one format. The SQL in the companion file was run on 30 October 2026 against a 3-day window of my own snapshots.

## What this note does not measure

Demand, payers, payment volume, intent, operators. The axis is routes per host, not calls per route. Resources that were never listed, and the reason any route left, are outside this instrument. A host share is a share of listed routes, not of a market. Payments are measured on the ledger, a separate instrument with its own note. Neither instrument confirms the other.

## How to reproduce

Inputs: your own full paged reads of the discovery listing every 6 h, one row per resource, each row keyed by the read's start time in ISO form with `T` and `Z`. Compare dates as ranges, never with LIKE. The clock is the read time: every age and share is stated "as of" a `snapshot_date`, not the moment of writing. Offset paging on a live listing can drop or repeat rows. The healthy filter rejects reads with many repeats or a collapse in size. It does not detect smaller drops. Every output carries `definition_version: 2026-10-30`. Any definition change gets a new version and a changelog line.

## Rules this note follows

Quoted from my published playbook:

- 1. A share without a denominator is not a measurement.
- 5. Write time is not event time.
- 9. The distribution is the headline, a single statistic is a summary of it.
- 27. Claim and freshness travel as a pair.
- 32. Say plainly what your instrument is not.

## Changelog

- 2026-10-30: first public version.
