# WI#20 S0: K1–K5, K7, K9 z wyjść L-24 (ext.json, log.json, l24_end.json) w katalogu biegu. Tylko odczyt plików; zero bazy.
# Wywołanie: python3 k_analysis.py <katalog_biegu> <END> -> <katalog_biegu>/kfacts.json (+ kody hostów tylko w work)
import json, sys, os, re, collections, statistics as st, datetime as dt
RD, END = sys.argv[1], sys.argv[2]
E = json.load(open(f'{RD}/ext.json')); LOG = json.load(open(f'{RD}/log.json')); O = json.load(open(f'{RD}/l24_end.json'))
FREEZE = '2026-11-03T10:29:14Z'; INS_END = '2026-11-03T09:59:59Z'
P = lambda s: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
tlo = json.load(open('/home/ubuntu/nightq-1103-tlo/work/anon_map.json'))
tlo = {(h[4:] if h.startswith('www.') else h).lower(): c for h, c in tlo.items()}
C1 = [h for h, c in tlo.items() if c == 'C1'][0]
A = O['windowA']; S = O['windowS']
sA = [s for s in E['snaps'] if '2026-10-01T00' <= s < END]; sS = [s for s in E['snaps'] if '2026-09-01T00' <= s < '2026-09-30T24']
assert len(sA) == A['n_snaps'] and len(sS) == S['n_snaps']
idx = {s: i for i, s in enumerate(sA)}
evA = A['events']; evS = S['events']
def D(s, h): return E['per'][s].get(h, [0, 0])[0]
# --- mapa kodów (tylko work): kody L-24 + nowe hosty populacji bez zdarzeń
codes = json.load(open(f'{RD}/codes.json'))
code_of = dict(tlo); code_of.update(codes['codes_own'])
pop = sorted({h for s in sA for h, (d, _) in E['per'][s].items() if d >= 200})
k = len(codes['codes_own'])
for h in pop:
    if h not in code_of: k += 1; code_of[h] = f"N{k:02d}"
json.dump({h: code_of[h] for h in pop}, open(f'{RD}/popcodes-WORK-ONLY.json', 'w'), indent=1)
# --- reguła C (logika 1:1 z s3_analyze.rule_C; payTo z miesięcy okna)
def payto_sets(months, h):
    s = set()
    for m in months: s |= set(E['payto'].get(m, {}).get(h, []))
    return frozenset(s) if s else frozenset({'__brak__' + h})
host_of = {code_of[h]: h for h in code_of}
def ruleC(ev, months):
    byday = collections.defaultdict(list)
    for e in ev: byday[e['snap'][:10]].append(e)
    focus = []
    for day, es in sorted(byday.items()):
        ps = [payto_sets(months, host_of[e['code']]) for e in es]
        if any(ps[a].isdisjoint(ps[b]) for a in range(len(es)) for b in range(a + 1, len(es))): focus.append(day)
    inf = sum(len(byday[d]) for d in focus)
    return dict(n=len(ev), focus_days=focus, in_focus=inf, share=(round(inf / len(ev), 3) if ev else None))
rd_by = {r['snap']: r for r in A['readings'] + S['readings']}
def full(r):
    ratio = (r['items'] / r['api_total']) if r['items'] and r['api_total'] else None
    return ratio, (ratio is not None and ratio >= 0.99 and (r['dup_pct'] or 0) <= 1.0)
