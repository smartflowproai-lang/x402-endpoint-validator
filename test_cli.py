import json
import os
import pytest

from x402_validator.cli import (
    read_urls_from_file,
    report_to_row,
    write_csv,
    write_json,
    write_html,
    audit_command,
)
from x402_validator._engine import (
    AuditReport,
    ManifestResult,
    Caip2Result,
    JsonResilienceResult,
    BazaarResult,
)
from datetime import datetime, timezone


def make_report(
    url: str,
    status: str = "PASS",
    manifest: str = "PASS",
    caip2: str = "PASS",
    json_res: str = "PASS",
    bazaar: str = "PASS",
) -> AuditReport:
    return AuditReport(
        target_url=url,
        timestamp=datetime.now(timezone.utc),
        overall_status=status,
        checks=[
            ManifestResult(status=manifest, message="ok"),
            Caip2Result(status=caip2, message="ok"),
            JsonResilienceResult(status=json_res, message="ok"),
            BazaarResult(status=bazaar, message="ok"),
        ],
        summary="",
    )


class TestReadUrlsFromFile:
    def test_reads_urls(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://a.com\nhttps://b.com\n")
        urls = read_urls_from_file(str(f))
        assert urls == ["https://a.com", "https://b.com"]

    def test_skips_blanks_and_comments(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("# comentario\nhttps://a.com\n\nhttps://b.com\n")
        urls = read_urls_from_file(str(f))
        assert urls == ["https://a.com", "https://b.com"]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        urls = read_urls_from_file(str(f))
        assert urls == []


class TestReportToRow:
    def test_converts_report(self):
        r = make_report("https://test.com", status="PASS")
        row = report_to_row(r)
        assert row["url"] == "https://test.com"
        assert row["overall_status"] == "PASS"
        assert row["manifest_discovery"] == "PASS"
        assert row["bazaar_compliance"] == "PASS"

    def test_failed_report(self):
        r = make_report("https://fail.com", status="FAIL", manifest="FAIL")
        row = report_to_row(r)
        assert row["overall_status"] == "FAIL"
        assert row["manifest_discovery"] == "FAIL"


class TestWriteCsv:
    def test_writes_csv(self, tmp_path):
        reports = [make_report("https://a.com"), make_report("https://b.com", status="FAIL")]
        p = str(tmp_path / "out.csv")
        write_csv(reports, p)
        with open(p) as f:
            content = f.read()
        assert "https://a.com" in content
        assert "https://b.com" in content
        assert "overall_status" in content


class TestWriteJson:
    def test_writes_json(self, tmp_path):
        reports = [make_report("https://a.com")]
        p = str(tmp_path / "out.json")
        write_json(reports, p)
        with open(p) as f:
            data = json.load(f)
        assert data["total"] == 1
        assert data["results"][0]["target_url"] == "https://a.com"


class TestWriteHtml:
    def test_writes_html(self, tmp_path):
        reports = [make_report("https://a.com"), make_report("https://b.com", status="FAIL")]
        p = str(tmp_path / "out.html")
        write_html(reports, p)
        with open(p) as f:
            content = f.read()
        assert "<table>" in content
        assert "https://a.com" in content
        assert "PASS" in content
        assert "FAIL" in content


class TestAuditCommand:
    """``audit_command`` accepts both ``list[str]`` and ``str`` for ``output``."""

    def test_list_output(self, tmp_path):
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.com\nhttps://b.com\n")
        mock_reports = [make_report("https://a.com"), make_report("https://b.com")]
        audit_command(
            str(urls_file),
            output=["csv"],
            output_path=str(tmp_path / "res.csv"),
            results=mock_reports,
        )
        assert os.path.exists(str(tmp_path / "res.csv"))

    def test_string_output_backward_compat(self, tmp_path):
        """Single string is treated as one-element list — keeps old test contracts working."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.com\n")
        mock_reports = [make_report("https://a.com")]
        audit_command(
            str(urls_file),
            output="csv",
            output_path=str(tmp_path / "res.csv"),
            results=mock_reports,
        )
        assert os.path.exists(str(tmp_path / "res.csv"))

    def test_multi_format(self, tmp_path):
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.com\n")
        mock_reports = [make_report("https://a.com")]
        audit_command(
            str(urls_file),
            output=["csv", "json"],
            output_path=None,
            results=mock_reports,
        )
        # Without a single-format output_path the writers use <base>.<ext> names
        expected_csv = tmp_path / "urls_results.csv"
        expected_json = tmp_path / "urls_results.json"
        assert expected_csv.exists()
        assert expected_json.exists()

    def test_unknown_format_rejected(self, tmp_path):
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.com\n")
        mock_reports = [make_report("https://a.com")]
        with pytest.raises(SystemExit) as exc_info:
            audit_command(
                str(urls_file),
                output=["bogus"],
                output_path=None,
                results=mock_reports,
            )
        assert exc_info.value.code == 2
