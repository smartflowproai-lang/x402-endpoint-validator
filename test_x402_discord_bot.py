import pytest
import discord
from datetime import datetime, timezone

from x402_conformance_engine import AuditReport, CheckResult, ManifestResult, Caip2Result, JsonResilienceResult
from x402_discord_bot import build_audit_embed, STATUS_COLORS, STATUS_EMOJI, CHECK_DISPLAY_NAMES


class TestBuildAuditEmbed:
    def _make_report(
        self,
        overall_status: str = "PASS",
        manifest_status: str = "PASS",
        caip2_status: str = "PASS",
        json_status: str = "PASS",
    ) -> AuditReport:
        return AuditReport(
            target_url="https://api.example.com",
            timestamp=datetime.now(timezone.utc),
            overall_status=overall_status,
            checks=[
                ManifestResult(status=manifest_status, message="Manifest OK",
                               details={"url": "https://api.example.com/.well-known/x402", "status_code": 200, "has_accepts": True, "headers": {}}),
                Caip2Result(status=caip2_status, message="CAIP-2 OK",
                            details={"header_present": True, "header_name": "X-Payment-Required", "caip2_value": "eip155:8453", "valid": caip2_status == "PASS"}),
                JsonResilienceResult(status=json_status, message="JSON OK",
                                     details={"status_code": 402, "payload_type": "dict" if json_status == "PASS" else "str", "is_dict": json_status == "PASS"}),
            ],
            summary=f"Overall: {overall_status}",
        )

    def test_pass_embed_color(self):
        report = self._make_report(overall_status="PASS")
        embed = build_audit_embed(report)
        assert embed.colour == discord.Colour(STATUS_COLORS["PASS"])

    def test_fail_embed_color(self):
        report = self._make_report(overall_status="FAIL")
        embed = build_audit_embed(report)
        assert embed.colour == discord.Colour(STATUS_COLORS["FAIL"])

    def test_critical_fail_embed_color(self):
        report = self._make_report(overall_status="CRITICAL_FAIL")
        embed = build_audit_embed(report)
        assert embed.colour == discord.Colour(STATUS_COLORS["CRITICAL_FAIL"])

    def test_error_embed_color(self):
        report = self._make_report(overall_status="ERROR")
        embed = build_audit_embed(report)
        assert embed.colour == discord.Colour(STATUS_COLORS["ERROR"])

    def test_embed_has_three_fields(self):
        report = self._make_report()
        embed = build_audit_embed(report)
        assert len(embed.fields) == 3

    def test_embed_field_names(self):
        report = self._make_report()
        embed = build_audit_embed(report)
        field_names = [f.name for f in embed.fields]
        assert "Manifest Discovery" in field_names
        assert "CAIP-2 Compliance" in field_names
        assert "JSON Resilience" in field_names

    def test_critical_fail_json_has_warning(self):
        report = self._make_report(json_status="CRITICAL_FAIL")
        embed = build_audit_embed(report)
        json_field = next(f for f in embed.fields if f.name == "JSON Resilience")
        assert "crash" in json_field.value.lower()
        assert "strict-v2" in json_field.value.lower()

    def test_critical_fail_json_has_sample(self):
        report = AuditReport(
            target_url="https://api.example.com",
            timestamp=datetime.now(timezone.utc),
            overall_status="CRITICAL_FAIL",
            checks=[
                ManifestResult(status="FAIL", message="No manifest"),
                Caip2Result(status="FAIL", message="No CAIP-2"),
                JsonResilienceResult(
                    status="CRITICAL_FAIL",
                    message="Primitive payload",
                    details={"status_code": 402, "payload_type": "str", "is_dict": False, "sample": "Payment required"},
                ),
            ],
            summary="CRITICAL_FAIL",
        )
        embed = build_audit_embed(report)
        json_field = next(f for f in embed.fields if f.name == "JSON Resilience")
        assert "Payment required" in json_field.value

    def test_caip2_field_shows_network(self):
        report = self._make_report(caip2_status="PASS")
        embed = build_audit_embed(report)
        caip2_field = next(f for f in embed.fields if f.name == "CAIP-2 Compliance")
        assert "eip155:8453" in caip2_field.value

    def test_manifest_field_shows_status_code(self):
        report = self._make_report(manifest_status="PASS")
        embed = build_audit_embed(report)
        manifest_field = next(f for f in embed.fields if f.name == "Manifest Discovery")
        assert "HTTP 200" in manifest_field.value

    def test_embed_title_contains_status(self):
        report = self._make_report(overall_status="PASS")
        embed = build_audit_embed(report)
        assert "PASS" in embed.title

    def test_embed_footer(self):
        report = self._make_report()
        embed = build_audit_embed(report)
        assert "strict-v2" in embed.footer.text


class TestStatusConstants:
    def test_all_statuses_have_colors(self):
        for status in ["PASS", "FAIL", "CRITICAL_FAIL", "ERROR"]:
            assert status in STATUS_COLORS

    def test_all_statuses_have_emoji(self):
        for status in ["PASS", "FAIL", "CRITICAL_FAIL", "ERROR"]:
            assert status in STATUS_EMOJI

    def test_all_check_names_have_display(self):
        for name in ["manifest_discovery", "caip2_compliance", "json_resilience"]:
            assert name in CHECK_DISPLAY_NAMES


class TestX402Bot:
    def test_bot_is_discord_client(self):
        from x402_discord_bot import bot
        assert isinstance(bot, discord.Client)

    def test_bot_has_command_tree(self):
        from x402_discord_bot import bot
        assert hasattr(bot, "tree")
