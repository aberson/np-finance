"""Tests for np_finance.main_reports.runner and the ``np-finance end-to-end-run`` command.

Every fixture is fictional (``Example`` placeholders, fake ids). The production CLI entry
point (:func:`np_finance.cli.main`) runs end to end: the real read-only capture against fake
gspread workbooks (``gspread.service_account`` returns a fake client routed by workbook key),
the real reimbursement refresh over a fictional mail archive, the real reconciliation,
journal projection and recording, facts, renderers, run manifest and publication. Content
cases replace only the headless Chromium export with a stand-in; the ``test_chromium_*``
case drives real Chromium and skips only when Playwright reports its browser executable
missing. Nothing reaches the network, Gmail or a live workbook.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import shutil
import struct
import time
import warnings
import zlib
from collections.abc import Sequence
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import gspread
import pytest
from google.auth.exceptions import RefreshError, TransportError
from PIL import Image
from requests.exceptions import ReadTimeout

from np_finance import (
    cli,
    gmail_source,
    receipt_assets,
    receipt_refresh,
    receipt_viewer,
    reimbursement_report,
)
from np_finance.main_reports import (
    adjustments,
    export,
    facts,
    reconcile,
    render,
    runner,
    sources,
)
from np_finance.main_reports.export import ExportError, ExportJob
from np_finance.main_reports.models import make_adjustment_id
from np_finance.sheets import SheetsClient
from tests.conftest import (
    _FULL_CONFIG,
    AS_OF,
    CFO_ID,
    VENDOR_JUNE,
    CfoHarness,
    RecordingSleep,
    _bundle_payload,
    _config,
    _harness,
    make_api_error,
    require_chromium,
)

FAKE_PDF = b"%PDF-1.4\n% fictional export stand-in\n"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FIRST_REQUEST = "<example-runner-request-1@example.invalid>"
SECOND_REQUEST = "<example-runner-request-2@example.invalid>"
SMOKE_SECONDS = 60.0
SECRET_CELL = "Example secret cell 4321.09"
REAL_EXPORT = export.export_documents


def _png(width: int, height: int) -> bytes:
    """A small white grayscale PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(b"\0" + b"\xff" * width for _ in range(height))
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


RECEIPT_PNG = _png(120, 160)


def fake_export(
    jobs: Sequence[ExportJob], *, executable: Path | None = None, sandbox: bool | None = None
) -> bool:
    """Stand-in for the Chromium export: minimal valid PDF/PNG files for every job."""
    for job in jobs:
        job.pdf.write_bytes(FAKE_PDF + job.html.name.encode())
        job.png.write_bytes(RECEIPT_PNG)
    return True


def _forbidden(*_args: object, **_kwargs: object) -> Any:
    raise AssertionError("the run crossed a boundary it must not cross")


# --------------------------------------------------------------------------------------
# Fictional world: fake workbooks, mail archive, bundle and receipt sidecar
# --------------------------------------------------------------------------------------


class RoutedClient:
    """A fake gspread client: the CFO key opens the fake CFO workbook, any other key ours."""

    def __init__(self, harness: CfoHarness) -> None:
        self.harness = harness

    def open_by_key(self, key: str) -> Any:
        if key == CFO_ID:
            return self.harness.cfo_client.open_by_key(key)
        return self.harness.own_client.open_by_key(key)

    def set_timeout(self, timeout: float) -> None:
        assert timeout > 0


def _legacy_bundle() -> dict[str, Any]:
    """The shared fictional bundle reduced to its legacy tickets (no mail-backed evidence)."""
    payload = _bundle_payload()
    payload["tickets"] = [t for t in payload["tickets"] if t["origin"] == "legacy"]
    payload["provenance"]["accounted_review_keys"] = []
    payload["source_summary"].update(mapped_rows=0, mapped_submissions=0, mapped_total="0.00")
    payload["supplemental"] = {
        "anchors_sha256": payload["supplemental"]["anchors_sha256"],
        "evidence": [],
        "events": [],
        "unmatched": [],
    }
    return payload


def _submission(
    path: Path,
    message_id: str,
    *,
    day: str = "21",
    amount: str = "8.00",
    receipt_url: str | None = None,
) -> None:
    message = EmailMessage()
    message["Subject"] = "Example Reimbursement Form got a new submission"
    message["From"] = "forms@example.invalid"
    message["To"] = "treasurer@example.invalid"
    message["Date"] = f"Sun, {day} Jul 2030 09:00:00 -0700"
    message["Message-ID"] = message_id
    message.set_content(
        f"""\
Example Reimbursement Form got a new submission
Requestor First and Last Name:
Fictional Requester
Email:
requester@example.invalid
1. Date:
2030-07-20
1. Event or Budget Category:
Supplies
1. Description:
Fictional classroom paper
1. Amount:
{amount}
Total Amount $:
{amount}
Choose Payment Type:
Check
"""
        + (f"PDF:\n{receipt_url}\n" if receipt_url else "")
    )
    path.write_bytes(message.as_bytes())


