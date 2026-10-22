"""Shared test fixtures — fake-org config + a fake gspread layer (no live Google calls).

Identity here is obviously-fake placeholders only (``Example PTA`` etc.). NOTHING in
these fixtures touches the network: a ``FakeWorksheet`` / ``FakeSpreadsheet`` / ``FakeClient``
stand in for the gspread objects, and :class:`~pta_finance.sheets.SheetsClient` is always
constructed with ``gspread_client=`` so :func:`gspread.service_account` is never called.
The fictional Main Report Set scenario (:class:`Scenario`: CFO source shapes, adopted budget,
crosswalk and a schema-v2 reimbursement bundle, driven through capture, reconciliation,
recorded adjustments and facts) is shared by the facts and render tests.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from gspread.exceptions import APIError
from gspread.utils import a1_to_rowcol
from requests.models import Response

from pta_finance import reimbursement_report, report_source
from pta_finance.config import Config, load_config
from pta_finance.main_reports import reconcile
from pta_finance.main_reports.adjustments import acquire_run_lock, project, read_journal, record
from pta_finance.main_reports.facts import build, build_from, reporting_periods
from pta_finance.main_reports.models import (
    AdjustedLedger,
    Adjustment,
    CaptureSet,
    ReportFacts,
    Transaction,
    make_adjustment_id,
)
from pta_finance.main_reports.sources import ReadOnlyWorkbook, capture, connect_source_client
from pta_finance.reimbursement_report import ReimbursementReport
from pta_finance.sheets import SheetsClient

_FULL_CONFIG = """\
[organization]
name = "Example PTA"
school_name = "Example Elementary"
school_email = "office@example.org"

[contacts]
president = ["president@example.org"]
treasurer = "treasurer@example.org"
cfo = "cfo@example.org"
account_holders = ["president@example.org", "treasurer@example.org"]

[fiscal_year]
start_month = 1

[grades]
labels = ["K", "1", "2", "3", "4", "5"]

[sheets]
spreadsheet_id = "fake-spreadsheet-id"
test_spreadsheet_id = "fake-test-sheet-id"
drive_receipts_folder_id = "fake-receipts-folder-id"
drive_reports_folder_id = "fake-reports-folder-id"

[google]
service_account_file = "secrets/service-account.json"
"""


def tagged_user_entered_grid(
    grid: Iterable[Iterable[object]],
) -> list[list[dict[str, object]]]:
    """Tag fake grid cells using the Sheets ``userEnteredValue`` vocabulary."""

    def _tag(value: object) -> dict[str, object]:
        if value is None or value == "":
            return {"userEnteredValue": None}
        if isinstance(value, bool):
            return {"userEnteredValue": {"boolValue": value}}
        if isinstance(value, (int, float)):
            return {"userEnteredValue": {"numberValue": value}}
        if isinstance(value, str) and value.startswith("="):
            return {"userEnteredValue": {"formulaValue": value}}
        return {"userEnteredValue": {"stringValue": str(value)}}

    return [[_tag(value) for value in row] for row in grid]


@pytest.fixture
def fake_config(tmp_path: Path) -> Config:
    """A loaded :class:`Config` with fake placeholder identity."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG, encoding="utf-8")
    return load_config(cfg_path)


def _a1_start_row(range_name: str) -> int:
    """Parse the 1-based start row from an A1 range like ``A1:O1`` -> ``1``."""
    start = range_name.split(":", 1)[0]
    digits = "".join(ch for ch in start if ch.isdigit())
    return int(digits) if digits else 1


def make_api_error(
    status: int,
    *,
    message: str = "rate limited",
    api_status: str = "RESOURCE_EXHAUSTED",
) -> APIError:
    """Build a real :class:`gspread.exceptions.APIError` with the given HTTP status.

    Constructs a minimal ``requests.Response`` carrying ``status_code`` and a JSON error
    body so ``APIError`` parses it the same way a live 429 would — exercising the
    production ``_status_of`` path, not a stubbed status. ``message``/``api_status`` let a
    test reproduce a specific rejection (e.g. a 400 duplicate-title error) verbatim.
    """
    response = Response()
    response.status_code = status
    body = {"error": {"code": status, "message": message, "status": api_status}}
    response._content = json.dumps(body).encode("utf-8")
    return APIError(response)


