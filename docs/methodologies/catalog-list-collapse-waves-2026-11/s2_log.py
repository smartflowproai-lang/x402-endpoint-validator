# L-24 krok 2: parsowanie logu crawlera (tylko odczyt). Wynik: work/log.json
import re, json, datetime as dt
L="/home/ubuntu/x402-network-mapper/logs/bazaar-crawler.log"
runs={}; cur=None; seen=set()
ts=lambda l: dt.datetime.strptime(l[:23],"%Y-%m-%d %H:%M:%S,%f")
for l in open(L, errors='replace'):
    l=l.rstrip('\n')
    if l in seen: continue          # każda linia logowana 2x (dwa handlery)
    seen.add(l)
    m=re.search(r"=== Bazaar crawler run: (\S+) ===",l)
    if m: cur=m.group(1); runs[cur]={'start':ts(l),'warn':0,'api_total':None,'items':None,'pages':None,'summary':None,'end':None}; continue
    if cur is None: continue
    r=runs[cur]
    if m:=re.search(r"reported by API: ([\d,]+)",l): r['api_total']=int(m.group(1).replace(',',''))
    elif m:=re.search(r"Fetch complete: ([\d,]+) total items across ([\d,]+) pages",l): r['items']=int(m.group(1).replace(',','')); r['pages']=int(m.group(2).replace(',',''))
    elif '[WARNING]' in l or '[ERROR]' in l: r['warn']+=1
    elif m:=re.search(r"=== SUMMARY === total=([\d,]+) \| prev=([\d,]+) \| new=([\d,]+) \| disappeared=([\d,]+)",l):
        r['summary']=[int(x.replace(',','')) for x in m.groups()]; r['end']=ts(l)
out={k:{**v,'start':v['start'].isoformat(),'end':v['end'].isoformat() if v['end'] else None,
        'dur_s':(v['end']-v['start']).total_seconds() if v['end'] else None} for k,v in runs.items()}
json.dump(out,open('log.json','w'),indent=0)
print(len(out),'runs; bez SUMMARY:',[k for k,v in out.items() if not v['summary']])
print('z WARN:',{k:v['warn'] for k,v in out.items() if v['warn']})
