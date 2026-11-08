# L-24 krok 4: generuje out/L24-SAFE.md z out/l24.json (tylko kody hostów)
import json, datetime as dt
o=json.load(open('../out/l24.json'))
f=lambda s: s[8:10]+'.'+s[5:7]+' '+s[11:13]+'Z'
n=lambda x: f"{x:,}".replace(',',' ') if isinstance(x,int) else (f"{x:.3f}".replace('.',',') if isinstance(x,float) else str(x))
WD={'Mon':'pn','Tue':'wt','Wed':'śr','Thu':'cz','Fri':'pt','Sat':'sb','Sun':'nd'}
L=[]; a=L.append
A=o['windowA']; S=o['windowS']
a("# L-24 — zapaści list hostów w katalogu Bazaar: druga droga, test artefaktu crawlera, okres niezależny")
a(f"Wygenerowano {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%MZ}. Źródło: `bazaar_snapshots` (mode=ro) + log crawlera (linie SUMMARY/Fetch complete). Hosty tylko kodami: H01–H25/C1 = kody z TLO-SAFE (ta sama mapa), N01… = kody własne (mapa w work/). Tylko obserwable.")
a("")
a("## Definicje")
a("- Host = netloc `resource_url` (małe litery, bez `www.`, port nie zdejmowany). D = COUNT(DISTINCT resource_url) hosta w odczycie (`snapshot_date`).")
a("- Populacja okna = hosty z max D ≥ 200 w tym oknie. Zapaść = pierwszy odczyt z D < 1 % ostatniej wartości ≥ 200 sprzed niego (w oknie). Ponowne uzbrojenie dopiero po D ≥ 200.")
a("- Seria = liczba kolejnych odczytów z D < 1 % (włącznie z odczytem zapaści). Powrót = D ≥ 1 % ref. w ≤ 72 h; „obcięte” = brak powrotu, a do końca okna < 72 h. Migotanie = już NASTĘPNY odczyt ma D ≥ 1 % ref.")
a("- Odczyt niepełny (obserwabla): pozycje pobrane (`Fetch complete`) / `Total resources reported by API` < 0,99, albo duplikaty > 1 % wierszy.")
a("- Reguła C — zamrożona w `out/rule_C.txt` przed pierwszym zapytaniem (sha256 1c929385…b8808ab, 10:29:14Z): doba skupienia = doba UTC z ≥ 2 zapaściami hostów o RÓŻNYCH payTo; „różne” = rozłączne zbiory payTo hosta (kolumna `pay_to`, odczyty z okna); brak payTo = osobny.")
a("")
a("## Bramki")
G=json.load(open('gates.json'))
for k,v in G.items(): a(f"- **{k} {v[0]}** — {v[1]}")
a("")
a(f"## A. Zapaści, okno {f(A['first'])} – {f(A['last'])} ({A['n_snaps']} odczytów; odczytu 01.10 00Z brak — pierwszy bieg 03Z)")
a(f"Populacja: {A['hosts_ge200']} hostów (25 + C1, jak w TLO). Zdarzeń: **{len(A['events'])}**.")
a("")
a("| # | host | odczyt zapaści | dz. | ostatnie D ≥ 200 (odczyt) | D bezpośr. przed | D | seria | do końca okna | powrót ≤ 72 h | następny D | payTo hosta |")
a("|---|---|---|---|---|---|---|---|---|---|---|---|")
for i,e in enumerate(sorted(A['events'],key=lambda e:(e['snap'],e['code'])),1):
    r='tak ('+f(e['back_snap'])+')' if e['returned'] is True else ('nie' if e['returned'] is False else 'obcięte')
    a(f"| {i} | {e['code']} | {f(e['snap'])} | {WD[dt.date.fromisoformat(e['snap'][:10]).strftime('%a')]} | {n(e['ref'])} ({f(e['ref_snap'])}) | {n(e['prev'])} | {e['D']} | {e['run']} | {'tak' if e['run_to_end'] else 'nie'} | {r} | {e['next_D']} | {e['n_payto']} |")