class FakeWorksheet:
    """A stand-in for ``gspread.Worksheet`` recording the calls a test cares about.

    ``grid`` is the current sheet contents as a list of rows (list[str]); row 0 is the
    header. ``batch_update`` / ``append_rows`` / ``delete_rows`` mutate ``grid`` and log
    their args. Any method can be made to raise on its first N calls via ``fail_first``
    to simulate a transient 429.
    """

    def __init__(
        self,
        grid: list[list[str]] | None = None,
        *,
        title: str = "",
        fail_first: MutableMapping[str, list[BaseException]] | None = None,
    ) -> None:
        self.grid: list[list[str]] = grid if grid is not None else []
        self.title = title
        self.batch_update_calls: list[list[dict[str, Any]]] = []
        # value_input_option recorded per batch_update / append_rows call (None = gspread default).
        self.batch_update_vios: list[str | None] = []
        self.append_rows_vios: list[str | None] = []
        self.append_rows_calls: list[list[list[str]]] = []
        self.delete_rows_calls: list[int] = []
        self.update_calls: list[tuple[str, list[list[str]]]] = []
        # value_input_option recorded per update call (None = gspread default).
        self.update_vios: list[Any] = []
        # method-name -> list of exceptions to raise (one per leading call), then succeed.
        self._fail_first: MutableMapping[str, list[BaseException]] = dict(fail_first or {})

    def _maybe_fail(self, method: str) -> None:
        queue = self._fail_first.get(method)
        if queue:
            raise queue.pop(0)

    # --- reads --------------------------------------------------------------

    def row_values(self, row: int) -> list[str]:
        self._maybe_fail("row_values")
        if 1 <= row <= len(self.grid):
            return list(self.grid[row - 1])
        return []

    def col_values(self, col: int) -> list[str]:
        self._maybe_fail("col_values")
        return [r[col - 1] if col - 1 < len(r) else "" for r in self.grid]

    def get_all_records(self) -> list[dict[str, Any]]:
        self._maybe_fail("get_all_records")
        if not self.grid:
            return []
        header = self.grid[0]
        return [dict(zip(header, row, strict=False)) for row in self.grid[1:]]

    def get_all_values(self, *, value_render_option: Any = None) -> list[list[str]]:
        self._maybe_fail("get_all_values")
        return [list(row) for row in self.grid]

    # --- writes -------------------------------------------------------------

    def batch_update(
        self, data: Iterable[Mapping[str, Any]], value_input_option: str | None = None
    ) -> dict[str, Any]:
        self._maybe_fail("batch_update")
        requests = [dict(req) for req in data]
        self.batch_update_calls.append(requests)
        self.batch_update_vios.append(value_input_option)
        return {"replies": [{} for _ in requests]}

    def append_rows(
        self, values: list[list[str]], value_input_option: str | None = None
    ) -> dict[str, Any]:
        self._maybe_fail("append_rows")
        self.append_rows_calls.append([list(v) for v in values])
        self.append_rows_vios.append(value_input_option)
        self.grid.extend(list(v) for v in values)
        return {}

    def update(
        self,
        values: list[list[str]] | None = None,
        range_name: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Stand-in for gspread v6 ``Worksheet.update`` (``values`` positional, ``range_name`` kw).

        Mirrors the real v6 signature so a future refactor to positional/old-order args is
        CATCHABLE rather than silently accepted: production's contract (see sheets.py) is to
        always pass ``range_name=`` and ``values=`` by name, and this fake rejects a call
        that omits ``range_name`` (the v5-positional shape) so the wrong call would fail
        under test. Records the call and writes the values into ``grid`` starting at the
        range's first row (1-based, parsed from the ``A<row>`` start of ``range_name``).
        """
        self._maybe_fail("update")
        if values is None or range_name is None:
            raise TypeError("update() requires values= and range_name= (v6 named-arg contract)")
        self.update_calls.append((range_name, [list(v) for v in values]))
        self.update_vios.append(kwargs.get("value_input_option"))
        start_row = _a1_start_row(range_name)
        for offset, row in enumerate(values):
            idx = start_row - 1 + offset
            while len(self.grid) <= idx:
                self.grid.append([])
            self.grid[idx] = list(row)
        return {}

    def clear(self) -> dict[str, Any]:
        self._maybe_fail("clear")
        self.grid = []
        return {}

    def delete_rows(self, start: int, end: int | None = None) -> dict[str, Any]:
        self._maybe_fail("delete_rows")
        self.delete_rows_calls.append(start)
        idx = start - 1
        if 0 <= idx < len(self.grid):
            del self.grid[idx]
        return {}


class FakeSpreadsheet:
    """A stand-in for ``gspread.Spreadsheet`` mapping tab name -> FakeWorksheet.

    Tracks insertion order so ``worksheets()`` returns titles in a stable order, and
    records ``add_worksheet`` calls so ``ensure_tab`` tests can assert a tab was created.
    """

    def __init__(
        self,
        worksheets: Mapping[str, FakeWorksheet],
        *,
        add_worksheet_error: BaseException | None = None,
    ) -> None:
        self._worksheets: dict[str, FakeWorksheet] = {}
        for title, ws in worksheets.items():
            if not ws.title:
                ws.title = title
            self._worksheets[title] = ws
        self.add_worksheet_calls: list[tuple[str, int, int]] = []
        self.metadata_params: list[dict[str, Any]] = []
        # When set, add_worksheet inserts the worksheet (the create applied server-side)
        # and THEN raises — simulating a retried-create that already took effect, so the
        # caller's recovery path sees the tab as now-present.
        self._add_worksheet_error = add_worksheet_error

    def worksheet(self, title: str) -> FakeWorksheet:
        return self._worksheets[title]

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self._worksheets.values())

    def fetch_sheet_metadata(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Return tagged user-entered cells for the one absolute worksheet range requested."""
        self.metadata_params.append(dict(params))
        raw_range = str(params["ranges"])
        title = raw_range.split("!", 1)[0]
        if title.startswith("'") and title.endswith("'"):
            title = title[1:-1].replace("''", "'")
        ws = self.worksheet(title)

        return {
            "sheets": [
                {
                    "data": [
                        {"rowData": [{"values": row} for row in tagged_user_entered_grid(ws.grid)]}
                    ]
                }
            ]
        }

    def add_worksheet(self, *, title: str, rows: int, cols: int) -> FakeWorksheet:
        self.add_worksheet_calls.append((title, rows, cols))
        ws = FakeWorksheet([], title=title)
        self._worksheets[title] = ws
        if self._add_worksheet_error is not None:
            raise self._add_worksheet_error
        return ws


class FakeClient:
    """A stand-in for ``gspread.Client`` returning a fixed :class:`FakeSpreadsheet`."""

    def __init__(self, spreadsheet: FakeSpreadsheet) -> None:
        self._spreadsheet = spreadsheet
        self.opened_keys: list[str] = []

    def open_by_key(self, key: str) -> FakeSpreadsheet:
        self.opened_keys.append(key)
        return self._spreadsheet


def require_chromium() -> Any:
    """Skip exactly as the receipt viewer browser test does when Chromium is not installed;
    otherwise return the Playwright sync API module."""
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


class RecordingSleep:
    """A no-op ``sleep`` that records the delays it was asked to wait."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# --------------------------------------------------------------------------------------
# CFO workbook fakes shared by the main_reports test modules
# --------------------------------------------------------------------------------------

MAPPING_HEADER = ["Keyword", "Target Category"]
CFO_ID = "fake-cfo-workbook-id"


BANK_HEADER = [
    "DATE",
    "DESCRIPTION",
    "AMOUNT",
    "CHECK #",
    "STATUS",
    "CATEGORY",
    "OVERRIDE CATEGORY",
    "FINAL CATEGORY",
]


WIX_GROUPS = [
    "Payment",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "Transaction",
    "",
    "",
    "Order",
    "",
    "",
    "",
    "Billing",
    "",
    "Shipping",
    "",
]
WIX_LABELS = [
    "Provider Payment ID",
    "Payment Date",
    "Transaction Date",
    "Time Zone",
    "Currency",
    "Amount",
    "Processing Fee",
    "Service Fee",
    "Net",
    "Status",
    "Refund Amount",
    "Payment Provider",
    "Order ID",
    "Product Name",
    "Quantity",
    "Status",
    "Name",
    "Country",
    "Name",
    "Country",
]


PAYPAL_HEADER = [
    "Date",
    "Time",
    "TimeZone",
    "Name",
    "Type",
    "Status",
    "Currency",
    "Gross",
    "Fee",
    "Net",
    "Transaction ID",
    "Reference Txn ID",
    "Item Title",
    "Quantity",
    "Balance Impact",
]


CARD_HEADER = ["Date", "Description", "Amount"]


BUDGET_GRID = [
    list(report_source.TIMESERIES_COLUMNS),
    ["2030", "Programs", "expense", "proposed", "500", "FALSE", "", "Classroom Supplies", "x"],
    ["2030", "Programs", "expense", "actual", "75.5", "FALSE", "", "Classroom Supplies", "x"],
    ["2030", "Fundraising", "income", "proposed", "1500", "TRUE", "", "Fundraiser Income", "x"],
]
ASSUMPTIONS_GRID = [["Assumption", "Value"], ["Example multiplier", "1.5"], ["Derived", "=B2*2"]]


# --------------------------------------------------------------------------------------
# Fake gspread layer with sheet ids, separate formula grids and changing reads
# --------------------------------------------------------------------------------------


class CfoWorksheet(FakeWorksheet):
    def __init__(
        self,
        grid: list[list[str]],
        *,
        sheet_id: int,
        formulas: list[list[str]] | None = None,
        versions: list[list[list[str]]] | None = None,
    ) -> None:
        super().__init__([list(row) for row in grid])
        self.id = sheet_id
        self.formula_grid = formulas
        self.versions = versions
        self.value_reads = 0

    def get_all_values(self, *, value_render_option: Any = None) -> list[list[str]]:
        self.value_reads += 1
        if self.versions:
            self.grid = self.versions.pop(0) if len(self.versions) > 1 else self.versions[0]
        return super().get_all_values()


class CfoSpreadsheet(FakeSpreadsheet):
    def fetch_sheet_metadata(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self.metadata_params.append(dict(params))
        title = str(params["ranges"]).split("!", 1)[0].strip("'")
        ws = self.worksheet(title)
        grid = getattr(ws, "formula_grid", None) or ws.grid
        rows = tagged_user_entered_grid(grid)
        return {"sheets": [{"data": [{"rowData": [{"values": row} for row in rows]}]}]}


class JournalWorksheet(CfoWorksheet):
    """Our own writable Assumptions tab: batch writes land in the grid like Sheets.

    ``RAW`` writes keep text as text (a value beginning with ``=`` stays a string, never a
    formula); ``entered`` overrides model a cell's typed value (e.g. a number behind a
    formatted display). A write past ``row_count`` / ``col_count`` is rejected with a 400,
    as Sheets does, until ``add_rows`` / ``add_cols`` grow the grid. ``after_batch_update``
    runs after a write lands (to simulate a concurrent edit or a lost response).
    """

    def __init__(
        self,
        grid: list[list[str]],
        *,
        sheet_id: int,
        row_count: int = 1000,
        col_count: int = 26,
        entered: Mapping[tuple[int, int], object] | None = None,
    ) -> None:
        super().__init__(grid, sheet_id=sheet_id)
        self.row_count = row_count
        self.col_count = col_count
        self.entered: dict[tuple[int, int], object] = dict(entered or {})
        self.raw_text: set[tuple[int, int]] = set()
        self.add_rows_calls: list[int] = []
        self.add_cols_calls: list[int] = []
        self.after_batch_update: Callable[[JournalWorksheet], None] | None = None

    def set_cell(self, row: int, column: int, value: str, *, raw: bool = False) -> None:
        """Set a zero-based cell's displayed value (``raw`` keeps formula-like text as text)."""
        while len(self.grid) <= row:
            self.grid.append([])
        line = self.grid[row]
        while len(line) <= column:
            line.append("")
        line[column] = value
        self.entered.pop((row, column), None)
        if raw:
            self.raw_text.add((row, column))
        else:
            self.raw_text.discard((row, column))

    def batch_update(
        self, data: Iterable[Mapping[str, Any]], value_input_option: str | None = None
    ) -> dict[str, Any]:
        self._maybe_fail("batch_update")
        requests = [dict(req) for req in data]
        for request in requests:
            row, column = a1_to_rowcol(str(request["range"]).split(":", 1)[0])
            values = request["values"]
            width = max((len(line) for line in values), default=0)
            if row - 1 + len(values) > self.row_count or column - 1 + width > self.col_count:
                raise make_api_error(
                    400, message="Range exceeds grid limits", api_status="INVALID_ARGUMENT"
                )
        self.batch_update_calls.append(requests)
        self.batch_update_vios.append(value_input_option)
        for request in requests:
            row, column = a1_to_rowcol(str(request["range"]).split(":", 1)[0])
            for row_offset, line in enumerate(request["values"]):
                for column_offset, value in enumerate(line):
                    self.set_cell(
                        row - 1 + row_offset,
                        column - 1 + column_offset,
                        str(value),
                        raw=value_input_option == "RAW",
                    )
        if self.after_batch_update is not None:
            self.after_batch_update(self)
        return {"replies": [{} for _ in requests]}

    def add_rows(self, rows: int) -> None:
        self._maybe_fail("add_rows")
        self.add_rows_calls.append(rows)
        self.row_count += rows

    def add_cols(self, cols: int) -> None:
        self._maybe_fail("add_cols")
        self.add_cols_calls.append(cols)
        self.col_count += cols

    def tagged_grid(self) -> list[list[dict[str, object]]]:
        rows = tagged_user_entered_grid(self.grid)
        for (row, column), value in self.entered.items():
            while len(rows) <= row:
                rows.append([])
            while len(rows[row]) <= column:
                rows[row].append({"userEnteredValue": None})
            rows[row][column] = tagged_user_entered_grid([[value]])[0][0]
        for row, column in self.raw_text:
            text = self.grid[row][column]
            rows[row][column] = {"userEnteredValue": {"stringValue": text} if text else None}
        return rows


