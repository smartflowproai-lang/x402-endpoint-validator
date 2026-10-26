#!/usr/bin/env python3
"""build_corpus_index.py — the conformance-corpus vector index, generated, never hand-typed.

Reads every tests/fixtures/*.json plus git history and the corpus-watch state,
emits a markdown table with one row per vector. Columns follow the terms agreed
in x402#3396: source enum (simulated/observed/derived, plus requires_chain_read
for rows whose claim needs a chain reader), captured_at to the
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

READ_RESULTS = ("found", "not_found", "pruned")
CHAIN_READ_FIELDS = ("settlement_chain", "settlement_block", "settlement_ref", "tool", "reads")

def chain_read_verified(ex):
    """last_verified_at for a requires_chain_read row: the latest node read, with
    its reader named. One read proves presence on that reader on that date, not an
    availability window, so a read without reader or read_at is refused, not guessed."""
    rid = ex.get("id", "?")
    missing = [k for k in CHAIN_READ_FIELDS if ex.get(k) in (None, "", [])]
    if missing:
        raise SystemExit(f"{rid}: requires_chain_read row missing {', '.join(missing)}")
    for i, rd in enumerate(ex["reads"]):
        for k in ("reader", "read_at", "read_result"):
            if not rd.get(k):
                raise SystemExit(f"{rid}: read {i} has no {k}")
        if rd["read_result"] not in READ_RESULTS:
            raise SystemExit(f"{rid}: read {i} read_result {rd['read_result']!r} not in {READ_RESULTS}")
    last = max(rd["read_at"] for rd in ex["reads"])
    latest = [rd for rd in ex["reads"] if rd["read_at"][:16] == last[:16]]
    # The block number alone does not pin the block on a chain that can reorg;
    # the read that sets last_verified_at must carry the block hash it saw.
    for rd in latest:
        if not rd.get("block_hash"):
            raise SystemExit(f"{rid}: latest read from {rd['reader']} has no block_hash")
    hashes = sorted({rd["block_hash"] for rd in latest})
    if ex.get("settlement_block_hash") and hashes != [ex["settlement_block_hash"]]:
        raise SystemExit(f"{rid}: settlement_block_hash differs from the block_hash of the latest read")
    methods = sorted({rd.get("method") or "method not recorded" for rd in latest})
    readers = ", ".join(f"{re.sub(r'^https?://', '', rd['reader'])} {rd['read_result']}" for rd in latest)
    return (f"{last[:16]}Z, block {ex['settlement_block']} on {ex['settlement_chain']}, "
            f"hash {' / '.join(hashes)}, tx {ex['settlement_ref']}, via {', '.join(methods)}, read from node: {readers}")

def external_row(ex):
    verified = chain_read_verified(ex) if ex["source"] == "requires_chain_read" else ex["last_verified_at"]
    command = ex["command"]
    for nr in ex.get("tool_not_run", []):
        command += f"; {nr}"
    return (ex["id"], ex["proves"], ex["source"], ex["captured_at"],
            ex.get("captured_at_note", ""), verified, ex["contributor"], command)

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

    # Contributed rows (tests/fixtures/external/*.json): carried verbatim, one file
    # per row, cells cut from the contributor's own vector files per the #3396
    # convention. Not loaded by the pytest corpus — their verification command
    # points at the contributor's suite, pinned to the contributor's tag.
    external_dir = os.path.join(FIXTURES, "external")
    if os.path.isdir(external_dir):
        for fn in sorted(os.listdir(external_dir)):
            if not fn.endswith(".json"):
                continue
            ex = json.load(open(os.path.join(external_dir, fn)))
            rows.append(external_row(ex))

    n_obs = sum(1 for r in rows if r[2] == "observed")
    n_sim = sum(1 for r in rows if r[2] == "simulated")
    n_der = sum(1 for r in rows if r[2] == "derived")
    n_chain = sum(1 for r in rows if r[2] == "requires_chain_read")
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
    if n_chain:
        print(f"**Class 3, `requires_chain_read`.** The claim needs a chain reader; freshness is (block, reader, "
              f"date), one read proves presence on that reader on that date, not an availability window. For "
              f"these rows `last_verified_at` is the last read of the settlement from a node, with the reader "
              f"named, not the unpaid preflight; a row without reader or read date is refused by the generator. "
              f"The cell gives the block hash the latest read saw, in full, next to the block number, and a "
              f"latest read without a block hash is refused. They are not in the daily watch.")
        print()
    chain_part = f", {n_chain} requires_chain_read" if n_chain else ""
    if n_der:
        print(f"Distribution: **{n_obs} observed, {n_sim} simulated, {n_der} derived{chain_part}.** Derived vectors follow "
              f"the thread convention: captured_at is the transformation date (or TBD), verification is per push "
              f"(CI replay), host_ref is n/a.")
    else:
        print(f"Distribution: **{n_obs} observed, {n_sim} simulated, 0 derived{chain_part}.** We contribute no `derived` "
              f"vectors yet; if your eight families include transformations, you define that value in practice.")
    print()
    print("| id | proves | source | captured_at | last_verified_at | contributor | command@tag |")
    print("|---|---|---|---|---|---|---|")
    for vid, proves, source, cap, cap_note, verified, contrib, cmd in rows:
        cap_cell = cap if cap in ("n/a",) else (f"{cap}" if cap != "TBD" else f"TBD ({cap_note})")
        print(f"| {vid} | {proves} | {source} | {cap_cell} | {verified} | {contrib} | {cmd} |")

if __name__ == "__main__":
    main()
