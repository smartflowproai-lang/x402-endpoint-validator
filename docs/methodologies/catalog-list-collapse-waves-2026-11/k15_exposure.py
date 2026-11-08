#!/usr/bin/env python3
"""K15: exposure-matched base rate for "hosts that never collapsed" (window A).
Reads only run files (ext.json, l24_end.json); no network, no database.
Exposure of a host = number of window-A reads with D >= 200.
Prints aggregates only: no host names, no payTo."""
import json, os, statistics, sys
RUN = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/nightq-1108-wi20/raw/refresh-2026-11-05T095959Z")
ext = json.load(open(os.path.join(RUN, "ext.json")))
A = json.load(open(os.path.join(RUN, "l24_end.json")))["windowA"]
snaps = [s for s in ext["snaps"] if A["first"] <= s <= A["last"]]
assert len(snaps) == A["n_snaps"], (len(snaps), A["n_snaps"])
D = lambda s, h: ext["per"][s].get(h, [0])[0]
hosts = {h for s in snaps for h, v in ext["per"][s].items() if v[0] >= 200}
assert len(hosts) == A["hosts_ge200"], (len(hosts), A["hosts_ge200"])
# collapse per L-24 definition: first read with D < 1% of last value >= 200; re-arm at D >= 200
coll = {}
for h in hosts:
    ref, armed, n = None, False, 0
    for s in snaps:
        d = D(s, h)
        if d >= 200:
            ref, armed = d, True
        elif armed and d < 0.01 * ref:
            n += 1; armed = False
    coll[h] = n
n_events = sum(coll.values())
assert n_events == len(A["events"]), (n_events, len(A["events"]))  # positive control vs rule output
expo = {h: sum(1 for s in snaps if D(s, h) >= 200) for h in hosts}
never = sorted(expo[h] for h in hosts if coll[h] == 0)
col = sorted(expo[h] for h in hosts if coll[h] > 0)
def mmm(x): return f"min {min(x)} / median {statistics.median(x)} / max {max(x)}"
print(f"K15 window A {A['first']} .. {A['last']}: {len(snaps)} reads, population {len(hosts)} hosts, "
      f"collapses {n_events} on {len(col)} hosts (control vs l24_end: PASS)")
print(f"K15 exposure (reads with D>=200) never collapsed n={len(never)}: {mmm(never)}; sorted {never}")
print(f"K15 exposure (reads with D>=200) collapsed n={len(col)}: {mmm(col)}; sorted {col}")
for t in (15, 30):
    tot = [h for h in hosts if expo[h] >= t]
    nv = [h for h in tot if coll[h] == 0]
    print(f"K15 exposure >= {t} reads: never collapsed {len(nv)} of {len(tot)} hosts")