class JournalSpreadsheet(CfoSpreadsheet):
    """Our own workbook: a :class:`JournalWorksheet` reports its tagged entered values."""

    def fetch_sheet_metadata(self, params: Mapping[str, Any]) -> dict[str, Any]:
        title = str(params["ranges"]).split("!", 1)[0].strip("'")
        ws = self.worksheet(title)
        if not isinstance(ws, JournalWorksheet):
            return super().fetch_sheet_metadata(params)
        self.metadata_params.append(dict(params))
        rows = ws.tagged_grid()
        return {"sheets": [{"data": [{"rowData": [{"values": row} for row in rows]}]}]}


class TimeoutClient(FakeClient):
    def __init__(self, spreadsheet: FakeSpreadsheet) -> None:
        super().__init__(spreadsheet)
        self.timeouts: list[float] = []

    def set_timeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


def _own_worksheets(assumptions: JournalWorksheet | None = None) -> dict[str, CfoWorksheet]:
    return {
        report_source.BUDGET_TIMESERIES_TAB: CfoWorksheet(BUDGET_GRID, sheet_id=2001),
        "Assumptions": assumptions or JournalWorksheet(ASSUMPTIONS_GRID, sheet_id=2002),
    }


_WIX_STATUS = 'transaction_status = { label = "Status", group = "Transaction" }'


