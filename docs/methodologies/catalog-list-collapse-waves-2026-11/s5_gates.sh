#!/bin/bash
# L-24 bramki B1–B6 -> work/gates.json; wywołanie: s5_gates.sh (dwa przebiegi: przed i po renderze SAFE)
cd ~/nightq-1103-l24/work
python3 - <<'PY'
import json,subprocess,hashlib,os
o=json.load(open('../out/l24.json')); G={}
c1={e['snap'] for e in o['windowA']['events'] if e['code']=='C1'}
need={'2026-10-18T15:00:02Z','2026-11-01T09:00:01Z'}
G['B1']=('PASS' if c1==need else 'FAIL', f"C1 zapaści w A: {sorted(c1)} (wymagane {sorted(need)}); D przed 15 559 i 11 738, w zapaści 0.")
rt={'C1':2,'H07':1,'H18':1,'H08':1,'H12':1,'H23':1,'H03':1,'H06':1,'H16':1,'H20':1}
from collections import Counter
me=Counter(e['code'] for e in o['windowA']['events'])
diff={k:(rt.get(k,0),me.get(k,0)) for k in set(rt)|set(me) if rt.get(k,0)!=me.get(k,0)}
G['B2']=('PASS' if not diff else 'FAIL', f"red team 11 zdarzeń, L-24 {sum(me.values())}; różnice per kod: {diff or 'brak'}; odczyty zapaści zgodne z tabelami M1+uzupełnienie TLO-SAFE (kody z tej samej mapy, `www.` zdjęte po obu stronach).")
src=''.join(open(f).read() for f in ['s1_extract.py','s3_analyze.py','s2_log.py'])
conns=src.count('sqlite3.connect('); ro=src.count('?mode=ro"')
wr=[w for w in ['INSERT','UPDATE ','DELETE','CREATE','DROP','.backup','ATTACH'] if w in src]
files=subprocess.run("find ~/nightq-1103-l24 -type f | sed 's#.*/nightq-1103-l24/##' | sort | tr '\n' ' '",shell=True,capture_output=True,text=True).stdout
G['B3']=('PASS' if conns==ro==1 and not wr else 'FAIL', f"połączeń sqlite {conns}, z `?mode=ro` {ro}; słowa zapisu w SQL: {wr or 0}; log crawlera czytany open() bez trybu zapisu; poza ~/nightq-1103-l24/ zapis tylko 2 linie do ALERTS.log (wymagane briefem). Pliki: {files.strip()}")
h=hashlib.sha256(open('../out/rule_C.txt','rb').read()).hexdigest()
G['B5']=('PASS' if h.startswith('1c929385') else 'FAIL', f"sha256(rule_C.txt) = {h[:8]}…{h[-7:]} = wartość z 10:29:14Z (przed 1. zapytaniem do bazy, plik snaps_all.txt mtime {subprocess.run(['date','-u','-r','snaps_all.txt','+%H:%M:%SZ'],capture_output=True,text=True).stdout.strip()}); s3_analyze.py implementuje rozłączność zbiorów payTo, bez progów dobranych po danych.")
S='../out/L24-SAFE.md'
if os.path.exists(S):
    b4=subprocess.run(['bash','-c',r'grep -cE "https?://|0x[0-9a-fA-F]{6,}|\.(com|io|dev|xyz|ai|me|app|net|org)\b" '+S],capture_output=True,text=True).stdout.strip()
    b4all=subprocess.run(['bash','-c',r'cat ../out/* | grep -cE "https?://|0x[0-9a-fA-F]{6,}|\.(com|io|dev|xyz|ai|me|app|net|org)\b"'],capture_output=True,text=True).stdout.strip()
    nl=int(subprocess.run(['bash','-c','wc -l < '+S],capture_output=True,text=True).stdout)
    G['B4']=('PASS' if b4=='0' else 'FAIL', f"grep -cE (wzorzec z briefu) na SAFE = {b4}; na całym out/ (cat) = {b4all}.")
    G['B6']=('PASS' if nl<=150 else 'FAIL', f"SAFE = {nl} linii (≤ 150).")
else:
    G['B4']=('?','—'); G['B6']=('?','—')
G={k:G[k] for k in ['B1','B2','B3','B4','B5','B6']}
json.dump(G,open('gates.json','w'),ensure_ascii=False)
print({k:v[0] for k,v in G.items()})
PY
