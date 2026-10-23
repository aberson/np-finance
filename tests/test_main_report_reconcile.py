"""Tests for pta_finance.main_reports.reconcile — the CFO-compatible source view.

Every fixture is fictional (``Example`` placeholders, fake ids). Each scenario runs through the
production path: private config loaded by the real loader -> read-only capture over fake
gspread workbooks -> :func:`sources.normalize_with_report` -> :func:`reconcile.from_capture`.
Nothing performs a live Google call, a workbook write or a file write.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pta_finance.config import (
    CategoryCrosswalk,
    Config,
    CrosswalkEntry,
    CrosswalkTarget,
    load_config,
)
from pta_finance.main_reports import reconcile
from pta_finance.main_reports.models import (
    Allocation,
    Discrepancy,
    Reconciliation,
    Transaction,
    canonical_json_bytes,
)
from pta_finance.main_reports.reconcile import (
    DISCREPANCY_KINDS,
    INTERNAL_TRANSFER_CATEGORY,
    ReconcileError,
    ReconciliationControls,
    build,
    controls_from,
    crosswalk_amounts,
    crosswalk_digest,
    from_capture,
    parse_month_label,
    reference_token,
)
from pta_finance.main_reports.sources import UNALLOCATED_SPLIT_CATEGORY, normalize
from tests.conftest import (
    _FULL_CONFIG,
    BANK_HEADER,
    CARD_HEADER,
    MAPPING_HEADER,
    PAYPAL_HEADER,
    WIX_GROUPS,
    WIX_LABELS,
    CfoHarness,
    CfoWorksheet,
    main_reports_toml,
)

# --------------------------------------------------------------------------------------
# Fictional source shapes
# --------------------------------------------------------------------------------------


def _bank(day: str, description: str, amount: str, final: str, status: str = "Posted") -> list[str]:
    return [day, description, amount, "", status, "", "", final]


BANK_ROWS = [
    _bank(
        "1/5/2030",
        "Deposit Example Store payout",
        "1,250.00",
        "Fundraiser Income: 1,280.00, Processing Fees: -30.00",
    ),
    _bank("1/9/2030", "Check 1001", "-75.50", "Classroom Supplies"),
    _bank("1/12/2030", "Transfer to savings", "-500.00", INTERNAL_TRANSFER_CATEGORY),
    _bank("1/15/2030", "Monthly service fee", "-3.00", "Fees"),
    _bank("1/15/2030", "Monthly service fee", "-3.00", "Fees"),
    _bank("1/20/2030", "Refund Example Buyer", "-20.00", "Fundraiser Income"),
    _bank("1/22/2030", "PAYPAL TRANSFER TXN-EX-3", "57.11", "Fundraiser Income"),
    _bank("2/1/2030", "Pending deposit", "40.00", "Donations", status="Pending"),
    _bank("2/3/2030", "Transfer from savings", "100.00", "internal transfer"),
    _bank(
        "2/4/2030",
        "Example vendor",
        "-10.00",
        "Classroom Supplies: -12.00, Internal Transfer: 2.00",
    ),
]
BANK_SETTLEMENT_ROW = 6  # index into BANK_ROWS
BANK_VARIANT_ROW = 8


def _wix(
    payment_id: str,
    day: int,
    amount: str,
    status: str,
    *,
    fee: str,
    net: str,
    refund: str = "",
    provider: str = "Wix Payments",
    product: str = "Spirit Shirt",
) -> list[str]:
    row = [
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
        provider,
        f"1000{day}",
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
    _wix("pi_ex_001", 4, "50.00", "Successful", fee="-1.75", net="48.25"),
    _wix(
        "pp_ex_002",
        6,
        "25.00",
        "Partially Refunded",
        fee="-1.10",
        net="13.90",
        refund="10.00",
        provider="PayPal",
    ),
    _wix("pi_ex_003", 7, "15.00", "Declined", fee="", net=""),
    _wix(
        "pp_ex_007",
        9,
        "30.00",
        "Successful",
        fee="-1.20",
        net="28.80",
        provider="PayPal",
        product="Raffle Ticket",
    ),
    _wix("pi_ex_008", 10, "20.00", "Refunded", fee="-0.80", net="14.20", refund="5.00"),
]
# WIX column positions used by row edits.
W_ID, W_NET, W_STATUS, W_REFUND = 0, 8, 9, 10


def _paypal(
    txn_id: str,
    day: str,
    kind: str,
    gross: str,
    fee: str,
    net: str,
    *,
    reference: str = "",
    title: str = "",
    status: str = "Completed",
) -> list[str]:
    row = [
        f"01/{day}/2030",
        "10:15:00",
        "PST",
        "Example Buyer",
        kind,
        status,
        "USD",
        gross,
        fee,
        net,
        txn_id,
        reference,
        title,
        "1" if title else "",
        "",
    ]
    assert len(row) == len(PAYPAL_HEADER)
    return row


_DETAIL = _paypal("TXN-EX-1", "04", "Shopping Cart Item", "30.00", "", "", title="Spirit Shirt")
PAYPAL_ROWS = [
    _paypal("TXN-EX-1", "04", "Website Payment", "60.00", "-2.39", "57.61"),
    list(_DETAIL),
    list(_DETAIL),
    _paypal("TXN-EX-2", "04", "Partner Fee", "-0.50", "", "-0.50", reference="TXN-EX-1"),
    _paypal("TXN-EX-3", "20", "General Withdrawal", "-57.11", "", "-57.11"),
    _paypal("pp_ex_002", "06", "Express Checkout Payment", "25.00", "-1.10", "23.90"),
    _paypal("TXN-EX-4", "22", "Payment Refund", "-10.00", "0.30", "-9.70", reference="pp_ex_002"),
    _paypal("TXN-EX-5", "23", "Partner Fee", "-0.25", "", "-0.25", reference="TXN-EX-404"),
    _paypal("TXN-EX-6", "25", "General Withdrawal", "-20.00", "", "-20.00"),
]
PAYPAL_OVERLAP_ROW = 5  # indexes into PAYPAL_ROWS
PAYPAL_REFUND_ROW = 6
# PayPal column positions used by row edits.
P_TIME, P_GROSS, P_FEE, P_NET, P_ID, P_REFERENCE = 1, 7, 8, 9, 10, 11

PNL_VALUES = [
    ["Category", "Jan 2030", "Feb 2030", "Total"],
    ["Classroom Supplies", "-75.50", "-12.00", "-87.50"],
    ["Donations", "", "40.00", "40.00"],
    ["Fees", "-6.00", "", "-6.00"],
    ["Fundraiser Income", "1,317.11", "", "1,317.11"],
    ["internal transfer", "", "100.00", "100.00"],
    ["Processing Fees", "-30.00", "", "-30.00"],
    ["Total Income", "1,317.11", "140.00", "1,457.11"],
    ["Total Expenses", "-111.50", "-12.00", "-123.50"],
    ["Net Income", "1,205.61", "128.00", "1,333.61"],
]
PNL_DONATIONS_ROW, PNL_FEES_ROW = 2, 3
MAPPING_VALUES = [
    MAPPING_HEADER,
    ["shirt", "Spirit Wear"],
    ["raffle", "Raffle"],
    ["ticket", "Events"],
    ["deposit", "Donations"],
]
TRACKER_VALUES = [["Category", "Budget", "Actual"], ["Classroom Supplies", "500.00", "87.50"]]

CROSSWALK_TOML = """
[main_reports.crosswalk]
version = 2
[[main_reports.crosswalk.entries]]
source_category = "Fundraiser Income"
targets = [{ category = "Fundraising", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Processing Fees"
targets = [{ category = "Fees and Charges", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Fees"
targets = [{ category = "Fees and Charges", share = "1" }]
note = "one-to-one"
[[main_reports.crosswalk.entries]]
source_category = "Classroom Supplies"
targets = [
  { category = "Grade Supplies", share = "0.25" },
  { category = "Shared Supplies", share = "0.75" },
]
note = "documented split"
"""


def _config(tmp_path: Path, crosswalk: str = CROSSWALK_TOML) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(_FULL_CONFIG + main_reports_toml() + crosswalk, encoding="utf-8")
    return load_config(path)


def _harness(
    config: Config,
    *,
    bank: Sequence[Sequence[str]] = BANK_ROWS,
    wix: Sequence[Sequence[str]] = WIX_ROWS,
    paypal: Sequence[Sequence[str]] = PAYPAL_ROWS,
    pnl: Sequence[Sequence[str]] = PNL_VALUES,
    pnl_entered: Mapping[tuple[int, int], float] | None = None,
    mapping: Sequence[Sequence[str]] = MAPPING_VALUES,
) -> CfoHarness:
    # The P&L entered-value grid: its A1 QUERY formula plus any numeric entered cells.
    entered: list[list[Any]] = [["" for _ in row] for row in pnl]
    entered[0][0] = '=QUERY({"example"}, "select *")'
    for (row, column), value in (pnl_entered or {}).items():
        entered[row][column] = value
    sheets = {
        "Bank Checking": CfoWorksheet([BANK_HEADER, *map(list, bank)], sheet_id=1001),
        "Store Transactions": CfoWorksheet(
            [WIX_GROUPS, WIX_LABELS, *map(list, wix)], sheet_id=1002
        ),
        "Processor Transactions": CfoWorksheet([PAYPAL_HEADER, *map(list, paypal)], sheet_id=1003),
        "Profit & Loss": CfoWorksheet([list(row) for row in pnl], sheet_id=1004, formulas=entered),
        "Budget Tracker": CfoWorksheet(TRACKER_VALUES, sheet_id=1005),
        "Category Mapping": CfoWorksheet([list(row) for row in mapping], sheet_id=1006),
        "Credit Card Transactions": CfoWorksheet([CARD_HEADER], sheet_id=1007),
    }
    return CfoHarness(config, sheets)


def _run(tmp_path: Path, crosswalk: str = CROSSWALK_TOML, **grids: Any) -> Reconciliation:
    config = _config(tmp_path, crosswalk)
    harness = _harness(config, **grids)
    result = from_capture(harness.capture(), config)
    harness.assert_no_writes()
    return result


def _kinds(result: Reconciliation) -> list[str]:
    return sorted(item.kind for item in result.discrepancies)


def _of_kind(result: Reconciliation, kind: str) -> list[Discrepancy]:
    return [item for item in result.discrepancies if item.kind == kind]


def _txn(result: Reconciliation, alias: str, **fields: Any) -> list[Transaction]:
    return [
        txn
        for txn in result.transactions
        if txn.source_alias == alias and all(getattr(txn, k) == v for k, v in fields.items())
    ]


def _one(result: Reconciliation, alias: str, **fields: Any) -> Transaction:
    (found,) = _txn(result, alias, **fields)
    return found


def _summary(result: Reconciliation, alias: str) -> Any:
    (found,) = [s for s in result.processor_summaries if s.source_alias == alias]
    return found


def _cells(result: Reconciliation) -> dict[tuple[str, str], Decimal]:
    return {(c.category, c.month.isoformat()[:7]): c.net for c in result.monthly_cells}


def _edit(rows: Sequence[Sequence[str]], index: int, cells: Mapping[int, str]) -> list[list[str]]:
    """Copy ``rows`` with the given column positions of one row replaced."""
    out = [list(row) for row in rows]
    for column, value in cells.items():
        out[index][column] = value
    return out


def _pnl_with(row: int, column: int, value: str) -> list[list[str]]:
    return _edit(PNL_VALUES, row, {column: value})


def _warned(result: Reconciliation) -> set[tuple[str, str]]:
    return {(issue.source_alias, issue.code) for issue in result.row_warnings}


BASE_KINDS = sorted(
    [
        "bank_row_not_posted",
        "category_mapping_ambiguous",
        "crosswalk_unmapped",
        "crosswalk_unmapped",
        "fee_unlinked",
        "overlap_missing",
        "refund_status_conflict",
        "settlement_unmatched",
        "transfer_category_variant",
    ]
)


# --------------------------------------------------------------------------------------
# Production path: capture -> normalize -> reconcile
# --------------------------------------------------------------------------------------


def test_production_reconciliation_end_to_end(tmp_path: Path) -> None:
    config = _config(tmp_path)
    harness = _harness(config)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = from_capture(harness.capture(), config)

    harness.assert_no_writes()
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before

    # Split conservation: every bank row's counted + transfer allocations equal its amount.
    for txn in _txn(result, "bank-checking"):
        own = [
            a
            for a in (*result.allocations, *result.transfer_allocations)
            if a.record_key == txn.record_key
        ]
        assert sum(a.amount for a in own) == txn.gross

    # Source monthly-category-net parity with the published P&L control.
    assert _cells(result) == {
        ("Classroom Supplies", "2030-01"): Decimal("-75.50"),
        ("Fees", "2030-01"): Decimal("-6.00"),
        ("Fundraiser Income", "2030-01"): Decimal("1317.11"),
        ("Processing Fees", "2030-01"): Decimal("-30.00"),
        ("Classroom Supplies", "2030-02"): Decimal("-12.00"),
        ("Donations", "2030-02"): Decimal("40.00"),
        ("internal transfer", "2030-02"): Decimal("100.00"),
    }
    control = result.pnl_control
    assert control.status == "matched"
    assert (control.compared_cells, control.matched_cells) == (7, 7)
    assert control.matched_total_rows == 3
    assert control.ignored_columns == 1
    assert control.source_alias == "pnl"
    assert [(t.month.month, t.income, t.expense, t.net) for t in result.pnl_totals] == [
        (1, Decimal("1317.11"), Decimal("-111.50"), Decimal("1205.61")),
        (2, Decimal("140.00"), Decimal("-12.00"), Decimal("128.00")),
    ]

    # Every remaining ambiguity is a visible, unresolved discrepancy.
    assert _kinds(result) == BASE_KINDS
    assert all(item.state == "unresolved" for item in result.discrepancies)
    assert result.unresolved == result.discrepancies

    # No processor/bank double counting: the bank source view is unchanged by processor rows.
    bank_only = build(
        [txn for txn in normalize(harness.capture()) if txn.source_kind == "bank"],
        controls_from(harness.capture(), config),
    )
    assert bank_only.monthly_cells == result.monthly_cells
    assert bank_only.pnl_totals == result.pnl_totals

    # Reconciliation is persisted as canonical JSON (decimal strings, no floats).
    payload = json.loads(canonical_json_bytes(result.to_dict()))
    assert payload["schema_version"] == 1
    assert payload["pnl_control"]["status"] == "matched"


@pytest.mark.parametrize("variant", ["internal transfer", "Internal  Transfer"])
def test_source_view_excludes_only_the_exact_transfer_category(
    tmp_path: Path, variant: str
) -> None:
    bank = _edit(BANK_ROWS, BANK_VARIANT_ROW, {7: variant})
    result = _run(tmp_path, bank=bank)
    transfers = {(a.category, a.amount) for a in result.transfer_allocations}
    assert transfers == {
        (INTERNAL_TRANSFER_CATEGORY, Decimal("-500.00")),
        (INTERNAL_TRANSFER_CATEGORY, Decimal("2.00")),
    }
    assert all(a.category != INTERNAL_TRANSFER_CATEGORY for a in result.allocations)

    savings = _one(result, "bank-checking", description="Transfer to savings")
    assert savings.reconciliation_state == "transfer_excluded"
    split = _one(result, "bank-checking", description="Example vendor")
    assert split.reconciliation_state == "source_view"  # its other component is counted

    (found,) = _of_kind(result, "transfer_category_variant")
    assert found.category == variant
    assert found.amount == Decimal("100.00")
    assert found.impact == "source_pnl"
    assert _cells(result)[(variant, "2030-02")] == Decimal("100.00")


def test_non_posted_rows_are_counted_and_flagged_not_filtered(tmp_path: Path) -> None:
    result = _run(tmp_path)
    (flag,) = _of_kind(result, "bank_row_not_posted")
    pending = _one(result, "bank-checking", description="Pending deposit")
    assert [ref.record_key for ref in flag.affected] == [pending.record_key]
    assert flag.amount == Decimal("40.00")
    assert _cells(result)[("Donations", "2030-02")] == Decimal("40.00")


def test_legitimate_identical_rows_are_both_counted(tmp_path: Path) -> None:
    result = _run(tmp_path)
    fees = _txn(result, "bank-checking", description="Monthly service fee")
    assert len(fees) == 2 and fees[0].record_key != fees[1].record_key
    (cell,) = [c for c in result.monthly_cells if c.category == "Fees"]
    assert cell.net == Decimal("-6.00")
    assert sorted(ref.record_key for ref in cell.contributors) == sorted(t.record_key for t in fees)


def test_classification_uses_the_monthly_net_and_labels_gross_activity(tmp_path: Path) -> None:
    result = _run(tmp_path)
    (cell,) = [c for c in result.monthly_cells if c.category == "Fundraiser Income"]
    assert (cell.inflow, cell.outflow, cell.net) == (
        Decimal("1337.11"),
        Decimal("-20.00"),
        Decimal("1317.11"),
    )
    assert cell.classification == "income"
    january = result.pnl_totals[0]
    # The refund lowers income (net basis) instead of appearing as a separate expense.
    assert january.income == Decimal("1317.11")
    assert january.expense == Decimal("-111.50")
    supplies = [c for c in result.monthly_cells if c.category == "Classroom Supplies"]
    assert {c.classification for c in supplies} == {"expense"}


# --------------------------------------------------------------------------------------
# Published P&L control
# --------------------------------------------------------------------------------------


def test_pnl_mismatch_is_a_located_discrepancy_never_parity(tmp_path: Path) -> None:
    result = _run(tmp_path, pnl=_pnl_with(PNL_FEES_ROW, 1, "-3.00"))
    assert result.pnl_control.status == "mismatched"
    (finding,) = _of_kind(result, "pnl_control_mismatch")
    assert finding.amount == Decimal("3.00")  # published - reproduced
    assert (finding.category, finding.month and finding.month.month) == ("Fees", 1)
    assert finding.control_cell == (4, 2)
    fees = _txn(result, "bank-checking", description="Monthly service fee")
    assert {ref.record_key for ref in finding.affected} == {t.record_key for t in fees}


def test_pnl_missing_extra_and_month_absent_cells(tmp_path: Path) -> None:
    grid = _pnl_with(PNL_DONATIONS_ROW, 2, "")  # Donations Feb blank in the published control
    grid.insert(7, ["Example Mystery", "5.00", "", "5.00"])
    result = _run(tmp_path, pnl=grid)
    (missing,) = _of_kind(result, "pnl_control_missing_cell")
    assert (missing.category, missing.amount) == ("Donations", Decimal("40.00"))
    (extra,) = _of_kind(result, "pnl_control_extra_cell")
    assert (extra.category, extra.amount, extra.control_cell) == (
        "Example Mystery",
        Decimal("5.00"),
        (8, 2),
    )
    assert result.pnl_control.status == "mismatched"

    january_only = [[row[0], row[1]] for row in PNL_VALUES]
    absent = _run(tmp_path, pnl=january_only)
    (month,) = _of_kind(absent, "pnl_control_month_absent")
    assert month.month is not None and month.month.month == 2
    assert absent.pnl_control.status == "mismatched"


def test_pnl_category_row_absent_from_the_control(tmp_path: Path) -> None:
    without_donations = [row for i, row in enumerate(PNL_VALUES) if i != PNL_DONATIONS_ROW]
    result = _run(tmp_path, pnl=without_donations)
    (missing,) = _of_kind(result, "pnl_control_missing_cell")
    assert (missing.category, missing.amount, missing.control_cell) == (
        "Donations",
        Decimal("40.00"),
        None,
    )
    pending = _one(result, "bank-checking", description="Pending deposit")
    assert [ref.record_key for ref in missing.affected] == [pending.record_key]
    assert result.pnl_control.status == "mismatched"

    # A category netting to exactly zero has no published row and still matches.
    held = [
        *BANK_ROWS,
        _bank("1/16/2030", "Example deposit held", "15.00", "Deposits Held"),
        _bank("1/18/2030", "Example deposit returned", "-15.00", "Deposits Held"),
    ]
    zero = _run(tmp_path, bank=held)
    (cell,) = [c for c in zero.monthly_cells if c.category == "Deposits Held"]
    assert (cell.net, cell.classification) == (Decimal("0.00"), "zero")
    assert zero.pnl_control.status == "matched"
    assert (zero.pnl_control.compared_cells, zero.pnl_control.matched_cells) == (8, 8)


def test_pnl_unlabeled_and_unreproduced_cells_are_extra(tmp_path: Path) -> None:
    grid = _pnl_with(PNL_FEES_ROW, 2, "4.00")  # Fees has no February bank activity
    grid.insert(7, ["", "7.00", "", ""])
    result = _run(tmp_path, pnl=grid)
    extras = {
        (d.category, d.amount, d.control_cell) for d in _of_kind(result, "pnl_control_extra_cell")
    }
    assert extras == {("Fees", Decimal("4.00"), (4, 3)), (None, Decimal("7.00"), (8, 2))}
    assert result.pnl_control.status == "mismatched"


def test_total_rows_need_a_total_label_and_matching_values(tmp_path: Path) -> None:
    phantom = [*PNL_VALUES, ["Example Phantom", "1,317.11", "140.00", ""]]
    result = _run(tmp_path, pnl=phantom)
    extras = {d.category for d in _of_kind(result, "pnl_control_extra_cell")}
    assert extras == {"Example Phantom"}  # equal to income totals, but not labeled a total
    assert result.pnl_control.matched_total_rows == 3

    wrong = _run(tmp_path, pnl=_pnl_with(7, 2, "141.00"))
    (total,) = _of_kind(wrong, "pnl_control_total_mismatch")
    assert (total.category, total.control_cell) == ("Total Income", (8, 1))
    assert wrong.pnl_control.status == "mismatched"

    # Expenses published as positive magnitudes are still a verified total row.
    positive = _edit(PNL_VALUES, 8, {1: "111.50", 2: "12.00"})
    assert _run(tmp_path, pnl=positive).pnl_control.matched_total_rows == 3


def test_unreadable_total_row_is_reported_once_not_recomputed(tmp_path: Path) -> None:
    result = _run(tmp_path, pnl=_pnl_with(7, 2, "-"))  # Total Income Feb: unproven dash
    (cell,) = _of_kind(result, "pnl_control_cell_unreadable")
    assert (cell.category, cell.control_cell) == ("Total Income", (8, 3))
    assert not _of_kind(result, "pnl_control_total_mismatch")
    assert result.pnl_control.matched_total_rows == 2


def test_duplicate_month_columns_are_an_unrecognized_layout(tmp_path: Path) -> None:
    grid = [[*row[:2], row[1]] for row in PNL_VALUES]
    grid[0] = ["Category", "Jan 2030", "2030-01"]
    result = _run(tmp_path, pnl=grid)
    assert result.pnl_control.status == "unverified"
    assert "pnl_control_layout_unrecognized" in _kinds(result)


def test_pnl_dash_cells_follow_the_source_dash_rule(tmp_path: Path) -> None:
    dashed = _pnl_with(PNL_FEES_ROW, 2, "-")  # Fees February shown as an Accounting dash
    zero = _run(tmp_path, pnl=dashed, pnl_entered={(PNL_FEES_ROW, 2): 0})
    assert zero.pnl_control.status == "matched"
    assert (zero.pnl_control.compared_cells, zero.pnl_control.matched_cells) == (8, 8)

    unproven = _run(tmp_path, pnl=dashed)
    (cell,) = _of_kind(unproven, "pnl_control_cell_unreadable")
    assert (cell.category, cell.control_cell) == ("Fees", (4, 3))

    hidden = _run(tmp_path, pnl=PNL_VALUES, pnl_entered={(PNL_FEES_ROW, 1): -6.004})
    (precision,) = _of_kind(hidden, "pnl_control_cell_unreadable")
    assert precision.control_cell == (4, 2)

    # A blank display over a nonzero entered number is hidden, not blank.
    masked = _run(tmp_path, pnl=PNL_VALUES, pnl_entered={(PNL_DONATIONS_ROW, 1): 5})
    (blank,) = _of_kind(masked, "pnl_control_cell_unreadable")
    assert (blank.category, blank.control_cell) == ("Donations", (3, 2))


def test_pnl_unreadable_cell_and_duplicate_row_are_unverified(tmp_path: Path) -> None:
    result = _run(tmp_path, pnl=_pnl_with(PNL_FEES_ROW, 1, "n/a"))
    (cell,) = _of_kind(result, "pnl_control_cell_unreadable")
    assert (cell.category, cell.control_cell, cell.amount) == ("Fees", (4, 2), None)
    assert result.pnl_control.compared_cells == 6

    duplicated = [list(r) for r in PNL_VALUES]
    duplicated.insert(4, list(PNL_VALUES[PNL_FEES_ROW]))
    dup = _run(tmp_path, pnl=duplicated)
    assert [d.category for d in _of_kind(dup, "pnl_control_duplicate_row")] == ["Fees"]
    assert dup.pnl_control.status == "mismatched"


def test_unrecognized_or_absent_control_never_claims_parity(tmp_path: Path) -> None:
    result = _run(tmp_path, pnl=[["Category", "Amount"], ["Fees", "-6.00"]])
    assert result.pnl_control.status == "unverified"
    assert "pnl_control_layout_unrecognized" in _kinds(result)
    assert ("pnl_control_unverified", "pnl") in {
        (f.code, f.source_alias) for f in result.coverage_flags
    }

    config = _config(tmp_path)
    captured = _harness(config).capture()
    controls = dataclasses.replace(controls_from(captured, config), pnl=None)
    absent = build(normalize(captured), controls)
    assert absent.pnl_control.status == "absent"
    assert "pnl_control_absent" in _kinds(absent)
    assert "pnl_control_absent" in {f.code for f in absent.coverage_flags}


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Jan 2030", (2030, 1)),
        ("January 2030", (2030, 1)),
        ("2030-02", (2030, 2)),
        ("3/2030", (2030, 3)),
        ("2030-04-01", (2030, 4)),
        ("5/1/2030", (2030, 5)),
        ("5/2/2030", None),
        ("Total", None),
        ("", None),
        ("x" * 200, None),
    ],
)
def test_parse_month_label(label: str, expected: tuple[int, int] | None) -> None:
    parsed = parse_month_label(label)
    assert (None if parsed is None else (parsed.year, parsed.month)) == expected
    assert parsed is None or parsed.day == 1


# --------------------------------------------------------------------------------------
# WIX / PayPal overlap and processor enrichment
# --------------------------------------------------------------------------------------


def test_wix_paypal_overlap_counts_one_representation(tmp_path: Path) -> None:
    result = _run(tmp_path)
    store = _one(result, "wix", native_id="pp_ex_002")
    paypal = _one(result, "paypal", native_id="pp_ex_002")
    refund = _one(result, "paypal", native_id="TXN-EX-4")
    assert store.reconciliation_state == "processor_primary"
    assert paypal.reconciliation_state == "overlap_secondary"
    assert refund.reconciliation_state == "overlap_secondary"  # represented by the store refund

    (overlap,) = [m for m in result.matches if m.kind == "processor_overlap"]
    assert {ref.record_key for ref in overlap.members} == {store.record_key, paypal.record_key}
    assert overlap.match_id.startswith("MATCH-")

    wix, pay = _summary(result, "wix"), _summary(result, "paypal")
    # Store: 50 + 25 + 30 + 20 gross; fees 1.75 + 1.10 + 1.20 + 0.80; refunds 10 + 5.
    assert (wix.gross, wix.fees, wix.refunds) == (
        Decimal("125.00"),
        Decimal("4.85"),
        Decimal("15.00"),
    )
    assert (wix.primary_count, wix.non_movement_count) == (4, 1)
    # PayPal: the overlapped sale and its refund are not counted again. Fees are the sale fee
    # 2.39 + its linked partner fee 0.50 + the unlinked partner fee 0.25 (a real PayPal fee
    # movement, counted once and flagged fee_unlinked, so the summary is inconsistent).
    assert (pay.gross, pay.fees, pay.refunds) == (
        Decimal("60.00"),
        Decimal("3.14"),
        Decimal("0.00"),
    )
    # One overlapped PAYMENT; its linked refund row follows it but is not a secondary payment.
    assert (pay.primary_count, pay.secondary_count) == (1, 1)
    assert not wix.settled and not wix.consistent and not pay.consistent
    flags = {(f.code, f.source_alias): f.count for f in result.coverage_flags}
    assert flags[("processor_gross_unsettled", "wix")] == 4
    assert flags[("processor_gross_unsettled", "paypal")] == 1


def test_fee_on_an_overlapped_payment_follows_its_payment(tmp_path: Path) -> None:
    fee = _paypal("TXN-EX-8", "06", "Partner Fee", "-0.40", "", "-0.40", reference="pp_ex_002")
    result = _run(tmp_path, paypal=[*PAYPAL_ROWS, fee])
    assert _one(result, "paypal", native_id="TXN-EX-8").reconciliation_state == (
        "overlap_secondary"
    )
    assert _summary(result, "paypal").fees == Decimal("3.14")  # not counted beside the store fee
    assert _summary(result, "paypal").secondary_count == 1  # payments only, not linked rows


def test_overlap_requires_paypal_provider_and_flags_missing_partner(tmp_path: Path) -> None:
    result = _run(tmp_path)
    (missing,) = _of_kind(result, "overlap_missing")
    raffle = _one(result, "wix", native_id="pp_ex_007")
    assert [ref.record_key for ref in missing.affected] == [raffle.record_key]
    assert raffle.reconciliation_state == "processor_primary"

    wix = _edit(WIX_ROWS, 1, {11: "Wix Payments"})
    conflicted = _run(tmp_path, wix=wix)
    (finding,) = _of_kind(conflicted, "overlap_provider_conflict")
    assert len(finding.affected) == 2
    assert _one(conflicted, "wix", native_id="pp_ex_002").reconciliation_state == "conflict"


def test_paypal_provider_store_row_without_an_id_is_never_counted_twice(tmp_path: Path) -> None:
    result = _run(tmp_path, wix=_edit(WIX_ROWS, 3, {W_ID: ""}))
    (finding,) = _of_kind(result, "overlap_unidentified")
    (row,) = [t for t in _txn(result, "wix") if t.native_id is None]
    assert row.reconciliation_state == "conflict"
    assert [ref.record_key for ref in finding.affected] == [row.record_key]
    assert _summary(result, "wix").gross == Decimal("95.00")  # 125.00 less the unpaired 30.00
    assert ("wix", "missing_native_id") in _warned(result)

    # A declined store row moved no money, so a missing ID cannot double count it.
    declined = _run(tmp_path, wix=_edit(WIX_ROWS, 3, {W_ID: "", W_STATUS: "Declined"}))
    assert not _of_kind(declined, "overlap_unidentified")
    (quiet,) = [t for t in _txn(declined, "wix") if t.native_id is None]
    assert quiet.reconciliation_state == "non_movement"


def test_overlap_amount_conflict_excludes_both_sides(tmp_path: Path) -> None:
    paypal = _edit(PAYPAL_ROWS, PAYPAL_OVERLAP_ROW, {P_GROSS: "26.00", P_NET: "24.90"})
    result = _run(tmp_path, paypal=paypal)
    assert len(_of_kind(result, "overlap_amount_conflict")) == 1
    store = _one(result, "wix", native_id="pp_ex_002")
    pay = _one(result, "paypal", native_id="pp_ex_002")
    refund = _one(result, "paypal", native_id="TXN-EX-4")
    assert {store.reconciliation_state, pay.reconciliation_state, refund.reconciliation_state} == {
        "conflict"
    }
    assert not any(m.kind == "processor_overlap" for m in result.matches)
    assert _summary(result, "wix").gross == Decimal("100.00")
    assert _summary(result, "paypal").gross == Decimal("60.00")
    assert _summary(result, "paypal").refunds == Decimal("0.00")
    assert _summary(result, "paypal").conflict_count == 2


def test_ambiguous_and_status_conflicting_overlaps(tmp_path: Path) -> None:
    twin = _edit(PAYPAL_ROWS, PAYPAL_OVERLAP_ROW, {P_TIME: "11:00:00"})[PAYPAL_OVERLAP_ROW]
    ambiguous = _run(tmp_path, paypal=[*PAYPAL_ROWS, twin])
    assert len(_of_kind(ambiguous, "overlap_ambiguous")) == 1
    assert len(_of_kind(ambiguous, "refund_unlinked")) == 1  # two candidate parents
    assert (
        len(_txn(ambiguous, "paypal", native_id="pp_ex_002", reconciliation_state="conflict")) == 2
    )
    assert ("paypal", "duplicate_native_id") in _warned(ambiguous)

    store_twin = _edit(WIX_ROWS, 1, {2: "2030-01-06 11:00:00"})[1]
    two_stores = _run(tmp_path, wix=[*WIX_ROWS, store_twin])
    assert len(_of_kind(two_stores, "overlap_ambiguous")) == 1
    assert ("wix", "duplicate_native_id") in _warned(two_stores)

    declined = _edit(WIX_ROWS, 1, {W_STATUS: "Declined", W_REFUND: "", W_NET: ""})
    status = _run(tmp_path, wix=declined)
    assert len(_of_kind(status, "overlap_status_conflict")) == 1
    assert _one(status, "paypal", native_id="TXN-EX-4").reconciliation_state == "conflict"


def test_unresolved_store_status_keeps_the_overlap_conflict_visible(tmp_path: Path) -> None:
    result = _run(tmp_path, wix=_edit(WIX_ROWS, 1, {W_STATUS: "Chargeback"}))
    assert len(_of_kind(result, "processor_status_unresolved")) == 1
    (overlap,) = _of_kind(result, "overlap_status_conflict")
    assert len(overlap.affected) == 2
    assert _one(result, "paypal", native_id="pp_ex_002").reconciliation_state == "conflict"
    assert not any(m.kind == "processor_overlap" for m in result.matches)
    assert not _summary(result, "paypal").consistent  # the PayPal side shows the removal

    # Neither side moved money (pending PayPal row) but one side is unresolved: still no pair.
    pending = _edit(PAYPAL_ROWS, PAYPAL_OVERLAP_ROW, {5: "Pending"})
    both = _run(tmp_path, wix=_edit(WIX_ROWS, 1, {W_STATUS: "Chargeback"}), paypal=pending)
    assert len(_of_kind(both, "overlap_status_conflict")) == 1
    assert not any(m.kind == "processor_overlap" for m in both.matches)


def test_fee_and_refund_conflicts_are_explicit(tmp_path: Path) -> None:
    fee = _run(
        tmp_path,
        paypal=_edit(PAYPAL_ROWS, PAYPAL_OVERLAP_ROW, {P_FEE: "-1.20", P_NET: "23.80"}),
    )
    (fee_conflict,) = _of_kind(fee, "overlap_fee_conflict")
    assert fee_conflict.amount == Decimal("-0.10")
    assert any(m.kind == "processor_overlap" for m in fee.matches)  # the pairing itself holds

    refund = _run(
        tmp_path,
        paypal=_edit(
            PAYPAL_ROWS, PAYPAL_REFUND_ROW, {P_GROSS: "-8.00", P_FEE: "0.24", P_NET: "-7.76"}
        ),
    )
    (cross,) = _of_kind(refund, "refund_cross_feed_conflict")
    assert cross.amount == Decimal("2.00")
    assert len(cross.affected) == 3

    excess = _run(
        tmp_path,
        paypal=_edit(
            PAYPAL_ROWS,
            PAYPAL_REFUND_ROW,
            {P_GROSS: "-70.00", P_FEE: "", P_NET: "-70.00", P_REFERENCE: "TXN-EX-1"},
        ),
    )
    (over,) = _of_kind(excess, "refund_exceeds_payment")
    assert over.amount == Decimal("10.00")
    assert len(_of_kind(excess, "refund_cross_feed_conflict")) == 1  # store refund now unmatched

    unlinked = _run(tmp_path, paypal=_edit(PAYPAL_ROWS, PAYPAL_REFUND_ROW, {P_REFERENCE: ""}))
    (lost,) = _of_kind(unlinked, "refund_unlinked")
    assert lost.amount == Decimal("-10.00")

    base = _run(tmp_path)
    (orphan_fee,) = _of_kind(base, "fee_unlinked")
    assert orphan_fee.amount == Decimal("-0.25")
    (status,) = _of_kind(base, "refund_status_conflict")
    assert status.amount == Decimal("5.00")


@pytest.mark.parametrize(
    ("cells", "kind"),
    [
        ({W_REFUND: "5.00", W_NET: "43.25"}, "refund_status_conflict"),  # successful + refund
        (
            {W_STATUS: "Partially Refunded", W_REFUND: "50.00", W_NET: "-1.75"},
            "refund_status_conflict",  # a "partial" refund of the whole payment
        ),
        ({W_STATUS: "Refunded", W_REFUND: "60.00", W_NET: "-11.75"}, "refund_exceeds_payment"),
    ],
)
def test_store_refund_variants_are_explicit(
    tmp_path: Path, cells: Mapping[int, str], kind: str
) -> None:
    result = _run(tmp_path, wix=_edit(WIX_ROWS, 0, cells))
    store = _one(result, "wix", native_id="pi_ex_001")
    assert any(
        store.record_key in {ref.record_key for ref in item.affected}
        for item in _of_kind(result, kind)
    )
    assert not _of_kind(result, "processor_net_arithmetic")


@pytest.mark.parametrize("status", ["Declined", "Authorized", "Pending"])
def test_non_movement_statuses_are_not_counted(tmp_path: Path, status: str) -> None:
    result = _run(tmp_path, wix=_edit(WIX_ROWS, 2, {W_STATUS: status}))
    assert _one(result, "wix", native_id="pi_ex_003").reconciliation_state == "non_movement"
    assert _summary(result, "wix").gross == Decimal("125.00")


@pytest.mark.parametrize("net", ["57.00", "62.39"])  # wrong amount; wrong direction by the fee
def test_processor_net_arithmetic_keeps_the_fee_sign(tmp_path: Path, net: str) -> None:
    result = _run(tmp_path, paypal=_edit(PAYPAL_ROWS, 0, {P_NET: net}))
    (arithmetic,) = _of_kind(result, "processor_net_arithmetic")
    parent = _one(result, "paypal", native_id="TXN-EX-1", row_role="payment")
    assert [ref.record_key for ref in arithmetic.affected] == [parent.record_key]


def test_unresolved_processor_status_is_excluded(tmp_path: Path) -> None:
    result = _run(tmp_path, wix=_edit(WIX_ROWS, 0, {W_STATUS: "Chargeback"}))
    (status,) = _of_kind(result, "processor_status_unresolved")
    assert _one(result, "wix", native_id="pi_ex_001").reconciliation_state == "conflict"
    assert len(status.affected) == 1
    assert _summary(result, "wix").gross == Decimal("75.00")


def test_paypal_details_are_enrichment_with_checked_sums(tmp_path: Path) -> None:
    result = _run(tmp_path)
    details = _txn(result, "paypal", native_id="TXN-EX-1", row_role="detail")
    assert len(details) == 2 and details[0].revision_hash == details[1].revision_hash
    assert {t.reconciliation_state for t in details} == {"detail_enrichment"}
    (group,) = [m for m in result.matches if m.kind == "processor_detail"]
    assert len(group.members) == 3
    assert _summary(result, "paypal").gross == Decimal("60.00")

    mismatch = _run(tmp_path, paypal=_edit(PAYPAL_ROWS, 1, {P_GROSS: "25.00"}))
    (sum_finding,) = _of_kind(mismatch, "paypal_detail_sum_mismatch")
    assert sum_finding.amount == Decimal("-5.00")

    partial = _run(tmp_path, paypal=_edit(PAYPAL_ROWS, 1, {P_GROSS: ""}))
    assert len(_of_kind(partial, "paypal_detail_sum_unverified")) == 1

    orphan = _run(tmp_path, paypal=_edit(PAYPAL_ROWS, 1, {P_ID: "TXN-EX-9"}))
    (lonely,) = _of_kind(orphan, "paypal_detail_orphan")
    assert len(lonely.affected) == 1


# --------------------------------------------------------------------------------------
# Bank settlements
# --------------------------------------------------------------------------------------


def _settlements(result: Reconciliation) -> int:
    return sum(1 for m in result.matches if m.kind == "bank_settlement")


def test_bank_settlements_need_a_reference_not_proximity(tmp_path: Path) -> None:
    result = _run(tmp_path)
    (settlement,) = [m for m in result.matches if m.kind == "bank_settlement"]
    withdrawal = _one(result, "paypal", native_id="TXN-EX-3")
    deposit = _one(result, "bank-checking", description="PAYPAL TRANSFER TXN-EX-3")
    assert {ref.record_key for ref in settlement.members} == {
        withdrawal.record_key,
        deposit.record_key,
    }
    assert deposit.reconciliation_state == "source_view"  # CFO treatment is unchanged
    (unmatched,) = _of_kind(result, "settlement_unmatched")
    assert unmatched.amount == Decimal("20.00")

    wrong = _edit(BANK_ROWS, BANK_SETTLEMENT_ROW, {2: "57.00"})
    conflict = _run(tmp_path, bank=wrong)
    assert len(_of_kind(conflict, "settlement_conflict")) == 1
    assert _settlements(conflict) == 0


def test_one_bank_row_settles_at_most_one_transfer(tmp_path: Path) -> None:
    # A second transfer naming the same reference cannot reuse the referenced bank row.
    twin = _paypal("TXN-EX-3", "21", "General Withdrawal", "-57.11", "", "-57.11")
    referenced = _run(tmp_path, paypal=[*PAYPAL_ROWS, twin])
    assert _settlements(referenced) == 1
    assert len(_of_kind(referenced, "settlement_unmatched")) == 2

    # An equal-amount transfer in the window cannot claim the already-settled bank row.
    rival = _paypal("TXN-EX-7", "21", "General Withdrawal", "-57.11", "", "-57.11")
    nearby = _run(tmp_path, paypal=[*PAYPAL_ROWS, rival])
    assert _settlements(nearby) == 1
    assert not _of_kind(nearby, "settlement_candidate")
    rival_key = _one(nearby, "paypal", native_id="TXN-EX-7").record_key
    assert any(
        rival_key in {ref.record_key for ref in d.affected}
        for d in _of_kind(nearby, "settlement_unmatched")
    )


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("prefix_reference", "settlement_candidate"),
        ("duplicate_reference", "settlement_conflict"),
        ("short_reference", "settlement_candidate"),
        ("window_edge", "settlement_candidate"),
        ("before_transfer", "settlement_unmatched"),
        ("beyond_window", "settlement_unmatched"),
    ],
)
def test_settlement_reference_and_window_edges(tmp_path: Path, case: str, expected: str) -> None:
    bank: list[list[str]] = [list(row) for row in BANK_ROWS]
    paypal: list[list[str]] = [list(row) for row in PAYPAL_ROWS]
    unsettled = "TXN-EX-6"  # 01/25, -20.00, no bank reference
    target = "TXN-EX-3"
    if case == "prefix_reference":
        bank[BANK_SETTLEMENT_ROW][1] = "PAYPAL TRANSFER TXN-EX-33"
    elif case == "duplicate_reference":
        bank.append(list(BANK_ROWS[BANK_SETTLEMENT_ROW]))
    elif case == "short_reference":
        paypal = _edit(PAYPAL_ROWS, 4, {P_ID: "TX-3"})
        bank[BANK_SETTLEMENT_ROW][1] = "PAYPAL TRANSFER TX-3"
        target = "TX-3"
    else:
        day = {"window_edge": "2/4/2030", "before_transfer": "1/24/2030"}.get(case, "2/5/2030")
        bank.append(_bank(day, "Online transfer", "20.00", "Fundraiser Income"))
        target = unsettled
    result = _run(tmp_path, bank=bank, paypal=paypal)
    key = _one(result, "paypal", native_id=target).record_key
    kinds = {
        d.kind
        for d in result.discrepancies
        if d.impact == "settlement" and key in {ref.record_key for ref in d.affected}
    }
    assert kinds == {expected}
    if target != unsettled:
        assert _settlements(result) == 0


# Sale (net 57.61), its two details, its linked partner fee (-0.50) and the one withdrawal
# (57.11) that is reference-matched to a bank deposit: the payout accounts for the balance.
SETTLED_PAYPAL = PAYPAL_ROWS[:5]


def test_settled_requires_matched_payouts_to_account_for_the_balance(tmp_path: Path) -> None:
    base = _run(tmp_path)
    pay = _summary(base, "paypal")
    # Balance 57.61 - 0.50 + 23.90 - 9.70 - 0.25 = 71.06, less the matched 57.11 payout; the
    # 20.00 withdrawal is unmatched too.
    assert (pay.settled, pay.untied) == (False, Decimal("13.95"))

    settled = _run(tmp_path, paypal=SETTLED_PAYPAL)
    assert (_summary(settled, "paypal").settled, _summary(settled, "paypal").untied) == (
        True,
        Decimal("0.00"),
    )
    flags = {(f.code, f.source_alias) for f in settled.coverage_flags}
    assert ("processor_gross_unsettled", "paypal") not in flags
    assert ("processor_gross_unsettled", "wix") in flags  # no payout evidence for the store

    # Five more 1,000.00 sales behind the same single matched withdrawal stay untied.
    sales = [
        _paypal(f"TXN-EX-1{n}", "05", "Website Payment", "1,000.00", "", "1,000.00")
        for n in range(5)
    ]
    probe = _run(tmp_path, paypal=[*SETTLED_PAYPAL, *sales])
    summary = _summary(probe, "paypal")
    assert (summary.settled, summary.untied, summary.gross) == (
        False,
        Decimal("5000.00"),
        Decimal("5060.00"),
    )
    counts = {(f.code, f.source_alias): f.count for f in probe.coverage_flags}
    assert counts[("processor_gross_unsettled", "paypal")] == 6


def test_alias_without_balance_movement_is_trivially_settled(tmp_path: Path) -> None:
    declined = [
        _edit([row], 0, {W_STATUS: "Declined"})[0] for i, row in enumerate(WIX_ROWS) if i != 1
    ]
    result = _run(tmp_path, wix=declined)
    wix = _summary(result, "wix")
    assert (wix.primary_count, wix.settled, wix.untied) == (0, True, Decimal("0.00"))
    flags = {(f.code, f.source_alias) for f in result.coverage_flags}
    assert ("processor_gross_unsettled", "wix") not in flags


def _sale(txn_id: str) -> list[str]:
    return _paypal(txn_id, "05", "Website Payment", "100.00", "", "100.00")


def _matched_transfer(txn_id: str, kind: str, net: str) -> tuple[list[str], list[str]]:
    """A PayPal transfer and the bank row that names it with the exact opposite amount."""
    paypal = _paypal(txn_id, "07", kind, net, "", net)
    bank_amount = net[1:] if net.startswith("-") else f"-{net}"
    return paypal, _bank("1/8/2030", f"PAYPAL TRANSFER {txn_id}", bank_amount, "Fundraiser Income")


def test_inbound_transfers_never_cancel_payouts(tmp_path: Path) -> None:
    # SETTLED_PAYPAL leaves untied 0.00; each probe adds a 100.00 sale.
    out_row, out_bank = _matched_transfer("TXN-EX-21", "General Withdrawal", "-50.00")
    in_row, in_bank = _matched_transfer("TXN-EX-22", "Bank Deposit to PP Account", "50.00")
    both = _run(
        tmp_path,
        paypal=[*SETTLED_PAYPAL, _sale("TXN-EX-20"), out_row, in_row],
        bank=[*BANK_ROWS, out_bank, in_bank],
    )
    assert _settlements(both) == 3  # all three transfers are reference-matched
    pay = _summary(both, "paypal")
    # 100.00 sale - 50.00 payout + 50.00 deposit: the deposit adds money, it cancels nothing.
    assert (pay.untied, pay.settled) == (Decimal("100.00"), False)

    dep_row, dep_bank = _matched_transfer("TXN-EX-23", "Bank Deposit to PP Account", "100.00")
    deposit = _run(
        tmp_path,
        paypal=[*SETTLED_PAYPAL, _sale("TXN-EX-20"), dep_row],
        bank=[*BANK_ROWS, dep_bank],
    )
    assert _settlements(deposit) == 2
    assert _summary(deposit, "paypal").untied == Decimal("200.00")


def test_standalone_refund_reduces_the_untied_balance(tmp_path: Path) -> None:
    # A refund of the PayPal-primary sale (not an overlap secondary) feeds untied.
    refund = _paypal(
        "TXN-EX-24", "08", "Payment Refund", "-10.00", "0.30", "-9.70", reference="TXN-EX-1"
    )
    result = _run(tmp_path, paypal=[*SETTLED_PAYPAL, refund])
    assert _one(result, "paypal", native_id="TXN-EX-24").reconciliation_state == (
        "processor_refund"
    )
    pay = _summary(result, "paypal")
    assert (pay.untied, pay.settled) == (Decimal("-9.70"), False)


def test_unmatched_payout_keeps_the_alias_unsettled(tmp_path: Path) -> None:
    # Untied is 0.00 (the matched payout covers the balance) but a second, unmatched payout
    # transfer still means processor money is unaccounted for.
    extra = _paypal("TXN-EX-6", "25", "General Withdrawal", "-20.00", "", "-20.00")
    result = _run(tmp_path, paypal=[*SETTLED_PAYPAL, extra])
    pay = _summary(result, "paypal")
    assert (pay.untied, pay.settled) == (Decimal("0.00"), False)


def test_unresolved_rows_leave_the_untied_amount_unknown(tmp_path: Path) -> None:
    result = _run(tmp_path, wix=_edit(WIX_ROWS, 0, {W_STATUS: "Chargeback"}))
    wix = _summary(result, "wix")
    assert (wix.settled, wix.untied) == (False, None)

    no_net = _run(tmp_path, wix=_edit(WIX_ROWS, 0, {W_NET: ""}))
    assert (_summary(no_net, "wix").settled, _summary(no_net, "wix").untied) == (False, None)


# --------------------------------------------------------------------------------------
# Category Mapping guidance and crosswalk
# --------------------------------------------------------------------------------------


def test_category_mapping_guides_processor_rows_only(tmp_path: Path) -> None:
    result = _run(tmp_path)
    by_key = {c.record_key: c for c in result.classifications}
    shirt = _one(result, "wix", native_id="pi_ex_001")
    assert (by_key[shirt.record_key].status, by_key[shirt.record_key].target_category) == (
        "matched",
        "Spirit Wear",
    )
    raffle = _one(result, "wix", native_id="pp_ex_007")
    assert by_key[raffle.record_key].status == "ambiguous"
    assert by_key[raffle.record_key].target_category is None
    assert by_key[raffle.record_key].rule_rows == (3, 4)
    (ambiguous,) = _of_kind(result, "category_mapping_ambiguous")
    assert [ref.record_key for ref in ambiguous.affected] == [raffle.record_key]
    parent = _one(result, "paypal", native_id="TXN-EX-1", row_role="payment")
    assert by_key[parent.record_key].status == "no_text"
    # The "deposit" keyword never overrides a bank FINAL CATEGORY.
    bank_keys = {t.record_key for t in _txn(result, "bank-checking")}
    assert not bank_keys & set(by_key)
    assert _cells(result)[("Fundraiser Income", "2030-01")] == Decimal("1317.11")


def test_incomplete_mapping_row_is_visible_and_never_halts(tmp_path: Path) -> None:
    result = _run(tmp_path, mapping=[*MAPPING_VALUES, ["hat", ""], ["", "Caps"]])
    ignored = [i for i in result.row_warnings if i.code == "category_mapping_row_ignored"]
    assert [(i.source_alias, i.row_number, i.severity) for i in ignored] == [
        ("category-mapping", 6, "warning"),
        ("category-mapping", 7, "warning"),
    ]
    assert result.pnl_control.status == "matched"  # the bank view is unaffected
    shirt = _one(result, "wix", native_id="pi_ex_001")
    assert {c.record_key: c.status for c in result.classifications}[shirt.record_key] == "matched"
    flags = {(f.code, f.source_alias): f.count for f in result.coverage_flags}
    assert flags[("category_mapping_row_ignored", "category-mapping")] == 2


def test_crosswalk_maps_monthly_cells_with_exact_cent_shares(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.crosswalk_version == 2
    supplies = {
        (c.month.month, c.target_category): c.amount
        for c in result.crosswalk_cells
        if c.source_category == "Classroom Supplies"
    }
    assert supplies == {
        (1, "Grade Supplies"): Decimal("-18.88"),
        (1, "Shared Supplies"): Decimal("-56.62"),
        (2, "Grade Supplies"): Decimal("-3.00"),
        (2, "Shared Supplies"): Decimal("-9.00"),
    }
    for cell in result.monthly_cells:
        mapped = [
            c.amount
            for c in result.crosswalk_cells
            if (c.source_category, c.month) == (cell.category, cell.month)
        ]
        if mapped:
            assert sum(mapped) == cell.net
    unmapped = sorted(d.category or "" for d in _of_kind(result, "crosswalk_unmapped"))
    assert unmapped == ["Donations", "internal transfer"]


def test_missing_crosswalk_is_a_flag_not_invented_mapping(tmp_path: Path) -> None:
    result = _run(tmp_path, crosswalk="")
    assert result.crosswalk_version is None and result.crosswalk_cells == ()
    assert "crosswalk_absent" in {f.code for f in result.coverage_flags}
    assert not _of_kind(result, "crosswalk_unmapped")


@pytest.mark.parametrize(
    "amount", ["0.01", "-0.01", "100.00", "-75.50", "1234.57", "0.00", "-0.02"]
)
def test_crosswalk_amounts_always_conserve(amount: str) -> None:
    thirds = [
        CrosswalkTarget("A", Decimal("0.3333")),
        CrosswalkTarget("B", Decimal("0.3333")),
        CrosswalkTarget("C", Decimal("0.3334")),
    ]
    parts = crosswalk_amounts(Decimal(amount), thirds)
    assert sum(value for _, value in parts) == Decimal(amount)
    assert all(value == value.quantize(Decimal("0.01")) for _, value in parts)
    assert [name for name, _ in parts] == ["A", "B", "C"]


@pytest.mark.parametrize(
    ("targets", "code"),
    [
        ([], "crosswalk_empty"),
        (
            [CrosswalkTarget("A", Decimal("0.5")), CrosswalkTarget("B", Decimal("0.4"))],
            "crosswalk_shares_invalid",
        ),
    ],
)
def test_crosswalk_amounts_reject_invalid_shares(targets: list[CrosswalkTarget], code: str) -> None:
    with pytest.raises(ReconcileError) as caught:
        crosswalk_amounts(Decimal("100.00"), targets)
    assert caught.value.code == code


# --------------------------------------------------------------------------------------
# Visibility, identity and invariants
# --------------------------------------------------------------------------------------


def test_normalization_row_warnings_stay_visible(tmp_path: Path) -> None:
    fallback = ["1/16/2030", "Example fallback fee", "-1.00", "", "Posted", "Fees", "", ""]
    mystery = _paypal("TXN-EX-9", "26", "Mystery Payment", "15.00", "", "15.00")
    result = _run(tmp_path, bank=[*BANK_ROWS, fallback], paypal=[*PAYPAL_ROWS, mystery])
    warned = _warned(result)
    assert ("bank-checking", "final_category_fallback") in warned
    assert ("paypal", "unknown_type") in warned
    flags = {(f.code, f.source_alias): f.count for f in result.coverage_flags}
    assert flags[("final_category_fallback", "bank-checking")] == 1

    # An unrecognized PayPal type is never counted as a sale.
    row = _one(result, "paypal", native_id="TXN-EX-9")
    assert row.reconciliation_state == "conflict"
    (finding,) = _of_kind(result, "processor_type_unrecognized")
    assert [ref.record_key for ref in finding.affected] == [row.record_key]
    assert _summary(result, "paypal").gross == Decimal("60.00")

    # The rule holds for a direct build() caller that passes no row warnings.
    config = _config(tmp_path)
    captured = _harness(config, paypal=[*PAYPAL_ROWS, mystery]).capture()
    direct = build(normalize(captured), controls_from(captured, config))
    assert _one(direct, "paypal", native_id="TXN-EX-9").reconciliation_state == "conflict"
    assert _summary(direct, "paypal").gross == Decimal("60.00")


def test_split_sum_mismatch_publishes_through_from_capture(tmp_path: Path) -> None:
    # Operator decision 2026-10-22: a split that does not add up is flagged and published with
    # an explicit remainder component, never a SourceValidationError for the whole run.
    typo = _bank(
        "1/16/2030", "Example split vendor", "-500.95", "Classroom Supplies: -300.00, Fees: -200.00"
    )
    result = _run(tmp_path, bank=[*BANK_ROWS, typo])
    assert isinstance(result, Reconciliation)
    assert ("bank-checking", "split_sum_mismatch") in _warned(result)
    (warning,) = [i for i in result.row_warnings if i.code == "split_sum_mismatch"]
    assert (warning.field, warning.severity) == ("final_category", "warning")

    row = _one(result, "bank-checking", description="Example split vendor")
    assert [(a.category, a.amount) for a in row.allocations] == [
        ("Classroom Supplies", Decimal("-300.00")),
        ("Fees", Decimal("-200.00")),
        (UNALLOCATED_SPLIT_CATEGORY, Decimal("-0.95")),
    ]
    assert sum((a.amount for a in row.allocations), Decimal(0)) == row.gross
    # The gap reaches the source view as its own category and stays visibly unmapped.
    assert _cells(result)[(UNALLOCATED_SPLIT_CATEGORY, "2030-01")] == Decimal("-0.95")
    assert UNALLOCATED_SPLIT_CATEGORY in {
        d.category for d in _of_kind(result, "crosswalk_unmapped")
    }


def test_capture_coverage_warnings_become_coverage_flags(tmp_path: Path) -> None:
    flags = {(f.code, f.source_alias) for f in _run(tmp_path).coverage_flags}
    assert ("observed_outside_declared_coverage", "bank-checking") in flags
    assert ("no_declared_coverage", "paypal") in flags
    assert ("processor_view_inconsistent", "wix") in flags


def test_discrepancy_and_match_ids_are_stable_under_reordering(tmp_path: Path) -> None:
    first = _run(tmp_path)
    reordered = _run(
        tmp_path,
        bank=list(reversed(BANK_ROWS)),
        paypal=[PAYPAL_ROWS[0], *reversed(PAYPAL_ROWS[1:])],
        wix=list(reversed(WIX_ROWS)),
    )
    assert [d.discrepancy_id for d in first.discrepancies] == [
        d.discrepancy_id for d in reordered.discrepancies
    ]
    assert {m.match_id for m in first.matches} == {m.match_id for m in reordered.matches}
    assert [c.to_dict() | {"contributors": None} for c in first.monthly_cells] == [
        c.to_dict() | {"contributors": None} for c in reordered.monthly_cells
    ]
    assert all(re.fullmatch(r"DISC-[0-9a-f]{64}", d.discrepancy_id) for d in first.discrepancies)


def test_every_discrepancy_kind_has_a_declared_impact() -> None:
    assert {impact for impact, _ in DISCREPANCY_KINDS.values()} <= set(reconcile.IMPACTS)


def test_duplicate_control_capture_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    captured = _harness(config).capture()
    pnl = captured.by_alias["pnl"]
    doubled = dataclasses.replace(
        captured, captures=(*captured.captures, dataclasses.replace(pnl, alias="pnl-copy"))
    )
    with pytest.raises(ReconcileError) as caught:
        controls_from(doubled, config)
    assert caught.value.code == "duplicate_control"


def _transactions(tmp_path: Path) -> tuple[list[Transaction], ReconciliationControls]:
    config = _config(tmp_path)
    captured = _harness(config).capture()
    return list(normalize(captured)), controls_from(captured, config)


@pytest.mark.parametrize(
    "code",
    [
        "duplicate_record_key",
        "split_not_conserved",
        "currency_mixing",
        "allocation_identity_mismatch",
        "bank_row_incomplete",
        "unknown_source_kind",
        "missing_source_ref",
    ],
)
def test_broken_normalization_invariants_fail_closed(tmp_path: Path, code: str) -> None:
    transactions, controls = _transactions(tmp_path)
    bank = next(t for t in transactions if t.source_kind == "bank")
    index = transactions.index(bank)
    if code == "duplicate_record_key":
        transactions.append(bank)
    elif code == "split_not_conserved":
        transactions[index] = dataclasses.replace(bank, gross=Decimal("1.00"))
    elif code == "currency_mixing":
        transactions[index] = dataclasses.replace(bank, currency="CAD")
    elif code == "allocation_identity_mismatch":
        moved = Allocation("v1:other:x:0", bank.revision_hash, "Fees", bank.gross or Decimal(0))
        transactions[index] = dataclasses.replace(bank, allocations=(moved,))
    elif code == "bank_row_incomplete":
        transactions[index] = dataclasses.replace(bank, allocations=())
    elif code == "missing_source_ref":
        transactions[index] = dataclasses.replace(bank, refs=())
    else:
        transactions[index] = dataclasses.replace(bank, source_kind="ledger")
    with pytest.raises(ReconcileError) as caught:
        build(transactions, controls)
    assert caught.value.code == code


CANARY = "CANARY-PAYEE-7731"


def test_reconcile_errors_never_echo_a_cell_value(tmp_path: Path) -> None:
    bank = [list(r) for r in BANK_ROWS]
    bank[1] = _bank("1/9/2030", CANARY, "-75.50", f"{CANARY} Supplies")
    config = _config(tmp_path)
    harness = _harness(config, bank=bank)
    transactions = list(normalize(harness.capture()))
    index = next(i for i, t in enumerate(transactions) if t.description == CANARY)
    transactions[index] = dataclasses.replace(transactions[index], gross=Decimal("9876.54"))
    with pytest.raises(ReconcileError) as caught:
        build(transactions, controls_from(harness.capture(), config))
    chain: list[BaseException] = []
    error: BaseException | None = caught.value
    while error is not None:
        chain.append(error)
        error = error.__cause__ or error.__context__
    for item in chain:
        assert CANARY not in str(item) and "9876.54" not in str(item)


def _digest_crosswalk(**changes: Any) -> CategoryCrosswalk:
    targets = changes.pop(
        "targets",
        (
            CrosswalkTarget("Grade Supplies", Decimal("0.25")),
            CrosswalkTarget("Shared Supplies", Decimal("0.75")),
        ),
    )
    entry = CrosswalkEntry(
        source_category=changes.pop("source_category", "Classroom Supplies"),
        targets=targets,
        note=changes.pop("note", "documented split"),
    )
    return CategoryCrosswalk(version=changes.pop("version", 1), entries=(entry,))


# A fixed literal: the digest of the default ``_digest_crosswalk()`` content. Changing the
# digest's canonical form must be a deliberate, visible edit here.
KNOWN_CROSSWALK_DIGEST = "f29d30b8f04a4d154576b1dc596e1eee1ee7852778fbf61df069ba53e305828b"


def test_crosswalk_digest_covers_every_component() -> None:
    assert crosswalk_digest(None) is None
    assert crosswalk_digest(_digest_crosswalk()) == KNOWN_CROSSWALK_DIGEST
    # Shares are normalized: 0.25/0.75 and 0.250/0.750 are the same content.
    same = _digest_crosswalk(
        targets=(
            CrosswalkTarget("Grade Supplies", Decimal("0.250")),
            CrosswalkTarget("Shared Supplies", Decimal("0.750")),
        )
    )
    assert crosswalk_digest(same) == KNOWN_CROSSWALK_DIGEST
    changed = {
        "version": _digest_crosswalk(version=2),
        "source_category": _digest_crosswalk(source_category="Field Trips"),
        "note": _digest_crosswalk(note="reworded"),
        "target_category": _digest_crosswalk(
            targets=(
                CrosswalkTarget("Grade Supplies", Decimal("0.25")),
                CrosswalkTarget("Other Supplies", Decimal("0.75")),
            )
        ),
        "share_value": _digest_crosswalk(
            targets=(
                CrosswalkTarget("Grade Supplies", Decimal("0.5")),
                CrosswalkTarget("Shared Supplies", Decimal("0.5")),
            )
        ),
        # Target order decides which target gets leftover cents, so it is content.
        "target_order": _digest_crosswalk(
            targets=(
                CrosswalkTarget("Shared Supplies", Decimal("0.75")),
                CrosswalkTarget("Grade Supplies", Decimal("0.25")),
            )
        ),
    }
    # Entry order is content too: the digest records entries exactly as configured.
    first, second = (
        _digest_crosswalk().entries[0],
        _digest_crosswalk(source_category="Field Trips").entries[0],
    )
    changed["entry_order"] = CategoryCrosswalk(version=1, entries=(second, first))
    two_entries = CategoryCrosswalk(version=1, entries=(first, second))
    assert crosswalk_digest(two_entries) != crosswalk_digest(changed["entry_order"])
    digests = {name: crosswalk_digest(item) for name, item in changed.items()}
    assert KNOWN_CROSSWALK_DIGEST not in digests.values()
    assert len(set(digests.values())) == len(digests)


def test_reconciliation_records_the_crosswalk_digest(tmp_path: Path) -> None:
    result = _run(tmp_path)
    config = _config(tmp_path)
    assert config.main_reports is not None
    assert result.crosswalk_sha256 == crosswalk_digest(config.main_reports.crosswalk)
    assert result.to_dict()["crosswalk_sha256"] == result.crosswalk_sha256
    # A second workbook directory whose config has no crosswalk at all records no digest.
    without = tmp_path / "without-crosswalk"
    without.mkdir()
    assert _run(without, crosswalk="").crosswalk_sha256 is None


@pytest.mark.parametrize(
    ("reference", "text", "ignore_case", "found"),
    [
        ("TXN-EX-3", "PAYPAL TRANSFER TXN-EX-3", False, True),
        ("TXN-EX-3", "PAYPAL TRANSFER txn-ex-3", False, False),
        ("TXN-EX-3", "PAYPAL TRANSFER txn-ex-3", True, True),
        ("TXN-EX-3", "PAYPAL TRANSFER TXN-EX-34", False, False),
        ("TXN-EX-3", "PAYPAL TRANSFER XTXN-EX-3", True, False),
        ("a.b", "ref aXb", False, False),
    ],
)
def test_reference_token_is_a_whole_token(
    reference: str, text: str, ignore_case: bool, found: bool
) -> None:
    token = reference_token(reference, ignore_case=ignore_case)
    assert (token.search(text) is not None) is found
