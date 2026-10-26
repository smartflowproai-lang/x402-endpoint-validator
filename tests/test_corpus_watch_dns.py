"""Daily re-read of dns-txt controller bindings (corpus_watch.reread_dns_bindings)
and the index cell that follows it (build_corpus_index.external_row).

DNS is stubbed (a fake resolver or a fake dig); these tests never leave the machine.
The alert file is a temporary file, never ~/monitoring/ALERTS.log."""
import copy, importlib.util, json, subprocess
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cw = _load("corpus_watch")
bci = _load("build_corpus_index")

SIGNER = "0x" + "aB" * 20
OTHER = "0x" + "cd" * 20
NAME = "_controllers.x402.seller.example"
FX = {
    "id": "seller_signed_offer_v0", "proves": "the signer is bound to the operator domain",
    "source": "observed", "captured_at": "2026-10-26T11:41:12Z",
    "last_verified_at": "2026-10-26T12:38Z (not in the daily watch)",
    "contributor": "someone", "command": "`x` @ not run",
    "recovered_signer": SIGNER,
    "binding": {"method": "dns-txt", "name": NAME, "read_at": "2026-10-26T12:38Z",
                "record": f"v=1;controller=did:pkh:eip155:1:{SIGNER}"},
}


def rec(addr):
    return ("ok", [f"v=1;controller=did:pkh:eip155:1:{addr}"])


def run(reads, tmp_path, prev=None, fixtures=None):
    """reads: resolver -> (status, records)."""
    alerts = tmp_path / "alerts.log"
    with mock.patch.object(cw, "LOG", str(tmp_path / "watch.log")):
        out = cw.reread_dns_bindings(fixtures or [("tests/fixtures/external/x.json", FX)], prev,
                                     resolve=lambda name, r: reads[r], alerts_path=str(alerts))
    return out, (alerts.read_text() if alerts.exists() else "")


@pytest.mark.parametrize("reads,result", [
    ({"system": rec(SIGNER.lower()), "1.1.1.1": rec(SIGNER.upper().replace("0X", "0x"))}, "same"),
    ({"system": rec(SIGNER), "1.1.1.1": rec(OTHER)}, "changed"),
    ({"system": ("ok", ["v=1;something-else"]), "1.1.1.1": rec(OTHER)}, "changed"),
    ({"system": ("nxdomain", []), "1.1.1.1": ("nxdomain", [])}, "nxdomain"),
    ({"system": ("nodata", []), "1.1.1.1": ("nxdomain", [])}, "nxdomain"),
    ({"system": ("error", ["timeout"]), "1.1.1.1": ("error", ["SERVFAIL"])}, "error"),
    # fail-closed: one resolver confirming is not enough
    ({"system": rec(SIGNER), "1.1.1.1": ("error", ["timeout"])}, "error"),
    ({"system": rec(SIGNER), "1.1.1.1": ("nxdomain", [])}, "nxdomain"),
])
def test_result(reads, result, tmp_path):
    out, alerts = run(reads, tmp_path)
    r = out[NAME]
    assert r["binding_reread_result"] == result
    assert r["binding_reread_at"].endswith("+00:00")
    assert r["binding_resolvers"][0].startswith("system ") and r["binding_resolvers"][1].startswith("1.1.1.1 ")
    if result in ("changed", "nxdomain"):
        assert f"UWAGA corpus-watch: binding {NAME} {result}" in alerts
    else:
        assert alerts == ""


def test_record_seen_is_stored(tmp_path):
    out, _ = run({"system": rec(OTHER), "1.1.1.1": rec(OTHER)}, tmp_path)
    assert out[NAME]["binding_record_seen"] == [f"v=1;controller=did:pkh:eip155:1:{OTHER}"]


def test_alert_only_on_transition_and_since_is_kept(tmp_path):
    reads = {"system": rec(OTHER), "1.1.1.1": rec(OTHER)}
    first, a1 = run(reads, tmp_path)
    prev = copy.deepcopy(first)
    prev[NAME]["binding_result_since"] = "2026-10-27T06:25:00+00:00"
    second, a2 = run(reads, tmp_path, prev)
    assert a2.count("UWAGA") == 1  # same file, no second line
    assert second[NAME]["binding_result_since"] == "2026-10-27T06:25:00+00:00"


