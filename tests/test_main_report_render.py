"""Tests for np_finance.main_reports.render and export — the six-report Main Report Set.

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
import math
import re
import shutil
import struct
import sys
import threading
import types
import urllib.parse
import warnings
import zlib
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from markupsafe import escape

from np_finance import receipt_viewer, reimbursement_report
from np_finance.main_reports import export, facts, planning, render, runner
from np_finance.main_reports.export import (
    ExportError,
    ExportJob,
    UnsandboxedExportWarning,
    export_documents,
)
from np_finance.main_reports.facts import build_from
from np_finance.main_reports.models import (
    ARTIFACT_MEDIA_TYPES,
    EXPENSE_BUCKETS,
    TRANSACTION_KINDS,
    ArtifactSet,
    Bridge,
    CaptureSet,
    ReportFacts,
    SourceRef,
    is_valid_run_id,
    make_run_id,
)
from np_finance.main_reports.render import (
    INDEX_HTML,
    OUTPUT_NAMES,
    QUEUE_HTML,
    STAGING_PREFIX,
    SUMMARY_NAMES,
    RenderContext,
    RenderError,
    SourceFreshness,
    format_money,
    format_whole,
    write,
)
from np_finance.reimbursement_report import STATUS_META
from tests.conftest import (
    BANK_ROWS,
    BUDGET_ROWS,
    CLASSROOM_CATEGORY,
    CLASSROOM_LEDGER_ROWS,
    CLASSROOM_LEDGER_TAB,
    CLASSROOM_NO_REFERENCE,
    CLASSROOM_ROUNDING_FIGURES,
    CLASSROOM_SIGN_FIGURES,
    CROSSWALK_TOML,
    PNL_VALUES,
    Scenario,
    _adjusted_scenario,
    _bank,
    _budget_row,
    _bundle_payload,
    _item,
    _record_payment,
    _ticket,
    _wix,
    classroom_bundle,
    classroom_figures,
    classroom_planning_document,
    generated_classroom_figures,
    require_chromium,
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
CLASSROOM = "classroom-budgets"
CLASSROOM_HTML = f"{CLASSROOM}.html"
TITLES = {
    "reimbursement-summary.html": "Reimbursement Summary",
    "budget-snapshot.html": "Budget Snapshot",
    "fundraising-summary.html": "Fundraising Summary",
    "cfo-pnl-summary.html": "CFO P&L Summary",
    "classroom-budgets.html": "Classroom Budgets",
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


# A large fictional world that maxes every cap: ~60 P&L categories (one a 200-character
# label of W, one hostile), 40 extra open requests, 80 budget lines, 30 processor
# categories, many discrepancies (none of the new categories is in the CFO P&L tab) and
# long bridge evidence (eight months of bank rows per category).
LONG_LABEL = "W" * 200


def _long_name(prefix: str, length: int = 120) -> str:
    return (prefix + " " + "Wide example words " * 10)[:length]


# A 180-character organization name (a real non-profit name easily passes 60 characters).
LONG_ORGANIZATION = _long_name(
    "Example Parent Teacher Association of the Fictional Elementary School", 180
)


def _large_world(*, covered: bool = True, adversarial: bool = False) -> dict[str, Any]:
    """The large world; ``adversarial`` adds 120-character names, long and blank line types,
    a 180-character organization, seven-digit amounts and the hostile bundle."""
    bank = list(BANK_ROWS)
    names = [f"Example category {index:02d}" for index in range(52)]
    names += [LONG_LABEL, f"{HOSTILE} expense", "W" * 60, f"Example income {LONG_LABEL}"]
    if adversarial:
        names[:10] = [_long_name(f"Example category {index:02d}") for index in range(10)]
        bank.append(_bank("7/15/2030", "Example large gift", "9876543.21", names[0]))
        bank.append(_bank("7/16/2030", "Example large bill", "-8765432.10", names[1]))
    for index, name in enumerate(names):
        for month in range(1, 9):
            income = index % 6 == 0 or name.startswith("Example income")
            amount = Decimal(index * 37 % 900 + month * 13 + 50) + Decimal("0.45")
            if income:
                amount *= 3
            day = f"{month}/{3 + index % 20}/2030"
            signed = amount if income else -amount
            bank.append(_bank(day, f"Example vendor {index}-{month}", f"{signed:.2f}", name))
    budget = [*BUDGET_ROWS]
    for index in range(80):
        kind = "income" if index % 4 == 0 else "expense"
        budget.append(
            _budget_row("2031", kind, "proposed", f"{(index * 53) % 4000 + 100}", names[index % 52])
        )
    budget.append(_budget_row("2031", "expense", "proposed", "75", LONG_LABEL))
    if adversarial:  # the largest targets: shown rows with long and blank types and names
        for kind, amount in (
            ("sponsorship", "999999"),
            ("", "999998"),
            ("recurring_income", "999997"),
        ):
            budget.append(_budget_row("2031", kind, "proposed", amount, _long_name("Example line")))
        for index in range(8):
            budget.append(
                _budget_row(
                    "2031",
                    "income",
                    "proposed",
                    f"{900000 + index}",
                    _long_name(f"Example income line {index}"),
                )
            )
    wix = []
    mapping = []
    for index in range(30):
        product = f"Example product {index:02d}"
        mapping.append([product, f"Example fund {index:02d}"])
        for copy in range(2):
            wix.append(
                _wix(
                    f"pi_ex_{index:03d}_{copy}",
                    date(2030, 7, 2 + index % 25),
                    f"{20 + index}.00",
                    "Successful",
                    fee="-1.00",
                    net=f"{19 + index}.00",
                    product=product,
                )
            )
    payload = _hostile_bundle() if adversarial else _bundle_payload()
    if adversarial:
        payload["report"]["organization"] = LONG_ORGANIZATION
    for index in range(40):
        ref = f"P-{100 + index}" if index else LONG_LABEL[:60]
        ticket = _ticket(
            100 + index,
            ref,
            "legacy",
            f"2030-0{1 + index % 7}-1{index % 9}",
            [
                _item(
                    f"p-{100 + index}:line:1",
                    1,
                    f"2030-0{1 + index % 7}-0{1 + index % 8}",
                    f"{10 + index * 7}.25",
                    "A",
                    "Field Trips",
                )
            ],
            status="A",
            decision="APPROVED",
        )
        ticket["source_evidence_sha256"] = hashlib.sha256(ref.encode()).hexdigest()
        payload["tickets"].append(ticket)
    world: dict[str, Any] = {
        "bank": bank,
        "budget": budget,
        "wix": wix,
        "mapping": mapping,
        "bundle": payload,
    }
    if not covered:
        world["bank_coverage"] = None
    return world


def _large_inputs(tmp_path: Path, *, covered: bool = True, adversarial: bool = False) -> RunInputs:
    return _inputs(
        tmp_path, adjusted=False, **_large_world(covered=covered, adversarial=adversarial)
    )


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
            state = values.get("data-state")
            span = values.get("colspan")
            classes = (
                (values.get("class") or "")
                + (f" state:{state}" if state else "")
                + (f" colspan:{span}" if span else "")
            )
            self.cell = ([], classes)
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


BASES = {
    "reimbursement": "items by their own expense date; payments by payment date",
    "budget": "adopted targets beside the adjusted bank view",
    "fundraising": "processor activity by payment date; the bank view is shown separately",
    "pnl": "adjusted bank view by bank date; internal transfers excluded",
}
MEASURE = {
    "observed": "Yes · bank, crosswalked",
    "coverage_partial": "In part · bank coverage incomplete",
    "crosswalk_missing": "Not yet · no category crosswalk",
    "category_unmapped": "Not yet · no source category maps here",
    "ambiguous": "Not yet · more than one adopted line",
}
LEGEND = "– Unknown: no declared coverage or no readable amount, never zero."
_TILE = re.compile(
    r'<div class="metric( [a-z]+)?"><strong(?: class="([^"]*)")?>([^<]*)</strong>'
    r"<span>([^<]*)</span>(?:<small>([^<]*)</small>)?</div>"
)
_ROUTE = re.compile(
    r'<div class="route"><span><span[^>]*>([^<]*)</span></span><span class="track">'
    r'(?:<span class="bar" style="width:([\d.]+)%"></span>)?</span>'
    r'<span class="val[^"]*">([^<]*)</span></div>'
)


def _tiles(html: str) -> list[tuple[str, str, str, str, str]]:
    """(state, strong classes, value, label, note) of every KPI tile."""
    return [
        (state.strip(), classes, unescape(value), unescape(label), unescape(note))
        for state, classes, value, label, note in _TILE.findall(html)
    ]


def _routes(html: str) -> list[tuple[str, str, str]]:
    """(label, bar width, value) of every bar row."""
    return [(unescape(a), b, unescape(c)) for a, b, c in _ROUTE.findall(html)]


def _audit_text(html: str) -> str:
    return _text("<body>" + html.split('<p class="audit">')[1].split("</p>")[0])


def _pnl_picked(ranked: Sequence[tuple[str, Decimal]]) -> set[str]:
    """The P&L page-1 rows: the largest income and expense categories, then the largest
    remaining ones, four in all."""
    picked = {
        *[n for n, a in ranked if a > 0][:1],
        *[n for n, a in ranked if a < 0][:1],
    }
    for name, _ in ranked:
        if len(picked) >= 4:
            break
        picked.add(name)
    return picked


def _whole_or_dash(value: Decimal | None) -> str:
    return "–" if value is None else format_whole(value)


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
        "reimbursement-summary.html": (SCHOOL_LABEL, SCHOOL_RANGE, BASES["reimbursement"]),
        "budget-snapshot.html": (SCHOOL_LABEL, SCHOOL_RANGE, BASES["budget"]),
        "fundraising-summary.html": (SCHOOL_LABEL, SCHOOL_RANGE, BASES["fundraising"]),
        "cfo-pnl-summary.html": (CALENDAR_LABEL, CALENDAR_RANGE, BASES["pnl"]),
    }
    facts_ = rendered.facts
    captured = render.captured_label(s.captured_at for s in rendered.inputs.context.sources)
    for name, (label, period_range, basis) in expected.items():
        html = rendered.html(name)
        text = _text(html)
        title = str(escape(f"{TITLES[name]} · {label}"))
        assert f"<title>{title}</title>" in html
        assert f'<meta http-equiv="Content-Security-Policy" content="{CSP}">' in html
        scope = _text("<body>" + html.split('<p class="scope">')[1].split("</p>")[0])
        assert scope.startswith(f"{label} · {period_range} · through August 15, 2030")
        assert basis in scope
        assert "As of August 15, 2030" in text
        assert f'<meta name="pta-run-id" content="{RUN_ID}">' in html
        # The run ID appears once, in the footer, beside the input set and capture times.
        assert text.count(RUN_ID) == 1
        footer = _text("<body>" + html.split('<footer class="foot">')[1])
        assert RUN_ID in footer and rendered.inputs.capture_set.aggregate_sha256[:16] in footer
        assert f"Inputs captured {captured}" in footer
        assert ("1 page + appendix" if name == "cfo-pnl-summary.html" else "1 page") in footer
        assert "Private financial report." in footer
        # The metadata cards, basis box, freshness table and findings section are gone.
        assert "Basis." not in text and "Source freshness" not in text
        assert "Findings, adjustments and discrepancies" not in text
        audit = _audit_text(html)
        assert f"Adjustments applied {len(facts_.applied_adjustments)}" in audit
        assert f"Unresolved discrepancies {len(facts_.discrepancy_ids)}" in audit
        assert f"Findings {sum(issue.count for issue in facts_.issues)}" in audit
        assert f'href="{INDEX_HTML}"' in html and f'href="{QUEUE_HTML}"' in html
    # The legacy FY label names the school year only, never the calendar-year P&L.
    assert "· FY2031 ·" in _text(rendered.html("budget-snapshot.html"))
    pnl = _text(rendered.html("cfo-pnl-summary.html"))
    assert "FY20" not in pnl
    assert "(FY" not in _text(rendered.html(INDEX_HTML))
    applied = len(facts_.applied_adjustments)
    assert applied and f"· {applied} adjustments applied" in pnl
    assert "Budgets are school-year targets; see the Budget Snapshot." in pnl
    assert "No calendar-year budget is derived" in _text(rendered.html("budget-snapshot.html"))
    reimbursement = _text(rendered.html("reimbursement-summary.html"))
    assert "and the reimbursement queue as of August 15, 2030" in reimbursement
    carry = sum(1 for e in facts_.reimbursements.queue if e.carryover)
    assert carry == 1 and "· includes 1 prior-year carryover" in reimbursement


def test_index_inputs_table_lists_every_feed_with_capture_time_and_coverage(
    rendered: RenderedSet,
) -> None:
    rows = _texts(_body(rendered.tables(INDEX_HTML)["inputs"]))
    capture_set = rendered.inputs.capture_set
    feeds = [c for c in capture_set.captures if c.kind in TRANSACTION_KINDS]
    assert [row[0] for row in rows] == [c.alias for c in feeds]
    by_label = {row[0]: row for row in rows}
    bank = capture_set.by_alias["bank-checking"]
    assert by_label["bank-checking"][1:] == [
        "Bank",
        f"{bank.captured_at:%Y-%m-%d %H:%M} UTC",
        "Complete for the period",
        "Complete for the period",
    ]
    assert by_label["paypal"][3].startswith("Partial: no declared coverage 2030-07-01 to")
    others = [
        *(c.alias for c in capture_set.captures if c.kind not in TRANSACTION_KINDS),
        capture_set.assumptions.alias,
        capture_set.adopted_budget.tab_title,
        HOSTILE,
    ]
    text = _text(rendered.html(INDEX_HTML))
    assert f"Also captured: {', '.join(others)} (not transaction feeds)." in text
    for name in SUMMARY_HTML:  # summaries carry no freshness table
        assert "inputs" not in rendered.tables(name) and bank.sha256[:12] not in rendered.html(name)


def test_reimbursement_summary_follows_the_facts(rendered: RenderedSet) -> None:
    facts_ = rendered.facts
    data = facts_.reimbursements
    period = facts_.periods.school
    html = rendered.html("reimbursement-summary.html")
    text = _text(html)
    tracked = len({i.review_key for i in data.items} | {e.review_key for e in data.queue})
    still_open = len(data.queue)
    closed = tracked - still_open
    clarification = sum((data.open_amount(b, "C") for b in EXPENSE_BUCKETS), Decimal("0.00"))
    unpriced = sum(t.unpriced for t in data.totals if t.open and t.status == "C")
    assert _tiles(html) == [
        ("", "", str(tracked), "Requests tracked", ""),
        ("closed", "", str(closed), "Closed", ""),
        ("open", "", str(still_open), "Still open", ""),
        (
            "amount",
            "",
            format_whole(clarification),
            "Needs clarification",
            f"{render.plural(unpriced, 'item', 'items')} without an amount" if unpriced else "",
        ),
    ]
    assert (tracked, closed, still_open) == (6, 2, 4) and clarification > 0
    assert "33% of requests are closed" in text  # half-up percent of the first part
    assert "Closed · 2 (33%)" in text and "Open · 4 (67%)" in text
    joins = [j for j in data.joins if period.position(j.payment_date) == "current"]
    matched = sum(1 for j in joins if j.state == "matched")
    paid_requests = len({i.review_key for i in data.items if i.payment_bucket == "current"})
    assert (
        f"Paid in the period {format_whole(data.paid('current'))} across "
        f"{render.plural(paid_requests, 'request', 'requests')}"
    ) in text
    assert f"{matched} matched to a bank row · {len(joins) - matched} not yet matched" in text
    assert f"{format_whole(data.paid('current', 'prior'))} paid for prior-year expenses" in text
    assert data.paid("current", "prior") > 0 or data.paid("current") > 0

    rows = _body(rendered.tables("reimbursement-summary.html")["open-requests"])
    ordered = sorted(data.queue, key=lambda e: (-e.pay_now, e.submitted, e.ticket_ref))
    assert len(ordered) <= 4  # every open request fits: no Other row in this fixture
    chips = {"expense_date": "By expense date", "submitted": "By submission", None: "No"}
    expected = [
        [
            f"{render._fit(e.ticket_ref, 34, render._TABLE_EMS)} "
            f"submitted {e.submitted.isoformat()}",
            f"{e.earliest_expense_date:%b} {e.earliest_expense_date.day}, "
            f"{e.earliest_expense_date.year}"
            if e.earliest_expense_date
            else "Not recorded",
            str(e.undated_items),
            format_whole(e.pay_now),
            chips[e.carryover_basis],
        ]
        for e in ordered
    ]
    assert _texts(rows) == [*expected, ["All open requests", format_whole(data.outstanding), ""]]
    assert sum((e.pay_now for e in data.queue), Decimal("0.00")) == data.outstanding
    assert f"Approved and not yet paid: {format_whole(data.outstanding)}" in text
    # A paid-but-unsettled request owes nothing now: an observed $0, never a dash.
    zero = [row for row in rows[:-1] if row[3].text == "$0"]
    assert zero and all("zero" in row[3].classes for row in zero)
    # Data follow-ups: reader text for this page's codes, by count then code.
    codes = sorted(
        (i for i in facts_.issues if i.code.startswith("reimbursement_")),
        key=lambda i: (-i.count, i.code),
    )
    cards = re.findall(r'<div class="followup"><strong>([^<]*)</strong><p>([^<]*)</p>', html)
    assert [unescape(t) for t, _ in cards] == [render._FOLLOWUPS[i.code][0] for i in codes][:4]
    assert (
        "Items without an amount",
        "1 item(s) have no amount; they are counted, never shown as $0.",
    ) in [(unescape(t), unescape(line)) for t, line in cards]


def _assert_other_budget_row(row: list[Cell], count: int) -> None:
    """The Budget "Other lines" row is counts only: a sum would blend income with expense
    targets and cover only the lines with a known actual, so target less to date would not
    reconcile. One muted cell spans the three amount columns; it is neither the unknown
    dash nor a partial star (those would wrongly explain known targets), and never $."""
    assert row[0].text == f"Other lines ({count})"
    assert len(row) == 3
    note = row[1]
    assert note.text == "not totaled; see run records" and "colspan:3" in note.classes
    assert not note.classes & {"unk", "partial", "starred"}
    assert not any(c.startswith("state:") for c in note.classes)
    assert not any("$" in cell.text for cell in row)


def test_budget_snapshot_follows_the_facts(rendered: RenderedSet) -> None:
    facts_ = rendered.facts
    budget = facts_.budget
    school = facts_.view("school", "adjusted")
    html = rendered.html("budget-snapshot.html")
    text = _text(html)
    unknown = sum(1 for line in budget.lines if line.actual is None)
    assert _tiles(html) == [
        ("closed", "", format_whole(school.income), "Received (bank basis)", ""),
        ("spent", "", format_whole(-school.expense), "Spent (bank basis)", ""),
        (
            "open",
            "",
            str(unknown),
            "Unknown actuals",
            f"of {len(budget.lines)} adopted lines",
        ),
        (
            "",
            "",
            format_whole(school.net),
            f"{SCHOOL_LABEL} adjusted bank net",
            "A change over the period, not a balance",
        ),
    ]
    rows = _body(rendered.tables("budget-snapshot.html")["lines"])
    ordered = sorted(
        budget.lines, key=lambda line: (line.target is None, -(line.target or 0), line.position)
    )
    shown, rest = ordered[:4], ordered[4:]
    reasons = {
        "category_unmapped": "Unknown: no source category",
        "ambiguous": "Unknown: category on two lines",
    }
    for row, line in zip(rows, shown, strict=False):
        typed = line.line_type in ("income", "expense")
        activity = None
        if line.actual is not None and typed:
            activity = line.actual if line.line_type == "income" else -line.actual
        remaining = None if line.target is None or activity is None else line.target - activity
        status = (
            reasons[line.actual_status]
            if line.actual is None
            else ("Observed" if typed else "Unknown: not income/expense")
        )
        assert [c.text for c in row] == [
            line.line_type.capitalize() or "Blank",
            line.category,
            _whole_or_dash(line.target),
            _whole_or_dash(activity),
            _whole_or_dash(remaining),
            status,
        ]
        assert ("unk" in row[3].classes) == (activity is None)
    kinds = {"income": 0, "expense": 0, "other": 0}
    for line in rest:
        kinds[line.line_type if line.line_type in ("income", "expense") else "other"] += 1
    assert rows[-1][0].text == f"Other lines ({len(rest)})"
    assert len(rows) == len(shown) + 1
    # The rest has unknown actuals beside a known one, and lines neither income nor expense.
    assert any(x.actual is None for x in rest) and any(x.actual is not None for x in rest)
    assert kinds["other"]
    _assert_other_budget_row(rows[-1], len(rest))
    meta = " · ".join(f"{n} {kind} line{'' if n == 1 else 's'}" for kind, n in kinds.items() if n)
    assert rows[-1][2].text == meta
    outside = sum((a for _, a in (*budget.unmapped, *budget.unbudgeted)), Decimal("0.00"))
    count = len(budget.unmapped) + len(budget.unbudgeted)
    assert (
        f"{count} lines outside the adopted lines: {format_whole(outside)} · 1 row of other "
        "fiscal years · 2 lines neither income nor expense"
    ) in text
    assert budget.other_year_rows == 1 and HOSTILE in [n for n, _ in budget.unbudgeted]
    assert f"Crosswalk version {budget.crosswalk_version}" in text
    # Meters: income and spending against the adopted targets (unreadable targets noted).
    income = sum(
        (x.target for x in budget.lines if x.line_type == "income" and x.target), Decimal(0)
    )
    expense = sum(
        (x.target for x in budget.lines if x.line_type == "expense" and x.target), Decimal(0)
    )
    # One expense target is unreadable: that target and its percent carry the star.
    assert f"Target {format_whole(income)}<" in html and f"Target {format_whole(expense)}*<" in html
    progress = _text(
        "<body>" + html.split("Progress against the adopted budget")[1].split("</div>")[0]
    )
    assert (
        f"% of the year has passed · income {render.pct(school.income, income)} · spending "
        f"{render.pct(-school.expense, expense)} of target"
    ) in progress
    assert re.search(r'spending <span class="partial">[^<]+</span> of target', html)
    # Where money went / came from: shares that add to exactly 100.
    went = re.findall(r'<div class="stack" id="went"[^>]*>(.*?)</div>', html)[0]
    widths = [Decimal(w) for w in re.findall(r"width:([\d.]+)%", went)]
    assert sum(widths) == Decimal("100.0")
    spent = sorted((-a for _, a in school.category_totals() if a < 0), reverse=True)
    assert len(widths) == min(len(spent), 5)
    # Only two follow-ups fit beside the progress meters; the qualifier says how many exist.
    cards = re.findall(r'<div class="followup">', html)
    total = len(render._followups(facts_, "budget-snapshot"))
    assert len(cards) == min(total, 2) and total > 2
    assert f"2 of {total} shown; all are in records/facts.json" in text


def test_fundraising_summary_follows_the_facts(rendered: RenderedSet) -> None:
    facts_ = rendered.facts
    items = facts_.fundraising
    school = facts_.view("school", "adjusted")
    period = facts_.periods.school
    html = rendered.html("fundraising-summary.html")
    text = _text(html)
    target = sum(
        (x.target for x in facts_.budget.lines if x.line_type == "income" and x.target),
        Decimal(0),
    )
    unknown = {
        item.source_alias
        for item in items
        if "coverage_partial" in item.incomplete_reasons
        and item.payment_count + item.fee_rows + item.refund_rows + item.excluded_rows == 0
    }
    complete = sum(1 for item in items if item.complete)
    gap = int(render._whole(target)) - int(render._whole(school.income))
    assert _tiles(html) == [
        ("closed", "", format_whole(school.income), "Income received since Jul 1", ""),
        (
            "",
            "",
            render.pct(school.income, target),
            f"Of the {format_whole(target)} adopted income target",
            "",
        ),
        (
            "amount",
            "",
            f"${gap:,}",
            f"Still to reach the target by {period.end_inclusive:%b} 30",
            "",
        ),
        (
            "open",
            "",
            f"{complete} of {len(items)}",
            "Processors complete",
            f"{len(unknown)} with no rows or coverage",
        ),
    ]
    assert unknown == {"paypal"} and complete < len(items)
    routes = _routes(html)
    known = [item for item in items if item.source_alias not in unknown]
    shares = render.largest_remainder([item.gross for item in known], 100)
    by_alias = dict(zip((i.source_alias for i in known), shares, strict=True))
    assert [(r[0], r[2]) for r in routes] == [
        (
            item.source_alias,
            "–"
            if item.source_alias in unknown
            else f"{format_whole(item.gross)} · {by_alias[item.source_alias]}%",
        )
        for item in items
    ]
    assert sum(by_alias.values()) == 100
    assert next(r for r in routes if r[0] == "paypal")[1] == ""  # no bar for an unknown
    fees = sum((i.fees for i in known), Decimal("0.00"))
    refunds = sum((i.refunds for i in known), Decimal("0.00"))
    net = sum((i.net for i in known), Decimal("0.00"))
    assert (
        f"Fees {format_whole(fees)} · Refunds {format_whole(refunds)} · Net {format_whole(net)}"
        in text
    )
    rows = _texts(_body(rendered.tables("fundraising-summary.html")["income-lines"]))
    income_lines = [x for x in facts_.budget.lines if x.line_type == "income"]
    assert rows == [
        *(
            [
                x.category,
                _whole_or_dash(x.target),
                _whole_or_dash(x.actual),
                MEASURE[x.actual_status],
            ]
            for x in income_lines
        ),
        [
            "All income lines",
            format_whole(target),
            format_whole(sum((x.actual or 0 for x in income_lines), Decimal("0.00"))),
            "",
        ],
    ]
    months = {m.month: m for m in school.months}
    for month in (date(2030, 7, 1), date(2030, 8, 1)):
        value = months[month].income if month in months else Decimal("0.00")
        assert f"{month:%b} {format_whole(value)}" in text
    assert "bank basis, all income categories" in text.lower()


def test_pnl_summary_and_appendix_follow_the_calendar_views(rendered: RenderedSet) -> None:
    facts_ = rendered.facts
    adjusted = facts_.view("calendar", "adjusted")
    source = facts_.view("calendar", "source")
    assert adjusted.complete
    html = rendered.html("cfo-pnl-summary.html")
    text = _text(html)
    assert _tiles(html) == [
        ("", "", format_whole(adjusted.income), "Income year to date", ""),
        ("spent", "", format_whole(-adjusted.expense), "Expenses year to date", ""),
        ("", "", format_whole(adjusted.net), "Net year to date", ""),
        (
            "",
            "",
            "8 of 8",
            "Months with declared bank coverage",
            f"Control check: {facts_.pnl_control_status.capitalize()}",
        ),
    ]
    tables = rendered.tables("cfo-pnl-summary.html")
    ranked = sorted(adjusted.category_totals(), key=lambda item: (-abs(item[1]), item[0]))
    top = _texts(_body(tables["categories"]))
    picked = _pnl_picked(ranked)
    shown = [(n, a) for n, a in ranked if n in picked]
    rest = [(n, a) for n, a in ranked if n not in picked]
    assert top[:4] == [
        [
            render._fit(name, 34, render._TABLE_EMS),
            "Income" if amount > 0 else "Expense",
            format_whole(amount),
            render.pct(amount, adjusted.income, share=True)
            if amount > 0
            else render.pct(-amount, -adjusted.expense, share=True),
            str(sum(1 for c in adjusted.cells if c.category == name and c.net != 0)),
        ]
        for name, amount in shown
    ]
    # The two largest income and expense categories; the rest is summed into one Other row.
    assert len(ranked) == 6 and len(top) == 6
    assert [t[1] for t in top[:4]] == ["Income", "Income", "Expense", "Expense"]
    other = sum((a for _, a in rest), Decimal("0.00"))
    assert top[4] == ["Other, net (2 categories)", format_whole(other), "", ""]
    assert top[-1] == ["Net", format_whole(adjusted.net), "", ""]
    assert sum((a for _, a in ranked), Decimal("0.00")) == adjusted.net

    monthly = tables["monthly"]
    months = [date(2030, m, 1) for m in range(1, 9)]
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    assert [c.text for c in monthly[0]] == ["Category", *names, "Year to date"]
    zero = Decimal("0.00")
    cells = {(c.category, c.month): c.net for c in adjusted.cells}

    def ytd(name: str) -> Decimal:
        return sum((cells.get((name, m), zero) for m in months), zero)

    order = sorted({c.category for c in adjusted.cells}, key=lambda n: (-abs(ytd(n)), n))

    def row(name: str) -> list[str]:
        return [
            render._fit(name, 34, 18),
            *(format_whole(cells.get((name, m), zero)) for m in months),
            format_whole(ytd(name)),
        ]

    adjusted_months = {m.month: m for m in adjusted.months}
    source_months = {m.month: m for m in source.months}

    def month_value(table: dict[Any, Any], month: Any, attr: str) -> Decimal:
        return getattr(table[month], attr) if month in table else zero

    expected = [
        ["Income"],
        *(row(n) for n in order if ytd(n) > 0),
        ["Expenses"],
        *(row(n) for n in order if ytd(n) <= 0),
        *(
            [
                label,
                *(format_whole(month_value(adjusted_months, m, attr)) for m in months),
                format_whole(total),
            ]
            for label, attr, total in (
                ("Income", "income", adjusted.income),
                ("Expenses", "expense", adjusted.expense),
                ("Net", "net", adjusted.net),
            )
        ),
        [
            "Source net (CFO view)",
            *(format_whole(month_value(source_months, m, "net")) for m in months),
            format_whole(source.net),
        ],
        [
            "Adjustments",
            *(
                format_whole(
                    month_value(adjusted_months, m, "net") - month_value(source_months, m, "net")
                )
                for m in months
            ),
            format_whole(adjusted.net - source.net),
        ],
    ]
    assert _texts(monthly[1:]) == expected
    assert adjusted.net != source.net  # the recorded adjustments move the calendar view
    assert HOSTILE in order
    assert '<tr class="group"><td colspan="10">Income</td></tr>' in html
    assert f"Control check against the CFO P&L: {facts_.pnl_control_status}" in text
    assert "$0" in [c.text for r in monthly for c in r]  # covered empty months are observed zeros


@pytest.mark.parametrize("page", sorted(set(BRIDGE_PAGES.values())))
def test_each_page_counts_its_bridges_and_the_pnl_lists_one_line_per_bridge(
    rendered: RenderedSet, page: str
) -> None:
    names = [name for name, owner in BRIDGE_PAGES.items() if owner == page]
    bridges = [rendered.facts.bridge(name) for name in names]
    balanced = sum(1 for bridge in bridges if bridge.balanced)
    audit = _audit_text(rendered.html(page))
    assert f"Bridges balanced {balanced} of {len(bridges)}." in audit
    for bridge in bridges:  # never an evidence list: no source row reference on any summary
        for row in bridge.rows:
            for ref in row.refs:
                assert _ref_text(ref) not in rendered.html(page)
            for key in row.item_keys:
                assert f"Reimbursement item {key}" not in _text(rendered.html(page))
    assert "Bridges balanced" not in _audit_text(rendered.html("fundraising-summary.html"))
    if page != "cfo-pnl-summary.html":
        return
    rows = _texts(_body(rendered.tables(page)["reconciliation"]))
    assert rows == [
        [
            render.SHORT_BRIDGE_TITLES[bridge.name],
            format_whole(bridge.from_amount),
            format_whole(sum((r.amount for r in bridge.rows), Decimal("0.00"))),
            format_whole(bridge.residual),
            "Balanced" if bridge.balanced else "Residual",
            str(sum(len(r.refs) + len(r.adjustment_ids) + len(r.item_keys) for r in bridge.rows)),
        ]
        for bridge in bridges
    ]
    assert re.findall(r'<tr data-bridge="([a-z_]+)">', rendered.html(page)) == names


@pytest.mark.parametrize("case", ["every_unknown", "no_processors"])
def test_fundraising_unknown_processors_are_dashes_never_zero(tmp_path: Path, case: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)
    items = inputs.facts.fundraising
    changed = (
        tuple(item for item in items if item.source_alias == "paypal")
        if case == "every_unknown"
        else ()
    )
    inputs.write(facts=dataclasses.replace(inputs.facts, fundraising=changed))
    html = (inputs.run_dir / "fundraising-summary.html").read_text(encoding="utf-8")
    text = _text(html)
    tile = _tiles(html)[3]
    if case == "no_processors":
        assert tile[2:4] == ("0 of 0", "Processors complete")
        assert "No processor source is configured or captured." in text
        assert "No online processor is configured." in text
        return
    assert tile == ("open", "", "0 of 1", "Processors complete", "1 with no rows or coverage")
    routes = _routes(html)
    assert routes == [("paypal", "", "–")]
    assert '<span class="val unk">–</span>' in html
    assert "Fees Unknown · Refunds Unknown · Net Unknown" in text
    assert "Online processors recorded Unknown gross and Unknown after fees and refunds" in text
    assert "$0 ·" not in text


@pytest.mark.parametrize(
    ("bridge", "page"),
    [
        ("school_expense_basis", "reimbursement-summary"),
        ("calendar_source_scope", "cfo-pnl-summary"),
    ],
)
def test_an_unexplained_residual_stays_visible(tmp_path: Path, bridge: str, page: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False)

    def shifted(item: Bridge) -> Bridge:
        if item.name != bridge:
            return item
        return dataclasses.replace(item, to_amount=item.to_amount + Decimal("1.00"))

    tampered = dataclasses.replace(
        inputs.facts, bridges=tuple(shifted(item) for item in inputs.facts.bridges)
    )
    inputs.write(facts=tampered)
    html = (inputs.run_dir / f"{page}.html").read_text(encoding="utf-8")
    title = render.SHORT_BRIDGE_TITLES[bridge]
    assert f'<span class="warn">{escape(title)}: residual $1</span>' in html
    names = [n for n, owner in BRIDGE_PAGES.items() if owner == f"{page}.html"]
    assert f"Bridges balanced {len(names) - 1} of {len(names)}." in _audit_text(html)
    if page == "cfo-pnl-summary":
        row = next(r for r in _tables(html)["reconciliation"] if r[0].text == title)
        assert [c.text for c in row[3:5]] == ["$1", "Residual"]
        assert '<span class="chip stop">Residual</span>' in html


def test_shared_scope_totals_match_in_every_report_that_shows_them(
    rendered: RenderedSet,
) -> None:
    facts_ = rendered.facts
    school = facts_.view("school", "adjusted").net
    calendar = facts_.view("calendar", "adjusted").net
    outstanding = facts_.reimbursements.outstanding
    paid = facts_.reimbursements.paid("current")
    index = _texts(_body(rendered.tables(INDEX_HTML)["shared"]))
    assert index == [  # the one place exact cents are shown
        [
            f"{SCHOOL_LABEL} adjusted bank net",
            format_money(school),
            "Budget Snapshot, Fundraising Summary, CFO P&L Summary",
        ],
        [f"{CALENDAR_LABEL} adjusted bank net", format_money(calendar), "CFO P&L Summary"],
        [
            "Approved and not yet paid (all open requests)",
            format_money(outstanding),
            "Reimbursement Summary, Reimbursement Queue",
        ],
        [f"Reimbursements paid in {SCHOOL_LABEL}", format_money(paid), "Reimbursement Summary"],
    ]
    budget = _tiles(rendered.html("budget-snapshot.html"))
    assert budget[3][2:4] == (format_whole(school), f"{SCHOOL_LABEL} adjusted bank net")
    pnl = _tiles(rendered.html("cfo-pnl-summary.html"))
    assert pnl[2][2:4] == (format_whole(calendar), "Net year to date")
    reconciliation = {
        row[0].text: row for row in _tables(rendered.html("cfo-pnl-summary.html"))["reconciliation"]
    }
    assert reconciliation["Calendar year → school year"][1].text == format_whole(calendar)
    reimbursement = _text(rendered.html("reimbursement-summary.html"))
    assert f"All open requests {format_whole(outstanding)}" in reimbursement
    assert f"Paid in the period {format_whole(paid)}" in reimbursement
    queue = reimbursement_report.load_bundle(rendered.inputs.staged)
    assert queue.summary.outstanding == facts_.reimbursements.outstanding


def test_hostile_labels_are_escaped_at_every_site(rendered: RenderedSet) -> None:
    for name in HTML_FILES:
        assert RAW_MARKER not in rendered.html(name), name
    sites = {
        "organization": HTML_FILES,
        "non-feed capture label": [INDEX_HTML],
        "bank category": ["cfo-pnl-summary.html", "budget-snapshot.html"],
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
    # A truncated label keeps its full, escaped text in a title attribute.
    assert f'title="P-001 {ESCAPED}"' in reimbursement
    assert f'title="{ESCAPED}"' in rendered.html("cfo-pnl-summary.html")
    # Evidence lists, payment references and item keys are no longer on any summary.
    for name in SUMMARY_HTML:
        html = rendered.html(name)
        assert f"Ref {ESCAPED}" not in html and f"new-03:{ESCAPED}" not in html


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
    # Run records are written beside the set by the runner (records/), not by render.write.
    files = {href for href in hrefs if not href.startswith("records/")}
    assert hrefs - files == {f"records/{name}" for name in runner._RECORD_FILES}
    assert all((run_dir / href).is_file() for href in files)


# --------------------------------------------------------------------------------------
# Coverage gaps
# --------------------------------------------------------------------------------------


# Budget lines whose actual or target is unknown, placed in the shown rows (largest targets).
UNKNOWN_BUDGET_CASES: dict[str, list[list[str]]] = {
    "unmapped_untyped": [
        _budget_row("2031", "expense", "proposed", "9000", "Example gala"),
        _budget_row("2031", "transfer", "proposed", "8000", "Fees and Charges"),
        _budget_row("2031", "expense", "proposed", "200", "Assemblies"),
    ],
    "ambiguous_and_observed_zero": [
        _budget_row("2031", "expense", "proposed", "9000", "Classroom Supplies"),
        _budget_row("2031", "expense", "proposed", "8000", "Classroom Supplies"),
        _budget_row("2031", "expense", "proposed", "7000", "Assemblies"),
    ],
    "target_missing": [
        _budget_row("2031", "expense", "proposed", "not a number", "Field Trips"),
        _budget_row("2031", "income", "proposed", "1,500", "Fundraising"),
    ],
}


def _assert_dash(cell: Cell, state: str = "unknown") -> None:
    """An unknown amount: the muted dash with its state, never a zero."""
    assert cell.text == "–" and {"unk", f"state:{state}"} <= cell.classes, cell
    assert "0" not in cell.text


@pytest.mark.parametrize("case", sorted(UNKNOWN_BUDGET_CASES))
def test_budget_unknowns_render_as_dashes_never_zero(tmp_path: Path, case: str) -> None:
    inputs = _inputs(tmp_path, adjusted=False, budget=UNKNOWN_BUDGET_CASES[case])
    inputs.write()
    html = (inputs.run_dir / "budget-snapshot.html").read_text(encoding="utf-8")
    body = [row for row in _body(_tables(html)["lines"]) if len(row) == 6]
    statuses = {line.category: line.actual_status for line in inputs.facts.budget.lines}
    if case == "unmapped_untyped":
        rows = {row[1].text: row for row in body}
        unmapped = rows["Example gala"]
        assert statuses["Example gala"] == "category_unmapped"
        assert unmapped[2].text == "$9,000"
        _assert_dash(unmapped[3])
        _assert_dash(unmapped[4])
        assert unmapped[5].text == "Unknown: no source category"
        untyped = rows["Fees and Charges"]
        assert untyped[0].text == "Transfer"
        _assert_dash(untyped[3])  # an actual exists, but the line is neither income nor expense
        _assert_dash(untyped[4])
        assert untyped[5].text == "Unknown: not income/expense"
    elif case == "ambiguous_and_observed_zero":
        assert statuses["Classroom Supplies"] == "ambiguous"
        lines = [row for row in body if row[1].text == "Classroom Supplies"]
        assert len(lines) == 2
        for line in lines:
            _assert_dash(line[3])
            _assert_dash(line[4])
            assert line[5].text == "Unknown: category on two lines"
        assemblies = next(row for row in body if row[1].text == "Assemblies")
        assert [c.text for c in assemblies[2:5]] == ["$7,000", "$0", "$7,000"]  # observed zero
        assert "zero" in assemblies[3].classes and "unk" not in assemblies[3].classes
    else:
        field = next(row for row in body if row[1].text == "Field Trips")
        assert (
            next(x for x in inputs.facts.budget.lines if x.category == "Field Trips").target is None
        )
        _assert_dash(field[2])  # the target is unreadable
        assert field[3].text != "–"  # its actual is still observed
        _assert_dash(field[4])  # target less to date is unknown, never $0
        assert "No readable target" in _text(html)  # no readable expense target at all
    assert _text(html).count(LEGEND) == 1


def test_partial_coverage_marks_processor_figures_percents_and_meters(tmp_path: Path) -> None:
    inputs = _inputs(
        tmp_path,
        adjusted=False,
        bank_coverage='start = "2030-03-01", end = "2030-07-31"',
        pnl=PNL_VALUES,
    )
    inputs.write()
    fundraising = (inputs.run_dir / "fundraising-summary.html").read_text(encoding="utf-8")
    items = inputs.facts.fundraising
    assert any(not item.complete for item in items)
    # Percent of target, its tile and the meter are partial when bank coverage is partial.
    assert _tiles(fundraising)[1][1] == "partial"
    assert re.search(
        r'<h2><span class="partial">[^<]+</span> of the adopted income target', fundraising
    )
    assert re.search(r"<text [^>]*>\$[\d,]+\* received</text>", fundraising)
    assert "(partial: bank coverage is incomplete)" in _text(fundraising)
    # Incomplete processors and every combined processor figure carry the partial mark.
    for label, _, value in _routes(fundraising):
        item = next(i for i in items if i.source_alias == label)
        if value != "–":
            marked = f'<span class="val partial">{escape(value)}</span>' in fundraising
            assert marked == (not item.complete), label
    combined = fundraising.split("Fees ", 1)[1].split("</p>", 1)[0]
    assert combined.count('<span class="partial">') == 3
    assert "excludes 1 processor with no rows or coverage" in _text(fundraising)
    budget = (inputs.run_dir / "budget-snapshot.html").read_text(encoding="utf-8")
    assert re.search(r'income <span class="partial">[^<]+</span> · spending', budget)
    assert re.search(r"<text [^>]*>\$[\d,]+\* spent</text>", budget)
    assert 'class="amt partial"' in budget  # the stacked categories


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
    monthly = _tables(pnl)["monthly"]
    assert [c.text for c in monthly[0][1:-1]] == [
        "Jan*",
        "Feb*",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug*",
    ]  # a partial month is marked once, in its header
    rows = {row[0].text: row for row in monthly}
    net = [(sorted(c.classes - {"amt"}), c.text) for c in rows["Net"][1:]]
    assert net[0] == ([], format_whole(Decimal("100.00")))  # January: seen, uncovered
    assert net[1] == (["state:uncovered", "unk"], "–")  # February: nothing seen, uncovered
    assert net[2] == (["zero"], "$0")  # March: covered, an observed zero
    assert net[7] == ([], format_whole(Decimal("-5.00")))  # August: after coverage
    assert "partial" in rows["Net"][-1].classes  # year to date
    assert 'data-state="uncovered" title="No declared bank coverage">–</td>' in pnl
    assert "Not covered" not in pnl
    tiles = _tiles(pnl)
    assert tiles[3][:4] == ("open", "", "5 of 8", "Months with declared bank coverage")
    assert all("partial" in tile[1] for tile in tiles[:3])
    text = _text(pnl)
    assert text.count(LEGEND) == 1  # the one legend line
    assert "5 of 8 months have declared bank coverage; the others are unknown, not zero." in text
    control = inputs.facts.pnl_control_status
    assert control != "mismatched" and f"Control check: {control.capitalize()}" in text

    school = inputs.facts.view("school", "adjusted")
    calendar = inputs.facts.view("calendar", "adjusted")
    assert not school.complete and not calendar.complete
    fundraising = (inputs.run_dir / "fundraising-summary.html").read_text(encoding="utf-8")
    received = _tiles(fundraising)[0]
    assert received[1:3] == ("partial", format_whole(school.income))
    assert _text(fundraising).count(LEGEND) == 1
    assert '<span class="partial">' in fundraising  # August income seen after coverage
    budget = (inputs.run_dir / "budget-snapshot.html").read_text(encoding="utf-8")
    net_tile = _tiles(budget)[3]
    assert net_tile[1:4] == (
        "partial",
        format_whole(school.net),
        f"{SCHOOL_LABEL} adjusted bank net",
    )
    assert "(partial: bank coverage is incomplete)" in _text(budget)
    classroom = next(
        row for row in _body(_tables(budget)["lines"]) if row[1].text == "Classroom Supplies"
    )
    assert [c.text for c in classroom[3:6]] == ["–", "–", "Unknown: coverage partial"]
    assert "state:unknown" in classroom[3].classes
    assert _text(budget).count(LEGEND) == 1
    index = (inputs.run_dir / INDEX_HTML).read_text(encoding="utf-8")
    shared = {row[0].text: row[1] for row in _body(_tables(index)["shared"])}
    assert "partial" in shared[f"{SCHOOL_LABEL} adjusted bank net"].classes
    assert "partial" in shared[f"{CALENDAR_LABEL} adjusted bank net"].classes
    assert "partial" not in shared["Approved and not yet paid (all open requests)"].classes
    assert "* Partial: bank coverage is incomplete" in _text(index)
    footer = _text("<body>" + pnl.split('<footer class="foot">')[1])
    assert "Bank coverage partial for 1 source; see the index" in footer


def test_the_legend_line_is_absent_without_a_dash_or_star(rendered: RenderedSet) -> None:
    # Full bank coverage: no starred month and no partial total on the P&L page.
    pnl = rendered.html("cfo-pnl-summary.html")
    assert 'class="amt unk"' not in pnl and "starred" not in pnl
    assert LEGEND not in _text(pnl)


def test_the_other_budget_row_alone_does_not_trigger_the_legend(tmp_path: Path) -> None:
    # Five known lines: four shown in full and one counted in the Other row, which carries
    # no unknown or partial marker, so the Budget page has no dash or star to explain.
    inputs = _inputs(tmp_path)
    inputs.write()
    html = (inputs.run_dir / "budget-snapshot.html").read_text(encoding="utf-8")
    rows = _body(_tables(html)["lines"])
    assert len(rows) == 4 + 1
    _assert_other_budget_row(rows[-1], 1)
    assert 'title="The remaining lines and their amounts are in the run records"' in html
    assert not re.search(r'class="[^"]*(?:unk|partial|starred)', html)
    assert LEGEND not in _text(html)


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
    expected = (
        f"{len(OUTPUT_NAMES)} output file(s) and 0"
        if leftover == "output"
        else "0 output file(s) and 1"
    )
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


def test_pointer_page_links_every_file_of_the_run_and_escapes_its_link() -> None:
    link = 'runs/<x>&"'
    page = render.pointer_page(
        run_id=RUN_ID,
        input_sha256="a" * 64,
        as_of=date(2030, 8, 15),
        published_at=datetime(2030, 8, 16, 9, 30, tzinfo=UTC),
        run_link=link,
        manifest_name="run-manifest.json",
    )
    escaped = str(escape(link))
    hrefs = re.findall(r'href="([^"]*)"', page)
    assert hrefs == [
        f"{escaped}/{name}"
        for name in (
            INDEX_HTML,
            QUEUE_HTML,
            COPY_TEXT,
            *SUMMARY_HTML,
            "run-manifest.json",
        )
    ]
    assert link not in page  # never raw
    assert f'<meta http-equiv="Content-Security-Policy" content="{CSP}">' in page
    assert str(render.run_id_meta(RUN_ID)) in page
    assert str(render.input_set_meta("a" * 64)) in page
    text = _text(page)
    assert "As of August 15, 2030" in text and "2030-08-16 09:30 UTC" in text
    for title in ("Reimbursement Queue", "Reimbursement Queue copy text", "Run manifest"):
        assert title in text
    assert all(title in text for title in TITLES.values())


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


def _pdf_sizes(payload: bytes) -> list[tuple[int, int]]:
    """(width, height) in points of every page, read from the PDF structure alone.

    Needs no optional library: Chromium writes one uncompressed ``/Type /Page`` object with
    its ``/MediaBox`` per page, so a missing parser can never turn a page check into a skip.
    """
    pages = re.findall(rb"/Type\s*/Page(?![A-Za-z])", payload)
    boxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", payload)
    assert pages and len(pages) == len(boxes), "unreadable PDF page structure"
    return [(round(float(w)), round(float(h))) for w, h in boxes]


def _pdf_texts(payload: bytes) -> list[str] | None:
    """Page texts when pypdfium2 (the ``slides`` extra) is installed: an extra check only;
    every gate also has a dependency-free form."""
    try:
        import pypdfium2
    except ImportError:
        return None
    document = pypdfium2.PdfDocument(payload)
    try:
        return [document[i].get_textpage().get_text_range() for i in range(len(document))]
    finally:
        document.close()


def test_pdf_page_structure_is_read_without_optional_libraries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    assert _pdf_texts(b"%PDF-") is None
    payload = (
        b"%PDF-1.4\n1 0 obj << /Type /Pages /Count 2 >> endobj\n"
        b"2 0 obj << /Type /Page /MediaBox [0 0 612 792] >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 792 612] >> endobj\n"
    )
    assert _pdf_sizes(payload) == [(612, 792), (792, 612)]
    with pytest.raises(AssertionError):
        _pdf_sizes(b"%PDF-1.4\n2 0 obj << /Type /Page >> endobj\n")


def test_chromium_export_produces_readable_pdf_and_png(tmp_path: Path) -> None:
    playwright = require_chromium()
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
        payload = (inputs.run_dir / f"{name}.pdf").read_bytes()
        sizes = _pdf_sizes(payload)
        if name == "cfo-pnl-summary":  # a portrait brief, then the landscape appendix
            assert sizes == [(612, 792), (792, 612)], name
        else:
            assert sizes == [(612, 792)], name
        texts = _pdf_texts(payload)
        if texts is not None:  # extra: the printed text itself
            assert TITLES[f"{name}.html"] in texts[0]
        png = (inputs.run_dir / f"{name}.png").read_bytes()
        png_width, png_height = _png_size(png)
        assert png_width == export.VIEWPORT_WIDTH
        # A full-page capture of the whole document (a one-page sheet is ~1,100 px tall).
        assert heights[name] > 900, name
        assert png_height >= heights[name] - 2, name
        assert _png_distinct_bytes(png) > 8, "the capture is not blank"


# --------------------------------------------------------------------------------------
# One-page fit (docs/plan-reference/main-report-design.md § 1.16), standard to adversarial
# --------------------------------------------------------------------------------------

# Every one-page summary keeps this much of the 973 px Letter content box unused, so the
# fit is structural rather than marginal.
FIT_LIMIT = 973
FIT_RESERVE = 40

_SCREEN_CHECK = """() => {
  const problems = [];
  for (const sheet of document.querySelectorAll('.sheet')) {
    const box = sheet.getBoundingClientRect();
    for (const el of sheet.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || el.closest('title, desc')) continue;
      if (r.left < box.left - 0.5 || r.right > box.right + 0.5)
        problems.push('outside:' + el.tagName + '.' + el.getAttribute('class'));
      const overflow = getComputedStyle(el).overflowX;
      const cell = el.tagName === 'TH' || el.tagName === 'TD';
      if ((overflow !== 'visible' || cell) && el.scrollWidth > el.clientWidth + 1)
        problems.push('clipped:' + el.tagName + '.' + el.getAttribute('class') + ':'
          + el.textContent.slice(0, 30));
    }
  }
  return {problems, scroll: document.documentElement.scrollWidth, inner: innerWidth};
}"""
_PRINT_CHECK = """() => {
  const sheet = document.querySelector('.sheet');
  const rows = [...document.querySelectorAll('table:not(.pnl) tbody tr')]
    .map(r => r.getBoundingClientRect().height);
  const n = document.querySelector('.narrative');
  const p = n ? n.querySelector('p') : null;
  const tables = [...document.querySelectorAll('table.pnl')];
  return {
    height: sheet.getBoundingClientRect().height,
    row: Math.max(0, ...rows),
    narrative: n ? n.getBoundingClientRect().height : 0,
    line: p ? parseFloat(getComputedStyle(p).lineHeight) : 0,
    pnlRows: document.querySelectorAll('table.pnl tbody tr').length,
    pnlTables: tables.length,
    // body rows that carry amounts on each appendix page (a group row alone is not one)
    pnlFilled: tables.map(t => t.querySelectorAll('tbody tr:not(.group)').length),
    eyebrow: document.querySelector('.eyebrow').getBoundingClientRect().height,
    text: sheet.innerText,
  };
}"""
_PHONE_CHECK = """() => ({
  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  tops: [...new Set([...document.querySelectorAll('.metrics .metric')]
    .map(m => Math.round(m.getBoundingClientRect().top)))].length,
  pad: parseFloat(getComputedStyle(document.querySelector('.sheet')).paddingLeft),
})"""
_BARS_CHECK = """() => [...document.querySelectorAll('.bars')].map(panel => {
  const rows = [...panel.querySelectorAll('.route')];
  const tracks = rows.map(r => r.querySelector('.track').getBoundingClientRect());
  const vals = rows.map(r => r.querySelector('.val').getBoundingClientRect().left);
  const errors = rows.map((r, i) => {
    const bar = r.querySelector('.bar');
    if (!bar) return 0;
    const pct = parseFloat(bar.style.width);
    return Math.abs(bar.getBoundingClientRect().width - tracks[i].width * pct / 100);
  });
  const spread = a => a.length ? Math.max(...a) - Math.min(...a) : 0;
  return {tracks: spread(tracks.map(t => t.width)), vals: spread(vals),
          error: Math.max(0, ...errors)};
})"""
_WRAP_CHECK = """() => [...document.querySelectorAll('th.wrap')]
  .map(th => [getComputedStyle(th).whiteSpace, th.scrollWidth - th.clientWidth])"""
FIT_WORLDS = ["standard", "large", "large_uncovered", "adversarial"]


def _fit_inputs(tmp_path: Path, world: str) -> RunInputs:
    if world == "standard":
        return _inputs(tmp_path, extra_source=True, **CONTENT_WORLD)
    return _large_inputs(tmp_path, covered=world == "large", adversarial=world == "adversarial")


@pytest.mark.parametrize("world", FIT_WORLDS)
def test_chromium_every_summary_fits_its_pages(tmp_path: Path, world: str) -> None:
    playwright = require_chromium()
    inputs = _fit_inputs(tmp_path, world)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnsandboxedExportWarning)
        inputs.write(exporter=None)
    run_dir = inputs.run_dir
    facts_ = inputs.facts
    if world != "standard":  # the large fixture really is large
        assert len(facts_.view("calendar", "adjusted").category_totals()) >= 45
        assert len(facts_.reimbursements.queue) >= 40 and len(facts_.budget.lines) >= 80
        assert len(facts_.discrepancy_ids) >= 40
        assert sum(len(r.refs) for b in facts_.bridges for r in b.rows) >= 300
    if world == "adversarial":  # ...and hostile where it counts
        bundle = reimbursement_report.load_bundle(inputs.staged)
        assert len(bundle.settings.organization) == 180
        assert (
            max(len(name) for name, _ in facts_.view("calendar", "adjusted").category_totals())
            >= 120
        )
        assert {"sponsorship", "", "recurring_income"} <= {x.line_type for x in facts_.budget.lines}
    printed: dict[str, dict[str, Any]] = {}
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chromium")
        page = browser.new_page(viewport={"width": 1100, "height": 1200})
        errors: list[str] = []
        requests: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        for name in SUMMARY_NAMES:
            uri = (run_dir / f"{name}.html").as_uri()
            page.set_viewport_size({"width": 1100, "height": 1200})
            page.emulate_media(media="screen")
            page.goto(uri)
            screen = page.evaluate(_SCREEN_CHECK)
            assert screen["scroll"] <= screen["inner"], name
            assert screen["problems"] == [], (name, screen["problems"][:5])
            for bars in page.evaluate(_BARS_CHECK):
                assert bars["tracks"] <= 0.5 and bars["vals"] <= 0.5, (name, bars)
                assert bars["error"] <= 1, (name, bars)
            for white_space, overflow in page.evaluate(_WRAP_CHECK):
                assert white_space == "normal" and overflow <= 1, name
            page.set_viewport_size({"width": 730, "height": 1000})
            page.emulate_media(media="print")
            page.goto(uri)
            fit = page.evaluate(_PRINT_CHECK)
            printed[name] = fit
            assert fit["height"] <= FIT_LIMIT - FIT_RESERVE, (name, fit["height"])
            assert fit["row"] <= 38, (name, fit["row"])
            assert fit["narrative"] <= 4.2 * fit["line"] + 16, (name, fit["narrative"])
            assert fit["eyebrow"] <= 16, (name, fit["eyebrow"])  # one masthead line
            page.emulate_media(media="screen")
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(uri)
            phone = page.evaluate(_PHONE_CHECK)
            assert phone["overflow"] <= 1 and phone["tops"] == 2 and phone["pad"] >= 16, name
        # The index stays a short link page.
        page.set_viewport_size({"width": 1100, "height": 1200})
        page.emulate_media(media="screen")
        page.goto((run_dir / INDEX_HTML).as_uri())
        index_pdf = page.pdf(print_background=True, prefer_css_page_size=True)
        browser.close()
    assert not errors
    assert all(url.startswith(("file:", "data:")) for url in requests)
    index_sizes = _pdf_sizes(index_pdf)
    assert 1 <= len(index_sizes) <= 2 and set(index_sizes) == {(612, 792)}

    for name in SUMMARY_NAMES:
        html = (run_dir / f"{name}.html").read_text(encoding="utf-8")
        payload = (run_dir / f"{name}.pdf").read_bytes()
        sizes = _pdf_sizes(payload)
        fit = printed[name]
        if name != "cfo-pnl-summary":
            assert sizes == [(612, 792)], (name, sizes)
        else:  # exactly one landscape page per 40 matrix body rows, none header-only
            expected = 1 + math.ceil(fit["pnlRows"] / 40)
            assert sizes == [(612, 792)] + [(792, 612)] * (expected - 1), (sizes, fit["pnlRows"])
            assert fit["pnlTables"] == expected - 1
            assert all(filled > 0 for filled in fit["pnlFilled"]), fit["pnlFilled"]
            if world == "standard":
                assert len(sizes) == 2
        # The printed text (print media), read without any PDF library.
        flat = " ".join(fit["text"].split())
        h1 = unescape(re.findall(r"<h1>([^<]*)</h1>", html)[0])
        assert h1 in flat and "Where things stand" in flat and RUN_ID in flat, name
        assert ("1 page + appendix" if name == "cfo-pnl-summary" else "1 page") in flat
        for tile in _tiles(html):
            assert tile[2] in flat, (name, tile)
        assert "Fictional Person" not in flat  # no requester name in any summary
        assert not re.search(r"\(?\d{3}\)?[ .-]\d{3}-\d{4}", flat), name  # no phone number
        texts = _pdf_texts(payload)
        if texts is not None:  # extra: the same strings in the PDF text itself
            pdf_flat = " ".join(texts[0].split())
            assert h1 in pdf_flat and RUN_ID in pdf_flat and "Fictional Person" not in pdf_flat
            for appendix_page in texts[1:]:
                assert appendix_page.count("$") >= 10


def test_large_fixture_caps_every_list_and_sums_the_rest(tmp_path: Path) -> None:
    inputs = _large_inputs(tmp_path)
    inputs.write()
    facts_ = inputs.facts
    run_dir = inputs.run_dir

    def page(name: str) -> str:
        return (run_dir / f"{name}.html").read_text(encoding="utf-8")

    data = facts_.reimbursements
    rows = _body(_tables(page("reimbursement-summary"))["open-requests"])
    assert len(rows) == 4 + 2  # four requests, Other, total
    ordered = sorted(data.queue, key=lambda e: (-e.pay_now, e.submitted, e.ticket_ref))
    rest = sum((e.pay_now for e in ordered[4:]), Decimal("0.00"))
    assert [c.text for c in rows[-2][:2]] == [
        f"{len(ordered) - 4} more open requests in the Reimbursement Queue",
        format_whole(rest),
    ]
    assert rows[-1][1].text == format_whole(data.outstanding)
    calendar = facts_.view("calendar", "adjusted")
    top = _body(_tables(page("cfo-pnl-summary"))["categories"])
    ranked = sorted(calendar.category_totals(), key=lambda i: (-abs(i[1]), i[0]))
    assert len(top) == 4 + 2
    picked = _pnl_picked(ranked)
    other = sum((a for n, a in ranked if n not in picked), Decimal("0.00"))
    assert [c.text for c in top[-2][:2]] == [
        f"Other, net ({len(ranked) - 4} categories)",
        format_whole(other),
    ]
    assert sum((a for _, a in ranked), Decimal("0.00")) == calendar.net  # table total is exact
    budget_rows = _body(_tables(page("budget-snapshot"))["lines"])
    assert len(budget_rows) == 4 + 1
    ordered_lines = sorted(
        facts_.budget.lines,
        key=lambda x: (x.target is None, -(x.target or Decimal("0.00")), x.position),
    )
    tail = ordered_lines[4:]
    # The rest mixes income and expense targets, and only some actuals are known.
    assert {"income", "expense"} <= {x.line_type for x in tail}
    assert any(x.actual is None for x in tail) and any(x.actual is not None for x in tail)
    _assert_other_budget_row(budget_rows[-1], len(tail))
    income = [x for x in facts_.budget.lines if x.line_type == "income"]
    assert len(_body(_tables(page("fundraising-summary"))["income-lines"])) == 7 + 2
    assert len(income) > 7
    routes = _routes(page("fundraising-summary"))
    assert len(routes) <= 4
    went = re.findall(r'<div class="cat">', page("budget-snapshot"))
    assert len(went) == 5
    for name in SUMMARY_NAMES:
        html = page(name)
        assert LONG_LABEL not in _text(html).replace(" ", "")  # truncated for display...
        assert len(re.findall(r'<div class="followup">', html)) <= 4
    assert f'title="{LONG_LABEL}"' in page("cfo-pnl-summary")  # ...with the full label kept


# --------------------------------------------------------------------------------------
# Audit-detail policy, privacy and whole-dollar money
# --------------------------------------------------------------------------------------


def test_summaries_show_counts_never_lists(rendered: RenderedSet) -> None:
    facts_ = rendered.facts
    assert facts_.discrepancy_ids and facts_.applied_adjustments
    for name in SUMMARY_HTML:
        html = rendered.html(name)
        text = _text(html)
        assert "DISC-" not in html and "ADJ-" not in html, name
        assert "Not covered" not in text
        audit = _audit_text(html)
        assert audit.startswith(
            f"Audit detail: Adjustments applied {len(facts_.applied_adjustments)} · "
            f"pending {len(facts_.pending_adjustments)} · "
            f"superseded {len(facts_.superseded_adjustments)} · "
            f"Adjustment warnings {len(facts_.adjustment_warnings)} · "
            f"Unresolved discrepancies {len(facts_.discrepancy_ids)} · "
            f"Findings {sum(i.count for i in facts_.issues)} · "
            f"Coverage flags {len(facts_.coverage_flags)}"
        )
        assert "Listed in records/facts.json and records/reconciliation.json of this run." in audit
        # The record names are plain text: compatibility copies live outside the run folder.
        assert 'href="records/' not in html
    index = rendered.html(INDEX_HTML)
    assert re.findall(r'href="(records/[^"]+)"', index) == [
        f"records/{name}" for name in runner._RECORD_FILES
    ]


def test_no_summary_names_a_person_email_or_payment_reference(rendered: RenderedSet) -> None:
    bundle = reimbursement_report.load_bundle(rendered.inputs.staged)
    names = {t.requestor_name for t in bundle.tickets}
    assert names
    for name in SUMMARY_HTML:
        text = _text(rendered.html(name))
        for person in names:
            assert all(token not in text for token in person.split() if len(token) > 3), name
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), name
        assert "Reference 2001" not in text and "Ref <script" not in text
        assert "noindex,nofollow" in rendered.html(name)


def _money_pool(facts_: ReportFacts) -> set[str]:
    """Whole-dollar strings every summary may show: facts values and their derivations."""
    values: set[Decimal] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str) and re.fullmatch(r"-?\d+\.\d\d", node):
            values.add(Decimal(node))

    walk(facts_.to_dict())
    zero = Decimal("0.00")
    for view in facts_.pnl_views:
        values.update(amount for _, amount in view.category_totals())
    lines = facts_.budget.lines
    for kind in ("income", "expense"):
        values.add(sum((x.target for x in lines if x.line_type == kind and x.target), zero))
    for line in lines:
        if line.target is not None and line.actual is not None:
            values.update({line.target - line.actual, line.target + line.actual})
    values.add(sum((a for _, a in (*facts_.budget.unmapped, *facts_.budget.unbudgeted)), zero))
    data = facts_.reimbursements
    values.add(sum((data.open_amount(b, "C") for b in EXPENSE_BUCKETS), zero))
    for kind in ("gross", "fees", "refunds", "net"):
        values.add(sum((getattr(i, kind) for i in facts_.fundraising), zero))
        values.add(sum((getattr(i, kind) for i in facts_.fundraising if i.payment_count), zero))
    for bridge in facts_.bridges:
        values.update({sum((r.amount for r in bridge.rows), zero), bridge.residual})
    source = {m.month: m.net for m in facts_.view("calendar", "source").months}
    for month in facts_.view("calendar", "adjusted").months:
        values.add(month.net - source.get(month.month, zero))
    values.add(facts_.view("calendar", "adjusted").net - facts_.view("calendar", "source").net)
    pool = {format_whole(v) for v in values} | {format_whole(-v) for v in values}
    target = sum((x.target for x in lines if x.line_type == "income" and x.target), zero)
    school = facts_.view("school", "adjusted")
    pool.add(render._dollars(render._whole(target) - render._whole(school.income)))
    return pool


def test_every_summary_amount_is_whole_dollars_traced_to_the_facts(rendered: RenderedSet) -> None:
    pool = _money_pool(rendered.facts)
    for name in SUMMARY_HTML:
        text = _text(rendered.html(name))
        assert not re.search(r"\$[\d,]+\.\d", text), name  # never cents on a summary
        shown = set(re.findall(r"-?\$\d{1,3}(?:,\d{3})*", text))
        if name == CLASSROOM_HTML:  # no planning input: unavailable, never $0
            assert rendered.facts.classroom is not None
            assert rendered.facts.classroom.status == "unavailable"
            assert not shown and "Unknown" in text
            continue
        assert shown and shown <= pool, (name, sorted(shown - pool))
    assert re.search(r"\$[\d,]+\.\d\d", _text(rendered.html(INDEX_HTML)))  # cents live here


def test_queue_links_resolve_to_queue_cards_and_skip_duplicate_anchors(
    rendered: RenderedSet,
) -> None:
    html = rendered.html("reimbursement-summary.html")
    queue = rendered.html(QUEUE_HTML)
    fragments = re.findall(r'href="reimbursement-report\.html#([^"]+)"', html)
    assert fragments
    for fragment in fragments:  # percent-encoded; the browser decodes it to the card id
        assert re.fullmatch(r"[A-Za-z0-9_.~%-]+", unescape(fragment))
        assert f'id="{escape(urllib.parse.unquote(unescape(fragment)))}"' in queue
    assert "%3Cscript%3E" in html  # the hostile ref's fragment is encoded, never raw
    tickets = [
        types.SimpleNamespace(review_key="a", ref="P-9", form_label="x"),
        types.SimpleNamespace(review_key="b", ref="P-9-x", form_label=""),
        types.SimpleNamespace(review_key="c", ref="P 10", form_label=""),
    ]
    bundle = types.SimpleNamespace(tickets=tickets)
    assert render._queue_anchors(bundle) == {"c": "p-10"}  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Pure display helpers
# --------------------------------------------------------------------------------------


def test_whole_dollars_round_once_half_up_and_keep_unknown() -> None:
    assert format_whole(None) == "Unknown"
    assert format_whole(Decimal("0.00")) == "$0"
    assert format_whole(Decimal("-0.49")) == "$0"
    assert format_whole(Decimal("0.50")) == "$1"
    assert format_whole(Decimal("-1234.50")) == "-$1,235"
    assert format_whole(Decimal("1234567.49")) == "$1,234,567"
    with pytest.raises(ValueError):
        format_whole(Decimal("0.001"))


def test_percent_display_rules() -> None:
    pct = render.pct
    assert pct(Decimal(5), None) == "–" and pct(Decimal(5), Decimal(0)) == "–"
    assert pct(Decimal(-5), Decimal(100)) == "0%" and pct(0, 100) == "0%"
    assert pct(Decimal("0.5"), Decimal(100)) == "<1%"
    assert pct(Decimal("99.6"), Decimal(100)) == "99%"  # below target never shows 100
    assert pct(Decimal("12.5"), Decimal(100)) == "13%"
    assert pct(Decimal(100), Decimal(100)) == "100%+" and pct(150, 100) == "100%+"
    assert pct(150, 100, share=True) == "150%" and pct(100, 100, share=True) == "100%"


def test_largest_remainder_sums_exactly() -> None:
    lr = render.largest_remainder
    assert lr([Decimal(1), Decimal(1), Decimal(1)], 100) == [34, 33, 33]
    assert lr([Decimal(2), Decimal(1)], 1000) == [667, 333]
    assert lr([Decimal(0), Decimal(-3)], 100) == [0, 0]
    assert sum(lr([Decimal("0.01")] * 7 + [Decimal(500)], 100)) == 100


def test_year_elapsed_plural_truncation_and_capture_label() -> None:
    from np_finance.main_reports.models import Period

    period = Period("school", date(2030, 7, 1), date(2031, 7, 1), date(2030, 8, 15))
    exact, whole = render.year_elapsed(period)
    assert whole == 13 and exact == Decimal(4600) / Decimal(365)
    late = dataclasses.replace(period, as_of=date(2032, 1, 1))
    assert render.year_elapsed(late)[1] == 100
    assert render.plural(1, "request", "requests") == "1 request"
    assert render.plural(2, "request", "requests") == "2 requests"
    assert render.truncate_label("abc", 3) == "abc" and render.truncate_label("abcd", 3) == "ab…"
    first = datetime(2030, 8, 15, 13, 0, 5, tzinfo=UTC)
    assert render.captured_label([first, first]) == "2030-08-15 13:00 UTC"
    assert (
        render.captured_label([first, datetime(2030, 8, 15, 14, 2, tzinfo=UTC)])
        == "2030-08-15 13:00–14:02 UTC"
    )
    assert (
        render.captured_label([datetime(2030, 8, 16, 1, 0, tzinfo=UTC), first])
        == "2030-08-15 13:00 to 2030-08-16 01:00 UTC"
    )


def test_pie_and_meter_geometry_follow_the_spec() -> None:
    pie = render._pie(2, 4)
    assert pie["base"] == "#147d83" and pie["first_pct"] == "33%" and pie["second_pct"] == "67%"
    near = render._pie(199, 1)  # an open request never reads 0%, a short whole never 100%
    assert (near["first_pct"], near["second_pct"]) == ("99%", "<1%")
    # The wedge (2/3) starts at 12 o'clock and runs clockwise with the large-arc flag set.
    assert pie["wedge"].startswith("M 80 80 L 80 12 A 68 68 0 1 1 ")
    assert pie["wedge"].endswith(" Z")
    assert render._pie(3, 0)["wedge"] == "" and render._pie(0, 3)["base"] == "#edb528"
    from np_finance.main_reports.models import Period

    period = Period("school", date(2030, 7, 1), date(2031, 7, 1), date(2030, 8, 15))
    meter = render._meter(Decimal(50), Decimal(100), period, "received", "#236c48", "m")
    assert meter["shape"] == "path" and meter["width"] == "182.5"
    assert meter["left"] == "$50 received" and meter["right"] == "Target $100"
    assert meter["top"] == "Aug 15 · 13% of the year"
    assert render._meter(Decimal(50), None, period, "received", "#236c48", "m")["missing"]
    assert render._meter(Decimal(500), Decimal(100), period, "x", "#000", "m")["shape"] == "full"
    assert render._meter(Decimal(0), Decimal(100), period, "x", "#000", "m")["shape"] == ""
    rows = render._bar_rows(
        [
            ("a", Decimal(30), False),
            ("b", None, False),
            ("c", Decimal(10), True),
            ("d", Decimal("0.01"), False),
        ]
    )
    assert [r["value"] for r in rows] == ["$30 · 75%", "–", "$10 · 25%", "$0 · <1%"]
    assert [r["partial"] for r in rows] == [False, False, True, False]
    rows = rows[:3]
    assert [r["width"] for r in rows] == ["100.0", "", "33.3"]


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]
)
def test_chromium_pages_are_readable_offline_at_desktop_and_phone_widths(
    rendered: RenderedSet, viewport: dict[str, int]
) -> None:
    playwright = require_chromium()
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
    require_chromium()
    html = tmp_path / "page.html"
    html.write_text(
        "<!doctype html><p>Example Non-profit</p><script>"
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
    require_chromium()
    monkeypatch.setattr(export, "_OFFLINE", False)
    origin = loopback.pop(0)
    (tmp_path / "tall.png").write_bytes(_png(50, 3000))
    html = tmp_path / "page.html"
    html.write_text(
        "<!doctype html><style>@page{size:letter portrait}body{margin:0}</style>"
        f'<link rel="stylesheet" href="{origin}/style.css">'
        f'<img src="{origin}/remote.png" alt="">'
        '<img src="tall.png" alt=""><p>Example Non-profit</p>',
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
    require_chromium()
    html = tmp_path / "page.html"
    html.write_text("<!doctype html><p>Example Non-profit</p>", encoding="utf-8")
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


def test_unreadable_income_targets_mark_the_fundraising_percent_and_meter(tmp_path: Path) -> None:
    budget = [
        _budget_row("2031", "income", "proposed", "1,500", "Fundraising"),
        _budget_row("2031", "income", "proposed", "not a number", "Donations"),
        _budget_row("2031", "expense", "proposed", "500", "Classroom Supplies"),
    ]
    inputs = _inputs(tmp_path, adjusted=False, budget=budget)
    inputs.write()
    assert inputs.facts.view("school", "adjusted").complete  # coverage is not the reason
    html = (inputs.run_dir / "fundraising-summary.html").read_text(encoding="utf-8")
    assert _tiles(html)[1][1] == "partial"
    assert re.search(r'<h2><span class="partial">[^<]+</span> of the adopted income target', html)
    assert "Target $1,500*</text>" in html
    assert "(some adopted targets are unreadable)" in _text(html)
    assert _text(html).count(LEGEND) == 1


# --------------------------------------------------------------------------------------
# Classroom Budgets (CORE-BRIEFS Step 66)
# --------------------------------------------------------------------------------------

_CLASSBAR = re.compile(r'<g class="classbar"><title>([^<]*)</title>')
_VALUE = re.compile(r'<text class="value( over)?"[^>]*>([^<]*)</text>')
_TEACHER = re.compile(r'<text class="teacher"[^>]*>(.*?)</text>')
_LEGEND = re.compile(r'<p class="legend"><span class="swatch"[^>]*></span>([^<]*)</p>')
# A classroom bar's tooltip: its label, then its allocation, paid and remaining figures.
_BAR_FIGURES = re.compile(r"(.*): allocation (\S+), paid (\S+), remaining (\S+)(?: \(.+\))?")
# The gridline labels (the only classroom text with a dy offset): not figures of any group.
_TICK_TEXT = re.compile(r'<text x="[^"]*" y="[^"]*" dy="[^"]*"[^>]*>[^<]*</text>')
_FIGURE = re.compile(r"-?\$\d{1,3}(?:,\d{3})*")


def _classroom_inputs(
    tmp_path: Path,
    document: dict[str, Any] | None = None,
    *,
    rows: Sequence[Sequence[str]] | None = None,
    **kwargs: Any,
) -> RunInputs:
    """The fictional classroom world through the production facts path (no adjustments)."""
    grid = list(rows or CLASSROOM_LEDGER_ROWS)
    return _inputs(
        tmp_path,
        adjusted=False,
        planning=document if document is not None else classroom_planning_document(rows=grid),
        planning_tabs={CLASSROOM_LEDGER_TAB: grid},
        bundle=kwargs.pop("bundle", classroom_bundle()),
        **kwargs,
    )


@pytest.fixture(scope="module")
def classroom_rendered(tmp_path_factory: pytest.TempPathFactory) -> RenderedSet:
    """One rendered set of the fictional classroom world (stand-in exporter, no browser)."""
    inputs = _classroom_inputs(tmp_path_factory.mktemp("classroom-set"))
    return RenderedSet(inputs, inputs.write())


def _teacher_labels(html: str) -> list[list[str]]:
    return [unescape(re.sub(r"<[^>]+>", " ", label)).split() for label in _TEACHER.findall(html)]


def _figure(text: str) -> int | None:
    """A printed whole-dollar figure as an integer (``None`` for Unknown or the dash)."""
    if text in (render._UNKNOWN, render._DASH):
        return None
    assert _FIGURE.fullmatch(text), text
    return int(text.replace("$", "").replace(",", ""))


def _refuse(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("a classroom print site rounded cents on its own")


def test_classroom_budgets_follow_the_facts(classroom_rendered: RenderedSet) -> None:
    data = classroom_rendered.facts.classroom
    assert data is not None and data.status == "partial"
    html = classroom_rendered.html(CLASSROOM_HTML)
    text = _text(html)
    # One identity with every other page of the set.
    assert f'<meta name="pta-run-id" content="{RUN_ID}">' in html
    assert text.count(RUN_ID) == 1
    assert f"<title>Classroom Budgets · {SCHOOL_LABEL}</title>" in html
    scope = _text("<body>" + html.split('<p class="scope">')[1].split("</p>")[0])
    assert scope.startswith(f"{SCHOOL_LABEL} · {SCHOOL_RANGE} · through August 15, 2030 · FY2031")
    assert "enrollment times the per-student rate beside posted academic-ledger payments" in scope
    # Tiles: whole dollars tied to their totals (assigned $380 + unassigned $16 = paid $396).
    assert _tiles(html) == [
        ("", "", "$700", "Allocated to classrooms", "4 classrooms allocated"),
        ("spent", "", "$396", "Paid (posted)", "$16 unassigned"),
        ("amount", "partial", "$320", "Remaining", "Net of 1 classroom $30 over budget"),
        ("open", "", "$12", "Issued, not yet matched", "1 request; not counted as paid"),
    ]
    # Every roster classroom has a bar (none hidden), plus the unassigned payments.
    titles = [unescape(title) for title in _CLASSBAR.findall(html)]
    assert len(titles) == len(data.classes) + 1 == 6
    assert titles[2] == "Example Teacher C: allocation $220, paid $250, remaining -$30"
    assert titles[4].startswith("Example Specialist E: allocation Unknown, paid $0")
    assert titles[5] == "Unassigned posted payments: $16"
    # One teacher with two classes gets class-qualified labels.
    labels = _teacher_labels(html)
    assert ["Example", "Teacher", "B", "(class-b)"] in labels
    assert ["Example", "Teacher", "B", "(class-d)"] in labels
    # The over-budget classroom: a signed negative remainder, a red overrun above its
    # allocation line, and never a negative remaining stack.
    values = [(bool(over), unescape(value)) for over, value in _VALUE.findall(html)]
    assert values == [
        (False, "$160"),
        (False, "$120"),
        (True, "-$30"),
        (False, "$70"),
        (False, "–"),
        (False, "$16"),
    ]
    assert sum(int(v.replace("$", "").replace(",", "")) for _, v in values[:4]) == 320
    assert html.count(f'fill="{render._STOP}"/>') == 1
    assert html.count('class="allocation-line"') == 1
    # The unassigned bar carries its posted amount, never a remaining figure (D51).
    assert (
        "the figure above each classroom bar is what remains. The unassigned bar shows posted "
        "payments not yet assigned to a classroom; its figure is that posted amount."
    ) in text
    (desc,) = re.findall(r'<desc id="classchart-desc">([^<]*)</desc>', html)
    assert "The figure above each classroom bar is the amount remaining" in desc
    assert "its figure is that posted amount, with no remaining figure." in desc
    # The template draws with render's own layout constants and palette (no copies).
    assert f'font-size="{render._num(render._VALUE_FONT)}"' in html
    assert f'font-size="{render._num(render._AXIS_FONT)}"' in html
    swatches = re.findall(r'class="swatch" style="background:(#[0-9a-f]{6})"', html)
    assert swatches == [render._SEA, render._SUN, render._STOP, render._INK_3]
    assert 'height="-' not in html
    # Larger purchases: paid, dated review items of the posted, linked payment only.
    rows = _texts(_body(_tables(html)["purchases"]))
    assert rows == [
        ["Fictional classroom materials", "Jun 28", "Example Teacher A", "$25"],
        ["Fictional classroom materials", "Jul 2", "Example Teacher A", "$20"],
        ["Itemized purchases on posted payments", "$45"],
    ]
    narrative = _text("<body>" + html.split('<section class="narrative">')[1])
    assert "4 classrooms have allocations totaling $700." in narrative
    assert "They are $200 above the adopted classroom budget of $500" in narrative
    assert "spending through Aug 15 is $396: $380 assigned and $16 not yet assigned" in narrative
    # $16 is not yet assigned, so the over-budget count and the remaining figures are partial
    # (rule 9): the count is "so far", the legend's remaining swatch says so and so does the
    # chart's description.
    assert "1 classroom is over budget so far." in narrative and "$12 is issued" in narrative
    assert _LEGEND.findall(html)[1] == render._REMAINING_LEGEND_PARTIAL
    assert text.count(render._REMAINING_PARTIAL) == 1 and render._REMAINING_PARTIAL in desc
    footer = _text("<body>" + html.split('<footer class="foot">')[1])
    assert footer.startswith(
        "Sources: Board-planning roster and academic-ledger capture and the reimbursement queue "
        "as of August 15, 2030 · Academic ledger coverage Jun 1, 2030 to Aug 31, 2030"
    )
    # The shared audit line (counts, never lists) carries the classroom counts too.
    audit = _audit_text(html)
    assert audit.startswith("Audit detail: Adjustments applied ")
    findings = sum(item.count for item in data.findings)
    assert (
        "Classroom payment rows 5 (fully assigned 4) · Classroom rows left out 2 · "
        f"Classroom findings {findings}. Listed in records/facts.json"
    ) in audit
    assert "Fictional Person" not in text and "Example Payee" not in text
    assert not re.search(r"\$[\d,]+\.\d", text)  # whole dollars; cents stay in the records
    assert text.count("– Unknown or no allocation recorded, never zero.") == 1
    # The index and pointer link the classroom triplet like every other summary.
    index = classroom_rendered.html(INDEX_HTML)
    assert "The six reports" in _text(index)
    for suffix in ("html", "pdf", "png"):
        assert f'href="{CLASSROOM}.{suffix}"' in index
    assert "Board planning input" in _text(index) and "Board planning academic ledger" in _text(
        index
    )


def test_classroom_amounts_trace_to_the_facts(classroom_rendered: RenderedSet) -> None:
    data = classroom_rendered.facts.classroom
    assert data is not None
    text = _text(classroom_rendered.html(CLASSROOM_HTML))
    # The fictional cents are whole dollars except 15.50, so here every printed figure is
    # also its own rounded fact; cents that force rounding choices are covered by
    # test_every_printed_classroom_figure_ties_to_its_group.
    shown = set(_FIGURE.findall(text))
    values = {
        data.allocation_total,
        data.source_total,
        data.assigned_total,
        data.unassigned_total,
        data.remaining_total,
        data.issued_total,
        data.classroom_budget,
        data.allocation_difference,
        sum((p.amount for p in data.purchases), Decimal("0.00")),
        *(p.amount for p in data.purchases),
        *(row.allocation for row in data.classes),
        *(row.paid for row in data.classes),
        *(row.remainder for row in data.classes),
    }
    pool = {format_whole(v) for v in values if v is not None}
    pool |= {format_whole(Decimal(tick)) for tick in ("0", "100", "200", "300")}  # gridlines
    assert shown and shown <= pool, sorted(shown - pool)


@pytest.mark.parametrize(
    "figures",
    [
        pytest.param(CLASSROOM_ROUNDING_FIGURES, id="rounding"),
        *(
            pytest.param(generated_classroom_figures(seed), id=f"generated-{seed}")
            for seed in range(4)
        ),
    ],
)
def test_every_printed_classroom_figure_ties_to_its_group(
    classroom_rendered: RenderedSet, tmp_path: Path, figures: dict[str, Any]
) -> None:
    """Rule 11 / D51 on the published page itself, over chosen and generated cents: each
    group's printed parts add to its printed total (the bar labels to Remaining), each
    derived figure is the difference of the printed figures it comes from, and no printed
    remaining has the opposite sign of its over-budget marker."""
    inputs = classroom_rendered.inputs
    assert inputs.facts.classroom is not None
    data = classroom_figures(inputs.facts.classroom, **figures)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rerun = dataclasses.replace(inputs, run_dir=run_dir)
    rerun.write(facts=dataclasses.replace(inputs.facts, classroom=data))
    html = (run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    tiles = {label: (value, note) for _, _, value, label, note in _tiles(html)}
    allocated = _figure(tiles[render._ALLOCATED_TILE][0])
    paid_total = _figure(tiles[render._PAID_TILE][0])
    remaining_total = _figure(tiles[render._REMAINING_TILE][0])
    issued = _figure(tiles[render._ISSUED_TILE][0])
    unassigned = _figure(tiles[render._PAID_TILE][1].removesuffix(" unassigned"))
    assert None not in (allocated, paid_total, remaining_total, issued, unassigned)
    # The kept totals are the correctly rounded cents.
    assert tiles[render._ALLOCATED_TILE][0] == format_whole(data.allocation_total)
    assert tiles[render._PAID_TILE][0] == format_whole(data.source_total)
    assert tiles[render._ISSUED_TILE][0] == format_whole(data.issued_total)

    # Each classroom bar: the figure above it is the remaining in its tooltip, agreeing in
    # sign with its cents remainder and its marker, and within $1 of allocation - paid.
    titles = [unescape(title) for title in _CLASSBAR.findall(html)]
    labels = [(bool(over), unescape(value)) for over, value in _VALUE.findall(html)]
    bars = [_BAR_FIGURES.fullmatch(title) for title in titles[: len(data.classes)]]
    rows = []
    for match, (over, label), row in zip(
        bars, labels[: len(data.classes)], data.classes, strict=True
    ):
        assert match is not None and match[1] == row.label
        allocation, paid, remaining = (_figure(match[i]) for i in (2, 3, 4))
        assert _figure(label) == remaining and over is row.over_budget
        if remaining is not None:
            assert allocation is not None and paid is not None and row.remainder is not None
            assert abs(allocation - paid - remaining) <= 1
            assert (remaining < 0) <= row.over_budget and (remaining > 0) <= (not over)
            assert remaining == 0 or (remaining < 0) is (row.remainder < 0)
        rows.append((allocation, paid, remaining))
    assert sum(a for a, _, _ in rows if a is not None) == allocated
    class_paid = sum(p for _, p, _ in rows if p is not None)
    assert class_paid + unassigned == paid_total
    remainders = [r for _, _, r in rows if r is not None]
    assert sum(remainders) == remaining_total
    # The unassigned bar is labelled as unassigned posted payments, with that same figure.
    assert unassigned is not None
    shown_unassigned = render._dollars(unassigned)
    if data.unassigned_total != 0:
        assert titles[-1] == f"Unassigned posted payments: {shown_unassigned}"
        assert labels[-1] == (False, shown_unassigned)
    assert len(titles) == len(data.classes) + (data.unassigned_total != 0)
    over_note = tiles[render._REMAINING_TILE][1]
    overrun = -sum(r for r in remainders if r < 0)
    # The fictional world keeps a payment unassigned, so its remaining figures are partial
    # and "none over budget" is never claimed as definitive (rule 9).
    assert "payments_unassigned" in data.reasons
    if data.over_budget:
        expected = f" {render._dollars(overrun)}" if overrun > 0 else ""
        count = len(data.over_budget)
        assert over_note == (
            f"Net of {count} classroom{'' if count == 1 else 's'}{expected} over budget"
        )
    else:
        assert over_note == "None over budget so far" and overrun == 0

    # The narrative prints the same integers; its difference is allocated - budget.
    narrative = _text("<body>" + html.split('<section class="narrative">')[1])
    (total,) = re.findall(r"allocations totaling (\$[\d,]+)\.", narrative)
    assert _figure(total) == allocated
    ((gap_text, side, budget_text),) = re.findall(
        r"They (?:are (\$[\d,]+|less than \$1) (above|below)|equal) the adopted classroom "
        r"budget of (\$[\d,]+)",
        narrative,
    )
    gap = 0 if gap_text in ("", "less than $1") else _figure(gap_text)
    budget = _figure(budget_text)
    assert gap is not None and budget is not None and allocated is not None
    assert allocated - budget == (-gap if side == "below" else gap)
    assert budget_text == format_whole(data.classroom_budget)
    (posted,) = re.findall(
        r"is (\$[\d,]+): (\$[\d,]+) assigned and (\$[\d,]+) not yet assigned", narrative
    )
    assert [_figure(value) for value in posted] == [paid_total, class_paid, unassigned]
    (issued_text,) = re.findall(r"(\$[\d,]+) is issued", narrative)
    assert _figure(issued_text) == issued

    # Purchases: the listed rows plus the exact Other row add to the printed total.
    table = _texts(_body(_tables(html)["purchases"]))
    *listed, (other_text, other), (_, purchase_total) = table
    assert other_text == f"Other itemized purchases ({len(data.purchases) - len(listed)})"
    amounts = [_figure(row[-1]) for row in listed] + [_figure(other)]
    assert all(amount is not None for amount in amounts)
    assert sum(a for a in amounts if a is not None) == _figure(purchase_total)


@pytest.mark.parametrize(
    ("case", "title", "tile"),
    [
        (
            "over",
            "allocation $101, paid $100, remaining $0",
            ("$149", "Net of 1 classroom over budget"),
        ),
        ("under", "allocation $100, paid $101, remaining $0", ("$150", "None over budget so far")),
    ],
)
def test_a_printed_remaining_agrees_with_its_over_budget_marker(
    classroom_rendered: RenderedSet, tmp_path: Path, case: str, title: str, tile: tuple[str, str]
) -> None:
    """Round 5's two cases on the published page: allocation less paid in displayed dollars
    would read +$1 beside the over-budget marker ("over") or -$1 with no marker and no
    classroom over budget ("under"); the printed remaining is $0 and the tile agrees. Both
    worlds keep an unassigned payment, so the wording is "so far" (rule 9; the definitive
    wording of complete figures is test_definitive_classroom_wording_needs_complete_figures).
    """
    inputs = classroom_rendered.inputs
    assert inputs.facts.classroom is not None
    data = classroom_figures(inputs.facts.classroom, **CLASSROOM_SIGN_FIGURES[case])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rerun = dataclasses.replace(inputs, run_dir=run_dir)
    rerun.write(facts=dataclasses.replace(inputs.facts, classroom=data))
    html = (run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    first = data.classes[0]
    assert unescape(_CLASSBAR.findall(html)[0]) == f"{first.label}: {title}"
    values = [(bool(over), unescape(value)) for over, value in _VALUE.findall(html)]
    assert values[0] == (case == "over", "$0")
    assert sum(_figure(value) or 0 for _, value in values[: len(data.classes)]) == int(
        tile[0].removeprefix("$")
    )
    tiles = {label: (value, note) for _, _, value, label, note in _tiles(html)}
    assert tiles[render._REMAINING_TILE] == tile
    narrative = _text("<body>" + html.split('<section class="narrative">')[1])
    assert ("1 classroom is over budget so far." in narrative) is (case == "over")
    assert "over budget." not in narrative.replace("over budget so far.", "")


# The fictional ledger without its one reference-less row: every payment is assigned, so
# the classroom facts are complete.
_COMPLETE_ROWS = [row for row in CLASSROOM_LEDGER_ROWS if row is not CLASSROOM_NO_REFERENCE]


def _classroom_page(inputs: RunInputs) -> tuple[str, str, dict[str, tuple[str, str, str]]]:
    """(page text, narrative, tile label -> (classes, value, note)) of a written world."""
    inputs.write()
    html = (inputs.run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    narrative = _text("<body>" + html.split('<section class="narrative">')[1])
    tiles = {label: (classes, value, note) for _, classes, value, label, note in _tiles(html)}
    return _text(html), narrative, tiles


def test_definitive_classroom_wording_needs_complete_figures(tmp_path: Path) -> None:
    """Complete facts state the allocation difference, the over-budget count and "no
    classroom over budget" definitively, with no partial mark (the counterpart of the
    rule-9 cases below)."""
    inputs = _classroom_inputs(
        tmp_path / "world", classroom_planning_document(rows=_COMPLETE_ROWS), rows=_COMPLETE_ROWS
    )
    data = inputs.facts.classroom
    assert data is not None and (data.status, data.reasons) == ("complete", ())
    text, narrative, tiles = _classroom_page(inputs)
    assert all(classes == "" for classes, _, _ in tiles.values())
    assert tiles[render._REMAINING_TILE][2] == "Net of 1 classroom $30 over budget"
    assert "4 classrooms have allocations totaling $700. They are $200 above the adopted " in (
        narrative
    )
    assert "spending through Aug 15 is $380: $380 assigned and $0 not yet assigned." in narrative
    assert "1 classroom is over budget." in narrative and "so far" not in narrative
    assert render._REMAINING_PARTIAL not in text and "Remaining allocation" in text
    assert render._REMAINING_LEGEND_PARTIAL not in text
    # Complete figures with no classroom over budget: the definitive "none" wording.
    under = classroom_figures(data, **{**CLASSROOM_SIGN_FIGURES["under"], "unassigned": "0.00"})
    assert under.reasons == () and not under.over_budget
    run_dir = tmp_path / "under"
    run_dir.mkdir()
    rerun = dataclasses.replace(inputs, run_dir=run_dir)
    rerun.write(facts=dataclasses.replace(inputs.facts, classroom=under))
    html = (run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    tiles = {label: (classes, value, note) for _, classes, value, label, note in _tiles(html)}
    assert tiles[render._REMAINING_TILE] == ("", "$150", "No classroom over budget")
    assert "over budget" not in _text("<body>" + html.split('<section class="narrative">')[1])


@pytest.mark.parametrize(
    ("case", "sentence", "over"),
    [
        (
            "rates",
            "Allocations recorded so far total $300 for 2 of 4 eligible classrooms, so no "
            "difference from the adopted budget is stated yet.",
            "None over budget so far",
        ),
        (
            "roster",
            "Allocations recorded so far total $700 for 4 of 4 eligible classrooms (the roster "
            "is incomplete), so no difference from the adopted budget is stated yet.",
            "Net of 1 classroom $30 over budget",
        ),
    ],
    ids=["rates", "roster"],
)
def test_a_partial_allocation_total_states_no_difference_from_the_budget(
    tmp_path: Path, case: str, sentence: str, over: str
) -> None:
    """Rule 9: classrooms without enrollment or a rate, or an incomplete roster, leave the
    allocation total a partial observed subtotal: it is shown (starred) as recorded so far
    and no difference from the adopted budget is stated; the remaining figures resting on
    it are starred, the chart's legend and description say they are partial and the
    over-budget count is "so far"."""
    document = classroom_planning_document(rows=_COMPLETE_ROWS, roster_complete=case != "roster")
    if case == "rates":
        document["classes"][1]["student_count"] = None
        document["classes"][2]["per_student_amount"] = None
    inputs = _classroom_inputs(tmp_path, document, rows=_COMPLETE_ROWS)
    data = inputs.facts.classroom
    assert data is not None and data.classroom_budget == Decimal("500.00")
    text, narrative, tiles = _classroom_page(inputs)
    assert narrative.split(" Posted classroom spending")[0] == f"Where things stand {sentence}"
    assert "adopted classroom budget of" not in narrative
    assert not re.search(r"\b(?:above|below|equal)\b", narrative)
    assert tiles[render._ALLOCATED_TILE][0] == "partial"
    assert tiles[render._REMAINING_TILE][0] == "partial"
    assert tiles[render._REMAINING_TILE][2] == over
    assert render._REMAINING_LEGEND_PARTIAL in text and render._REMAINING_PARTIAL in text
    if case == "roster":
        assert "1 classroom is over budget so far." in narrative
    # Posted spending is complete here: neither its tile nor its sentence is partial.
    assert tiles[render._PAID_TILE][0] == "" and "so far:" not in narrative


def test_partial_ledger_coverage_marks_paid_purchases_and_remaining_partial(
    tmp_path: Path,
) -> None:
    """Rule 9: a ledger whose declared coverage stops before the as-of date leaves the
    posted total, the purchases on posted payments and the remaining figures partial."""
    document = classroom_planning_document(rows=_COMPLETE_ROWS)
    document["bindings"][0]["coverage_end"] = "2030-07-31"
    inputs = _classroom_inputs(tmp_path, document, rows=_COMPLETE_ROWS)
    data = inputs.facts.classroom
    assert data is not None and data.reasons == ("ledger_coverage_partial",)
    text, narrative, tiles = _classroom_page(inputs)
    html = (inputs.run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    assert (
        "Posted classroom spending through Aug 15 is $380 so far: $380 assigned and $0 not yet "
        "assigned."
    ) in narrative
    assert tiles[render._PAID_TILE][0] == tiles[render._REMAINING_TILE][0] == "partial"
    assert tiles[render._ALLOCATED_TILE][0] == ""
    assert "They are $200 above the adopted classroom budget of $500" in narrative
    assert "1 classroom is over budget so far." in narrative
    *_, total = _body(_tables(html)["purchases"])
    assert total[0].text == "Itemized purchases on posted payments"
    assert "partial" in total[-1].classes
    assert render._REMAINING_LEGEND_PARTIAL in text and render._REMAINING_PARTIAL in text
    # Why it is partial: the footer's coverage clause.
    assert "Academic ledger coverage Jun 1, 2030 to Jul 31, 2030; partial for the period" in text


@pytest.mark.parametrize(
    ("case", "paid_note", "issued", "because"),
    [
        ("ledger", "No academic ledger bound", "$57", "no academic ledger is bound"),
        (
            "category",
            "No classroom category declared",
            "Unknown",
            "no classroom spending category is declared",
        ),
    ],
    ids=["ledger", "category"],
)
def test_unknown_spending_is_never_stated_as_zero_or_none_over_budget(
    tmp_path: Path, case: str, paid_note: str, issued: str, because: str
) -> None:
    """Rule 9: without a ledger, or without a declared classroom category, posted spending
    is unknown: Paid and Remaining read Unknown (never $0), the Remaining tile claims
    nothing about over-budget classrooms, and without a category no request can be a
    classroom request, so Issued is unknown too."""
    document = classroom_planning_document()
    if case == "ledger":
        document["bindings"] = []
    else:
        document["classroom_categories"] = []
    inputs = _classroom_inputs(tmp_path, document)
    text, narrative, tiles = _classroom_page(inputs)
    assert tiles[render._PAID_TILE][1:] == ("Unknown", paid_note)
    assert tiles[render._REMAINING_TILE][1:] == (
        "Unknown",
        "Needs allocations and posted payments",
    )
    assert tiles[render._ISSUED_TILE][1] == issued
    if case == "category":
        assert tiles[render._ISSUED_TILE][2] == "No classroom category declared"
    assert f"Posted spending is unknown: {because}." in narrative
    assert "over budget" not in narrative and render._REMAINING_PARTIAL not in text
    # The allocations are still complete, so they stand with their stated basis.
    assert "4 classrooms have allocations totaling $700." in narrative


def test_classroom_print_sites_read_only_the_display_figures(
    classroom_rendered: RenderedSet, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No classroom print site rounds (or recomputes) a figure: given display figures that
    no cents of the facts round to, the page prints exactly those, gridlines aside."""
    world = classroom_rendered.facts
    assert world.classroom is not None
    # Two more purchases than the page lists, so the exact Other row's print site is read too.
    template = world.classroom.purchases[0]
    extra = render._PURCHASE_ROWS + 2 - len(world.classroom.purchases)
    report = dataclasses.replace(
        world,
        classroom=dataclasses.replace(
            world.classroom,
            purchases=world.classroom.purchases
            + tuple(
                dataclasses.replace(template, amount=Decimal("1.00"), item_key=f"other:{index}")
                for index in range(extra)
            ),
        ),
    )
    assert report.classroom is not None
    real = planning.classroom_display(report.classroom, listed=render._PURCHASE_ROWS)
    # Deliberately untied, so a site that re-derives a figure is caught as well.
    fake = dataclasses.replace(
        real,
        classes=tuple(
            dataclasses.replace(
                row,
                allocation=None if row.allocation is None else 1101 + index,
                paid=None if row.paid is None else 2201 + index,
                remaining=None if row.remaining is None else 3301 + index,
            )
            for index, row in enumerate(real.classes)
        ),
        allocation_total=4401,
        classroom_budget=4402,
        allocation_difference=4403,
        paid_total=4404,
        assigned_total=4405,
        unassigned_total=4406,
        remaining_total=4407,
        overrun=4408,
        purchases=tuple(4409 + index for index in range(len(real.purchases))),
        other=4419,
        purchase_total=4420,
        issued_total=4421,
    )
    assert real.other is not None and len(real.purchases) == render._PURCHASE_ROWS
    monkeypatch.setattr(planning, "classroom_display", lambda classroom, *, listed: fake)
    # With every rounding helper refusing, the summary still builds from the display alone.
    with monkeypatch.context() as refusing:
        for owner, name in [
            (render, "format_whole"),
            (render, "format_money"),
            (render, "_whole"),
            (planning, "half_up"),
            (planning, "display_parts"),
        ]:
            refusing.setattr(owner, name, _refuse)
        assert render._classroom_summary(report)["available"]
    # The published page prints exactly the display's figures, every one of them.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dataclasses.replace(classroom_rendered.inputs, run_dir=run_dir).write(facts=report)
    html = (run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    printed = set(_FIGURE.findall(_text(_TICK_TEXT.sub("", html))))
    figures = [
        *(
            value
            for row in fake.classes
            for value in (row.allocation, row.paid, row.remaining)
            if value is not None
        ),
        *range(4401, 4409),
        *fake.purchases,
        fake.other,
        fake.purchase_total,
        fake.issued_total,
    ]
    assert printed == {render._dollars(value) for value in figures if value is not None}


def test_absent_planning_renders_an_explicit_unavailable_page(rendered: RenderedSet) -> None:
    html = rendered.html(CLASSROOM_HTML)
    text = _text(html)
    assert [tile[2] for tile in _tiles(html)] == ["Unknown"] * 4
    assert "No board-planning input is configured for this run." in text
    assert "no adopted total is divided" in text and 'class="classchart"' not in html
    assert "every other report of this run is unaffected" in text


def test_a_missing_roster_never_divides_the_budget_equally(tmp_path: Path) -> None:
    document = classroom_planning_document(classes=[], allocations=[])
    document["payee_aliases"] = []
    inputs = _classroom_inputs(tmp_path, document)
    inputs.write()
    html = (inputs.run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    text = _text(html)
    tiles = _tiles(html)
    assert tiles[0][2:] == ("Unknown", "Allocated to classrooms", "No roster recorded")
    assert tiles[2][2] == "Unknown"  # no remaining figure without allocations
    assert [unescape(t) for t in _CLASSBAR.findall(html)] == ["Unassigned posted payments: $396"]
    assert "allocations are unavailable and the adopted budget is never divided equally" in text
    assert "No roster is recorded, so no classroom has an allocation." in text


def test_hostile_classroom_labels_are_escaped(tmp_path: Path) -> None:
    document = classroom_planning_document()
    document["classes"][0]["teacher_label"] = HOSTILE
    inputs = _classroom_inputs(tmp_path, document)
    inputs.write()
    html = (inputs.run_dir / CLASSROOM_HTML).read_text(encoding="utf-8")
    assert RAW_MARKER not in html
    assert f"<title>{ESCAPED}: allocation $200" in html


def test_a_roster_beyond_the_page_capacity_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    document = classroom_planning_document(allocations=[])
    template = document["classes"][0]
    document["classes"] = [
        {**template, "class_id": f"class-{index:02d}", "teacher_label": f"Teacher {index:02d}"}
        for index in range(render.CLASSROOM_CAPACITY + 1)
    ]
    document["payee_aliases"] = []
    inputs = _classroom_inputs(tmp_path, document)
    with pytest.raises(RenderError) as caught:
        inputs.write()
    assert caught.value.code == "classroom_layout_overflow"
    _assert_clean_error(caught.value)
    assert list(inputs.run_dir.iterdir()) == []


def test_a_classroom_ledger_this_run_did_not_capture_is_refused(tmp_path: Path) -> None:
    inputs = _classroom_inputs(tmp_path)
    data = inputs.facts.classroom
    assert data is not None and data.ledger_sha256 is not None
    sources = tuple(
        dataclasses.replace(s, sha256="0" * 64) if s.sha256 == data.ledger_sha256 else s
        for s in inputs.context.sources
    )
    error = _expect(
        "context_mismatch", inputs, context=dataclasses.replace(inputs.context, sources=sources)
    )
    assert "0 coverage source(s) and 1 evidence ref(s)" in str(error)
    assert list(inputs.run_dir.iterdir()) == []


def _classroom_fit_inputs(tmp_path: Path, world: str) -> tuple[RunInputs, int]:
    """(inputs, expected bars) of one classroom fit world."""
    if world == "standard":
        return _classroom_inputs(tmp_path), 6
    if world == "missing_roster":
        document = classroom_planning_document(classes=[], allocations=[])
        document["payee_aliases"] = []
        return _classroom_inputs(tmp_path, document), 1
    count = render.CLASSROOM_CAPACITY if world in ("large", "partial") else 3
    rows = [list(row) for row in CLASSROOM_LEDGER_ROWS]
    classes = []
    for index in range(count):
        label = (
            f"Teacher {index:02d}"
            if index % 3 == 0
            else ("W" * 200 if world == "long" else _long_name(f"Example Teacher {index:02d}"))
        )
        classes.append(
            {
                "class_id": f"class-{index:02d}",
                "teacher_label": label,
                "student_count": 20 + index,
                "per_student_amount": "250.00",
                "effective_start": "2030-07-01",
                "effective_end": "2031-06-30",
                "eligible": True,
            }
        )
        amount = (index * 9731) % 9000 + 1000  # some classrooms over their allocation
        rows.append(
            [
                "8/1/2030",
                f"Example order {index}",
                f"-{amount}.25",
                CLASSROOM_CATEGORY,
                "2031",
                f"EX-9{index:03d}",
                f"Example Payee {index:02d}",
            ]
        )
    if world == "partial":
        rows.append(["", "Example undated order", "-7.00", CLASSROOM_CATEGORY, "2031", "EX-8", ""])
    document = classroom_planning_document(
        classes=classes, rows=rows, allocations=[], roster_complete=world != "partial"
    )
    document["payee_aliases"] = [
        {"source_payee": f"Example Payee {index:02d}", "class_id": f"class-{index:02d}"}
        for index in range(count)
    ]
    if world == "partial":
        # Every rule-9 wording at once on the largest roster: a partial allocation total, a
        # posted total "so far" (an undated row) and partial remaining figures.
        document["classes"][1]["student_count"] = None
        document["classes"][2]["per_student_amount"] = None
    return _classroom_inputs(tmp_path, document, rows=rows), count + 1


@pytest.mark.parametrize("world", ["standard", "large", "long", "missing_roster", "partial"])
def test_chromium_classroom_page_fits_one_readable_letter_page(tmp_path: Path, world: str) -> None:
    playwright = require_chromium()
    inputs, bars = _classroom_fit_inputs(tmp_path, world)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnsandboxedExportWarning)
        inputs.write(exporter=None)
    data = inputs.facts.classroom
    assert data is not None and data.status != "unavailable"
    if world in ("large", "partial"):
        assert len(data.classes) == render.CLASSROOM_CAPACITY and data.over_budget
    if world == "partial":
        assert {
            "roster_incomplete",
            "allocation_missing",
            "payments_unassigned",
            "rows_unreadable",
        } <= set(data.reasons)
    uri = (inputs.run_dir / CLASSROOM_HTML).as_uri()
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chromium")
        page = browser.new_page(viewport={"width": 1100, "height": 1200})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(uri)
        screen = page.evaluate(_SCREEN_CHECK)
        assert screen["scroll"] <= screen["inner"]
        assert screen["problems"] == [], screen["problems"][:5]
        # No teacher row is hidden: one drawn bar group and one axis label per bar, every
        # label inside the chart.
        drawn = page.evaluate(
            """() => {
              const svg = document.querySelector('svg.classchart').getBoundingClientRect();
              const labels = [...document.querySelectorAll('svg.classchart text.teacher')]
                .map(t => t.getBoundingClientRect());
              return {
                groups: document.querySelectorAll('svg.classchart g.classbar').length,
                labels: labels.length,
                outside: labels.filter(r => r.left < svg.left - 0.5 || r.right > svg.right + 0.5
                  || r.top < svg.top - 0.5 || r.bottom > svg.bottom + 0.5).length,
                width: Math.min(...labels.map(r => Math.max(r.width, r.height))),
              };
            }"""
        )
        assert drawn["groups"] == drawn["labels"] == bars
        assert drawn["outside"] == 0 and drawn["width"] > 10
        page.set_viewport_size({"width": 730, "height": 1000})
        page.emulate_media(media="print")
        page.goto(uri)
        fit = page.evaluate(_PRINT_CHECK)
        assert fit["height"] <= FIT_LIMIT - FIT_RESERVE, fit["height"]
        assert fit["row"] <= 38 and fit["eyebrow"] <= 16
        assert fit["narrative"] <= 4.2 * fit["line"] + 16
        page.emulate_media(media="screen")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(uri)
        phone = page.evaluate(_PHONE_CHECK)
        assert phone["overflow"] <= 1 and phone["tops"] == 2 and phone["pad"] >= 16
        browser.close()
    assert not errors
    payload = (inputs.run_dir / f"{CLASSROOM}.pdf").read_bytes()
    assert _pdf_sizes(payload) == [(612, 792)]
    flat = " ".join(fit["text"].split())
    assert "Classroom Budgets" in flat and RUN_ID in flat and "1 page" in flat
    texts = _pdf_texts(payload)
    if texts is not None:  # extra: the printed PDF text itself
        assert "Classroom Budgets" in texts[0] and "Where things stand" in texts[0]
