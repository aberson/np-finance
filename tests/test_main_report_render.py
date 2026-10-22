"""Tests for pta_finance.main_reports.render and export — the five-report Main Report Set.

Every fixture is fictional (``Example`` placeholders, fake ids). Content cases run the
production path without a browser: fake gspread workbooks -> read-only capture ->
reconciliation -> recorded adjustments -> :func:`facts.build_from` -> :func:`render.write`
with an injected exporter, which reuses the existing reimbursement queue renderer with a
fictional receipt sidecar. Only the ``test_chromium_*`` cases drive headless Chromium (real
PDF/PNG export, readable layouts, the request guard); they skip only when Playwright reports
its browser executable missing. Nothing reaches the network or a live workbook.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import http.server
import json
import re
import shutil
import struct
import sys
import threading
import zlib
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from markupsafe import escape

from pta_finance import receipt_viewer, reimbursement_report
from pta_finance.main_reports import export, facts, render
from pta_finance.main_reports.export import (
    ExportError,
    ExportJob,
    UnsandboxedExportWarning,
    export_documents,
)
from pta_finance.main_reports.facts import build_from
from pta_finance.main_reports.models import (
    ARTIFACT_MEDIA_TYPES,
    EXPENSE_BUCKETS,
    ArtifactSet,
    Bridge,
    CaptureSet,
    ReportFacts,
    SourceRef,
    is_valid_run_id,
    make_run_id,
)
from pta_finance.main_reports.render import (
    INDEX_HTML,
    OUTPUT_NAMES,
    QUEUE_HTML,
    STAGING_PREFIX,
    SUMMARY_NAMES,
    RenderContext,
    RenderError,
    SourceFreshness,
    format_money,
    write,
)
from pta_finance.reimbursement_report import STATUS_META
from tests.conftest import (
    BANK_ROWS,
    BUDGET_ROWS,
    CROSSWALK_TOML,
    PNL_VALUES,
    Scenario,
    _adjusted_scenario,
    _bank,
    _budget_row,
    _bundle_payload,
    _record_payment,
)

RUN_ID = make_run_id(datetime(2030, 8, 15, 13, 0, tzinfo=UTC))
OTHER_RUN_ID = make_run_id(datetime(2030, 8, 16, 9, 0, tzinfo=UTC))
HOSTILE = "<script>alert(1)</script>\"'</title>&=SUM(A1)"
RAW_MARKER = "<script>alert(1)"
ESCAPED = str(escape(HOSTILE))
SCHOOL_LABEL = "School year 2030–31"
SCHOOL_RANGE = "July 1, 2030 to June 30, 2031"
CALENDAR_LABEL = "Calendar year 2030"
CALENDAR_RANGE = "January 1, 2030 to December 31, 2030"
SUMMARY_HTML = [f"{name}.html" for name in SUMMARY_NAMES]
SUMMARY_FILES = [f"{name}.{suffix}" for name in SUMMARY_NAMES for suffix in ("html", "pdf", "png")]
COPY_TEXT = "reimbursement-report.copy.txt"
ALL_FILES = sorted([QUEUE_HTML, COPY_TEXT, INDEX_HTML, *SUMMARY_FILES])
HTML_FILES = [QUEUE_HTML, INDEX_HTML, *SUMMARY_HTML]
TITLES = {
    "reimbursement-summary.html": "Reimbursement Summary",
    "budget-snapshot.html": "Budget Snapshot",
    "fundraising-summary.html": "Fundraising Summary",
    "cfo-pnl-summary.html": "CFO P&L Summary",
}
BUCKET_LABELS = {
    "prior": "Before the period",
    "current": "In the period",
    "later": "After the as-of date",
    "undated": "Undated",
    "unpaid": "Not paid",
}
BRIDGE_PAGES = {
    "school_source_scope": "budget-snapshot.html",
    "school_adjustments": "budget-snapshot.html",
    "school_budget_crosswalk": "budget-snapshot.html",
    "calendar_source_scope": "cfo-pnl-summary.html",
    "calendar_adjustments": "cfo-pnl-summary.html",
    "calendar_to_school": "cfo-pnl-summary.html",
    "school_payment_timing": "reimbursement-summary.html",
    "school_expense_basis": "reimbursement-summary.html",
}
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
    "form-action 'none'"
)
FAKE_PDF = b"%PDF-1.4\n% fictional export stand-in\n"


# --------------------------------------------------------------------------------------
# Fictional run inputs
# --------------------------------------------------------------------------------------


def _png(width: int, height: int, line: tuple[int, int] = (0, 0)) -> bytes:
    """A white grayscale PNG with an optional gray band between rows ``line``."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(
        b"\0" + bytes([170 if line[0] <= y < line[1] else 255]) * width for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


RECEIPT_PNG = _png(200, 300, (100, 110))


def fake_exporter(jobs: Sequence[ExportJob]) -> None:
    """Stand-in for the Chromium export: minimal valid PDF/PNG files for every job."""
    for job in jobs:
        job.pdf.write_bytes(FAKE_PDF + job.html.name.encode())
        job.png.write_bytes(RECEIPT_PNG)


