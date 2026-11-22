"""Tests for np_finance.main_reports.planning — the Classroom Budgets facts (CORE-BRIEFS).

Every fixture is fictional (``Example`` placeholders, fake ids and amounts). Production-path
cases run the real read-only capture of a fictional board-planning input and academic ledger
(:class:`tests.conftest.Scenario` with ``planning=``) through reconciliation, the journal
projection and :func:`np_finance.main_reports.facts.build_from`, which is the production
caller of :func:`planning.classroom_facts`. Pure cases exercise the ledger reader and the
display-rounding rule directly.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from np_finance import reimbursement_report
from np_finance.main_reports import facts, planning, sources
from np_finance.main_reports.facts import FactsError
from np_finance.main_reports.models import (
    CLASSROOM_SCHEMA_VERSION,
    ISSUED_REASONS,
    ClassroomFacts,
    ClassroomPayment,
    ClassroomRow,
    EnteredNumber,
    IssuedPayment,
    canonical_json_bytes,
    is_valid_record_key,
)
from tests.conftest import (
    BUDGET_ROWS,
    CLASSROOM_CATEGORY,
    CLASSROOM_ISSUED_REFERENCE,
    CLASSROOM_ISSUED_TICKET,
    CLASSROOM_LATER,
    CLASSROOM_LEDGER_COLUMNS,
    CLASSROOM_LEDGER_ROWS,
    CLASSROOM_LEDGER_TAB,
    CLASSROOM_LINKED,
    CLASSROOM_NO_REFERENCE,
    CLASSROOM_OTHER_CATEGORY,
    CLASSROOM_PREPAID,
    CLASSROOM_PRIOR_YEAR,
    CLASSROOM_REFUND,
    CLASSROOM_ROUNDING_FIGURES,
    CLASSROOM_SHARED,
    CLASSROOM_SIGN_FIGURES,
    CLASSROOM_UNREFERENCED_TICKET,
    PAID_TICKET,
    PLANNING_LEDGER_HEADER,
    Scenario,
    _budget_row,
    classroom_bundle,
    classroom_figures,
    classroom_ledger_row,
    classroom_planning_document,
    generated_classroom_figures,
)


def _facts(
    tmp_path: Path,
    document: dict[str, Any] | None = None,
    *,
    rows: list[list[str]] | None = None,
    **kwargs: Any,
) -> ClassroomFacts:
    """Classroom facts of the fictional world through the production caller."""
    grid = rows or CLASSROOM_LEDGER_ROWS
    scenario = Scenario(
        tmp_path / "world",
        planning=document if document is not None else classroom_planning_document(rows=grid),
        planning_tabs={CLASSROOM_LEDGER_TAB: grid},
        bundle=kwargs.pop("bundle", classroom_bundle()),
        **kwargs,
    )
    classroom = scenario.facts().classroom
    assert classroom is not None
    return classroom


def _by_id(classroom: ClassroomFacts) -> dict[str, ClassroomRow]:
    return {row.class_id: row for row in classroom.classes}


def _payment(
    classroom: ClassroomFacts, row: list[str], rows: list[list[str]] | None = None
) -> ClassroomPayment:
    key = classroom_ledger_row(row, rows or ()).record_key
    (found,) = [item for item in classroom.payments if item.record_key == key]
    return found


def _review_key(ref: str, bundle: dict[str, Any] | None = None) -> str:
    """The fictional bundle's review key of request ``ref``."""
    tickets = (bundle or classroom_bundle())["tickets"]
    (key,) = [t["review_key"] for t in tickets if t["ref"] == ref]
    return str(key)


def _paid_classroom_requests(bundle: dict[str, Any]) -> dict[str, Decimal]:
    """Review key to approved classroom-item total of every request the fictional bundle
    records paid in the school year to date (Jul 1 to Aug 15, 2030), computed here from
    the raw payload independently of the code under test."""
    requests: dict[str, Decimal] = {}
    for ticket in bundle["tickets"]:
        live = ticket["live"]
        if live["payment_status"] != "PAID":
            continue
        if not "2030-07-01" <= live["payment_date"] <= "2030-08-15":
            continue
        amounts = [
            Decimal(item["source_amount"])
            for item in ticket["items"]
            if item["status"] == "A" and item["canonical_category"] == CLASSROOM_CATEGORY
        ]
        if amounts:
            requests[ticket["review_key"]] = sum(amounts, Decimal("0.00"))
    return requests


def _assert_paid_or_issued_never_both(
    classroom: ClassroomFacts, bundle: dict[str, Any] | None = None
) -> None:
    """The D49 partition: every paid classroom request of the bundle is settled by exactly
    one posted row counted in paid or listed as issued, never both and never neither, and
    the two sides add up to the total of the paid classroom requests."""
    expected = _paid_classroom_requests(bundle or classroom_bundle())
    settled = [key for payment in classroom.payments for key in payment.review_keys]
    issued = {item.review_key: item for item in classroom.issued}
    assert len(settled) == len(set(settled)) and len(issued) == len(classroom.issued)
    assert not set(settled) & set(issued)  # never both
    assert sorted([*settled, *issued]) == sorted(expected)  # never neither
    assert all(item.amount == expected[key] for key, item in issued.items())
    assert all(item.reason in ISSUED_REASONS for item in issued.values())
    settled_total = sum((expected[key] for key in settled), Decimal("0.00"))
    assert settled_total + classroom.issued_total == sum(expected.values(), Decimal("0.00"))


# --------------------------------------------------------------------------------------
# Display rounding (rule 11)
# --------------------------------------------------------------------------------------


def test_display_parts_tie_signed_parts_to_the_correctly_rounded_total() -> None:
    parts, total = planning.display_parts([Decimal("0.50"), Decimal("0.50"), Decimal("0.50")])
    assert total == 2 and sum(parts) == 2 and parts == [1, 1, 0]  # ties in input order
    parts, total = planning.display_parts([Decimal("380.00"), Decimal("15.50")])
    assert (parts, total) == ([380, 16], 396)
    signed = [Decimal("160.00"), Decimal("120.40"), Decimal("-30.40"), Decimal("70.00")]
    parts, total = planning.display_parts(signed)
    assert total == 320 and sum(parts) == 320 and parts[2] == -30
    assert planning.display_parts([]) == ([], 0)
    # The total is the exact-cent sum rounded once, half up; each part moves by under $1.
    values = [Decimal("33.33"), Decimal("33.33"), Decimal("33.34"), Decimal("-0.49")]
    parts, total = planning.display_parts(values)
    assert total == 100 and sum(parts) == total
    assert all(abs(Decimal(part) - value) < 1 for part, value in zip(parts, values, strict=True))


def _sign(value: Decimal | int) -> int:
    return (value > 0) - (value < 0)


