import asyncio
import csv
import os
import pytest
import tempfile
from unittest.mock import AsyncMock, patch

from batch_validator import (
    audit_single_url,
    read_urls_from_csv,
    write_results_to_csv,
    print_summary,
    run_batch,
)
from x402_conformance_engine import AuditReport, CheckResult, ManifestResult, Caip2Result, JsonResilienceResult
from datetime import datetime, timezone


@pytest.fixture
def sample_csv(tmp_path):
    csv_path = str(tmp_path / "test_input.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "name"])
        writer.writeheader()
        writer.writerow({"url": "https://api.example.com", "name": "Example"})
        writer.writerow({"url": "https://other.example.com", "name": "Other"})
    return csv_path


@pytest.fixture
def sample_csv_no_url_column(tmp_path):
    csv_path = str(tmp_path / "bad.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["endpoint", "name"])
        writer.writeheader()
        writer.writerow({"endpoint": "https://api.example.com", "name": "Example"})
    return csv_path


@pytest.fixture
def sample_csv_empty(tmp_path):
    csv_path = str(tmp_path / "empty.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url"])
        writer.writeheader()
    return csv_path


class TestReadUrlsFromCsv:
    def test_reads_urls_correctly(self, sample_csv):
        urls = read_urls_from_csv(sample_csv)
        assert len(urls) == 2
        assert "https://api.example.com" in urls
        assert "https://other.example.com" in urls

    def test_custom_column_name(self, sample_csv):
        urls = read_urls_from_csv(sample_csv, url_column="name")
        assert len(urls) == 2
        assert "Example" in urls

    def test_missing_column_exits(self, sample_csv_no_url_column):
        with pytest.raises(SystemExit):
            read_urls_from_csv(sample_csv_no_url_column)

    def test_empty_csv_returns_empty(self, sample_csv_empty):
        urls = read_urls_from_csv(sample_csv_empty)
        assert urls == []


class TestWriteResultsToCsv:
    def test_writes_results_correctly(self, tmp_path):
        output_path = str(tmp_path / "output.csv")
        results = [
            {
                "url": "https://api.example.com",
                "overall_status": "PASS",
                "manifest_status": "PASS",
                "caip2_status": "PASS",
                "json_resilience_status": "PASS",
            }
        ]
        write_results_to_csv(results, output_path)

        with open(output_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["url"] == "https://api.example.com"
        assert rows[0]["overall_status"] == "PASS"
        assert rows[0]["manifest_status"] == "PASS"
        assert rows[0]["caip2_status"] == "PASS"
        assert rows[0]["json_resilience_status"] == "PASS"

    def test_writes_multiple_rows(self, tmp_path):
        output_path = str(tmp_path / "output.csv")
        results = [
            {"url": f"https://api{i}.example.com", "overall_status": "PASS",
             "manifest_status": "PASS", "caip2_status": "PASS", "json_resilience_status": "PASS"}
            for i in range(5)
        ]
        write_results_to_csv(results, output_path)

        with open(output_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 5


class TestAuditSingleUrl:
    @pytest.mark.asyncio
    async def test_successful_audit(self):
        mock_report = AuditReport(
            target_url="https://api.example.com",
            timestamp=datetime.now(timezone.utc),
            overall_status="PASS",
            checks=[
                ManifestResult(status="PASS", message="OK"),
                Caip2Result(status="PASS", message="OK"),
                JsonResilienceResult(status="PASS", message="OK"),
            ],
            summary="3/3 checks passed. Overall: PASS",
        )

        with patch("batch_validator.run_audit", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_report
            semaphore = asyncio.Semaphore(10)
            result = await audit_single_url("https://api.example.com", semaphore)

            assert result["url"] == "https://api.example.com"
            assert result["overall_status"] == "PASS"
            assert result["manifest_status"] == "PASS"
            assert result["caip2_status"] == "PASS"
            assert result["json_resilience_status"] == "PASS"

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch("batch_validator.run_audit", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("Connection failed")
            semaphore = asyncio.Semaphore(10)
            result = await audit_single_url("https://api.example.com", semaphore)

            assert result["overall_status"] == "ERROR"
            assert result["manifest_status"] == "ERROR"


class TestPrintSummary:
    def test_prints_summary(self, capsys):
        results = [
            {"url": "https://a.com", "overall_status": "PASS", "manifest_status": "PASS",
             "caip2_status": "PASS", "json_resilience_status": "PASS"},
            {"url": "https://b.com", "overall_status": "FAIL", "manifest_status": "FAIL",
             "caip2_status": "PASS", "json_resilience_status": "PASS"},
            {"url": "https://c.com", "overall_status": "CRITICAL_FAIL", "manifest_status": "FAIL",
             "caip2_status": "FAIL", "json_resilience_status": "CRITICAL_FAIL"},
        ]
        print_summary(results)
        captured = capsys.readouterr()
        assert "PASS:" in captured.out
        assert "1" in captured.out
        assert "FAIL:" in captured.out
        assert "CRITICAL_FAIL:" in captured.out
        assert "https://c.com" in captured.out


class TestRunBatch:
    @pytest.mark.asyncio
    async def test_run_batch_end_to_end(self, tmp_path):
        output_path = str(tmp_path / "result.csv")

        mock_report = AuditReport(
            target_url="https://api.example.com",
            timestamp=datetime.now(timezone.utc),
            overall_status="PASS",
            checks=[
                ManifestResult(status="PASS", message="OK"),
                Caip2Result(status="PASS", message="OK"),
                JsonResilienceResult(status="PASS", message="OK"),
            ],
            summary="3/3 checks passed. Overall: PASS",
        )

        with patch("batch_validator.run_audit", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_report
            results = await run_batch(
                ["https://api.example.com"],
                concurrency=5,
                timeout=10.0,
                output_path=output_path,
            )

            assert len(results) == 1
            assert results[0]["overall_status"] == "PASS"

            with open(output_path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1
