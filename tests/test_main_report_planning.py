"""Classroom Budgets facts through the production capture and facts callers (fictional data).

Every case drives fake workbooks through :func:`sources.capture` (the board-planning input is a
fictional private JSON file beside a fictional config) and :func:`facts.build_from`, which calls
:func:`planning.classroom_facts`. Expected amounts are independent Decimal arithmetic over the
fictional ledger rows in ``tests.conftest`` (:data:`CLASSROOM_LEDGER_ROWS`), never the code's
own totals. Identities are fictional placeholders only.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from np_finance.main_reports import planning
from np_finance.main_reports.facts import FactsError
from np_finance.main_reports.models import (
    ClassroomFacts,
    ClassroomPayment,
    ReportFacts,
    canonical_json_bytes,
    is_valid_record_key,
)
from tests.conftest import (
    CLASSROOM_CHECK,
    CLASSROOM_CLASSES,
    CLASSROOM_LEDGER_ROWS,
    CLASSROOM_SHARED,
    PAYMENT_REFERENCE,
    PLANNING_LEDGER_HEADER,
    Scenario,
    _bundle_payload,
    _item,
    _record_payment,
    _ticket,
    classroom_class,
    classroom_document,
    planning_binding,
    planning_document,
)

D = Decimal
ZERO = D("0.00")
SHARED_REFERENCE = "EX-CHK-3001"
PAID_TICKET_KEY = f"submission:v1:{1:064x}"  # the fixture's paid NEW-01 request (reference 2001)


def _classroom(
    tmp_path: Path,
    document: Mapping[str, Any] | None = None,
    *,
    ledger: Sequence[Sequence[str]] = CLASSROOM_LEDGER_ROWS,
    bundle: dict[str, Any] | None = None,
) -> tuple[ClassroomFacts, Scenario]:
    scenario = Scenario(
        tmp_path,
        planning=classroom_document() if document is None else document,
        planning_ledger=ledger,
        bundle=bundle,
    )
    report = scenario.facts()
    assert report.classroom is not None
    return report.classroom, scenario


def _rebuild(scenario: Scenario, document: Mapping[str, Any]) -> ClassroomFacts:
    """Rewrite the private input and recapture through the production path."""
    assert scenario.planning_path is not None
    scenario.planning_path.write_text(json.dumps(document), encoding="utf-8")
    report = scenario.facts()
    assert report.classroom is not None
    return report.classroom


def _payment(classroom: ClassroomFacts, description: str) -> ClassroomPayment:
    (found,) = [p for p in classroom.payments if p.description == description]
    return found


def _paid(classroom: ClassroomFacts) -> dict[str, Decimal | None]:
    return {row.class_id: row.paid for row in classroom.classes}


def _allocation(
    payment: ClassroomPayment, class_id: str, amount: str, evidence: str = "fictional split"
) -> dict[str, Any]:
    return {
        "source_record_key": payment.ref.record_key,
        "source_revision_hash": payment.ref.revision_hash,
        "class_id": class_id,
        "amount": amount,
        "evidence": evidence,
    }


def _ledger(*rows: Sequence[str]) -> list[list[str]]:
    return [list(PLANNING_LEDGER_HEADER), *(list(row) for row in rows)]


def _row(day: str, description: str, amount: str, **fields: str) -> list[str]:
    return [
        day,
        description,
        amount,
        fields.get("category", "Classroom Supplies"),
        fields.get("year", "2031"),
        fields.get("reference", ""),
        fields.get("payee", ""),
    ]


# --------------------------------------------------------------------------------------
# Posted payments: attribution and conservation
# --------------------------------------------------------------------------------------


def test_source_payments_reconcile_to_assigned_plus_unassigned(tmp_path: Path) -> None:
    classroom, _ = _classroom(tmp_path)
    assert classroom.status == "complete"
    assert classroom.fiscal_year == 2031
    # Independent arithmetic over the fictional rows in the school year through Aug 15:
    # art 60.00 (payee A), prepaid workbooks 30.00 (payee B, Jun 25), shared rug 90.00,
    # unassigned 12.50 and the 2001 check 20.00. Excluded: the field trip (not classroom),
    # the Aug 20 row (after the as-of date) and the FY2030 carryover (other year).
    expected_total = D("60.00") + D("30.00") + D("90.00") + D("12.50") + D("20.00")
    assert classroom.source_total == expected_total
    assert classroom.assigned == D("90.00")
    assert classroom.unassigned == D("90.00") + D("12.50") + D("20.00")
    assert classroom.assigned + classroom.unassigned == classroom.source_total
    assert sum((row.paid or ZERO for row in classroom.classes), ZERO) == classroom.assigned
    assert _paid(classroom) == {"class-a": D("60.00"), "class-b": D("30.00"), "class-c": ZERO}
    assert dict(classroom.excluded) == {
        "after_as_of": 1,
        "other_fiscal_year": 1,
        "not_classroom": 1,
    }
    for payment in classroom.payments:
        parts = sum((item.amount for item in payment.assignments), ZERO)
        assert parts + payment.unassigned == payment.amount
        assert is_valid_record_key(payment.ref.record_key)
        assert payment.ref.record_key.startswith(f"v1:{planning.PLANNING_LEDGER_ALIAS}:")
    prepaid = _payment(classroom, "Example prepaid workbooks")
    assert prepaid.prepaid and prepaid.fiscal_year == 2031  # paid before July, kept in FY2031
    assert prepaid.assignments[0].basis == "payee_alias"
    # Allocations are enrollment times rate: 20, 18 and 12 students at $5.00.
    assert {row.class_id: row.allocation for row in classroom.classes} == {
        "class-a": D("100.00"),
        "class-b": D("90.00"),
        "class-c": D("60.00"),
    }
    assert classroom.allocated == D("250.00") and classroom.allocation_complete
    # The adopted classroom envelope is shown with its difference, never used to scale.
    assert classroom.adopted_envelope == D("500.00")
    assert classroom.envelope_difference == D("250.00")
    labels = [row.label for row in classroom.classes]
    assert labels == [
        "Example Teacher A",
        "Example Teacher B · class-b",
        "Example Teacher B · class-c",
    ]
    assert {(f.code, f.count) for f in classroom.findings} == {("payment_unassigned", 3)}


def test_shared_and_check_allocations_never_duplicate_spend(tmp_path: Path) -> None:
    first, scenario = _classroom(tmp_path)
    shared = _payment(first, CLASSROOM_SHARED)
    check = _payment(first, CLASSROOM_CHECK)
    document = classroom_document(
        payment_allocations=[
            _allocation(shared, "class-a", "30.00"),
            _allocation(shared, "class-b", "30.00"),
            _allocation(shared, "class-c", "30.00"),
            _allocation(check, "class-c", "20.00", "fictional check stub"),
        ]
    )
    classroom = _rebuild(scenario, document)
    assert classroom.source_total == first.source_total  # a split never adds spend
    assert classroom.unassigned == D("12.50")
    assert classroom.assigned == first.source_total - D("12.50")
    assert _paid(classroom) == {
        "class-a": D("60.00") + D("30.00"),
        "class-b": D("30.00") + D("30.00"),
        "class-c": D("30.00") + D("20.00"),
    }
    split = _payment(classroom, CLASSROOM_SHARED)
    assert [item.class_id for item in split.assignments] == ["class-a", "class-b", "class-c"]
    assert {item.basis for item in split.assignments} == {"payment_allocation"}
    assert split.unassigned == ZERO
    # The shared row is one payment, listed once per class it was split to.
    assert sum(1 for p in classroom.payments if p.description == CLASSROOM_SHARED) == 1
    keys = [key for row in classroom.classes for key, _, _ in row.payments]
    assert keys.count(split.ref.record_key) == 3
    # The 2001 check is posted, so the request it paid is linked, never also "issued".
    assert _payment(classroom, CLASSROOM_CHECK).linked_review_keys == (PAID_TICKET_KEY,)
    assert classroom.issued_unposted == ()
    assert not [f for f in classroom.findings if f.code == "payment_unassigned" and f.count > 1]


def test_one_check_paying_two_requests_counts_its_spend_once(tmp_path: Path) -> None:
    """Two paid requests recorded with the shared row's exact check reference both link to
    that one posted row: the spend is counted once and neither request is "issued"."""
    bundle = _bundle_payload()
    for order, ref in ((801, "P-801"), (802, "P-802")):
        ticket = _ticket(
            order,
            ref,
            "legacy",
            "2030-07-28",
            [_item(f"{ref.lower()}:line:1", 1, "2030-07-27", "45.00", "A", "Classroom Supplies")],
            status="A",
            decision="APPROVED",
        )
        ticket["source_evidence_sha256"] = f"{order % 16:x}" * 64
        bundle["tickets"].append(ticket)
        _record_payment(bundle, ticket, "2030-08-01", SHARED_REFERENCE, f"{order % 16:x}")
    classroom, _ = _classroom(tmp_path, bundle=bundle)
    shared = _payment(classroom, CLASSROOM_SHARED)
    assert shared.amount == D("90.00")
    assert shared.linked_review_keys == ("legacy:v1:p-801", "legacy:v1:p-802")
    assert classroom.issued_unposted == ()
    assert classroom.source_total == D("212.50")
    purchases = {p.ticket_ref: p for p in classroom.purchases}
    assert purchases["P-801"].posted and purchases["P-802"].posted


def test_issued_but_unposted_payments_are_separate_and_never_counted_twice(
    tmp_path: Path,
) -> None:
    without_check = [row for row in CLASSROOM_LEDGER_ROWS if row[1] != CLASSROOM_CHECK]
    issued, _ = _classroom(tmp_path / "issued", ledger=without_check)
    posted, _ = _classroom(tmp_path / "posted")
    # Not yet posted: the request paid by check 2001 is shown separately (its classroom item
    # dated in the school year, $20.00) and is not in posted spending.
    (entry,) = issued.issued_unposted
    assert entry.review_key == PAID_TICKET_KEY and entry.reference == PAYMENT_REFERENCE
    assert entry.amount == D("20.00") and issued.issued_total == D("20.00")
    assert issued.source_total == D("192.50")
    assert ("reimbursement_issued_not_posted", 1) in {(f.code, f.count) for f in issued.findings}
    # Once posted, it is posted spending only: the issued list is empty.
    assert posted.issued_unposted == () and posted.issued_total == ZERO
    assert posted.source_total == issued.source_total + D("20.00")


def test_payment_allocations_that_do_not_sum_to_their_row_are_refused(tmp_path: Path) -> None:
    first, scenario = _classroom(tmp_path)
    shared = _payment(first, CLASSROOM_SHARED)
    document = classroom_document(
        payment_allocations=[
            _allocation(shared, "class-a", "30.00"),
            _allocation(shared, "class-b", "30.00"),
        ]
    )
    assert scenario.planning_path is not None
    scenario.planning_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(FactsError) as caught:
        scenario.facts()
    assert caught.value.code == "payment_allocation_mismatch"
    assert "30.00" not in str(caught.value) and CLASSROOM_SHARED not in str(caught.value)


def test_a_stale_allocation_leaves_its_row_visibly_unassigned(tmp_path: Path) -> None:
    first, scenario = _classroom(tmp_path)
    shared = _payment(first, CLASSROOM_SHARED)
    stale = _allocation(shared, "class-a", "90.00")
    stale["source_revision_hash"] = "0" * 64  # an earlier revision of the row
    classroom = _rebuild(scenario, classroom_document(payment_allocations=[stale]))
    assert _payment(classroom, CLASSROOM_SHARED).unassigned == D("90.00")
    assert ("payment_allocation_unused", 1) in {(f.code, f.count) for f in classroom.findings}
    assert classroom.source_total == first.source_total


def test_identical_rows_are_kept_and_keys_survive_reordering(tmp_path: Path) -> None:
    twin = _row("7/22/2030", "Example identical supplies", "-7.00", payee="Example Payee A")
    rows = [twin, list(twin), _row("7/23/2030", "Example other supplies", "-3.00")]
    first, _ = _classroom(tmp_path / "a", ledger=_ledger(*rows))
    second, _ = _classroom(tmp_path / "b", ledger=_ledger(*reversed(rows)))
    twins = [p for p in first.payments if p.description == "Example identical supplies"]
    assert len(twins) == 2  # never deduplicated by amount or description
    assert len({p.ref.record_key for p in twins}) == 2
    assert {p.ref.record_key.rsplit(":", 1)[1] for p in twins} == {"0", "1"}
    assert first.source_total == D("17.00") and _paid(first)["class-a"] == D("14.00")
    assert sorted(p.ref.record_key for p in first.payments) == sorted(
        p.ref.record_key for p in second.payments
    )


def test_a_period_allocation_moves_one_exact_row_into_the_school_year(tmp_path: Path) -> None:
    first, scenario = _classroom(tmp_path)
    assert all(p.description != "Example prior-year carryover" for p in first.payments)
    # The FY2030-labelled row is not in the facts, so its key comes from the ledger reader.
    reference = {item.role: item for item in scenario.harness.capture().planning.references}  # type: ignore[union-attr]
    ledger = planning.read_academic_ledger(reference["academic_ledger"])
    (carry,) = [row for row in ledger.rows if row.description == "Example prior-year carryover"]
    document = classroom_document(
        period_allocations=[
            {
                "source_record_key": carry.ref.record_key,
                "source_revision_hash": carry.ref.revision_hash,
                "fiscal_year": 2031,
                "evidence": "fictional invoice period review",
            },
            {
                "source_record_key": carry.ref.record_key,
                "source_revision_hash": "1" * 64,
                "fiscal_year": 2031,
                "evidence": "fictional stale correction",
            },
        ]
    )
    classroom = _rebuild(scenario, document)
    moved = _payment(classroom, "Example prior-year carryover")
    assert (moved.source_fiscal_year, moved.fiscal_year) == (2030, 2031)
    assert moved.period_evidence == "fictional invoice period review"
    assert classroom.source_total == first.source_total + D("20.00")
    assert ("period_allocation_unused", 1) in {(f.code, f.count) for f in classroom.findings}


# --------------------------------------------------------------------------------------
# Allocations: actual enrollment times rate only
# --------------------------------------------------------------------------------------


def test_over_budget_class_shows_a_signed_negative_remainder(tmp_path: Path) -> None:
    classes = [dict(item) for item in CLASSROOM_CLASSES]
    classes[0]["student_count"] = 10  # $50.00 allocated, $60.00 posted
    classroom, _ = _classroom(tmp_path, classroom_document(classes=classes))
    (row,) = [row for row in classroom.classes if row.class_id == "class-a"]
    assert row.allocation == D("50.00") and row.paid == D("60.00")
    assert row.remainder == D("-10.00") and row.over_budget
    assert classroom.over_budget == (row,)
    # The signed remainders add up: -10.00 + 60.00 + 60.00.
    assert classroom.remaining == D("110.00")
    payload = row.to_dict()
    assert payload["remainder"] == "-10.00" and payload["over_budget"] is True


@pytest.mark.parametrize("case", ["no_planning", "empty_roster", "no_counts"])
def test_a_missing_roster_is_unavailable_never_an_equal_distribution(
    tmp_path: Path, case: str
) -> None:
    if case == "no_planning":
        report = Scenario(tmp_path).facts()
        classroom = report.classroom
        assert classroom is not None
        assert classroom.status == "unavailable" and not classroom.paid_available
        assert [f.code for f in classroom.findings] == ["planning_input_absent"]
    elif case == "empty_roster":
        document = classroom_document(classes=[])
        document["payee_aliases"] = []
        classroom, _ = _classroom(tmp_path, document)
        assert classroom.classes == ()
        assert classroom.unassigned == classroom.source_total == D("212.50")
        assert "roster_empty" in {f.code for f in classroom.findings}
    else:
        classes = [
            classroom_class(c["class_id"], c["teacher_label"], None) for c in CLASSROOM_CLASSES
        ]
        classroom, _ = _classroom(tmp_path, classroom_document(classes=classes))
        assert classroom.status == "partial"
        assert ("class_allocation_missing", 3) in {(f.code, f.count) for f in classroom.findings}
        assert all(row.allocation is None and row.remainder is None for row in classroom.classes)
    # Never the draft's equal split of the adopted classroom budget.
    assert classroom.allocated is None and classroom.remaining is None
    assert not classroom.allocation_complete
    equal_share = D("500.00") / 3
    assert all(row.allocation != equal_share.quantize(D("0.01")) for row in classroom.classes)


def test_ineligible_and_out_of_period_classes_get_no_allocation(tmp_path: Path) -> None:
    classes = [
        *CLASSROOM_CLASSES,
        classroom_class("class-d", "Example Specialist", 25, eligible=False),
        classroom_class(
            "class-e",
            "Example Former Teacher",
            20,
            effective_start="2029-08-01",
            effective_end="2030-06-30",
        ),
    ]
    classroom, _ = _classroom(tmp_path, classroom_document(classes=classes))
    ids = [row.class_id for row in classroom.classes]
    assert ids == ["class-a", "class-b", "class-c", "class-d"]  # class-e left the roster
    (specialist,) = [row for row in classroom.classes if row.class_id == "class-d"]
    assert specialist.allocation is None and not specialist.eligible
    assert classroom.allocated == D("250.00")  # ineligible classes never add an allocation
    assert ("class_outside_period", 1) in {(f.code, f.count) for f in classroom.findings}


def test_an_incomplete_roster_is_partial(tmp_path: Path) -> None:
    classroom, _ = _classroom(tmp_path, classroom_document(roster_complete=False))
    assert classroom.status == "partial" and not classroom.allocation_complete
    assert "roster_incomplete" in {f.code for f in classroom.findings}
    assert classroom.allocated == D("250.00")  # the known allocations stay visible


# --------------------------------------------------------------------------------------
# Missing and incomplete inputs
# --------------------------------------------------------------------------------------


def test_a_planning_input_for_another_year_is_unavailable(tmp_path: Path) -> None:
    # The Step 65 fixture input names FY2030; the fixture as-of date is in FY2031.
    document = planning_document(classroom_category="Classroom Supplies")
    classroom, _ = _classroom(tmp_path, document)
    assert classroom.status == "unavailable" and classroom.payments == ()
    assert [f.code for f in classroom.findings] == ["planning_year_mismatch"]


def test_unmapped_unreadable_and_uncovered_ledger_rows_are_partial(tmp_path: Path) -> None:
    rows = [
        _row("7/20/2030", "Example art supplies", "-60.00", payee="Example Payee A"),
        _row("7/21/2030", "Example mystery spend", "-5.00", category="Example Mystery"),
        _row("7/22/2030", "Example unreadable amount", "about ten"),
        _row("", "Example undated row", "-4.00"),
    ]
    document = classroom_document()
    planning_binding(document, "academic_ledger").update(coverage_start="2030-07-15")
    classroom, _ = _classroom(tmp_path, document, ledger=_ledger(*rows))
    found = {(f.code, f.count) for f in classroom.findings}
    assert classroom.status == "partial"
    assert {
        ("ledger_category_unmapped", 1),
        ("ledger_rows_unreadable", 2),
        ("ledger_coverage_partial", 1),
    } <= found
    assert not classroom.ledger_coverage_complete
    assert classroom.source_total == D("60.00")  # an unreadable row is never guessed


@pytest.mark.parametrize("case", ["no_ledger", "no_categories"])
def test_no_ledger_or_classroom_category_makes_posted_spending_unavailable(
    tmp_path: Path, case: str
) -> None:
    if case == "no_ledger":
        document = classroom_document()
        document["bindings"] = [b for b in document["bindings"] if b["role"] != "academic_ledger"]
        code = "academic_ledger_absent"
    else:
        document = classroom_document()
        document["classroom_categories"] = []
        document["central_case"]["classroom_budget_categories"] = []
        code = "classroom_categories_absent"
    classroom, _ = _classroom(tmp_path, document)
    assert classroom.status == "unavailable" and not classroom.paid_available
    assert classroom.findings[0].code == code
    # The roster's actual allocations stay visible; posted payments are unknown, not zero.
    assert classroom.allocated == D("250.00")
    assert all(row.paid is None and row.remainder is None for row in classroom.classes)


# --------------------------------------------------------------------------------------
# Evidence and serialization
# --------------------------------------------------------------------------------------


def test_larger_purchases_come_from_paid_dated_itemized_review_lines(tmp_path: Path) -> None:
    classroom, _ = _classroom(tmp_path)
    # Only the paid request's July line qualifies: its June line belongs to the prior year,
    # and unpaid, undated or declined lines never appear.
    assert [(p.ticket_ref, p.item_key, p.amount) for p in classroom.purchases] == [
        ("NEW-01", "new-01:line:2", D("20.00"))
    ]
    assert classroom.purchases[0].posted  # its 2001 check is on a posted ledger row


def test_classroom_facts_serialize_their_own_versioned_payload(tmp_path: Path) -> None:
    classroom, scenario = _classroom(tmp_path)
    payload = json.loads(canonical_json_bytes(classroom.to_dict()))
    assert payload["schema_version"] == 1 and payload["status"] == "complete"
    assert set(payload) == {
        "schema_version",
        "status",
        "fiscal_year",
        "roster_complete",
        "roster_as_of",
        "planning_sha256",
        "ledger_sha256",
        "ledger_coverage",
        "ledger_coverage_complete",
        "classes",
        "payments",
        "issued_unposted",
        "purchases",
        "adopted_envelope",
        "totals",
        "excluded",
        "findings",
    }
    assert payload["totals"] == {
        "source_total": "212.50",
        "assigned": "90.00",
        "unassigned": "122.50",
        "allocated": "250.00",
        "allocation_complete": True,
        "remaining": "160.00",
        "issued_unposted": "0.00",
        "envelope_difference": "250.00",
    }
    capture_set = scenario.harness.capture()
    assert capture_set.planning is not None
    assert payload["planning_sha256"] == capture_set.planning.sha256
    assert payload["classes"][0]["payments"][0]["amount"] == "60.00"
    report: ReportFacts = scenario.facts()
    whole = json.loads(canonical_json_bytes(report.to_dict()))
    assert whole["classroom"] == payload
    # Private payee text is used for attribution only and never serialized.
    assert "Example Payee" not in json.dumps(payload)


def test_a_corrupt_planning_capture_is_refused(tmp_path: Path) -> None:
    _, scenario = _classroom(tmp_path)
    capture_set = scenario.harness.capture()
    assert capture_set.planning is not None
    broken = dataclasses.replace(capture_set.planning, input_json="{")
    with pytest.raises(planning.PlanningError) as caught:
        planning.read_policy(broken)
    assert caught.value.code == "planning_policy_invalid"
