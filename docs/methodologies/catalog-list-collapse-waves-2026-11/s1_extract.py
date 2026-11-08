# L-24 krok 1: ekstrakcja z bazaar_snapshots (mode=ro). Wynik: work/ext.json
import sqlite3, json, collections, time, sys
DB="/home/ubuntu/x402-network-mapper/mapper.db"
c=sqlite3.connect(f"file:{DB}?mode=ro", uri=True, isolation_level=None)
def host(u):
    i=u.find('://')
    if i<0: return '(brak-schematu)'
    r=u[i+3:]
    for ch in '/?#':
        j=r.find(ch)
        if j>=0: r=r[:j]
    r=r.lower()
    if '@' in r: r=r.split('@',1)[1]
    if r.startswith('www.'): r=r[4:]
    return r
snaps=[l.split('|')[0] for l in open('snaps_all.txt').read().split('\n') if l]
snaps=[s for s in snaps if '2026-09-01T00'<=s<__import__('os').environ.get('WI20_END','2026-11-03')]
per={}; cat={}; payto=collections.defaultdict(lambda: collections.defaultdict(set)); qt=[]
for s in snaps:
    t=time.time()
    rs=c.execute("select resource_url, lower(trim(pay_to)) from bazaar_snapshots where snapshot_date=?",(s,)).fetchall()
    qt.append(time.time()-t)
    d=collections.defaultdict(set); n=collections.Counter()
    for u,p in rs:
        h=host(u); d[h].add(u); n[h]+=1
        if p: payto[s[:7]][h].add(p)
    per[s]={h:[len(d[h]),n[h]] for h in d}
    cat[s]=[len(set(u for u,_ in rs)), len(rs)]
json.dump({'snaps':snaps,'per':per,'cat':cat,
           'payto':{m:{h:sorted(v) for h,v in hp.items()} for m,hp in payto.items()},
           'qmax':max(qt),'qsum':sum(qt)},open('ext.json','w'))
print(len(snaps),'snaps; qmax',round(max(qt),1),'qsum',round(sum(qt)))