def test_rows_without_dns_binding_are_skipped_and_fixture_untouched(tmp_path):
    fx = copy.deepcopy(FX)
    other = {"id": "plain", "binding": {"method": "something"}}
    out, _ = run({"system": rec(SIGNER), "1.1.1.1": rec(SIGNER)}, tmp_path,
                 fixtures=[("a.json", fx), ("b.json", other), ("c.json", {"id": "none"})])
    assert list(out) == [NAME]
    assert fx == FX


def test_shipped_signed_offer_row_is_picked_up(tmp_path):
    ex = json.loads((ROOT / "tests/fixtures/external/tokenizen_signed_offer_v0.json").read_text())
    signer = ex["recovered_signer"]
    out, _ = run({"system": rec(signer), "1.1.1.1": rec(signer)}, tmp_path,
                 fixtures=[("t.json", ex)])
    assert out[ex["binding"]["name"]]["binding_reread_result"] == "same"


# --- dig parsing -------------------------------------------------------------

DIG_OK = f""";; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1
{NAME}. 300 IN TXT "v=1;controller=did:pkh:eip155:1:" "{SIGNER}"
"""
DIG_NX = ";; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 2\n"
DIG_NODATA = ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 3\n"
DIG_SERVFAIL = ";; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 4\n"


@pytest.mark.parametrize("stdout,status", [
    (DIG_OK, "ok"), (DIG_NX, "nxdomain"), (DIG_NODATA, "nodata"), (DIG_SERVFAIL, "error"),
    (";; connection timed out; no servers could be reached\n", "error"),
])
def test_dig_txt_parses(stdout, status):
    cp = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
    with mock.patch.object(cw.subprocess, "run", return_value=cp) as run_:
        st, records = cw.dig_txt(NAME, "1.1.1.1")
    assert st == status
    assert run_.call_args.args[0][-1] == "@1.1.1.1"
    assert run_.call_args.kwargs["timeout"] == 10
    if status == "ok":
        assert records == [f"v=1;controller=did:pkh:eip155:1:{SIGNER}"]


def test_dig_timeout_is_error():
    with mock.patch.object(cw.subprocess, "run", side_effect=subprocess.TimeoutExpired("dig", 10)) as run_:
        assert cw.dig_txt(NAME, "system")[0] == "error"
    assert not any(a.startswith("@") for a in run_.call_args.args[0])


# --- index cell ----------------------------------------------------------------

def state(result, at="2026-10-27T06:25:03+00:00", since=None):
    return {NAME: {"binding_reread_at": at, "binding_reread_result": result,
                   "binding_resolvers": ["system ok", "1.1.1.1 ok"],
                   "binding_record_seen": [], "binding_result_since": since or at}}


def test_cell_without_state_keeps_fixture_text():
    row = bci.external_row(FX, {})
    assert row[5] == FX["last_verified_at"] and row[1] == FX["proves"]
    assert bci.external_row(FX)[5] == FX["last_verified_at"]


def test_cell_same():
    row = bci.external_row(FX, state("same"))
    assert row[5] == "bound (record re-read 2026-10-27T06:25Z via system, 1.1.1.1: same)"
    assert row[1] == FX["proves"]


@pytest.mark.parametrize("result,cell", [
    ("changed", "binding_changed since 2026-10-27T06:25Z"),
    ("nxdomain", "record missing 2026-10-28T06:25Z"),
    ("error", "re-read failed 2026-10-28T06:25Z"),
])
def test_cell_not_same_drops_bound(result, cell):
    row = bci.external_row(FX, state(result, at="2026-10-28T06:25:01+00:00",
                                     since="2026-10-27T06:25:02+00:00"))
    assert row[5] == cell
    assert "bound (" not in row[5] and "is bound" not in row[1]
    assert "was bound on 2026-10-26" in row[1]


def test_generator_reads_bindings_from_watch_state(tmp_path, monkeypatch, capsys):
    ex = json.loads((ROOT / "tests/fixtures/external/tokenizen_signed_offer_v0.json").read_text())
    st = tmp_path / "state.json"
    st.write_text(json.dumps({"checked_at": "x", "routes": {},
                              "bindings": {ex["binding"]["name"]: state("nxdomain")[NAME]}}))
    monkeypatch.setattr(bci, "WATCH_STATE", str(st))
    bci.main()
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("| tokenizen_signed_offer_v0 |"))
    assert "record missing 2026-10-27T06:25Z" in line and "is bound" not in line
