"""CLI contracts for the private reimbursement refresh/report boundary.

The fixtures are deliberately fictional.  These tests also make every Google entry point
explode if touched: neither command is allowed to reach Sheets, and report-only rendering is
not allowed to load config or Gmail at all.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import gspread
import pytest
from PIL import Image

from np_finance import cli, receipt_assets, reimbursement_pipeline, reimbursement_report
from np_finance.config import Config, ReceiptRefresh
from np_finance.main_reports.sources import READONLY_SCOPE
from tests.conftest import _FULL_CONFIG
from tests.test_approved_list import LIST_GRID, LIST_TAB, ListClient, assert_value_free, list_client


def _bundle() -> dict[str, object]:
    review_key = "submission:v1:" + "a" * 64
    return {
        "schema_version": 1,
        "report": {
            "title": "Example Reimbursement Review",
            "eyebrow": "Example Organization - Treasurer",
            "subtitle": "Structured fictional review queue.",
            "organization": "Example Organization",
            "email_signoff": ["Thank you!", "Example Treasurer Team"],
            "logo_data_uri": "",
            "confirmed_outstanding": "12.34",
            "cutoff_date": "2026-06-01",
            "policy_version": "example-v1",
            "as_of_date": "2026-08-04",
        },
        "provenance": {
            "mapped_sha256": "1" * 64,
            "policy_sha256": "2" * 64,
            "source_snapshot_sha256": "3" * 64,
            "accounted_review_keys": [review_key],
        },
        "source_summary": {
            "mapped_rows": 1,
            "mapped_submissions": 1,
            "mapped_total": "12.34",
            "first_received": "2026-08-02",
            "last_received": "2026-08-02",
        },
        "tickets": [
            {
                "review_key": review_key,
                "ref": "NEW-01",
                "form_label": "",
                "origin": "submission",
                "display_order": 1,
                "requestor_name": "Fictional Requester",
                "form_type": "Example Reimbursement Form",
                "submitted": "2026-08-02",
                "submitted_label": "",
                "payment_method": "Zelle",
                "source_evidence_sha256": "4" * 64,
                "source": {
                    "stated_total": "12.34",
                    "mapped_total": "12.34",
                    "categories": ["Classroom Supplies"],
                    "flags": [],
                },
                "live": {
                    "workflow_state": "ACTIVE",
                    "decision": "APPROVED",
                    "payment_status": "NOT_PAID",
                    "payment_date": "",
                    "confirmations": [],
                },
                "review": {
                    "status": "A",
                    "action": "Send the fictional payment.",
                    "block": "No blocker in this example.",
                    "asks": [],
                    "note": "Fictional reviewer note.",
                    "email_questions": [],
                    "email_context": "",
                },
                "items": [
                    {
                        "item_key": "fictional-line-1",
                        "source_index": 1,
                        "source_date": "2026-08-01",
                        "source_description": "Fictional classroom materials",
                        "source_amount": "12.34",
                        "canonical_category": "Classroom Supplies",
                        "display_date": "",
                        "display_item": "",
                        "reviewed_amount": "",
                        "status": "A",
                        "why": "The fictional evidence is complete.",
                    }
                ],
                "messages": [{"kind": "draft", "date": "", "mode": "generated", "body": ""}],
                "archive_note": "",
            }
        ],
        "appendix": {"amendments": [], "cfo_checks": [], "excluded": [], "defects": []},
    }


def _report_summary() -> reimbursement_report.ReportSummary:
    return reimbursement_report.ReportSummary(
        review_rows=1,
        active=1,
        settled=0,
        live_unreviewed=0,
        new_records=1,
        legacy_records=0,
        item_lines=1,
        known_total=Decimal("12.34"),
        approved=Decimal("12.34"),
        clarification=Decimal("0.00"),
        declined=Decimal("0.00"),
        question=Decimal("0.00"),
        outstanding=Decimal("12.34"),
        legacy_outstanding=Decimal("0.00"),
        emails_to_send=1,
    )


def _merge_summary() -> reimbursement_pipeline.BundleMergeSummary:
    return reimbursement_pipeline.BundleMergeSummary(
        new_tickets=1,
        unchanged_tickets=2,
        total_source_tickets=3,
        mapped_rows=4,
        mapped_total=Decimal("45.67"),
        first_received="2026-06-02",
        last_received="2026-08-03",
        supplemental_evidence=5,
        supplemental_events=3,
        unmatched_evidence=2,
        supplemental_excluded_by_cutoff=7,
    )


def _forbidden(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("this command crossed an external-service boundary")


def _ban_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "SheetsClient", _forbidden)
    for name in ("needs_consent", "load_or_mint_credentials", "build_service", "fetch_window"):
        monkeypatch.setattr(cli.gmail_source, name, _forbidden)


def test_report_reimbursements_is_offline_and_prints_only_aggregates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = tmp_path / "bundle.json"
    output_path = tmp_path / "queue.html"
    data_path.write_text(json.dumps(_bundle()), encoding="utf-8")

    monkeypatch.setattr(cli, "_load", _forbidden)
    _ban_google(monkeypatch)

    rc = cli.main(
        [
            "report-reimbursements",
            "--data",
            str(data_path),
            "--output",
            str(output_path),
        ]
    )

    stdout = capsys.readouterr().out
    assert rc == 0
    assert output_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "Fictional Requester" in output_path.read_text(encoding="utf-8")
    assert "1 active, 0 settled" in stdout
    assert "receipt links  : 0 linked, 1 unlinked" in stdout
    assert "$12.34 approved" in stdout
    assert "Fictional Requester" not in stdout
    assert "example.org" not in stdout
    assert "copy text" in stdout
    assert "Fictional Requester" in output_path.with_name("queue.copy.txt").read_text(
        encoding="utf-8"
    )


def test_update_reimbursements_dry_run_preserves_bundle_and_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_config: Config,
) -> None:
    source = tmp_path / "mail"
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "queue.html"
    category_map = tmp_path / "category-map.csv"
    anchors_path = tmp_path / "anchors.json"
    bundle_path.write_text("prior bundle", encoding="utf-8")
    output_path.write_text("prior report", encoding="utf-8")
    prior_bundle = bundle_path.read_bytes()
    prior_html = output_path.read_bytes()
    text_path = output_path.with_name("queue.copy.txt")
    text_path.write_text("prior copy text", encoding="utf-8")
    captured: dict[str, Any] = {}

    def plan(**kwargs: Any) -> tuple[dict[str, Any], reimbursement_pipeline.BundleMergeSummary]:
        captured.update(kwargs)
        return {}, _merge_summary()

    monkeypatch.setattr(cli, "_load", lambda _args: fake_config)
    monkeypatch.setattr(cli.reimbursement_pipeline, "plan_bundle_refresh", plan)
    monkeypatch.setattr(cli.reimbursement_pipeline, "refresh_bundle", _forbidden)
    monkeypatch.setattr(cli.reimbursement_report, "build_report", _forbidden)
    _ban_google(monkeypatch)

    rc = cli.main(
        [
            "update-reimbursements",
            "--source",
            str(source),
            "--category-map",
            str(category_map),
            "--data",
            str(bundle_path),
            "--anchors",
            str(anchors_path),
            "--output",
            str(output_path),
            "--received-since",
            "2026-06-01",
            "--as-of",
            "2026-08-04",
            "--dry-run",
        ]
    )

    stdout = capsys.readouterr().out
    assert rc == 0
    assert bundle_path.read_bytes() == prior_bundle
    assert output_path.read_bytes() == prior_html
    assert text_path.read_text(encoding="utf-8") == "prior copy text"
    assert captured == {
        "bundle_path": bundle_path,
        "source": source,
        "category_map_path": category_map,
        "start_month": 1,
        "received_since": date(2026, 6, 1),
        "as_of": date(2026, 8, 4),
        "subject_filter": None,
        "anchors_path": anchors_path,
    }
    assert "3 source submission(s), 4 line(s), $45.67" in stdout
    assert "5 evidence, 3 event(s), 2 unmatched, 7 cutoff-excluded" in stdout
    assert "no bundle or report files written" in stdout
    assert "Fictional Requester" not in stdout


def test_update_reimbursements_refreshes_then_reports_without_sheets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_config: Config,
) -> None:
    source = tmp_path / "mail"
    bundle_path = tmp_path / "bundle.json"
    output_path = tmp_path / "queue.html"
    category_map = tmp_path / "category-map.csv"
    events: list[str] = []

    def refresh(**kwargs: Any) -> reimbursement_pipeline.BundleMergeSummary:
        events.append("refresh")
        assert kwargs["source"] == source
        assert kwargs["bundle_path"] == bundle_path
        bundle_path.write_text("Fictional Requester private bundle", encoding="utf-8")
        return _merge_summary()

    def report(data: Path, output: Path) -> reimbursement_report.BuildResult:
        events.append("report")
        assert data == bundle_path
        assert data.read_text(encoding="utf-8") == "Fictional Requester private bundle"
        output.write_text("rendered private report", encoding="utf-8")
        return reimbursement_report.BuildResult(
            output_path=output.resolve(),
            sha256="5" * 64,
            bytes_written=output.stat().st_size,
            summary=_report_summary(),
        )

    def prepare(**kwargs: Any) -> cli.receipt_refresh.RefreshSummary:
        events.append("receipt-prep")
        assert kwargs == {
            "bundle_path": bundle_path,
            "source": source,
            "config": fake_config.receipt_refresh,
            "dry_run": False,
        }
        return cli.receipt_refresh.RefreshSummary(False, 0, 0, 0, 0, 0)

    monkeypatch.setattr(cli, "_load", lambda _args: fake_config)
    monkeypatch.setattr(cli.reimbursement_pipeline, "refresh_bundle", refresh)
    monkeypatch.setattr(cli.reimbursement_pipeline, "plan_bundle_refresh", _forbidden)
    monkeypatch.setattr(cli.receipt_refresh, "refresh_receipts", prepare)
    monkeypatch.setattr(cli.reimbursement_report, "build_report", report)
    _ban_google(monkeypatch)

    rc = cli.main(
        [
            "update-reimbursements",
            "--source",
            str(source),
            "--category-map",
            str(category_map),
            "--data",
            str(bundle_path),
            "--output",
            str(output_path),
            "--received-since",
            "2026-06-01",
            "--as-of",
            "2026-08-04",
        ]
    )

    stdout = capsys.readouterr().out
    assert rc == 0
    assert events == ["refresh", "receipt-prep", "report"]
    assert output_path.read_text(encoding="utf-8") == "rendered private report"
    assert "1 new, 2 unchanged" in stdout
    assert "5 evidence, 3 event(s), 2 unmatched, 7 cutoff-excluded" in stdout
    assert "1 active, 0 settled" in stdout
    assert "Fictional Requester" not in stdout


def test_update_reimbursements_prepares_real_page_sidecar_and_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_config: Config,
) -> None:
    """CLI wiring gate: parsed mail -> fetch seam -> decode child -> validator -> HTML."""

    message_id = "<Fictional.CLI.Raw@Example.ORG>"
    review_key = "submission:v1:" + hashlib.sha256(message_id.encode()).hexdigest()
    value = _bundle()
    ticket = value["tickets"][0]  # type: ignore[index]
    ticket["review_key"] = review_key  # type: ignore[index]
    value["provenance"]["accounted_review_keys"] = [review_key]  # type: ignore[index]
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(value), encoding="utf-8")
    source = tmp_path / "mail"
    source.mkdir()
    message = EmailMessage()
    message["Subject"] = "Example Reimbursement Form got a new submission"
    message["From"] = "forms@example.org"
    message["To"] = "treasurer@example.org"
    message["Date"] = "Wed, 21 Oct 2026 09:00:00 -0700"
    message["Message-ID"] = message_id
    message.set_content(
        """Example Reimbursement Form got a new submission