def _source_toml(
    alias: str, kind: str, tab: str, signature: Sequence[Sequence[str]], extra: str = ""
) -> str:
    return (
        f"\n[main_reports.sources.{alias}]\nkind = {json.dumps(kind)}\ntab = {json.dumps(tab)}\n"
        f"header_signature = {json.dumps([list(row) for row in signature])}\n{extra}"
    )


def main_reports_toml(
    *,
    omit: Sequence[str] = (),
    wix_columns: str = _WIX_STATUS,
    bank_extra: str = "",
    bank_signature: Sequence[Sequence[str]] = (BANK_HEADER,),
) -> str:
    parts = {
        "bank-checking": _source_toml(
            "bank-checking",
            "bank",
            "Bank Checking",
            bank_signature,
            'tab_id = 1001\ncoverage = [{ start = "2030-01-01", end = "2030-01-31", '
            'evidence = "example-statement-index" }]\n' + bank_extra,
        ),
        "wix": _source_toml(
            "wix",
            "wix",
            "Store Transactions",
            [WIX_GROUPS, WIX_LABELS],
            'coverage = [{ start = "2030-01-01", end = "2030-12-31", '
            'evidence = "example-export" }]\n'
            + (f"[main_reports.sources.wix.columns]\n{wix_columns}\n" if wix_columns else ""),
        ),
        "paypal": _source_toml("paypal", "paypal", "Processor Transactions", [PAYPAL_HEADER]),
        "pnl": _source_toml("pnl", "pnl", "Profit & Loss", []),
        "budget-tracker": _source_toml("budget-tracker", "budget_tracker", "Budget Tracker", []),
        "category-mapping": _source_toml(
            "category-mapping", "category_mapping", "Category Mapping", [MAPPING_HEADER]
        ),
        "credit-card": _source_toml(
            "credit-card", "credit_card", "Credit Card Transactions", [CARD_HEADER]
        ),
    }
    body = "".join(text for alias, text in parts.items() if alias not in omit)
    return (
        "\n[main_reports]\n"
        f'source_spreadsheet_id = "{CFO_ID}"\n'
        'output_dir = "reports/output/main-report-runs"\n' + body
    )


def _clock() -> Callable[[], datetime]:
    counter = itertools.count()
    start = datetime(2030, 2, 1, 12, 0, tzinfo=UTC)
    return lambda: start + timedelta(seconds=next(counter))


