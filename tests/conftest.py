"""Shared test fixtures — fake-org config + a fake gspread layer (no live Google calls).

Identity here is obviously-fake placeholders only (``Example PTA`` etc.). NOTHING in
these fixtures touches the network: a ``FakeWorksheet`` / ``FakeSpreadsheet`` / ``FakeClient``
stand in for the gspread objects, and :class:`~pta_finance.sheets.SheetsClient` is always
constructed with ``gspread_client=`` so :func:`gspread.service_account` is never called.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from gspread.exceptions import APIError
from gspread.utils import a1_to_rowcol
from requests.models import Response

from pta_finance import report_source
from pta_finance.config import Config, load_config
from pta_finance.main_reports.models import CaptureSet
from pta_finance.main_reports.sources import ReadOnlyWorkbook, capture, connect_source_client
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