a("")
a("10 z 11 odczytów zapaści w dobach 17–19.10 (3) i 28.10–01.11 (7); poza nimi H18 26.10. Migotanie: 1/11 (C1 01.11 09Z → 6 412 w 15Z).")
a("")
a("## B. Kompletność odczytów")
for W,lab in [(A,'okno A'),(S,'okres wrz.')]:
    R=W['readings']; m=W['medians']
    rat=[r['items']/r['api_total'] for r in R]
    a(f"- {lab}: {len(R)} odczytów, SUMMARY w logu dla {sum(r['log'] for r in R)}/{len(R)}, ostrzeżeń HTTP 0 we wszystkich. Mediany: wiersze {n(round(m['rows']))}, distinct {n(round(m['distinct']))}, duplikaty {n(m['dup_pct'])} %, hosty D>0 {n(round(m['hosts_pos']))}, strony {n(round(m['pages']))}, czas {round(m['dur_s'])} s. Pobrane/API: min {n(round(min(rat),4))}; < 0,99: {', '.join(f(r['snap'])+' ('+n(r['items'])+'/'+n(r['api_total'])+')' for r in R if r['items']/r['api_total']<0.99) or 'brak'}; duplikaty > 1 %: {', '.join(f(r['snap'])+' ('+n(r['dup_pct'])+' %)' for r in R if r['dup_pct']>1) or 'brak'}.")
a("")
a("Odczyty z zapaściami (sąsiedzi = odczyt przed → zapaść → odczyt po):")
a("")
a("| odczyt | zapaści | distinct przed→w→po | hosty D>0 przed→w→po | dup. % | pobrane/API | strony | czas s | SUMMARY (total/prev/new/disappeared) |")
a("|---|---|---|---|---|---|---|---|---|")
for W in [A,S]:
    R=W['readings']; idx={r['snap']:i for i,r in enumerate(R)}
    by={}
    for e in W['events']: by.setdefault(e['snap'],[]).append(e['code'])
    for s in sorted(by):
        i=idx[s]; p,r=R[i-1],R[i]; q=R[i+1] if i+1<len(R) else None
        a(f"| {f(s)} | {', '.join(sorted(by[s]))} | {n(p['distinct'])}→{n(r['distinct'])}→{n(q['distinct']) if q else '—'} | {n(p['hosts_pos'])}→{n(r['hosts_pos'])}→{n(q['hosts_pos']) if q else '—'} | {n(r['dup_pct'])} | {n(round(r['items']/r['api_total'],4))} | {r['pages']} | {round(r['dur_s'])} | {'/'.join(n(x) for x in r['summary'])} |")
a("")
a("Obserwable B:")
a("- Okno A, 10 odczytów z zapaściami: pobrane/API ≥ 0,999 w 10/10; duplikaty ≤ 0,22 % w 9/10 (wyjątek 31.10 15Z — H08: 1,015 %); hosty D>0 w ±1 % odczytu poprzedniego w 9/10 (wyjątek 01.11 09Z: 3 112 vs 2 994 w 01.11 03Z, który sam jest niepełny).")
a("- Okno A: jedyny odczyt z pobrane/API < 0,99 to 01.11 03Z (duplikaty 6,6 %) — to odczyt BEZPOŚREDNIO PRZED drugą zapaścią C1 i zarazem jej „ostatnie D ≥ 200” (C1: 76 688 w 31.10 21Z → 11 738 w 01.11 03Z → 0 → 6 412 → 22 078). Sam odczyt zapaści 01.11 09Z: pobrane = API (28 207), ale czas 164 s vs mediana 467 s, distinct 28 201 vs 38 134 przed i 34 670 po.")
a("- Okno A: 10/11 zapaści bez migotania (następny odczyt nadal < 1 %); 9/11 z serią ≥ 5 odczytów. Wzorzec „cały odczyt niepełny” nie występuje w odczytach zapaści okna A (poza zastrzeżeniami wyżej).")
a("- Wrzesień: 9 z 11 zapaści w JEDNYM odczycie 23.09 21Z: 98 wierszy z 16 604 zgłoszonych przez API (1 strona, 2 s, hosty D>0 54 vs mediana 1 993); wszystkie 9 migoczą (wracają w 24.09 03Z do ~tej samej D). Log crawlera nie ma dla niego WARNING — SUMMARY: total=98, disappeared=16 502.")
a("")
a("## C. Reguła C (bez zmian po obejrzeniu danych)")
a("")
a("| okres | odczyty | hosty ≥ 200 | zapaści | doby skupienia | zapaści w dobach skupienia | udział | pn | wt | śr | cz | pt | sb | nd |")
a("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for W,lab in [(A,'A 01.10–02.11'),(S,'01.09–30.09')]:
    C=W['C']; w=C['weekday']
    a(f"| {lab} | {W['n_snaps']} | {W['hosts_ge200']} | {C['n']} | {C['n_focus']} ({', '.join(d[8:10]+'.'+d[5:7] for d in C['focus_days'])}) | {C['in_focus']} | {n(C['share'])} | "+' | '.join(str(w[k]) for k in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])+" |")
