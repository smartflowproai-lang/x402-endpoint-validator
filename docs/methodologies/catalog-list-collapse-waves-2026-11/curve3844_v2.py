#!/usr/bin/env python3
# v2 (3.11 po red teamie): krzywa D + luki jednego odczytu + pierwsze powroty + test „nieobecne we wszystkich odczytach od Sun 09Z”.
# Tylko liczby, zero URL. mapper.db mode=ro + query_only.
import sqlite3, os, sys
DB = os.path.expanduser("~/x402-network-mapper/mapper.db")
END = sys.argv[1] if len(sys.argv) > 1 else "2026-11-03T15:00:59"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
c.execute("PRAGMA query_only=1")
HOST = "%://market.datapackvibe.com/%"
reads = [r[0] for r in c.execute(
    "SELECT DISTINCT snapshot_date FROM bazaar_snapshots WHERE snapshot_date >= '2026-10-31T21:00:00' AND snapshot_date < ? ORDER BY 1", (END,))]
H = {d: {r[0] for r in c.execute("SELECT DISTINCT resource_url FROM bazaar_snapshots WHERE snapshot_date = ? AND resource_url LIKE ?", (d, HOST))} for d in reads}
sat = [d for d in reads if d.startswith("2026-10-31T21")][0]
sun09 = [d for d in reads if d.startswith("2026-11-01T09")][0]
sun21 = [d for d in reads if d.startswith("2026-11-01T21")][0]
S, SUN = H[sat], H[sun21]; D = S - SUN; O = S & SUN
print(f"S={len(S)} SUN={len(SUN)} D={len(D)} O={len(O)}  sun09_host={len(H[sun09])}")
after = [d for d in reads if d > sun21]
seen = set()
for i, d in enumerate(after):
    R = H[d]; listed = D & R; first = listed - seen; seen |= listed
    nxt = H[after[i+1]] if i + 1 < len(after) else None
    o_miss = O - R
    o_miss_back_next = len(o_miss & nxt) if nxt is not None else None
    prv = H[after[i-1]] if i > 0 else H[sun21]
    d_gap = len(((D & prv) - R) & nxt) if (nxt is not None and i > 0) else None   # D: w poprzednim i nastepnym, brak tutaj
    print(f"{d} D_listed={len(listed)} ({100*len(listed)/len(D):.1f}%) D_first={len(first)} O_present={len(O & R)} O_missing={len(o_miss)} O_missing_listed_next={o_miss_back_next} D_one_read_gap={d_gap}")
last, prev = after[-1], after[-2]
new_last = (D & H[last]) - H[prev]
win = [d for d in reads if sun09 <= d <= prev]            # Sun 09Z ... przedostatni odczyt
absent_all = {u for u in new_last if all(u not in H[d] for d in win)}
print(f"D listed at {last} but not at {prev}: {len(new_last)}; of these absent in ALL {len(win)} reads {win[0]}..{win[-1]}: {len(absent_all)}; seen in some read of that window: {len(new_last)-len(absent_all)}")
d_drop_last = (D & H[prev]) - H[last]; o_drop_last = (O & H[prev]) - H[last]
print(f"listed at {prev}, missing at {last}: D {len(d_drop_last)}/{len(D & H[prev])} ({100*len(d_drop_last)/max(1,len(D & H[prev])):.2f}%)  O {len(o_drop_last)}/{len(O & H[prev])} ({100*len(o_drop_last)/max(1,len(O & H[prev])):.2f}%)")
print(f"D never listed in any read after {sun21} (to {last}): {len(D - seen)}; D ever listed after {sun21}: {len(seen)} ({100*len(seen)/len(D):.1f}%)")
print(f"D seen after {sun21}, missing at both {prev} and {last}: {len(seen - H[last] - H[prev])}")
