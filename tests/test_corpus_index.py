"""Class 3 rows (source requires_chain_read) in scripts/build_corpus_index.py:
freshness is (block, reader, date), so a read without reader or read_at is refused."""
import contextlib, copy, importlib.util, io, json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_corpus_index", ROOT / "scripts" / "build_corpus_index.py")
bci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bci)

ROW = json.loads((ROOT / "tests" / "fixtures" / "external" / "holistis_settlement_link_kanon.json").read_text())


def test_shipped_row_names_reader_and_date():
    row = bci.external_row(ROW)
    assert row[2] == "requires_chain_read"
    verified = row[5]
    assert verified.startswith("2026-10-26T11:41Z")
    assert "block 48209372 on eip155:84532" in verified
    assert "sepolia.base.org found" in verified
    assert "base-sepolia-rpc.publicnode.com found" in verified
    assert "agent-receipt-verify@0.2.17" in row[7] and "not run" in row[7]


@pytest.mark.parametrize("field", ["reader", "read_at", "read_result"])
def test_read_without_field_is_refused(field):
    ex = copy.deepcopy(ROW)
    del ex["reads"][0][field]
    with pytest.raises(SystemExit, match=field):
        bci.external_row(ex)


@pytest.mark.parametrize("field", ["settlement_chain", "settlement_block", "settlement_ref", "tool", "reads"])
def test_row_without_settlement_field_is_refused(field):
    ex = copy.deepcopy(ROW)
    del ex[field]
    with pytest.raises(SystemExit, match=field):
        bci.external_row(ex)


def test_unknown_read_result_is_refused():
    ex = copy.deepcopy(ROW)
    ex["reads"][1]["read_result"] = "yes"
    with pytest.raises(SystemExit, match="read_result"):
        bci.external_row(ex)


def test_latest_read_wins_and_names_only_its_reader():
    ex = copy.deepcopy(ROW)
    ex["reads"][2]["read_at"] = "2026-11-01T08:00:00Z"
    ex["reads"][2]["read_result"] = "pruned"
    verified = bci.external_row(ex)[5]
    assert verified.startswith("2026-11-01T08:00Z")
    assert "sepolia.base.org pruned" in verified
    assert "publicnode" not in verified


def test_latest_read_without_block_hash_is_refused():
    ex = copy.deepcopy(ROW)
    del ex["reads"][-1]["block_hash"]
    with pytest.raises(SystemExit, match="block_hash"):
        bci.external_row(ex)


def test_cell_shows_full_block_hash_and_read_method():
    verified = bci.external_row(ROW)[5]
    block_hash = ROW["reads"][-1]["block_hash"]
    assert len(block_hash) == 66
    assert f"block 48209372 on eip155:84532, hash {block_hash}," in verified
    assert "via eth_getTransactionReceipt" in verified
    assert f"tx {ROW['settlement_ref']}," in verified
    assert len(ROW['settlement_ref']) == 66


def test_settlement_block_hash_matches_latest_read():
    last = max(rd["read_at"] for rd in ROW["reads"])
    latest = [rd for rd in ROW["reads"] if rd["read_at"] == last]
    assert len(latest) == 2
    assert all(rd["block_hash"] == ROW["settlement_block_hash"] for rd in latest)
    assert all(rd["block"] == ROW["settlement_block"] for rd in latest)
    ex = copy.deepcopy(ROW)
    ex["settlement_block_hash"] = "0x" + "0" * 64
    with pytest.raises(SystemExit, match="settlement_block_hash"):
        bci.external_row(ex)


def test_other_external_rows_carry_their_cell_verbatim():
    ex = json.loads((ROOT / "tests" / "fixtures" / "external" / "tamga_composition_v0.json").read_text())
    assert bci.external_row(ex)[5] == "per push (CI replay)"


def test_index_keeps_existing_distribution_and_adds_class_3():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        bci.main()
    text = out.getvalue()
    # 11 observed since the tokenizen signed-offer row (external rows count; definition unchanged)
    assert "**11 observed, 6 simulated, 2 derived, 1 requires_chain_read.**" in text
    assert "not an availability window" in text
    assert "| holistis_settlement_link_kanon |" in text


def test_unknown_finality_is_refused():
    ex = copy.deepcopy(ROW)
    ex["reads"][-1]["finality"] = "safe"
    with pytest.raises(SystemExit, match="finality"):
        bci.external_row(ex)


def test_cell_shows_finality_with_head_and_not_read_without_it():
    verified = bci.external_row(ROW)[5]
    for rd in ROW["reads"][-2:]:
        host = rd["reader"].split("://", 1)[1]
        assert f"{rd['finality']} (finalized head {rd['finalized_head']} on {host})" in verified
    ex = copy.deepcopy(ROW)
    for rd in ex["reads"][-2:]:
        del rd["finality"], rd["finalized_head"]
    assert "finality: not read," in bci.external_row(ex)[5]


def test_signed_offer_row_loads_with_required_fields():
    ex = json.loads((ROOT / "tests" / "fixtures" / "external" / "tokenizen_signed_offer_v0.json").read_text())
    for k in ("id", "proves", "source", "url", "captured_at", "last_verified_at", "status",
              "offer", "signature_check", "contributor", "command"):
        assert ex.get(k) not in (None, ""), k
    assert ex["source"] == "observed" and ex["status"] == 402
    assert ex["signature_check"] in ("recovered", "invalid", "not_run")
    if ex["signature_check"] == "recovered":
        assert len(ex["recovered_signer"]) == 42
    assert ex["offer"]["format"] == "eip712"
    assert ex["command"] == "`npx -y agent-receipt-verify https://x402.tokenizen.nl/api/bug-intel-quick` @ not run"
    row = bci.external_row(ex)
    assert row[2] == "observed" and row[6] == "holistis"
