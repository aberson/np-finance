"""Tests for pta_finance.main_reports.sources — read-only CFO capture and adapters.

Every fixture is fictional (``Example`` placeholders, fake ids). The CFO workbook and our own
workbook are fake gspread layers; the production config loader, :func:`connect_source_client`,
:func:`capture`, :func:`normalize` and :func:`store_capture_set` are exercised end to end.
Nothing performs a live Google call or a workbook write.
"""

from __future__ import annotations

import ast
import dataclasses
import itertools
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pta_finance import report_source
from pta_finance.config import Config, ConfigError, load_config
from pta_finance.main_reports import models, sources
from pta_finance.main_reports.models import CaptureSet, Transaction, make_record_key
from pta_finance.main_reports.sources import (
    READONLY_SCOPE,
    ReadOnlyWorkbook,
    SourceCaptureError,
    SourceConfigError,
    SourceSchemaError,
    SourceValidationError,
    capture,
    classify_status,
    compare_captures,
    compare_transactions,
    connect_source_client,
    coverage_status,
    is_dash_placeholder,
    normalize,
    normalize_with_report,
    parse_allocations,
    parse_money,
    parse_source_date,
    read_category_mapping,
    require_bindings,
    store_capture_set,
)
from pta_finance.sheets import SheetsClient
from tests.conftest import (
    _FULL_CONFIG,
    FakeClient,
    FakeSpreadsheet,
    FakeWorksheet,
    RecordingSleep,
    tagged_user_entered_grid,
)

CFO_ID = "fake-cfo-workbook-id"