def _stage(source: Path, root: Path) -> Path:
    """Copy the bundle into a staged directory with a fictional receipt sidecar beside it."""
    root.mkdir(parents=True)
    staged = root / "reimbursement-report.json"
    shutil.copyfile(source, staged)
    report = reimbursement_report.load_bundle(staged)
    ticket = report.active_tickets[0]
    (root / "receipt-1.png").write_bytes(RECEIPT_PNG)
    sidecar = {
        "schema_version": 1,
        "pages": [
            {
                "id": "page-1",
                "path": "receipt-1.png",
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
    staged.with_suffix(".receipts.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return staged


@dataclasses.dataclass
class RunInputs:
    capture_set: CaptureSet
    facts: ReportFacts
    staged: Path
    run_dir: Path
    context: RenderContext

    def write(self, **kwargs: Any) -> ArtifactSet:
        kwargs.setdefault("exporter", fake_exporter)
        context = kwargs.pop("context", self.context)
        report = kwargs.pop("facts", self.facts)
        return write(report, self.staged, self.run_dir, context=context, **kwargs)


def _inputs(
    tmp_path: Path, *, adjusted: bool = True, extra_source: bool = False, **kwargs: Any
) -> RunInputs:
    if adjusted:
        scenario, _, _ = _adjusted_scenario(tmp_path / "world", **kwargs)
    else:
        scenario = Scenario(tmp_path / "world", **kwargs)
    capture_set, ledger, bundle = scenario.inputs()
    result = build_from(capture_set, ledger, bundle, scenario.config)
    staged = _stage(scenario.bundle_path, tmp_path / "staged")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    context = RenderContext.from_capture_set(RUN_ID, capture_set)
    if extra_source:  # a freshness entry whose label is hostile text
        note = SourceFreshness(
            label=HOSTILE,
            kind="notes",
            captured_at=datetime(2030, 8, 15, 12, 0, tzinfo=UTC),
            sha256="a" * 64,
        )
        context = dataclasses.replace(context, sources=(*context.sources, note))
    return RunInputs(capture_set, result, staged, run_dir, context)


def _hostile_bundle() -> dict[str, Any]:
    payload = _bundle_payload()
    payload["report"]["organization"] = HOSTILE
    payload["report"]["logo_data_uri"] = "data:image/png;base64," + base64.b64encode(
        RECEIPT_PNG
    ).decode("ascii")
    tickets = {ticket["ref"]: ticket for ticket in payload["tickets"]}
    for ticket in payload["tickets"]:
        for item in ticket["items"]:
            if item["item_key"] == "new-03:line:2":
                item["item_key"] = f"new-03:{HOSTILE}"
    # A prior-year payment recorded with a hostile reference (an unjoined bank lookup).
    _record_payment(payload, tickets["P-002"], "2030-03-05", f"Ref {HOSTILE}", "e")
    # An item without an amount (the request total stays the sum of priced items).
    unpriced = tickets["NEW-04"]
    unpriced["items"][0]["source_amount"] = ""
    unpriced["source"]["stated_total"] = ""
    unpriced["source"]["mapped_total"] = "0.00"
    tickets["P-001"]["ref"] = f"P-001 {HOSTILE}"
    tickets["NEW-01"]["ref"] = f"NEW-01 {HOSTILE}"  # the joined ticket
    return payload


CONTENT_WORLD: dict[str, Any] = {
    "bank": [*BANK_ROWS, _bank("7/20/2030", "Example vendor E", "-3.00", HOSTILE)],
    "budget": [
        *BUDGET_ROWS,
        _budget_row("2031", "expense", "proposed", "50", f"{HOSTILE} line"),
        _budget_row("2031", "expense", "proposed", "not a number", "Supplies Reserve"),
        _budget_row("2031", "transfer", "proposed", "10", "Fees and Charges"),
        _budget_row("2031", "", "proposed", "5", "Yearbook"),
    ],
    "mapping": [["Spirit", HOSTILE]],
    # Donations map to a budget category that has no adopted line (hostile name).
    "crosswalk": CROSSWALK_TOML
    + "[[main_reports.crosswalk.entries]]\n"
    + 'source_category = "Donations"\n'
    + f'targets = [{{ category = {json.dumps(HOSTILE)}, share = "1" }}]\n'
    + 'note = "fictional"\n',
    "bundle": _hostile_bundle(),
}


@dataclasses.dataclass
class RenderedSet:
    inputs: RunInputs
    artifacts: ArtifactSet

    @property
    def facts(self) -> ReportFacts:
        return self.inputs.facts

    def html(self, name: str) -> str:
        return (self.inputs.run_dir / name).read_text(encoding="utf-8")

    def tables(self, name: str) -> dict[str, list[list[Cell]]]:
        return _tables(self.html(name))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> RenderedSet:
    """One rendered set (stand-in exporter, no browser). Tests only read it."""
    tmp_path = tmp_path_factory.mktemp("main-report-set")
    inputs = _inputs(tmp_path, extra_source=True, **CONTENT_WORLD)
    before = _files(tmp_path)
    artifacts = inputs.write()
    after = _files(tmp_path)
    changed = {name for name in after if before.get(name) != after[name]}
    assert changed == {f"run/{name}" for name in ALL_FILES}, "rendering wrote outside run_dir"
    return RenderedSet(inputs, artifacts)


# --------------------------------------------------------------------------------------
# Rendered-HTML helpers
# --------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Cell:
    text: str
    classes: frozenset[str]


_VOID = {"br", "img", "meta", "link", "hr", "input"}


class _TableParser(HTMLParser):
    """Rows of every table, keyed by the nearest enclosing element ``id``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.tables: dict[str, list[list[Cell]]] = defaultdict(list)
        self.row: list[Cell] | None = None
        self.cell: tuple[list[str], str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in _VOID:
            if self.cell is not None:
                self.cell[0].append(" ")
            return
        self.stack.append((tag, values.get("id")))
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = ([], values.get("class") or "")
        elif tag == "li" and self.cell is not None:
            self.cell[0].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            text = " ".join("".join(self.cell[0]).split())
            self.row.append(Cell(text, frozenset(self.cell[1].split())))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            owner = next((ident for _, ident in reversed(self.stack) if ident), "")
            self.tables[owner].append(self.row)
            self.row = None
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell[0].append(data)


def _tables(html: str) -> dict[str, list[list[Cell]]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


def _texts(rows: Sequence[Sequence[Cell]]) -> list[list[str]]:
    return [[cell.text for cell in row] for row in rows]


def _body(rows: Sequence[Sequence[Cell]]) -> list[list[Cell]]:
    """Rows without the header row(s) (all-``th`` rows are not distinguishable, so the
    first row of each owner is the header in these templates)."""
    return [list(row) for row in rows[1:]]


def _text(html: str) -> str:
    """Visible text of the body: tags removed, entities decoded, whitespace collapsed."""
    body = html.split("<body>", 1)[1]
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", body)).split())


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _png_size(payload: bytes) -> tuple[int, int]:
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", payload[16:24])
    return int(width), int(height)


def _png_distinct_bytes(payload: bytes) -> int:
    """Distinct values in the decompressed image data (a blank image has very few)."""
    position, data = 8, b""
    while position < len(payload):
        (length,) = struct.unpack(">I", payload[position : position + 4])
        kind = payload[position + 4 : position + 8]
        if kind == b"IDAT":
            data += payload[position + 8 : position + 8 + length]
        position += 12 + length
    return len(set(zlib.decompress(data)))


def _assert_clean_error(error: BaseException) -> None:
    """Error text names codes and counts only; nothing raw is chained."""
    assert error.__cause__ is None
    assert error.__suppress_context__ or error.__context__ is None
    assert "$" not in str(error)
    assert not re.search(r"\d+\.\d\d\b", str(error))


def _ref_text(ref: SourceRef) -> str:
    return f"{ref.source_alias} row {ref.row_number} (revision {ref.revision_hash[:8]})"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


# --------------------------------------------------------------------------------------
# The complete set through the production path
# --------------------------------------------------------------------------------------


def test_all_five_reports_and_the_index_are_written_with_their_artifact_set(
    rendered: RenderedSet,
) -> None:
    artifacts = rendered.artifacts
    run_dir = rendered.inputs.run_dir
    assert list(artifacts.paths) == ALL_FILES
    assert sorted(p.name for p in run_dir.iterdir()) == ALL_FILES  # no staging left behind
    assert artifacts.run_id == RUN_ID
    media = {item.path: item.media_type for item in artifacts.artifacts}
    assert set(media.values()) == set(ARTIFACT_MEDIA_TYPES)
    for item in artifacts.artifacts:
        payload = (run_dir / item.path).read_bytes()
        assert item.byte_length == len(payload) > 0
        assert item.sha256 == hashlib.sha256(payload).hexdigest()
        suffix = item.path.rsplit(".", 1)[1]
        assert (
            media[item.path]
            == {
                "html": "text/html",
                "pdf": "application/pdf",
                "png": "image/png",
                "txt": "text/plain",
            }[suffix]
        )
    for name in SUMMARY_NAMES:  # each export belongs to its own summary
        assert (run_dir / f"{name}.pdf").read_bytes() == FAKE_PDF + f"{name}.html".encode()
    assert json.loads(json.dumps(artifacts.to_dict()))["artifacts"][0]["path"] == ALL_FILES[0]
    assert artifacts.get(INDEX_HTML).media_type == "text/html"


def test_every_page_names_its_period_basis_as_of_run_and_freshness(
    rendered: RenderedSet,
) -> None:
    expected = {
        "reimbursement-summary.html": (SCHOOL_LABEL, SCHOOL_RANGE),
        "budget-snapshot.html": (SCHOOL_LABEL, SCHOOL_RANGE),
        "fundraising-summary.html": (SCHOOL_LABEL, SCHOOL_RANGE),
        "cfo-pnl-summary.html": (CALENDAR_LABEL, CALENDAR_RANGE),
    }
    captured = {c.alias: c.captured_at for c in rendered.inputs.capture_set.captures}
    facts_ = rendered.facts
    for name, (label, period_range) in expected.items():
        html = rendered.html(name)
        text = _text(html)
        title = str(escape(f"{TITLES[name]} · {label}"))
        assert f"<title>{title}</title>" in html
        assert f'<meta http-equiv="Content-Security-Policy" content="{CSP}">' in html
        assert f"{label} · {period_range} · through August 15, 2030" in text
        assert "As of August 15, 2030" in text
        assert f'<meta name="pta-run-id" content="{RUN_ID}">' in html
        assert RUN_ID in text and rendered.inputs.capture_set.aggregate_sha256[:16] in text
        assert "Basis." in text
        assert f"{captured['bank-checking']:%Y-%m-%d %H:%M} UTC" in text
        assert f"Adjustments applied {len(facts_.applied_adjustments)}" in text
        assert f"Unresolved discrepancies {len(facts_.discrepancy_ids)}" in text
        assert f"Findings {sum(issue.count for issue in facts_.issues)}" in text
        assert f'href="{INDEX_HTML}"' in html and f'href="{QUEUE_HTML}"' in html
    # The legacy FY label names the school year only, never the calendar-year P&L.
    assert "Period School year 2030–31 (FY2031)" in _text(rendered.html("budget-snapshot.html"))
    pnl = _text(rendered.html("cfo-pnl-summary.html"))
    assert "Period Calendar year 2030 As of" in pnl and "(FY" not in pnl
    assert "(FY" not in _text(rendered.html(INDEX_HTML))
    assert "No calendar-year budget is shown" in pnl
    budget = _text(rendered.html("budget-snapshot.html"))
    assert "No calendar-year budget is derived" in budget


def test_freshness_table_lists_every_input_with_capture_time_and_coverage(
    rendered: RenderedSet,
) -> None:
    rows = _texts(_body(rendered.tables("budget-snapshot.html")["freshness"]))
    labels = [row[0] for row in rows]
    capture_set = rendered.inputs.capture_set
    assert labels == [
        *(c.alias for c in capture_set.captures),
        capture_set.assumptions.alias,
        capture_set.adopted_budget.tab_title,
        HOSTILE,
    ]
    by_label = {row[0]: row for row in rows}
    bank = capture_set.by_alias["bank-checking"]
    assert by_label["bank-checking"][1:] == [
        "Bank",
        f"{bank.captured_at:%Y-%m-%d %H:%M} UTC",
        f"{bank.observed_first.isoformat()} to {bank.observed_last.isoformat()}"
        if bank.observed_first and bank.observed_last
        else "No dated rows",
        "Complete for the period",
        bank.sha256[:12],
    ]
    assert by_label["paypal"][4].startswith("Partial: no declared coverage 2030-07-01 to")
    assert by_label["pnl"][1] == "P&L" and by_label["pnl"][4] == "Not a transaction feed"


def test_reimbursement_summary_tables_follow_the_facts(rendered: RenderedSet) -> None:
    data = rendered.facts.reimbursements
    tables = rendered.tables("reimbursement-summary.html")
    statuses = list(STATUS_META)
    header = _texts(tables["expense"][:1])[0]
    assert header == [
        "Expense date",
        "APPROVED",
        "CLARIFICATION",
        "DECLINE",
        "UNREVIEWED",
        "No status",
    ]

    headline = re.findall(
        r'<div class="box ?[a-z]*"><div class="n">([^<]*)</div><div class="k">([^<]*)</div>',
        rendered.html("reimbursement-summary.html")
        .split('<div class="score">')[1]
        .split("</div>\n")[0],
    )
    assert headline == [
        (format_money(data.outstanding), "Approved, not yet paid"),
        (str(len(data.queue)), "Requests in the queue"),
        (str(sum(1 for e in data.queue if e.carryover)), "Prior-year carryovers"),
        (format_money(data.expense("current", "A")), "Approved expense dated in the period"),
        (format_money(data.paid("current")), "Paid in the period"),
        (format_money(data.paid("current", "prior")), "Paid in the period for prior-year expenses"),
    ]
    assert 0 < sum(1 for e in data.queue if e.carryover) < len(data.queue)
    assert data.paid("current", "prior") > 0 and data.expense("current", "A") > 0

    def cell(bucket: str, status: str) -> str:
        groups = [t for t in data.totals if t.expense_bucket == bucket and t.status == status]
        count, unpriced = sum(t.count for t in groups), sum(t.unpriced for t in groups)
        text = f"{format_money(data.expense(bucket, status))} {_plural(count, 'item')}"
        return text + (f" · {unpriced} without an amount" if unpriced else "")

    assert _texts(_body(tables["expense"])) == [
        [BUCKET_LABELS[b], *(cell(b, s) for s in statuses)] for b in EXPENSE_BUCKETS
    ]
    assert _texts(_body(tables["payments"])) == [
        *([BUCKET_LABELS[b], format_money(data.paid("current", b))] for b in EXPENSE_BUCKETS),
        ["Reimbursements paid in the period", format_money(data.paid("current"))],
    ]
    opens = [data.open_amount(b, "A") for b in EXPENSE_BUCKETS]
    assert sum(opens, Decimal("0.00")) == data.outstanding
    assert _texts(_body(tables["obligations"])) == [
        *([BUCKET_LABELS[b], format_money(a)] for b, a in zip(EXPENSE_BUCKETS, opens, strict=True)),
        ["Approved and not yet paid (all open requests)", format_money(data.outstanding)],
    ]
    basis = {"expense_date": "By expense date", "submitted": "By submitted", None: "No"}
    assert _texts(_body(tables["queue"])) == [
        [
            entry.ticket_ref,
            entry.origin.capitalize(),
            entry.submitted.isoformat(),
            entry.earliest_expense_date.isoformat()
            if entry.earliest_expense_date
            else "Not recorded",
            str(entry.undated_items),
            format_money(entry.pay_now),
            basis[entry.carryover_basis],
        ]
        for entry in data.queue
    ]
    assert any(e.carryover for e in data.queue) and any(not e.carryover for e in data.queue)
    states = {
        "matched": "Matched",
        "no_reference": "No reference",
        "unmatched": "Unmatched",
        "ambiguous": "Ambiguous",
        "outside_capture_window": "Outside capture window",
    }
    assert _texts(_body(tables["joins"])) == [
        [
            join.ticket_ref,
            states[join.state],
            join.payment_date.isoformat() if join.payment_date else "Not recorded",
            join.reference or "Not recorded",
            format_money(join.amount) if join.amount is not None else "Not recorded",
            "; ".join(_ref_text(ref) for ref in join.bank_refs) or "None",
        ]
        for join in data.joins
    ]
    assert {"matched", "unmatched"} <= {join.state for join in data.joins}
    labels = {code: STATUS_META[code][0] for code in STATUS_META} | {"-": "No status"}
    groups = _body(tables["groups"])
    assert [[c.text for c in row] for row in groups] == [
        [
            BUCKET_LABELS[t.expense_bucket],
            BUCKET_LABELS[t.payment_bucket],
            labels[t.status],
            "Open" if t.open else "Settled",
            str(t.count),
            format_money(t.amount),
            str(t.unpriced),
        ]
        for t in data.totals
    ]
    assert [("unknown" in row[6].classes) for row in groups] == [
        bool(t.unpriced) for t in data.totals
    ]
    # The fixture's unpriced item stays visible: counted, never priced as $0.00 silently.
    unpriced = [t for t in data.totals if t.unpriced]
    assert [(t.expense_bucket, t.status, t.unpriced) for t in unpriced] == [("later", "Q", 1)]
    later = next(row for row in _body(tables["expense"]) if row[0].text == "After the as-of date")
    assert later[4].text == "$0.00 1 item · 1 without an amount"


def test_budget_snapshot_tables_follow_the_facts(rendered: RenderedSet) -> None:
    budget = rendered.facts.budget
    tables = rendered.tables("budget-snapshot.html")
    rows = _body(tables["lines"])
    assert len(rows) == len(budget.lines)
    reasons = {
        "category_unmapped": "Unknown: no source category maps to this budget category",
        "ambiguous": "Unknown: the category has more than one adopted line",
    }
    for row, line in zip(rows, budget.lines, strict=True):
        typed = line.line_type in ("income", "expense")
        activity = None
        if line.actual is not None and typed:
            activity = line.actual if line.line_type == "income" else -line.actual
        remaining = None if line.target is None or activity is None else line.target - activity
        if line.actual is None:
            status = reasons[line.actual_status]
        elif not typed:
            status = "Unknown: the line type is not income or expense"
        else:
            status = "Observed"
        assert [c.text for c in row] == [
            line.line_type.capitalize() or "Not recorded",
            line.category,
            format_money(line.target),
            format_money(line.actual),
            format_money(activity),
            format_money(remaining),
            status,
        ]
        assert ("unknown" in row[2].classes) == (line.target is None)
        assert ("unknown" in row[4].classes) == (activity is None)
    library = next(row for row in rows if row[1].text == "Library Books")
    assert [c.text for c in library[3:6]] == ["Unknown"] * 3  # never $0.00
    assemblies = next(row for row in rows if row[1].text == "Assemblies")
    assert [c.text for c in assemblies[2:6]] == ["$200.00", "$0.00", "$0.00", "$200.00"]
    untyped = next(row for row in rows if row[1].text == "Fees and Charges")
    assert untyped[3].text != "Unknown" and untyped[4].text == "Unknown"
    assert _texts(_body(tables["outside"])) == [
        *(["Mapped, no adopted line", n, format_money(a)] for n, a in budget.unbudgeted),
        *(
            ["Source category without a crosswalk entry", n, format_money(a)]
            for n, a in budget.unmapped
        ),
    ]
    assert HOSTILE in [n for n, _ in budget.unmapped]
    # Headline target totals: known targets only, visibly partial with the unknown count.
    html = rendered.html("budget-snapshot.html")
    income = sum(
        (x.target for x in budget.lines if x.line_type == "income" and x.target), Decimal(0)
    )
    expense = sum(
        (x.target for x in budget.lines if x.line_type == "expense" and x.target), Decimal(0)
    )
    assert (
        f'<div class="n">{format_money(income)}</div><div class="k">Adopted income targets</div>'
        in html
    )
    assert (
        f'<div class="n partial">{format_money(expense)}</div>'
        '<div class="k">Adopted expense targets · 1 line without a readable target</div>'
    ) in html
    unknown = sum(1 for line in budget.lines if line.actual is None)
    text = _text(html)
    assert f"{unknown} Lines with an unknown actual" in text
    assert "2 lines with a type other than income or expense are in neither target total" in text
    assert "* Target totals marked * are partial" in text
    assert "* The school-year bank net is partial" not in text  # full bank coverage
    assert f"Adopted lines for FY{budget.fiscal_year}" in text and budget.fiscal_year == 2031
    assert f"Category crosswalk version {budget.crosswalk_version}." in text
    assert budget.crosswalk_version == 3
    assert budget.other_year_rows == 1
    assert "1 adopted row of other fiscal years is outside this period." in text
    yearbook = next(row for row in rows if row[1].text == "Yearbook")
    assert yearbook[0].text == "Not recorded"
    assert [n for n, _ in budget.unbudgeted] == [HOSTILE]


def test_fundraising_summary_follows_the_facts_and_marks_incomplete_processors(
    rendered: RenderedSet,
) -> None:
    items = rendered.facts.fundraising
    tables = rendered.tables("fundraising-summary.html")
    rows = _body(tables["processors"])
    assert len(rows) == len(items) + 1
    reasons = {
        "coverage_partial": "Coverage partial",
        "processor_gross_unsettled": "Processor gross unsettled",
        "processor_view_inconsistent": "Processor view inconsistent",
        "rows_excluded": "Rows excluded",
    }
    for row, item in zip(rows[:-1], items, strict=True):
        moved = item.payment_count + item.fee_rows + item.refund_rows + item.excluded_rows
        unknown = "coverage_partial" in item.incomplete_reasons and moved == 0
        amounts = [item.gross, item.fees, item.refunds, item.net]
        assert [c.text for c in row] == [
            item.source_alias,
            *(["Unknown"] * 4 if unknown else [format_money(a) for a in amounts]),
            str(item.payment_count),
            str(item.fee_rows),
            str(item.refund_rows),
            str(item.excluded_rows),
            "Complete"
            if item.complete
            else "Incomplete " + "; ".join(reasons[r] for r in item.incomplete_reasons),
        ]
        marker = "unknown" if unknown else (None if item.complete else "partial")
        for money_cell in row[1:5]:
            assert (marker in money_cell.classes) if marker else not money_cell.classes - {"amt"}
    paypal = next(item for item in items if item.source_alias == "paypal")
    assert not paypal.complete and paypal.payment_count == 0
    wix = next(item for item in items if item.source_alias == "wix")
    assert wix.gross > 0
    total = rows[-1]
    sums = [
        sum((getattr(i, k) for i in items), Decimal("0.00"))
        for k in ("gross", "fees", "refunds", "net")
    ]
    assert [c.text for c in total[:5]] == ["All processors", *map(format_money, sums)]
    assert all("partial" in c.classes for c in total[1:5])  # an incomplete processor is in it
    html = rendered.html("fundraising-summary.html")
    assert (
        f'<div class="n partial">{format_money(sums[0])}</div><div class="k">Processor gross</div>'
        in html
    )
    attribution = _texts(tables["attribution"])
    expected: list[list[str]] = []
    for item in items:
        expected.append([f"{item.source_alias}: category", "Classification", "Sales", "Gross"])
        expected.extend(
            [
                category.category or "Not attributed",
                category.classification.replace("_", " ").capitalize(),
                str(category.count),
                format_money(category.gross),
            ]
            for category in item.categories
        )
        if not item.categories:
            expected.append(["No sales in the period."])
    assert attribution == expected
    assert any(c.category == HOSTILE for item in items for c in item.categories)
    school = rendered.facts.view("school", "adjusted")
    assert f"{format_money(school.income)} Bank-basis income, all categories" in _text(html)


def test_pnl_rows_follow_the_calendar_views_month_by_month(rendered: RenderedSet) -> None:
    facts_ = rendered.facts
    adjusted = facts_.view("calendar", "adjusted")
    source = facts_.view("calendar", "source")
    assert adjusted.complete
    tables = rendered.tables("cfo-pnl-summary.html")
    monthly = tables["monthly"]
    months = [datetime(2030, m, 1).date() for m in range(1, 9)]
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    assert [c.text for c in monthly[0]] == [
        "Category",
        *(f"{n} 2030" for n in names),
        "Year to date",
    ]
    zero = Decimal("0.00")
    cells = {(c.category, c.month): c.net for c in adjusted.cells}
    categories = sorted({c.category for c in adjusted.cells})
    adjusted_months = {m.month: m for m in adjusted.months}
    source_months = {m.month: m for m in source.months}

    def month_value(table: dict[Any, Any], month: Any, attr: str) -> Decimal:
        return getattr(table[month], attr) if month in table else zero

    expected = [
        [category, *(format_money(cells.get((category, m), zero)) for m in months)]
        + [format_money(sum((cells.get((category, m), zero) for m in months), zero))]
        for category in categories
    ]
    for label, attr, ytd in (
        ("Income", "income", adjusted.income),
        ("Expenses", "expense", adjusted.expense),
        ("Net", "net", adjusted.net),
    ):
        expected.append(
            [label, *(format_money(month_value(adjusted_months, m, attr)) for m in months)]
            + [format_money(ytd)]
        )
    expected.append(
        [
            "Source net (CFO view)",
            *(format_money(month_value(source_months, m, "net")) for m in months),
        ]
        + [format_money(source.net)]
    )
    expected.append(
        [
            "Adjustments",
            *(
                format_money(
                    month_value(adjusted_months, m, "net") - month_value(source_months, m, "net")
                )
                for m in months
            ),
        ]
        + [format_money(adjusted.net - source.net)]
    )
    assert _texts(monthly[1:]) == expected
    assert adjusted.net != source.net  # the recorded adjustments move the calendar view
    assert HOSTILE in categories
    assert _texts(_body(tables["walk"])) == [
        [
            label,
            format_money(getattr(source, attr)),
            format_money(getattr(adjusted, attr) - getattr(source, attr)),
            format_money(getattr(adjusted, attr)),
        ]
        for label, attr in (("Income", "income"), ("Expenses", "expense"), ("Net", "net"))
    ]
    walk = rendered.html("cfo-pnl-summary.html").split('id="walk"')[1].split("</table>")[0]
    assert '<tr class="total"><td>Net</td>' in walk and "<tr><td>Income</td>" in walk
    control = facts_.pnl_control_status.capitalize()
    assert f"Published P&L control check: {control}." in _text(
        rendered.html("cfo-pnl-summary.html")
    )


@pytest.mark.parametrize("name", list(BRIDGE_PAGES))
def test_every_bridge_shows_its_rows_records_and_residual(rendered: RenderedSet, name: str) -> None:
    bridge = rendered.facts.bridge(name)
    rows = _texts(rendered.tables(BRIDGE_PAGES[name])[f"bridge-{name}"])
    assert rows[1][1:3] == ["Starting total", format_money(bridge.from_amount)]
    assert rows[-1][1:3] == ["Ending total", format_money(bridge.to_amount)]
    assert rows[-2] == [
        "Unexplained residual",
        "Every difference is explained."
        if bridge.balanced
        else "Not explained by any recorded row; left visible.",
        format_money(bridge.residual),
        "",
    ]
    body = rows[2:-2]
    assert len(body) == len(bridge.rows)
    for rendered_row, row in zip(body, bridge.rows, strict=True):
        assert rendered_row[1:3] == [row.explanation, format_money(row.amount)]
        evidence = [
            *(_ref_text(ref) for ref in row.refs),
            *(f"Adjustment {i}" for i in row.adjustment_ids),
            *(f"Reimbursement item {k}" for k in row.item_keys),
        ]
        if evidence:
            assert rendered_row[3].startswith(_plural(len(evidence), "record"))
            for entry in evidence:
                assert entry in rendered_row[3]
        else:
            assert rendered_row[3] == "None linked"


def test_bridges_appear_in_their_reading_order(rendered: RenderedSet) -> None:
    for page in sorted(set(BRIDGE_PAGES.values())):
        html = rendered.html(page)
        found = re.findall(r'<div class="bridge" id="bridge-([a-z_]+)">', html)
        assert found == [name for name, owner in BRIDGE_PAGES.items() if owner == page], page


@pytest.mark.parametrize("case", ["counts", "every_unknown"])
def test_fundraising_columns_and_an_all_unknown_total(tmp_path: Path, case: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    items = inputs.facts.fundraising
    if case == "counts":  # every count column distinct, so a swapped column shows
        changed = tuple(
            dataclasses.replace(item, fee_rows=3, refund_rows=2, excluded_rows=1)
            if item.source_alias == "wix"
            else item
            for item in items
        )
    else:  # only the processor with no rows and no declared coverage
        changed = tuple(item for item in items if item.source_alias == "paypal")
    inputs.write(facts=dataclasses.replace(inputs.facts, fundraising=changed))
    html = (inputs.run_dir / "fundraising-summary.html").read_text(encoding="utf-8")
    rows = {row[0].text: row for row in _body(_tables(html)["processors"])}
    if case == "counts":
        wix = next(item for item in changed if item.source_alias == "wix")
        assert [c.text for c in rows["wix"][5:9]] == [str(wix.payment_count), "3", "2", "1"]
        return
    assert [c.text for c in rows["paypal"][1:5]] == ["Unknown"] * 4
    total = rows["All processors"]
    assert [c.text for c in total[1:5]] == ["Unknown"] * 4
    assert all("unknown" in c.classes for c in total[1:5])
    assert '<div class="n unknown">Unknown</div><div class="k">Processor gross</div>' in html
    assert "1 processor has no rows and no declared coverage" in _text(html)
    assert "$0.00" not in "".join(c.text for c in total)


def test_an_unexplained_residual_stays_visible(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, adjusted=False)

    def shifted(item: Bridge) -> Bridge:
        if item.name != "school_expense_basis":
            return item
        return dataclasses.replace(item, to_amount=item.to_amount + Decimal("1.00"))

    tampered = dataclasses.replace(
        inputs.facts, bridges=tuple(shifted(item) for item in inputs.facts.bridges)
    )
    inputs.write(facts=tampered)
    rows = _tables((inputs.run_dir / "reimbursement-summary.html").read_text(encoding="utf-8"))[
        "bridge-school_expense_basis"
    ]
    residual = rows[-2]
    assert [c.text for c in residual] == [
        "Unexplained residual",
        "Not explained by any recorded row; left visible.",
        "$1.00",
        "",
    ]
    html = (inputs.run_dir / "reimbursement-summary.html").read_text(encoding="utf-8")
    assert '<tr class="resid off"><td>Unexplained residual</td>' in html


def test_shared_scope_totals_match_in_every_report_that_shows_them(
    rendered: RenderedSet,
) -> None:
    facts_ = rendered.facts
    school = format_money(facts_.view("school", "adjusted").net)
    calendar = format_money(facts_.view("calendar", "adjusted").net)
    outstanding = format_money(facts_.reimbursements.outstanding)
    paid = format_money(facts_.reimbursements.paid("current"))
    index = _texts(_body(rendered.tables(INDEX_HTML)["shared"]))
    assert index == [
        [
            f"{SCHOOL_LABEL} adjusted bank net",
            school,
            "Budget Snapshot, Fundraising Summary, CFO P&L Summary",
        ],
        [f"{CALENDAR_LABEL} adjusted bank net", calendar, "CFO P&L Summary"],
        [
            "Approved and not yet paid (all open requests)",
            outstanding,
            "Reimbursement Summary, Reimbursement Queue",
        ],
        [f"Reimbursements paid in {SCHOOL_LABEL}", paid, "Reimbursement Summary"],
    ]
    budget = _text(rendered.html("budget-snapshot.html"))
    fundraising = _text(rendered.html("fundraising-summary.html"))
    pnl = _text(rendered.html("cfo-pnl-summary.html"))
    reimbursement = _text(rendered.html("reimbursement-summary.html"))
    assert f"{school} {SCHOOL_LABEL} adjusted bank net" in budget
    assert f"{school} {SCHOOL_LABEL} adjusted bank net" in fundraising
    assert f"{CALENDAR_LABEL} adjusted bank net: {calendar}" in pnl
    assert f"School adjusted net Ending total {school}" in pnl  # calendar-to-school bridge
    assert f"Approved and not yet paid (all open requests) {outstanding}" in reimbursement
    assert f"Reimbursements paid in the period {paid}" in reimbursement
    queue = reimbursement_report.load_bundle(rendered.inputs.staged)
    assert queue.summary.outstanding == facts_.reimbursements.outstanding


def test_hostile_labels_are_escaped_at_every_site(rendered: RenderedSet) -> None:
    for name in HTML_FILES:
        assert RAW_MARKER not in rendered.html(name), name
    sites = {
        "organization": HTML_FILES,
        "freshness label": [INDEX_HTML, *SUMMARY_HTML],
        "bank category": ["cfo-pnl-summary.html", "budget-snapshot.html"],
        "budget category": ["budget-snapshot.html"],
        "unbudgeted category": ["budget-snapshot.html"],
        "payment reference": ["reimbursement-summary.html"],
        "attribution category": ["fundraising-summary.html"],
        "ticket reference": ["reimbursement-summary.html", QUEUE_HTML],
    }
    for site, names in sites.items():
        for name in names:
            assert ESCAPED in rendered.html(name), (site, name)
    for name in [INDEX_HTML, *SUMMARY_HTML]:
        html = rendered.html(name)
        assert f'alt="{ESCAPED} logo"' in html  # attribute context
        assert f"{ESCAPED} · Private Main Report Set" in html
    reimbursement = rendered.html("reimbursement-summary.html")
    assert f"Reimbursement item new-03:{ESCAPED}" in reimbursement  # bridge evidence
    assert f"P-001 {ESCAPED}" in reimbursement
    joins = rendered.tables("reimbursement-summary.html")["joins"]
    by_ref = {row[0].text: row for row in joins}
    assert by_ref[f"NEW-01 {HOSTILE}"][1].text == "Matched"  # hostile joined ticket ref
    assert by_ref["P-002"][3].text == f"Ref {HOSTILE}"  # hostile payment reference
    assert (
        f"<td>Ref {ESCAPED}</td>" in reimbursement and f"<td>NEW-01 {ESCAPED}</td>" in reimbursement
    )
    outside = rendered.tables("budget-snapshot.html")["outside"]
    assert ["Mapped, no adopted line", HOSTILE] == [c.text for c in outside[1][:2]]
    assert f"<td>Mapped, no adopted line</td><td>{ESCAPED}</td>" in rendered.html(
        "budget-snapshot.html"
    )


def test_queue_reuses_the_existing_renderer_with_receipts_and_copy_text(
    rendered: RenderedSet, tmp_path: Path
) -> None:
    run_dir = rendered.inputs.run_dir
    reimbursement_report.build_report(rendered.inputs.staged, tmp_path / QUEUE_HTML)
    assert (run_dir / QUEUE_HTML).read_bytes() == (tmp_path / QUEUE_HTML).read_bytes()
    assert (run_dir / COPY_TEXT).read_bytes() == (tmp_path / COPY_TEXT).read_bytes()
    queue = rendered.html(QUEUE_HTML)
    assert "data:image/png;base64," in queue and "View source receipt" in queue
    hrefs = set(re.findall(r'href="([^"]+)"', rendered.html(INDEX_HTML)))
    assert set(ALL_FILES) - {INDEX_HTML} <= hrefs
    assert all((run_dir / href).is_file() for href in hrefs)


# --------------------------------------------------------------------------------------
# Coverage gaps
# --------------------------------------------------------------------------------------


def test_partial_bank_coverage_shows_uncovered_months_and_unknown_actuals(
    tmp_path: Path,
) -> None:
    inputs = _inputs(
        tmp_path,
        adjusted=False,
        bank_coverage='start = "2030-03-01", end = "2030-07-31"',
        pnl=PNL_VALUES,
    )
    inputs.write()
    pnl = (inputs.run_dir / "cfo-pnl-summary.html").read_text(encoding="utf-8")
    rows = {row[0].text: row for row in _tables(pnl)["monthly"]}
    net = [(sorted(c.classes - {"amt"}), c.text) for c in rows["Net"][1:]]
    assert net[0] == (["partial"], format_money(Decimal("100.00")))  # January: seen, uncovered
    assert net[1] == (["uncovered"], "Not covered")  # February: nothing seen, uncovered
    assert net[2] == (["zero"], "$0.00")  # March: covered, observed zero
    assert net[7] == (["partial"], format_money(Decimal("-5.00")))  # August: after coverage
    assert "partial" in rows["Net"][-1].classes  # year to date
    assert "Bank coverage is partial for this calendar year (3 months" in _text(pnl)
    fundraising = (inputs.run_dir / "fundraising-summary.html").read_text(encoding="utf-8")
    attribution = [
        row for row in _tables(fundraising)["attribution"] if row[0].text != "wix: category"
    ]
    wix = next(item for item in inputs.facts.fundraising if item.source_alias == "wix")
    assert wix.categories and all(c.category is None for c in wix.categories)
    unattributed = [row[0] for row in attribution if row[0].text == "Not attributed"]
    assert len(unattributed) == len(wix.categories)
    assert all("unknown" in cell.classes for cell in unattributed)
    school = inputs.facts.view("school", "adjusted")
    calendar = inputs.facts.view("calendar", "adjusted")
    assert not school.complete and not calendar.complete
    assert (
        f'<div class="n partial">{format_money(school.net)}</div><div class="k">{SCHOOL_LABEL}'
        in fundraising
    )
    assert (
        f'<div class="n partial">{format_money(school.income)}</div>'
        '<div class="k">Bank-basis income' in fundraising
    )
    assert f'<b class="partial">{format_money(calendar.net)}</b>' in pnl
    control = inputs.facts.pnl_control_status
    assert control != "mismatched"
    assert f"Published P&L control check: {control.capitalize()}." in _text(pnl)
    index = (inputs.run_dir / INDEX_HTML).read_text(encoding="utf-8")
    shared = {row[0].text: row[1] for row in _body(_tables(index)["shared"])}
    assert "partial" in shared[f"{SCHOOL_LABEL} adjusted bank net"].classes
    assert "partial" in shared[f"{CALENDAR_LABEL} adjusted bank net"].classes
    assert "partial" not in shared["Approved and not yet paid (all open requests)"].classes
    assert "* Partial: bank coverage is incomplete" in _text(index)
    budget = (inputs.run_dir / "budget-snapshot.html").read_text(encoding="utf-8")
    assert (
        f'<div class="n partial">{format_money(school.net)}</div><div class="k">{SCHOOL_LABEL}'
        in budget
    )
    assert "* The school-year bank net is partial" in _text(budget)
    classroom = next(
        row for row in _body(_tables(budget)["lines"]) if row[1].text == "Classroom Supplies"
    )
    assert [c.text for c in classroom[3:7]] == [
        "Unknown",
        "Unknown",
        "Unknown",
        "Unknown: bank coverage is partial for the period",
    ]


# --------------------------------------------------------------------------------------
# Fail-closed inputs
# --------------------------------------------------------------------------------------


def _expect(code: str, inputs: RunInputs, **kwargs: Any) -> RenderError:
    with pytest.raises(RenderError) as caught:
        write(
            kwargs.pop("facts", inputs.facts),
            kwargs.pop("staged", inputs.staged),
            kwargs.pop("run_dir", inputs.run_dir),
            context=kwargs.pop("context", inputs.context),
            exporter=fake_exporter,
        )
    assert caught.value.code == code
    _assert_clean_error(caught.value)
    return caught.value


def test_missing_run_directory_is_refused(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    _expect("run_dir_invalid", inputs, run_dir=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("case", ["run_id", "hash", "duplicate", "naive"])
def test_invalid_run_context_is_refused(tmp_path: Path, case: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    context = inputs.context
    if case == "run_id":
        context = dataclasses.replace(context, run_id="run-latest")
    elif case == "hash":
        context = dataclasses.replace(context, input_sha256="not-a-hash")
    elif case == "duplicate":
        context = dataclasses.replace(context, sources=(*context.sources, context.sources[0]))
    else:
        naive = dataclasses.replace(context.sources[0], captured_at=datetime(2030, 8, 15))
        context = dataclasses.replace(context, sources=(naive, *context.sources[1:]))
    _expect("context_invalid", inputs, context=context)
    assert list(inputs.run_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("case", "counts"),
    [("missing_source", "2 coverage source(s) and 0"), ("other_snapshot", "0 coverage source(s)")],
)
def test_context_from_another_input_set_is_refused(tmp_path: Path, case: str, counts: str) -> None:
    inputs = _inputs(tmp_path)
    context = inputs.context
    if case == "missing_source":  # a coverage source with no bridge evidence
        sources = tuple(s for s in context.sources if s.label != "wix")
    else:  # bridge evidence from a bank snapshot this run did not capture
        sources = tuple(
            dataclasses.replace(s, sha256="0" * 64) if s.label == "bank-checking" else s
            for s in context.sources
        )
    error = _expect(
        "context_mismatch", inputs, context=dataclasses.replace(context, sources=sources)
    )
    assert counts in str(error)
    assert list(inputs.run_dir.iterdir()) == []


def test_bundle_other_than_the_facts_bundle_is_refused(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    payload = json.loads(inputs.staged.read_text(encoding="utf-8"))
    payload["report"]["as_of_date"] = "2030-08-14"
    other = tmp_path / "other" / "reimbursement-report.json"
    other.parent.mkdir()
    other.write_text(json.dumps(payload), encoding="utf-8")
    _expect("bundle_mismatch", inputs, staged=other)
    assert list(inputs.run_dir.iterdir()) == []


@pytest.mark.parametrize("case", ["window", "items", "queue", "outstanding"])
def test_facts_from_another_bundle_are_refused(tmp_path: Path, case: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    data = inputs.facts.reimbursements
    if case == "window":
        data = dataclasses.replace(data, cutoff_date=datetime(2030, 5, 1).date())
    elif case == "items":
        data = dataclasses.replace(data, items=data.items[1:])
    elif case == "queue":
        data = dataclasses.replace(data, queue=tuple(reversed(data.queue)))
    else:
        data = dataclasses.replace(data, outstanding=data.outstanding + Decimal("0.01"))
    tampered = dataclasses.replace(inputs.facts, reimbursements=data)
    error = _expect("bundle_mismatch", inputs, facts=tampered)
    assert "in 1 check(s)" in str(error)
    assert list(inputs.run_dir.iterdir()) == []


def test_unreadable_bundle_is_refused_with_fixed_text(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"schema_version": 2, "unexpected-private-key": 1}), "utf-8")
    error = _expect("bundle_invalid", inputs, staged=broken)
    assert str(error) == "bundle_invalid: the staged reimbursement bundle is invalid"
    assert list(inputs.run_dir.iterdir()) == []


def test_stale_receipt_sidecar_stops_before_anything_is_written(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    sidecar = inputs.staged.with_suffix(".receipts.json")
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    raw["items"][0]["item_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(raw), encoding="utf-8")
    error = _expect("queue_invalid", inputs)
    assert str(error) == (
        "queue_invalid: the reimbursement queue or its receipt sidecar is invalid"
    )
    assert list(inputs.run_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("bridge", "end"),
    [
        ("school_budget_crosswalk", "from_amount"),
        ("calendar_to_school", "to_amount"),
        ("calendar_to_school", "from_amount"),
        ("calendar_adjustments", "to_amount"),
        ("school_payment_timing", "to_amount"),
        ("open_totals", ""),
    ],
)
def test_disagreeing_shared_totals_are_refused(tmp_path: Path, bridge: str, end: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    if bridge == "open_totals":  # open approved amounts no longer add up to the outstanding
        data = inputs.facts.reimbursements
        totals = tuple(
            t for t in data.totals if not (t.open and t.payment_bucket == "unpaid" and t.amount)
        )
        assert totals != data.totals
        tampered = dataclasses.replace(
            inputs.facts, reimbursements=dataclasses.replace(data, totals=totals)
        )
    else:

        def shifted(item: Bridge) -> Bridge:
            if item.name != bridge:
                return item
            return dataclasses.replace(item, **{end: getattr(item, end) + Decimal("0.01")})

        tampered = dataclasses.replace(
            inputs.facts, bridges=tuple(shifted(item) for item in inputs.facts.bridges)
        )
    error = _expect("totals_mismatch", inputs, facts=tampered)
    assert "1 shared-scope total(s)" in str(error)
    assert list(inputs.run_dir.iterdir()) == []


# --------------------------------------------------------------------------------------
# A failed export never leaves a half-written or changed run directory
# --------------------------------------------------------------------------------------


def _failing_after_partial_output(jobs: Sequence[ExportJob]) -> None:
    jobs[0].pdf.write_bytes(FAKE_PDF + b"half-written")
    raise ExportError("export_failed", "a summary could not be printed or captured")


def _writes_nothing(jobs: Sequence[ExportJob]) -> None:
    return None


def _writes_garbage(jobs: Sequence[ExportJob]) -> None:
    for job in jobs:
        job.pdf.write_bytes(b"not a pdf")
        job.png.write_bytes(RECEIPT_PNG)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("stand_in", "export_failed"),
        ("missing_browser", "export_unavailable"),
        ("no_files", "export_output_invalid"),
        ("garbage", "export_output_invalid"),
    ],
)
def test_failed_export_leaves_the_fresh_run_directory_empty(
    tmp_path: Path, failure: str, code: str
) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    with pytest.raises(ExportError) as caught:
        if failure == "missing_browser":
            inputs.write(exporter=None, chromium_path=tmp_path / "no-such-chromium.exe")
        else:
            exporter = {
                "stand_in": _failing_after_partial_output,
                "no_files": _writes_nothing,
                "garbage": _writes_garbage,
            }[failure]
            inputs.write(exporter=exporter)
    assert caught.value.code == code
    _assert_clean_error(caught.value)
    assert list(inputs.run_dir.iterdir()) == []  # nothing published, no staging left
    inputs.write()  # the same directory then takes the complete set
    assert sorted(p.name for p in inputs.run_dir.iterdir()) == ALL_FILES


@pytest.mark.parametrize("leftover", ["output", "staging"])
def test_a_written_run_directory_is_never_written_again(tmp_path: Path, leftover: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    if leftover == "output":
        inputs.write()
    else:
        (inputs.run_dir / f"{STAGING_PREFIX}abandoned").mkdir()
    previous = _files(inputs.run_dir)
    other = dataclasses.replace(inputs.context, run_id=OTHER_RUN_ID)
    with pytest.raises(RenderError) as caught:
        inputs.write(context=other)
    assert caught.value.code == "run_dir_not_empty"
    _assert_clean_error(caught.value)
    expected = "15 output file(s) and 0" if leftover == "output" else "0 output file(s) and 1"
    assert expected in str(caught.value)
    assert _files(inputs.run_dir) == previous  # byte-identical
    assert sorted(p.name for p in inputs.run_dir.iterdir()) == sorted(
        ALL_FILES if leftover == "output" else [f"{STAGING_PREFIX}abandoned"]
    )


def test_the_index_is_moved_into_place_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    order: list[str] = []
    publish = render._publish

    def recording(source: Path, target: Path) -> None:
        assert not (inputs.run_dir / INDEX_HTML).exists()  # nothing links a missing file
        order.append(target.name)
        publish(source, target)

    monkeypatch.setattr(render, "_publish", recording)
    inputs.write()
    assert order == list(OUTPUT_NAMES) and order[-1] == INDEX_HTML
    assert sorted(order) == ALL_FILES


@pytest.mark.parametrize("withdraw_fails", [False, True])
def test_a_failed_move_withdraws_what_was_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, withdraw_fails: bool
) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    publish = render._publish
    moved: list[str] = []

    def locked_third(source: Path, target: Path) -> None:
        if len(moved) == 2:
            raise PermissionError("the target is held open")  # a Windows sharing violation
        publish(source, target)
        moved.append(target.name)

    def stuck(path: Path) -> None:
        raise PermissionError("the file is held open")

    monkeypatch.setattr(render, "_publish", locked_third)
    if withdraw_fails:
        monkeypatch.setattr(render, "_withdraw", stuck)
    with pytest.raises(RenderError) as caught:
        inputs.write()
    _assert_clean_error(caught.value)
    remaining = sorted(p.name for p in inputs.run_dir.iterdir())
    if withdraw_fails:
        assert caught.value.code == "output_incomplete"
        assert "2 file(s) of an incomplete set" in str(caught.value)
        assert remaining == sorted(moved) and INDEX_HTML not in remaining
    else:
        assert caught.value.code == "output_failed"
        assert remaining == []


def test_a_queue_write_failure_is_typed_and_cleaned_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, adjusted=False)

    def full_disk(path: Path, html_text: str) -> None:
        raise OSError("no space left on the device")

    monkeypatch.setattr(reimbursement_report, "write_html_atomic", full_disk)
    with pytest.raises(RenderError) as caught:
        inputs.write()
    assert caught.value.code == "output_failed"
    assert str(caught.value) == "output_failed: the rendered set could not be written"
    _assert_clean_error(caught.value)
    assert list(inputs.run_dir.iterdir()) == []


@pytest.mark.parametrize("outcome", ["complete", "failed"])
def test_a_staging_folder_that_cannot_be_removed_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    attempts: list[Path] = []

    def locked(path: Path) -> None:
        attempts.append(path)
        raise PermissionError("a scanner holds a file open")

    monkeypatch.setattr(render, "_remove_tree", locked)
    monkeypatch.setattr(render.time, "sleep", lambda seconds: None)
    if outcome == "complete":
        with pytest.raises(RenderError) as caught:
            inputs.write()
        assert caught.value.code == "staging_not_removed"
        message = str(caught.value)
        _assert_clean_error(caught.value)
    else:
        with pytest.raises(ExportError) as export_caught:
            inputs.write(exporter=_failing_after_partial_output)
        message = " ".join(export_caught.value.__notes__)
    assert len(attempts) == 3 and len(set(attempts)) == 1
    staging = attempts[0]
    assert staging.parent == inputs.run_dir and staging.name.startswith(STAGING_PREFIX)
    assert staging.name in message and staging.is_dir()


def test_missing_playwright_is_a_typed_export_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = tmp_path / "page.html"
    html.write_text("<!doctype html><title>x</title><p>Example</p>", encoding="utf-8")
    pdf, png = tmp_path / "page.pdf", tmp_path / "page.png"
    pdf.write_bytes(b"%PDF-old")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(ExportError) as caught:
        export_documents([ExportJob(html=html, pdf=pdf, png=png)])
    assert caught.value.code == "export_unavailable"
    _assert_clean_error(caught.value)
    assert pdf.read_bytes() == b"%PDF-old" and not png.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["page.html", "page.pdf"]


@pytest.mark.parametrize("case", ["missing", "clash", "overwrite_input"])
def test_invalid_export_jobs_are_refused(tmp_path: Path, case: str) -> None:
    html = tmp_path / "page.html"
    html.write_text("<!doctype html><p>Example</p>", encoding="utf-8")
    job = ExportJob(html=html, pdf=tmp_path / "a.pdf", png=tmp_path / "a.png")
    if case == "missing":
        jobs = [dataclasses.replace(job, html=tmp_path / "absent.html")]
    elif case == "clash":
        jobs = [job, dataclasses.replace(job, png=tmp_path / "b.png")]
    else:
        jobs = [dataclasses.replace(job, png=html)]
    with pytest.raises(ExportError) as caught:
        export_documents(jobs)
    assert caught.value.code == "export_input_invalid"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["page.html"]


# --------------------------------------------------------------------------------------
# Headless Chromium: real export, readable layouts and the request guard
# --------------------------------------------------------------------------------------


def _require_chromium() -> Any:
    """Skip exactly as the receipt viewer browser test does when Chromium is not installed."""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chromium")
        except playwright.Error as exc:
            if "Executable doesn't exist at" in str(exc):
                pytest.skip("Playwright Chromium executable is not installed")
            raise
        browser.close()
    return playwright


def _pdf_pages(payload: bytes) -> list[tuple[float, float, str]]:
    """(width, height, text) per page: pypdfium2 when installed, else a structural read."""
    try:
        import pypdfium2
    except ImportError:
        boxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", payload)
        return [(float(w), float(h), "") for w, h in boxes]
    document = pypdfium2.PdfDocument(payload)
    try:
        pages = []
        for index in range(len(document)):
            page = document[index]
            width, height = page.get_size()
            text = page.get_textpage().get_text_range()
            pages.append((float(width), float(height), text))
        return pages
    finally:
        document.close()


def test_chromium_export_produces_readable_pdf_and_png(tmp_path: Path) -> None:
    playwright = _require_chromium()
    inputs = _inputs(tmp_path, adjusted=False)
    artifacts = inputs.write(exporter=None)
    assert list(artifacts.paths) == ALL_FILES
    assert artifacts.export_sandboxed is export.default_sandbox()
    heights: dict[str, int] = {}
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chromium")
        page = browser.new_page(viewport={"width": export.VIEWPORT_WIDTH, "height": 900})
        for name in SUMMARY_NAMES:
            page.goto((inputs.run_dir / f"{name}.html").as_uri())
            heights[name] = page.evaluate("document.documentElement.scrollHeight")
        browser.close()
    for name in SUMMARY_NAMES:
        pages = _pdf_pages((inputs.run_dir / f"{name}.pdf").read_bytes())
        assert pages, name
        width, height, text = pages[0]
        if name == "cfo-pnl-summary":
            assert width > height, "the P&L prints landscape"
        else:
            assert height > width, name
        if text:  # pypdfium2 text extraction
            assert TITLES[f"{name}.html"] in text
        png = (inputs.run_dir / f"{name}.png").read_bytes()
        png_width, png_height = _png_size(png)
        assert png_width == export.VIEWPORT_WIDTH
        # A full-page capture: the whole document, well past the 900-pixel viewport.
        assert heights[name] > 1400, name
        assert png_height >= heights[name] - 2 and png_height > 900 + 400, name
        assert _png_distinct_bytes(png) > 8, "the capture is not blank"


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]
)
def test_chromium_pages_are_readable_offline_at_desktop_and_phone_widths(
    rendered: RenderedSet, viewport: dict[str, int]
) -> None:
    playwright = _require_chromium()
    run_dir = rendered.inputs.run_dir
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chromium")
        page = browser.new_page(viewport=viewport)
        errors: list[str] = []
        requests: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        for name in [*SUMMARY_HTML, INDEX_HTML]:
            page.goto((run_dir / name).as_uri())
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            assert overflow <= 1, name
            smallest = page.evaluate(
                "Math.min(...[...document.querySelectorAll('td, th, p, li')]"
                ".map(el => parseFloat(getComputedStyle(el).fontSize)))"
            )
            assert smallest >= 9.5, name
            assert not page.evaluate("Boolean(window.alerted)")
        page.goto((run_dir / QUEUE_HTML).as_uri())
        page.locator(".receipt-item", has_text="View source receipt").first.click()
        page.wait_for_function("document.getElementById('receipt-image').naturalWidth === 200")
        assert page.locator("#receipt-viewer").is_visible()
        assert page.locator("#receipt-marks ellipse").count() == 1
        assert not errors
        assert all(url.startswith(("file:", "data:")) for url in requests)
        browser.close()


def test_chromium_export_never_runs_page_scripts(tmp_path: Path) -> None:
    _require_chromium()
    html = tmp_path / "page.html"
    html.write_text(
        "<!doctype html><p>Example PTA</p><script>"
        "document.body.insertAdjacentHTML('beforeend','<div style=\"height:6000px\"></div>')"
        "</script>",
        encoding="utf-8",
    )
    pdf, png = tmp_path / "page.pdf", tmp_path / "page.png"
    with pytest.warns(UnsandboxedExportWarning):  # an unsandboxed export is never silent
        sandboxed = export_documents([ExportJob(html=html, pdf=pdf, png=png)], sandbox=False)
    assert sandboxed is False
    assert _png_size(png.read_bytes())[1] < 2000


@pytest.fixture
def loopback() -> Iterator[list[str]]:
    """A loopback HTTP server recording every request it receives."""
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(_png(50, 3000))

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    hits.append(f"http://127.0.0.1:{server.server_address[1]}")
    try:
        yield hits
    finally:
        server.shutdown()
        server.server_close()


def test_chromium_export_aborts_every_request_but_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback: list[str]
) -> None:
    """With network emulation turned off, the route handler alone keeps the page local."""
    _require_chromium()
    monkeypatch.setattr(export, "_OFFLINE", False)
    origin = loopback.pop(0)
    (tmp_path / "tall.png").write_bytes(_png(50, 3000))
    html = tmp_path / "page.html"
    html.write_text(
        "<!doctype html><style>@page{size:letter portrait}body{margin:0}</style>"
        f'<link rel="stylesheet" href="{origin}/style.css">'
        f'<img src="{origin}/remote.png" alt="">'
        '<img src="tall.png" alt=""><p>Example PTA</p>',
        encoding="utf-8",
    )
    pdf, png = tmp_path / "page.pdf", tmp_path / "page.png"
    export_documents([ExportJob(html=html, pdf=pdf, png=png)])
    assert loopback == []  # no request reached the server
    assert _png_size(png.read_bytes())[1] < 1500  # neither 3000-pixel image was loaded
    assert pdf.read_bytes().startswith(b"%PDF-")


def test_chromium_unreadable_export_output_is_refused_and_earlier_files_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_chromium()
    html = tmp_path / "page.html"
    html.write_text("<!doctype html><p>Example PTA</p>", encoding="utf-8")
    pdf, png = tmp_path / "page.pdf", tmp_path / "page.png"
    pdf.write_bytes(b"%PDF-old")
    png.write_bytes(b"old png")

    def garbage(browser: Any, job: ExportJob, pdf_temp: Path, png_temp: Path) -> None:
        pdf_temp.write_bytes(b"%PDF-new")
        png_temp.write_bytes(b"not a png")

    monkeypatch.setattr(export, "_render", garbage)
    with pytest.raises(ExportError) as caught:
        export_documents([ExportJob(html=html, pdf=pdf, png=png)])
    assert caught.value.code == "export_output_invalid"
    assert pdf.read_bytes() == b"%PDF-old" and png.read_bytes() == b"old png"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["page.html", "page.pdf", "page.png"]


# --------------------------------------------------------------------------------------
# Helpers and identifiers
# --------------------------------------------------------------------------------------


def test_money_formatting_marks_unknown_and_keeps_exact_cents() -> None:
    assert format_money(None) == "Unknown"
    assert format_money(Decimal("0.00")) == "$0.00"
    assert format_money(Decimal("-1234.5")) == "-$1,234.50"
    assert format_money(Decimal("1234567.89")) == "$1,234,567.89"
    with pytest.raises(ValueError):
        format_money(Decimal("0.001"))


def test_run_ids_have_the_contract_shape() -> None:
    run_id = make_run_id(datetime(2030, 8, 15, 13, 5, 6, 789, tzinfo=UTC))
    assert run_id.startswith("run-20300815T130506000789Z-") and is_valid_run_id(run_id)
    assert make_run_id(datetime(2030, 8, 15, tzinfo=UTC)) != make_run_id(
        datetime(2030, 8, 15, tzinfo=UTC)
    )
    assert not is_valid_run_id("run-20300815T130506Z-" + "0" * 32)
    with pytest.raises(ValueError):
        make_run_id(datetime(2030, 8, 15))


def test_vocabulary_is_read_from_its_owners() -> None:
    assert render._APPROVED is facts.APPROVED_STATUS
    assert facts.APPROVED_STATUS in STATUS_META
    assert export.PNG_SIGNATURE is reimbursement_report.PNG_SIGNATURE
    assert reimbursement_report._PNG_SIGNATURE is reimbursement_report.PNG_SIGNATURE
    assert OUTPUT_NAMES[-1] == INDEX_HTML and sorted(OUTPUT_NAMES) == ALL_FILES
    assert set(render.BRIDGE_TITLES) == set(facts.BRIDGE_NAMES)
