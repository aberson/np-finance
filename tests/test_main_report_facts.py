"""Tests for np_finance.main_reports.facts — school-year and calendar-year projections.

Every fixture is fictional (``Example`` placeholders, fake ids). Scenarios run through the
production path: private config loaded by the real loader -> read-only capture over fake
gspread workbooks -> :func:`reconcile.from_capture` -> adjustments recorded by
:func:`adjustments.record` into our own fake workbook and recaptured ->
:func:`adjustments.project` -> :func:`facts.build_from`, with the reimbursement side loaded
from a fictional schema-v2 bundle file by :func:`reimbursement_report.load_bundle`. Building
facts performs no live Google call, workbook write or file write.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from np_finance import ids, reimbursement_report
from np_finance.config import CrosswalkTarget
from np_finance.main_reports import facts, reconcile
from np_finance.main_reports.adjustments import (
    AdjustmentConflictError,
)
from np_finance.main_reports.facts import FactsError, build_from, reporting_periods
from np_finance.main_reports.models import (
    EXPENSE_BUCKETS,
    AdjustedLedger,
    AdjustmentIssue,
    Period,
    ReportFacts,
    Transaction,
    canonical_json_bytes,
)
from tests.conftest import (
    AS_OF,
    BANK_HEADER,
    BANK_ROWS,
    BUDGET_ROWS,
    CHECK_JULY,
    CROSSWALK_TOML,
    DONATION_JAN,
    FULL_BANK_COVERAGE,
    PAID_TICKET,
    PAYMENT_REFERENCE,
    PAYPAL_HEADER,
    PNL_VALUES,
    VENDOR_AS_OF,
    VENDOR_DEC,
    VENDOR_JUNE,
    VENDOR_LATER,
    CfoWorksheet,
    Scenario,
    _adjusted_scenario,
    _adjustment,
    _bank,
    _budget_row,
    _bundle_payload,
    _config,
    _item,
    _record_payment,
    _seal,
    _ticket,
    _wix,
)


def _months(view: Any) -> dict[str, tuple[Decimal, Decimal]]:
    return {m.month.isoformat()[:7]: (m.income, m.expense) for m in view.months}


def _rows(result: ReportFacts, name: str) -> list[tuple[str, Decimal]]:
    return [(row.kind, row.amount) for row in result.bridge(name).rows]


def _descriptions(row_refs: Sequence[Any], rec_txns: Sequence[Transaction]) -> set[str]:
    by_key = {t.record_key: t.description for t in rec_txns}
    return {str(by_key[ref.record_key]) for ref in row_refs}


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*"))


# --------------------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "school", "calendar"),
    [
        (date(2030, 6, 30), (date(2029, 7, 1), date(2030, 7, 1)), date(2030, 1, 1)),
        (date(2030, 7, 1), (date(2030, 7, 1), date(2031, 7, 1)), date(2030, 1, 1)),
        (date(2029, 12, 31), (date(2029, 7, 1), date(2030, 7, 1)), date(2029, 1, 1)),
        (date(2030, 1, 1), (date(2029, 7, 1), date(2030, 7, 1)), date(2030, 1, 1)),
    ],
)
def test_reporting_periods_split_at_june_july_and_december_january(
    as_of: date, school: tuple[date, date], calendar: date
) -> None:
    periods = reporting_periods(as_of, 7)
    assert (periods.school.start, periods.school.end_exclusive) == school
    assert periods.school.basis == "school" and periods.calendar.basis == "calendar"
    assert periods.calendar.start == calendar
    assert periods.calendar.end_exclusive == date(calendar.year + 1, 1, 1)
    # Half-open internally, clipped to the as-of date, inclusive for display.
    for period in (periods.school, periods.calendar):
        assert period.clip_end == as_of + timedelta(days=1)
        assert period.position(as_of) == "current"
        assert period.position(as_of + timedelta(days=1)) == "later"
        assert period.position(period.start) == "current"
        assert period.position(period.start - timedelta(days=1)) == "prior"
        assert period.position(None) == "undated"
        assert period.end_inclusive == period.end_exclusive - timedelta(days=1)
    # The legacy FY label is preserved beside the explicit label.
    assert periods.school.year_label == ids.fiscal_year_label(as_of, 7)


def test_period_labels_and_clipping() -> None:
    periods = reporting_periods(AS_OF, 7)
    assert periods.school.label == "School year 2030–31"
    assert periods.school.year_label == 2031
    assert periods.calendar.label == "Calendar year 2030"
    assert periods.to_dict()["school"]["end_inclusive"] == "2031-06-30"
    assert periods.to_dict()["school"]["clip_end"] == "2030-08-16"
    # A period whose as-of is past its end clips at its own end.
    past = Period("school", date(2029, 7, 1), date(2030, 7, 1), AS_OF)
    assert past.clip_end == date(2030, 7, 1) and past.position(date(2030, 7, 1)) == "later"
    # A January start month makes the school year the calendar year.
    calendar_school = reporting_periods(AS_OF, 1).school
    assert (calendar_school.start, calendar_school.label) == (date(2030, 1, 1), "School year 2030")


@pytest.mark.parametrize("month", [0, 13])
def test_invalid_start_month_is_refused(month: int) -> None:
    with pytest.raises(FactsError) as caught:
        reporting_periods(AS_OF, month)
    assert caught.value.code == "start_month_invalid"


# --------------------------------------------------------------------------------------
# Production path: capture -> reconcile -> record -> recapture -> project -> facts
# --------------------------------------------------------------------------------------


def test_facts_through_the_production_path(tmp_path: Path) -> None:
    scenario, moved, added = _adjusted_scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    writes = len(scenario.harness.assumptions.batch_update_calls)
    before_files = _files(tmp_path)
    bundle_bytes = scenario.bundle_path.read_bytes()

    result = build_from(capture_set, ledger, bundle, scenario.config)

    # Pure: no workbook write, no file, and every input unchanged.
    scenario.harness.assert_no_cfo_writes()
    assert len(scenario.harness.assumptions.batch_update_calls) == writes
    assert _files(tmp_path) == before_files
    assert scenario.bundle_path.read_bytes() == bundle_bytes
    assert bundle == reimbursement_report.load_bundle(scenario.bundle_path)
    assert ledger == scenario.inputs()[1]
    assert scenario.config.fiscal_year.start_month == 7

    assert result.as_of == AS_OF and result.applied_adjustments == ledger.applied
    assert set(result.applied_adjustments) == {moved.adjustment_id, added.adjustment_id}
    assert result.journal_sha256 == ledger.journal_sha256
    assert result.pnl_control_status == "matched"
    # Unresolved reconciliation findings travel into the facts (Donations is unmapped).
    assert result.discrepancy_ids == tuple(d.discrepancy_id for d in ledger.source.unresolved)
    assert result.discrepancy_ids
    assert result.pending_adjustments == () and result.superseded_adjustments == ()
    assert result.periods == reporting_periods(AS_OF, 7)

    calendar_source = result.view("calendar", "source")
    assert (calendar_source.income, calendar_source.expense, calendar_source.net) == (
        Decimal("150.00"),
        Decimal("-91.75"),
        Decimal("58.25"),
    )
    calendar_adjusted = result.view("calendar", "adjusted")
    assert _months(calendar_adjusted) == {
        "2030-01": (Decimal("100.00"), Decimal("0.00")),
        "2030-07": (Decimal("50.00"), Decimal("-86.75")),
        "2030-08": (Decimal("25.00"), Decimal("-5.00")),
    }
    assert calendar_adjusted.net == Decimal("83.25") and calendar_adjusted.complete
    school_source = result.view("school", "source")
    assert (school_source.income, school_source.expense, school_source.net) == (
        Decimal("50.00"),
        Decimal("-51.75"),
        Decimal("-1.75"),
    )
    school_adjusted = result.view("school", "adjusted")
    assert school_adjusted.category_totals() == (
        ("Classroom Supplies", Decimal("-45.00")),
        ("Donations", Decimal("25.00")),
        ("Field Trips", Decimal("-45.00")),
        ("Fundraiser Income", Decimal("50.00")),
        ("Processing Fees", Decimal("-1.75")),
    )
    assert school_adjusted.net == Decimal("-16.75")

    assert all(bridge.balanced for bridge in result.bridges), [
        (b.name, b.residual) for b in result.bridges if not b.balanced
    ]
    assert [b.name for b in result.bridges] == list(facts.BRIDGE_NAMES)

    payload = json.loads(canonical_json_bytes(result.to_dict()))
    assert payload["schema_version"] == 1
    assert payload["periods"]["school"]["label"] == "School year 2030–31"
    assert all(item["balanced"] for item in payload["bridges"])


def test_december_january_and_as_of_boundaries_bridge_to_the_source_pnl(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    result = scenario.facts()
    _, rec = scenario.reconciled()
    calendar = result.bridge("calendar_source_scope")
    assert (
        calendar.from_amount
        == sum((t.net for t in rec.pnl_totals), Decimal("0.00"))
        == Decimal("41.25")
    )
    assert _rows(result, "calendar_source_scope") == [
        ("before_period", Decimal("10.00")),  # Dec 31 row is outside calendar 2030
        ("after_period", Decimal("7.00")),  # the row after the as-of date is outside
    ]
    before, after = calendar.rows
    assert _descriptions(before.refs, rec.transactions) == {VENDOR_DEC}
    assert _descriptions(after.refs, rec.transactions) == {VENDOR_LATER}
    # Jan 1 and the as-of day itself are inside.
    jan = {c.category: c.net for c in result.view("calendar", "source").cells if c.month.month == 1}
    assert jan == {"Donations": Decimal("100.00")}
    assert calendar.to_amount == Decimal("58.25") and calendar.balanced

    school = result.bridge("school_source_scope")
    assert _rows(result, "school_source_scope") == [
        ("before_period", Decimal("-50.00")),
        ("after_period", Decimal("7.00")),
    ]
    assert _descriptions(school.rows[0].refs, rec.transactions) == {
        VENDOR_DEC,
        DONATION_JAN,
        VENDOR_JUNE,  # June 30 is the prior school year
    }
    assert school.to_amount == Decimal("-1.75") and school.balanced
    # No adjustments: source and adjusted views agree and their bridges have no rows.
    assert result.bridge("school_adjustments").rows == ()
    assert result.view("school", "adjusted").cells == result.view("school", "source").cells


def test_adjustment_bridges_attribute_each_recorded_entry(tmp_path: Path) -> None:
    scenario, moved, added = _adjusted_scenario(tmp_path)
    result = scenario.facts()
    school = result.bridge("school_adjustments")
    assert sorted((row.adjustment_ids, row.amount) for row in school.rows) == sorted(
        [((moved.adjustment_id,), Decimal("-40.00")), ((added.adjustment_id,), Decimal("25.00"))]
    )
    assert school.from_amount == Decimal("-1.75") and school.to_amount == Decimal("-16.75")
    assert school.balanced
    # Moving June 30 to July 1 stays inside calendar 2030: only the additive entry shows.
    calendar = result.bridge("calendar_adjustments")
    assert [(row.adjustment_ids, row.amount) for row in calendar.rows] == [
        ((added.adjustment_id,), Decimal("25.00"))
    ]
    (moved_row,) = [row for row in school.rows if row.adjustment_ids == (moved.adjustment_id,)]
    assert [ref.record_key for ref in moved_row.refs] == [scenario.txn(VENDOR_JUNE).record_key]

    window = result.bridge("calendar_to_school")
    assert _rows(result, "calendar_to_school") == [("only_in_base_period", Decimal("-100.00"))]
    assert (window.from_amount, window.to_amount) == (Decimal("83.25"), Decimal("-16.75"))
    assert window.balanced


def test_june_expense_paid_in_july_is_counted_once(tmp_path: Path) -> None:
    scenario, _, _ = _adjusted_scenario(tmp_path)
    result = scenario.facts()
    reimbursements = result.reimbursements
    by_key = {item.item_key: item for item in reimbursements.items}
    june, july = by_key["new-01:line:1"], by_key["new-01:line:2"]
    # A cross-year claim splits at item level: one ticket, two school years.
    assert (june.expense_bucket, june.payment_bucket) == ("prior", "current")
    assert (july.expense_bucket, july.payment_bucket) == ("current", "current")
    assert june.received == july.received == date(2030, 7, 3)

    # Expense view by item date; payment view by payment date; never added together.
    assert reimbursements.expense("current") == Decimal("43.00")
    assert reimbursements.expense("current", "A") == Decimal("25.00")
    assert reimbursements.expense("prior") == Decimal("70.00")
    assert reimbursements.paid("current") == Decimal("45.00")
    assert reimbursements.paid("current", "prior") == Decimal("25.00")
    assert reimbursements.paid("prior") == Decimal("15.00")
    timing = result.bridge("school_payment_timing")
    assert _rows(result, "school_payment_timing") == [
        ("paid_in_period_expense_prior", Decimal("25.00")),
        ("approved_in_period_payment_unpaid", Decimal("-5.00")),
    ]
    assert timing.rows[0].item_keys == ("new-01:line:1",)
    assert timing.rows[1].item_keys == ("new-03:line:2",)
    assert (timing.from_amount, timing.to_amount) == (
        Decimal("25.00"),
        Decimal("45.00"),
    ) and timing.balanced

    # The July check joins exactly one bank row; the expense basis swaps that payment for the
    # current-year item only, so the June item and the payment are never counted twice.
    joins = {join.ticket_ref: join for join in reimbursements.joins}
    assert joins[PAID_TICKET].state == "matched"
    assert joins[PAID_TICKET].reference == PAYMENT_REFERENCE
    assert [ref.record_key for ref in joins[PAID_TICKET].bank_refs] == [
        scenario.txn(CHECK_JULY).record_key
    ]
    assert joins["P-002"].state == "no_reference"
    basis = result.bridge("school_expense_basis")
    # The removed payment is broken down by the expense date of the items it paid.
    assert _rows(result, "school_expense_basis") == [
        ("matched_payment_prior_items", Decimal("25.00")),
        ("matched_payment_current_items", Decimal("20.00")),
        ("joined_item_expense", Decimal("-20.00")),
    ]
    assert [row.item_keys for row in basis.rows] == [
        ("new-01:line:1",),
        ("new-01:line:2",),
        ("new-01:line:2",),
    ]
    assert basis.rows[0].refs == basis.rows[1].refs == joins[PAID_TICKET].bank_refs
    assert (basis.from_amount, basis.to_amount) == (
        Decimal("-16.75"),
        Decimal("8.25"),
    ) and basis.balanced
    # Joining changes no adjudication: the bundle's own reducers are unchanged.
    bundle = scenario.inputs()[2]
    assert bundle.tickets[0].live.payment_status == "PAID"
    assert bundle.summary == reimbursement_report.load_bundle(scenario.bundle_path).summary


def test_old_outstanding_requests_and_missing_dates_stay_visible(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    result = scenario.facts()
    reimbursements = result.reimbursements
    bundle = scenario.inputs()[2]
    # Every unsettled ticket stays in the queue whatever its dates.
    assert [entry.ticket_ref for entry in reimbursements.queue] == [
        "P-001",
        "NEW-02",
        "NEW-03",
        "NEW-04",
    ]
    assert [e.review_key for e in reimbursements.queue] == [
        t.review_key for t in bundle.active_tickets
    ]
    old = reimbursements.queue[0]
    assert old.carryover and old.earliest_expense_date == date(2029, 5, 10)
    assert old.carryover_basis == "expense_date"
    assert old.pay_now == Decimal("30.00")
    assert reimbursements.outstanding == bundle.summary.outstanding == Decimal("35.00")
    assert reimbursements.open_amount("prior") == Decimal("30.00")
    assert reimbursements.open_amount("prior", "A") == Decimal("30.00")
    # Approved open amounts over every bucket are exactly the pay-now outstanding.
    assert reimbursements.outstanding == sum(
        (reimbursements.open_amount(bucket, "A") for bucket in EXPENSE_BUCKETS), Decimal("0.00")
    )
    # A missing date is its own visible bucket, never a guessed year.
    undated = reimbursements.queue[1]
    assert undated.undated_items == 1 and not undated.carryover
    assert undated.carryover_basis is None
    assert reimbursements.expense("undated") == Decimal("12.00")
    assert reimbursements.expense("later") == Decimal("9.00")
    codes = {issue.code: issue.count for issue in result.issues}
    assert codes["reimbursement_item_undated"] == 1
    # The legacy prior-paid ticket has no reference by construction: no finding.
    assert "reimbursement_payment_no_reference" not in codes
    assert "bundle_as_of_mismatch" not in codes
    assert "reimbursement_item_unpriced" not in codes
    # Every item is in exactly one total group; stable keys are carried unchanged.
    assert sum(t.count for t in reimbursements.totals) == len(reimbursements.items) == 9
    assert [i.item_key for i in reimbursements.items] == [
        item.item_key for ticket in bundle.tickets for item in ticket.items
    ]
    # The mail collection window is reported as stored, not re-filtered to July.
    assert reimbursements.cutoff_date == date(2030, 6, 1) == bundle.settings.cutoff_date
    assert (reimbursements.first_received, reimbursements.last_received) == (
        date(2030, 6, 2),
        date(2030, 8, 10),
    )


def test_budget_targets_sit_beside_crosswalked_actuals(tmp_path: Path) -> None:
    scenario, _, _ = _adjusted_scenario(tmp_path)
    result = scenario.facts()
    budget = result.budget
    assert budget.fiscal_year == 2031 and budget.crosswalk_version == 3
    assert [
        (line.category, line.line_type, line.target, line.actual, line.actual_status)
        for line in budget.lines
    ] == [
        ("Classroom Supplies", "expense", Decimal("500.00"), Decimal("-45.00"), "observed"),
        ("Field Trips", "expense", Decimal("300.00"), Decimal("-45.00"), "observed"),
        ("Fundraising", "income", Decimal("1500.00"), Decimal("50.00"), "observed"),
        # Mapped, complete coverage, no activity: an OBSERVED zero.
        ("Assemblies", "expense", Decimal("200.00"), Decimal("0.00"), "observed"),
        # Not a crosswalk target: unknown, never an invented zero.
        ("Library Books", "expense", Decimal("100.00"), None, "category_unmapped"),
    ]
    assert ("budget_actual_unknown", 1, "category_unmapped") in {
        (i.code, i.count, i.subject) for i in result.issues
    }
    assert budget.other_year_rows == 1
    assert budget.unmapped == (("Donations", Decimal("25.00")),)
    assert budget.unbudgeted == (("Fees and Charges", Decimal("-1.75")),)
    bridge = result.bridge("school_budget_crosswalk")
    assert _rows(result, "school_budget_crosswalk") == [("unmapped_category", Decimal("-25.00"))]
    assert (bridge.from_amount, bridge.to_amount) == (Decimal("-16.75"), Decimal("-41.75"))
    assert bridge.balanced


def test_budget_row_problems_are_visible_issues(tmp_path: Path) -> None:
    rows = [
        _budget_row("2031", "expense", "proposed", "12,34", "Classroom Supplies"),
        _budget_row("2031", "expense", "proposed", "", "Field Trips"),
        _budget_row("FY31", "expense", "proposed", "10", "Field Trips"),
        _budget_row("2031", "other", "proposed", "10", "Fundraising"),
        _budget_row("2031", "income", "proposed", "20", "Fundraising"),
    ]
    result = Scenario(tmp_path, budget=rows).facts()
    issues = sorted((issue.code, issue.subject) for issue in result.issues)
    assert [item for item in issues if item[0].startswith("budget_")] == [
        ("budget_actual_unknown", "ambiguous"),
        ("budget_amount_missing", "adopted row 2"),
        ("budget_amount_unreadable", "adopted row 1"),
        ("budget_line_ambiguous", "adopted row 4"),
        ("budget_line_ambiguous", "adopted row 5"),
        ("budget_type_unrecognized", "adopted row 4"),
        ("budget_year_unreadable", "adopted row 3"),
    ]
    lines = {line.position: line for line in result.budget.lines}
    assert sorted(lines) == [1, 2, 4, 5]
    assert lines[1].target is None and lines[1].actual == Decimal("-45.00")
    assert lines[2].target is None
    assert lines[4].actual is None and lines[5].actual is None
    assert lines[4].actual_status == lines[5].actual_status == "ambiguous"
    assert all("12,34" not in str(issue.to_dict()) for issue in result.issues)


def test_fundraising_counts_each_movement_once_by_payment_date(tmp_path: Path) -> None:
    result = Scenario(tmp_path).facts()
    paypal, wix = result.fundraising  # ordered by source alias
    assert wix.source_alias == "wix" and paypal.source_alias == "paypal"
    assert (wix.gross, wix.fees, wix.refunds, wix.net) == (
        Decimal("50.00"),
        Decimal("1.75"),
        Decimal("0.00"),
        Decimal("48.25"),
    )
    assert wix.payment_count == 1  # the June sale belongs to the prior school year
    assert [(c.category, c.classification, c.count, c.gross) for c in wix.categories] == [
        (None, "unmatched", 1, Decimal("50.00"))
    ]
    # No payout ties the processor balance to the bank: incomplete, never claimed settled.
    assert wix.incomplete_reasons == ("processor_gross_unsettled",)
    # A source with no declared coverage is partial, never an implied zero.
    assert paypal.payment_count == 0 and paypal.incomplete_reasons == ("coverage_partial",)
    flags = {(flag.code, flag.source_alias) for flag in result.coverage_flags}
    assert {("school_coverage_partial", "paypal"), ("calendar_coverage_partial", "paypal")} <= flags
    assert not {
        code for code, alias in flags if alias in {"bank-checking", "wix"} and "partial" in code
    }


def test_fundraising_matches_the_processor_summary_for_a_whole_window(tmp_path: Path) -> None:
    rows = [
        _wix("pi_ex_010", date(2030, 7, 2), "40.00", "Successful", fee="-1.40", net="38.60"),
        _wix(
            "pi_ex_011",
            date(2030, 7, 3),
            "20.00",
            "Partially Refunded",
            fee="-0.80",
            net="14.20",
            refund="5.00",
        ),
        _wix("pi_ex_012", date(2030, 7, 4), "15.00", "Chargeback", fee="", net=""),
    ]
    scenario = Scenario(tmp_path, wix=rows)
    result = scenario.facts()
    _, rec = scenario.reconciled()
    (summary,) = [s for s in rec.processor_summaries if s.source_alias == "wix"]
    (wix,) = [f for f in result.fundraising if f.source_alias == "wix"]
    assert (wix.gross, wix.fees, wix.refunds) == (summary.gross, summary.fees, summary.refunds)
    assert wix.net == Decimal("52.80") and wix.payment_count == summary.primary_count == 2
    # The unresolved chargeback is excluded and named, never counted.
    assert wix.excluded_rows == summary.conflict_count == 1
    assert wix.incomplete_reasons == (
        "processor_view_inconsistent",
        "processor_gross_unsettled",
        "rows_excluded",
    )
    assert ("processor_rows_excluded", 1, "wix") in {
        (i.code, i.count, i.subject) for i in result.issues
    }


def test_partial_bank_coverage_marks_both_views_partial(tmp_path: Path) -> None:
    result = Scenario(tmp_path, bank_coverage='start = "2030-01-01", end = "2030-07-31"').facts()
    assert not result.view("school", "source").complete
    assert not result.view("calendar", "adjusted").complete
    flags = {(flag.code, flag.source_alias) for flag in result.coverage_flags}
    assert ("school_coverage_partial", "bank-checking") in flags
    assert ("calendar_coverage_partial", "bank-checking") in flags
    (status,) = [
        s
        for s in result.coverage
        if s.source_alias == "bank-checking" and s.start == date(2030, 7, 1)
    ]
    assert status.uncovered == ((date(2030, 8, 1), date(2030, 8, 16)),)
    # Totals are still the observed activity, labeled partial, never zero-filled.
    assert result.view("school", "source").net == Decimal("-1.75")


def test_no_bank_capture_is_flagged_absent(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    others = tuple(c for c in capture_set.captures if c.kind != "bank")
    bare = dataclasses.replace(
        ledger,
        source=dataclasses.replace(
            ledger.source,
            transactions=tuple(t for t in ledger.source.transactions if t.source_kind != "bank"),
            allocations=(),
            transfer_allocations=(),
            monthly_cells=(),
            pnl_totals=(),
        ),
        allocations=(),
        monthly_cells=(),
        pnl_totals=(),
    )
    bare = dataclasses.replace(bare, source=dataclasses.replace(bare.source, crosswalk_cells=()))
    result, _ = scenario.build(bare, captures=others)
    assert "bank_coverage_absent" in {flag.code for flag in result.coverage_flags}
    assert not result.view("calendar", "source").complete
    # Without bank coverage no budget actual is observed.
    assert {line.actual_status for line in result.budget.lines} == {
        "coverage_partial",
        "category_unmapped",
    }
    assert all(line.actual is None for line in result.budget.lines)
    # With no bank capture the coverage is unknown: the payment stays a visible finding.
    states = {j.ticket_ref: j.state for j in result.reimbursements.joins}
    assert states[PAID_TICKET] == "unmatched"


# --------------------------------------------------------------------------------------
# Payment joins: exact reference plus corroborating amount and date
# --------------------------------------------------------------------------------------


def _with_bank_row(index: int, row: list[str]) -> list[list[str]]:
    rows = [list(item) for item in BANK_ROWS]
    rows[index] = row
    return rows


CHECK_INDEX = 4
JOIN_CASES = {
    "wrong_amount": (
        [_bank("7/10/2030", CHECK_JULY, "-44.00", "Classroom Supplies", check="2001")],
        "unmatched",
    ),
    "too_late": (
        [_bank("8/23/2030", CHECK_JULY, "-45.00", "Classroom Supplies", check="2001")],
        "unmatched",
    ),
    "before_payment": (
        [_bank("7/7/2030", CHECK_JULY, "-45.00", "Classroom Supplies", check="2001")],
        "unmatched",
    ),
    "no_reference": (
        [_bank("7/10/2030", "Example vendor E", "-45.00", "Classroom Supplies")],
        "unmatched",
    ),
    "short_token_in_description": (
        [_bank("7/10/2030", "Payment 2001", "-45.00", "Classroom Supplies")],
        "unmatched",
    ),
    "last_clearing_day": (
        [_bank("8/22/2030", CHECK_JULY, "-45.00", "Classroom Supplies", check="2001")],
        "matched",
    ),
    "same_day": (
        [_bank("7/8/2030", CHECK_JULY, "-45.00", "Classroom Supplies", check="2001")],
        "matched",
    ),
    "two_candidates": (
        [
            _bank("7/10/2030", CHECK_JULY, "-45.00", "Classroom Supplies", check="2001"),
            _bank("7/11/2030", "Check 2001 copy", "-45.00", "Classroom Supplies", check="2001"),
        ],
        "ambiguous",
    ),
}


@pytest.mark.parametrize("case", sorted(JOIN_CASES))
def test_payment_join_needs_reference_amount_and_date(tmp_path: Path, case: str) -> None:
    replacement, expected = JOIN_CASES[case]
    bank = [list(row) for row in BANK_ROWS]
    bank[CHECK_INDEX : CHECK_INDEX + 1] = [list(row) for row in replacement]
    result = Scenario(tmp_path, bank=bank).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == PAID_TICKET]
    assert join.state == expected
    basis = result.bridge("school_expense_basis")
    assert basis.balanced
    if expected == "matched":
        # The joined item enters by its own date; the bank row leaves only when it falls in
        # the period (the last clearing day is after the as-of date).
        removed = case != "last_clearing_day"
        assert [row.kind for row in basis.rows] == [
            *(["matched_payment_prior_items", "matched_payment_current_items"] if removed else []),
            "joined_item_expense",
        ]
    else:
        # An unjoined payment stays on the bank basis alone: nothing is swapped in.
        assert basis.rows == () and basis.to_amount == basis.from_amount
        assert f"reimbursement_payment_{expected}" in {i.code for i in result.issues}
    if expected == "ambiguous":
        assert len(join.bank_refs) == 2


def test_description_reference_token_joins_and_one_row_serves_one_ticket(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["supplemental"]["events"][0]["reference"] = "EXREF2001"
    _seal(payload["supplemental"]["events"][0])
    payload["tickets"][0]["live"]["confirmations"] = ["Reference EXREF2001; amount $45.00"]
    bank = _with_bank_row(
        CHECK_INDEX, _bank("7/10/2030", "Zelle EXREF2001 sent", "-45.00", "Classroom Supplies")
    )
    result = Scenario(tmp_path, bank=bank, bundle=payload).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == PAID_TICKET]
    assert join.state == "matched" and join.reference == "EXREF2001"
    # The token must stand alone: a longer word that contains it is no reference.
    bank = _with_bank_row(
        CHECK_INDEX, _bank("7/10/2030", "Zelle XEXREF2001 sent", "-45.00", "Classroom Supplies")
    )
    result = Scenario(tmp_path / "other", bank=bank, bundle=payload).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == PAID_TICKET]
    assert join.state == "unmatched"


def test_one_bank_row_claimed_by_two_payments_is_ambiguous(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    (paid,) = [t for t in bundle.tickets if t.ref == PAID_TICKET]
    (event,) = bundle.supplemental.events
    twin_ticket = dataclasses.replace(paid, review_key="legacy:v1:p-009", ref="P-009")
    twin_event = dataclasses.replace(event, ticket_review_key="legacy:v1:p-009")
    doubled = dataclasses.replace(
        bundle,
        tickets=(*bundle.tickets, twin_ticket),
        supplemental=dataclasses.replace(
            bundle.supplemental, events=(*bundle.supplemental.events, twin_event)
        ),
    )
    result = build_from(capture_set, ledger, doubled, scenario.config)
    states = {j.ticket_ref: j.state for j in result.reimbursements.joins}
    assert states[PAID_TICKET] == states["P-009"] == "ambiguous"
    assert result.bridge("school_expense_basis").rows == ()


# --------------------------------------------------------------------------------------
# Fail-closed inputs
# --------------------------------------------------------------------------------------


def test_blocked_adjusted_publication_is_refused(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    ledger = scenario.inputs()[1]
    blocked = dataclasses.replace(
        ledger, conflicts=(AdjustmentIssue("target_revision_mismatch", "error"),)
    )
    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.build(blocked)
    assert caught.value.code == "adjusted_publication_blocked"


def _one_year_later(periods: Any) -> Any:
    """Both periods one year later, so the as-of date precedes their start."""
    school, calendar = periods.school, periods.calendar
    return dataclasses.replace(
        periods,
        school=dataclasses.replace(
            school,
            start=school.start.replace(year=school.start.year + 1),
            end_exclusive=school.end_exclusive.replace(year=school.end_exclusive.year + 1),
        ),
        calendar=dataclasses.replace(
            calendar,
            start=calendar.start.replace(year=calendar.start.year + 1),
            end_exclusive=calendar.end_exclusive.replace(year=calendar.end_exclusive.year + 1),
        ),
    )


FAIL_CASES: dict[str, tuple[Callable[[Any], Any], str]] = {
    "as_of_mismatch": (
        lambda p: reporting_periods(AS_OF + timedelta(days=1), 7),
        "as_of_mismatch",
    ),
    "school_basis": (
        lambda p: dataclasses.replace(p, school=dataclasses.replace(p.school, basis="calendar")),
        "periods_invalid",
    ),
    "calendar_not_january": (
        lambda p: dataclasses.replace(p, calendar=dataclasses.replace(p.school, basis="calendar")),
        "periods_invalid",
    ),
    "short_period": (
        lambda p: dataclasses.replace(
            p, school=dataclasses.replace(p.school, end_exclusive=date(2031, 1, 1))
        ),
        "periods_invalid",
    ),
    "mid_month_start": (
        lambda p: dataclasses.replace(
            p,
            school=dataclasses.replace(
                p.school, start=date(2030, 7, 2), end_exclusive=date(2031, 7, 1)
            ),
        ),
        "periods_invalid",
    ),
    "as_of_before_start": (
        _one_year_later,
        "periods_invalid",
    ),
}


@pytest.mark.parametrize("case", sorted(FAIL_CASES))
def test_inconsistent_periods_fail_closed(tmp_path: Path, case: str) -> None:
    edit, code = FAIL_CASES[case]
    with pytest.raises(FactsError) as caught:
        Scenario(tmp_path).build(periods=edit(reporting_periods(AS_OF, 7)))
    assert caught.value.code == code


def test_ledger_from_another_capture_or_journal_is_refused(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    with pytest.raises(FactsError) as caught:
        scenario.build(captures=())
    assert caught.value.code == "capture_mismatch"
    stale = dataclasses.replace(ledger, journal_sha256="0" * 64)
    with pytest.raises(FactsError) as caught:
        build_from(capture_set, stale, bundle, scenario.config)
    assert caught.value.code == "journal_mismatch"


def _replace_processor(ledger: AdjustedLedger, **fields: Any) -> AdjustedLedger:
    transactions = tuple(
        dataclasses.replace(t, **fields) if t.source_kind == "wix" else t
        for t in ledger.source.transactions
    )
    return dataclasses.replace(
        ledger, source=dataclasses.replace(ledger.source, transactions=transactions)
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"payment_date": None}, "processor_row_undated"),
        ({"record_key": "v1:wix:" + "0" * 64 + ":0"}, "classification_missing"),
    ],
)
def test_broken_processor_invariants_fail_closed(
    tmp_path: Path, change: dict[str, Any], code: str
) -> None:
    scenario = Scenario(tmp_path)
    with pytest.raises(FactsError) as caught:
        scenario.build(_replace_processor(scenario.inputs()[1], **change))
    assert caught.value.code == code
    text = str(caught.value)
    assert "50.00" not in text and "48.25" not in text
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_unpriced_and_undated_payments_are_counted(tmp_path: Path) -> None:
    payload = _bundle_payload()
    paid_prior = payload["tickets"][3]
    paid_prior["live"]["payment_status"] = "PAID"  # a current-process payment, undated
    paid_prior["live"]["payment_date"] = ""
    paid_prior["items"][0]["source_amount"] = ""
    paid_prior["source"]["stated_total"] = ""
    paid_prior["source"]["mapped_total"] = ""
    payload["source_summary"]["mapped_total"] = "69.00"
    result = Scenario(tmp_path, bundle=payload).facts()
    codes = {issue.code: issue.count for issue in result.issues}
    assert codes["reimbursement_payment_undated"] == 1
    assert codes["reimbursement_item_unpriced"] == 1
    assert codes["reimbursement_payment_no_reference"] == 1
    (item,) = [i for i in result.reimbursements.items if i.ticket_ref == "P-002"]
    assert (item.amount, item.payment_bucket) == (None, "undated")
    (group,) = [t for t in result.reimbursements.totals if t.payment_bucket == "undated"]
    assert (group.count, group.unpriced, group.amount) == (1, 1, Decimal("0.00"))
    assert result.bridge("school_payment_timing").balanced


# --------------------------------------------------------------------------------------
# Processor fee and refund rows, declined lines, residuals and spring windows
# --------------------------------------------------------------------------------------


def _paypal(
    txn_id: str, kind: str, gross: str, fee: str, net: str, reference: str = ""
) -> list[str]:
    row = ["07/02/2030", "10:15:00", "PST", "Example Buyer", kind, "Completed", "USD"]
    row += [gross, fee, net, txn_id, reference, "", "", ""]
    assert len(row) == len(PAYPAL_HEADER)
    return row


def test_processor_fee_and_refund_rows_count_once(tmp_path: Path) -> None:
    rows = [
        _paypal("TXN-EX-1", "Website Payment", "60.00", "-2.39", "57.61"),
        _paypal("TXN-EX-2", "Partner Fee", "-0.50", "", "-0.50", reference="TXN-EX-1"),
        _paypal("TXN-EX-4", "Payment Refund", "-10.00", "0.30", "-9.70", reference="TXN-EX-1"),
    ]
    scenario = Scenario(tmp_path, paypal=rows)
    result = scenario.facts()
    _, rec = scenario.reconciled()
    (summary,) = [s for s in rec.processor_summaries if s.source_alias == "paypal"]
    (paypal,) = [f for f in result.fundraising if f.source_alias == "paypal"]
    assert (paypal.gross, paypal.fees, paypal.refunds) == (
        summary.gross,
        summary.fees,
        summary.refunds,
    )
    assert (paypal.gross, paypal.fees, paypal.refunds, paypal.net) == (
        Decimal("60.00"),
        Decimal("2.89"),
        Decimal("10.00"),
        Decimal("47.11"),
    )
    assert (paypal.payment_count, paypal.fee_rows, paypal.refund_rows) == (1, 1, 1)
    # Processor activity never reaches the bank-basis views.
    assert result.view("school", "source") == Scenario(tmp_path / "bare").facts().view(
        "school", "source"
    )


def test_declined_line_on_a_paid_ticket_is_not_paid(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["tickets"][3] = _ticket(
        4,
        "P-002",
        "legacy",
        "2030-03-02",
        [
            _item("p-002:line:1", 1, "2030-03-01", "15.00", "A", "Classroom Supplies"),
            _item("p-002:line:2", 2, "2030-03-01", "4.00", "D", "Classroom Supplies"),
        ],
        status="D",
        decision="DECLINED",
        workflow="SETTLED",
        payment_status="PAID_PRIOR",
        payment_date="2030-03-05",
        confirmations=["Fictional confirmation"],
    )
    result = Scenario(tmp_path, bundle=payload).facts()
    by_key = {item.item_key: item for item in result.reimbursements.items}
    assert by_key["p-002:line:1"].payment_bucket == "prior"
    assert by_key["p-002:line:2"].payment_bucket == "unpaid"
    assert result.reimbursements.paid("prior") == Decimal("15.00")
    assert result.reimbursements.expense("prior", "D") == Decimal("4.00")
    # The settled ticket's unpaid declined line is no open obligation.
    assert result.reimbursements.open_amount("prior") == Decimal("30.00")


def test_unexplained_difference_stays_in_the_residual(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    target = scenario.txn(VENDOR_AS_OF).record_key
    tampered = dataclasses.replace(
        ledger,
        allocations=tuple(
            dataclasses.replace(item, amount=item.amount - Decimal("1.00"))
            if item.record_key == target
            else item
            for item in ledger.allocations
        ),
    )
    result = build_from(capture_set, tampered, bundle, scenario.config)
    bridge = result.bridge("school_adjustments")
    # No journal entry explains the change, so no row claims it: it is never forced to zero.
    assert bridge.rows == () and bridge.residual == Decimal("-1.00") and not bridge.balanced
    assert result.to_dict()["bridges"][2]["balanced"] is False


def test_spring_as_of_bridges_the_school_year_to_a_new_calendar_year(tmp_path: Path) -> None:
    as_of = date(2031, 1, 10)
    result = Scenario(tmp_path).facts(as_of)
    assert result.periods == reporting_periods(as_of, 7)
    assert result.view("calendar", "adjusted").net == Decimal("0.00")
    window = result.bridge("calendar_to_school")
    # July-December 2030 is inside the school year but outside calendar 2031; the Aug 16 row
    # is now before the as-of date.
    assert _rows(result, "calendar_to_school") == [("only_in_target_period", Decimal("-8.75"))]
    assert (window.from_amount, window.to_amount) == (Decimal("0.00"), Decimal("-8.75"))
    assert window.balanced
    # Bank coverage ends in August 2030: both views are partial, never zero-filled.
    assert not result.view("school", "source").complete
    assert result.reimbursements.expense("later") == Decimal("0.00")
    assert result.reimbursements.expense("current", "Q") == Decimal("9.00")


def test_informational_line_on_a_joined_ticket_is_not_an_expense(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["tickets"][0]["items"].append(
        _item("new-01:line:3", 3, "2030-07-02", "0.00", "-", "Classroom Supplies")
    )
    result = Scenario(tmp_path, bundle=payload).facts()
    (joined,) = [
        r for r in result.bridge("school_expense_basis").rows if r.kind == "joined_item_expense"
    ]
    assert joined.item_keys == ("new-01:line:2",) and joined.amount == Decimal("-20.00")


def test_category_mapping_attributes_fundraising_gross(tmp_path: Path) -> None:
    result = Scenario(tmp_path, mapping=[["shirt", "Spirit Wear"]]).facts()
    (wix,) = [f for f in result.fundraising if f.source_alias == "wix"]
    assert [(c.category, c.classification, c.count, c.gross) for c in wix.categories] == [
        ("Spirit Wear", "matched", 1, Decimal("50.00"))
    ]


def test_recategorized_transfer_enters_the_adjustment_bridge(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    transfer = _adjustment(
        "category_override",
        scenario.txn("Transfer to savings"),
        prior_value=reconcile.INTERNAL_TRANSFER_CATEGORY,
        replacement_value="Field Trips",
    )
    scenario.record([transfer])
    result = scenario.facts()
    # The source view excludes the exact transfer category; the adjusted view now counts it.
    assert _rows(result, "school_adjustments") == [("adjustment", Decimal("-500.00"))]
    assert result.bridge("school_adjustments").balanced
    assert result.view("school", "adjusted").net == Decimal("-501.75")


# --------------------------------------------------------------------------------------
# Obligations, carryovers, joins and diagnostics
# --------------------------------------------------------------------------------------


def test_paid_but_unsettled_ticket_is_not_an_open_obligation(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["tickets"][3]["live"]["workflow_state"] = "ACTIVE"  # P-002: paid, not settled
    payload["tickets"][3]["archive_note"] = ""
    result = Scenario(tmp_path, bundle=payload).facts()
    reimbursements = result.reimbursements
    (entry,) = [e for e in reimbursements.queue if e.ticket_ref == "P-002"]
    # Still a prior-year request in the queue (membership), but nothing is owed.
    assert (entry.carryover, entry.carryover_basis, entry.pay_now) == (
        True,
        "expense_date",
        Decimal("0.00"),
    )
    # Only the unpaid approved P-001 line is a prior-year obligation, as pay-now says.
    assert reimbursements.open_amount("prior", "A") == Decimal("30.00")
    assert reimbursements.outstanding == Decimal("35.00")
    assert reimbursements.outstanding == sum(
        (reimbursements.open_amount(bucket, "A") for bucket in EXPENSE_BUCKETS), Decimal("0.00")
    )


def test_one_obligation_rule_drives_carryover_earliest_date_and_undated_count(
    tmp_path: Path,
) -> None:
    payload = _bundle_payload()
    # P-001, submitted 2029-05-20: declined and informational lines are never obligations.
    payload["tickets"][1] = _ticket(
        2,
        "P-001",
        "legacy",
        "2029-05-20",
        [
            _item("p-001:line:1", 1, "2029-01-05", "4.00", "D", "Field Trips"),
            _item("p-001:line:2", 2, "", "2.00", "-", "Field Trips"),
            _item("p-001:line:3", 3, "2030-07-10", "30.00", "A", "Field Trips"),
            _item("p-001:line:4", 4, "", "6.00", "Q", "Field Trips"),
        ],
        status="Q",
    )
    result = Scenario(tmp_path, bundle=payload).facts()
    (entry,) = [e for e in result.reimbursements.queue if e.ticket_ref == "P-001"]
    # Obligations are the A and Q lines only: the same set for all three fields.
    assert (entry.carryover, entry.carryover_basis) == (True, "submitted")
    assert entry.earliest_expense_date == date(2030, 7, 10)
    assert entry.undated_items == 1


CARRYOVER_CASES: dict[str, tuple[str, list[tuple[str, str, str]], str, bool, str | None]] = {
    # name: (submitted, [(expense date, amount, status)], review status, carryover, basis)
    "only_non_obligations_undated": (
        "2029-05-20",
        [("", "4.00", "D"), ("", "2.00", "-"), ("2030-07-10", "30.00", "A")],
        "D",
        False,
        None,
    ),
    "obligation_dated_after_the_period": (
        "2029-05-20",
        [("2030-08-20", "30.00", "A")],
        "A",
        False,
        None,
    ),
    "undated_obligation_submitted_after_as_of": (
        "2030-08-20",
        [("", "30.00", "Q")],
        "Q",
        False,
        None,
    ),
    "undated_obligation_submitted_last_year": (
        "2029-05-20",
        [("", "30.00", "Q")],
        "Q",
        True,
        "submitted",
    ),
}


@pytest.mark.parametrize("case", sorted(CARRYOVER_CASES))
def test_carryover_needs_a_prior_year_obligation(tmp_path: Path, case: str) -> None:
    submitted, lines, status, carryover, basis = CARRYOVER_CASES[case]
    payload = _bundle_payload()
    payload["tickets"][1] = _ticket(  # P-001, an outstanding legacy request
        2,
        "P-001",
        "legacy",
        submitted,
        [
            _item(f"p-001:line:{index}", index, day, amount, line_status, "Field Trips")
            for index, (day, amount, line_status) in enumerate(lines, 1)
        ],
        status=status,
    )
    result = Scenario(tmp_path, bundle=payload).facts()
    (entry,) = [e for e in result.reimbursements.queue if e.ticket_ref == "P-001"]
    assert (entry.carryover, entry.carryover_basis) == (carryover, basis)


def test_undated_request_submitted_last_year_is_a_carryover(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["tickets"][1]["items"][0]["source_date"] = ""  # P-001, submitted 2029-05-20
    payload["tickets"][4]["items"] = [  # NEW-03: only DECLINED lines are prior or undated
        _item("new-03:line:1", 1, "2030-06-01", "10.00", "D", "Classroom Supplies"),
        _item("new-03:line:2", 2, "2030-07-05", "5.00", "A", "Classroom Supplies"),
        _item("new-03:line:3", 3, "", "1.00", "D", "Classroom Supplies"),
    ]
    payload["tickets"][4]["source"]["stated_total"] = "16.00"
    payload["tickets"][4]["source"]["mapped_total"] = "16.00"
    result = Scenario(tmp_path, bundle=payload).facts()
    queue = {entry.ticket_ref: entry for entry in result.reimbursements.queue}
    old = queue["P-001"]
    assert (old.carryover, old.carryover_basis, old.undated_items) == (True, "submitted", 1)
    assert old.earliest_expense_date is None
    # A declined line is no obligation, so it never makes a request a carryover.
    partly = queue["NEW-03"]
    assert (partly.carryover, partly.carryover_basis) == (False, None)
    # The undated declined line is no obligation: same item set as the flag.
    assert partly.undated_items == 0
    # The earliest date uses the same obligation items as the flag.
    assert partly.earliest_expense_date == date(2030, 7, 5)
    # Undated on a current-year request is not a carryover; the item stays undated.
    assert queue["NEW-02"].carryover is False
    (item,) = [i for i in result.reimbursements.items if i.item_key == "p-001:line:1"]
    assert item.expense_bucket == "undated"


def test_undated_and_later_items_of_a_joined_payment_stay_visible(tmp_path: Path) -> None:
    payload = _bundle_payload()
    paid = payload["tickets"][0]
    paid["items"] += [
        _item("new-01:line:3", 3, "", "5.00", "A", "Classroom Supplies"),
        _item("new-01:line:4", 4, "2030-08-20", "3.00", "A", "Classroom Supplies"),
    ]
    paid["source"]["stated_total"] = paid["source"]["mapped_total"] = "53.00"
    paid["live"]["confirmations"] = [f"Reference {PAYMENT_REFERENCE}; amount $53.00"]
    event = payload["supplemental"]["events"][0]
    event["amount"] = "53.00"
    _seal(event)
    bank = _with_bank_row(
        CHECK_INDEX, _bank("7/10/2030", CHECK_JULY, "-53.00", "Classroom Supplies", check="2001")
    )
    result = Scenario(tmp_path, bank=bank, bundle=payload).facts()
    basis = result.bridge("school_expense_basis")
    assert [(row.kind, row.amount, row.item_keys) for row in basis.rows] == [
        ("matched_payment_prior_items", Decimal("25.00"), ("new-01:line:1",)),
        ("matched_payment_current_items", Decimal("20.00"), ("new-01:line:2",)),
        ("matched_payment_later_items", Decimal("3.00"), ("new-01:line:4",)),
        ("matched_payment_undated_items", Decimal("5.00"), ("new-01:line:3",)),
        ("joined_item_expense", Decimal("-20.00"), ("new-01:line:2",)),
    ]
    assert basis.balanced


def test_bank_payment_not_explained_by_items_is_a_remainder_row(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    check = scenario.txn(CHECK_JULY).record_key
    # An adjusted bank amount larger than the paid items: the extra is named, not hidden.
    larger = dataclasses.replace(
        ledger,
        allocations=tuple(
            dataclasses.replace(item, amount=Decimal("-46.00"))
            if item.record_key == check
            else item
            for item in ledger.allocations
        ),
    )
    result = build_from(capture_set, larger, bundle, scenario.config)
    rows = {row.kind: row.amount for row in result.bridge("school_expense_basis").rows}
    assert rows["matched_payment_remainder"] == Decimal("1.00")
    assert result.bridge("school_expense_basis").balanced


def test_payment_timing_names_prior_and_later_payments(tmp_path: Path) -> None:
    payload = _bundle_payload()
    p002 = payload["tickets"][3]  # paid before the item date
    p002["items"][0]["source_date"] = "2030-07-02"
    p002["live"]["payment_date"] = "2030-06-25"
    new03 = payload["tickets"][4]  # approved line paid after the as-of date
    new03["live"] = {
        "workflow_state": "SETTLED",
        "decision": "DECLINED",
        "payment_status": "PAID",
        "payment_date": "2030-08-20",
        "confirmations": ["Fictional confirmation"],
    }
    new03["archive_note"] = "Fictional archive note."
    result = Scenario(tmp_path, bundle=payload).facts()
    timing = result.bridge("school_payment_timing")
    assert [(row.kind, row.amount, row.item_keys) for row in timing.rows] == [
        ("paid_in_period_expense_prior", Decimal("25.00"), ("new-01:line:1",)),
        ("approved_in_period_payment_prior", Decimal("-15.00"), ("p-002:line:1",)),
        ("approved_in_period_payment_later", Decimal("-5.00"), ("new-03:line:2",)),
    ]
    assert (timing.from_amount, timing.to_amount) == (Decimal("40.00"), Decimal("45.00"))
    assert timing.balanced
    codes = {issue.code: issue.count for issue in result.issues}
    # A later payment with no recorded reference IS a finding.
    assert codes["reimbursement_payment_no_reference"] == 1


def test_current_payment_without_a_reference_is_a_finding(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["tickets"][3]["live"]["payment_status"] = "PAID"
    payload["tickets"][3]["live"]["payment_date"] = "2030-07-20"
    current = Scenario(tmp_path, bundle=payload).facts()
    codes = {issue.code: issue.count for issue in current.issues}
    assert codes["reimbursement_payment_no_reference"] == 1
    # The same ticket paid before the period is an expected state, not a finding.
    payload["tickets"][3]["live"]["payment_date"] = "2030-03-05"
    prior = Scenario(tmp_path / "prior", bundle=payload).facts()
    assert "reimbursement_payment_no_reference" not in {issue.code for issue in prior.issues}
    (join,) = [j for j in prior.reimbursements.joins if j.ticket_ref == "P-002"]
    assert join.state == "no_reference"
    # A legacy PAID_PRIOR ticket has no reference by construction, even when paid in period.
    payload["tickets"][3]["live"]["payment_status"] = "PAID_PRIOR"
    payload["tickets"][3]["live"]["payment_date"] = "2030-07-20"
    legacy = Scenario(tmp_path / "legacy", bundle=payload).facts()
    assert "reimbursement_payment_no_reference" not in {issue.code for issue in legacy.issues}


CHECK_CELL_CASES = {
    "token_in_check_cell": ("#2001", "matched"),
    "longer_check_number": ("20012", "unmatched"),
    "check_number_prefix": ("12001", "unmatched"),
}


@pytest.mark.parametrize("case", sorted(CHECK_CELL_CASES))
def test_check_number_matches_a_whole_token(tmp_path: Path, case: str) -> None:
    cell, expected = CHECK_CELL_CASES[case]
    bank = _with_bank_row(
        CHECK_INDEX, _bank("7/10/2030", "Example check", "-45.00", "Classroom Supplies", check=cell)
    )
    result = Scenario(tmp_path, bank=bank).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == PAID_TICKET]
    assert join.state == expected


def test_short_reference_never_matches_a_check_number(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["supplemental"]["events"][0]["reference"] = "12"
    _seal(payload["supplemental"]["events"][0])
    payload["tickets"][0]["live"]["confirmations"] = ["Reference 12; amount $45.00"]
    bank = _with_bank_row(
        CHECK_INDEX, _bank("7/10/2030", "Example check", "-45.00", "Classroom Supplies", check="12")
    )
    result = Scenario(tmp_path, bank=bank, bundle=payload).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == PAID_TICKET]
    assert join.state == "unmatched"


def test_journal_diagnostics_travel_into_the_facts(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    first = _adjustment(
        "additive",
        effective=date(2030, 8, 1),
        category="Donations",
        signed_amount=Decimal("25.00"),
        evidence=("example-cash-count-2030-08",),
    )
    withdrawn = _adjustment("reversal", effective=date(2030, 8, 2), supersedes=first.adjustment_id)
    future = _adjustment(
        "additive",
        effective=date(2030, 9, 1),
        category="Donations",
        signed_amount=Decimal("10.00"),
        evidence=("example-cash-count-2030-09",),
    )
    scenario.record([first, withdrawn, future])
    capture_set, ledger, bundle = scenario.inputs()
    result = build_from(capture_set, ledger, bundle, scenario.config)
    assert result.applied_adjustments == (withdrawn.adjustment_id,)
    assert result.superseded_adjustments == (first.adjustment_id,) == ledger.superseded
    assert result.pending_adjustments == (future.adjustment_id,) == ledger.pending
    warned = dataclasses.replace(
        ledger,
        warnings=(AdjustmentIssue("duplicate_adjustment_row", "warning", first.adjustment_id, 9),),
    )
    result = build_from(capture_set, warned, bundle, scenario.config)
    assert result.adjustment_warnings == warned.warnings
    assert result.to_dict()["adjustment_warnings"][0]["code"] == "duplicate_adjustment_row"


def test_mismatched_pnl_control_status_and_findings_flow_into_facts(tmp_path: Path) -> None:
    pnl = [list(row) for row in PNL_VALUES]
    pnl[2][2] = "90.00"  # published Donations Jan 2030 differs from the bank rows
    scenario = Scenario(tmp_path, pnl=pnl)
    capture_set, ledger, bundle = scenario.inputs()
    result = build_from(capture_set, ledger, bundle, scenario.config)
    assert result.pnl_control_status == "mismatched"
    kinds = {d.discrepancy_id: d.kind for d in ledger.source.unresolved}
    assert "pnl_control_mismatch" in {kinds[i] for i in result.discrepancy_ids}
    assert set(result.discrepancy_ids) == set(kinds)


def test_crosswalk_must_be_the_one_the_reconciliation_applied(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    assert scenario.config.main_reports is not None
    crosswalk = scenario.config.main_reports.crosswalk
    assert crosswalk is not None
    split = dataclasses.replace(
        crosswalk,
        entries=tuple(
            dataclasses.replace(
                entry,
                targets=(
                    CrosswalkTarget("Classroom Supplies", Decimal("0.5")),
                    CrosswalkTarget("Shared Supplies", Decimal("0.5")),
                ),
            )
            if entry.source_category == "Classroom Supplies"
            else entry
            for entry in crosswalk.entries
        ),
    )
    for changed in (None, dataclasses.replace(crosswalk, version=4), split):
        with pytest.raises(FactsError) as caught:
            scenario.build(crosswalk=changed)
        assert caught.value.code == "crosswalk_mismatch"
    # Reconciled cells that do not follow from the recorded crosswalk are refused too.
    _, ledger, _ = scenario.inputs()
    tampered = dataclasses.replace(
        ledger,
        source=dataclasses.replace(
            ledger.source, crosswalk_cells=ledger.source.crosswalk_cells[1:]
        ),
    )
    with pytest.raises(FactsError) as caught:
        scenario.build(tampered)
    assert caught.value.code == "crosswalk_mismatch"
    # The production caller reloads the crosswalk from config: a changed config is refused.
    capture_set, ledger, bundle = scenario.inputs()
    reloaded = _config(tmp_path / "reloaded", crosswalk="")
    with pytest.raises(FactsError) as caught:
        build_from(capture_set, ledger, bundle, reloaded)
    assert caught.value.code == "crosswalk_mismatch"


def test_budget_actuals_are_unknown_without_a_crosswalk_or_coverage(tmp_path: Path) -> None:
    missing = Scenario(tmp_path / "missing", crosswalk="").facts()
    assert {(line.actual, line.actual_status) for line in missing.budget.lines} == {
        (None, "crosswalk_missing")
    }
    assert ("budget_actual_unknown", 5, "crosswalk_missing") in {
        (i.code, i.count, i.subject) for i in missing.issues
    }
    partial = Scenario(
        tmp_path / "partial", bank_coverage='start = "2030-01-01", end = "2030-07-31"'
    ).facts()
    statuses = {line.category: (line.actual, line.actual_status) for line in partial.budget.lines}
    assert statuses["Assemblies"] == (None, "coverage_partial")  # never an invented 0.00
    assert statuses["Classroom Supplies"] == (None, "coverage_partial")
    assert statuses["Library Books"] == (None, "category_unmapped")
    # The crosswalked totals themselves stay visible beside the unknown line actuals.
    assert dict(partial.budget.mapped_actuals)["Classroom Supplies"] == Decimal("-45.00")


def test_primary_refund_is_a_magnitude_whatever_its_sign(tmp_path: Path) -> None:
    rows = [
        _wix(
            "pi_ex_020",
            date(2030, 7, 3),
            "20.00",
            "Partially Refunded",
            fee="-0.80",
            net="14.20",
            refund="-5.00",
        )
    ]
    result = Scenario(tmp_path, wix=rows).facts()
    (wix,) = [f for f in result.fundraising if f.source_alias == "wix"]
    assert (wix.gross, wix.fees, wix.refunds, wix.net) == (
        Decimal("20.00"),
        Decimal("0.80"),
        Decimal("5.00"),
        Decimal("14.20"),
    )


def test_fundraising_categories_are_ordered_and_attributed(tmp_path: Path) -> None:
    rows = [
        _wix("pi_ex_030", date(2030, 7, 2), "30.00", "Successful", fee="-1.00", net="29.00"),
        _wix(
            "pi_ex_031",
            date(2030, 7, 3),
            "12.00",
            "Successful",
            fee="-0.50",
            net="11.50",
            product="Raffle Ticket",
        ),
        _wix(
            "pi_ex_032",
            date(2030, 7, 4),
            "8.00",
            "Successful",
            fee="-0.30",
            net="7.70",
            product="Bake Sale",
        ),
    ]
    mapping = [["shirt", "Spirit Wear"], ["raffle", "Raffle"]]
    result = Scenario(tmp_path, wix=rows, mapping=mapping).facts()
    (wix,) = [f for f in result.fundraising if f.source_alias == "wix"]
    assert [(c.category, c.classification, c.count, c.gross) for c in wix.categories] == [
        ("Raffle", "matched", 1, Decimal("12.00")),
        ("Spirit Wear", "matched", 1, Decimal("30.00")),
        (None, "unmatched", 1, Decimal("8.00")),
    ]


HOSTILE_FORMULA = '=HYPERLINK("http://example.invalid")'
HOSTILE_MARKUP = "<script>alert(1)</script>"


def test_hostile_labels_pass_through_verbatim(tmp_path: Path) -> None:
    budget = [
        *BUDGET_ROWS,
        _budget_row("2031", "expense", "proposed", "10", HOSTILE_FORMULA),
        _budget_row("2031", "expense", "proposed", "10", HOSTILE_MARKUP),
    ]
    payload = _bundle_payload()
    payload["tickets"][2]["items"][1]["canonical_category"] = HOSTILE_MARKUP
    payload["tickets"][2]["source"]["categories"] = ["Classroom Supplies", HOSTILE_MARKUP]
    result = Scenario(tmp_path, budget=budget, bundle=payload).facts()
    lines = {line.category: line for line in result.budget.lines}
    # Facts carry source text as data, unchanged: escaping belongs to rendering.
    assert lines[HOSTILE_FORMULA].actual_status == "category_unmapped"
    assert lines[HOSTILE_MARKUP].actual is None
    (item,) = [i for i in result.reimbursements.items if i.item_key == "new-02:line:2"]
    assert item.category == HOSTILE_MARKUP
    payload_json = json.loads(canonical_json_bytes(result.to_dict()))
    categories = {line["category"] for line in payload_json["budget"]["lines"]}
    assert {HOSTILE_FORMULA, HOSTILE_MARKUP} <= categories


def test_unknown_payment_status_and_undated_bank_rows_fail_closed(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    _, ledger, bundle = scenario.inputs()
    renamed = dataclasses.replace(
        bundle,
        tickets=tuple(
            dataclasses.replace(t, live=dataclasses.replace(t.live, payment_status="REFUNDED"))
            if t.ref == "P-001"
            else t
            for t in bundle.tickets
        ),
    )
    with pytest.raises(FactsError) as caught:
        scenario.build(bundle=renamed)
    assert caught.value.code == "payment_status_unrecognized"
    undated = dataclasses.replace(
        ledger,
        source=dataclasses.replace(
            ledger.source,
            transactions=tuple(
                dataclasses.replace(t, posting_date=None) if t.description == CHECK_JULY else t
                for t in ledger.source.transactions
            ),
        ),
    )
    with pytest.raises(FactsError) as caught:
        scenario.build(undated)
    assert caught.value.code == "bank_row_undated"


# --------------------------------------------------------------------------------------
# Payload shape, payment findings, windows and configuration
# --------------------------------------------------------------------------------------

SOURCE_REF_KEYS = {
    "source_alias",
    "snapshot_sha256",
    "tab_id",
    "row_number",
    "record_key",
    "revision_hash",
}


def test_report_facts_payload_pins_every_key_and_shape(tmp_path: Path) -> None:
    scenario, _, _ = _adjusted_scenario(tmp_path)
    capture_set, ledger, bundle = scenario.inputs()
    warned = dataclasses.replace(
        ledger, warnings=(AdjustmentIssue("duplicate_adjustment_row", "warning", None, 9),)
    )
    result = build_from(capture_set, warned, bundle, scenario.config)
    payload = json.loads(canonical_json_bytes(result.to_dict()))
    assert set(payload) == {
        "schema_version",
        "as_of",
        "periods",
        "journal_sha256",
        "applied_adjustments",
        "pnl_views",
        "bridges",
        "reimbursements",
        "budget",
        "fundraising",
        "coverage",
        "coverage_flags",
        "issues",
        "pnl_control_status",
        "discrepancy_ids",
        "pending_adjustments",
        "superseded_adjustments",
        "adjustment_warnings",
    }
    assert payload["schema_version"] == 1 and payload["as_of"] == "2030-08-15"
    assert payload["journal_sha256"] == ledger.journal_sha256
    assert payload["pnl_control_status"] == "matched"
    assert payload["discrepancy_ids"] == [d.discrepancy_id for d in ledger.source.unresolved]
    assert payload["applied_adjustments"] == list(ledger.applied)
    assert payload["pending_adjustments"] == [] and payload["superseded_adjustments"] == []
    assert payload["adjustment_warnings"] == [
        {
            "code": "duplicate_adjustment_row",
            "severity": "warning",
            "adjustment_id": None,
            "row_number": 9,
            "field": None,
        }
    ]

    assert set(payload["periods"]) == {"school", "calendar"}
    assert payload["periods"]["school"] == {
        "basis": "school",
        "label": "School year 2030–31",
        "year_label": 2031,
        "start": "2030-07-01",
        "end_exclusive": "2031-07-01",
        "end_inclusive": "2031-06-30",
        "as_of": "2030-08-15",
        "clip_end": "2030-08-16",
    }

    view = payload["pnl_views"][0]
    assert [(v["basis"], v["view"]) for v in payload["pnl_views"]] == [
        ("school", "source"),
        ("school", "adjusted"),
        ("calendar", "source"),
        ("calendar", "adjusted"),
    ]
    assert set(view) == {"basis", "view", "cells", "months", "income", "expense", "net", "complete"}
    assert set(view["cells"][0]) == {
        "category",
        "month",
        "net",
        "inflow",
        "outflow",
        "classification",
        "allocation_count",
        "contributors",
    }
    assert set(view["cells"][0]["contributors"][0]) == SOURCE_REF_KEYS
    assert set(view["months"][0]) == {"month", "income", "expense", "net"}
    assert view["complete"] is True and view["net"] == "-1.75"

    bridge = payload["bridges"][0]
    assert set(bridge) == {
        "name",
        "from_label",
        "from_amount",
        "to_label",
        "to_amount",
        "rows",
        "residual",
        "balanced",
    }
    assert set(bridge["rows"][0]) == {
        "kind",
        "amount",
        "explanation",
        "refs",
        "adjustment_ids",
        "item_keys",
    }
    basis = next(b for b in payload["bridges"] if b["name"] == "school_expense_basis")
    assert [row["item_keys"] for row in basis["rows"]] == [
        ["new-01:line:1"],
        ["new-01:line:2"],
        ["new-01:line:2"],
    ]
    assert basis["residual"] == "0.00" and basis["balanced"] is True

    reimbursements = payload["reimbursements"]
    assert set(reimbursements) == {
        "items",
        "totals",
        "queue",
        "outstanding",
        "joins",
        "cutoff_date",
        "first_received",
        "last_received",
        "bundle_as_of",
    }
    assert reimbursements["bundle_as_of"] == "2030-08-15"
    assert reimbursements["cutoff_date"] == "2030-06-01"
    assert reimbursements["outstanding"] == "35.00"
    assert set(reimbursements["items"][0]) == {
        "review_key",
        "ticket_ref",
        "origin",
        "item_key",
        "category",
        "status",
        "amount",
        "expense_date",
        "expense_bucket",
        "received",
        "payment_status",
        "payment_date",
        "payment_bucket",
        "open",
    }
    assert set(reimbursements["totals"][0]) == {
        "expense_bucket",
        "payment_bucket",
        "status",
        "open",
        "count",
        "amount",
        "unpriced",
    }
    assert set(reimbursements["queue"][0]) == {
        "review_key",
        "ticket_ref",
        "origin",
        "submitted",
        "pay_now",
        "earliest_expense_date",
        "carryover",
        "carryover_basis",
        "undated_items",
    }
    assert [
        (q["ticket_ref"], q["carryover"], q["carryover_basis"]) for q in reimbursements["queue"]
    ] == [
        ("P-001", True, "expense_date"),
        ("NEW-02", False, None),
        ("NEW-03", False, None),
        ("NEW-04", False, None),
    ]
    joins = {j["ticket_ref"]: j for j in reimbursements["joins"]}
    assert set(joins[PAID_TICKET]) == {
        "review_key",
        "ticket_ref",
        "state",
        "payment_date",
        "reference",
        "amount",
        "bank_refs",
    }
    assert joins[PAID_TICKET]["payment_date"] == "2030-07-08"
    assert joins[PAID_TICKET]["amount"] == "45.00"
    (bank_ref,) = joins[PAID_TICKET]["bank_refs"]
    assert set(bank_ref) == SOURCE_REF_KEYS
    assert bank_ref["record_key"] == scenario.txn(CHECK_JULY).record_key
    assert joins["P-002"]["bank_refs"] == [] and joins["P-002"]["state"] == "no_reference"

    budget = payload["budget"]
    assert set(budget) == {
        "fiscal_year",
        "crosswalk_version",
        "lines",
        "mapped_actuals",
        "unmapped",
        "unbudgeted",
        "other_year_rows",
    }
    assert budget["unbudgeted"] == [["Fees and Charges", "-1.75"]]
    assert budget["unmapped"] == [["Donations", "25.00"]]
    assert budget["other_year_rows"] == 1
    assert set(budget["lines"][0]) == {
        "position",
        "fiscal_year",
        "line_type",
        "category",
        "target",
        "actual",
        "actual_status",
    }
    assert [(line["actual"], line["actual_status"]) for line in budget["lines"]] == [
        ("-45.00", "observed"),
        ("-45.00", "observed"),
        ("50.00", "observed"),
        ("0.00", "observed"),
        (None, "category_unmapped"),
    ]

    paypal, wix = payload["fundraising"]
    assert set(wix) == {
        "source_alias",
        "gross",
        "fees",
        "refunds",
        "net",
        "payment_count",
        "fee_rows",
        "refund_rows",
        "excluded_rows",
        "categories",
        "complete",
        "incomplete_reasons",
    }
    assert set(wix["categories"][0]) == {"category", "classification", "count", "gross"}
    assert (wix["complete"], wix["incomplete_reasons"]) == (False, ["processor_gross_unsettled"])
    assert (paypal["complete"], paypal["categories"]) == (False, [])

    assert set(payload["coverage"][0]) == {
        "source_alias",
        "start",
        "end_exclusive",
        "complete",
        "uncovered",
        "observed_first",
        "observed_last",
    }
    assert set(payload["coverage_flags"][0]) == {"code", "source_alias", "count"}
    assert set(payload["issues"][0]) == {"code", "count", "subject"}


def test_payment_findings_on_prior_paid_tickets_stay_visible_with_exact_counts(
    tmp_path: Path,
) -> None:
    payload = _bundle_payload()
    # Three prior-period recorded payments: two match no bank row, one matches two rows.
    _record_payment(payload, payload["tickets"][3], "2030-03-05", "EXREF0305", "a")
    extra = [
        _ticket(
            7,
            "P-003",
            "legacy",
            "2030-03-30",
            [_item("p-003:line:1", 1, "2030-03-29", "12.00", "A", "Field Trips")],
            status="A",
        ),
        _ticket(
            8,
            "P-004",
            "legacy",
            "2030-04-30",
            [_item("p-004:line:1", 1, "2030-04-29", "7.00", "A", "Field Trips")],
            status="A",
        ),
    ]
    payload["tickets"] += extra
    _record_payment(payload, extra[0], "2030-04-01", "EXREF0401", "b")
    _record_payment(payload, extra[1], "2030-05-01", "EXREF0501", "c")
    bank = [
        *BANK_ROWS,
        _bank("5/2/2030", "Zelle EXREF0501", "-7.00", "Field Trips"),
        _bank("5/3/2030", "Zelle EXREF0501 again", "-7.00", "Field Trips"),
    ]
    result = Scenario(tmp_path, bank=bank, bundle=payload).facts()
    states = {j.ticket_ref: j.state for j in result.reimbursements.joins}
    assert states == {
        PAID_TICKET: "matched",
        "P-002": "unmatched",
        "P-003": "unmatched",
        "P-004": "ambiguous",
    }
    codes = {issue.code: issue.count for issue in result.issues if "payment" in issue.code}
    # Prior-paid exempts only a MISSING reference; a reference that fails to join is a finding.
    assert codes == {
        "reimbursement_payment_unmatched": 2,
        "reimbursement_payment_ambiguous": 1,
    }


def test_reference_matching_ignores_case(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["supplemental"]["events"][0]["reference"] = "exref2001"
    _seal(payload["supplemental"]["events"][0])
    payload["tickets"][0]["live"]["confirmations"] = ["Reference exref2001; amount $45.00"]
    bank = _with_bank_row(
        CHECK_INDEX, _bank("7/10/2030", "Zelle EXREF2001 sent", "-45.00", "Classroom Supplies")
    )
    result = Scenario(tmp_path, bank=bank, bundle=payload).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == PAID_TICKET]
    assert join.state == "matched"


def test_prior_paid_legacy_payment_needs_no_date_or_reference(tmp_path: Path) -> None:
    payload = _bundle_payload()
    payload["tickets"][3]["live"]["payment_date"] = ""  # P-002 stays PAID_PRIOR
    result = Scenario(tmp_path, bundle=payload).facts()
    codes = {issue.code for issue in result.issues}
    assert "reimbursement_payment_undated" not in codes
    assert "reimbursement_payment_no_reference" not in codes
    # The item still shows an unknown payment date: it is never assigned a year.
    (item,) = [i for i in result.reimbursements.items if i.ticket_ref == "P-002"]
    assert item.payment_bucket == "undated"


def test_crosswalk_digest_blocks_an_adjustment_only_remap(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    grant = _adjustment(
        "additive",
        effective=date(2030, 8, 1),
        category="Grants",  # no source bank row carries this category
        signed_amount=Decimal("30.00"),
        evidence=("example-grant-letter-2030-08",),
    )
    scenario.record([grant])
    capture_set, ledger, bundle = scenario.inputs()
    assert scenario.config.main_reports is not None
    assert ledger.source.crosswalk_sha256 == reconcile.crosswalk_digest(
        scenario.config.main_reports.crosswalk
    )
    result = build_from(capture_set, ledger, bundle, scenario.config)
    assert result.budget.unmapped == (("Grants", Decimal("30.00")),)
    # Same version, an added mapping for the adjustment-only category: refused.
    remapped = CROSSWALK_TOML + (
        "[[main_reports.crosswalk.entries]]\n"
        'source_category = "Grants"\n'
        'targets = [{ category = "Fundraising", share = "1" }]\n'
        'note = "remapped later"\n'
    )
    reloaded = _config(tmp_path / "reloaded", crosswalk=remapped)
    with pytest.raises(FactsError) as caught:
        build_from(capture_set, ledger, bundle, reloaded)
    assert caught.value.code == "crosswalk_mismatch"


def test_school_year_start_month_comes_from_config(tmp_path: Path) -> None:
    result = Scenario(tmp_path, start_month=9).facts()
    school = result.periods.school
    assert (school.start, school.end_exclusive) == (date(2029, 9, 1), date(2030, 9, 1))
    assert school.label == "School year 2029–30" and result.budget.fiscal_year == 2030
    # September 2029 - Aug 15 2030 includes the Dec 31, Jan 1 and Jun 30 rows.
    assert result.view("school", "source").net == Decimal("48.25")


SAVINGS_TOML = (
    "\n[main_reports.sources.bank-savings]\n"
    'kind = "bank"\n'
    'tab = "Bank Savings"\n'
    f"header_signature = {json.dumps([BANK_HEADER])}\n"
    'coverage = [{ start = "2030-01-01", end = "2030-07-31", evidence = "example-savings" }]\n'
)


def test_every_bank_capture_must_be_complete(tmp_path: Path) -> None:
    savings = CfoWorksheet(
        [BANK_HEADER, _bank("7/20/2030", "Example interest", "1.00", "Interest Income")],
        sheet_id=1008,
    )
    result = Scenario(tmp_path, sources=SAVINGS_TOML, extra={"Bank Savings": savings}).facts()
    complete = {(status.source_alias, status.start): status.complete for status in result.coverage}
    assert complete[("bank-checking", date(2030, 7, 1))] is True
    assert complete[("bank-savings", date(2030, 7, 1))] is False
    # One complete account does not make the view complete.
    assert not result.view("school", "source").complete
    assert result.view("school", "source").net == Decimal("-0.75")
    flags = {(flag.code, flag.source_alias) for flag in result.coverage_flags}
    assert ("school_coverage_partial", "bank-savings") in flags
    assert ("school_coverage_partial", "bank-checking") not in flags


def test_payment_timing_later_and_undated_buckets(tmp_path: Path) -> None:
    payload = _bundle_payload()
    paid = payload["tickets"][0]
    paid["items"] += [
        _item("new-01:line:3", 3, "", "5.00", "A", "Classroom Supplies"),
        _item("new-01:line:4", 4, "2030-08-20", "3.00", "A", "Classroom Supplies"),
    ]
    paid["source"]["stated_total"] = paid["source"]["mapped_total"] = "53.00"
    paid["live"]["confirmations"] = [f"Reference {PAYMENT_REFERENCE}; amount $53.00"]
    event = payload["supplemental"]["events"][0]
    event["amount"] = "53.00"
    _seal(event)
    p002 = payload["tickets"][3]  # paid under the current process, date unknown
    p002["items"][0]["source_date"] = "2030-07-02"
    p002["live"]["payment_status"] = "PAID"
    p002["live"]["payment_date"] = ""
    result = Scenario(tmp_path, bundle=payload).facts()
    timing = result.bridge("school_payment_timing")
    assert [(row.kind, row.amount, row.item_keys) for row in timing.rows] == [
        ("paid_in_period_expense_prior", Decimal("25.00"), ("new-01:line:1",)),
        ("paid_in_period_expense_later", Decimal("3.00"), ("new-01:line:4",)),
        ("paid_in_period_expense_undated", Decimal("5.00"), ("new-01:line:3",)),
        ("approved_in_period_payment_unpaid", Decimal("-5.00"), ("new-03:line:2",)),
        ("approved_in_period_payment_undated", Decimal("-15.00"), ("p-002:line:1",)),
    ]
    assert (timing.from_amount, timing.to_amount) == (Decimal("40.00"), Decimal("53.00"))
    assert timing.balanced
    codes = {issue.code: issue.count for issue in result.issues}
    assert codes["reimbursement_payment_undated"] == 1


BUNDLE_AS_OF_CASES = {
    "same_day": ("2030-08-15", False),
    "older_inside_period": ("2030-08-10", False),
    "period_start": ("2030-07-01", False),
    "before_period_start": ("2030-06-30", True),
    "after_report_as_of": ("2030-08-16", True),
}


@pytest.mark.parametrize("case", sorted(BUNDLE_AS_OF_CASES))
def test_bundle_as_of_is_freshness_unless_outside_the_period(tmp_path: Path, case: str) -> None:
    day, flagged = BUNDLE_AS_OF_CASES[case]
    payload = _bundle_payload()
    payload["report"]["as_of_date"] = day
    result = Scenario(tmp_path, bundle=payload).facts()
    assert result.reimbursements.bundle_as_of == date.fromisoformat(day)
    found = [(i.code, i.count) for i in result.issues if i.code == "bundle_as_of_outside_period"]
    assert found == ([("bundle_as_of_outside_period", 1)] if flagged else [])


# --------------------------------------------------------------------------------------
# Crosswalk digest refusal, component by component
# --------------------------------------------------------------------------------------

GRANTS_TOML = (
    "[[main_reports.crosswalk.entries]]\n"
    'source_category = "Grants"\n'
    'targets = [{ category = "Fundraising", share = "1" }]\n'
    'note = "grant income"\n'
)


def test_retargeting_an_adjustment_only_category_is_refused(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path, crosswalk=CROSSWALK_TOML + GRANTS_TOML)
    grant = _adjustment(
        "additive",
        effective=date(2030, 8, 1),
        category="Grants",  # no source bank row carries this category
        signed_amount=Decimal("30.00"),
        evidence=("example-grant-letter-2030-08",),
    )
    scenario.record([grant])
    capture_set, ledger, bundle = scenario.inputs()
    accepted = build_from(capture_set, ledger, bundle, scenario.config)
    assert dict(accepted.budget.mapped_actuals)["Fundraising"] == Decimal("80.00")
    # Same version and entry count, Grants retargeted: the cell check cannot see it.
    retargeted = _config(
        tmp_path / "retargeted",
        crosswalk=CROSSWALK_TOML + GRANTS_TOML.replace("Fundraising", "Fees and Charges"),
    )
    with pytest.raises(FactsError) as caught:
        build_from(capture_set, ledger, bundle, retargeted)
    assert caught.value.code == "crosswalk_mismatch"


def _edit_entry(crosswalk: Any, source: str, **changes: Any) -> Any:
    return dataclasses.replace(
        crosswalk,
        entries=tuple(
            dataclasses.replace(entry, **changes) if entry.source_category == source else entry
            for entry in crosswalk.entries
        ),
    )


DIGEST_EDITS: dict[str, tuple[Callable[[Any], Any], bool]] = {
    "target_category": (
        lambda c: _edit_entry(
            c, "Assemblies", targets=(CrosswalkTarget("Field Trips", Decimal("1")),)
        ),
        True,
    ),
    "source_category": (
        lambda c: _edit_entry(c, "Assemblies", source_category="School Assemblies"),
        True,
    ),
    "note": (lambda c: _edit_entry(c, "Assemblies", note="reworded note"), True),
    "share_value": (
        lambda c: _edit_entry(
            c,
            "Assemblies",
            targets=(
                CrosswalkTarget("Assemblies", Decimal("0.6")),
                CrosswalkTarget("Field Trips", Decimal("0.4")),
            ),
        ),
        True,
    ),
    "share_spelling_only": (
        lambda c: _edit_entry(
            c, "Assemblies", targets=(CrosswalkTarget("Assemblies", Decimal("1.00")),)
        ),
        False,
    ),
}


@pytest.mark.parametrize("case", sorted(DIGEST_EDITS))
def test_each_crosswalk_component_is_verified(tmp_path: Path, case: str) -> None:
    edit, refused = DIGEST_EDITS[case]
    scenario = Scenario(tmp_path)
    assert scenario.config.main_reports is not None
    changed = edit(scenario.config.main_reports.crosswalk)
    if not refused:
        result, _ = scenario.build(crosswalk=changed)
        assert result.budget.crosswalk_version == 3
        return
    with pytest.raises(FactsError) as caught:
        scenario.build(crosswalk=changed)
    assert caught.value.code == "crosswalk_mismatch"


DECLARED_BANK_CAPTURE_CASES = {
    # Declared bank coverage 2029-07-01..2030-08-31; captured rows 2029-12-31..2030-08-16.
    "quiet_after_last_row": ("2030-08-17", FULL_BANK_COVERAGE, "", "unmatched"),
    "quiet_before_first_row": ("2029-11-15", FULL_BANK_COVERAGE, "", "unmatched"),
    "window_reaches_coverage_start": ("2029-05-17", FULL_BANK_COVERAGE, "", "unmatched"),
    "window_ends_before_coverage": ("2029-05-16", FULL_BANK_COVERAGE, "", "outside_capture_window"),
    "sent_on_last_covered_day": ("2030-08-31", FULL_BANK_COVERAGE, "", "unmatched"),
    "sent_after_coverage": ("2030-09-01", FULL_BANK_COVERAGE, "", "outside_capture_window"),
    "coverage_undeclared": ("2030-09-01", None, "", "unmatched"),
    "other_account_covers_window": (
        "2030-09-01",
        'start = "2029-07-01", end = "2030-07-31"',
        "covering",
        "unmatched",
    ),
    "other_account_undeclared": ("2029-05-01", FULL_BANK_COVERAGE, "undeclared", "unmatched"),
}

_SAVINGS_COVERAGE = (
    'coverage = [{ start = "2030-01-01", end = "2030-07-31", evidence = "example-savings" }]\n'
)


def _savings(kind: str) -> str:
    if kind == "covering":
        return SAVINGS_TOML.replace('end = "2030-07-31"', 'end = "2030-12-31"')
    if kind == "undeclared":
        return SAVINGS_TOML.replace(_SAVINGS_COVERAGE, "")
    return ""


@pytest.mark.parametrize("case", sorted(DECLARED_BANK_CAPTURE_CASES))
def test_only_payments_outside_declared_bank_coverage_are_informational(
    tmp_path: Path, case: str
) -> None:
    day, coverage, savings, expected = DECLARED_BANK_CAPTURE_CASES[case]
    payload = _bundle_payload()
    _record_payment(payload, payload["tickets"][3], day, "EXREF9999", "a")
    extra = {}
    if savings:
        extra = {"Bank Savings": CfoWorksheet([BANK_HEADER], sheet_id=1008)}
    result = Scenario(
        tmp_path, bank_coverage=coverage, sources=_savings(savings), extra=extra, bundle=payload
    ).facts()
    (join,) = [j for j in result.reimbursements.joins if j.ticket_ref == "P-002"]
    assert join.state == expected
    codes = {issue.code for issue in result.issues}
    assert ("reimbursement_payment_unmatched" in codes) is (expected == "unmatched")
