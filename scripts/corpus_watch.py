#!/usr/bin/env python3
"""
corpus-watch — daily unpaid-preflight freshness check for EVERY live-host fixture in the corpus.

Generalises the per-seller viridis-watch (which additionally verifies the seller's
sha256 pin and stays as the PR #14 commitment) to the whole corpus. The route list
is NOT maintained by hand: every tests/fixtures/*.json on origin/main that carries
a real live URL is included automatically the moment it lands on main.

Per fixture:
  1. read the fixture bytes from origin/main (git fetch first; working tree untouched)
  2. issue the same unpaid preflight (method + request_body if present, no payment)
  3. compare returned status against fixture "status" and the PAYMENT-REQUIRED
     challenge header against the stored one

Drift semantics:
  challenge_match=False  -> the live endpoint no longer constructs the challenge
                            captured in the fixture (re-capture needed)
  status drift / timeout -> endpoint moved or died; fixture keeps testing the
                            parser but stops being a live claim

State: state.json (alert only when a route's signature changes = dedup).
Log: watch.log. Alerts: Telegram + ~/monitoring/ALERTS.log.
Excluded automatically: fixtures without "url", constructed ones, example.test hosts.
"""
import json, hashlib, os, subprocess, sys, datetime, urllib.request, urllib.error

REPO = os.path.expanduser("~/x402-endpoint-validator")
BASE = os.path.expanduser("~/corpus-watch")
STATE = os.path.join(BASE, "state.json")
LOG = os.path.join(BASE, "watch.log")
ALERTS = os.path.expanduser("~/monitoring/ALERTS.log")
UA = "SmartFlow-corpus-watch/1.0 (+https://github.com/smartflowproai-lang/x402-endpoint-validator)"
TIMEOUT = 20
EXCLUDED_HOSTS = ("example.test",)

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

def log(msg):
    line = f"[{now()}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def tg(msg):
    creds = os.path.expanduser("~/.secrets/tg-credentials")
    if not os.path.exists(creds):
        log("TG: no credentials, skipping")
        return
    env = {}
    for line in open(creds):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    tok, chat = env.get("TG_TOKEN"), env.get("TG_CHAT")
    if not (tok and chat):
        log("TG: incomplete credentials")
        return
    subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-X", "POST",
         f"https://api.telegram.org/bot{tok}/sendMessage",
         "-d", f"chat_id={chat}", "--data-urlencode", f"text={msg}"],
        timeout=20, check=False)
    log("TG: alert sent")

def fetch(url, method="GET", body=None):
    h = {"User-Agent": UA}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)
    except Exception as e:
        return None, {"_error": str(e)}

def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True, timeout=60)

def live_fixtures():
    """Every fixture on origin/main with a real live URL. No hand-maintained list."""
    ls = git("ls-tree", "--name-only", "origin/main", "tests/fixtures/")
    for path in ls.stdout.split():
        if not path.endswith(".json"):
            continue
        show = git("show", f"origin/main:{path}")
        if show.returncode != 0:
            log(f"WARN: cannot read {path} from origin/main")
            continue
        try:
            fx = json.loads(show.stdout)
        except json.JSONDecodeError:
            log(f"WARN: {path} is not valid json on origin/main")
            continue
        url = fx.get("url", "")
        if not url or fx.get("constructed") or any(h in url for h in EXCLUDED_HOSTS):
            continue
        yield path, fx

def main():
    os.makedirs(BASE, exist_ok=True)
    f = git("fetch", "origin", "main", "-q")
    if f.returncode != 0:
        log(f"ERROR: git fetch failed: {f.stderr.strip()[:200]}")
        tg("corpus-watch: git fetch failed, watch did not run")
        return 1

    prev = json.load(open(STATE)) if os.path.exists(STATE) else {}
    state = {"checked_at": now(), "origin_main": git("rev-parse", "origin/main").stdout.strip(), "routes": {}}
    alerts, matched = [], 0

    for path, fx in live_fixtures():
        name = fx.get("name", path.split("/")[-1])
        stored_hdr = (fx.get("headers") or {}).get("payment-required", "")
        exp_status = fx.get("status", 402)
        st, hdrs = fetch(fx["url"], method=fx.get("method", "GET"),
                         body=fx.get("request_body"))
        live_hdr = ""
        for k, v in hdrs.items():
            if k.lower() == "payment-required":
                live_hdr = v
                break
        rec = {
            "fixture": path,
            "url": fx["url"],
            "live_status": st,
            "status_match": (st == exp_status),
            "challenge_match": bool(stored_hdr) and (live_hdr == stored_hdr),
            "capture_field": ("captured_at_utc" if "captured_at_utc" in fx
                              else "captured_at" if "captured_at" in fx
                              else "capture_date" if "capture_date" in fx
                              else "git_history"),
            "capture_value": fx.get("captured_at_utc") or fx.get("captured_at")
                             or fx.get("capture_date") or None,
        }
        rec["signature"] = f"{rec['live_status']}|{rec['status_match']}|{rec['challenge_match']}"
        state["routes"][name] = rec

        if st is None:
            alerts.append(f"UNREACHABLE {name}: {hdrs.get('_error','?')[:80]}")
        elif st != exp_status:
            alerts.append(f"STATUS DRIFT {name}: fixture {exp_status} -> live {st}")
        elif not stored_hdr:
            log(f"{name}: no stored payment-required header, status-only check")
        elif live_hdr != stored_hdr:
            alerts.append(f"CHALLENGE DRIFT {name}: stored {len(stored_hdr)}B vs live {len(live_hdr)}B "
                          f"(capture {rec['capture_field']}={rec['capture_value']})")
        if rec["status_match"] and (not stored_hdr or rec["challenge_match"]):
            matched += 1
        log(f"{name}: status={st} status_match={rec['status_match']} challenge_match={rec['challenge_match']}")

    json.dump(state, open(STATE, "w"), indent=2)
    total = len(state["routes"])
    log(f"run done: {matched}/{total} fully matched, {len(alerts)} finding(s)")

    changed = any(
        rec.get("signature") != prev.get("routes", {}).get(name, {}).get("signature")
        for name, rec in state["routes"].items()
    ) or set(state["routes"]) != set(prev.get("routes", {}))
    if alerts and not changed:
        log("state unchanged since previous run (known drift, already reported) - alert suppressed")
        alerts = []

    if alerts:
        msg = "corpus-watch: DRIFT DETECTED\n\n" + "\n".join("- " + a for a in alerts)
        tg(msg)
        with open(ALERTS, "a") as f:
            f.write(f"[corpus-watch {now()}] {'; '.join(alerts)}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