class CfoHarness:
    """A loaded config plus fake CFO and own workbooks; :meth:`capture` runs the production
    read-only capture against them and :meth:`assert_no_writes` proves nothing was written.
    Our own Assumptions tab is a writable :class:`JournalWorksheet` (``assumptions``).
    """

    def __init__(
        self,
        config: Config,
        cfo: Mapping[str, CfoWorksheet],
        *,
        assumptions: JournalWorksheet | None = None,
        own_extra: Mapping[str, CfoWorksheet] | None = None,
    ) -> None:
        self.config = config
        self.cfo_sheets = dict(cfo)
        self.own_sheets = {**_own_worksheets(assumptions), **(own_extra or {})}
        self.cfo_spreadsheet = CfoSpreadsheet(self.cfo_sheets)
        self.own_spreadsheet = JournalSpreadsheet(self.own_sheets)
        self.cfo_client = TimeoutClient(self.cfo_spreadsheet)
        self.own_client = FakeClient(self.own_spreadsheet)

    def source(self) -> ReadOnlyWorkbook:
        return connect_source_client(
            self.config, gspread_client=self.cfo_client, sleep=RecordingSleep()
        )

    def own(self) -> SheetsClient:
        return SheetsClient(self.config, gspread_client=self.own_client, sleep=RecordingSleep())

    def capture(self, clock: Callable[[], datetime] | None = None) -> CaptureSet:
        return capture(
            self.config,
            source_workbook=self.source(),
            own_client=self.own(),
            clock=clock or _clock(),
        )

    @property
    def assumptions(self) -> JournalWorksheet:
        sheet = self.own_sheets["Assumptions"]
        assert isinstance(sheet, JournalWorksheet)
        return sheet

    def assert_no_cfo_writes(self) -> None:
        """No write of any kind reached the CFO workbook, and only it was opened by key."""
        for ws in self.cfo_sheets.values():
            assert ws.batch_update_calls == []
            assert ws.append_rows_calls == []
            assert ws.update_calls == []
            assert ws.delete_rows_calls == []
        assert self.cfo_spreadsheet.add_worksheet_calls == []
        assert set(self.cfo_client.opened_keys) <= {CFO_ID}

    def assert_no_writes(self) -> None:
        self.assert_no_cfo_writes()
        for ws in self.own_sheets.values():
            assert ws.batch_update_calls == []
            assert ws.append_rows_calls == []
            assert ws.update_calls == []
            assert ws.delete_rows_calls == []
        assert self.assumptions.add_rows_calls == []
        assert self.assumptions.add_cols_calls == []
        assert self.own_spreadsheet.add_worksheet_calls == []


# --------------------------------------------------------------------------------------
# Fictional source shapes (school year 2030-31, calendar year 2030, as of Aug 15 2030)
# --------------------------------------------------------------------------------------

AS_OF = date(2030, 8, 15)
RECORDED_AT = datetime(2030, 8, 15, 12, 0, tzinfo=UTC)


def _bank(day: str, description: str, amount: str, final: str, *, check: str = "") -> list[str]:
    return [day, description, amount, check, "Posted", "", "", final]


VENDOR_DEC = "Example vendor A"
DONATION_JAN = "Deposit Example donation"
VENDOR_JUNE = "Example vendor B"
PAYOUT_JULY = "Deposit Example Store payout"
CHECK_JULY = "Check 2001"
VENDOR_AS_OF = "Example vendor C"
VENDOR_LATER = "Example vendor D"
BANK_ROWS = [
    _bank("12/31/2029", VENDOR_DEC, "-10.00", "Classroom Supplies"),
    _bank("1/1/2030", DONATION_JAN, "100.00", "Donations"),
    _bank("6/30/2030", VENDOR_JUNE, "-40.00", "Field Trips"),
    _bank("7/1/2030", PAYOUT_JULY, "48.25", "Fundraiser Income: 50.00, Processing Fees: -1.75"),
    _bank("7/10/2030", CHECK_JULY, "-45.00", "Classroom Supplies", check="2001"),
    _bank("7/12/2030", "Transfer to savings", "-500.00", reconcile.INTERNAL_TRANSFER_CATEGORY),
    _bank("8/15/2030", VENDOR_AS_OF, "-5.00", "Field Trips"),
    _bank("8/16/2030", VENDOR_LATER, "-7.00", "Field Trips"),
]
PNL_VALUES = [
    ["Category", "Dec 2029", "Jan 2030", "Jun 2030", "Jul 2030", "Aug 2030"],
    ["Classroom Supplies", "-10.00", "", "", "-45.00", ""],
    ["Donations", "", "100.00", "", "", ""],
    ["Field Trips", "", "", "-40.00", "", "-12.00"],
    ["Fundraiser Income", "", "", "", "50.00", ""],
    ["Processing Fees", "", "", "", "-1.75", ""],
]


def _wix(
    payment_id: str,
    day: date,
    amount: str,
    status: str,
    *,
    fee: str,
    net: str,
    refund: str = "",
    product: str = "Spirit Shirt",
) -> list[str]:
    row = [
        payment_id,
        f"{day.month}/{day.day}/{day.year}",
        f"{day.isoformat()} 10:15:00",
        "-08:00",
        "USD",
        amount,
        fee,
        "0.00",
        net,
        status,
        refund,
        "Wix Payments",
        f"10{day.month:02d}{day.day:02d}",
        product,
        "1",
        "Fulfilled",
        "Example Buyer",
        "US",
        "Example Buyer",
        "US",
    ]
    assert len(row) == len(WIX_LABELS)
    return row


WIX_ROWS = [
    _wix("pi_ex_000", date(2030, 6, 20), "20.00", "Successful", fee="-0.80", net="19.20"),
    _wix("pi_ex_001", date(2030, 7, 1), "50.00", "Successful", fee="-1.75", net="48.25"),
]

BUDGET_HEADER = [
    "fiscal_year",
    "category_group",
    "type",
    "measure",
    "amount",
    "is_fundraiser",
    "grade",
    "raw_category",
    "source_tab",
]


