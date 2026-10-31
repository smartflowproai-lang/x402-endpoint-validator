-- catalogue-concentration-2026-10.sql
-- Companion to docs/methodologies/catalogue-concentration-2026-10.md
-- definition_version: 2026-10-30. Input: your own 6-hourly paged reads of the
-- discovery listing, one row per resource, keyed by the read's start time
-- (ISO 8601 with T and Z). Compare snapshot_date as a range, never with LIKE.

-- 1. Healthy-snapshot filter. prev_median is the median of the 3 previous reads
--    (sum minus max minus min over a window of exactly 3). The median runs over
--    all previous reads, healthy or not. ORDER BY is textual: one date format.
WITH s AS (
  SELECT snapshot_date, COUNT(*) AS n_rows,
         COUNT(DISTINCT resource_url) AS n_routes
  FROM bazaar_snapshots GROUP BY snapshot_date),
w AS (
  SELECT *, COUNT(n_routes) OVER p AS k,
         SUM(n_routes) OVER p - MAX(n_routes) OVER p - MIN(n_routes) OVER p AS prev_median
  FROM s
  WINDOW p AS (ORDER BY snapshot_date
               ROWS BETWEEN 3 PRECEDING AND CURRENT ROW EXCLUDE CURRENT ROW))
SELECT snapshot_date FROM w
WHERE n_rows - n_routes < 0.01 * n_routes
  AND k = 3 AND n_routes >= 0.5 * prev_median;

-- 1b. Rejected reads: the complement of query 1, with the reason. Reads with fewer
--     than 3 previous reads cannot be evaluated and are listed as such. Nothing is
--     dropped silently: every read is in query 1 or in query 1b.
WITH s AS (
  SELECT snapshot_date, COUNT(*) AS n_rows,
         COUNT(DISTINCT resource_url) AS n_routes
  FROM bazaar_snapshots GROUP BY snapshot_date),
w AS (
  SELECT *, COUNT(n_routes) OVER p AS k,
         SUM(n_routes) OVER p - MAX(n_routes) OVER p - MIN(n_routes) OVER p AS prev_median
  FROM s
  WINDOW p AS (ORDER BY snapshot_date
               ROWS BETWEEN 3 PRECEDING AND CURRENT ROW EXCLUDE CURRENT ROW))
SELECT snapshot_date, n_rows, n_routes, prev_median,
       CASE WHEN k < 3 THEN 'not evaluable (fewer than 3 previous reads)'
            WHEN n_rows - n_routes >= 0.01 * n_routes THEN 'duplicates'
            ELSE 'size' END AS reason
FROM w
WHERE NOT (k = 3 AND n_rows - n_routes < 0.01 * n_routes
           AND n_routes >= 0.5 * prev_median)
ORDER BY snapshot_date;

-- 2. Routes per host at END (:end = snapshot_date of the last healthy read),
--    with numerator and denominator on every row.
--    routes(snapshot_date, resource_url, host) is built in step zero,
--    host = urlsplit(resource_url).hostname parsed outside SQL.
SELECT host, COUNT(DISTINCT resource_url) AS routes,
       (SELECT COUNT(DISTINCT resource_url) FROM routes
        WHERE snapshot_date = :end) AS all_routes
FROM routes WHERE snapshot_date = :end
GROUP BY host ORDER BY routes DESC;
-- Top-N share: the first :n rows of query 2 over all_routes.

-- 3. Histogram of routes per host, by order of magnitude.
SELECT length(CAST(routes AS TEXT)) AS digits, COUNT(*) AS hosts
FROM (SELECT host, COUNT(DISTINCT resource_url) AS routes
      FROM routes WHERE snapshot_date = :end GROUP BY host)
GROUP BY digits ORDER BY digits;

-- 4. Series of one host across healthy reads, zero where absent.
--    healthy(snapshot_date) holds the output of query 1.
SELECT h.snapshot_date,
       COUNT(DISTINCT r.resource_url) AS routes
FROM healthy h
LEFT JOIN routes r
  ON r.snapshot_date = h.snapshot_date AND r.host = :host
GROUP BY h.snapshot_date ORDER BY h.snapshot_date;
