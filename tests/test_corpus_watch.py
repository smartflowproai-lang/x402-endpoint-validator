"""Contract tests for the daily corpus watch (scripts/corpus_watch.py).

Two properties are pinned here, both of them ways the watch could report a
success it did not earn:

1. blindness must not look like a pass — an empty route list exits non-zero
   (git ls-tree exits 0 with empty stdout on a path that no longer exists, so
   a moved tests/fixtures/ would otherwise log "0/0 fully matched" and exit 0);
2. a fixture whose expected channel covers the body has its body watched too —
   the header alone matching is not the whole live claim.

The network and git are stubbed; these tests never leave the machine.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"

_spec = importlib.util.spec_from_file_location(
    "corpus_watch", REPO_ROOT / "scripts" / "corpus_watch.py"
)
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)


PAY_TO = "0x" + "11" * 20
ASSET = "0x" + "22" * 20
CHALLENGE = {
    "x402Version": 2,
    "resource": {"url": "https://seller.example/api/thing"},
    "accepts": [
        {
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": "5000",
            "maxAmountRequired": "5000",
            "payTo": PAY_TO,
            "asset": ASSET,
            "maxTimeoutSeconds": 300,
        }
    ],
    "first_call_free": {"eligible_endpoint": True},
}


def _fixture(channel: str, body_obj: dict | None = None) -> dict:
    body = json.dumps(body_obj if body_obj is not None else CHALLENGE)
    header = base64.b64encode(json.dumps(CHALLENGE).encode()).decode()
    return {
        "name": f"seller_{channel}",
        "url": "https://seller.example/api/thing",
        "method": "GET",
        "status": 402,
        "headers": {"content-type": "application/json", "payment-required": header},
        "body": body if channel in ("both", "body") else "",
        "captured_at_utc": "2026-09-01T00:00:00Z",
        "expect": {"passed": True, "channel": channel, "legacy_placement": False},
    }


class WatchHarness:
    """Runs cw.main() against a stubbed origin/main and a stubbed network."""

    def __init__(self, fixtures: dict[str, dict], live: dict | None = None):
        self.fixtures = fixtures  # path -> fixture dict served from origin/main
        self.live = live or {}  # url -> (status, headers, body)
        self.alerts_sent: list[str] = []

    def _git(self, *args):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        r = R()
        if args[0] == "ls-tree":
            r.stdout = "\n".join(self.fixtures)
        elif args[0] == "show":
            path = args[1].split(":", 1)[1]
            if path in self.fixtures:
                r.stdout = json.dumps(self.fixtures[path])
            else:
                r.returncode = 1
        elif args[0] == "rev-parse":
            r.stdout = "0" * 40
        return r

    def _fetch(self, url, method="GET", body=None):
        return self.live.get(url, (None, {"_error": "not stubbed"}, ""))

    def run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.multiple(
                cw,
                BASE=tmp,
                STATE=str(Path(tmp) / "state.json"),
                LOG=str(Path(tmp) / "watch.log"),
                ALERTS=str(Path(tmp) / "alerts.log"),
                git=self._git,
                fetch=self._fetch,
                tg=self.alerts_sent.append,
            ):
                rc = cw.main()
                log = (Path(tmp) / "watch.log").read_text(encoding="utf-8")
                state_path = Path(tmp) / "state.json"
                state = (
                    json.loads(state_path.read_text(encoding="utf-8"))
                    if state_path.exists()
                    else {}
                )
        return rc, log, state


class EmptyRouteListGuardTests(unittest.TestCase):
    """(B) An empty route list is a finding, never a silent 0/0 success."""

    def test_missing_fixtures_path_exits_nonzero_with_finding(self):
        rc, log, state = WatchHarness(fixtures={}).run()
        self.assertNotEqual(rc, 0, "blind run must not exit 0")
        self.assertIn("FINDING: route list empty (fixtures path missing?)", log)
        self.assertNotIn("fully matched", log, "no route was checked, nothing may be claimed")
        self.assertEqual(state, {}, "a blind run must not overwrite state")

    def test_no_live_url_among_fixtures_also_exits_nonzero(self):
        synthetic = _fixture("header")
        synthetic["url"] = "https://example.test/x"
        rc, log, _ = WatchHarness(fixtures={"tests/fixtures/synthetic.json": synthetic}).run()
        self.assertNotEqual(rc, 0)
        self.assertIn("FINDING: route list empty (fixtures path missing?)", log)
        self.assertIn("none carries a live URL", log)

    def test_one_live_route_still_exits_zero(self):
        fx = _fixture("header")
        harness = WatchHarness(
            fixtures={"tests/fixtures/seller.json": fx},
            live={fx["url"]: (402, fx["headers"], "")},
        )
        rc, log, state = harness.run()
        self.assertEqual(rc, 0)
        self.assertIn("1/1 fully matched", log)
        self.assertEqual(state["routes"]["seller_header"]["body_match"], None)
        self.assertIn("body_match=n/a", log)


class BodyChannelWatchTests(unittest.TestCase):
    """(A) A fixture claiming the body channel has its body compared too."""

    def _run(self, channel, live_body):
        fx = _fixture(channel)
        harness = WatchHarness(
            fixtures={"tests/fixtures/seller.json": fx},
            live={fx["url"]: (402, fx["headers"], live_body)},
        )
        rc, log, state = harness.run()
        # alert text goes to Telegram / ALERTS.log, not to watch.log, which
        # records the per-route line and the finding count only
        return rc, log, state["routes"][f"seller_{channel}"], "\n".join(harness.alerts_sent)

    def test_unchanged_body_matches(self):
        rc, log, rec, alerts = self._run("both", json.dumps(CHALLENGE))
        self.assertEqual(rc, 0)
        self.assertTrue(rec["body_match"])
        self.assertIn("body_match=True", log)
        self.assertIn("1/1 fully matched, 0 finding(s)", log)
        self.assertEqual(alerts, "")

    def test_added_body_field_is_drift(self):
        drifted = json.loads(json.dumps(CHALLENGE))
        drifted["first_call_free"]["requires_balance"] = True
        rc, log, rec, alerts = self._run("both", json.dumps(drifted))
        self.assertFalse(rec["body_match"])
        self.assertIn("body_match=False", log)
        self.assertIn("0/1 fully matched, 1 finding(s)", log)
        self.assertIn("BODY DRIFT", alerts)

    def test_body_drift_is_caught_even_though_header_is_identical(self):
        """The exact asterpay shape: header byte-identical, body drifted."""
        drifted = json.loads(json.dumps(CHALLENGE))
        drifted["first_call_free"]["zero_balance_alternative"] = "see freeEndpoints"
        _, _, rec, alerts = self._run("both", json.dumps(drifted))
        self.assertTrue(rec["challenge_match"], "header side must still match")
        self.assertFalse(rec["body_match"])
        self.assertIn("BODY DRIFT", alerts)
        self.assertNotIn("CHALLENGE DRIFT", alerts)

    def test_body_compare_is_the_parsed_object_not_raw_bytes(self):
        """Key order and whitespace are invisible to the validator, so not drift."""
        reordered = json.dumps(
            json.loads(json.dumps(CHALLENGE)), indent=2, sort_keys=True
        )
        _, _, rec, alerts = self._run("both", reordered)
        self.assertNotEqual(reordered, json.dumps(CHALLENGE), "test must actually re-serialise")
        self.assertTrue(rec["body_match"])
        self.assertEqual(alerts, "")

    def test_body_that_stops_parsing_is_drift(self):
        _, _, rec, alerts = self._run("both", "<html>502 Bad Gateway</html>")
        self.assertFalse(rec["body_match"])
        self.assertIn("BODY DRIFT", alerts)

    def test_body_only_channel_is_watched_too(self):
        drifted = json.loads(json.dumps(CHALLENGE))
        drifted["accepts"][0]["amount"] = "9999"
        _, _, rec, alerts = self._run("body", json.dumps(drifted))
        self.assertFalse(rec["body_match"])
        self.assertIn("BODY DRIFT", alerts)

    def test_header_channel_body_is_not_watched(self):
        """A header-channel fixture stores no body claim; live body is not drift."""
        _, log, rec, alerts = self._run("header", '{"anything": true}')
        self.assertIsNone(rec["body_match"])
        self.assertIn("body_match=n/a", log)
        self.assertEqual(alerts, "")


class ExpectChannelResolutionTests(unittest.TestCase):
    """The channel lives under three different key names across fixture generations."""

    def test_expect_key(self):
        self.assertEqual(cw.expect_channel({"expect": {"channel": "header"}}), "header")

    def test_expect_default_key(self):
        self.assertEqual(
            cw.expect_channel({"expect_default": {"channel": "both"}}), "both"
        )

    def test_expect_strict_v2_key(self):
        self.assertEqual(
            cw.expect_channel({"expect_strict_v2": {"channel": "header"}}), "header"
        )

    def test_missing_expectation_is_none(self):
        self.assertIsNone(cw.expect_channel({"name": "x"}))

    def test_real_asterpay_fixtures_resolve_to_both(self):
        """Binds the watch to the corpus: these two are why body compare exists."""
        for name in ("asterpay_crypto_prices", "asterpay_sentiment"):
            fx = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(cw.expect_channel(fx), "both", name)
            self.assertIn(cw.expect_channel(fx), cw.BODY_CHANNELS, name)

    def test_stored_asterpay_bodies_parse_on_the_body_channel(self):
        """A "both" fixture whose body does not parse would report drift forever."""
        for name in ("asterpay_crypto_prices", "asterpay_sentiment"):
            fx = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(
                cw.body_payment_obj(fx["headers"], fx["body"]), name
            )


if __name__ == "__main__":
    unittest.main()