# --------------------------------------------------------------------------------------
# Fictional source shapes
# --------------------------------------------------------------------------------------

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
BANK_ROWS = [
    [
        "1/5/2030",
        "Deposit Example Store payout",
        "1,250.00",
        "",
        "Posted",
        "Fundraiser",
        "",
        "Fundraiser Income: 1,280.00, Processing Fees: -30.00",
    ],
    [
        "1/9/2030",
        "Check 1001",
        "-75.50",
        "1001",
        "Posted",
        "Supplies",
        "Classroom Supplies",
        "Classroom Supplies",
    ],
    [
        "1/12/2030",
        "Transfer to savings",
        "-500.00",
        "",
        "Posted",
        "Internal Transfer",
        "",
        "Internal Transfer",
    ],
    ["1/15/2030", "Monthly service fee", "-3.00", "", "Posted", "Fees", "", "Fees"],
    ["1/15/2030", "Monthly service fee", "-3.00", "", "Posted", "Fees", "", "Fees"],
    ["", "Total", "668.50", "", "", "", "", ""],
    ["2/1/2030", "Pending deposit", "$40.00", "", "Pending", "Donations", "", "Donations"],
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


def _wix_row(
    payment_id: str, day: int, amount: str, status: str, *, refund: str = "", fee: str = "-1.00"
) -> list[str]:
    net = "" if status == "Declined" else "1.00"
    return [
        payment_id,
        f"1/{day}/2030",
        f"2030-01-{day:02d} 10:15:00",
        "-08:00",
        "USD",
        amount,
        fee,
        "0.00",
        net,
        status,
        refund,
        "Example Payments",
        f"1000{day}",
        "Spirit Shirt",
        "1",
        "Fulfilled",
        "Example Buyer",
        "US",
        "Example Buyer",
        "US",
    ]


WIX_ROWS = [
    _wix_row("pi_example_001", 4, "$50.00", "Successful"),
    _wix_row("pp_example_002", 6, "25.00", "Partially Refunded", refund="10.00"),
    _wix_row("pi_example_003", 7, "15.00", "Declined", fee=""),
    _wix_row("pi_example_004", 8, "12.00", "Chargeback"),
    _wix_row("pi_example_005", 9, "8.00", "Authorized"),
    _wix_row("pi_example_006", 10, "20.00", "Refunded", refund="20.00"),
    [
        "",
        "",
        "Total",
        "",
        "",
        "130.00",
        "-5.00",
        "0.00",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ],
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
_DETAIL = [
    "01/04/2030",
    "10:15:00",
    "PST",
    "Example Buyer",
    "Shopping Cart Item",
    "Completed",
    "USD",
    "30.00",
    "",
    "",
    "TXN-EX-1",
    "",
    "Spirit Shirt",
    "1",
    "",
]
PAYPAL_ROWS = [
    [
        "01/04/2030",
        "10:15:00",
        "PST",
        "Example Buyer",
        "Website Payment",
        "Completed",
        "USD",
        "60.00",
        "-2.39",
        "57.61",
        "TXN-EX-1",
        "",
        "",
        "",
        "Credit",
    ],
    list(_DETAIL),
    list(_DETAIL),
    [
        "01/04/2030",
        "10:15:00",
        "PST",
        "",
        "Partner Fee",
        "Completed",
        "USD",
        "-0.50",
        "",
        "-0.50",
        "TXN-EX-2",
        "TXN-EX-1",
        "",
        "",
        "Debit",
    ],
    [
        "01/20/2030",
        "08:00:00",
        "PST",
        "",
        "General Withdrawal",
        "Completed",
        "USD",
        "-57.11",
        "",
        "-57.11",
        "TXN-EX-3",
        "",
        "",
        "",
        "Debit",
    ],
    [
        "01/22/2030",
        "09:00:00",
        "PST",
        "Example Buyer",
        "Payment Refund",
        "Completed",
        "USD",
        "-10.00",
        "0.30",
        "-9.70",
        "TXN-EX-4",
        "TXN-EX-1",
        "",
        "",
        "Debit",
    ],
    [
        "01/06/2030",
        "09:00:00",
        "PST",
        "Example Buyer",
        "Express Checkout Payment",
        "Completed",
        "USD",
        "25.00",
        "-1.10",
        "23.90",
        "pp_example_002",
        "",
        "",
        "",
        "Credit",
    ],
    ["", "", "", "Total", "", "", "", "88.00", "", "", "", "", "", "", ""],
]

PNL_VALUES = [["Category", "Jan 2030"], ["Fundraiser Income", "1,280.00"], ["Fees", "-6.00"]]
PNL_FORMULAS = [['=QUERY({"example"}, "select *")', ""], ["", ""], ["", ""]]
TRACKER_VALUES = [["Category", "Budget", "Actual"], ["Classroom Supplies", "500.00", "75.50"]]
TRACKER_FORMULAS = [["", "", ""], ["", '=IMPORTRANGE("fake-own-budget-id", "B2")', ""]]
MAPPING_VALUES = [["Keyword", "Target Category"], ["shirt", "Spirit Wear"], ["", ""]]
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


class TimeoutClient(FakeClient):
    def __init__(self, spreadsheet: FakeSpreadsheet) -> None:
        super().__init__(spreadsheet)
        self.timeouts: list[float] = []

    def set_timeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


def _cfo_worksheets(**overrides: CfoWorksheet) -> dict[str, CfoWorksheet]:
    sheets = {
        "Bank Checking": CfoWorksheet([BANK_HEADER, *BANK_ROWS], sheet_id=1001),
        "Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *WIX_ROWS], sheet_id=1002),
        "Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *PAYPAL_ROWS], sheet_id=1003),
        "Profit & Loss": CfoWorksheet(PNL_VALUES, sheet_id=1004, formulas=PNL_FORMULAS),
        "Budget Tracker": CfoWorksheet(TRACKER_VALUES, sheet_id=1005, formulas=TRACKER_FORMULAS),
        "Category Mapping": CfoWorksheet(MAPPING_VALUES, sheet_id=1006),
        "Credit Card Transactions": CfoWorksheet([CARD_HEADER], sheet_id=1007),
    }
    sheets.update(overrides)
    return sheets


def _own_worksheets() -> dict[str, CfoWorksheet]:
    return {
        report_source.BUDGET_TIMESERIES_TAB: CfoWorksheet(BUDGET_GRID, sheet_id=2001),
        "Assumptions": CfoWorksheet(ASSUMPTIONS_GRID, sheet_id=2002),
    }


# --------------------------------------------------------------------------------------
# Private-config fixture (written to tmp and loaded through the production loader)
# --------------------------------------------------------------------------------------

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
            "category-mapping", "category_mapping", "Category Mapping", [MAPPING_VALUES[0]]
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


def _config(tmp_path: Path, **kwargs: Any) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(_FULL_CONFIG + main_reports_toml(**kwargs), encoding="utf-8")
    return load_config(path)


def _store_root(tmp_path: Path) -> Path:
    """The configured private output root (the production store location)."""
    main = _config(tmp_path).main_reports
    assert main is not None
    return main.output_path


def _clock() -> Callable[[], datetime]:
    counter = itertools.count()
    start = datetime(2030, 2, 1, 12, 0, tzinfo=UTC)
    return lambda: start + timedelta(seconds=next(counter))


class Harness:
    def __init__(
        self,
        config: Config,
        cfo: Mapping[str, CfoWorksheet] | None = None,
    ) -> None:
        self.config = config
        self.cfo_sheets = dict(cfo or _cfo_worksheets())
        self.own_sheets = _own_worksheets()
        self.cfo_spreadsheet = CfoSpreadsheet(self.cfo_sheets)
        self.own_spreadsheet = CfoSpreadsheet(self.own_sheets)
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

    def assert_no_writes(self) -> None:
        for ws in [*self.cfo_sheets.values(), *self.own_sheets.values()]:
            assert ws.batch_update_calls == []
            assert ws.append_rows_calls == []
            assert ws.update_calls == []
            assert ws.delete_rows_calls == []
        assert self.cfo_spreadsheet.add_worksheet_calls == []
        assert self.own_spreadsheet.add_worksheet_calls == []


def _by_alias(transactions: Sequence[Transaction], alias: str) -> list[Transaction]:
    return [txn for txn in transactions if txn.source_alias == alias]


# --------------------------------------------------------------------------------------
# Config -> read-only client -> capture -> normalize (production entry points)
# --------------------------------------------------------------------------------------


def test_production_capture_uses_readonly_client_and_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    harness = Harness(config)
    calls: list[dict[str, Any]] = []

    def fake_service_account(**kwargs: Any) -> TimeoutClient:
        calls.append(kwargs)
        return harness.cfo_client

    monkeypatch.setattr(sources.gspread, "service_account", fake_service_account)

    captured = capture(config, own_client=harness.own(), clock=_clock())

    assert calls == [
        {
            "filename": str(config.google.service_account_path),
            "scopes": [READONLY_SCOPE],
        }
    ]
    assert READONLY_SCOPE == "https://www.googleapis.com/auth/spreadsheets.readonly"
    assert harness.cfo_client.timeouts == [sources.HTTP_TIMEOUT_SECONDS]
    assert set(harness.cfo_client.opened_keys) == {CFO_ID}
    assert set(captured.by_alias) == {
        "bank-checking",
        "budget-tracker",
        "category-mapping",
        "credit-card",
        "paypal",
        "pnl",
        "wix",
    }
    assert captured.consistency.consistent and captured.consistency.attempts == 1
    transactions = normalize(captured)
    assert {txn.source_kind for txn in transactions} == {"bank", "wix", "paypal"}
    harness.assert_no_writes()


def test_read_only_workbook_exposes_no_write_methods() -> None:
    write_verbs = ("update", "append", "delete", "clear", "add_worksheet", "batch", "replace")
    names = [name for name in dir(ReadOnlyWorkbook) if not name.startswith("__")]
    assert not [name for name in names if any(verb in name for verb in write_verbs)]


def test_missing_binding_fails_before_any_read(tmp_path: Path) -> None:
    config = _config(tmp_path, omit=("credit-card",))
    harness = Harness(config)
    with pytest.raises(SourceConfigError) as caught:
        harness.capture()
    assert caught.value.code == "missing_binding"
    assert harness.cfo_client.opened_keys == []
    assert harness.own_client.opened_keys == []


def test_missing_main_reports_section_is_a_config_error(fake_config: Config) -> None:
    with pytest.raises(SourceConfigError) as caught:
        require_bindings(fake_config)
    assert caught.value.code == "main_reports_missing"


def test_config_example_main_reports_block_loads_and_resolves(tmp_path: Path) -> None:
    example = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text(
        encoding="utf-8"
    )
    lines = example.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# [main_reports]"))
    end = next(i for i, line in enumerate(lines) if line.startswith("# [llm]"))
    toml_line = re.compile(r"$|\[|\]|\s|[a-z_]+\s*=")  # prose comment lines match none
    uncommented = (line.removeprefix("#").removeprefix(" ") for line in lines[start:end])
    block = "\n".join(line for line in uncommented if toml_line.match(line))
    path = tmp_path / "config.toml"
    path.write_text(_FULL_CONFIG + "\n" + block + "\n", encoding="utf-8")
    config = load_config(path)
    resolved = {item.binding.alias: item for item in require_bindings(config)}
    wix = dict(resolved["wix"].columns)
    assert wix["transaction_status"] == 9  # the Transaction-group "Status", not the Order one
    assert config.main_reports is not None and config.main_reports.crosswalk is not None


# --------------------------------------------------------------------------------------
# Source shapes
# --------------------------------------------------------------------------------------


def test_bank_rows_keep_exact_money_splits_and_legitimate_duplicates(tmp_path: Path) -> None:
    harness = Harness(_config(tmp_path))
    result = normalize_with_report(harness.capture())
    bank = _by_alias(result.transactions, "bank-checking")

    assert [txn.refs[0].row_number for txn in bank] == [2, 3, 4, 5, 6, 8]
    payout = bank[0]
    assert payout.gross == Decimal("1250.00")
    assert payout.posting_date == date(2030, 1, 5)
    assert [(a.category, a.amount) for a in payout.allocations] == [
        ("Fundraiser Income", Decimal("1280.00")),
        ("Processing Fees", Decimal("-30.00")),
    ]
    assert sum(a.amount for a in payout.allocations) == payout.gross
    assert payout.source_values == tuple(BANK_ROWS[0])
    assert payout.final_category == BANK_ROWS[0][7]
    assert payout.record_key.startswith("v1:bank-checking:")

    check = bank[1]
    assert check.check_number == "1001"
    assert check.raw_category == "Supplies"
    assert check.override_category == "Classroom Supplies"
    assert [(a.category, a.amount) for a in check.allocations] == [
        ("Classroom Supplies", Decimal("-75.50"))
    ]

    fee_a, fee_b = bank[3], bank[4]
    assert fee_a.record_key != fee_b.record_key
    assert {fee_a.record_key.rsplit(":", 1)[1], fee_b.record_key.rsplit(":", 1)[1]} == {"0", "1"}
    assert bank[5].source_status == "Pending"
    assert bank[5].gross == Decimal("40.00")

    excluded = {(row.source_alias, row.row_number, row.reason) for row in result.excluded}
    assert excluded == {
        ("bank-checking", 7, "summary_row"),
        ("wix", 9, "summary_row"),
        ("paypal", 9, "summary_row"),
    }
    assert result.errors == ()


def test_wix_two_row_header_binds_by_position_and_classifies_states(tmp_path: Path) -> None:
    harness = Harness(_config(tmp_path))
    wix = _by_alias(normalize(harness.capture()), "wix")

    assert [txn.status_class for txn in wix] == [
        "successful",
        "partially_refunded",
        "declined",
        "chargeback",
        "authorized",
        "refunded",
    ]
    first = wix[0]
    assert first.native_id == "pi_example_001"
    assert first.source_status == "Successful"  # Transaction group, not Order "Fulfilled"
    assert first.gross == Decimal("50.00")
    assert first.fee == Decimal("-1.00")
    assert first.fee_components == (
        ("processing_fee", Decimal("-1.00")),
        ("service_fee", Decimal("0.00")),
    )
    assert first.payment_date == date(2030, 1, 4)
    assert first.original_timestamp == "2030-01-04 10:15:00"
    assert first.original_offset == "-08:00"
    assert first.order_id == "10004"
    assert first.product_name == "Spirit Shirt"
    assert first.quantity == "1"
    assert first.payment_provider == "Example Payments"
    assert wix[1].refund == Decimal("10.00")
    assert wix[2].fee_components == (("service_fee", Decimal("0.00")),)
    assert all(txn.row_role == "payment" and txn.currency == "USD" for txn in wix)
    assert [txn.refs[0].row_number for txn in wix] == [3, 4, 5, 6, 7, 8]


def test_wix_repeated_label_without_group_is_ambiguous(tmp_path: Path) -> None:
    config = _config(tmp_path, wix_columns='transaction_status = "Status"')
    with pytest.raises(SourceConfigError) as caught:
        require_bindings(config)
    assert caught.value.code == "ambiguous_column"


def test_wix_occurrence_binding_matches_group_binding(tmp_path: Path) -> None:
    config = _config(
        tmp_path, wix_columns='transaction_status = { label = "Status", occurrence = 1 }'
    )
    wix = next(item for item in require_bindings(config) if item.binding.alias == "wix")
    assert dict(wix.columns)["transaction_status"] == 9


def test_paypal_repeated_ids_keep_details_and_separate_roles(tmp_path: Path) -> None:
    harness = Harness(_config(tmp_path))
    result = normalize_with_report(harness.capture())
    paypal = _by_alias(result.transactions, "paypal")

    by_id = [txn for txn in paypal if txn.native_id == "TXN-EX-1"]
    assert [txn.row_role for txn in by_id] == ["payment", "detail", "detail"]
    parent, detail_a, detail_b = by_id
    assert len({parent.record_key, detail_a.record_key, detail_b.record_key}) == 3
    assert detail_a.parent_key == parent.record_key == detail_b.parent_key
    assert detail_a.revision_hash == detail_b.revision_hash  # identical items both preserved
    assert detail_a.product_name == "Spirit Shirt"
    assert parent.gross == Decimal("60.00") and parent.net == Decimal("57.61")
    assert parent.original_timestamp == "01/04/2030 10:15:00"
    assert parent.original_offset == "PST"

    roles = {txn.native_id: txn.row_role for txn in paypal if txn.row_role != "detail"}
    assert roles == {
        "TXN-EX-1": "payment",
        "TXN-EX-2": "fee",
        "TXN-EX-3": "transfer",
        "TXN-EX-4": "refund",
        "pp_example_002": "payment",
    }
    fee = next(txn for txn in paypal if txn.native_id == "TXN-EX-2")
    assert fee.reference_id == "TXN-EX-1"
    assert result.errors == ()


def test_wix_and_paypal_shared_provider_id_keep_both_records(tmp_path: Path) -> None:
    transactions = normalize(Harness(_config(tmp_path)).capture())
    shared = [txn for txn in transactions if txn.native_id == "pp_example_002"]
    assert sorted(txn.source_kind for txn in shared) == ["paypal", "wix"]
    assert len({txn.record_key for txn in shared}) == 2


def test_orphan_paypal_detail_is_reported_not_dropped(tmp_path: Path) -> None:
    orphan = list(_DETAIL)
    orphan[10] = "TXN-EX-9"
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, orphan], sheet_id=1003)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    detail = _by_alias(result.transactions, "paypal")[0]
    assert detail.parent_key is None
    paypal_issues = [(i.code, i.severity) for i in result.issues if i.source_alias == "paypal"]
    assert paypal_issues == [("orphan_detail", "warning")]


