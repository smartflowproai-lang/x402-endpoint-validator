#!/usr/bin/env python3
"""build_corpus_index.py — the conformance-corpus vector index, generated, never hand-typed.

Reads every tests/fixtures/*.json plus git history and the corpus-watch state,
emits a markdown table with one row per vector. Columns follow the terms agreed
in x402#3396: source enum (simulated/observed/derived), captured_at to the
minute, last_verified_at as the freshness half of the (claim, freshness) pair,
contributor without e-mail addresses, and a regenerating command pinned to an
exact tag.

Usage: python3 scripts/build_corpus_index.py [TAG] > docs/corpus-index.md
"""
import json, os, re, subprocess, sys, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
WATCH_STATE = os.path.expanduser("~/corpus-watch/state.json")
TAG = sys.argv[1] if len(sys.argv) > 1 else "v1.5.1"

# contributor = GitHub handle of the author of the vector's first commit.
# Never an e-mail address in the output: noreply addresses carry the handle,
# the rest are mapped here explicitly.
EMAIL_TO_HANDLE = {
    "smartflowpro.ai@gmail.com": "smartflowproai-lang",
    "a.gentry@terradeed.co.uk": "terradeed",
    "globalsoilintelligenceproject@gmail.com": "Jdhart82",
}

def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True, timeout=60).stdout

def contributor(path):
    line = git("log", "--diff-filter=A", "--format=%an|%ae", "--", path).strip().splitlines()
    if not line:
        return "unknown"
    name, email = line[-1].split("|", 1)
    m = re.match(r"\d+\+(.+)@users\.noreply\.github\.com$", email)
    if m:
        return m.group(1)
    return EMAIL_TO_HANDLE.get(email, name)

def captured_at(fx, path):
    for key in ("captured_at_utc", "captured_at", "capture_date"):
        if fx.get(key):
            val = fx[key]
            return (val, key) if "T" in val else (val, key + " (date only)")
    first = git("log", "--diff-filter=A", "--format=%ad", "--date=format:%Y-%m-%d", "--", path).strip().splitlines()
    committed = first[-1] if first else "?"
    return ("TBD", f"no capture field; first committed {committed} (commit date is not capture time)")

def watch_verified():
    """fixture path -> (checked_at, fully_matched) from the last corpus-watch run."""
    if not os.path.exists(WATCH_STATE):
        return {}
    s = json.load(open(WATCH_STATE))
    out = {}
    for rec in s.get("routes", {}).values():
        ok = (rec.get("status_match") and rec.get("challenge_match")
              and rec.get("body_match") is not False)
        out[rec.get("fixture")] = (s.get("checked_at", "?"), ok,
                                   rec.get("volatile_masked"))
    return out

def main():
    watch = watch_verified()
    rows = []
    for fn in sorted(os.listdir(FIXTURES)):
        if not fn.endswith(".json"):
            continue
        path = f"tests/fixtures/{fn}"
        fx = json.load(open(os.path.join(FIXTURES, fn)))
        vid = fn[:-5]
        source = fx.get("source") or ("simulated" if fx.get("constructed") else ("observed" if fx.get("url") else "simulated"))
        cap, cap_note = captured_at(fx, path)
        if source == "simulated":
            cap, cap_note = "n/a", "constructed"
        w = watch.get(path)
        if source in ("simulated", "derived"):
            verified = "per push (CI replay)"
        elif w and w[1]:
            verified = w[0][:16] + "Z"
            if w[2]:
                verified += f" (volatile masked: {w[2]})"
        elif w:
            verified = w[0][:16] + "Z (DRIFTED)"
        else:
            verified = "not in last watch run"
        proves = fx.get("proves", "(no proves declared)")
        cmd = f"`pytest tests/test_fixtures_corpus.py -k {vid}` @ {TAG}"
        rows.append((vid, proves, source, cap if cap == "n/a" or cap == "TBD" else cap,
                     cap_note, verified, contributor(path), cmd))

    n_obs = sum(1 for r in rows if r[2] == "observed")
    n_sim = sum(1 for r in rows if r[2] == "simulated")
    n_der = sum(1 for r in rows if r[2] == "derived")
    head_sha = git("rev-parse", "--short", TAG + "^{commit}").strip() or git("rev-parse", "--short", "HEAD").strip()
    today = datetime.date.today().isoformat()

    print(f"# Conformance corpus — vector index (first cut)")
    print()
    print(f"Generated {today} by `scripts/build_corpus_index.py` from the fixtures at `{TAG}` (commit `{head_sha}`). "
          f"Regenerate, do not edit: every cell comes from the vector file, git history, or the daily watch state.")
    print()
    print(f"**Disclosure note.** These {n_obs} observed vectors have carried full URLs in the public "
          f"repository since July, with route operators either contributing the capture themselves or "
          f"named in provenance. The `host_ref` pseudonymisation agreed in the thread applies to vectors "
          f"contributed FROM NOW ON whose operators have not seen the capture, not retroactively to these.")
    print()
    print(f"**Freshness.** `captured_at` is the claim's birth date; `last_verified_at` is the last time the "
          f"daily unpaid preflight matched the stored challenge (the (claim, freshness) pair from the thread). "
          f"Volatile clock fields, where declared, are masked before the verdict.")
    print()
    if n_der:
        print(f"Distribution: **{n_obs} observed, {n_sim} simulated, {n_der} derived.** Derived vectors follow "
              f"the thread convention: captured_at is the transformation date (or TBD), verification is per push "
              f"(CI replay), host_ref is n/a.")
    else:
        print(f"Distribution: **{n_obs} observed, {n_sim} simulated, 0 derived.** We contribute no `derived` "
              f"vectors yet; if your eight families include transformations, you define that value in practice.")
    print()
    print("| id | proves | source | captured_at | last_verified_at | contributor | command@tag |")
    print("|---|---|---|---|---|---|---|")
    for vid, proves, source, cap, cap_note, verified, contrib, cmd in rows:
        cap_cell = cap if cap in ("n/a",) else (f"{cap}" if cap != "TBD" else f"TBD ({cap_note})")
        print(f"| {vid} | {proves} | {source} | {cap_cell} | {verified} | {contrib} | {cmd} |")

if __name__ == "__main__":
    main()
