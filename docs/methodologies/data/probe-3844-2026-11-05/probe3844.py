#!/usr/bin/env python3
# Sonda: GET bez płatności + POST bez ciała dla raw/sample.jsonl. ≤4 wątki, ≤5 req/s globalnie, twardy limit 1900 żądań.
# Bez nagłówków płatności, bez przekierowań, bez retry poza 1× po 30 s dla wyniku "transport".
import json, time, threading, random, sys, requests
from concurrent.futures import ThreadPoolExecutor
UA = "x402-network-mapper/0.1 (+research; contact: info@smartflowproai.com)"
HDR = {"User-Agent": UA, "Accept": "application/json"}
LIMIT, RATE, WORKERS, TO = 1900, 5.0, 4, 10
lock = threading.Lock(); count = [0]; next_slot = [time.monotonic()]
reqlog = open("raw/requests.log", "a")
def take():
    with lock:
        if count[0] >= LIMIT: raise RuntimeError("LIMIT")
        now = time.monotonic(); t = max(now, next_slot[0]); next_slot[0] = t + 1.0 / RATE; count[0] += 1; n = count[0]
    time.sleep(max(0, t - time.monotonic())); return n
def classify(code, headers, body):
    if code == 402:
        b = body[:200000].decode("utf-8", "replace")
        if any(k.lower() == "payment-required" for k in headers) or "x402Version" in b or '"accepts"' in b: return "402_x402"
        return "402_other"
    if 200 <= code < 300: return "2xx"
    if 300 <= code < 400: return "3xx"
    if code == 530: return "530"
    if 400 <= code < 500: return "4xx_other"
    if code >= 500: return "5xx_other"
    return "other"
def one(method, url):
    n = take(); t0 = time.monotonic(); ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        h = dict(HDR)
        if method == "POST": h["Content-Length"] = "0"
        r = requests.request(method, url, headers=h, timeout=TO, allow_redirects=False)
        body = r.content; dt = time.monotonic() - t0
        res = {"cls": classify(r.status_code, r.headers, body), "code": r.status_code, "ms": round(dt*1000), "size": len(body),
               "server": r.headers.get("server"), "pr_hdr": "payment-required" in {k.lower() for k in r.headers},
               "ctype": r.headers.get("content-type"), "snip": body[:240].decode("utf-8", "replace")}
    except Exception as e:
        res = {"cls": "transport", "code": None, "ms": round((time.monotonic()-t0)*1000), "size": None, "server": None, "err": type(e).__name__ + ": " + str(e)[:200]}
    res["ts"] = ts
    with lock: reqlog.write(f"{n} {ts} {method} {res['cls']} {res['code']}\n"); reqlog.flush()
    return res
def job(item):
    out = dict(item)
    for m in ("GET", "POST"): out[m] = one(m, item["url"])
    return out
items = [json.loads(l) for l in open("raw/sample.jsonl")]
random.Random(20261105).shuffle(items)   # przeplot populacji w czasie
t_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
with ThreadPoolExecutor(WORKERS) as ex: results = list(ex.map(job, items))
# retry 1× po 30 s dla (url, metoda) z wynikiem transport
todo = [(r, m) for r in results for m in ("GET", "POST") if r[m]["cls"] == "transport"]
if todo:
    time.sleep(30)
    def rj(rm): r, m = rm; r[m]["retry_result"] = one(m, r["url"])
    with ThreadPoolExecutor(WORKERS) as ex: list(ex.map(rj, todo))
with open("raw/results.jsonl", "w") as f:
    for r in results: f.write(json.dumps(r) + "\n")
t_end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
json.dump({"start": t_start, "end": t_end, "requests": count[0], "retries": len(todo), "limit": LIMIT, "rate": RATE, "workers": WORKERS, "ua": UA}, open("raw/probe_meta.json", "w"))
print(t_start, t_end, "requests", count[0], "retries", len(todo))