def test_control_tabs_capture_formulas_without_evaluating_them(tmp_path: Path) -> None:
    captured = Harness(_config(tmp_path)).capture()
    pnl = captured.by_alias["pnl"]
    assert pnl.values == tuple(tuple(row) for row in PNL_VALUES)
    assert [(f.row, f.column, f.formula) for f in pnl.formulas] == [(0, 0, PNL_FORMULAS[0][0])]
    tracker = captured.by_alias["budget-tracker"]
    assert [f.formula for f in tracker.formulas] == [TRACKER_FORMULAS[1][1]]
    assert [f.formula for f in captured.assumptions.formulas] == ["=B2*2"]
    assert captured.assumptions.tab_title == "Assumptions"
    rules = read_category_mapping(captured.by_alias["category-mapping"])
    assert [(r.keyword, r.target_category, r.row_number) for r in rules] == [
        ("shirt", "Spirit Wear", 2)
    ]


def test_adopted_budget_is_proposed_rows_only_and_never_synthetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("to_inputs synthetic annual rows must not enter source capture")

    monkeypatch.setattr(report_source, "to_inputs", forbidden)
    captured = Harness(_config(tmp_path)).capture()
    budget = captured.adopted_budget
    assert [row["raw_category"] for row in budget.rows_as_dicts()] == [
        "Classroom Supplies",
        "Fundraiser Income",
    ]
    assert all(row["measure"] == "proposed" for row in budget.rows_as_dicts())
    assert budget.excluded_non_adopted_rows == 1
    dates = {
        d
        for txn in normalize(captured)
        for d in (txn.posting_date, txn.payment_date, txn.expense_date)
        if d is not None
    }
    assert dates and all(d.year == 2030 and d.month in {1, 2} for d in dates)


def test_credit_card_tab_is_not_ingested_but_population_is_flagged(tmp_path: Path) -> None:
    empty = Harness(_config(tmp_path)).capture()
    assert empty.by_alias["credit-card"].warnings == ()
    cfo = _cfo_worksheets(
        **{
            "Credit Card Transactions": CfoWorksheet(
                [CARD_HEADER, ["1/3/2030", "Example vendor", "-9.99"]], sheet_id=1007
            )
        }
    )
    populated = Harness(_config(tmp_path), cfo).capture()
    assert populated.by_alias["credit-card"].warnings == ("uncovered_source_populated",)
    assert all(txn.source_alias != "credit-card" for txn in normalize(populated))


# --------------------------------------------------------------------------------------
# Idempotency, change detection, provenance
# --------------------------------------------------------------------------------------


def test_duplicate_import_is_idempotent(tmp_path: Path) -> None:
    harness = Harness(_config(tmp_path))
    first = harness.capture(clock=_clock())
    later = datetime(2030, 3, 1, tzinfo=UTC)
    second = harness.capture(clock=lambda: later)

    assert first.aggregate_sha256 == second.aggregate_sha256
    assert (
        first.by_alias["bank-checking"].captured_at != second.by_alias["bank-checking"].captured_at
    )
    assert normalize(first) == normalize(second)
    assert compare_transactions(normalize(first), normalize(second)) == ()
    assert compare_captures(first, second) == ()

    root = _store_root(tmp_path)
    stored = store_capture_set(first, root)
    assert stored.created
    original = stored.path.read_bytes()
    again = store_capture_set(second, root)
    assert not again.created and again.path == stored.path
    assert stored.path.read_bytes() == original
    assert len(list((root / "captures").iterdir())) == 2


def test_stored_capture_conflict_is_never_overwritten(tmp_path: Path) -> None:
    captured = Harness(_config(tmp_path)).capture()
    root = _store_root(tmp_path)
    stored = store_capture_set(captured, root)
    stored.path.write_text('{"aggregate_sha256": "tampered"}', encoding="utf-8")
    with pytest.raises(SourceCaptureError) as caught:
        store_capture_set(captured, root)
    assert caught.value.code == "stored_capture_conflict"


def test_provenance_manifest_has_hashes_but_no_cell_values(tmp_path: Path) -> None:
    captured = Harness(_config(tmp_path)).capture()
    stored = store_capture_set(captured, _store_root(tmp_path))
    manifest = json.loads(stored.manifest_path.read_text(encoding="utf-8"))
    assert manifest["aggregate_sha256"] == captured.aggregate_sha256
    assert manifest["source_spreadsheet_id"] == CFO_ID
    bank = manifest["captures"]["bank-checking"]
    assert bank["tab_id"] == 1001
    assert bank["observed_first"] == "2030-01-05" and bank["observed_last"] == "2030-02-01"
    assert bank["captured_at"].endswith("Z")
    assert len(bank["sha256"]) == 64
    text = stored.manifest_path.read_text(encoding="utf-8")
    assert "Deposit Example Store payout" not in text and "1,250.00" not in text
    full = json.loads(stored.path.read_text(encoding="utf-8"))
    assert full["captures"]["bank-checking"]["values"][1] == BANK_ROWS[0]


def test_row_edits_are_revisions_and_fingerprint_changes_are_missing_plus_added(
    tmp_path: Path,
) -> None:
    before = normalize(Harness(_config(tmp_path)).capture())

    edited = [list(row) for row in BANK_ROWS]
    edited[1][7] = "Field Trips"  # category edit keeps identity
    edited[2][1] = "Transfer to reserve"  # description edit changes the fingerprint
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *edited], sheet_id=1001)})
    after_capture = Harness(_config(tmp_path), cfo).capture()
    after = normalize(after_capture)

    changes = compare_transactions(before, after)
    kinds = sorted(change.kind for change in changes)
    assert kinds == ["added", "missing", "revised"]
    revised = next(c for c in changes if c.kind == "revised")
    assert revised.record_key == _by_alias(before, "bank-checking")[1].record_key
    assert revised.previous_revision != revised.current_revision


