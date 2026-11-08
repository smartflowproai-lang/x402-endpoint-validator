#!/usr/bin/env python3
"""K14 v3 — test okna przesuwnego (24 h / 12 h) z testem rozłącznych payTo + DWIE bazy losowe. Tylko pliki, zero bazy.
Wejście: opcjonalny plik JSON ze zdarzeniami (domyślnie wbudowane 11 zapaści okna A do END 05.11 09Z):
  {"slots_total": 142, "events": {"KOD": "YYYY-MM-DDTHH", ...}, "shared": [["H06","H08","H16"]], "label": "..."}
  slots_total = liczba odczytów okna A (co 6 h); shared = grupy hostów o wspólnym payTo (pary w grupie NIE są rozłączne).
Wyjście: liczba zapaści z towarzyszem o ROZŁĄCZNYM payTo w oknie ±24 h / ±12 h (inkluzywnie i ostro) oraz dwie bazy losowe
(200 000 losowań każda, payTo rozłączne): (1) zdarzenia losowo w slots_total slotach całego okna; (2) zdarzenia losowo w slotach
PASMA od pierwszej do ostatniej zapaści (null warunkowany po danych — dlatego oba). Użycie: python3 k14_window_baseline.py [events.json] [seed]."""
import random, sys, json, itertools
from datetime import datetime
DEFAULT = {"slots_total": 142, "label": "okno A 01.10 03Z - 05.11 09Z (END pakietu S0)",
  "events": {"H07":"2026-10-17T21","C1a":"2026-10-18T15","H20":"2026-10-19T03","H18":"2026-10-26T03","H12":"2026-10-28T15",
             "H23":"2026-10-28T15","H03":"2026-10-29T09","H06":"2026-10-31T09","H08":"2026-10-31T15","H16":"2026-10-31T21","C1b":"2026-11-01T09"},
  "shared": [["H06","H08","H16"]]}
args = [a for a in sys.argv[1:]]
cfg = DEFAULT
if args and args[0].endswith(".json"):
    cfg = json.load(open(args[0])); args = args[1:]
seed = int(args[0]) if args else 20261106
EV = cfg["events"]; SLOTS_TOTAL = int(cfg["slots_total"]); N_EV = len(EV)
groups = [set(g) for g in cfg.get("shared", [])]
def disjoint(a, b): return not any(a in g and b in g for g in groups)
T0 = datetime(2026, 10, 1)
H = {k: (datetime.strptime(v, "%Y-%m-%dT%H") - T0).total_seconds() / 3600 for k, v in EV.items()}
print(f"K14 v3 [{cfg.get('label','')}] zdarzen={N_EV} slotow={SLOTS_TOTAL} seed={seed}")
for W in (24, 12):
    inc = sum(1 for a in H if any(b != a and abs(H[a]-H[b]) <= W and disjoint(a, b) for b in H))
    strict = sum(1 for a in H if any(b != a and abs(H[a]-H[b]) < W and disjoint(a, b) for b in H))
    print(f"K14 okno {W} h: z towarzyszem <= {W} h: {inc}/{N_EV}; < {W} h: {strict}/{N_EV}")
lone = [k for k in H if not any(b != k and abs(H[k]-H[b]) <= 24 and disjoint(k, b) for b in H)]
print(f"K14 bez towarzysza w 24 h: {lone}")
BAND = int((max(H.values()) - min(H.values())) / 6) + 1
print(f"K14 pasmo zapasci: {min(EV.values())} .. {max(EV.values())} = {BAND} slotow z {SLOTS_TOTAL}")
N = 200000
for label, SLOTS in (("cale okno", SLOTS_TOTAL), ("pasmo zapasci", BAND)):
    random.seed(seed)
    for W, s in ((24, 4), (12, 2)):
        tot = 0; hist = [0] * (N_EV + 1)
        for _ in range(N):
            x = [random.randrange(SLOTS) for _ in range(N_EV)]
            k = sum(1 for i in range(N_EV) if any(j != i and abs(x[i]-x[j]) <= s for j in range(N_EV)))
            tot += k; hist[k] += 1
        obs = sum(1 for a in H if any(b != a and abs(H[a]-H[b]) <= W and disjoint(a, b) for b in H))
        p_obs = sum(hist[obs:]) / N
        print(f"K14 baza losowa [{label}, {SLOTS} slotow] ±{s} slotow ({W} h), {N} losowan: oczekiwane z towarzyszem {tot/N:.2f}/{N_EV}; "
              f"P(>= obserwowane {obs}) = {p_obs:.3f}")