class World:
    """A fictional installation: config, fake workbooks, mail, bundle and receipt sidecar.

    ``gspread.service_account`` returns a routed fake client (recording each requested
    scope set), the Chromium export is a stand-in and every Gmail entry point is forbidden.
    """

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path
        self.monkeypatch = monkeypatch
        self.config = _config(tmp_path)
        self.config_path = tmp_path / "config.toml"
        self.harness = _harness(self.config)
        self.output = tmp_path / "reports" / "output"
        self.runs = self.output / "main-report-runs"
        self.bundle = self.output / "reimbursement-report.json"
        self.mail = tmp_path / "mail"
        self.category_map = self.output / "category_map.csv"
        self.output.mkdir(parents=True)
        self.mail.mkdir()
        _submission(self.mail / "request-1.eml", FIRST_REQUEST)
        self.category_map.write_text(
            "raw_category,canonical_category\nSupplies,Classroom Supplies\n", encoding="utf-8"
        )
        self.bundle.write_text(json.dumps(_legacy_bundle()), encoding="utf-8")
        self._sidecar()
        self.scopes: list[tuple[str, ...]] = []

        def service_account(*, filename: str, scopes: Sequence[str]) -> RoutedClient:
            self.scopes.append(tuple(scopes))
            return RoutedClient(self.harness)

        monkeypatch.setattr(gspread, "service_account", service_account)
        monkeypatch.setattr(export, "export_documents", fake_export)
        for name in ("needs_consent", "load_or_mint_credentials", "build_service", "fetch_window"):
            monkeypatch.setattr(gmail_source, name, _forbidden)

    def _sidecar(self) -> None:
        """A fictional receipt page linked to the outstanding legacy request."""
        report = reimbursement_report.load_bundle(self.bundle)
        ticket = report.active_tickets[0]
        pages = self.output / "receipt-pages"
        pages.mkdir()
        (pages / "page-1.png").write_bytes(RECEIPT_PNG)
        sidecar = {
            "schema_version": 1,
            "pages": [
                {
                    "id": "page-1",
                    "path": "receipt-pages/page-1.png",
                    "sha256": hashlib.sha256(RECEIPT_PNG).hexdigest(),
                    "label": "Example receipt page 1",
                }
            ],
            "items": [
                {
                    "review_key": ticket.review_key,
                    "item_key": ticket.items[0].item_key,
                    "item_sha256": receipt_viewer.item_fingerprint(ticket, ticket.items[0]),
                    "regions": [{"page_id": "page-1", "box": [0.1, 0.3, 0.8, 0.05]}],
                }
            ],
        }
        self.sidecar.write_text(json.dumps(sidecar), encoding="utf-8")

    @property
    def sidecar(self) -> Path:
        return self.bundle.with_suffix(".receipts.json")

    def args(self, *extra: str, as_of: date = AS_OF) -> list[str]:
        return [
            "end-to-end-run",
            "--as-of",
            as_of.isoformat(),
            "--config",
            str(self.config_path),
            "--data",
            str(self.bundle),
            "--source",
            str(self.mail),
            "--category-map",
            str(self.category_map),
            *extra,
        ]

    def main(self, *extra: str) -> int:
        return cli.main(self.args(*extra))

    def run_dirs(self) -> list[Path]:
        if not self.runs.is_dir():
            return []
        return sorted(p for p in self.runs.iterdir() if p.name.startswith("run-"))

    def published(self) -> dict[str, bytes]:
        """Every file beside the runs folder: pointer, compatibility copies and inputs."""
        return {p.name: p.read_bytes() for p in self.output.iterdir() if p.is_file()}

    def proposals(self, path: Path) -> str:
        """Write a one-entry adjustments file moving the June vendor row to July 1."""
        capture_set = self.harness.capture()
        reconciled = reconcile.from_capture(capture_set, self.config)
        (txn,) = [t for t in reconciled.transactions if t.description == VENDOR_JUNE]
        adjustment_id = make_adjustment_id()
        payload = {
            "schema_version": 1,
            "adjustments": [
                {
                    "adjustment_id": adjustment_id,
                    "targets": [{"record_key": txn.record_key, "revision_hash": txn.revision_hash}],
                    "kind": "date_override",
                    "effective_date": "2030-07-01",
                    "prior_value": "2030-06-30",
                    "replacement_value": "2030-07-01",
                    "reason": "Example correction",
                    "evidence": ["example-statement-2030-07"],
                }
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return adjustment_id


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def _tree(root: Path) -> dict[str, bytes | None]:
    """Every path under ``root``: file bytes, or ``None`` for a directory."""
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def _manifest(run_dir: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((run_dir / runner.MANIFEST_NAME).read_text("utf-8"))
    return value


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _tickets(path: Path) -> int:
    return len(reimbursement_report.load_bundle(path).tickets)


# --------------------------------------------------------------------------------------
# Bounded smoke: the production CLI from sources to a published five-report set
# --------------------------------------------------------------------------------------


def test_cli_smoke_publishes_the_complete_set_within_the_bound(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    started = time.monotonic()
    assert world.main() == runner.EXIT_OK
    assert time.monotonic() - started < SMOKE_SECONDS

    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    assert manifest["status"] == "published"
    assert manifest["run_id"] == run_dir.name
    assert manifest["as_of"] == AS_OF.isoformat()
    assert manifest["failure_codes"] == []
    assert {item["path"] for item in manifest["artifacts"]["artifacts"]} == set(render.OUTPUT_NAMES)
    for item in manifest["artifacts"]["artifacts"]:
        payload = (run_dir / item["path"]).read_bytes()
        assert (_sha(payload), len(payload)) == (item["sha256"], item["byte_length"])
    # The reimbursement refresh appended the fictional mail submission to the live bundle.
    assert _tickets(world.bundle) == 3
    # The current-run pointer names this run and links into its folder.
    pointer = (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert str(render.run_id_meta(run_dir.name)) in pointer
    assert str(render.input_set_meta(manifest["input_sha256"])) in pointer
    assert f'content="{render.CONTENT_SECURITY_POLICY}"' in pointer
    assert f'href="main-report-runs/{run_dir.name}/{render.INDEX_HTML}"' in pointer
    # The in-place refresh changed the evidence bundle; the staged copy is its new state.
    assert manifest["bundle_sha256_before_refresh"] != manifest["bundle_sha256_after_refresh"]
    assert manifest["bundle_sha256_after_refresh"] == manifest["bundle_sha256"]
    assert manifest["sidecar_sha256_before_refresh"] == manifest["sidecar_sha256_after_refresh"]
    # Every compatibility file is a byte copy of its run file.
    assert dict(manifest["alias_refresh"]) == {
        alias: "refreshed" for _name, alias in runner.COMPATIBILITY_FILES
    }
    for name, alias in runner.COMPATIBILITY_FILES:
        assert (world.output / alias).read_bytes() == (run_dir / name).read_bytes()
    stdout = capsys.readouterr().out
    assert "15 file(s) validated" in stdout
    assert "16 refreshed, 0 not refreshed (complete refresh)" in stdout
    assert manifest["alias_refresh_state"] == "complete"
    # No CFO workbook write, and only read-only clients were requested.
    world.harness.assert_no_writes()
    assert set(world.scopes) == {(sources.READONLY_SCOPE,)}


def test_every_artifact_and_record_identifies_the_same_captured_input_set(world: World) -> None:
    assert world.main() == runner.EXIT_OK
    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    run_id, input_sha = manifest["run_id"], manifest["input_sha256"]
    for name in (*(f"{n}.html" for n in render.SUMMARY_NAMES), render.INDEX_HTML):
        html = (run_dir / name).read_text("utf-8")
        assert str(render.run_id_meta(run_id)) in html
        assert str(render.input_set_meta(input_sha)) in html
    assert manifest["artifacts"]["run_id"] == run_id
    # The manifest's input hash is recomputable from exactly the components it lists.
    components = manifest["input_components"]
    assert runner.input_set_sha256(components) == input_sha
    assert components == {
        "capture_aggregate_sha256": manifest["capture_aggregate_sha256"],
        "journal_sha256": manifest["journal_sha256"],
        "crosswalk_sha256": manifest["crosswalk_sha256"],
        "bundle_sha256": manifest["bundle_sha256"],
        "sidecar_sha256": manifest["sidecar_sha256"],
        "receipt_pages": [list(pair) for pair in manifest["receipt_pages"].items()],
        "start_month": world.config.fiscal_year.start_month,
        "assumptions_tab": "Assumptions",
        "as_of": AS_OF.isoformat(),
    }
    # The staged inputs are byte copies of the refreshed live bundle, sidecar and page.
    inputs = run_dir / runner.INPUTS_DIR
    assert (inputs / world.bundle.name).read_bytes() == world.bundle.read_bytes()
    assert manifest["bundle_sha256"] == _sha(world.bundle.read_bytes())
    assert manifest["sidecar_sha256"] == _sha(world.sidecar.read_bytes())
    assert manifest["receipt_pages"] == {"receipt-pages/page-1.png": _sha(RECEIPT_PNG)}
    assert (inputs / "receipt-pages" / "page-1.png").read_bytes() == RECEIPT_PNG
    # The queue embeds the staged receipt page and keeps its copy text.
    queue = (run_dir / render.QUEUE_HTML).read_text("utf-8")
    assert "data:image/png;base64," in queue
    assert (run_dir / render.QUEUE_COPY_TEXT).read_text("utf-8")
    # Records and the content-addressed capture store carry the same identities.
    for relative, digest in manifest["records"].items():
        assert _sha((run_dir / relative).read_bytes()) == digest
    facts_record = json.loads((run_dir / runner.RECORDS_DIR / "facts.json").read_text("utf-8"))
    assert facts_record["as_of"] == AS_OF.isoformat()
    assert facts_record["journal_sha256"] == manifest["journal_sha256"]
    stored = json.loads((world.runs / manifest["capture_ref"]).read_text("utf-8"))
    assert stored["aggregate_sha256"] == manifest["capture_aggregate_sha256"]
    assert {alias: entry["sha256"] for alias, entry in stored["captures"].items()} == manifest[
        "capture_hashes"
    ]
    assert manifest["assumptions_sha256"] == stored["assumptions"]["sha256"]
    assert manifest["adopted_budget_sha256"] == stored["adopted_budget"]["sha256"]


def test_identical_inputs_rerun_into_a_new_folder_and_retain_the_previous_publication(
    world: World,
) -> None:
    assert world.main() == runner.EXIT_OK
    (first,) = world.run_dirs()
    first_tree = _tree(first)
    first_published = world.published()

    assert world.main() == runner.EXIT_OK
    second = next(d for d in world.run_dirs() if d != first)
    assert _tree(first) == first_tree  # the earlier run folder is immutable
    assert _manifest(second)["input_sha256"] == _manifest(first)["input_sha256"]
    assert len(list((world.runs / "captures").glob("*.manifest.json"))) == 1
    pointer = (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert second.name in pointer and first.name not in pointer
    previous = second / runner.PUBLICATION_DIR / runner.PREVIOUS_DIR
    assert (previous / runner.POINTER_NAME).read_bytes() == first_published[runner.POINTER_NAME]
    for _name, alias in runner.COMPATIBILITY_FILES:
        assert (previous / alias).read_bytes() == first_published[alias]
    assert not (world.runs / adjustments.LOCK_FILENAME).exists()


def test_the_input_hash_changes_when_only_the_bundle_changes(world: World) -> None:
    assert world.main() == runner.EXIT_OK
    _submission(world.mail / "request-2.eml", SECOND_REQUEST, day="22", amount="9.50")
    assert world.main() == runner.EXIT_OK
    first, second = (_manifest(d) for d in world.run_dirs())
    assert first["capture_aggregate_sha256"] == second["capture_aggregate_sha256"]
    assert first["bundle_sha256"] != second["bundle_sha256"]
    assert first["input_sha256"] != second["input_sha256"]


BASE_COMPONENTS: dict[str, Any] = {
    "capture_aggregate_sha256": "a" * 64,
    "journal_sha256": "b" * 64,
    "crosswalk_sha256": "c" * 64,
    "bundle_sha256": "d" * 64,
    "sidecar_sha256": "e" * 64,
    "receipt_pages": [["receipt-pages/page-1.png", "f" * 64]],
    "start_month": 7,
    "assumptions_tab": "Assumptions",
    "as_of": "2030-08-15",
}
# Pins the hash shape (schema version, key names, value encoding) against silent drift.
KNOWN_INPUT_SET_SHA256 = "cef67b7db4b47396b52684cf96b140ecbcf4829c615c14df0b60044bbac4d8f8"
CHANGED_COMPONENTS: dict[str, Any] = {
    "capture_aggregate_sha256": "1" * 64,
    "journal_sha256": "2" * 64,
    "crosswalk_sha256": None,
    "bundle_sha256": "3" * 64,
    "sidecar_sha256": None,
    "receipt_pages": [["receipt-pages/page-1.png", "4" * 64]],
    "start_month": 1,
    "assumptions_tab": "Example Assumptions",
    "as_of": "2030-08-14",
}


@pytest.mark.parametrize("component", runner.INPUT_COMPONENTS)
def test_every_input_component_changes_the_input_set_hash(component: str) -> None:
    assert set(CHANGED_COMPONENTS) == set(BASE_COMPONENTS) == set(runner.INPUT_COMPONENTS)
    changed = {**BASE_COMPONENTS, component: CHANGED_COMPONENTS[component]}
    assert runner.input_set_sha256(changed) != runner.input_set_sha256(BASE_COMPONENTS)


def test_the_input_set_hash_shape_is_pinned() -> None:
    assert runner.input_set_sha256(BASE_COMPONENTS) == KNOWN_INPUT_SET_SHA256


def test_the_input_set_hash_refuses_missing_or_extra_components() -> None:
    missing = {k: v for k, v in BASE_COMPONENTS.items() if k != "journal_sha256"}
    with pytest.raises(ValueError):
        runner.input_set_sha256(missing)
    with pytest.raises(ValueError):
        runner.input_set_sha256({**BASE_COMPONENTS, "extra": "x"})


# --------------------------------------------------------------------------------------
# Dry run and request validation
# --------------------------------------------------------------------------------------


def test_dry_run_validates_everything_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _tree(world.root)
    assert world.main("--dry-run") == runner.EXIT_OK
    assert _tree(world.root) == before
    world.harness.assert_no_writes()
    assert set(world.scopes) == {(sources.READONLY_SCOPE,)}
    stdout = capsys.readouterr().out
    assert "1 new, 0 unchanged" in stdout  # the refresh was planned, not written
    assert "[dry-run]: inputs validated" in stdout


def test_dry_run_reports_a_failed_validation_without_writing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.bundle.write_text('{"schema_version": 2}', encoding="utf-8")
    before = _tree(world.root)
    assert world.main("--dry-run") == runner.EXIT_FAILED
    assert _tree(world.root) == before
    assert "reimbursement_failed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        ("--dry-run", "--fetch-since", "2030-08-01"),
        ("--dry-run", "--adjustments-file", "proposals.json"),
        ("--fetch-limit", "5"),
        ("--fetch-query", "has:attachment"),
        ("--fetch-since", "2030-08-02", "--fetch-until", "2030-08-02"),
        ("--fetch-since", "2030-08-02", "--fetch-limit", "0"),
    ],
)
def test_invalid_requests_are_refused_before_config_or_sheets(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: tuple[str, ...],
) -> None:
    monkeypatch.setattr(cli, "load_config", _forbidden)
    before = _tree(world.root)
    assert world.main(*extra) == runner.EXIT_INVALID
    assert _tree(world.root) == before
    assert world.scopes == []
    assert "options_invalid" in capsys.readouterr().out


def test_missing_as_of_is_an_argument_error(world: World) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(world.args()[3:])
    assert caught.value.code == runner.EXIT_INVALID


@pytest.mark.parametrize(
    "case", ["no_section", "pointer_in_project", "missing_binding", "not_toml", "missing_file"]
)
def test_invalid_configuration_exits_2_before_any_write(
    world: World, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    text = world.config_path.read_text("utf-8")
    if case == "missing_file":
        world.config_path.unlink()
    elif case == "not_toml":
        text = "[organization"
    elif case == "no_section":
        text = _FULL_CONFIG
    elif case == "pointer_in_project":
        text = text.replace(
            'output_dir = "reports/output/main-report-runs"', 'output_dir = "reports/output"'
        )
    else:
        start = text.index("\n[main_reports.sources.credit-card]")
        end = text.index("\n[", start + 1)
        text = text[:start] + text[end:]
    if case != "missing_file":
        world.config_path.write_text(text, encoding="utf-8")
    before = _tree(world.root)
    assert world.main() == runner.EXIT_INVALID
    assert _tree(world.root) == before
    assert world.scopes == []
    assert "config_invalid" in capsys.readouterr().out


def test_the_runner_itself_refuses_a_dry_run_that_would_write(world: World) -> None:
    lines: list[str] = []
    options = runner.RunOptions(
        as_of=AS_OF,
        config_dir=world.root,
        bundle_path=world.bundle,
        source=world.mail,
        category_map_path=world.category_map,
        dry_run=True,
        adjustments_file=world.root / "proposals.json",
    )
    before = _tree(world.root)
    result = runner.run(options, world.config, out=lines.append)
    assert (result.exit_code, result.failure_code) == (runner.EXIT_INVALID, "options_invalid")
    assert (result.manifest_path, result.index_path, result.run_id) == (None, None, None)
    assert _tree(world.root) == before
    assert world.scopes == []


def test_unreadable_adjustments_file_exits_2_before_sheets(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = world.root / "proposals.json"
    bad.write_text('{"schema_version": 1, "adjustments": [{"kind": "additive"}]}', "utf-8")
    before = _tree(world.root)
    assert world.main("--adjustments-file", str(bad)) == runner.EXIT_INVALID
    assert _tree(world.root) == before
    assert world.scopes == []
    assert "adjustments_file_invalid" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# Adjustments: explicit opt-in, immediate effect, no duplicates on rerun
# --------------------------------------------------------------------------------------


def test_adjustments_file_records_once_and_reruns_never_duplicate(world: World) -> None:
    proposals = world.root / "proposals.json"
    adjustment_id = world.proposals(proposals)
    journal = world.harness.assumptions

    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_OK
    assert len(journal.batch_update_calls) == 1
    (first,) = world.run_dirs()
    manifest = _manifest(first)
    assert manifest["adjustments_written"] == [adjustment_id]
    assert manifest["applied_adjustments"] == [adjustment_id]
    assert _relative_file(world, manifest["journal_snapshot"])
    assert (adjustments.WRITE_SCOPE,) in world.scopes
    world.harness.assert_no_cfo_writes()

    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_OK
    assert len(journal.batch_update_calls) == 1  # nothing written twice
    second = next(d for d in world.run_dirs() if d != first)
    rerun = _manifest(second)
    assert rerun["adjustments_written"] == []
    assert rerun["adjustments_already_recorded"] == [adjustment_id]
    assert rerun["applied_adjustments"] == [adjustment_id]
    assert rerun["journal_sha256"] == manifest["journal_sha256"]

    # A source-only run reads the recorded journal and writes nothing.
    world.scopes.clear()
    assert world.main() == runner.EXIT_OK
    assert len(journal.batch_update_calls) == 1
    assert set(world.scopes) == {(sources.READONLY_SCOPE,)}
    third = [d for d in world.run_dirs() if d not in (first, second)][0]
    assert _manifest(third)["applied_adjustments"] == [adjustment_id]


def test_a_failed_journal_write_publishes_nothing(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    proposals = world.root / "proposals.json"
    world.proposals(proposals)
    world.harness.assumptions._fail_first["batch_update"] = [
        make_api_error(403, message=f"{CFO_ID} {SECRET_CELL}", api_status="PERMISSION_DENIED")
    ]
    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_FAILED
    assert not (world.output / runner.POINTER_NAME).exists()
    stdout = capsys.readouterr().out
    assert "adjustments_failed" in stdout and "write_failed" in stdout
    assert SECRET_CELL not in stdout and CFO_ID not in stdout
    assert "may have landed" not in stdout
    (failed,) = world.run_dirs()
    record = _failed_record(world, failed)
    # Rejected outright on its only attempt with the tab unchanged: it cannot have landed.
    assert record["journal_write_may_have_landed"] is False
    assert record["journal_write_error"] == "write_failed"
    assert _relative_file(world, record["journal_snapshot"])


# --------------------------------------------------------------------------------------
# Failure recovery: the previous publication is kept byte for byte
# --------------------------------------------------------------------------------------


def _fail_capture(world: World) -> None:
    sheet = world.harness.cfo_sheets["Bank Checking"]
    sheet._fail_first["get_all_values"] = [
        make_api_error(403, message=f"{CFO_ID} {SECRET_CELL}", api_status="PERMISSION_DENIED")
    ]


def _fail_render(world: World) -> None:
    def broken(*_args: object, **_kwargs: object) -> bool:
        raise ExportError("export_unavailable", "headless Chromium could not be started")

    world.monkeypatch.setattr(export, "export_documents", broken)


def _fail_mail(world: World) -> None:
    def broken(*_args: object, **_kwargs: object) -> Any:
        raise gmail_source.GmailFetchError("the fictional fetch failed.", "retry later.")

    world.monkeypatch.setattr(gmail_source, "fetch_window", broken)


def _fail_bundle(world: World) -> None:
    world.category_map.unlink()


def _fail_validation(world: World) -> None:
    """The renderer returns, but a file of the set no longer matches what it rendered."""
    original = render.write

    def tampered(*args: Any, **kwargs: Any) -> Any:
        artifacts = original(*args, **kwargs)
        page = args[2] / "budget-snapshot.html"
        page.write_bytes(page.read_bytes() + b"<!-- changed -->")
        return artifacts

    world.monkeypatch.setattr(render, "write", tampered)


@pytest.mark.parametrize(
    ("case", "breaker", "code", "extra"),
    [
        ("capture", _fail_capture, "capture_failed", ()),
        ("render", _fail_render, "render_failed", ()),
        ("mail", _fail_mail, "mail_failed", ("--fetch-since", "2030-07-01")),
        ("refresh", _fail_bundle, "reimbursement_failed", ()),
        ("validation", _fail_validation, "validation_failed", ()),
    ],
)
def test_a_failed_run_keeps_the_previous_publication_and_is_recorded(
    world: World,
    capsys: pytest.CaptureFixture[str],
    case: str,
    breaker: Any,
    code: str,
    extra: tuple[str, ...],
) -> None:
    assert world.main() == runner.EXIT_OK
    (first,) = world.run_dirs()
    published = world.published()
    first_tree = _tree(first)
    capsys.readouterr()

    breaker(world)
    if case == "mail":
        result = cli._cmd_end_to_end_run(
            cli.build_parser().parse_args(world.args(*extra)), service=object()
        )
    else:
        result = world.main(*extra)
    assert result == runner.EXIT_FAILED

    stdout = capsys.readouterr().out
    assert code in stdout and "previous publication is unchanged" in stdout
    assert SECRET_CELL not in stdout and CFO_ID not in stdout
    current = world.published()
    for name in (runner.POINTER_NAME, *(alias for _n, alias in runner.COMPATIBILITY_FILES)):
        assert current[name] == published[name]
    assert _tree(first) == first_tree
    failed = next(d for d in world.run_dirs() if d != first)
    record = json.loads(
        (world.runs / runner.FAILED_RUNS_DIR / f"{failed.name}.json").read_text("utf-8")
    )
    assert record["status"] == "failed" and record["failure_codes"] == [code]
    assert SECRET_CELL not in json.dumps(record) and CFO_ID not in json.dumps(record)
    assert _manifest(failed)["status"] == "failed"
    assert not (world.runs / adjustments.LOCK_FILENAME).exists()
    if case == "refresh":  # a refresh that failed still records the store's digests after it
        assert record["bundle_sha256_after_refresh"] == _sha(world.bundle.read_bytes())
        assert record["sidecar_sha256_after_refresh"] == _sha(world.sidecar.read_bytes())


def test_a_pointer_that_cannot_be_replaced_keeps_the_previous_publication(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.main() == runner.EXIT_OK
    published = world.published()

    original = reimbursement_report.write_html_atomic
    pointer = world.output / runner.POINTER_NAME

    def refused(path: Path, html_text: str) -> None:
        if path == pointer:
            raise PermissionError("fictional lock on the pointer")
        original(path, html_text)

    monkeypatch.setattr(reimbursement_report, "write_html_atomic", refused)
    assert world.main() == runner.EXIT_FAILED
    assert world.published() == published
    assert "publish_failed" in capsys.readouterr().out
    # The pre-switch "published, pending" manifest is rewritten: never published, no copy state.
    failed = max(world.run_dirs())
    for record in (_manifest(failed), _failed_record(world, failed)):
        assert record["status"] == "failed"
        assert (record["published_at"], record["alias_refresh_state"]) == (None, None)


def test_alias_failure_is_explicit_and_keeps_the_new_pointer(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = "budget-snapshot.pdf"
    (world.output / blocked).mkdir()  # a folder where the compatibility file belongs
    assert world.main() == runner.EXIT_FAILED
    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    assert manifest["status"] == "published"
    assert manifest["failure_codes"] == ["alias_refresh_failed"]
    assert manifest["alias_refresh"][blocked] == "failed"
    refreshed = {a for a, status in manifest["alias_refresh"].items() if status == "refreshed"}
    assert refreshed == {a for _n, a in runner.COMPATIBILITY_FILES} - {blocked}
    assert run_dir.name in (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert (world.output / blocked).is_dir()
    assert not list(world.output.glob(f".{blocked}.*.tmp"))
    stdout = capsys.readouterr().out
    assert manifest["alias_refresh_state"] == "partial"
    assert "15 refreshed, 1 not refreshed (partial refresh)" in stdout
    assert f"not refreshed: {blocked}" in stdout


def test_a_manifest_that_cannot_be_finalized_is_reported_after_publication(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = sources._atomic_write

    def refuse_final(path: Path, data: bytes) -> None:
        if path.name == runner.MANIFEST_NAME and b'"alias_refresh_state":"complete"' in data:
            raise PermissionError("fictional lock on the manifest")
        original(path, data)

    monkeypatch.setattr(sources, "_atomic_write", refuse_final)
    assert world.main() == runner.EXIT_FAILED
    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    assert (manifest["status"], manifest["alias_refresh_state"]) == ("published", "pending")
    assert run_dir.name in (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert "manifest_failed" in capsys.readouterr().out


def test_an_unwritable_output_root_is_an_operational_failure(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.runs.write_text("not a folder", encoding="utf-8")
    before = _tree(world.root)
    assert world.main() == runner.EXIT_FAILED
    assert _tree(world.root) == before
    assert world.scopes == []
    assert "output_unavailable" in capsys.readouterr().out


def test_a_receipt_page_outside_the_staging_folder_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sidecar = json.loads(world.sidecar.read_text("utf-8"))
    sidecar["pages"][0]["path"] = "../outside.png"
    (world.output.parent / "outside.png").write_bytes(RECEIPT_PNG)
    # The viewer's own guard refuses this sidecar first; staging refuses it independently.
    monkeypatch.setattr(receipt_viewer, "headroom_bytes", lambda _path: 0)
    world.sidecar.write_text(json.dumps(sidecar), encoding="utf-8")
    assert world.main() == runner.EXIT_FAILED
    (run_dir,) = world.run_dirs()
    assert not (run_dir / "outside.png").exists()
    assert sorted(p.name for p in (run_dir / runner.INPUTS_DIR).iterdir()) == [
        world.bundle.name,
        world.sidecar.name,
    ]
    assert "staging_failed" in capsys.readouterr().out
    assert not (world.output / runner.POINTER_NAME).exists()


def test_two_sidecar_entries_naming_one_page_stage_it_once(world: World) -> None:
    sidecar = json.loads(world.sidecar.read_text("utf-8"))
    alias = dict(sidecar["pages"][0], id="page-1-again", path="./receipt-pages/page-1.png")
    sidecar["pages"].append(alias)
    sidecar["items"][0]["regions"].append({"page_id": "page-1-again", "box": None})
    world.sidecar.write_text(json.dumps(sidecar), encoding="utf-8")
    assert world.main() == runner.EXIT_OK
    (run_dir,) = world.run_dirs()
    staged = run_dir / runner.INPUTS_DIR / "receipt-pages"
    assert [p.name for p in staged.iterdir()] == ["page-1.png"]


def test_a_second_writer_is_refused_while_the_lock_is_held(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.runs.mkdir(parents=True)
    lock = world.runs / adjustments.LOCK_FILENAME
    lock.write_text('{"pid": 1, "token": "other-writer"}', encoding="utf-8")
    before = _tree(world.root)
    assert world.main() == runner.EXIT_FAILED
    assert _tree(world.root) == before
    assert world.scopes == []
    assert "run_busy" in capsys.readouterr().out


def test_the_runner_catches_the_one_sheets_failure_set() -> None:
    from np_finance import sheets as sheets_module

    assert runner.SHEETS_FAILURES is sheets_module.SHEETS_FAILURES
    assert adjustments.SHEETS_FAILURES is sheets_module.SHEETS_FAILURES
    assert runner.http_status is sheets_module.http_status


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            make_api_error(404, message=f"{CFO_ID} {SECRET_CELL}", api_status="NOT_FOUND"),
            "APIError 404",
        ),
        (RefreshError(f"{CFO_ID} {SECRET_CELL}"), "RefreshError"),
        (TransportError(f"{CFO_ID} {SECRET_CELL}"), "TransportError"),
        (FileNotFoundError(2, SECRET_CELL, CFO_ID), "FileNotFoundError"),
        (ValueError(f"{CFO_ID} {SECRET_CELL}"), "ValueError"),
    ],
)
def test_transport_failures_reach_output_as_type_and_status_only(
    failure: BaseException, expected: str
) -> None:
    """The stage boundary keeps workbook ids and cell text out of text and chaining."""

    def leak() -> None:
        raise failure

    with pytest.raises(runner.RunnerError) as caught:
        runner._attempt("capture_failed", leak)
    error = caught.value
    assert str(error) == f"capture_failed: {expected}"
    assert error.__cause__ is None and error.__context__ is None
    assert error.exit_code == runner.EXIT_FAILED


# --------------------------------------------------------------------------------------
# One failure path for everything after argument validation
# --------------------------------------------------------------------------------------


def _failed_record(world: World, run_dir: Path) -> dict[str, Any]:
    path = world.runs / runner.FAILED_RUNS_DIR / f"{run_dir.name}.json"
    value: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return value


def _relative_file(world: World, item: str) -> bool:
    """A recorded evidence path is relative to the output root and names an existing file."""
    path = Path(item)
    return not path.is_absolute() and not path.drive and (world.runs / item).is_file()


def _published_files(world: World) -> dict[str, bytes]:
    names = (runner.POINTER_NAME, *(alias for _n, alias in runner.COMPATIBILITY_FILES))
    return {name: (world.output / name).read_bytes() for name in names}


def test_an_unexpected_error_is_recorded_by_type_and_stage_only(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.main() == runner.EXIT_OK
    (first,) = world.run_dirs()
    published = _published_files(world)
    capsys.readouterr()

    def broken(*_args: object, **_kwargs: object) -> Any:
        raise KeyError(f"{CFO_ID} {SECRET_CELL}")

    monkeypatch.setattr(facts, "build_from", broken)
    assert world.main() == runner.EXIT_FAILED
    stdout = capsys.readouterr().out
    assert "unexpected_failure: KeyError during the facts stage" in stdout
    assert SECRET_CELL not in stdout and CFO_ID not in stdout and "Traceback" not in stdout
    assert _published_files(world) == published
    failed = next(d for d in world.run_dirs() if d != first)
    record = _failed_record(world, failed)
    assert (record["status"], record["stage"]) == ("failed", "facts")
    assert (record["failure_codes"], record["failure_type"]) == (["unexpected_failure"], "KeyError")
    assert SECRET_CELL not in json.dumps(record) and CFO_ID not in json.dumps(record)
    # The in-place evidence refresh is visible in the record; the published set is not changed.
    assert record["bundle_sha256_before_refresh"] == record["bundle_sha256_after_refresh"]
    assert record["bundle_sha256_after_refresh"] == _sha(world.bundle.read_bytes())
    assert _manifest(failed)["status"] == "failed"
    assert not (world.runs / adjustments.LOCK_FILENAME).exists()


def test_an_interrupt_before_publication_is_recorded_and_exits_130(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert world.main() == runner.EXIT_OK
    (first,) = world.run_dirs()
    published = _published_files(world)
    capsys.readouterr()

    def interrupted(*_args: object, **_kwargs: object) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(render, "write", interrupted)
    assert world.main() == runner.EXIT_INTERRUPTED
    stdout = capsys.readouterr().out
    assert "interrupted during the render stage" in stdout and "Traceback" not in stdout
    assert _published_files(world) == published
    failed = next(d for d in world.run_dirs() if d != first)
    record = _failed_record(world, failed)
    assert (record["failure_codes"], record["failure_type"]) == (
        ["interrupted"],
        "KeyboardInterrupt",
    )
    assert record["stage"] == "render"
    assert not (world.runs / adjustments.LOCK_FILENAME).exists()


def test_the_runner_re_raises_an_interrupt_after_recording_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(*_args: object, **_kwargs: object) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(facts, "build_from", interrupted)
    options = runner.RunOptions(
        as_of=AS_OF,
        config_dir=world.root,
        bundle_path=world.bundle,
        source=world.mail,
        category_map_path=world.category_map,
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run(options, world.config, out=lambda _line: None)
    (failed,) = world.run_dirs()
    assert _failed_record(world, failed)["stage"] == "facts"
    assert not (world.output / runner.POINTER_NAME).exists()
    assert not (world.runs / adjustments.LOCK_FILENAME).exists()


def test_a_failure_after_a_journal_write_keeps_the_write_evidence(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proposals = world.root / "proposals.json"
    adjustment_id = world.proposals(proposals)
    _fail_render(world)
    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_FAILED
    assert len(world.harness.assumptions.batch_update_calls) == 1
    (failed,) = world.run_dirs()
    for record in (_failed_record(world, failed), _manifest(failed)):
        assert record["status"] == "failed" and record["stage"] == "render"
        assert record["adjustments_written"] == [adjustment_id]
        assert (world.runs / record["journal_snapshot"]).is_file()
    assert not (world.output / runner.POINTER_NAME).exists()
    assert "render_failed" in capsys.readouterr().out


def test_a_set_whose_staging_folder_remains_is_never_published(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """render.write may raise staging_not_removed AFTER the full set is in the run folder."""
    assert world.main() == runner.EXIT_OK
    (first,) = world.run_dirs()
    published = _published_files(world)
    capsys.readouterr()

    def stuck(_path: Path) -> None:
        raise PermissionError("fictional scanner holds the staging folder")

    monkeypatch.setattr(render, "_remove_tree", stuck)
    assert world.main() == runner.EXIT_FAILED
    failed = next(d for d in world.run_dirs() if d != first)
    assert all((failed / name).is_file() for name in render.OUTPUT_NAMES)  # the full set
    assert "staging_not_removed" in capsys.readouterr().out
    assert _published_files(world) == published
    assert _manifest(failed)["status"] == "failed"
    assert _failed_record(world, failed)["failure_codes"] == ["render_failed"]


def test_the_lock_is_held_until_publication_completes(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = reimbursement_report.write_html_atomic
    pointer = world.output / runner.POINTER_NAME
    lock = world.runs / adjustments.LOCK_FILENAME
    during: list[int] = []

    def switching(path: Path, html_text: str) -> None:
        if path == pointer:
            assert lock.is_file()
            during.append(world.main())  # a second run attempted during the pointer switch
        original(path, html_text)

    monkeypatch.setattr(reimbursement_report, "write_html_atomic", switching)
    assert world.main() == runner.EXIT_OK
    assert during == [runner.EXIT_FAILED]
    assert "run_busy" in capsys.readouterr().out
    assert len(world.run_dirs()) == 1  # the refused run created no folder
    assert not lock.exists()


def _interrupt_copy(world: World, alias: str) -> None:
    original = shutil.copyfile

    def copy(source: Any, target: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(target).name.startswith(f".{alias}."):
            raise KeyboardInterrupt
        return original(source, target, *args, **kwargs)

    world.monkeypatch.setattr(shutil, "copyfile", copy)


def test_an_interrupt_during_the_compatibility_refresh_is_recorded_as_partial(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    interrupted_alias = "budget-snapshot.pdf"
    _interrupt_copy(world, interrupted_alias)
    assert world.main() == runner.EXIT_INTERRUPTED
    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    assert manifest["status"] == "published"
    assert manifest["alias_refresh_state"] == "partial"
    assert manifest["failure_codes"] == ["alias_refresh_failed", "alias_refresh_interrupted"]
    aliases = [alias for _n, alias in runner.COMPATIBILITY_FILES]
    position = aliases.index(interrupted_alias)
    statuses = manifest["alias_refresh"]
    assert all(statuses[a] == "refreshed" for a in aliases[:position])
    assert statuses[interrupted_alias] == "failed"
    assert all(statuses[a] == "not_attempted" for a in aliases[position + 1 :])
    assert run_dir.name in (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert not (world.runs / runner.FAILED_RUNS_DIR).exists()
    assert not list(world.output.glob(".*.tmp"))
    assert not (world.runs / adjustments.LOCK_FILENAME).exists()
    stdout = capsys.readouterr().out
    assert "(partial refresh)" in stdout and "interrupted after publication" in stdout


def test_any_error_on_one_copy_marks_it_failed_and_the_refresh_goes_on(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_alias = "fundraising-summary.png"
    original = shutil.copyfile

    def copy(source: Any, target: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(target).name.startswith(f".{broken_alias}."):
            raise RuntimeError("fictional copy failure")
        return original(source, target, *args, **kwargs)

    monkeypatch.setattr(shutil, "copyfile", copy)
    assert world.main() == runner.EXIT_FAILED
    (run_dir,) = world.run_dirs()
    statuses = _manifest(run_dir)["alias_refresh"]
    assert statuses[broken_alias] == "failed"
    assert {a for a, status in statuses.items() if status != "refreshed"} == {broken_alias}


def test_a_page_naming_another_input_set_is_never_published(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = render.RenderContext.from_capture_set

    def other_input_set(run_id: str, capture_set: Any, *, input_sha256: str | None = None) -> Any:
        return original(run_id, capture_set, input_sha256="0" * 64)

    monkeypatch.setattr(render.RenderContext, "from_capture_set", other_input_set)
    assert world.main() == runner.EXIT_FAILED
    assert "validation_failed" in capsys.readouterr().out
    assert not (world.output / runner.POINTER_NAME).exists()


def test_an_unexpected_error_after_publication_keeps_the_new_pointer(world: World) -> None:
    def out(line: str) -> None:
        if line.startswith("  published"):
            raise RuntimeError("fictional console failure")

    options = runner.RunOptions(
        as_of=AS_OF,
        config_dir=world.root,
        bundle_path=world.bundle,
        source=world.mail,
        category_map_path=world.category_map,
    )
    result = runner.run(options, world.config, out=out)
    assert (result.exit_code, result.failure_code) == (runner.EXIT_FAILED, "unexpected_failure")
    (run_dir,) = world.run_dirs()
    assert run_dir.name in (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert not (world.runs / runner.FAILED_RUNS_DIR).exists()


def test_a_published_run_is_never_recorded_failed_even_if_the_pointer_is_unreadable(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The in-process published flag decides; reading the pointer back is only the
    fallback for the instant between the atomic replace and setting that flag."""
    monkeypatch.setattr(runner, "_pointer_names", lambda _root, _run_id: False)

    def out(line: str) -> None:
        if line.startswith("  published"):
            raise RuntimeError("fictional console failure")

    options = runner.RunOptions(
        as_of=AS_OF,
        config_dir=world.root,
        bundle_path=world.bundle,
        source=world.mail,
        category_map_path=world.category_map,
    )
    result = runner.run(options, world.config, out=out)
    assert result.failure_code == "unexpected_failure"
    assert not (world.runs / runner.FAILED_RUNS_DIR).exists()
    (run_dir,) = world.run_dirs()
    assert _manifest(run_dir)["status"] == "published"


def test_an_unverifiable_pointer_folder_is_a_configuration_error(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unverifiable(*_args: object) -> Path:
        raise PermissionError("fictional identity check failure")

    monkeypatch.setattr(runner, "_private_output_path", unverifiable)
    before = _tree(world.root)
    assert world.main("--dry-run") == runner.EXIT_INVALID
    assert _tree(world.root) == before
    assert "config_invalid" in capsys.readouterr().out


def test_an_output_dir_outside_the_project_publishes_beside_it(
    world: World, tmp_path_factory: pytest.TempPathFactory
) -> None:
    external = tmp_path_factory.mktemp("external-private") / "runs"
    text = world.config_path.read_text("utf-8").replace(
        'output_dir = "reports/output/main-report-runs"',
        f"output_dir = {json.dumps(external.as_posix())}",
    )
    world.config_path.write_text(text, encoding="utf-8")
    assert world.main() == runner.EXIT_OK
    (run_dir,) = [p for p in external.iterdir() if p.name.startswith("run-")]
    pointer = external.parent / runner.POINTER_NAME
    assert run_dir.name in pointer.read_text("utf-8")
    assert f'href="runs/{run_dir.name}/{render.INDEX_HTML}"' in pointer.read_text("utf-8")
    assert not (world.output / runner.POINTER_NAME).exists()
    assert not world.runs.exists()


# --------------------------------------------------------------------------------------
# Journal writes that fail or are uncertain keep their evidence
# --------------------------------------------------------------------------------------


def test_a_journal_write_that_lands_but_fails_readback_keeps_its_evidence(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    proposals = world.root / "proposals.json"
    adjustment_id = world.proposals(proposals)
    journal = world.harness.assumptions
    journal.after_batch_update = lambda ws: ws.set_cell(0, 1, "Example edit")  # another editor
    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_FAILED
    assert len(journal.batch_update_calls) == 1  # the write landed
    (failed,) = world.run_dirs()
    for record in (_failed_record(world, failed), _manifest(failed)):
        assert record["stage"] == "adjustments"
        assert record["adjustments_attempted"] == [adjustment_id]
        assert record["journal_write_error"] == "concurrent_edit_detected"
        assert record["journal_write_may_have_landed"] is True
        assert len(record["journal_evidence"]) == 2  # pre-write snapshot + readback
        assert all(_relative_file(world, item) for item in record["journal_evidence"])
        assert record["journal_snapshot"] == record["journal_evidence"][0]
    assert not (world.output / runner.POINTER_NAME).exists()
    assert "adjustments_failed" in capsys.readouterr().out


def test_an_ambiguous_journal_timeout_is_recorded_as_possibly_landed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposals = world.root / "proposals.json"
    world.proposals(proposals)
    # Every attempt the client's retry policy allows times out; its backoff is recorded.
    policy = SheetsClient(world.config)
    cap = next(n for n in itertools.count(1) if policy.backoff_delay(n) is None)
    world.harness.assumptions._fail_first["batch_update"] = [ReadTimeout() for _ in range(cap)]
    sleep = RecordingSleep()
    original = adjustments.connect_journal_client
    monkeypatch.setattr(
        adjustments,
        "connect_journal_client",
        lambda config, **kwargs: original(config, **{**kwargs, "sleep": sleep}),
    )
    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_FAILED
    (failed,) = world.run_dirs()
    record = _failed_record(world, failed)
    assert record["journal_write_error"] == "write_failed"
    assert record["journal_write_may_have_landed"] is True
    assert _relative_file(world, record["journal_snapshot"])
    assert record["adjustments_written"] == []
    assert len(sleep.calls) == cap - 1  # a pause before every re-send


def test_a_journal_refused_before_writing_is_recorded_as_unwritten(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposals = world.root / "proposals.json"
    world.proposals(proposals)
    original = adjustments.connect_journal_client

    def edited_meanwhile(config: Any, **kwargs: Any) -> Any:
        world.harness.assumptions.set_cell(1, 1, "2.5")  # changed after the run captured it
        return original(config, **kwargs)

    monkeypatch.setattr(adjustments, "connect_journal_client", edited_meanwhile)
    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_FAILED
    (failed,) = world.run_dirs()
    record = _failed_record(world, failed)
    assert record["journal_write_error"] == "assumptions_changed"
    assert record["journal_write_may_have_landed"] is False
    assert (record["journal_snapshot"], record["journal_evidence"]) == (None, [])
    assert world.harness.assumptions.batch_update_calls == []


def _fail_after_landing(world: World, error: BaseException) -> None:
    def landed_then_failed(_sheet: Any) -> None:
        world.harness.assumptions.after_batch_update = None
        raise error

    world.harness.assumptions.after_batch_update = landed_then_failed


@pytest.mark.parametrize(
    ("error", "expected_exit", "code", "failure_type"),
    [
        (KeyboardInterrupt(), runner.EXIT_INTERRUPTED, "interrupted", "KeyboardInterrupt"),
        (RuntimeError("unclassified"), runner.EXIT_FAILED, "unexpected_failure", "RuntimeError"),
    ],
)
def test_an_unclassified_failure_after_the_journal_write_lands_records_it(
    world: World,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    expected_exit: int,
    code: str,
    failure_type: str,
) -> None:
    proposals = world.root / "proposals.json"
    adjustment_id = world.proposals(proposals)
    _fail_after_landing(world, error)
    assert world.main("--adjustments-file", str(proposals)) == expected_exit
    assert len(world.harness.assumptions.batch_update_calls) == 1  # the rows landed
    (failed,) = world.run_dirs()
    for record in (_failed_record(world, failed), _manifest(failed)):
        assert (record["failure_codes"], record["failure_type"]) == ([code], failure_type)
        assert record["stage"] == "adjustments"
        assert record["journal_write_may_have_landed"] is True
        assert record["adjustments_attempted"] == [adjustment_id]
        assert _relative_file(world, record["journal_snapshot"])
        assert record["journal_evidence"] == [record["journal_snapshot"]]
    assert not (world.output / runner.POINTER_NAME).exists()
    assert "journal write may have landed" in capsys.readouterr().out


def test_an_unclassified_failure_before_the_snapshot_records_no_landing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposals = world.root / "proposals.json"
    adjustment_id = world.proposals(proposals)

    def broken(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("fictional failure before the snapshot")

    monkeypatch.setattr(adjustments.backup, "snapshot_raw_tab", broken)
    assert world.main("--adjustments-file", str(proposals)) == runner.EXIT_FAILED
    (failed,) = world.run_dirs()
    record = _failed_record(world, failed)
    assert record["journal_write_may_have_landed"] is False
    assert record["adjustments_attempted"] == [adjustment_id]
    assert (record["journal_snapshot"], record["journal_evidence"]) == (None, [])
    assert world.harness.assumptions.batch_update_calls == []


# --------------------------------------------------------------------------------------
# Dry run failures stay value-free and write nothing
# --------------------------------------------------------------------------------------


def test_an_unexpected_dry_run_error_is_value_free_and_writes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*_args: object, **_kwargs: object) -> Any:
        raise KeyError(f"{CFO_ID} {SECRET_CELL}")

    monkeypatch.setattr(facts, "build_from", broken)
    before = _tree(world.root)
    assert world.main("--dry-run") == runner.EXIT_FAILED
    assert _tree(world.root) == before
    stdout = capsys.readouterr().out
    assert "[dry-run]: unexpected_failure: KeyError; nothing was written" in stdout
    assert SECRET_CELL not in stdout and CFO_ID not in stdout


def test_an_interrupted_dry_run_exits_130_and_writes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(*_args: object, **_kwargs: object) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(facts, "build_from", interrupted)
    before = _tree(world.root)
    assert world.main("--dry-run") == runner.EXIT_INTERRUPTED
    assert _tree(world.root) == before
    assert "[dry-run]: interrupted; nothing was written" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# Publication windows: the manifest never contradicts the pointer
# --------------------------------------------------------------------------------------


def test_an_interrupt_just_after_the_pointer_switch_is_not_a_failed_run(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = reimbursement_report.write_html_atomic
    pointer = world.output / runner.POINTER_NAME

    def switched_then_interrupted(path: Path, html_text: str) -> None:
        original(path, html_text)
        if path == pointer:
            raise KeyboardInterrupt

    monkeypatch.setattr(reimbursement_report, "write_html_atomic", switched_then_interrupted)
    assert world.main() == runner.EXIT_INTERRUPTED
    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    assert (manifest["status"], manifest["alias_refresh_state"]) == ("published", "pending")
    assert manifest["published_at"] is not None
    assert run_dir.name in pointer.read_text("utf-8")
    assert not (world.runs / runner.FAILED_RUNS_DIR).exists()
    assert "interrupted after publication" in capsys.readouterr().out


def test_an_error_just_after_the_pointer_switch_is_not_a_failed_run(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = reimbursement_report.write_html_atomic
    pointer = world.output / runner.POINTER_NAME

    def switched_then_failed(path: Path, html_text: str) -> None:
        original(path, html_text)
        if path == pointer:
            raise RuntimeError("fictional failure after the atomic replace")

    monkeypatch.setattr(reimbursement_report, "write_html_atomic", switched_then_failed)
    assert world.main() == runner.EXIT_FAILED
    (run_dir,) = world.run_dirs()
    assert _manifest(run_dir)["status"] == "published"
    assert not (world.runs / runner.FAILED_RUNS_DIR).exists()
    assert "RuntimeError after publication" in capsys.readouterr().out


def test_an_interrupt_during_the_final_manifest_write_leaves_it_consistent(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = sources._atomic_write

    def interrupted(path: Path, data: bytes) -> None:
        if path.name == runner.MANIFEST_NAME and b'"alias_refresh_state":"complete"' in data:
            raise KeyboardInterrupt
        original(path, data)

    monkeypatch.setattr(sources, "_atomic_write", interrupted)
    assert world.main() == runner.EXIT_INTERRUPTED
    (run_dir,) = world.run_dirs()
    manifest = _manifest(run_dir)
    assert (manifest["status"], manifest["alias_refresh_state"]) == ("published", "pending")
    assert run_dir.name in (world.output / runner.POINTER_NAME).read_text("utf-8")
    assert not (world.runs / runner.FAILED_RUNS_DIR).exists()


@pytest.mark.parametrize(
    "override",
    [
        {"run_id": "run-unrelated"},
        {"input_sha256": "0" * 64},
        {"run_link": "main-report-runs/run-unrelated"},
    ],
    ids=["run-id", "input-set", "index-link"],
)
def test_a_pointer_page_that_does_not_name_the_run_is_never_published(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    override: dict[str, str],
) -> None:
    assert world.main() == runner.EXIT_OK
    (first,) = world.run_dirs()
    published = _published_files(world)
    capsys.readouterr()
    original = render.pointer_page

    def unnamed(**kwargs: Any) -> str:
        return original(**{**kwargs, **override})

    monkeypatch.setattr(render, "pointer_page", unnamed)
    assert world.main() == runner.EXIT_FAILED
    assert _published_files(world) == published
    failed = next(d for d in world.run_dirs() if d != first)
    manifest = _manifest(failed)
    assert manifest["status"] == "failed"
    assert (manifest["published_at"], manifest["alias_refresh_state"]) == (None, None)
    assert _failed_record(world, failed)["failure_codes"] == ["publish_failed"]
    assert "publish_failed" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# Configured receipt preparation runs, and dry-run keeps it write-free
# --------------------------------------------------------------------------------------

RECEIPT_URL = "https://uploads.example.org/fictional-receipt.png"
RECEIPT_TOML = """
[receipt_refresh]
allowlist = ["uploads.example.org"]
cache_dir = "reports/output/receipt-cache"
pages_dir = "reports/output/receipt-pages"
"""


def test_configured_receipt_preparation_runs_and_reaches_the_staged_sidecar(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.config_path.write_text(
        world.config_path.read_text("utf-8") + RECEIPT_TOML, encoding="utf-8"
    )
    configured = cli.load_config(world.config_path).receipt_refresh
    assert configured is not None
    (world.mail / "request-1.eml").unlink()
    _submission(world.mail / "request-1.eml", FIRST_REQUEST, receipt_url=RECEIPT_URL)
    cached = world.root / "fictional-upload.png"
    Image.new("RGB", (320, 180), "white").save(cached, format="PNG")
    payload = cached.read_bytes()
    fetched: list[int] = []

    def fetch_assets(urls: Any, **_kwargs: Any) -> list[receipt_assets.AssetResult]:
        fetched.append(1)
        return [
            receipt_assets.AssetResult(
                RECEIPT_URL,
                "fictional-key",
                receipt_assets.ASSET_ID.prefix + hashlib.sha256(payload).hexdigest(),
                "png",
                cached,
                len(payload),
                "cached",
                "",
            )
        ]

    calls: list[dict[str, Any]] = []
    original = receipt_refresh.refresh_receipts

    def spy(**kwargs: Any) -> receipt_refresh.RefreshSummary:
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(receipt_refresh.receipt_assets, "fetch_assets", fetch_assets)
    monkeypatch.setattr(receipt_refresh, "refresh_receipts", spy)

    before = _tree(world.root)
    assert world.main("--dry-run") == runner.EXIT_OK
    assert _tree(world.root) == before
    (dry,) = calls
    assert (dry["dry_run"], dry["config"]) == (True, configured)
    assert fetched == []

    calls.clear()
    assert world.main() == runner.EXIT_OK
    (real,) = calls
    assert (real["dry_run"], real["config"]) == (False, configured)
    assert fetched == [1]
    (run_dir,) = world.run_dirs()
    staged = json.loads(
        (run_dir / runner.INPUTS_DIR / world.sidecar.name).read_text(encoding="utf-8")
    )
    review_key = "submission:v1:" + hashlib.sha256(FIRST_REQUEST.encode()).hexdigest()
    assert review_key in {item["review_key"] for item in staged["items"]}
    assert len(staged["pages"]) == 2  # the existing page plus the prepared upload
    assert all((run_dir / runner.INPUTS_DIR / page["path"]).is_file() for page in staged["pages"])
    assert staged == json.loads(world.sidecar.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Mail acquisition reuses the existing window semantics
# --------------------------------------------------------------------------------------


def test_fetch_window_lands_beside_the_archive_before_the_refresh(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fetch(service: Any, **kwargs: Any) -> gmail_source.FetchSummary:
        calls.append(kwargs)
        _submission(kwargs["out_dir"] / "request-2.eml", SECOND_REQUEST, day="22", amount="9.50")
        return gmail_source.FetchSummary("query", kwargs["out_dir"], 1, 1, 0, 0, False)

    monkeypatch.setattr(gmail_source, "fetch_window", fetch)
    args = world.args("--fetch-since", "2030-07-01", "--fetch-until", "2030-08-16")
    result = cli._cmd_end_to_end_run(cli.build_parser().parse_args(args), service=object())
    assert result == runner.EXIT_OK
    assert calls == [
        {
            "since": date(2030, 7, 1),
            "until": date(2030, 8, 16),
            "extra_query": None,
            "out_dir": world.mail,
            "limit": None,
            "dry_run": False,
        }
    ]
    assert _tickets(world.bundle) == 4


def test_the_received_cutoff_reaches_the_refresh(world: World) -> None:
    _submission(world.mail / "request-2.eml", SECOND_REQUEST, day="20", amount="9.50")
    assert world.main("--received-since", "2030-07-21") == runner.EXIT_OK
    assert _tickets(world.bundle) == 3  # the 20 July submission is before the cutoff


# --------------------------------------------------------------------------------------
# Headless Chromium: the same CLI cycle with the real PDF/PNG export
# --------------------------------------------------------------------------------------


def test_chromium_end_to_end_run_publishes_real_exports_within_the_bound(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_chromium()
    monkeypatch.setattr(export, "export_documents", REAL_EXPORT)
    started = time.monotonic()
    with warnings.catch_warnings():
        # Off Windows the export runs unsandboxed and says so; the manifest records it.
        warnings.simplefilter("ignore", export.UnsandboxedExportWarning)
        assert world.main() == runner.EXIT_OK
    assert time.monotonic() - started < SMOKE_SECONDS
    (run_dir,) = world.run_dirs()
    for name in render.SUMMARY_NAMES:
        assert (run_dir / f"{name}.pdf").read_bytes().startswith(b"%PDF-")
        assert (run_dir / f"{name}.png").read_bytes().startswith(PNG_SIGNATURE)
        assert (world.output / f"{name}.pdf").read_bytes() == (run_dir / f"{name}.pdf").read_bytes()
    assert _manifest(run_dir)["artifacts"]["export_sandboxed"] == export.default_sandbox()