def test_reordered_rows_keep_their_record_keys(tmp_path: Path) -> None:
    before = normalize(Harness(_config(tmp_path)).capture())
    reordered = list(reversed(BANK_ROWS))
    cfo = _cfo_worksheets(
        **{"Bank Checking": CfoWorksheet([BANK_HEADER, *reordered], sheet_id=1001)}
    )
    after = normalize(Harness(_config(tmp_path), cfo).capture())
    assert compare_transactions(before, after) == ()
    assert sorted(t.record_key for t in before) == sorted(t.record_key for t in after)


def test_changed_source_capture_is_detected(tmp_path: Path) -> None:
    first = Harness(_config(tmp_path)).capture()
    rows = [list(row) for row in BANK_ROWS]
    rows[0][2] = "1,250.01"
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    second = Harness(_config(tmp_path), cfo).capture()
    assert compare_captures(first, second) == ("bank-checking",)
    assert first.aggregate_sha256 != second.aggregate_sha256


def test_source_change_mid_capture_retries_whole_capture_once(tmp_path: Path) -> None:
    changed = [BANK_HEADER, *BANK_ROWS[:-1]]
    stable = [BANK_HEADER, *BANK_ROWS]
    bank = CfoWorksheet(stable, sheet_id=1001, versions=[changed, stable, stable])
    harness = Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank}))
    captured = harness.capture()
    assert captured.consistency.attempts == 2
    assert captured.consistency.changed_aliases == ("bank-checking",)
    assert captured.by_alias["bank-checking"].values[-1] == tuple(BANK_ROWS[-1])


def test_source_changing_on_every_attempt_fails_closed(tmp_path: Path) -> None:
    grids = [[BANK_HEADER, *BANK_ROWS[: n + 1]] for n in range(6)]
    bank = CfoWorksheet(grids[0], sheet_id=1001, versions=grids)
    harness = Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank}))
    with pytest.raises(SourceCaptureError) as caught:
        harness.capture()
    assert caught.value.code == "capture_inconsistent"
    harness.assert_no_writes()


# --------------------------------------------------------------------------------------
# Schema, missing fields, coverage
# --------------------------------------------------------------------------------------


def test_header_drift_and_tab_identity_fail_closed(tmp_path: Path) -> None:
    drifted = [*BANK_HEADER[:-1], "FINAL CAT"]
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([drifted, *BANK_ROWS], sheet_id=1001)})
    with pytest.raises(SourceSchemaError) as caught:
        Harness(_config(tmp_path), cfo).capture()
    assert caught.value.code == "header_signature_mismatch"

    moved = _cfo_worksheets(
        **{"Bank Checking": CfoWorksheet([BANK_HEADER, *BANK_ROWS], sheet_id=9999)}
    )
    with pytest.raises(SourceSchemaError) as caught:
        Harness(_config(tmp_path), moved).capture()
    assert caught.value.code == "tab_id_mismatch"


def test_signature_missing_a_required_column_is_rejected_before_reads(tmp_path: Path) -> None:
    config = _config(tmp_path, bank_signature=(BANK_HEADER[:-1],))
    with pytest.raises(SourceConfigError) as caught:
        require_bindings(config)
    assert caught.value.code == "missing_column"


@pytest.mark.parametrize(
    ("row_index", "column", "value", "code", "field"),
    [
        (1, 2, "", "missing_value", "amount"),
        (1, 0, "", "missing_value", "date"),
        (1, 0, "13/45/2030", "invalid_date", "date"),
        (1, 2, "12.345", "invalid_money", "amount"),
        (1, 2, "12,34", "invalid_money", "amount"),
        (1, 2, "twelve", "invalid_money", "amount"),
        (0, 7, "Fundraiser Income: 1,280.00, Processing Fees: -29.00", "split_sum_mismatch", None),
        (0, 7, "Fundraiser Income: 1,280.00, Processing Fees", "unparseable_split", None),
    ],
)
def test_bank_row_errors_are_explicit_and_redacted(
    tmp_path: Path,
    row_index: int,
    column: int,
    value: str,
    code: str,
    field: str | None,
) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows[row_index][column] = value
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    captured = Harness(_config(tmp_path), cfo).capture()

    result = normalize_with_report(captured)
    errors = [(i.row_number, i.code, i.field) for i in result.errors]
    assert errors == [(row_index + 2, code, field or "final_category")]
    bank_rows = [t.refs[0].row_number for t in _by_alias(result.transactions, "bank-checking")]
    assert row_index + 2 not in bank_rows and len(bank_rows) == 5

    with pytest.raises(SourceValidationError) as caught:
        normalize(captured)
    message = str(caught.value)
    assert code in message and f"row {row_index + 2}" in message
    assert "1,280.00" not in message and "Check 1001" not in message


def test_unsupported_currency_and_missing_final_category(tmp_path: Path) -> None:
    wix_rows = [list(row) for row in WIX_ROWS]
    wix_rows[0][4] = "CAD"
    bank_rows = [list(row) for row in BANK_ROWS]
    bank_rows[3][5] = bank_rows[3][7] = ""
    bank_rows[1][7] = ""  # override still present: fallback warning, not an error
    cfo = _cfo_worksheets(
        **{
            "Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix_rows], sheet_id=1002),
            "Bank Checking": CfoWorksheet([BANK_HEADER, *bank_rows], sheet_id=1001),
        }
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    found = {(i.source_alias, i.row_number, i.code, i.severity) for i in result.issues}
    assert ("wix", 3, "unsupported_currency", "error") in found
    assert ("bank-checking", 5, "missing_value", "error") in found
    assert ("bank-checking", 3, "final_category_fallback", "warning") in found
    fallback = next(
        t for t in result.transactions if t.refs[0].row_number == 3 and t.source_kind == "bank"
    )
    assert fallback.final_category is None
    assert [a.category for a in fallback.allocations] == ["Classroom Supplies"]


def test_missing_coverage_is_explicit(tmp_path: Path) -> None:
    captured = Harness(_config(tmp_path)).capture()
    bank = captured.by_alias["bank-checking"]
    assert bank.observed_first == date(2030, 1, 5)
    assert bank.observed_last == date(2030, 2, 1)
    assert "observed_outside_declared_coverage" in bank.warnings
    assert captured.by_alias["paypal"].warnings == ("no_declared_coverage",)

    status = coverage_status(bank, date(2030, 1, 1), date(2031, 1, 1))
    assert not status.complete
    assert status.uncovered == ((date(2030, 2, 1), date(2031, 1, 1)),)
    january = coverage_status(bank, date(2030, 1, 1), date(2030, 2, 1))
    assert january.complete and january.uncovered == ()
    paypal = coverage_status(captured.by_alias["paypal"], date(2030, 1, 1), date(2030, 2, 1))
    assert paypal.uncovered == ((date(2030, 1, 1), date(2030, 2, 1)),)
    assert paypal.observed_first == date(2030, 1, 4)


# --------------------------------------------------------------------------------------
# Parsers and the retired bank-PDF path
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.56", Decimal("1234.56")),
        ("$1,234.5", Decimal("1234.50")),
        ("-$3.00", Decimal("-3.00")),
        ("$-3.00", Decimal("-3.00")),
        ("(3.00)", Decimal("-3.00")),
        ("  ", None),
    ],
)
def test_parse_money_is_exact(raw: str, expected: Decimal | None) -> None:
    assert parse_money(raw) == expected


def test_parse_source_date_and_allocations() -> None:
    assert parse_source_date("1/5/2030") == date(2030, 1, 5)
    assert parse_source_date("2030-01-05") == date(2030, 1, 5)
    assert parse_source_date("2030-01-05T23:30:00-08:00") == date(2030, 1, 5)
    assert parse_source_date("Jan 5, 2030") == date(2030, 1, 5)
    assert parse_source_date("") is None
    assert parse_allocations("Programs: Field Trips", Decimal("-5.00")) == (
        ("Programs: Field Trips", Decimal("-5.00")),
    )
    assert parse_allocations("A: 1,000.00, B: -3.00", Decimal("997.00")) == (
        ("A", Decimal("1000.00")),
        ("B", Decimal("-3.00")),
    )
    assert classify_status("Mystery") == "unknown"


def test_record_key_shape() -> None:
    key = make_record_key("bank-checking", ["bank", "2030-01-05"], 2)
    prefix, alias, digest, occurrence = key.split(":")
    assert (prefix, alias, occurrence) == ("v1", "bank-checking", "2")
    assert len(digest) == 64
    with pytest.raises(ValueError):
        make_record_key("Bad Alias", ["x"], 0)


