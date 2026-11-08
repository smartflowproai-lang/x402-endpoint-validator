#!/bin/bash
# wi20_refresh.sh <END>  — przelicza K1–K5, K7, K9 pakietu WI#20 S0 dla odczytów < END (np. 2026-11-08T09:59:59Z).
# Tylko odczyt mapper.db (mode=ro + PRAGMA query_only przez ro_run.py / skrypt krzywej); surowe do ~/nightq-1108-wi20/raw/refresh-<END>/.
# Odmowa: 07:30–08:30Z (kopie) i df / < 100 G. Bez &.
set -euo pipefail
END="${1:?użycie: wi20_refresh.sh <END np. 2026-11-08T09:59:59Z>}"
[[ "$END" =~ ^2026-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || { echo "ZŁY END: $END"; exit 2; }
B=~/nightq-1108-wi20; W=$B/work; REF=$B/out/ref/kfacts-20261105T0900Z.json
hm=$(date -u +%H%M); if [ "$hm" -ge 0730 ] && [ "$hm" -lt 0830 ]; then echo "ODMOWA: okno kopii 07:30–08:30Z ($hm)"; exit 3; fi
free=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); [ "$free" -ge 100 ] || { echo "ODMOWA: df / = ${free}G < 100G"; exit 3; }
pgrep -f 'python3.*(backup-mapper-r2|restore-test-mapper|bazaar_crawler\.py)' >/dev/null && { echo "ODMOWA: bieg kopii/crawlera trwa"; exit 3; }
[ "$(sha256sum $B/../nightq-1103-l24/out/rule_C.txt | cut -c1-64)" = 1c9293850560d6680a6ab6f70c9ce8280608f882402557f561562daa1b8808ab ] || { echo "rule_C.txt sha ZMIENIONE"; exit 4; }
R=$B/raw/refresh-${END//:/}; mkdir -p "$R"; cd "$R"
echo "$(date -u +%FT%TZ) refresh END=$END -> $R" | tee -a $B/logs/refresh.log
timeout 600 sqlite3 -cmd 'PRAGMA query_only=1' -cmd '.timeout 30000' 'file:/home/ubuntu/x402-network-mapper/mapper.db?mode=ro' \
  "select snapshot_date, count(*) from bazaar_snapshots where snapshot_date>='2026-08-01' group by snapshot_date order by 1" > snaps_all.txt
WI20_END="$END" timeout 600 python3 $W/ro_run.py $W/s1_extract.py
timeout 600 python3 $W/s2_log.py > s2.txt
mkdir -p ../out  # s3_analyze.py pisze ../out/l24.json (oryginał L-24) = raw/out/ — kopiowane po każdym biegu
WI20_END=2026-11-02T24 timeout 600 python3 $W/s3_analyze.py > s3_b1.txt; cp ../out/l24.json l24_b1.json
WI20_END="$END" timeout 600 python3 $W/s3_analyze.py > s3_end.txt; cp ../out/l24.json l24_end.json
timeout 600 python3 $W/k_analysis.py "$R" "$END" > k.txt
timeout 600 python3 $W/curve3844_v2.py > curve_tue15.txt
timeout 600 python3 $W/curve3844_v2.py "${END%Z}" > curve_end.txt
python3 $W/compare.py "$R" "$REF" | tee compare.txt