Requestor First and Last Name:
Fictional Requester
1. Date:
2026-08-01
1. Event or Budget Category:
Classroom Supplies
1. Description:
Fictional classroom supplies
1. Amount:
12.34
Total Amount $:
12.34
Choose Payment Type:
Check
PDF:
https://uploads.example.org/fictional.png
"""
    )
    (source / "submission.eml").write_bytes(message.as_bytes())
    cached = tmp_path / "cached.png"
    Image.new("RGB", (320, 180), "white").save(cached, format="PNG")
    payload = cached.read_bytes()
    asset = receipt_assets.AssetResult(
        "https://uploads.example.org/fictional.png",
        "fictional-key",
        receipt_assets.ASSET_ID.prefix + hashlib.sha256(payload).hexdigest(),
        "png",
        cached,
        len(payload),
        "cached",
        "",
    )
    receipt_config = ReceiptRefresh(
        ("uploads.example.org",), tmp_path / "cache", tmp_path / "receipt-pages"
    )
    configured = dataclasses.replace(fake_config, receipt_refresh=receipt_config)
    monkeypatch.setattr(cli, "_load", lambda _args: configured)
    monkeypatch.setattr(
        cli.reimbursement_pipeline, "refresh_bundle", lambda **_kwargs: _merge_summary()
    )
    monkeypatch.setattr(cli.reimbursement_pipeline, "plan_bundle_refresh", _forbidden)
    monkeypatch.setattr(
        cli.receipt_refresh.receipt_assets,
        "fetch_assets",
        lambda *_args, **_kwargs: [asset],
    )
    _ban_google(monkeypatch)
    output = tmp_path / "queue.html"
    rc = cli.main(
        [
            "update-reimbursements",
            "--source",
            str(source),
            "--category-map",
            str(tmp_path / "category-map.csv"),
            "--data",
            str(bundle_path),
            "--output",
            str(output),
            "--received-since",
            "2026-06-01",
            "--as-of",
            "2026-08-04",
        ]
    )
    stdout = capsys.readouterr().out
    sidecar = json.loads(bundle_path.with_suffix(".receipts.json").read_text("utf-8"))
    assert rc == 0
    assert sidecar["items"][0]["review_key"] == review_key
    assert sidecar["items"][0]["match_method"] == "automatic-ticket-source-v1"
    assert sidecar["items"][0]["regions"][0]["box"] is None
    assert output.read_text("utf-8").startswith("<!doctype html>")
    assert "automatic suggestion" in output.read_text("utf-8")
    assert "1 linked, 0 automatic mark(s), 1 review-needed" in stdout


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--fetch-until", "2026-08-05"),
        ("--fetch-query", "has:attachment"),
        ("--fetch-limit", "5"),
    ],
)
def test_update_fetch_options_require_fetch_since(
    option: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_load", _forbidden)
    monkeypatch.setattr(cli.reimbursement_pipeline, "plan_bundle_refresh", _forbidden)
    monkeypatch.setattr(cli.reimbursement_pipeline, "refresh_bundle", _forbidden)
    monkeypatch.setattr(cli.reimbursement_report, "build_report", _forbidden)
    _ban_google(monkeypatch)

    rc = cli.main(["update-reimbursements", option, value])

    stdout = capsys.readouterr().out
    assert rc == 1
    assert "require --fetch-since" in stdout


def test_report_failure_preserves_prior_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = tmp_path / "invalid.json"
    output_path = tmp_path / "queue.html"
    data_path.write_text('{"not": "a valid bundle"}', encoding="utf-8")
    output_path.write_text("prior complete report", encoding="utf-8")

    monkeypatch.setattr(cli, "_load", _forbidden)
    _ban_google(monkeypatch)

    rc = cli.main(
        [
            "report-reimbursements",
            "--data",
            str(data_path),
            "--output",
            str(output_path),
        ]
    )

    stdout = capsys.readouterr().out
    assert rc == 1
    assert output_path.read_text(encoding="utf-8") == "prior complete report"
    assert "report-reimbursements:" in stdout
    assert "Fictional Requester" not in stdout


def test_reimbursement_commands_stay_independent_of_the_main_report_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --source, update-reimbursements still reads the configured Gmail inbox, and
    neither reimbursement command reaches the Main Report Set runner or its outputs."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        _FULL_CONFIG
        + "\n[gmail]\n"
        + 'client_secrets_file = "secrets/gmail-client-secret.json"\n'
        + 'token_file = "secrets/gmail-token.json"\n'
        + 'inbox_dir = "inbox"\n',
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(_bundle()), encoding="utf-8")
    output_path = tmp_path / "queue.html"
    refreshed: dict[str, Any] = {}

    def refresh(**kwargs: Any) -> reimbursement_pipeline.BundleMergeSummary:
        refreshed.update(kwargs)
        return _merge_summary()

    monkeypatch.setattr(cli.reimbursement_pipeline, "refresh_bundle", refresh)
    monkeypatch.setattr(cli.reimbursement_pipeline, "plan_bundle_refresh", _forbidden)
    for name in ("run", "check_request"):
        monkeypatch.setattr(cli.runner, name, _forbidden)
    monkeypatch.setattr(cli.runner.render, "write", _forbidden)
    _ban_google(monkeypatch)

    rc = cli.main(
        [
            "update-reimbursements",
            "--config",
            str(config_path),
            "--data",
            str(bundle_path),
            "--category-map",
            str(tmp_path / "category-map.csv"),
            "--output",
            str(output_path),
            "--as-of",
            "2026-08-04",
        ]
    )
    assert rc == 0
    assert refreshed["source"] == (tmp_path / "inbox").resolve()
    assert refreshed["start_month"] == 1
    assert "Fictional Requester" in output_path.read_text(encoding="utf-8")

    rc = cli.main(
        ["report-reimbursements", "--data", str(bundle_path), "--output", str(output_path)]
    )
    assert rc == 0
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "main-report-set.html").exists()
    assert "Fictional Requester" not in capsys.readouterr().out


# --- approved list (APPROVED-LIST Step 75) -------------------------------------------------

_LIST_SUBMISSION = """Example Reimbursement Form got a new submission
Requestor First and Last Name:
Fictional Requester
Email:
fictional.requester@example.org
1. Date:
2026-08-01
1. Event or Budget Category:
Supplies
1. Description:
Fictional classroom supplies
1. Amount:
12.34
Total Amount $:
12.34
Choose Payment Type:
Check
"""


def _list_install(root: Path, *, with_list: bool) -> list[str]:
    """A fictional install (one settled legacy ticket plus one new mailed submission).

    Returns the ``update-reimbursements`` argv. The config is a real file, so the optional
    ``[sheets] approved_list_tab`` key is parsed by the production loader.
    """
    root.mkdir()
    value = _bundle()
    ticket = value["tickets"][0]  # type: ignore[index]
    ticket.update(review_key="legacy:v1:fictional-p-001", ref="P-001", origin="legacy")
    ticket["items"][0]["item_key"] = "legacy:v1:fictional-p-001:line:1"
    value["provenance"]["accounted_review_keys"] = []  # type: ignore[index]
    value["source_summary"].update(  # type: ignore[attr-defined]
        mapped_rows=0, mapped_submissions=0, mapped_total="0.00"
    )
    (root / "bundle.json").write_text(json.dumps(value), encoding="utf-8")
    source = root / "mail"
    source.mkdir()
    message = EmailMessage()
    message["Subject"] = "Example Reimbursement Form got a new submission"
    message["From"] = "forms@example.org"
    message["To"] = "treasurer@example.org"
    message["Date"] = "Wed, 05 Aug 2026 09:00:00 -0700"
    message["Message-ID"] = "<fictional-list-run@example.org>"
    message.set_content(_LIST_SUBMISSION)
    (source / "submission.eml").write_bytes(message.as_bytes())
    (root / "category-map.csv").write_text(
        "raw_category,canonical_category\nSupplies,Classroom Supplies\n", encoding="utf-8"
    )
    text = _FULL_CONFIG
    if with_list:
        line = 'drive_reports_folder_id = "fake-reports-folder-id"\n'
        text = text.replace(line, line + f'approved_list_tab = "{LIST_TAB}"\n')
    (root / "config.toml").write_text(text, encoding="utf-8")
    return [
        "update-reimbursements",
        "--config",
        str(root / "config.toml"),
        "--source",
        str(source),
        "--category-map",
        str(root / "category-map.csv"),
        "--data",
        str(root / "bundle.json"),
        "--output",
        str(root / "queue.html"),
        "--received-since",
        "2026-06-01",
        "--as-of",
        "2026-08-10",
    ]


def _outputs(root: Path) -> tuple[bytes, ...]:
    return tuple(
        (root / name).read_bytes() for name in ("bundle.json", "queue.html", "queue.copy.txt")
    )


def _serve_list(
    monkeypatch: pytest.MonkeyPatch, grid: list[list[str]] | None = None, *, tab: str = LIST_TAB
) -> list[tuple[str, ...]]:
    """Route ``gspread.service_account`` to a fake own-spreadsheet; return the scope log."""
    recorded: list[tuple[str, ...]] = []

    def service_account(*, filename: str, scopes: Sequence[str]) -> ListClient:
        recorded.append(tuple(scopes))
        return list_client(grid, tab=tab)

    monkeypatch.setattr(gspread, "service_account", service_account)
    return recorded


def test_update_reimbursements_reads_the_configured_list_without_changing_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ban_google(monkeypatch)
    monkeypatch.setattr(gspread, "service_account", _forbidden)
    plain = _list_install(tmp_path / "unkeyed", with_list=False)
    assert cli.main(plain) == 0
    assert "approved list" not in capsys.readouterr().out

    recorded = _serve_list(monkeypatch)
    listed = _list_install(tmp_path / "keyed", with_list=True)
    prior_bundle = (tmp_path / "keyed" / "bundle.json").read_bytes()
    assert cli.main([*listed, "--dry-run"]) == 0
    dry_stdout = capsys.readouterr().out
    assert (tmp_path / "keyed" / "bundle.json").read_bytes() == prior_bundle
    assert not (tmp_path / "keyed" / "queue.html").exists()
    assert cli.main(listed) == 0
    stdout = capsys.readouterr().out

    assert recorded == [(READONLY_SCOPE,), (READONLY_SCOPE,)]
    for text in (dry_stdout, stdout):
        assert "update-reimbursements: approved list -> 2 approved row(s)" in text
        assert_value_free(text)
    assert _outputs(tmp_path / "keyed") == _outputs(tmp_path / "unkeyed")


def _list_grid(row: int, column: int, value: str) -> list[list[str]]:
    grid = [list(cells) for cells in LIST_GRID]
    grid[row][column] = value
    return grid


@pytest.mark.parametrize(
    ("grid", "tab", "message"),
    [
        pytest.param(None, "Another Tab", "tab was not found", id="missing-tab"),
        pytest.param(_list_grid(0, 6, "State"), LIST_TAB, "column(s): Status", id="no-status"),
        pytest.param(_list_grid(0, 8, "Email"), LIST_TAB, "duplicate", id="duplicate-header"),
        pytest.param(_list_grid(1, 1, "Avery Listed"), LIST_TAB, "row 2", id="bad-email"),
        pytest.param([LIST_GRID[0], LIST_GRID[3]], LIST_TAB, "no Approved", id="none-approved"),
    ],
)
def test_update_reimbursements_list_errors_write_nothing_and_fetch_no_mail(
    grid: list[list[str]] | None,
    tab: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ban_google(monkeypatch)  # a mail fetch reached after a list error would raise here
    monkeypatch.setattr(cli.reimbursement_pipeline, "refresh_bundle", _forbidden)
    monkeypatch.setattr(cli.reimbursement_pipeline, "plan_bundle_refresh", _forbidden)
    recorded = _serve_list(monkeypatch, grid, tab=tab)
    argv = _list_install(tmp_path / "install", with_list=True)
    prior_bundle = (tmp_path / "install" / "bundle.json").read_bytes()

    rc = cli.main([*argv, "--fetch-since", "2026-08-01"])

    stdout = capsys.readouterr().out
    assert rc == 1
    assert recorded == [(READONLY_SCOPE,)]
    assert "update-reimbursements: approved list check failed: " in stdout
    assert message in stdout
    assert_value_free(stdout)
    assert (tmp_path / "install" / "bundle.json").read_bytes() == prior_bundle
    assert sorted(path.name for path in (tmp_path / "install" / "mail").iterdir()) == [
        "submission.eml"
    ]
    assert not (tmp_path / "install" / "queue.html").exists()
    assert not (tmp_path / "install" / "queue.copy.txt").exists()