def test_main_reports_package_never_imports_bank_pdf_extraction() -> None:
    package = Path(sources.__file__).resolve().parent
    forbidden = ("treasurer_slides", "pypdfium2", "bank_statements", "receipt_pdf_render")
    for module in package.glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            assert not any(part in name for name in names for part in forbidden), module.name


def test_duplicate_or_reserved_bindings_are_rejected(tmp_path: Path) -> None:
    second_pnl = _source_toml("pnl-two", "pnl", "Second P&L", [])
    path = tmp_path / "config.toml"
    path.write_text(_FULL_CONFIG + main_reports_toml() + second_pnl, encoding="utf-8")
    with pytest.raises(SourceConfigError) as caught:
        require_bindings(load_config(path))
    assert caught.value.code == "duplicate_binding"

    same_tab = _source_toml("bank-savings", "bank", "Bank Checking", [BANK_HEADER])
    path.write_text(_FULL_CONFIG + main_reports_toml() + same_tab, encoding="utf-8")
    with pytest.raises(SourceConfigError) as caught:
        require_bindings(load_config(path))
    assert caught.value.code == "duplicate_tab_binding"


# --------------------------------------------------------------------------------------
# Redaction, WIX/PayPal shapes, vocabulary ownership and robustness
# --------------------------------------------------------------------------------------

CANARY = "CANARY-PAYEE-7731"
CANARY_AMOUNT = "9,876.54"


def test_header_mismatch_error_never_echoes_cell_values(tmp_path: Path) -> None:
    # A data row slides into the header position (rows deleted above it).
    shifted = ["1/5/2030", CANARY, CANARY_AMOUNT, "", "Posted", "Fees", "", "Fees"]
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([shifted, *BANK_ROWS], sheet_id=1001)})
    with pytest.raises(SourceSchemaError) as caught:
        Harness(_config(tmp_path), cfo).capture()
    message = str(caught.value)
    assert caught.value.code == "header_signature_mismatch"
    assert CANARY not in message and CANARY_AMOUNT not in message and "1/5/2030" not in message
    assert caught.value.positions == tuple((0, column) for column in range(8))


def test_no_error_or_issue_text_echoes_a_canary_cell(tmp_path: Path) -> None:
    """Every error path reached by a canary-bearing bad row stays value-free."""
    bank = [list(row) for row in BANK_ROWS]
    bank[0][1] = CANARY
    bank[0][2] = CANARY  # invalid money that IS the canary
    bank[1][1] = CANARY
    bank[1][7] = f"{CANARY}: 1.00, Other: {CANARY_AMOUNT}"  # split sum mismatch
    wix = [list(row) for row in WIX_ROWS]
    wix[0][4] = CANARY  # unsupported currency
    wix[1][1] = CANARY  # invalid date
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal[0][7] = CANARY_AMOUNT + "9"  # still exact cents but a canary amount
    paypal[3][4] = CANARY  # unknown type warning
    paypal[4][9] = ""  # missing net
    cfo = _cfo_worksheets(
        **{
            "Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001),
            "Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix], sheet_id=1002),
            "Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003),
        }
    )
    captured = Harness(_config(tmp_path), cfo).capture()
    result = normalize_with_report(captured)
    assert len(result.errors) >= 5
    rendered = json.dumps([issue.to_dict() for issue in result.issues])
    with pytest.raises(SourceValidationError) as caught:
        normalize(captured)
    for text in (rendered, str(caught.value)):
        assert CANARY not in text and CANARY_AMOUNT not in text


def test_wix_and_paypal_subtotal_rows_are_excluded_explicitly(tmp_path: Path) -> None:
    result = normalize_with_report(Harness(_config(tmp_path)).capture())
    excluded = {(row.source_alias, row.row_number) for row in result.excluded}
    assert {("wix", 9), ("paypal", 9)} <= excluded
    assert all(
        txn.refs[0].row_number != 9 for txn in result.transactions if txn.source_kind != "bank"
    )
    assert result.errors == ()


@pytest.mark.parametrize(
    ("column", "code", "field"),
    [
        (10, "missing_value", "transaction_id"),
        (0, "missing_value", "date"),
        (4, "missing_value", "type"),
        (5, "missing_value", "status"),
        (6, "missing_value", "currency"),
        (7, "missing_value", "gross"),
        (9, "missing_value", "net"),
    ],
)
def test_paypal_parent_row_missing_required_fields(
    tmp_path: Path, column: int, code: str, field: str
) -> None:
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal[4][column] = ""  # General Withdrawal parent row (sheet row 6)
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert [(i.source_alias, i.row_number, i.code, i.field) for i in result.errors] == [
        ("paypal", 6, code, field)
    ]
    assert all(t.refs[0].row_number != 6 for t in _by_alias(result.transactions, "paypal"))


def test_paypal_detail_rows_may_omit_parent_only_fields(tmp_path: Path) -> None:
    paypal = [list(row) for row in PAYPAL_ROWS]
    for column in (5, 6, 7, 9):  # status, currency, gross, net
        paypal[1][column] = ""
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert result.errors == ()
    detail = next(
        t for t in result.transactions if t.refs[0].row_number == 3 and t.source_kind == "paypal"
    )
    assert detail.row_role == "detail" and detail.gross is None and detail.source_status is None
    assert detail.parent_key is not None


def test_wix_row_without_provider_id_gets_warned_stable_fallback_key(tmp_path: Path) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[0][0] = ""
    cfo = _cfo_worksheets(
        **{"Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix], sheet_id=1002)}
    )
    first = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert ("wix", 3, "missing_native_id", "warning") in {
        (i.source_alias, i.row_number, i.code, i.severity) for i in first.issues
    }
    fallback = next(t for t in first.transactions if t.source_kind == "wix" and t.native_id is None)
    reordered = [wix[-2], *wix[:-2], wix[-1]]
    cfo2 = _cfo_worksheets(
        **{"Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *reordered], sheet_id=1002)}
    )
    second = normalize(Harness(_config(tmp_path), cfo2).capture())
    again = next(t for t in second if t.source_kind == "wix" and t.native_id is None)
    assert again.record_key == fallback.record_key
    assert again.revision_hash == fallback.revision_hash


def test_oversized_money_cell_is_a_row_issue_not_a_crash(tmp_path: Path) -> None:
    bank = [list(row) for row in BANK_ROWS]
    bank[1][2] = "1" * 30
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001)})
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [
        (3, "invalid_money", "amount")
    ]


def test_entered_number_cross_check_rejects_hidden_sub_cent_precision(tmp_path: Path) -> None:
    entered: list[list[object]] = [list(BANK_HEADER), *([*row] for row in BANK_ROWS)]
    entered[2][2] = -75.505  # displayed "-75.50", entered with sub-cent precision
    entered[4][2] = -3  # entered integer matching "-3.00": fine
    bank = CfoWorksheet([BANK_HEADER, *BANK_ROWS], sheet_id=1001, formulas=entered)
    captured = Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank})).capture()
    numbers = captured.by_alias["bank-checking"].entered_numbers
    assert [(n.row, n.column, n.value) for n in numbers] == [(2, 2, "-75.505"), (4, 2, "-3")]
    result = normalize_with_report(captured)
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [
        (3, "display_precision_mismatch", "amount")
    ]


def test_credit_card_population_is_a_warning_even_with_a_new_header(tmp_path: Path) -> None:
    cfo = _cfo_worksheets(
        **{
            "Credit Card Transactions": CfoWorksheet(
                [["Posted", "Merchant", "Charge"], ["1/3/2030", "Example vendor", "-9.99"]],
                sheet_id=1007,
            )
        }
    )
    captured = Harness(_config(tmp_path), cfo).capture()
    assert captured.by_alias["credit-card"].warnings == (
        "uncovered_source_populated",
        "header_signature_changed",
    )