def _budget_row(year: str, kind: str, measure: str, amount: str, category: str) -> list[str]:
    return [year, "Programs", kind, measure, amount, "FALSE", "", category, "x"]


BUDGET_ROWS = [
    _budget_row("2031", "expense", "proposed", "500", "Classroom Supplies"),
    _budget_row("2031", "expense", "proposed", "300", "Field Trips"),
    _budget_row("2031", "income", "proposed", "1,500", "Fundraising"),
    _budget_row("2031", "expense", "proposed", "200", "Assemblies"),
    _budget_row("2031", "expense", "proposed", "100", "Library Books"),
    _budget_row("2031", "expense", "actual", "75.5", "Classroom Supplies"),
    _budget_row("2030", "expense", "proposed", "450", "Classroom Supplies"),
]

CROSSWALK_TOML = """
[main_reports.crosswalk]
version = 3
[[main_reports.crosswalk.entries]]
source_category = "Fundraiser Income"
targets = [{ category = "Fundraising", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Processing Fees"
targets = [{ category = "Fees and Charges", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Classroom Supplies"
targets = [{ category = "Classroom Supplies", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Field Trips"
targets = [{ category = "Field Trips", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Assemblies"
targets = [{ category = "Assemblies", share = "1" }]
note = "one-to-one, no activity yet"
"""
_DEFAULT_BANK_COVERAGE = 'start = "2030-01-01", end = "2030-01-31"'
FULL_BANK_COVERAGE = 'start = "2029-07-01", end = "2030-08-31"'


def _config(
    tmp_path: Path,
    *,
    bank_coverage: str | None = FULL_BANK_COVERAGE,
    crosswalk: str = CROSSWALK_TOML,
    start_month: int = 7,
    sources: str = "",
) -> Config:
    """``bank_coverage=None`` removes the bank source's declared coverage entirely."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bank = main_reports_toml()
    if bank_coverage is None:
        declared = f"coverage = [{{ {_DEFAULT_BANK_COVERAGE}, "
        start = bank.index(declared)
        bank = bank[:start] + bank[bank.index("\n", start) + 1 :]
    else:
        bank = bank.replace(_DEFAULT_BANK_COVERAGE, bank_coverage)
    toml = (
        _FULL_CONFIG.replace("start_month = 1", f"start_month = {start_month}")
        + bank
        + sources
        + crosswalk
    )
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")
    return load_config(path)


def _harness(
    config: Config,
    *,
    bank: Sequence[Sequence[str]] = BANK_ROWS,
    wix: Sequence[Sequence[str]] = WIX_ROWS,
    paypal: Sequence[Sequence[str]] = (),
    pnl: Sequence[Sequence[str]] = PNL_VALUES,
    mapping: Sequence[Sequence[str]] = (),
    budget: Sequence[Sequence[str]] = BUDGET_ROWS,
    extra: Mapping[str, CfoWorksheet] | None = None,
) -> CfoHarness:
    sheets = {
        "Bank Checking": CfoWorksheet([BANK_HEADER, *map(list, bank)], sheet_id=1001),
        "Store Transactions": CfoWorksheet(
            [WIX_GROUPS, WIX_LABELS, *map(list, wix)], sheet_id=1002
        ),
        "Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *map(list, paypal)], sheet_id=1003),
        "Profit & Loss": CfoWorksheet([list(row) for row in pnl], sheet_id=1004),
        "Budget Tracker": CfoWorksheet([["Category", "Budget", "Actual"]], sheet_id=1005),
        "Category Mapping": CfoWorksheet([MAPPING_HEADER, *map(list, mapping)], sheet_id=1006),
        "Credit Card Transactions": CfoWorksheet([CARD_HEADER], sheet_id=1007),
        **(extra or {}),
    }
    own = {"Budget Timeseries": CfoWorksheet([BUDGET_HEADER, *map(list, budget)], sheet_id=2001)}
    return CfoHarness(config, sheets, own_extra=own)


def _recorded_clock() -> Callable[[], datetime]:
    counter = itertools.count()
    return lambda: RECORDED_AT + timedelta(seconds=next(counter))


# --------------------------------------------------------------------------------------
# Fictional reimbursement bundle (schema v2, loaded by the production loader)
# --------------------------------------------------------------------------------------


def _item(
    key: str, index: int, day: str, amount: str, status: str, category: str
) -> dict[str, Any]:
    return {
        "item_key": key,
        "source_index": index,
        "source_date": day,
        "source_description": "Fictional classroom materials",
        "source_amount": amount,
        "canonical_category": category,
        "display_date": "",
        "display_item": "",
        "reviewed_amount": "",
        "status": status,
        "why": "Fictional evidence supports this test disposition.",
    }


def _ticket(
    order: int,
    ref: str,
    origin: str,
    submitted: str,
    items: list[dict[str, Any]],
    *,
    status: str,
    decision: str = "UNREVIEWED",
    workflow: str = "ACTIVE",
    payment_status: str = "NOT_PAID",
    payment_date: str = "",
    confirmations: Sequence[str] = (),
) -> dict[str, Any]:
    total = sum((Decimal(str(item["source_amount"])) for item in items), Decimal("0.00"))
    review_key = (
        f"submission:v1:{order:064x}" if origin == "submission" else f"legacy:v1:{ref.lower()}"
    )
    return {
        "review_key": review_key,
        "ref": ref,
        "form_label": "",
        "origin": origin,
        "display_order": order,
        "requestor_name": f"Fictional Person {order}",
        "form_type": "Example Reimbursement Form",
        "submitted": submitted,
        "submitted_label": "",
        "payment_method": "Check",
        "source_evidence_sha256": f"{order:x}" * 64,
        "source": {
            "stated_total": f"{total:.2f}",
            "mapped_total": f"{total:.2f}",
            "categories": list(dict.fromkeys(i["canonical_category"] for i in items)),
            "flags": [],
        },
        "live": {
            "workflow_state": workflow,
            "decision": decision,
            "payment_status": payment_status,
            "payment_date": payment_date,
            "confirmations": list(confirmations),
        },
        "review": {
            "status": status,
            "action": "Complete the fictional next step",
            "block": "Use the structured test evidence.",
            "asks": [],
            "note": "Fictional reviewer note.",
            "email_questions": [],
            "email_context": "",
        },
        "items": items,
        "messages": [],
        "archive_note": "Fictional archive note." if workflow == "SETTLED" else "",
    }


def _seal(record_: dict[str, Any]) -> None:
    record_.pop("record_sha256", None)
    record_["record_sha256"] = hashlib.sha256(
        json.dumps(record_, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


PAID_TICKET = "NEW-01"  # June and July items, one check paid in July
PAYMENT_REFERENCE = "2001"


def _payment_records(
    ticket_key: str, day: str, amount: str, reference: str, digest_char: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sealed operator-payment evidence and its PAYMENT_RECORDED event for one ticket."""
    digest = digest_char * 64
    evidence: dict[str, Any] = {
        "evidence_key": f"operator-payment:v1:{digest}",
        "source_type": "OPERATOR_PAYMENT",
        "message_id": "",
        "in_reply_to": [],
        "references": [],
        "occurred_on": day,
        "occurred_at": "",
        "top_authored_sha256": digest,
        "evidence_sha256": digest,
        "attachments": [],
    }
    _seal(evidence)
    event: dict[str, Any] = {
        "event_key": "event:v1:"
        + hashlib.sha256(
            f"{evidence['evidence_key']}\0{ticket_key}\0PAYMENT_RECORDED".encode()
        ).hexdigest(),
        "evidence_key": evidence["evidence_key"],
        "ticket_review_key": ticket_key,
        "kind": "PAYMENT_RECORDED",
        "occurred_on": day,
        "occurred_at": "",
        "evidence_sha256": digest,
        "summary": "Synthetic configured-operator payment recorded.",
        "amount": amount,
        "reference": reference,
        "discrepancy": "",
    }
    _seal(event)
    return evidence, event