a("")
a("Zapaści per doba: A — "+'; '.join(d[8:10]+'.'+d[5:7]+': '+', '.join(c) for d,c in A['C']['per_day'].items())+".")
a("Wrz. — "+'; '.join(d[8:10]+'.'+d[5:7]+': '+', '.join(c) for d,c in S['C']['per_day'].items())+".")
a("")
a("- Okres niezależny: wrzesień 2026 ma pełne odczyty (120/120, pierwszy 01.09 03Z), więc użyty wprost.")
a("- A: doba 31.10 ma 3 zapaści (H06, H08, H16), ale każda para hostów ma ≥ 1 wspólny payTo (H08 i H16: ten sam jedyny payTo; H06: 2 payTo, w tym ten) ⇒ wg reguły C NIE jest dobą skupienia. Doby 17.10, 18.10, 19.10 mają po 1 zapaści (H07, C1, H20; payTo parami rozłączne) ⇒ też nie. Jedyna doba skupienia A: 28.10 (H12, H23, payTo rozłączne).")
a("- Wrz.: jedyna doba skupienia (23.09) to w całości odczyt niepełny z sekcji B (9 zapaści, 9 różnych zbiorów payTo).")
a("")
a("## Uwagi (opis, NIE zmiana reguły C)")
a("- Zgodność z red teamem jest pełna, ale reguła C daje dla A 1 dobę skupienia / 2 z 11 zapaści; zdanie „10 z 11 w 17–19.10 i 28.10–01.11” opisuje okna 3- i 5-dobowe, a nie doby z ≥ 2 zapaściami różnych payTo.")
a("- Po wyłączeniu odczytów niepełnych (pobrane/API < 0,99) wrzesień miałby 2 zapaści (N03 06.09, H07 07.09; obie bez powrotu, serie 100 i 85) i 0 dób skupienia; A bez zmian liczbowo (01.11 03Z nie jest odczytem zapaści, ale jest odczytem odniesienia dla C1 #2). Podane tylko jako kontekst.")
a("- H07 zapadał się w obu okresach (07.09 i 17.10, za każdym razem z ref. 844); H03 i H06 we wrześniu tylko w odczycie niepełnym.")
a("- Okna liczone wewnętrznie: zapaść z ref. sprzed początku okna (np. host ≥ 200 pod koniec sierpnia) nie jest liczona. 4 odczyty okna A (05.10 15Z, 17.10 03Z, 31.10 15Z, 01.11 03Z) mają duplikaty > 1 %; tylko 31.10 15Z jest odczytem zapaści.")
a("- Pełna tabela per odczyt (B) dla 252 odczytów: `out/l24.json` → `readings`. Skrypty: `out/s1_extract.py`, `s2_log.py`, `s3_analyze.py`, `s4_safe.py`, `s5_gates.sh`.")
open('../out/L24-SAFE.md','w').write('\n'.join(L)+'\n')
print(len(L))