def test_credit_card_may_be_bound_with_no_signature_while_empty(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    text = _FULL_CONFIG + main_reports_toml(omit=("credit-card",))
    text += _source_toml("credit-card", "credit_card", "Credit Card Transactions", [])
    path.write_text(text, encoding="utf-8")
    cfo = _cfo_worksheets(**{"Credit Card Transactions": CfoWorksheet([], sheet_id=1007)})
    captured = Harness(load_config(path), cfo).capture()
    assert captured.by_alias["credit-card"].warnings == ()


def test_adopted_budget_measure_matches_the_existing_adapter_rule(tmp_path: Path) -> None:
    harness = Harness(_config(tmp_path))
    grid = harness.own_sheets[report_source.BUDGET_TIMESERIES_TAB].grid
    grid[1][3] = " Proposed "
    grid.append(["2030", "Programs", "expense", "forecast", "1", "FALSE", "", "Other", "x"])
    budget = harness.capture().adopted_budget
    assert [row["raw_category"] for row in budget.rows_as_dicts()] == [
        "Classroom Supplies",
        "Fundraiser Income",
    ]
    assert budget.warnings == ("unrecognized_measure",)
    assert budget.excluded_non_adopted_rows == 2
    # Same recognition rule as the legacy projection (one owner: report_source.row_measure).
    budget_rows, _ = report_source.to_inputs(
        report_source.read_timeseries(harness.own()), start_month=7
    )
    assert {row["category"] for row in budget_rows} == {"Classroom Supplies", "Fundraiser Income"}


def test_coverage_declaration_changes_the_capture_hash(tmp_path: Path) -> None:
    first = Harness(_config(tmp_path)).capture()
    path = tmp_path / "config.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('end = "2030-01-31"', 'end = "2030-02-28"'),
        encoding="utf-8",
    )
    changed = Harness(load_config(path)).capture()
    assert compare_captures(first, changed) == ("bank-checking",)
    assert first.aggregate_sha256 != changed.aggregate_sha256
    assert "observed_outside_declared_coverage" not in changed.by_alias["bank-checking"].warnings


def test_trailing_padding_never_changes_revisions_or_detail_keys(tmp_path: Path) -> None:
    before = normalize(Harness(_config(tmp_path)).capture())
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal[2] = [*paypal[2], "", "", "stray note"]  # one row widens the whole grid
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003)}
    )
    after = normalize(Harness(_config(tmp_path), cfo).capture())
    changes = compare_transactions(before, after)
    # Only the row that actually gained content changes; padding elsewhere is ignored.
    assert len(changes) == 2 and {c.kind for c in changes} == {"added", "missing"}


def test_duplicate_native_ids_and_ambiguous_duplicates_are_reviewable(tmp_path: Path) -> None:
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal.insert(5, list(paypal[4]))  # repeated General Withdrawal, same Transaction ID
    bank = [list(row) for row in BANK_ROWS]
    bank[4][7] = "Bank Fees"  # twin fee rows now differ only in category
    cfo = _cfo_worksheets(
        **{
            "Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003),
            "Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001),
        }
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    warnings = {(i.source_alias, i.row_number, i.code) for i in result.warnings}
    assert {("paypal", 6, "duplicate_native_id"), ("paypal", 7, "duplicate_native_id")} <= warnings
    assert {
        ("bank-checking", 5, "ambiguous_duplicate_identity"),
        ("bank-checking", 6, "ambiguous_duplicate_identity"),
    } <= warnings
    # Identical legitimate twins (default fixture) and identical PayPal details are not warned.
    plain = normalize_with_report(Harness(_config(tmp_path)).capture())
    assert not [i for i in plain.issues if "duplicate" in i.code]


def test_unrecognized_paypal_type_is_flagged_not_silently_a_sale(tmp_path: Path) -> None:
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal[0][4] = "Mystery Movement"
    paypal[4][4] = "Withdraw Funds to a Bank Account"
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert ("paypal", 2, "unknown_type") in {
        (i.source_alias, i.row_number, i.code) for i in result.warnings
    }
    withdrawal = next(t for t in result.transactions if t.native_id == "TXN-EX-3")
    assert withdrawal.row_role == "transfer"


def test_summary_detection_is_linear_on_hostile_cells(tmp_path: Path) -> None:

    bank = [list(row) for row in BANK_ROWS]
    bank[5][1] = "sub" + " " * 50_000 + "x"  # the former quadratic shape, Sheets max length
    bank[5][3] = " " * 50_000
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001)})
    captured = Harness(_config(tmp_path), cfo).capture()
    started = time.perf_counter()
    normalize_with_report(captured)
    assert time.perf_counter() - started < 1.0


def test_source_workbook_must_not_be_our_own_workbook(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        _FULL_CONFIG + main_reports_toml().replace(CFO_ID, "fake-spreadsheet-id"),
        encoding="utf-8",
    )
    with pytest.raises(SourceConfigError) as caught:
        require_bindings(load_config(path))
    assert caught.value.code == "source_is_own_workbook"


def test_vocabularies_have_one_owner() -> None:
    from pta_finance import config as config_module

    assert config_module.SOURCE_KINDS is models.SOURCE_KINDS
    assert sources.SOURCE_KINDS is models.SOURCE_KINDS
    assert tuple(sources.ADAPTERS) == models.SOURCE_KINDS
    statuses = {
        classify_status(text)
        for text in (
            "Completed",
            "Refunded",
            "Partially Refunded",
            "Chargeback",
            "Declined",
            "Authorized",
            "Pending",
            "Reversed",
            "Mystery",
        )
    }
    assert statuses <= set(models.STATUS_CLASSES)
    roles = {
        sources.classify_paypal_type(text)[0]
        for text in (
            "Shopping Cart Item",
            "Partner Fee",
            "General Withdrawal",
            "Payment Refund",
            "Website Payment",
            "Mystery",
            "Transfer Fee",
        )
    }
    assert roles <= set(models.ROW_ROLES)


# --------------------------------------------------------------------------------------
# Strict money shape, exception chains, summary rows, precision and the capture store
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234,567.8", Decimal("1234567.80")),
        ("$ 1,234.56", Decimal("1234.56")),
        ("$ (5.00)", Decimal("-5.00")),
        ("$(5.00)", Decimal("-5.00")),
        ("($5.00)", Decimal("-5.00")),
        ("+5", Decimal("5.00")),
        ("1234", Decimal("1234.00")),
    ],
)
def test_parse_money_accepts_exact_display_shapes(raw: str, expected: Decimal) -> None:
    assert parse_money(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "12,34",
        "1,2,3",
        "1,,5",
        "1,2,3,4.00",
        "12,3456",
        ",123",
        "1.",
        ".50",
        "-(5.00)",
        "$--1",
        "($-5.00)",
        "1 234",
        "12.345",
        "--",
        "$",
        "1.001",
        "--1",
        "(-1.00)",
        "NaN",
        "1e3",
        "USD 1",
        "$$1",
        "(1.00",
        "1" * 30,
    ],
)
def test_parse_money_rejects_mis_grouped_or_malformed_text(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid_money"):
        parse_money(raw)


@pytest.mark.parametrize("raw", ["1.00.00", "12,34", "1" * 30, CANARY, f"{CANARY_AMOUNT}x"])
def test_parse_money_exceptions_carry_no_cell_text_in_their_chain(raw: str) -> None:
    with pytest.raises(ValueError) as caught:
        parse_money(raw)
    error = caught.value
    assert error.__cause__ is None and error.__context__ is None
    assert str(error) in {"invalid_money", "money_precision"}
    assert raw not in str(error) and raw not in repr(error)


def test_summary_label_in_primary_column_is_excluded_with_a_warning(tmp_path: Path) -> None:
    bank = [list(row) for row in BANK_ROWS]
    bank.append(["Ending Balance:", "", "1,000.00", "", "", "", "", ""])
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001)})
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert ("bank-checking", 9, "summary_row") in {
        (row.source_alias, row.row_number, row.reason) for row in result.excluded
    }
    assert result.errors == ()
    excluded_warnings = [
        (i.source_alias, i.row_number) for i in result.warnings if i.code == "summary_row_excluded"
    ]
    assert sorted(excluded_warnings) == [
        ("bank-checking", 7),
        ("bank-checking", 9),
        ("paypal", 9),
        ("wix", 9),
    ]


def test_description_starting_with_total_is_never_silently_dropped(tmp_path: Path) -> None:
    bank = [list(row) for row in BANK_ROWS]
    bank.append(["", "Total Wine #12", "-45.10", "", "Posted", "Supplies", "", "Supplies"])
    bank.append(
        ["2/2/2030", "Totally Fun Store", "-9.00", "", "Posted", "Supplies", "", "Supplies"]
    )
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001)})
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert 9 not in {
        row.row_number for row in result.excluded if row.source_alias == "bank-checking"
    }
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [
        (9, "missing_value", "date")
    ]
    kept = [t for t in result.transactions if t.description == "Totally Fun Store"]
    assert len(kept) == 1 and kept[0].gross == Decimal("-9.00")


def _entered_bank(cell_overrides: dict[tuple[int, int], object]) -> CfoWorksheet:
    entered: list[list[object]] = [list(BANK_HEADER), *([*row] for row in BANK_ROWS)]
    for (row, column), value in cell_overrides.items():
        entered[row][column] = value
    return CfoWorksheet([BANK_HEADER, *BANK_ROWS], sheet_id=1001, formulas=entered)  # type: ignore[arg-type]