def _record_payment(
    payload: dict[str, Any], ticket: dict[str, Any], day: str, reference: str, digest_char: str
) -> None:
    """Settle an approved ticket as PAID with an exact recorded payment event."""
    total = sum((Decimal(str(i["source_amount"])) for i in ticket["items"]), Decimal("0.00"))
    ticket["live"] = {
        "workflow_state": "SETTLED",
        "decision": "APPROVED",
        "payment_status": "PAID",
        "payment_date": day,
        "confirmations": [f"Reference {reference}; amount ${total:.2f}"],
    }
    ticket["archive_note"] = "Fictional archive note."
    evidence, event = _payment_records(
        ticket["review_key"], day, f"{total:.2f}", reference, digest_char
    )
    supplemental = payload["supplemental"]
    supplemental["evidence"] = sorted(
        [*supplemental["evidence"], evidence], key=lambda item: item["evidence_key"]
    )
    supplemental["events"] = sorted(
        [*supplemental["events"], event], key=lambda item: item["event_key"]
    )


def _bundle_payload() -> dict[str, Any]:
    paid = _ticket(
        1,
        PAID_TICKET,
        "submission",
        "2030-07-03",
        [
            _item("new-01:line:1", 1, "2030-06-28", "25.00", "A", "Classroom Supplies"),
            _item("new-01:line:2", 2, "2030-07-02", "20.00", "A", "Classroom Supplies"),
        ],
        status="A",
        decision="APPROVED",
        workflow="SETTLED",
        payment_status="PAID",
        payment_date="2030-07-08",
        confirmations=[f"Reference {PAYMENT_REFERENCE}; amount $45.00"],
    )
    old_outstanding = _ticket(
        2,
        "P-001",
        "legacy",
        "2029-05-20",
        [_item("p-001:line:1", 1, "2029-05-10", "30.00", "A", "Field Trips")],
        status="A",
        decision="APPROVED",
    )
    undated = _ticket(
        3,
        "NEW-02",
        "submission",
        "2030-07-21",
        [
            _item("new-02:line:1", 1, "", "12.00", "Q", "Classroom Supplies"),
            _item("new-02:line:2", 2, "2030-07-20", "8.00", "C", "Classroom Supplies"),
        ],
        status="C",
    )
    paid_prior = _ticket(
        4,
        "P-002",
        "legacy",
        "2030-03-02",
        [_item("p-002:line:1", 1, "2030-03-01", "15.00", "A", "Classroom Supplies")],
        status="A",
        decision="APPROVED",
        workflow="SETTLED",
        payment_status="PAID_PRIOR",
        payment_date="2030-03-05",
        confirmations=["Fictional confirmation"],
    )
    partly_declined = _ticket(
        5,
        "NEW-03",
        "submission",
        "2030-07-06",
        [
            _item("new-03:line:1", 1, "2030-07-05", "10.00", "D", "Classroom Supplies"),
            _item("new-03:line:2", 2, "2030-07-05", "5.00", "A", "Classroom Supplies"),
        ],
        status="D",
    )
    after_as_of = _ticket(
        6,
        "NEW-04",
        "submission",
        "2030-08-10",
        [_item("new-04:line:1", 1, "2030-08-20", "9.00", "Q", "Field Trips")],
        status="Q",
    )
    tickets = [paid, old_outstanding, undated, paid_prior, partly_declined, after_as_of]
    submissions = sorted(t["review_key"] for t in tickets if t["origin"] == "submission")

    evidence, event = _payment_records(
        paid["review_key"], "2030-07-08", "45.00", PAYMENT_REFERENCE, "d"
    )
    return {
        "schema_version": 2,
        "report": {
            "title": "Example Reimbursement Review",
            "eyebrow": "Example Organization",
            "subtitle": "Structured fictional review queue.",
            "organization": "Example Organization",
            "email_signoff": ["Thank you!", "Example Treasurer Team"],
            "logo_data_uri": "",
            "confirmed_outstanding": "35.00",
            "cutoff_date": "2030-06-01",
            "policy_version": "example-v1",
            "as_of_date": "2030-08-15",
        },
        "provenance": {
            "mapped_sha256": "1" * 64,
            "policy_sha256": "2" * 64,
            "source_snapshot_sha256": "3" * 64,
            "accounted_review_keys": submissions,
        },
        "source_summary": {
            "mapped_rows": 6,
            "mapped_submissions": len(submissions),
            "mapped_total": "84.00",
            "first_received": "2030-06-02",
            "last_received": "2030-08-10",
        },
        "tickets": tickets,
        "appendix": {"amendments": [], "cfo_checks": [], "excluded": [], "defects": []},
        "supplemental": {
            "anchors_sha256": "f" * 64,
            "evidence": [evidence],
            "events": [event],
            "unmatched": [],
        },
    }


