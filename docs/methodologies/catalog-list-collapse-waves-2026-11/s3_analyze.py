# L-24 krok 3: zapaści (A), kompletność odczytów (B), reguła C. Wejście: ext.json, log.json, TLO anon_map. Wynik: out/l24.json + work/codes.json
import json, statistics as st, datetime as dt, collections
E=json.load(open('ext.json')); LOG=json.load(open('log.json'))
tlo=json.load(open('/home/ubuntu/nightq-1103-tlo/work/anon_map.json'))
tlo={(h[4:] if h.startswith('www.') else h).lower():c for h,c in tlo.items()}
P=lambda s: dt.datetime.strptime(s,"%Y-%m-%dT%H:%M:%SZ")
WA=('2026-10-01T00',__import__('os').environ.get('WI20_END','2026-11-02T24')); WS=('2026-09-01T00','2026-09-30T24')
codes={}; own=[0]
def code(h):
    if h in tlo: return tlo[h]
    if h not in codes: own[0]+=1; codes[h]=f"N{own[0]:02d}"
    return codes[h]
def collapses(W):
    snaps=[s for s in E['snaps'] if W[0]<=s<W[1]]
    hosts=sorted({h for s in snaps for h,(d,_) in E['per'][s].items() if d>=200})
    ev=[]
    for h in hosts:
        D=[E['per'][s].get(h,[0,0])[0] for s in snaps]
        ref=None; refi=None; i=0
        while i<len(snaps):
            if D[i]>=200: ref=D[i]; refi=i; i+=1; continue
            if ref is not None and D[i]<0.01*ref:
                j=i
                while j<len(snaps) and D[j]<0.01*ref: j+=1
                t0=P(snaps[i]); back=None
                for k in range(i+1,len(snaps)):
                    if (P(snaps[k])-t0).total_seconds()>72*3600: break
                    if D[k]>=0.01*ref: back=snaps[k]; break
                trunc = back is None and (P(snaps[-1])-t0).total_seconds()<72*3600
                ev.append(dict(host=h,code=code(h),snap=snaps[i],ref=ref,ref_snap=snaps[refi],prev=D[i-1],D=D[i],
                    run=j-i,run_to_end=(j==len(snaps)),returned=('obcięte' if trunc else bool(back)),back_snap=back,
                    next_D=(D[i+1] if i+1<len(snaps) else None),flicker=(i+1<len(snaps) and D[i+1]>=0.01*ref)))
                ref=None; i=j; continue   # ponowne uzbrojenie dopiero po D>=200
            i+=1
    return snaps,hosts,ev
def readings(snaps):
    rows=[]
    for s in snaps:
        d,n=E['cat'][s]; lg=LOG.get(s)
        rows.append(dict(snap=s,rows=n,distinct=d,dup_pct=round(100*(n-d)/n,3) if n else None,
            hosts_pos=len(E['per'][s]),log=bool(lg and lg['summary']),
            api_total=lg and lg['api_total'],items=lg and lg['items'],pages=lg and lg['pages'],
            warn=lg and lg['warn'],dur_s=lg and lg['dur_s'],summary=lg and lg['summary']))
    return rows
def payto_sets(month_keys,h):
    s=set()
    for m in month_keys: s|=set(E['payto'].get(m,{}).get(h,[]))
    return frozenset(s) if s else frozenset({'__brak__'+h})
def rule_C(ev,months):
    byday=collections.defaultdict(list)
    for e in ev: byday[e['snap'][:10]].append(e)
    focus=[]
    for day,es in sorted(byday.items()):
        ps=[payto_sets(months,e['host']) for e in es]
        if any(ps[a].isdisjoint(ps[b]) for a in range(len(es)) for b in range(a+1,len(es))): focus.append(day)
    inf=sum(len(byday[d]) for d in focus)
    wd=collections.Counter(dt.date.fromisoformat(e['snap'][:10]).strftime('%a') for e in ev)
    shared=[[e['code'] for e in es] for d,es in byday.items() if len(es)>=2]
    return dict(n=len(ev),focus_days=focus,n_focus=len(focus),in_focus=inf,share=(round(inf/len(ev),3) if ev else None),
                weekday={k:wd.get(k,0) for k in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']},
                per_day={d:[e['code'] for e in es] for d,es in sorted(byday.items())})
sA,hA,evA=collapses(WA); sS,hS,evS=collapses(WS)
rA=readings(sA); rS=readings(sS)
def med(rows,k): return st.median([r[k] for r in rows])
out=dict(windowA=dict(n_snaps=len(sA),first=sA[0],last=sA[-1],hosts_ge200=len(hA),events=evA,
          medians={k:med(rA,k) for k in ['rows','distinct','dup_pct','hosts_pos','dur_s','pages']},readings=rA,C=rule_C(evA,['2026-10','2026-11'])),
         windowS=dict(n_snaps=len(sS),first=sS[0],last=sS[-1],hosts_ge200=len(hS),events=evS,
          medians={k:med(rS,k) for k in ['rows','distinct','dup_pct','hosts_pos','dur_s','pages']},readings=rS,C=rule_C(evS,['2026-09'])))
# payTo – tylko liczności w out (adresy zostają w work)
for W,ev,months in [('windowA',evA,['2026-10','2026-11']),('windowS',evS,['2026-09'])]:
    for e in ev:
        ps=payto_sets(months,e['host']); e['n_payto']=0 if any(p.startswith('__brak__') for p in ps) else len(ps)
pt_work={W:{e['code']:sorted(payto_sets(m,e['host'])) for e in ev} for W,ev,m in [('A',evA,['2026-10','2026-11']),('S',evS,['2026-09'])]}
json.dump(dict(codes_own=codes,codes_tlo_used={e['host']:e['code'] for e in evA+evS},payto=pt_work),open('codes.json','w'),indent=1)
for W in ['windowA','windowS']:
    for e in out[W]['events']: del e['host']
json.dump(out,open('../out/l24.json','w'),indent=1)
for W in ['windowA','windowS']:
    o=out[W]; print(W,o['n_snaps'],o['first'],o['last'],'hosts>=200',o['hosts_ge200'],'med',o['medians'])
    for e in o['events']: print(' ',{k:e[k] for k in ['code','snap','ref','ref_snap','prev','D','run','run_to_end','returned','next_D','flicker','n_payto']})
    print('  C',{k:v for k,v in o['C'].items()})