def test_precision_check_tolerates_binary_float_noise(tmp_path: Path) -> None:
    bank = _entered_bank({(2, 2): -75.50000000000001, (4, 2): -2.9999999999999996})
    result = normalize_with_report(
        Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank})).capture()
    )
    assert result.errors == ()


def test_formula_money_cell_is_flagged_unverified_not_silently_accepted(tmp_path: Path) -> None:
    bank = _entered_bank({(2, 2): "=-75.5*1", (4, 2): "=B5*0.0725"})
    result = normalize_with_report(
        Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank})).capture()
    )
    assert result.errors == ()
    flagged = [
        (i.row_number, i.field) for i in result.warnings if i.code == "formula_money_unverified"
    ]
    assert flagged == [(3, "amount"), (5, "amount")]


def test_split_parsing_is_linear_on_hostile_category_text(tmp_path: Path) -> None:
    hostile = "a:," + " " * 50_000 + "x"
    started = time.perf_counter()
    assert parse_allocations(hostile, Decimal("1.00")) == ((hostile, Decimal("1.00")),)
    assert parse_allocations("a:" + ", b" * 20_000, Decimal("1.00"))[0][1] == Decimal("1.00")
    assert time.perf_counter() - started < 1.0

    bank = [list(row) for row in BANK_ROWS]
    bank[1][7] = hostile
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *bank], sheet_id=1001)})
    captured = Harness(_config(tmp_path), cfo).capture()
    started = time.perf_counter()
    normalize_with_report(captured)
    assert time.perf_counter() - started < 1.0


def test_store_rejects_non_hex_digest(tmp_path: Path) -> None:
    captured = Harness(_config(tmp_path)).capture()
    forged = dataclasses.replace(captured, aggregate_sha256="../../escape")
    with pytest.raises(SourceCaptureError) as caught:
        store_capture_set(forged, _store_root(tmp_path))
    assert caught.value.code == "invalid_digest"
    assert not (_store_root(tmp_path).parent / "escape.json").exists()


def test_store_recomputes_content_hashes_instead_of_trusting_them(tmp_path: Path) -> None:
    captured = Harness(_config(tmp_path)).capture()
    root = _store_root(tmp_path)
    stored = store_capture_set(captured, root)
    data = json.loads(stored.path.read_text(encoding="utf-8"))
    data["captures"]["bank-checking"]["values"][1][2] = "9,999.99"  # declared hashes intact
    stored.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SourceCaptureError) as caught:
        store_capture_set(captured, root)
    assert caught.value.code == "stored_capture_conflict"


def test_changed_capture_is_stored_beside_the_first(tmp_path: Path) -> None:
    root = _store_root(tmp_path)
    first = store_capture_set(Harness(_config(tmp_path)).capture(), root)
    rows = [list(row) for row in BANK_ROWS]
    rows[0][2] = "1,250.01"
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    second = store_capture_set(Harness(_config(tmp_path), cfo).capture(), root)
    assert first.created and second.created and first.path != second.path
    assert first.path.exists() and second.path.exists()
    assert not store_capture_set(Harness(_config(tmp_path)).capture(), root).created


def test_budget_schema_drift_fails_closed(tmp_path: Path) -> None:
    harness = Harness(_config(tmp_path))
    grid = harness.own_sheets[report_source.BUDGET_TIMESERIES_TAB].grid
    grid[0] = ["origin" if cell == "source_tab" else cell for cell in grid[0]]
    with pytest.raises(SourceSchemaError) as caught:
        harness.capture()
    assert caught.value.code == "budget_schema_mismatch"


def test_empty_budget_and_empty_feed_are_explicit_warnings(tmp_path: Path) -> None:
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER], sheet_id=1001)})
    harness = Harness(_config(tmp_path), cfo)
    harness.own_sheets[report_source.BUDGET_TIMESERIES_TAB].grid = [
        list(report_source.TIMESERIES_COLUMNS)
    ]
    captured = harness.capture()
    assert captured.adopted_budget.warnings == ("no_budget_rows",)
    assert captured.adopted_budget.rows == ()
    assert captured.by_alias["bank-checking"].warnings == ("no_data_rows",)
    assert _by_alias(normalize(captured), "bank-checking") == []


def test_ambiguous_paypal_parent_is_a_warning(tmp_path: Path) -> None:
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal.insert(1, list(paypal[0]))  # two payment rows share TXN-EX-1
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    ambiguous = sorted(i.row_number for i in result.warnings if i.code == "ambiguous_parent")
    assert ambiguous == [4, 5]
    details = [t for t in result.transactions if t.row_role == "detail"]
    assert details and all(t.parent_key is None for t in details)


def test_unknown_status_is_warned_for_wix_and_paypal(tmp_path: Path) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[0][9] = "Mystery"
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal[0][5] = "Mystery"
    cfo = _cfo_worksheets(
        **{
            "Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix], sheet_id=1002),
            "Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003),
        }
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    found = {(i.source_alias, i.row_number, i.code, i.field) for i in result.warnings}
    assert ("wix", 3, "unknown_status", "transaction_status") in found
    assert ("paypal", 2, "unknown_status", "status") in found
    assert result.errors == ()


@pytest.mark.parametrize(
    ("column", "field"),
    [
        (5, "amount"),
        (1, "payment_date"),
        (2, "transaction_datetime"),
        (9, "transaction_status"),
        (11, "payment_provider"),
    ],
)
def test_wix_required_fields_missing_are_row_errors(
    tmp_path: Path, column: int, field: str
) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[3][column] = ""  # sheet row 6
    cfo = _cfo_worksheets(
        **{"Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix], sheet_id=1002)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert [(i.source_alias, i.row_number, i.code, i.field) for i in result.errors] == [
        ("wix", 6, "missing_value", field)
    ]
    assert 6 not in {t.refs[0].row_number for t in _by_alias(result.transactions, "wix")}


def test_own_workbook_is_also_read_through_a_readonly_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    harness = Harness(config)

    class DispatchClient(TimeoutClient):
        def open_by_key(self, key: str) -> FakeSpreadsheet:
            self.opened_keys.append(key)
            return harness.cfo_spreadsheet if key == CFO_ID else harness.own_spreadsheet

    calls: list[dict[str, Any]] = []
    client = DispatchClient(harness.cfo_spreadsheet)

    def fake_service_account(**kwargs: Any) -> DispatchClient:
        calls.append(kwargs)
        return client

    monkeypatch.setattr(sources.gspread, "service_account", fake_service_account)
    captured = capture(config, clock=_clock())
    assert len(calls) == 2
    assert all(call["scopes"] == [READONLY_SCOPE] for call in calls)
    assert set(client.opened_keys) == {CFO_ID, "fake-spreadsheet-id"}
    assert captured.adopted_budget.rows
    harness.assert_no_writes()


# --------------------------------------------------------------------------------------
# Dash placeholders, -0.00, date range, inherited currency and dated summary rows
# --------------------------------------------------------------------------------------


def _bank_sheet(values: list[list[str]], entered: dict[tuple[int, int], object]) -> CfoWorksheet:
    grid: list[list[object]] = [list(BANK_HEADER), *([*row] for row in values)]
    for (row, column), value in entered.items():
        grid[row][column] = value
    return CfoWorksheet([BANK_HEADER, *values], sheet_id=1001, formulas=grid)  # type: ignore[arg-type]


def test_parse_money_dash_needs_corroboration_and_never_chains() -> None:
    for raw in ("$ -", " - ", "$-", "-"):
        assert is_dash_placeholder(raw)
        with pytest.raises(ValueError) as caught:
            parse_money(raw)
        assert str(caught.value) == "dash_placeholder"
        assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not is_dash_placeholder("--") and not is_dash_placeholder("-5")


def test_accounting_zero_with_numeric_zero_entered_value_is_exact_zero(tmp_path: Path) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows[3][2] = "$ -"  # sheet row 5: displayed Accounting zero, entered numeric 0
    bank = _bank_sheet(rows, {(4, 2): 0})
    result = normalize_with_report(
        Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank})).capture()
    )
    assert result.errors == ()
    zero = next(t for t in result.transactions if t.refs[0].row_number == 5)
    assert zero.gross == Decimal("0.00") and str(zero.gross) == "0.00"