# --------------------------------------------------------------------------------------
# Production-path scenario
# --------------------------------------------------------------------------------------


class Scenario:
    """Fake workbooks + a bundle file, driven through every production caller."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        bank_coverage: str | None = FULL_BANK_COVERAGE,
        crosswalk: str = CROSSWALK_TOML,
        start_month: int = 7,
        sources: str = "",
        bundle: dict[str, Any] | None = None,
        **sheets: Any,
    ) -> None:
        self.tmp_path = tmp_path
        self.config = _config(
            tmp_path,
            bank_coverage=bank_coverage,
            crosswalk=crosswalk,
            start_month=start_month,
            sources=sources,
        )
        self.harness = _harness(self.config, **sheets)
        self.bundle_path = tmp_path / "reports" / "output" / "reimbursement-report.json"
        self.bundle_path.parent.mkdir(parents=True, exist_ok=True)
        self.bundle_path.write_text(
            json.dumps(bundle or _bundle_payload(), ensure_ascii=False), encoding="utf-8"
        )

    def reconciled(self) -> tuple[CaptureSet, Any]:
        capture_set = self.harness.capture()
        return capture_set, reconcile.from_capture(capture_set, self.config)

    def txn(self, description: str) -> Transaction:
        _, rec = self.reconciled()
        (found,) = [t for t in rec.transactions if t.description == description]
        return found

    def record(self, proposals: Sequence[Adjustment]) -> None:
        capture_set, rec = self.reconciled()
        with acquire_run_lock(self.config) as lock:
            record(
                proposals,
                config=self.config,
                client=self.harness.own(),
                captured=capture_set.assumptions,
                reconciliation=rec,
                as_of=AS_OF,
                lock=lock,
                clock=_recorded_clock(),
            )

    def inputs(self, as_of: date = AS_OF) -> tuple[CaptureSet, AdjustedLedger, ReimbursementReport]:
        capture_set, rec = self.reconciled()
        ledger = project(rec, read_journal(capture_set.assumptions), as_of)
        return capture_set, ledger, reimbursement_report.load_bundle(self.bundle_path)

    def facts(self, as_of: date = AS_OF) -> ReportFacts:
        capture_set, ledger, bundle = self.inputs(as_of)
        return build_from(capture_set, ledger, bundle, self.config)

    def build(
        self, ledger: AdjustedLedger | None = None, **changes: Any
    ) -> tuple[ReportFacts, CaptureSet]:
        """Call :func:`facts.build` directly with this scenario's inputs, some replaced."""
        capture_set, own_ledger, bundle = self.inputs()
        assert self.config.main_reports is not None
        arguments: dict[str, Any] = {
            "bundle": bundle,
            "periods": reporting_periods(AS_OF, 7),
            "captures": capture_set.captures,
            "crosswalk": self.config.main_reports.crosswalk,
        }
        arguments.update(changes)
        result = build(
            ledger or own_ledger,
            arguments.pop("bundle"),
            capture_set.adopted_budget,
            arguments.pop("periods"),
            **arguments,
        )
        return result, capture_set


def _adjustment(kind: str, txn: Transaction | None = None, **fields: Any) -> Adjustment:
    return Adjustment(
        adjustment_id=make_adjustment_id(),
        kind=kind,
        effective_date=fields.pop("effective", date(2030, 7, 1)),
        reason="Example correction",
        evidence=fields.pop("evidence", ("example-statement-2030-07",)),
        targets=() if txn is None else ((txn.record_key, txn.revision_hash),),
        **fields,
    )


def _adjusted_scenario(tmp_path: Path, **kwargs: Any) -> tuple[Scenario, Adjustment, Adjustment]:
    scenario = Scenario(tmp_path, **kwargs)
    moved = _adjustment(
        "date_override",
        scenario.txn(VENDOR_JUNE),
        prior_value="2030-06-30",
        replacement_value="2030-07-01",
    )
    added = _adjustment(
        "additive",
        effective=date(2030, 8, 1),
        category="Donations",
        signed_amount=Decimal("25.00"),
        evidence=("example-cash-count-2030-08",),
    )
    scenario.record([moved, added])
    return scenario, moved, added
