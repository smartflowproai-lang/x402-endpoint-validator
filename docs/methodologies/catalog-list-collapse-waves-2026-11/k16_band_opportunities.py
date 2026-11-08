#!/usr/bin/env python3
"""K16: collapse opportunities inside vs outside the band of window A (file-only, no network, no DB).
Band = from the read of the first to the read of the last window-A collapse, inclusive.
Opportunity, two variants: (a) host-read of a population host with D >= 200;
(b) host armed entering the read (D >= 200 at some read since its last collapse);
(c) host with D >= 200 in the previous read (the reviewer's R5 definition, 890 vs 1,184).
Prints aggregates only (no host names, no payTo). Positive control: 11 collapses in band / 0 outside."""
import json, os, sys
RUN = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/nightq-1108-wi20/raw/refresh-2026-11-05T095959Z")
ext = json.load(open(os.path.join(RUN, "ext.json")))
A = json.load(open(os.path.join(RUN, "l24_end.json")))["windowA"]
snaps = [s for s in ext["snaps"] if A["first"] <= s <= A["last"]]
assert len(snaps) == A["n_snaps"] == 142
D = lambda s, h: ext["per"][s].get(h, [0])[0]
hosts = {h for s in snaps for h, v in ext["per"][s].items() if v[0] >= 200}
assert len(hosts) == A["hosts_ge200"] == 27
ev_snaps = sorted(e["snap"] for e in A["events"])
b0, b1 = snaps.index(ev_snaps[0]), snaps.index(ev_snaps[-1])
zone = lambda i: "before" if i < b0 else ("band" if i <= b1 else "after")
hr = {"before": 0, "band": 0, "after": 0}; arm = dict(hr); col = dict(hr); nreads = dict(hr)
for i, s in enumerate(snaps): nreads[zone(i)] += 1
pre_band_ge200 = set()
for h in hosts:
    ref, armed = None, False
    for i, s in enumerate(snaps):
        z = zone(i); d = D(s, h)
        if armed: arm[z] += 1
        if d >= 200:
            hr[z] += 1; ref, armed = d, True
            if z == "before": pre_band_ge200.add(h)
        elif armed and d < 0.01 * ref:
            col[z] += 1; armed = False
assert sum(col.values()) == 11
print(f"K16 band: {snaps[b0]} .. {snaps[b1]}; reads before/band/after = {nreads['before']}/{nreads['band']}/{nreads['after']}")
print(f"K16 collapses before/band/after = {col['before']}/{col['band']}/{col['after']} (control: 0/11/0)")
print(f"K16 (a) host-reads D>=200 before/band/after = {hr['before']}/{hr['band']}/{hr['after']}; "
      f"before vs band+after = {hr['before']} vs {hr['band']+hr['after']}; total {sum(hr.values())}")
print(f"K16 (b) armed opportunities before/band/after = {arm['before']}/{arm['band']}/{arm['after']}; "
      f"before vs band+after = {arm['before']} vs {arm['band']+arm['after']}; in band vs outside = {arm['band']} vs {arm['before']+arm['after']}")
prev = {"before": 0, "band": 0, "after": 0}
for i in range(1, len(snaps)):
    prev[zone(i)] += sum(1 for h in hosts if D(snaps[i-1], h) >= 200)
print(f"K16 (c) D>=200 in previous read before/band/after = {prev['before']}/{prev['band']}/{prev['after']}; before vs band+after = {prev['before']} vs {prev['band']+prev['after']}; in band vs outside = {prev['band']} vs {prev['before']+prev['after']}")
print(f"K16 population hosts with D>=200 in at least one read before the band: {len(pre_band_ge200)} of {len(hosts)}")