periods = {'wrz': sS, 'A_in': [s for s in sA if s <= INS_END], 'A_out': [s for s in sA if s > FREEZE], 'A_all': sA}
K2 = {}; K4 = {}
for name, ss in periods.items():
    ev = [e for e in (evS if name == 'wrz' else evA) if e['snap'] in set(ss)]
    hosts = sorted({h for s in ss for h, (d, _) in E['per'][s].items() if d >= 200})
    rc = ruleC(ev, ['2026-09'] if name == 'wrz' else ['2026-10', '2026-11'])
    K2[name] = dict(readings=len(ss), first=ss[0] if ss else None, last=ss[-1] if ss else None, hosts_ge200=len(hosts), **rc)
    rows = [rd_by[s] for s in ss]; rat = [(r['snap'], full(r)[0]) for r in rows]
    K4[name] = dict(readings=len(rows), summary=sum(1 for r in rows if r['log']), with_ratio=sum(1 for _, x in rat if x is not None),
                    ratio_min=min(x for _, x in rat if x is not None), ratio_lt099=[(s, round(x, 4)) for s, x in rat if x is not None and x < 0.99],
                    dup_gt1=[(r['snap'], r['dup_pct']) for r in rows if (r['dup_pct'] or 0) > 1.0])
K2['A_out']['snaps'] = periods['A_out']
# --- K1: tabela zapaści A do END + po zamrożeniu + pełny/niepełny
K1 = []
for e in sorted(evA, key=lambda e: (e['snap'], e['code'])):
    K1.append({**{x: e[x] for x in ['code', 'snap', 'ref', 'ref_snap', 'prev', 'D', 'run', 'run_to_end', 'returned', 'back_snap', 'next_D', 'flicker', 'n_payto']},
               'after_freeze': e['snap'] > FREEZE, 'reading_full': full(rd_by[e['snap']])[1], 'ratio': round(full(rd_by[e['snap']])[0], 4), 'dup_pct': rd_by[e['snap']]['dup_pct']})
# --- K3: rozkład
def k3(ev, ss):
    hosts = {h for s in ss for h, (d, _) in E['per'][s].items() if d >= 200}
    col = {host_of[e['code']] for e in ev}
    return dict(runs=sorted(e['run'] for e in ev), run_hist=dict(sorted(collections.Counter(e['run'] for e in ev).items())),
                returned_72h=sum(1 for e in ev if e['returned'] is True), not_returned=sum(1 for e in ev if e['returned'] is False),
                truncated=sum(1 for e in ev if e['returned'] == 'obcięte'), flicker=sum(1 for e in ev if e['flicker']),
                run_to_end=sum(1 for e in ev if e['run_to_end']),
                ref=[min(e['ref'] for e in ev), st.median(e['ref'] for e in ev), max(e['ref'] for e in ev)],
                prev=[min(e['prev'] for e in ev), st.median(e['prev'] for e in ev), max(e['prev'] for e in ev)],
                hosts_ge200=len(hosts), hosts_collapsed=len(col), never_collapsed=len(hosts - col))
K3 = {'A_all': k3(evA, sA), 'wrz': k3(evS, sS)}
# --- K7: C1
ser = [(s, D(s, C1), E['cat'][s][0]) for s in E['snaps'] if s >= '2026-10-17T21']
K7 = dict(series=[(s, d, c, round(100 * d / c, 2) if c else None) for s, d, c in ser],
          ref1=('2026-10-18T09:00:01Z', D('2026-10-18T09:00:01Z', C1)), ref2=('2026-10-31T21:00:01Z', D('2026-10-31T21:00:01Z', C1)),
          r0103=dict(D=D('2026-11-01T03:00:02Z', C1), ratio=round(full(rd_by['2026-11-01T03:00:02Z'])[0], 4), items=rd_by['2026-11-01T03:00:02Z']['items'],
                     api=rd_by['2026-11-01T03:00:02Z']['api_total'], dup=rd_by['2026-11-01T03:00:02Z']['dup_pct']),
          ctrl={'2026-11-01T21': D('2026-11-01T21:00:01Z', C1), '2026-11-03T09': D('2026-11-03T09:00:02Z', C1),
                'cat_2026-11-03T09': E['cat']['2026-11-03T09:00:02Z'][0], 'cat_2026-11-01T09': E['cat']['2026-11-01T09:00:01Z'][0]})