@pytest.mark.parametrize("seed", range(60))
def test_display_parts_never_flip_the_sign_of_a_part(seed: int) -> None:
    """Generated signed cents, many within a dollar of zero and some whole: a displayed part
    never has the opposite sign of its cents, a whole-dollar part keeps its value (so zero
    stays zero), and the parts still tie to the correctly rounded total."""
    count = 1 + seed % 9
    values = []
    for index in range(count):
        mixed = (seed * 7919 + index * 9731) % 4001 - 2000  # -20.00 to 20.00
        values.append(Decimal(mixed if index % 3 else mixed % 199 - 99) / 100)
        if index % 4 == 3:
            values[-1] = Decimal(mixed // 100)  # a whole-dollar part, zero included
    parts, total = planning.display_parts(values)
    assert total == _rounded(sum(values, Decimal("0.00"))) and sum(parts) == total
    for part, value in zip(parts, values, strict=True):
        assert _sign(part) in (_sign(value), 0), (values, parts)
        assert abs(Decimal(part) - value) < 1
        if value == value.to_integral_value():
            assert part == value


def test_display_parts_refuse_parts_that_do_not_add_up() -> None:
    with pytest.raises(FactsError) as mismatch:
        planning.display_parts([Decimal("1.00"), Decimal("2.00")], Decimal("4.00"))
    with pytest.raises(FactsError) as sub_cent:
        planning.display_parts([Decimal("1.005")])  # never sub-cent money
    assert mismatch.value.code == sub_cent.value.code == "display_parts_invalid"
    assert "4" not in str(mismatch.value) and "1.005" not in str(sub_cent.value)  # value-free


def _rounded(value: Decimal) -> int:
    """The half-up whole dollars of ``value``, computed here independently of the module."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@pytest.fixture(scope="module")
def fictional_classroom(tmp_path_factory: pytest.TempPathFactory) -> ClassroomFacts:
    """The fictional world's classroom facts, built once through the production caller."""
    return _facts(tmp_path_factory.mktemp("classroom"))


def test_classroom_display_keeps_the_totals_and_derives_the_differences(
    fictional_classroom: ClassroomFacts,
) -> None:
    data = classroom_figures(fictional_classroom, **CLASSROOM_ROUNDING_FIGURES)
    shown = planning.classroom_display(data, listed=3)
    # Kept totals, each rounded once half up: allocation 100.40 -> $100, budget 50.60 -> $51.
    # The difference is the displayed figures' difference ($49), never the rounded cents
    # difference ($50), so the printed trio ties.
    assert (shown.allocation_total, shown.classroom_budget) == (100, 51)
    assert shown.allocation_difference == 49
    # Paid 112.50 -> $113, shared by largest remainder among the classrooms and unassigned.
    assert [row.paid for row in shown.classes] == [11, 21, 0, 61, 0]
    assert (shown.paid_total, shown.unassigned_total, shown.assigned_total) == (113, 20, 93)
    # The remaining figures are their own group: remainders 39.70, 29.70, -0.40 and -60.60
    # keep 8.40 -> $8, shared by largest remainder, so classroom c (40 cents over budget)
    # displays -$1 rather than allocation less paid ($0), and none flips its sign.
    assert [row.allocation for row in shown.classes] == [50, 50, 0, 0, None]
    assert [row.remaining for row in shown.classes] == [40, 30, -1, -61, None]
    assert (shown.remaining_total, shown.overrun) == (8, 62)
    # Purchases 32.00 -> $32: three listed rows and the exact Other row (50 cents -> $0).
    assert (shown.purchases, shown.other, shown.purchase_total) == ((11, 11, 10), 0, 32)
    assert shown.issued_total == 1
    # The facts keep their cents.
    assert data.allocation_difference == Decimal("49.80")
    assert data.remaining_total == Decimal("8.40")


def _near_zero_remainders(figures: dict[str, Any], seed: int) -> dict[str, Any]:
    """``figures`` with each allocated classroom's paid figure moved to within a dollar of
    its allocation (never below zero), so its cents remainder lands near zero, where display
    rounding could flip a sign. Every other figure is unchanged."""
    paid = list(figures["paid"])
    for index, allocated in enumerate(figures["allocations"]):
        if allocated is not None:
            offset = Decimal((seed * 7919 + (4 + index) * 9731) % 199 - 99) / 100  # +-0.99
            paid[index] = str(max(Decimal(allocated) + offset, Decimal("0.00")))
    return {**figures, "paid": paid}


@pytest.mark.parametrize("seed", range(40))
def test_classroom_display_ties_every_group_over_generated_cents(
    fictional_classroom: ClassroomFacts, seed: int
) -> None:
    """Generated cents; on odd seeds every allocated classroom's paid figure is within a
    dollar of its allocation, so remainders near zero keep their sign and marker too."""
    figures = generated_classroom_figures(seed)
    if seed % 2:
        figures = _near_zero_remainders(figures, seed)
    data = classroom_figures(fictional_classroom, **figures)
    shown = planning.classroom_display(data, listed=3)
    assert data.allocation_total is not None and data.source_total is not None
    assert data.classroom_budget is not None and shown.unassigned_total is not None
    # Kept totals are the correctly rounded totals.
    assert shown.allocation_total == _rounded(data.allocation_total)
    assert shown.classroom_budget == _rounded(data.classroom_budget)
    assert shown.paid_total == _rounded(data.source_total)
    assert shown.issued_total == _rounded(data.issued_total)
    total = sum((item.amount for item in data.purchases), Decimal("0.00"))
    assert shown.purchase_total == _rounded(total)
    # Parts tie to their kept totals, and each moves by under $1 from its cents.
    allocations, paid, remaining = [], [], []
    for row, figures in zip(data.classes, shown.classes, strict=True):
        assert (figures.allocation is None) is (row.allocation is None)
        assert (figures.paid is None) is (row.paid is None)
        if row.allocation is not None and figures.allocation is not None:
            assert abs(figures.allocation - row.allocation) < 1
            allocations.append(figures.allocation)
        if row.paid is not None and figures.paid is not None:
            assert abs(figures.paid - row.paid) < 1
            paid.append(figures.paid)
        # The remaining group: each part keeps its cents' sign and moves by under $1; it
        # may differ from allocation less paid by at most $1.
        if row.remainder is None:
            assert figures.remaining is None
        else:
            assert figures.allocation is not None and figures.paid is not None
            assert abs(row.remainder) < 1 or not seed % 2  # odd seeds: near zero
            assert _sign(figures.remaining) in (_sign(row.remainder), 0), (seed, row.class_id)
            assert (figures.remaining < 0) <= row.over_budget
            assert (figures.remaining > 0) <= (not row.over_budget)
            assert abs(figures.remaining - row.remainder) < 1
            assert abs(figures.allocation - figures.paid - figures.remaining) <= 1
            remaining.append(figures.remaining)
    assert sum(allocations) == shown.allocation_total
    assert sum(paid) + shown.unassigned_total == shown.paid_total
    assert shown.assigned_total == sum(paid)
    assert shown.other is not None
    assert sum(shown.purchases) + shown.other == shown.purchase_total
    assert shown.allocation_difference == shown.allocation_total - shown.classroom_budget
    assert data.remaining_total is not None
    assert shown.remaining_total == _rounded(data.remaining_total) == sum(remaining)
    assert shown.overrun == -sum(value for value in remaining if value < 0)


@pytest.mark.parametrize(("case", "allocation", "paid"), [("over", 101, 100), ("under", 100, 101)])
def test_a_displayed_remaining_never_contradicts_its_over_budget_marker(
    fictional_classroom: ClassroomFacts, case: str, allocation: int, paid: int
) -> None:
    """Round 5's two cases: allocation less paid in displayed dollars has the opposite sign
    of the 10-cent remainder, so the displayed remaining comes from its own group ($0)."""
    data = classroom_figures(fictional_classroom, **CLASSROOM_SIGN_FIGURES[case])
    row, *_ = data.classes
    assert row.remainder == (Decimal("-0.10") if case == "over" else Decimal("0.10"))
    assert row.over_budget is (case == "over")
    shown = planning.classroom_display(data, listed=3)
    figures = shown.classes[0]
    assert (figures.allocation, figures.paid, figures.remaining) == (allocation, paid, 0)
    assert [row.remaining for row in shown.classes] == (
        [0, 49, 50, 50, None] if case == "over" else [0, 50, 50, 50, None]
    )
    assert (shown.remaining_total, shown.overrun) == (149 if case == "over" else 150, 0)


def test_classroom_display_refuses_facts_whose_parts_do_not_add_up(
    fictional_classroom: ClassroomFacts,
) -> None:
    broken = dataclasses.replace(fictional_classroom, source_total=Decimal("1.00"))
    with pytest.raises(FactsError) as raised:
        planning.classroom_display(broken, listed=3)
    assert raised.value.code == "display_parts_invalid"


# --------------------------------------------------------------------------------------
# Academic-ledger identities
# --------------------------------------------------------------------------------------


def test_ledger_rows_use_the_record_key_convention_and_keep_identical_rows_distinct() -> None:
    twin = list(CLASSROOM_SHARED)
    grid = [PLANNING_LEDGER_HEADER, CLASSROOM_SHARED, twin, CLASSROOM_LINKED]
    rows = planning.read_ledger(grid, 1, CLASSROOM_LEDGER_COLUMNS)
    assert [row.row_number for row in rows] == [2, 3, 4]
    assert all(is_valid_record_key(row.record_key) for row in rows)
    assert all(row.record_key.split(":")[1] == planning.ACADEMIC_LEDGER_ALIAS for row in rows)
    # Identical-looking rows are never collapsed: same identity, distinct occurrences.
    first, second = rows[0], rows[1]
    assert first.record_key.rsplit(":", 1)[0] == second.record_key.rsplit(":", 1)[0]
    assert {first.record_key, second.record_key} == {
        first.record_key.rsplit(":", 1)[0] + ":0",
        first.record_key.rsplit(":", 1)[0] + ":1",
    }
    assert first.amount == Decimal("-90.00") and first.spend == Decimal("90.00")
    assert first.fiscal_year == 2031 and first.payment_reference == "EX-3002"


def test_ledger_keys_survive_reordering_and_a_revision_names_exact_content() -> None:
    grid = [PLANNING_LEDGER_HEADER, CLASSROOM_LINKED, CLASSROOM_SHARED]
    reordered = [PLANNING_LEDGER_HEADER, CLASSROOM_SHARED, CLASSROOM_LINKED]
    keys = {
        (r.record_key, r.revision_hash)
        for r in planning.read_ledger(grid, 1, CLASSROOM_LEDGER_COLUMNS)
    }
    again = {
        (r.record_key, r.revision_hash)
        for r in planning.read_ledger(reordered, 1, CLASSROOM_LEDGER_COLUMNS)
    }
    assert keys == again
    edited = [PLANNING_LEDGER_HEADER, [*CLASSROOM_LINKED[:6], "Example Revised Payee"]]
    (row,) = planning.read_ledger(edited, 1, CLASSROOM_LEDGER_COLUMNS)
    original = classroom_ledger_row(CLASSROOM_LINKED)
    # The identity (date, description, amount, reference) is unchanged; the revision moves.
    assert row.record_key == original.record_key and row.revision_hash != original.revision_hash


def test_ledger_amounts_fail_closed_on_hidden_precision_and_read_an_accounting_zero() -> None:
    grid = [
        PLANNING_LEDGER_HEADER,
        ["8/1/2030", "Example hidden cents", "-10.00", CLASSROOM_CATEGORY, "2031", "EX-1", ""],
        ["8/2/2030", "Example accounting zero", "-", CLASSROOM_CATEGORY, "2031", "EX-2", ""],
        ["8/3/2030", "Example text dash", "-", CLASSROOM_CATEGORY, "2031", "EX-3", ""],
        ["not a date", "Example undated", "-1.00", CLASSROOM_CATEGORY, "2031", "EX-4", ""],
    ]
    entered = (EnteredNumber(1, 2, "-10.004"), EnteredNumber(2, 2, "0"))
    rows = planning.read_ledger(grid, 1, CLASSROOM_LEDGER_COLUMNS, entered_numbers=entered)
    assert [row.amount for row in rows] == [None, Decimal("0.00"), None, Decimal("-1.00")]
    assert rows[3].payment_date is None


# The D50 academic-year label grammar: every accepted form resolves to its ending year.
ACCEPTED_YEAR_LABELS = [
    ("2031", 2031),
    ("FY2031", 2031),
    ("FY 2031", 2031),
    ("fy2031", 2031),
    ("Fy 2031", 2031),
    ("2030-31", 2031),
    ("2030-2031", 2031),
    ("2030\u201331", 2031),  # en dash
    ("2030\u20132031", 2031),
    ("2030/31", 2031),
    ("2030/2031", 2031),
    ("2099-00", 2100),  # a two-digit end year wraps the century
    (" 2030-31 ", 2031),  # the cell is trimmed, as every ledger cell is
]
# Every other label leaves the row unmapped (never inferred from the payment date).
REJECTED_YEAR_LABELS = [
    "",
    "next year",
    "2030-32",  # not consecutive
    "2030-2032",
    "2031-30",  # reversed
    "2030-30",
    "2030 - 31",  # no spaces around the separator
    "2030 31",
    "2030_31",  # only a hyphen, an en dash or a slash separates a span
    "2030.31",
    "2030\u201431",  # em dash
    "FY2030-31",  # FY prefixes an ending year only
    "FY  2031",  # at most one space after FY
    "FY-2031",
    "SY2031",
    "203",
    "20310",
    "2,031",
    "2031.0",
    "\uff12\uff10\uff13\uff11",  # full-width digits: ASCII digits only
]


@pytest.mark.parametrize(
    ("label", "year"),
    [*ACCEPTED_YEAR_LABELS, *((label, None) for label in REJECTED_YEAR_LABELS)],
)
def test_academic_year_labels_follow_the_d50_grammar(label: str, year: int | None) -> None:
    grid = [
        PLANNING_LEDGER_HEADER,
        ["8/1/2030", "Example order", "-1.00", CLASSROOM_CATEGORY, label, "EX-1", ""],
    ]
    (row,) = planning.read_ledger(grid, 1, CLASSROOM_LEDGER_COLUMNS)
    assert row.fiscal_year == year


def test_an_unreadable_academic_year_leaves_its_row_unmapped_with_a_finding(
    tmp_path: Path,
) -> None:
    unreadable = ["8/2/2030", "Example order", "-7.00", CLASSROOM_CATEGORY, "2030-32", "EX-8", ""]
    trip = ["8/2/2030", "Example bus", "-9.00", "Field Trips", "FY2030-31", "EX-9", ""]
    rows = [*CLASSROOM_LEDGER_ROWS, unreadable, trip]
    classroom = _facts(tmp_path, rows=rows)
    findings = {f.code: f.count for f in classroom.findings}
    assert findings["ledger_year_unreadable"] == 2  # every unmapped row, any category
    (excluded,) = [item for item in classroom.excluded if item.reason == "year_unreadable"]
    assert (excluded.rows, excluded.amount) == (1, Decimal("7.00"))
    assert excluded.record_keys == (classroom_ledger_row(unreadable, rows).record_key,)
    assert classroom.source_total == Decimal("395.50")  # never counted in paid
    assert "rows_unreadable" in classroom.reasons


# --------------------------------------------------------------------------------------
# Classroom facts through the production caller
# --------------------------------------------------------------------------------------


def test_source_payments_reconcile_to_assigned_plus_unassigned(tmp_path: Path) -> None:
    classroom = _facts(tmp_path)
    assert classroom.status == "partial" and classroom.reasons == ("payments_unassigned",)
    # Linked 45 + shared 90 + prepaid 250 + unreferenced 15.50 - refund 5 (signed, unclamped).
    assert classroom.source_total == Decimal("395.50")
    assert classroom.assigned_total == Decimal("380.00")
    assert classroom.unassigned_total == Decimal("15.50")
    assert classroom.source_total == classroom.assigned_total + classroom.unassigned_total
    assert sum(p.amount for p in classroom.payments) == classroom.source_total
    for payment in classroom.payments:
        assert sum(a.amount for a in payment.assignments) + payment.unassigned == payment.amount
    paid = {row.class_id: row.paid for row in classroom.classes}
    assert paid == {
        "class-a": Decimal("40.00"),  # 45 paid, 5 refunded
        "class-b": Decimal("60.00"),
        "class-c": Decimal("250.00"),
        "class-d": Decimal("30.00"),
        "class-e": Decimal("0.00"),
    }
    assert sum(paid.values()) == classroom.assigned_total
    # A payee mapping never assigns a row without an explicit payment reference.
    unreferenced = _payment(classroom, CLASSROOM_NO_REFERENCE)
    assert unreferenced.assignments == () and unreferenced.unassigned == Decimal("15.50")
    assert ("classroom_payment_unassigned", 1) in {(f.code, f.count) for f in classroom.findings}
    # Every displayed class row keeps its exact source rows.
    assert _by_id(classroom)["class-a"].payment_keys == (
        classroom_ledger_row(CLASSROOM_LINKED).record_key,
        classroom_ledger_row(CLASSROOM_REFUND).record_key,
    )


def test_shared_splits_and_check_mappings_count_each_payment_once(tmp_path: Path) -> None:
    classroom = _facts(tmp_path)
    shared = _payment(classroom, CLASSROOM_SHARED)
    assert [(a.class_id, a.amount, a.basis) for a in shared.assignments] == [
        ("class-b", Decimal("60.00"), "payment_allocation"),
        ("class-d", Decimal("30.00"), "payment_allocation"),
    ]
    assert shared.amount == Decimal("90.00") and shared.unassigned == Decimal("0.00")
    # The paid request whose check (reference 2001) posted is linked to that one row: its
    # items are purchases of that payment and it is not also listed as issued.
    linked = _payment(classroom, CLASSROOM_LINKED)
    assert len(linked.review_keys) == 1
    assert [p.record_key for p in classroom.purchases] == [linked.record_key] * 2
    assert sorted(p.amount for p in classroom.purchases) == [Decimal("20.00"), Decimal("25.00")]
    assert all(p.class_ids == ("class-a",) for p in classroom.purchases)
    assert PAID_TICKET not in {item.ticket_ref for item in classroom.issued}
    # The request paid on Aug 14 has not posted: shown separately, never in paid.
    (issued,) = classroom.issued
    assert issued.ticket_ref == CLASSROOM_ISSUED_TICKET and issued.amount == Decimal("12.00")
    assert issued.reason == "not_posted"
    assert classroom.issued_total == Decimal("12.00")
    assert all(not p.review_keys or p is linked for p in classroom.payments)


def test_an_issued_payment_leaves_the_issued_list_once_it_posts(tmp_path: Path) -> None:
    before = _facts(tmp_path / "before")
    posted_row = [
        "8/14/2030",
        "Example reimbursement check",
        "-12.00",
        CLASSROOM_CATEGORY,
        "2031",
        CLASSROOM_ISSUED_REFERENCE,
        "Example Payee A",
    ]
    rows = [*CLASSROOM_LEDGER_ROWS, posted_row]
    after = _facts(tmp_path / "after", rows=rows)
    assert after.issued == () and after.issued_total == Decimal("0.00")
    # The same $12 is counted exactly once: it moved from issued to paid.
    assert after.source_total == before.source_total + Decimal("12.00")
    assert after.source_total + after.issued_total == before.source_total + before.issued_total
    posted = classroom_ledger_row(posted_row, rows)
    (payment,) = [p for p in after.payments if p.record_key == posted.record_key]
    assert len(payment.review_keys) == 1 and payment.assignments[0].class_id == "class-a"
    assert {p.ticket_ref for p in after.purchases} == {PAID_TICKET, CLASSROOM_ISSUED_TICKET}


# A check that posted to the ledger without a reference (fictional), for the issued request.
CHECK_WITHOUT_REFERENCE = [
    "8/14/2030",
    "Example reimbursement check",
    "-12.00",
    CLASSROOM_CATEGORY,
    "2031",
    "",
    "Example Payee A",
]


def _check_allocation(
    rows: list[list[str]], check: list[str] = CHECK_WITHOUT_REFERENCE, **fields: str
) -> dict[str, Any]:
    """An evidence-backed $12 allocation of the reference-less ``check`` to class-a;
    ``fields`` override the evidence text or add the optional D49 ``review_key``."""
    row = classroom_ledger_row(check, rows)
    return {
        "source_record_key": row.record_key,
        "source_revision_hash": row.revision_hash,
        "class_id": "class-a",
        "amount": "12.00",
        "evidence": "fictional check photo",
        **fields,
    }


def test_a_verified_check_mapping_without_a_reference_is_paid_never_also_issued(
    tmp_path: Path,
) -> None:
    rows = [*CLASSROOM_LEDGER_ROWS, CHECK_WITHOUT_REFERENCE]
    review_key = _review_key(CLASSROOM_ISSUED_TICKET)
    document = classroom_planning_document(rows=rows)
    document["payment_allocations"].append(_check_allocation(rows, review_key=review_key))
    classroom = _facts(tmp_path / "linked", document, rows=rows)
    # The allocation assigns the reference-less row and its review_key names the request it
    # paid, so the request is counted in paid through that one row and is not also issued.
    check = _payment(classroom, CHECK_WITHOUT_REFERENCE, rows)
    assert [(a.class_id, a.amount, a.basis) for a in check.assignments] == [
        ("class-a", Decimal("12.00"), "payment_allocation")
    ]
    assert check.payment_reference is None and check.review_keys == (review_key,)
    assert classroom.issued == () and classroom.issued_total == Decimal("0.00")
    assert classroom.source_total == Decimal("407.50")  # 395.50 + the posted $12, counted once
    assert _by_id(classroom)["class-a"].paid == Decimal("52.00")
    assert CLASSROOM_ISSUED_TICKET in {p.ticket_ref for p in classroom.purchases}
    codes = {f.code for f in classroom.findings}
    assert "issued_payment_amount_mismatch" not in codes
    assert "issued_payment_out_of_scope" not in codes
    _assert_paid_or_issued_never_both(classroom)
    # Evidence is free text, never parsed as an identifier: evidence that spells out the
    # request's review key exactly does not link it, so the request stays issued.
    other = classroom_planning_document(rows=rows)
    other["payment_allocations"].append(_check_allocation(rows, evidence=review_key))
    unlinked = _facts(tmp_path / "unlinked", other, rows=rows)
    assert _payment(unlinked, CHECK_WITHOUT_REFERENCE, rows).review_keys == ()
    assert [(item.review_key, item.reason) for item in unlinked.issued] == [
        (review_key, "not_posted")
    ]
    _assert_paid_or_issued_never_both(unlinked)


@pytest.mark.parametrize(
    ("source", "out_of_scope"),
    [
        pytest.param(CLASSROOM_PRIOR_YEAR, 1, id="prior-school-year"),
        pytest.param(CLASSROOM_OTHER_CATEGORY, 1, id="non-classroom-category"),
        pytest.param(CLASSROOM_LATER, 0, id="after-as-of"),
    ],
)
def test_a_reference_only_on_rows_outside_paid_keeps_the_request_issued(
    tmp_path: Path, source: list[str], out_of_scope: int
) -> None:
    # A reused check number on a row that feeds no paid figure never marks the request
    # posted: it stays listed as issued (never added to paid), with a finding when that row
    # is dated on or before the as-of date (after it, the payment simply has not posted).
    reused = [*source[:5], CLASSROOM_ISSUED_REFERENCE, *source[6:]]
    rows = [*CLASSROOM_LEDGER_ROWS, reused]
    classroom = _facts(tmp_path, rows=rows)
    (issued,) = classroom.issued
    assert issued.ticket_ref == CLASSROOM_ISSUED_TICKET and issued.amount == Decimal("12.00")
    assert issued.reason == ("reference_out_of_scope" if out_of_scope else "not_posted")
    findings = {f.code: f.count for f in classroom.findings}
    assert findings.get("issued_payment_out_of_scope", 0) == out_of_scope
    assert classroom_ledger_row(reused, rows).record_key not in {
        p.record_key for p in classroom.payments
    }
    assert classroom.source_total == Decimal("395.50")
    _assert_paid_or_issued_never_both(classroom)


# Every case of the D49 partition. Each names the request it is about, the rows added to
# the ledger, the allocations added to the planning document, the optional unreferenced
# request's category, and the expected outcome: the posted row that settles the request
# (by its index in the added rows, or the fixture's referenced row) or its issued reason,
# with the findings the case must add.
UNREFERENCED_KEY = "legacy:v1:" + CLASSROOM_UNREFERENCED_TICKET.lower()
TWIN_ISSUED = [
    "8/14/2030",
    "Example reimbursement check",
    "-12.00",
    CLASSROOM_CATEGORY,
    "2031",
    CLASSROOM_ISSUED_REFERENCE,
    "Example Payee A",
]
PARTITION_CASES = [
    pytest.param(
        PAID_TICKET, [], [], None, ("settled", CLASSROOM_LINKED), {}, id="exact-reference-in-scope"
    ),
    pytest.param(
        CLASSROOM_ISSUED_TICKET,
        [[*CLASSROOM_PRIOR_YEAR[:5], CLASSROOM_ISSUED_REFERENCE, *CLASSROOM_PRIOR_YEAR[6:]]],
        [],
        None,
        ("issued", "reference_out_of_scope"),
        {"issued_payment_out_of_scope": 1},
        id="reference-only-on-out-of-scope-rows",
    ),
    pytest.param(
        CLASSROOM_UNREFERENCED_TICKET,
        [CHECK_WITHOUT_REFERENCE],
        [{"review_key": UNREFERENCED_KEY}],
        CLASSROOM_CATEGORY,
        ("settled", CHECK_WITHOUT_REFERENCE),
        # Settled, but with no recorded payment amount to cross-check against the row.
        {"issued_payment_amount_mismatch": 1},
        id="no-reference-allocation-with-review-key",
    ),
    pytest.param(
        CLASSROOM_UNREFERENCED_TICKET,
        [CHECK_WITHOUT_REFERENCE],
        [{"evidence": UNREFERENCED_KEY}],  # evidence text is never an identifier
        CLASSROOM_CATEGORY,
        ("issued", "no_reference"),
        {"issued_payment_no_reference": 1},
        id="no-reference-allocation-without-review-key",
    ),
    pytest.param(
        CLASSROOM_UNREFERENCED_TICKET,
        [CHECK_WITHOUT_REFERENCE],
        [],
        CLASSROOM_CATEGORY,
        ("issued", "no_reference"),
        {"issued_payment_no_reference": 1},
        id="no-reference-no-allocation",
    ),
    pytest.param(
        CLASSROOM_UNREFERENCED_TICKET,
        [CHECK_WITHOUT_REFERENCE],
        [{"review_key": "legacy:v1:p-999"}],
        CLASSROOM_CATEGORY,
        ("issued", "no_reference"),
        {"payment_allocation_review_key_unknown": 1, "issued_payment_no_reference": 1},
        id="unknown-review-key",
    ),
    pytest.param(
        None,
        [CHECK_WITHOUT_REFERENCE],
        [{"review_key": UNREFERENCED_KEY}],
        "Field Trips",  # a paid request, but not a classroom request
        None,
        {"payment_allocation_review_key_out_of_scope": 1},
        id="review-key-of-a-paid-non-classroom-request",
    ),
    pytest.param(
        CLASSROOM_ISSUED_TICKET,
        [TWIN_ISSUED, [*TWIN_ISSUED[:1], "Example second check", *TWIN_ISSUED[2:]]],
        [],
        None,
        ("issued", "ambiguous"),
        {"issued_payment_ambiguous": 1},
        id="reference-on-two-posted-rows",
    ),
]


@pytest.mark.parametrize(
    ("subject", "added_rows", "added_allocations", "unreferenced", "outcome", "added_findings"),
    PARTITION_CASES,
)
def test_every_paid_classroom_request_is_settled_by_one_posted_row_or_issued(
    tmp_path: Path,
    subject: str | None,
    added_rows: list[list[str]],
    added_allocations: list[dict[str, str]],
    unreferenced: str | None,
    outcome: tuple[str, Any] | None,
    added_findings: dict[str, int],
) -> None:
    rows = [*CLASSROOM_LEDGER_ROWS, *added_rows]
    document = classroom_planning_document(rows=rows)
    for fields in added_allocations:
        document["payment_allocations"].append(_check_allocation(rows, **fields))
    bundle = classroom_bundle(unreferenced=unreferenced)
    classroom = _facts(tmp_path, document, rows=rows, bundle=bundle)
    _assert_paid_or_issued_never_both(classroom, bundle)
    if subject is not None and outcome is not None:
        key = _review_key(subject, bundle)
        side, detail = outcome
        if side == "settled":
            assert _payment(classroom, detail, rows).review_keys == (key,)
            assert key not in {item.review_key for item in classroom.issued}
        else:
            assert [i.reason for i in classroom.issued if i.review_key == key] == [detail]
            assert all(key not in p.review_keys for p in classroom.payments)
    # Each case adds exactly its own findings to those of the base fixture world.
    base = {f.code: f.count for f in _facts(tmp_path / "base").findings}
    findings = {f.code: f.count for f in classroom.findings}
    for code in {*base, *findings, *added_findings}:
        if code == "classroom_payment_unassigned":
            continue  # an added reference-less row stays unassigned unless allocated
        assert findings.get(code, 0) == base.get(code, 0) + added_findings.get(code, 0), code
    assert set(added_findings) <= set(planning.CLASSROOM_FINDINGS)


def test_the_partition_invariant_refuses_a_request_on_neither_or_both_sides(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(classroom_bundle()), encoding="utf-8")
    (ticket,) = [
        t
        for t in reimbursement_report.load_bundle(path).tickets
        if t.ref == CLASSROOM_ISSUED_TICKET
    ]
    paid_on = ticket.live.payment_date
    assert paid_on is not None
    request = planning._PaidRequest(ticket, paid_on, ticket.items, None, None)
    issued = IssuedPayment(ticket.review_key, ticket.ref, paid_on, request.amount, (), "not_posted")
    # Exactly one side holds the request: either partition passes.
    planning._check_partition([request], planning._Partition(issued=[issued]))
    planning._check_partition([request], planning._Partition(settled={"row": [request]}))
    broken = [
        planning._Partition(),  # neither
        planning._Partition(settled={"row": [request]}, issued=[issued]),  # both
        planning._Partition(issued=[dataclasses.replace(issued, amount=Decimal("1.00"))]),
    ]
    for partition in broken:
        with pytest.raises(FactsError) as raised:
            planning._check_partition([request], partition)
        assert raised.value.code == "classroom_partition_mismatch"


def test_an_allocation_review_key_is_optional_and_exact(tmp_path: Path) -> None:
    # A version-1 document without review_key stays valid (every other case here); with one,
    # the key must be a non-empty string and any other extra key is still refused at
    # capture, value-free.
    for index, (name, value) in enumerate(
        [("review_key", ""), ("review_key", 12), ("review_key", None), ("note", "x")]
    ):
        document = classroom_planning_document()
        document["payment_allocations"][0][name] = value
        with pytest.raises(sources.SourceConfigError) as raised:
            _facts(tmp_path / str(index), document)
        assert raised.value.code == "planning_input_invalid"
        assert str(raised.value).startswith("planning_input_invalid: payment_allocations[0]")
    # The key is compared exactly: another case spelling of a real review key is unknown.
    rows = [*CLASSROOM_LEDGER_ROWS, CHECK_WITHOUT_REFERENCE]
    document = classroom_planning_document(rows=rows)
    review_key = _review_key(CLASSROOM_ISSUED_TICKET)
    document["payment_allocations"].append(_check_allocation(rows, review_key=review_key.upper()))
    classroom = _facts(tmp_path / "case", document, rows=rows)
    findings = {f.code: f.count for f in classroom.findings}
    assert findings["payment_allocation_review_key_unknown"] == 1
    assert [item.review_key for item in classroom.issued] == [review_key]


# One $24 check posted without a reference that pays two $12 requests of class-a.
DOUBLE_CHECK = [*CHECK_WITHOUT_REFERENCE[:2], "-24.00", *CHECK_WITHOUT_REFERENCE[3:]]


def test_one_row_settles_two_requests_of_one_class_through_distinct_review_keys(
    tmp_path: Path,
) -> None:
    rows = [*CLASSROOM_LEDGER_ROWS, DOUBLE_CHECK]
    bundle = classroom_bundle(unreferenced=CLASSROOM_CATEGORY)
    keys = [_review_key(CLASSROOM_ISSUED_TICKET, bundle), UNREFERENCED_KEY]
    document = classroom_planning_document(rows=rows)
    for key in keys:
        document["payment_allocations"].append(
            _check_allocation(rows, DOUBLE_CHECK, review_key=key)
        )
    classroom = _facts(tmp_path, document, rows=rows, bundle=bundle)
    # Both allocations of the one row to class-a apply: the row settles both requests, so
    # neither is also listed as issued, and class-a is paid the row once.
    check = _payment(classroom, DOUBLE_CHECK, rows)
    assert sorted(check.review_keys) == sorted(keys)
    assert [(a.class_id, a.amount, a.basis) for a in check.assignments] == [
        ("class-a", Decimal("24.00"), "payment_allocation")
    ]
    assert classroom.issued == ()
    assert _by_id(classroom)["class-a"].paid == Decimal("64.00")  # 40.00 + the $24 check
    _assert_paid_or_issued_never_both(classroom, bundle)


@pytest.mark.parametrize(
    "review_key",
    [pytest.param(UNREFERENCED_KEY, id="same-review-key"), pytest.param(None, id="no-review-key")],
)
def test_a_repeated_allocation_of_one_row_to_one_class_is_refused(
    tmp_path: Path, review_key: str | None
) -> None:
    # The same row, class and review key twice (or twice without one) stays a duplicate;
    # the amounts would still add up to the row's payment.
    rows = [*CLASSROOM_LEDGER_ROWS, DOUBLE_CHECK]
    document = classroom_planning_document(rows=rows)
    fields = {} if review_key is None else {"review_key": review_key}
    for _ in range(2):
        document["payment_allocations"].append(_check_allocation(rows, DOUBLE_CHECK, **fields))
    with pytest.raises(sources.SourceConfigError) as raised:
        _facts(tmp_path, document, rows=rows)
    index = len(document["payment_allocations"]) - 1
    assert str(raised.value) == (
        f"planning_input_invalid: payment_allocations[{index}]: duplicates an allocation"
    )


def test_planning_reads_the_shared_vocabularies() -> None:
    assert planning.ACADEMIC_LEDGER_ROLE is sources.PLANNING_ROLES[0]
    assert planning._EXPENSE_ROLE is sources.CATEGORY_ROLES[2]
    assert planning._EXPENSE_LINE is facts.BUDGET_LINE_TYPES[1]
    assert planning.PAID_STATUS is facts.PAID_STATUS
    assert planning._NOT_POSTED is ISSUED_REASONS[0] and planning._AMBIGUOUS is ISSUED_REASONS[3]


def test_a_missing_roster_is_an_explicit_unavailable_allocation_never_equal_shares(
    tmp_path: Path,
) -> None:
    document = classroom_planning_document(classes=[], allocations=[])
    document["payee_aliases"] = []
    classroom = _facts(tmp_path, document)
    assert classroom.classes == () and classroom.allocation_total is None
    assert "roster_absent" in classroom.reasons and classroom.status == "partial"
    # Every posted classroom payment stays visible as unassigned; nothing is divided equally.
    assert classroom.assigned_total == Decimal("0.00")
    assert classroom.unassigned_total == classroom.source_total == Decimal("395.50")
    assert classroom.remaining_total is None and classroom.allocation_difference is None


def test_missing_enrollment_or_rate_leaves_that_allocation_unavailable(tmp_path: Path) -> None:
    document = classroom_planning_document()
    document["classes"][1]["student_count"] = None
    document["classes"][2]["per_student_amount"] = None
    classroom = _facts(tmp_path, document)
    rows = _by_id(classroom)
    assert (rows["class-b"].allocation_state, rows["class-b"].allocation) == (
        "enrollment_missing",
        None,
    )
    assert (rows["class-c"].allocation_state, rows["class-c"].allocation) == ("rate_missing", None)
    assert rows["class-b"].remainder is None and rows["class-b"].paid == Decimal("60.00")
    assert rows["class-e"].allocation_state == "not_eligible"
    # Known allocations only: never an estimate for the missing ones.
    assert classroom.allocation_total == Decimal("300.00")
    assert "allocation_missing" in classroom.reasons


def test_an_over_budget_classroom_keeps_a_signed_negative_remainder(tmp_path: Path) -> None:
    classroom = _facts(tmp_path)
    rows = _by_id(classroom)
    over = rows["class-c"]  # 22 students x $10.00 = $220, prepaid $250 assigned to this year
    expected = (Decimal("220.00"), Decimal("250.00"), Decimal("-30.00"))
    assert (over.allocation, over.paid, over.remainder) == expected
    assert over.over_budget and classroom.over_budget == (over,)
    assert classroom.remaining_total == Decimal("320.00")  # 160 + 120 - 30 + 70
    assert classroom.allocation_total == Decimal("700.00")
    # The adopted classroom envelope is shown beside the allocations, never scaled to them.
    assert classroom.classroom_budget == Decimal("500.00")
    assert classroom.allocation_difference == Decimal("200.00")
    payload = json.loads(canonical_json_bytes(over.to_dict()))
    assert payload["remainder"] == "-30.00" and payload["over_budget"] is True


def test_rows_outside_the_school_year_to_date_stay_explicit(tmp_path: Path) -> None:
    classroom = _facts(tmp_path)
    excluded = {item.reason: item for item in classroom.excluded}
    assert set(excluded) == {"after_as_of", "other_school_year"}
    assert (excluded["after_as_of"].rows, excluded["after_as_of"].amount) == (1, Decimal("30.00"))
    assert excluded["after_as_of"].record_keys == (
        classroom_ledger_row(CLASSROOM_LATER).record_key,
    )
    assert (excluded["other_school_year"].rows, excluded["other_school_year"].amount) == (
        1,
        Decimal("40.00"),
    )
    # A June prepayment the ledger assigns to this school year counts in it.
    prepaid = _payment(classroom, CLASSROOM_PREPAID)
    assert prepaid.payment_date.isoformat() == "2030-06-20" and prepaid.fiscal_year == 2031
    # The non-classroom category is never classroom spending.
    assert all(p.category == CLASSROOM_CATEGORY for p in classroom.payments)


def test_a_period_allocation_moves_one_exact_row_and_keeps_both_years(tmp_path: Path) -> None:
    document = classroom_planning_document()
    prior = classroom_ledger_row(CLASSROOM_PRIOR_YEAR)
    document["period_allocations"] = [
        {
            "source_record_key": prior.record_key,
            "source_revision_hash": prior.revision_hash,
            "fiscal_year": 2031,
            "evidence": "fictional invoice dated for the new year",
        }
    ]
    classroom = _facts(tmp_path, document)
    moved = _payment(classroom, CLASSROOM_PRIOR_YEAR)
    assert (moved.source_fiscal_year, moved.fiscal_year) == (2030, 2031)
    assert "other_school_year" not in {item.reason for item in classroom.excluded}
    assert classroom.source_total == Decimal("435.50")


def test_a_period_allocation_of_a_journal_target_is_a_conflict(tmp_path: Path) -> None:
    document = classroom_planning_document()
    prior = classroom_ledger_row(CLASSROOM_PRIOR_YEAR)
    document["period_allocations"] = [
        {
            "source_record_key": prior.record_key,
            "source_revision_hash": prior.revision_hash,
            "fiscal_year": 2031,
            "evidence": "fictional",
        }
    ]
    scenario = Scenario(tmp_path / "world", planning=document, bundle=classroom_bundle())
    capture_set, _, bundle = scenario.inputs()
    report = scenario.facts()
    with pytest.raises(FactsError) as caught:
        planning.classroom_facts(
            capture_set.planning,
            report.periods.school,
            bundle,
            report.budget.lines,
            journal_targets=[prior.record_key],
        )
    assert caught.value.code == "period_allocation_conflict"
    assert prior.record_key not in str(caught.value)


def test_allocations_that_do_not_add_up_to_the_payment_fail(tmp_path: Path) -> None:
    document = classroom_planning_document()
    document["payment_allocations"][1]["amount"] = "29.99"
    with pytest.raises(FactsError) as caught:
        _facts(tmp_path, document)
    assert caught.value.code == "payment_allocation_mismatch"
    assert "29.99" not in str(caught.value) and "90" not in str(caught.value)


def test_a_stale_allocation_leaves_its_row_unassigned_and_visible(tmp_path: Path) -> None:
    document = classroom_planning_document()
    for item in document["payment_allocations"]:
        item["source_revision_hash"] = "0" * 64  # the row was edited after the split
    classroom = _facts(tmp_path, document)
    shared = _payment(classroom, CLASSROOM_SHARED)
    assert shared.assignments == () and shared.unassigned == Decimal("90.00")
    findings = {f.code: f.count for f in classroom.findings}
    assert findings["payment_allocation_unmatched"] == 2
    assert "allocations_unmatched" in classroom.reasons
    assert classroom.source_total == classroom.assigned_total + classroom.unassigned_total


def test_an_allocation_of_a_row_after_the_as_of_date_is_counted_not_applied(
    tmp_path: Path,
) -> None:
    document = classroom_planning_document()
    later = classroom_ledger_row(CLASSROOM_LATER)
    document["payment_allocations"].append(
        {
            "source_record_key": later.record_key,
            "source_revision_hash": later.revision_hash,
            "class_id": "class-a",
            "amount": "30.00",
            "evidence": "fictional early split",
        }
    )
    classroom = _facts(tmp_path, document)
    assert {f.code: f.count for f in classroom.findings}["payment_allocation_out_of_scope"] == 1
    assert "allocations_unmatched" not in classroom.reasons
    assert later.record_key not in {p.record_key for p in classroom.payments}
    assert _by_id(classroom)["class-a"].paid == Decimal("40.00")


def test_absent_planning_or_another_school_year_is_unavailable(tmp_path: Path) -> None:
    absent = Scenario(tmp_path / "absent").facts().classroom
    assert absent is not None
    assert (absent.status, absent.reasons) == ("unavailable", ("planning_absent",))
    assert absent.classes == () and absent.source_total is None
    other = _facts(tmp_path / "other", classroom_planning_document(fiscal_year=2030))
    assert (other.status, other.reasons) == ("unavailable", ("planning_year_mismatch",))
    assert other.planning_sha256 is not None and other.allocation_total is None


def test_without_an_academic_ledger_allocations_stand_and_paid_is_unknown(tmp_path: Path) -> None:
    document = classroom_planning_document(allocations=[])
    document["bindings"] = []
    classroom = _facts(tmp_path, document)
    assert classroom.status == "partial" and "academic_ledger_absent" in classroom.reasons
    assert classroom.allocation_total == Decimal("700.00") and classroom.source_total is None
    assert all(row.paid is None and row.remainder is None for row in classroom.classes)


def test_an_unknown_classroom_budget_is_a_finding_never_zero(tmp_path: Path) -> None:
    budget = [row for row in BUDGET_ROWS if not (row[0] == "2031" and row[7] == CLASSROOM_CATEGORY)]
    budget.append(_budget_row("2031", "expense", "proposed", "", CLASSROOM_CATEGORY))
    classroom = _facts(tmp_path, budget=budget)
    assert classroom.classroom_budget is None and classroom.allocation_difference is None
    assert "classroom_budget_unknown" in {f.code for f in classroom.findings}


def test_short_ledger_coverage_makes_the_classroom_facts_partial(tmp_path: Path) -> None:
    document = classroom_planning_document()
    document["bindings"][0]["coverage_end"] = "2030-07-31"
    classroom = _facts(tmp_path, document)
    assert "ledger_coverage_partial" in classroom.reasons and classroom.status == "partial"


def test_classroom_payload_has_its_own_version_and_exact_cents(tmp_path: Path) -> None:
    classroom = _facts(tmp_path)
    payload = json.loads(canonical_json_bytes(classroom.to_dict()))
    assert payload["schema_version"] == CLASSROOM_SCHEMA_VERSION == 1
    assert set(payload) == {
        "schema_version",
        "status",
        "reasons",
        "fiscal_year",
        "as_of",
        "planning_sha256",
        "planning_input_sha256",
        "ledger_sha256",
        "ledger_coverage_start",
        "ledger_coverage_end",
        "roster_complete",
        "roster_as_of",
        "classes",
        "payments",
        "source_total",
        "assigned_total",
        "unassigned_total",
        "allocation_total",
        "classroom_budget",
        "allocation_difference",
        "remaining_total",
        "issued",
        "issued_total",
        "purchases",
        "excluded",
        "findings",
    }
    assert payload["source_total"] == "395.50" and payload["unassigned_total"] == "15.50"
    assert payload["fiscal_year"] == 2031 and payload["as_of"] == "2030-08-15"
    assert payload["classes"][0]["per_student_amount"] == "10.00"
    # The complete rows stay in the private record: every payment with its identity.
    assert {p["record_key"] for p in payload["payments"]} == {
        p.record_key for p in classroom.payments
    }
    replaced = dataclasses.replace(classroom, status="complete")
    assert json.loads(canonical_json_bytes(replaced.to_dict()))["status"] == "complete"


# --------------------------------------------------------------------------------------
# Rule 9: partial inputs give partial observed subtotals, never definitive comparisons
# --------------------------------------------------------------------------------------

# The fictional ledger without its one reference-less row: every payment is assigned, so
# the classroom facts are complete.
_COMPLETE_ROWS = [row for row in CLASSROOM_LEDGER_ROWS if row is not CLASSROOM_NO_REFERENCE]


def _allocation_world(case: str) -> dict[str, Any]:
    """The planning document of one allocation-completeness case (complete rows)."""
    document = classroom_planning_document(rows=_COMPLETE_ROWS, roster_complete=case != "roster")
    if case == "rates":
        document["classes"][1]["student_count"] = None
        document["classes"][2]["per_student_amount"] = None
    return document


@pytest.mark.parametrize(
    ("case", "total", "gaps", "difference"),
    [
        ("complete", 700, (), 200),
        ("rates", 300, ("allocation_missing",), None),
        ("roster", 700, ("roster_incomplete",), None),
    ],
    ids=["complete", "rates", "roster"],
)
def test_the_allocation_difference_needs_a_complete_allocation_total(
    tmp_path: Path, case: str, total: int, gaps: tuple[str, ...], difference: int | None
) -> None:
    """The allocation total is shown in every case, but a partial one (an enrollment or a
    rate missing, or an incomplete roster) is a partial observed subtotal: no difference
    from the adopted budget is displayed for it (rule 9)."""
    classroom = _facts(tmp_path, _allocation_world(case), rows=_COMPLETE_ROWS)
    shown = planning.classroom_display(classroom, listed=6)
    assert classroom.status == ("complete" if case == "complete" else "partial")
    assert shown.allocation_total == total and shown.classroom_budget == 500
    assert shown.allocation_gaps == gaps and shown.allocation_difference == difference
    # The remaining group rests on the same allocations, so it is partial with them.
    assert shown.remaining_gaps == gaps and shown.paid_gaps == ()
    # The machine record keeps the known allocations' cents difference beside its reasons.
    assert classroom.allocation_difference == Decimal(total - 500)


@pytest.mark.parametrize(
    ("case", "reason"),
    [("coverage", "ledger_coverage_partial"), ("unreadable", "rows_unreadable")],
    ids=["coverage", "unreadable"],
)
def test_partial_paid_inputs_leave_paid_and_remaining_partial(
    tmp_path: Path, case: str, reason: str
) -> None:
    rows = list(_COMPLETE_ROWS)
    if case == "unreadable":
        rows.append(["", "Example undated order", "-7.00", CLASSROOM_CATEGORY, "2031", "EX-8", ""])
    document = classroom_planning_document(rows=rows)
    if case == "coverage":
        document["bindings"][0]["coverage_end"] = "2030-07-31"
    classroom = _facts(tmp_path, document, rows=rows)
    shown = planning.classroom_display(classroom, listed=6)
    assert classroom.reasons == (reason,)
    assert shown.paid_gaps == shown.remaining_gaps == (reason,) and shown.allocation_gaps == ()
    # The allocation total is complete, so its difference is still stated.
    assert shown.allocation_difference == 200


def test_unassigned_payments_leave_only_the_remaining_group_partial(
    fictional_classroom: ClassroomFacts,
) -> None:
    shown = planning.classroom_display(fictional_classroom, listed=6)
    assert fictional_classroom.reasons == ("payments_unassigned",)
    assert (shown.allocation_gaps, shown.paid_gaps) == ((), ())
    assert shown.remaining_gaps == ("payments_unassigned",)
    assert shown.allocation_difference == 200


def test_without_a_classroom_category_spending_is_unknown_never_zero(tmp_path: Path) -> None:
    document = classroom_planning_document()
    document["classroom_categories"] = []
    classroom = _facts(tmp_path, document)
    assert classroom.status == "partial" and classroom.reasons == ("classroom_categories_absent",)
    # The ledger was captured, but no row can be classroom spending: unknown, never $0.
    assert classroom.ledger_sha256 is not None and classroom.source_total is None
    assert all(row.paid is None and row.remainder is None for row in classroom.classes)
    assert classroom.allocation_total == Decimal("700.00") and classroom.payments == ()
    shown = planning.classroom_display(classroom, listed=6)
    assert (shown.paid_total, shown.remaining_total, shown.issued_total) == (None, None, None)
    assert (shown.allocation_gaps, shown.paid_gaps, shown.remaining_gaps) == ((), (), ())
    payload = json.loads(canonical_json_bytes(classroom.to_dict()))
    assert payload["source_total"] is None


def test_without_a_captured_ledger_no_allocation_is_unmatched(tmp_path: Path) -> None:
    """No ledger was searched, so neither the payment allocations nor a period allocation
    count as unmatched; with the ledger captured, the same period allocation of a row that
    is not in it does."""
    document = classroom_planning_document()
    document["period_allocations"] = [
        {
            "source_record_key": classroom_ledger_row(CLASSROOM_LATER).record_key,
            "source_revision_hash": "0" * 64,
            "fiscal_year": 2031,
            "evidence": "fictional",
        }
    ]
    assert document["payment_allocations"]
    captured = _facts(tmp_path / "captured", document)
    assert {f.code: f.count for f in captured.findings}["period_allocation_unmatched"] == 1
    document["bindings"] = []
    classroom = _facts(tmp_path / "absent", document)
    assert classroom.reasons == ("academic_ledger_absent",)
    codes = {f.code for f in classroom.findings}
    assert not codes & {"payment_allocation_unmatched", "period_allocation_unmatched"}
    assert "allocations_unmatched" not in classroom.reasons