def test_text_dash_in_required_money_field_is_a_row_issue(tmp_path: Path) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows[3][2] = "-"  # text placeholder: no entered number proves zero
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [
        (5, "missing_value", "amount")
    ]
    assert 5 not in {t.refs[0].row_number for t in _by_alias(result.transactions, "bank-checking")}


def test_text_dash_in_optional_money_field_is_absent_with_a_warning(tmp_path: Path) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[0][10] = "$ -"  # refund amount (optional), sheet row 3
    cfo = _cfo_worksheets(
        **{"Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix], sheet_id=1002)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert result.errors == ()
    assert ("wix", 3, "dash_placeholder", "refund_amount") in {
        (i.source_alias, i.row_number, i.code, i.field) for i in result.warnings
    }
    first = next(t for t in result.transactions if t.native_id == "pi_example_001")
    assert first.refund is None


@pytest.mark.parametrize(
    "final_category",
    ["Fundraising: -", "Fundraiser Income: -75.50, Processing Fees: $ -"],
)
def test_dash_split_component_is_a_placeholder_not_a_sum_mismatch(
    tmp_path: Path, final_category: str
) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows[1][7] = final_category  # sheet row 3, amount -75.50
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [
        (3, "split_dash_placeholder", "final_category")
    ]


def test_negative_zero_is_one_canonical_amount_and_identity(tmp_path: Path) -> None:
    assert str(parse_money("-0.00")) == "0.00" and str(parse_money("(0.00)")) == "0.00"
    assert models.money_str(Decimal("-0.00")) == "0.00"

    def bank_key(amount_text: str) -> str:
        rows = [list(row) for row in BANK_ROWS]
        rows[2][2] = amount_text  # sheet row 4
        cfo = _cfo_worksheets(
            **{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)}
        )
        txns = normalize(Harness(_config(tmp_path), cfo).capture())
        return next(t.record_key for t in txns if t.refs[0].row_number == 4)

    assert bank_key("-0.00") == bank_key("0.00")


def test_far_future_dates_are_row_issues_not_overflows(tmp_path: Path) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows[1][0] = "12/31/9999"
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    captured = Harness(_config(tmp_path), cfo).capture()  # no OverflowError
    assert captured.by_alias["bank-checking"].observed_last == date(2030, 2, 1)
    result = normalize_with_report(captured)
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [
        (3, "date_out_of_range", "date")
    ]
    with pytest.raises(ValueError, match="date_out_of_range"):
        parse_source_date("9999-12-31")

    path = tmp_path / "config.toml"
    path.write_text(
        _FULL_CONFIG + main_reports_toml().replace('end = "2030-01-31"', 'end = "9999-12-31"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "main_reports.sources.bank-checking.coverage[0].end"


def test_paypal_detail_currency_is_inherited_or_unresolved_never_assumed(tmp_path: Path) -> None:
    paypal = [list(row) for row in PAYPAL_ROWS]
    paypal[1][6] = ""  # detail row 3 with a parent: inherits explicitly
    orphan = list(_DETAIL)
    orphan[10] = "TXN-EX-9"
    orphan[6] = ""  # orphan detail without currency: cannot be resolved
    paypal.append(orphan)  # sheet row 10 (after the Total row)
    cfo = _cfo_worksheets(
        **{"Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *paypal], sheet_id=1003)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    inherited = next(
        t for t in result.transactions if t.source_kind == "paypal" and t.refs[0].row_number == 3
    )
    assert inherited.currency == "USD" and inherited.parent_key is not None
    assert [(i.source_alias, i.row_number, i.code, i.field) for i in result.errors] == [
        ("paypal", 10, "currency_unresolved", "currency")
    ]
    assert 10 not in {t.refs[0].row_number for t in _by_alias(result.transactions, "paypal")}


def test_dated_summary_label_is_excluded_but_dated_store_name_is_kept(tmp_path: Path) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows.append(["1/31/2030", "Ending balance", "1,000.00", "", "", "", "", ""])  # row 9
    rows.append(["1/20/2030", "Total Wine #12", "-45.10", "", "Posted", "Supplies", "", "Supplies"])
    cfo = _cfo_worksheets(**{"Bank Checking": CfoWorksheet([BANK_HEADER, *rows], sheet_id=1001)})
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert ("bank-checking", 9) in {(r.source_alias, r.row_number) for r in result.excluded}
    assert ("bank-checking", 9, "summary_row_excluded") in {
        (i.source_alias, i.row_number, i.code) for i in result.warnings
    }
    store = [t for t in result.transactions if t.description == "Total Wine #12"]
    assert len(store) == 1 and store[0].gross == Decimal("-45.10")
    assert result.errors == ()


def test_clock_alias_is_exported() -> None:
    assert "Clock" in sources.__all__ and "is_dash_placeholder" in sources.__all__


# --------------------------------------------------------------------------------------
# Dash display over a hidden nonzero entered number, and a formula dash
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entered", "code"),
    [
        (-0.004, "display_precision_mismatch"),  # hidden amount displayed as "$ -"
        (5, "display_precision_mismatch"),
        ("=B5*0", "formula_dash_unverified"),  # computed: no entered number proves zero
    ],
)
def test_dash_display_over_unproven_value_is_a_row_error(
    tmp_path: Path, entered: object, code: str
) -> None:
    rows = [list(row) for row in BANK_ROWS]
    rows[3][2] = "$ -"  # sheet row 5, required AMOUNT
    bank = _bank_sheet(rows, {(4, 2): entered})
    result = normalize_with_report(
        Harness(_config(tmp_path), _cfo_worksheets(**{"Bank Checking": bank})).capture()
    )
    assert [(i.row_number, i.code, i.field) for i in result.errors] == [(5, code, "amount")]
    assert 5 not in {t.refs[0].row_number for t in _by_alias(result.transactions, "bank-checking")}


def test_formula_dash_in_optional_money_field_is_absent_with_a_warning(tmp_path: Path) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[0][10] = "$ -"  # refund amount (optional), sheet row 3
    entered: list[list[object]] = [list(WIX_GROUPS), list(WIX_LABELS), *([*r] for r in wix)]
    entered[2][10] = "=F3*0"
    sheet = CfoWorksheet(
        [WIX_GROUPS, WIX_LABELS, *wix],
        sheet_id=1002,
        formulas=entered,  # type: ignore[arg-type]
    )
    result = normalize_with_report(
        Harness(_config(tmp_path), _cfo_worksheets(**{"Store Transactions": sheet})).capture()
    )
    assert result.errors == ()
    assert ("wix", 3, "formula_dash_unverified", "refund_amount") in {
        (i.source_alias, i.row_number, i.code, i.field) for i in result.warnings
    }
    assert next(t for t in result.transactions if t.native_id == "pi_example_001").refund is None


# --------------------------------------------------------------------------------------
# A dash fee component never leaves a silently understated fee
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("column", [6, 7], ids=["processing_fee", "service_fee"])
def test_wix_dash_fee_component_makes_the_summed_fee_a_row_issue(
    tmp_path: Path, column: int
) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[0][column] = "$ -"  # text dash, no entered number (sheet row 3)
    cfo = _cfo_worksheets(
        **{"Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, *wix], sheet_id=1002)}
    )
    result = normalize_with_report(Harness(_config(tmp_path), cfo).capture())
    assert [(i.source_alias, i.row_number, i.code, i.field) for i in result.errors] == [
        ("wix", 3, "fee_component_unresolved", "fee")
    ]
    assert all(t.native_id != "pi_example_001" for t in result.transactions)


def test_wix_accounting_zero_fee_with_entered_zero_is_still_exact(tmp_path: Path) -> None:
    wix = [list(row) for row in WIX_ROWS]
    wix[0][7] = "$ -"  # service fee shown as Accounting zero over an entered numeric 0
    entered: list[list[object]] = [list(WIX_GROUPS), list(WIX_LABELS), *([*r] for r in wix)]
    entered[2][7] = 0
    sheet = CfoWorksheet(
        [WIX_GROUPS, WIX_LABELS, *wix],
        sheet_id=1002,
        formulas=entered,  # type: ignore[arg-type]
    )
    result = normalize_with_report(
        Harness(_config(tmp_path), _cfo_worksheets(**{"Store Transactions": sheet})).capture()
    )
    assert result.errors == ()
    first = next(t for t in result.transactions if t.native_id == "pi_example_001")
    assert first.fee == Decimal("-1.00")
    assert first.fee_components == (
        ("processing_fee", Decimal("-1.00")),
        ("service_fee", Decimal("0.00")),
    )