# --- K9
c1_state = set(); any_state = set(); oth_state = set()
for e in evA:
    i = idx[e['snap']]; rng = set(sA[i:i + e['run']])
    any_state |= rng
    if e['code'] == 'C1': c1_state |= rng
    else: oth_state |= rng
def frac(a, n): return f"{a}/{n}"
allr = [s for s in E['snaps'] if '2026-09-01T00' <= s < END]
drops = []
for a, b in zip(allr, allr[1:]):
    ra, rb = rd_by.get(a), rd_by.get(b)
    if ra and rb and full(ra)[1] and full(rb)[1]:
        drops.append((E['cat'][a][0] - E['cat'][b][0], a, b, E['cat'][a][0], E['cat'][b][0]))
dA = [x for x in drops if x[1] >= '2026-10-01']
K9 = dict(i_c1=frac(len(c1_state), len(sA)), i_c1_snaps=sorted(c1_state),
          i_c1_in=frac(len([s for s in c1_state if s <= INS_END]), len(periods['A_in'])),
          ii_any=frac(len(any_state), len(sA)), ii_any_in=frac(len([s for s in any_state if s <= INS_END]), len(periods['A_in'])),
          ii_any_first=min(any_state), ii_without_c1=frac(len(oth_state), len(sA)),
          iii_maxdrop_A=max(dA), iii_maxdrop_all=max(drops), n_pairs_A=len(dA), n_pairs_all=len(drops),
          iii_top3_A=sorted(dA, reverse=True)[:3])
# --- K4 backfill + K5
bf = [json.loads(l) for l in open('/home/ubuntu/nightq-1103-crawlergate/bazaar-read-status-backfill.jsonl')]
inc = [x for x in bf if x['status'] != 'complete']
why = lambda x: ('oba' if x['ratio'] < 0.99 and x['dup_pct'] > 1 else ('ratio' if x['ratio'] < 0.99 else 'dup'))
K4['backfill'] = dict(n=len(bf), first=bf[0]['snapshot_date'], last=bf[-1]['snapshot_date'], incomplete=len(inc),
                      reasons=dict(collections.Counter(why(x) for x in inc)), list=[(x['snapshot_date'], x['ratio'], x['dup_pct'], why(x)) for x in inc])
bfi = {x['snapshot_date']: x for x in bf}
K4['ctrl'] = {s: (bfi[s]['status'], bfi[s]['ratio'], bfi[s]['dup_pct']) for s in ['2026-09-23T21:00:01Z', '2026-11-01T03:00:02Z']}
seen = set(); rs = []
for l in open('/home/ubuntu/x402-network-mapper/logs/bazaar-crawler.log', errors='replace'):
    if 'READ-STATUS' in l and l not in seen: seen.add(l); rs.append(l.strip())
js = [json.loads(l) for l in open('/home/ubuntu/x402-network-mapper/logs/bazaar-read-status.jsonl')] if os.path.exists('/home/ubuntu/x402-network-mapper/logs/bazaar-read-status.jsonl') else []
js = [x for x in js if x['snapshot_date'] < END]
warn = sum(1 for l in open('/home/ubuntu/monitoring/ALERTS.log', errors='replace') if re.search(r'^\[[^\]]+\] WARNING bazaar-read:', l))
K5 = dict(log_lines_unique=len(rs), first_line=rs[0] if rs else None, jsonl=js, alerts_warning=warn,
          snaps_in_db_after=[s for s in E['snaps'] if s >= '2026-11-04T10' and s < END],
          jsonl_vs_db={x['snapshot_date']: (x['fetched'], next((r['rows'] for r in A['readings'] if r['snap'] == x['snapshot_date']), None)) for x in js})
out = dict(END=END, last_snap=sA[-1], K1=K1, K2=K2, K3=K3, K4=K4, K5=K5, K7=K7, K9=K9)
json.dump(out, open(f'{RD}/kfacts.json', 'w'), indent=1, default=str)
print(json.dumps({k: out[k] for k in ['END', 'last_snap', 'K2', 'K3', 'K9']}, default=str)[:6000])
