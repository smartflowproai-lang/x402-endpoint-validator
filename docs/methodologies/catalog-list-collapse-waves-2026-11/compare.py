# Porównanie biegu refresh z pakietem S0: kontrole dodatnie (twarde) + różnice względem kfacts referencyjnego.
import json, sys, subprocess, os
RD, REF = sys.argv[1], sys.argv[2]
k = json.load(open(f'{RD}/kfacts.json')); r = json.load(open(REF))
ok = True
def chk(name, got, want):
    global ok; p = got == want; ok &= p; print(f"{'PASS' if p else 'FAIL'} {name}: {got} (oczekiwane {want})")
b1 = json.load(open(f'{RD}/l24_b1.json'))
chk('B1 11 zapaści L-24 (cięcie 02.11 21Z)', sorted((e['code'], e['snap']) for e in b1['windowA']['events']),
    sorted([('H07','2026-10-17T21:00:01Z'),('C1','2026-10-18T15:00:02Z'),('H20','2026-10-19T03:00:01Z'),('H18','2026-10-26T03:00:02Z'),('H12','2026-10-28T15:00:01Z'),
            ('H23','2026-10-28T15:00:01Z'),('H03','2026-10-29T09:00:01Z'),('H06','2026-10-31T09:00:02Z'),('H08','2026-10-31T15:00:01Z'),('H16','2026-10-31T21:00:01Z'),('C1','2026-11-01T09:00:01Z')]))
chk('K2 A_in', {x: k['K2']['A_in'][x] for x in ['readings','hosts_ge200','n','focus_days','in_focus']}, {'readings':134,'hosts_ge200':26,'n':11,'focus_days':['2026-10-28'],'in_focus':2})
chk('K2 wrz', {x: k['K2']['wrz'][x] for x in ['readings','n','focus_days','in_focus']}, {'readings':120,'n':11,'focus_days':['2026-09-23'],'in_focus':9})
chk('K7 ref1/ref2', [k['K7']['ref1'][1], k['K7']['ref2'][1]], [15559, 76688])
chk('K7 ND21/WT09/cat WT09', [k['K7']['ctrl']['2026-11-01T21'], k['K7']['ctrl']['2026-11-03T09'], k['K7']['ctrl']['cat_2026-11-03T09']], [22078, 67064, 102115])
chk('K7 01.11 03Z niepełny', [k['K7']['r0103']['items'], k['K7']['r0103']['api'], k['K7']['r0103']['ratio']], [40834, 48597, 0.8403])
chk('K4 kontrole backfill', k['K4']['ctrl'], {'2026-09-23T21:00:01Z': ['incomplete', 0.0059, 0.0], '2026-11-01T03:00:02Z': ['incomplete', 0.8403, 6.61]})
m=k['K9']['iii_maxdrop_A']
chk('K9 (iii) max spadek A (albo nowszy, większy po END pakietu)', m[:3] == [15441, '2026-10-18T09:00:01Z', '2026-10-18T15:00:02Z'] or (m[0] > 15441 and m[1] >= r['last_snap']), True)
cv = open(f'{RD}/curve_tue15.txt').read()
chk('krzywa C1 Tue 15:00 (nota difference-set)', ['4439; of these absent in ALL 9 reads' in cv, 'D 282/40732 (0.69%)' in cv, '45180 (79.7%)' in cv], [True, True, True])
# różnice względem pakietu
def flat(o, p=''):
    if isinstance(o, dict):
        for a, b in o.items(): yield from flat(b, f'{p}.{a}')
    else: yield p, json.dumps(o, default=str)
fa, fb = dict(flat(r)), dict(flat(k))
d = sorted(x for x in set(fa) | set(fb) if fa.get(x) != fb.get(x))
print(f"RÓŻNICE vs pakiet ({REF}): {len(d)} pól" + ('' if not d else ': ' + ', '.join(d[:60])))
print(f"nowe odczyty po {r['last_snap']}: {[s for s in k['K2']['A_all'] and k['K2']['A_out']['snaps'] if s > r['last_snap']]}")
print('KONTROLE:', 'PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
