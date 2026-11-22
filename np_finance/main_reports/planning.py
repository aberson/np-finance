"""Pure board-planning calculations for the Main Report Set (CORE-BRIEFS).

The optional ``[main_reports.board_planning]`` capture (:class:`PlanningCapture`, Step 65)
holds the private planning document verbatim plus read-only captures of its supplemental
tabs. This module turns that capture into facts; it reads no workbook or file and changes
nothing. :func:`np_finance.main_reports.facts.build_from` is its production caller. Later
CORE-BRIEFS steps extend it (Budget Snapshot scenarios and projection, Treasurer Notes
placeholders); Step 66 adds the Classroom Budgets facts (:func:`classroom_facts`):

* **Allocations** are the roster's enrollment times its per-student rate for each eligible
  class effective in the school year. A missing count or rate leaves that allocation
  unavailable with its reason; an adopted total is never divided among classes.
* **Paid** is the posted academic-ledger spending of the school year through the as-of date
  in the declared classroom categories. Rows carry the project's record-key and revision-hash
  identities (:data:`ACADEMIC_LEDGER_ALIAS`); identical-looking rows stay distinct. A row
  reaches a classroom only through an evidence-backed ``payment_allocations`` split of that
  exact key and revision (shared purchases), or through the exact ``payee_aliases`` mapping
  of a row that carries an explicit payment reference. Everything else stays unassigned and
  visible, so assigned plus unassigned always equals the classroom spending. Matching never
  uses an amount alone, a normalized spelling or free text.
* **Issued, not yet matched to a posted payment** is the other side of one total partition
  of the paid classroom requests of the school year to date (D49, :func:`_partition`). A
  request is settled by exactly one of the rows that feed paid, through its exact recorded
  payment reference on that row or an applied ``payment_allocations`` entry of that exact
  row whose optional ``review_key`` names it, and is then counted in paid through that row
  only. Every other request (no posted row yet, a reference only on rows outside paid, no
  reference and no naming allocation, or more than one candidate row) is listed as issued
  with its :data:`~np_finance.main_reports.models.ISSUED_REASONS` reason and kept out of
  paid: never both, never neither. ``evidence`` is free text, never an identifier, and an
  allocation ``review_key`` that names no paid classroom request is a finding.
* **Larger purchases** come only from paid, dated, priced, approved review items of
  requests settled by one posted classroom payment.
* **Academic years** come from the ledger's own label in the D50 grammar (:func:`_year`) or
  an exact ``period_allocations`` entry, never from a payment date; an unreadable label
  leaves its row unmapped with a finding.

:func:`half_up` is the one display-rounding rule and :func:`display_parts` its
largest-remainder form (calculation rule 11): whole-dollar parts that add exactly to their
correctly rounded total. :func:`classroom_display` computes, once, every whole-dollar figure
the Classroom Budgets brief displays (D51). Errors are
:class:`~np_finance.main_reports.facts.FactsError` with value-free text.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from np_finance.main_reports.facts import (
    APPROVED_STATUS,
    BUDGET_LINE_TYPES,
    PAID_STATUS,
    RECORDED_PAYMENT_EVENT,
    FactsError,
)
from np_finance.main_reports.models import (
    ALLOCATION_STATES,
    ASSIGNMENT_BASES,
    CENT,
    CLASSROOM_EXCLUSIONS,
    CLASSROOM_STATUSES,
    EXPENSE_BUCKETS,
    ISSUED_REASONS,
    BudgetLine,
    ClassroomAssignment,
    ClassroomExclusion,
    ClassroomFacts,
    ClassroomPayment,
    ClassroomPurchase,
    ClassroomRow,
    EnteredNumber,
    FactIssue,
    FormulaCell,
    IssuedPayment,
    Period,
    PlanningCapture,
    PlanningReferenceCapture,
    content_hash,
    make_record_key,
    money_str,
)
from np_finance.main_reports.reconcile import reference_token
from np_finance.main_reports.sources import (
    CATEGORY_ROLES,
    PLANNING_ROLES,
    entered_matches,
    parse_money,
    parse_source_date,
    trim_trailing_blanks,
)
from np_finance.reimbursement_report import ReimbursementReport, ReviewItem, Ticket

__all__ = [
    # constants
    "ACADEMIC_LEDGER_ALIAS",
    "ACADEMIC_LEDGER_ROLE",
    "CLASSROOM_REASONS",
    "CLASSROOM_FINDINGS",
    # functions
    "half_up",
    "display_parts",
    "classroom_display",
    "planning_input",
    "ledger_rows",
    "read_ledger",
    "classroom_facts",
    # types
    "RosterClass",
    "PaymentAllocation",
    "PeriodAllocation",
    "CategoryRole",
    "PlanningInput",
    "LedgerRow",
    "ClassroomRowDisplay",
    "ClassroomDisplay",
]

# The record-key alias of academic-ledger rows: distinct from every bank-feed alias, so a
# planning row can never be mistaken for, or matched against, a reconciled transaction.
ACADEMIC_LEDGER_ALIAS = "planning-academic-ledger"
ACADEMIC_LEDGER_ROLE = PLANNING_ROLES[0]

# Why classroom facts are partial or unavailable (value-free codes).
CLASSROOM_REASONS: tuple[str, ...] = (
    "planning_absent",
    "planning_year_mismatch",
    "classroom_categories_absent",
    "academic_ledger_absent",
    "ledger_coverage_partial",
    "roster_absent",
    "roster_incomplete",
    "allocation_missing",
    "payments_unassigned",
    "rows_unreadable",
    "allocations_unmatched",
)
(
    _PLANNING_ABSENT,
    _PLANNING_YEAR_MISMATCH,
    _CATEGORIES_ABSENT,
    _LEDGER_ABSENT,
    _LEDGER_COVERAGE_PARTIAL,
    _ROSTER_ABSENT,
    _ROSTER_INCOMPLETE,
    _ALLOCATION_MISSING,
    _PAYMENTS_UNASSIGNED,
    _ROWS_UNREADABLE,
    _ALLOCATIONS_UNMATCHED,
) = CLASSROOM_REASONS
# The reasons that leave a shown classroom total a partial observed subtotal (rule 9), so a
# figure or comparison resting on it is never stated as definitive: the allocation total (the
# roster, an enrollment or a rate incomplete), the paid total (ledger coverage short of the
# as-of date, or rows left out as unreadable) and the remaining group (either of those, or a
# payment not assigned to its classroom).
_ALLOCATION_GAPS = frozenset({_ROSTER_INCOMPLETE, _ALLOCATION_MISSING})
_PAID_GAPS = frozenset({_LEDGER_COVERAGE_PARTIAL, _ROWS_UNREADABLE})
_REMAINING_GAPS = _ALLOCATION_GAPS | _PAID_GAPS | {_PAYMENTS_UNASSIGNED, _ALLOCATIONS_UNMATCHED}

# Countable classroom findings (value-free; ``FactIssue.count`` carries the number).
CLASSROOM_FINDINGS: tuple[str, ...] = (
    "classroom_payment_unassigned",
    "payment_allocation_unmatched",
    "payment_allocation_out_of_scope",
    "period_allocation_unmatched",
    "payment_allocation_review_key_unknown",
    "payment_allocation_review_key_out_of_scope",
    "ledger_duplicate_identity",
    "ledger_category_unresolved",
    "ledger_year_unreadable",
    "ledger_amount_unverified",
    "issued_payment_no_reference",
    "issued_payment_ambiguous",
    "issued_payment_out_of_scope",
    "issued_payment_amount_mismatch",
    "classroom_budget_unknown",
)
(
    _FINDING_UNASSIGNED,
    _FINDING_ALLOCATION_UNMATCHED,
    _FINDING_ALLOCATION_OUT_OF_SCOPE,
    _FINDING_PERIOD_UNMATCHED,
    _FINDING_KEY_UNKNOWN,
    _FINDING_KEY_OUT_OF_SCOPE,
    _FINDING_DUPLICATE,
    _FINDING_CATEGORY,
    _FINDING_YEAR,
    _FINDING_UNVERIFIED,
    _FINDING_NO_REFERENCE,
    _FINDING_AMBIGUOUS,
    _FINDING_ISSUED_OUT_OF_SCOPE,
    _FINDING_AMOUNT_MISMATCH,
    _FINDING_BUDGET_UNKNOWN,
) = CLASSROOM_FINDINGS

_COMPLETE, _PARTIAL, _UNAVAILABLE = CLASSROOM_STATUSES
(
    _ALLOCATED,
    _NOT_ELIGIBLE,
    _OUTSIDE_YEAR,
    _ENROLLMENT_MISSING,
    _RATE_MISSING,
) = ALLOCATION_STATES
_BY_ALLOCATION, _BY_PAYEE = ASSIGNMENT_BASES
_NOT_POSTED, _REFERENCE_OUT_OF_SCOPE, _NO_REFERENCE, _AMBIGUOUS = ISSUED_REASONS
# The finding each issued reason adds (a request that simply has not posted adds none).
_ISSUED_FINDINGS: Mapping[str, str] = {
    _REFERENCE_OUT_OF_SCOPE: _FINDING_ISSUED_OUT_OF_SCOPE,
    _NO_REFERENCE: _FINDING_NO_REFERENCE,
    _AMBIGUOUS: _FINDING_AMBIGUOUS,
}
(
    _AFTER_AS_OF,
    _OTHER_YEAR,
    _YEAR_UNREADABLE,
    _UNDATED,
    _AMOUNT_UNREADABLE,
) = CLASSROOM_EXCLUSIONS
# Exclusions that make classroom spending incomplete (the other two are simply out of scope).
_UNREADABLE_EXCLUSIONS = frozenset({_YEAR_UNREADABLE, _UNDATED, _AMOUNT_UNREADABLE})
_CURRENT = EXPENSE_BUCKETS[1]
_EXPENSE_ROLE = CATEGORY_ROLES[2]
_EXPENSE_LINE = BUDGET_LINE_TYPES[1]
_ZERO = Decimal("0.00")
_ONE = Decimal(1)

# The academic-year label grammar (D50), matched against the whole trimmed cell: an ending
# year ``YYYY``, ``FY YYYY`` or ``FYYYYY`` (``FY`` in any case, at most one space), or a span
# ``YYYY-YY`` / ``YYYY-YYYY`` written with a hyphen, an en dash or a slash, whose end year is
# exactly its start year plus one. A label resolves to its ending year; anything else is
# unreadable (:func:`_year`). Never inferred from a payment date.
_YEAR = re.compile(r"(?:[Ff][Yy] ?)?([0-9]{4})")
_YEAR_SPAN = re.compile(r"([0-9]{4})[-\u2013/]([0-9]{2}|[0-9]{4})")


# --------------------------------------------------------------------------------------
# Display rounding (calculation and display contract, rule 11)
# --------------------------------------------------------------------------------------


def half_up(value: Decimal) -> int:
    """``value`` rounded once, half up, to a whole number (display only).

    The one rounding rule of every displayed whole-dollar figure and whole percent; the
    renderer imports it rather than restating it.
    """
    return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def _exact(value: Decimal) -> Decimal:
    """``value`` as exact cents (``display_parts_invalid`` for a sub-cent amount)."""
    try:
        return Decimal(money_str(value))
    except ValueError:
        raise FactsError("display_parts_invalid", "display parts must be exact cents") from None


def display_parts(parts: Sequence[Decimal], total: Decimal | None = None) -> tuple[list[int], int]:
    """Whole-dollar parts that add exactly to their correctly rounded total.

    ``parts`` are exact-cent amounts (signed amounts allowed); ``total`` defaults to their
    sum and, when given, must equal it. The total is rounded once, half up; each part starts
    from its floor and the parts with the largest cent remainders (ties in input order) take
    the missing dollars, so the displayed parts sum to the displayed total. A part never
    takes the opposite sign of its cents: the missing dollars number at most the parts with
    a nonzero cent remainder (the total moves the floors' sum by under half a dollar plus
    the remainders, each at most 99 cents), so a whole-dollar part keeps its value, a
    positive part shows zero or more and a negative part zero or less. Machine records keep
    cents: this is display only. Raises :class:`FactsError` (``display_parts_invalid``) for
    a sub-cent amount or parts that do not add up to ``total``.
    """
    cents = [_exact(part) for part in parts]
    exact = sum(cents, _ZERO)
    if total is not None and _exact(total) != exact:
        raise FactsError("display_parts_invalid", "display parts must add up to their total")
    whole = half_up(exact)
    floors = [int(value.quantize(_ONE, rounding=ROUND_FLOOR)) for value in cents]
    fractions = [value - floor for value, floor in zip(cents, floors, strict=True)]
    order = sorted(range(len(cents)), key=lambda index: (-fractions[index], index))
    for index in order[: whole - sum(floors)]:
        floors[index] += 1
    return floors, whole


@dataclass(frozen=True)
class ClassroomRowDisplay:
    """One roster classroom's displayed whole dollars (``None`` where the fact is unknown).

    ``remaining`` is this classroom's part of the remaining group (D51): one
    :func:`display_parts` call over the cents remainders against their kept total, so it
    never has the opposite sign of the cents remainder. It may differ from the displayed
    ``allocation`` less the displayed ``paid`` by at most one dollar.
    """

    class_id: str
    allocation: int | None
    paid: int | None
    remaining: int | None


@dataclass(frozen=True)
class ClassroomDisplay:
    """Every whole-dollar figure the Classroom Budgets brief displays (D51, rule 11).

    Computed once from :class:`~np_finance.main_reports.models.ClassroomFacts` by
    :func:`classroom_display`; the renderer and template print only these integers, so no
    print site rounds cents on its own and a figure shown in two places reads the same.

    Kept totals are rounded once from cents, half up: ``allocation_total``,
    ``classroom_budget``, ``paid_total`` (the facts' ``source_total``), ``purchase_total``
    and the single figure ``issued_total``. Each kept total's parts come from one
    :func:`display_parts` call against it: the classrooms' ``allocation``; the classrooms'
    ``paid`` plus ``unassigned_total``; ``purchases`` (the listed rows) plus ``other`` (the
    exact Other row, ``None`` when every purchase is listed). The remaining figures are
    their own group: ``remaining_total`` is the kept total of the cents remainders and each
    classroom's ``remaining`` its part from one :func:`display_parts` call over those
    remainders, so the bar labels add to the Remaining tile and a displayed remaining never
    contradicts its over-budget marker (unassigned payments belong to no classroom and
    reduce no remainder). Derived figures are differences of the displayed integers:
    ``allocation_difference`` (allocation total less budget), ``assigned_total`` (paid
    total less unassigned) and ``overrun`` (the negative ``remaining`` figures, negated and
    summed). ``classes`` follows the facts' classes; ``None`` is an unknown figure.

    ``allocation_gaps``, ``paid_gaps`` and ``remaining_gaps`` are the facts' reasons, in
    :data:`CLASSROOM_REASONS` order, that leave that shown total a partial observed
    subtotal (rule 9); each is empty when its total is complete or unknown. A comparison
    resting on a partial total is not definitive: ``allocation_difference`` is ``None``
    whenever ``allocation_gaps`` is not empty. ``issued_total`` is ``None`` when no
    classroom category is declared, so no request can be identified as a classroom one.
    """

    classes: tuple[ClassroomRowDisplay, ...]
    allocation_total: int | None
    classroom_budget: int | None
    allocation_difference: int | None
    paid_total: int | None
    assigned_total: int | None
    unassigned_total: int | None
    remaining_total: int | None
    overrun: int
    purchases: tuple[int, ...]
    other: int | None
    purchase_total: int
    issued_total: int | None
    allocation_gaps: tuple[str, ...]
    paid_gaps: tuple[str, ...]
    remaining_gaps: tuple[str, ...]


def _gaps(classroom: ClassroomFacts, total: int | None, gaps: frozenset[str]) -> tuple[str, ...]:
    """The facts' reasons in ``gaps`` (in their order) when ``total`` is shown, else none."""
    if total is None:
        return ()
    return tuple(reason for reason in classroom.reasons if reason in gaps)


def classroom_display(classroom: ClassroomFacts, *, listed: int) -> ClassroomDisplay:
    """The displayed whole dollars of ``classroom`` (pure; see :class:`ClassroomDisplay`).

    ``listed`` is how many of the largest purchases the page names; the rest form the exact
    Other row. Raises :class:`FactsError` (``display_parts_invalid``) when a kept total's
    parts do not add up to it, a broken facts invariant.
    """
    rows = classroom.classes
    allocations: dict[str, int] = {}
    allocation_total = None
    if classroom.allocation_total is not None:
        known = {row.class_id: row.allocation for row in rows if row.allocation is not None}
        parts, allocation_total = display_parts(list(known.values()), classroom.allocation_total)
        allocations = dict(zip(known, parts, strict=True))
    paid: dict[str, int] = {}
    paid_total = assigned_total = unassigned_total = None
    if classroom.source_total is not None:
        posted = {row.class_id: row.paid for row in rows if row.paid is not None}
        parts, paid_total = display_parts(
            [*posted.values(), classroom.unassigned_total], classroom.source_total
        )
        *class_parts, unassigned_total = parts
        paid = dict(zip(posted, class_parts, strict=True))
        assigned_total = paid_total - unassigned_total
    remainders = {row.class_id: row.remainder for row in rows if row.remainder is not None}
    remaining: dict[str, int] = {}
    remaining_total = None
    if remainders:
        parts, remaining_total = display_parts(list(remainders.values()), classroom.remaining_total)
        remaining = dict(zip(remainders, parts, strict=True))
    shown = tuple(
        ClassroomRowDisplay(
            class_id=row.class_id,
            allocation=allocations.get(row.class_id),
            paid=paid.get(row.class_id),
            remaining=remaining.get(row.class_id),
        )
        for row in rows
    )
    budget = None
    if classroom.classroom_budget is not None:
        budget = half_up(_exact(classroom.classroom_budget))
    allocation_gaps = _gaps(classroom, allocation_total, _ALLOCATION_GAPS)
    named, rest = classroom.purchases[:listed], classroom.purchases[listed:]
    parts, purchase_total = display_parts(
        [
            *(item.amount for item in named),
            *([sum((item.amount for item in rest), _ZERO)] if rest else []),
        ]
    )
    return ClassroomDisplay(
        classes=shown,
        allocation_total=allocation_total,
        classroom_budget=budget,
        allocation_difference=None
        if allocation_total is None or budget is None or allocation_gaps
        else allocation_total - budget,
        paid_total=paid_total,
        assigned_total=assigned_total,
        unassigned_total=unassigned_total,
        remaining_total=remaining_total,
        overrun=-sum(value for value in remaining.values() if value < 0),
        purchases=tuple(parts[: len(named)]),
        other=parts[len(named)] if rest else None,
        purchase_total=purchase_total,
        issued_total=None
        if _CATEGORIES_ABSENT in classroom.reasons
        else half_up(_exact(classroom.issued_total)),
        allocation_gaps=allocation_gaps,
        paid_gaps=_gaps(classroom, paid_total, _PAID_GAPS),
        remaining_gaps=_gaps(classroom, remaining_total, _REMAINING_GAPS),
    )


# --------------------------------------------------------------------------------------
# The planning document (already validated at capture; read here as a typed view)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterClass:
    class_id: str
    teacher_label: str
    student_count: int | None
    per_student_amount: Decimal | None
    effective_start: date
    effective_end: date
    eligible: bool


@dataclass(frozen=True)
class PaymentAllocation:
    """An evidence-backed reporting assignment of one exact source row to one class.

    ``amount`` is in spend terms (an outflow positive); the allocations of one row add up to
    that row's spend. ``review_key`` (optional, D49) is the exact review key of the paid
    request this row settles (see :func:`_partition`); the entry's ``evidence`` is free text,
    never parsed as an identifier, so it is not read here.
    """

    source_record_key: str
    source_revision_hash: str
    class_id: str
    amount: Decimal
    review_key: str | None = None


@dataclass(frozen=True)
class PeriodAllocation:
    source_record_key: str
    source_revision_hash: str
    fiscal_year: int


@dataclass(frozen=True)
class CategoryRole:
    source_category: str
    role: str
    budget_category: str


@dataclass(frozen=True)
class PlanningInput:
    """The typed view of one captured planning document (no amounts are cached in it)."""

    schema_version: int
    fiscal_year: int
    roster_complete: bool
    roster_as_of: date
    classes: tuple[RosterClass, ...]
    payee_aliases: Mapping[str, str]
    payment_allocations: tuple[PaymentAllocation, ...]
    category_roles: tuple[CategoryRole, ...]
    classroom_categories: frozenset[str]
    period_allocations: tuple[PeriodAllocation, ...]

    def role_of(self, source_category: str) -> CategoryRole | None:
        for item in self.category_roles:
            if item.source_category == source_category:
                return item
        return None

    def is_classroom(self, category: str) -> bool:
        """A ledger source category whose declared role is a classroom expense."""
        role = self.role_of(category)
        return (
            role is not None
            and role.role == _EXPENSE_ROLE
            and role.budget_category in self.classroom_categories
        )

    def is_classroom_item(self, category: str) -> bool:
        """A review item's category: a classroom budget category or a mapped source category."""
        return category in self.classroom_categories or self.is_classroom(category)


def _invalid(dotted: str) -> FactsError:
    # The capture validated this document; a type surprise here is a broken input contract.
    return FactsError("planning_input_invalid", f"{dotted}: unexpected shape after capture")


def _decimal(value: Any, dotted: str) -> Decimal:
    if not isinstance(value, str):
        raise _invalid(dotted)
    try:
        return Decimal(value)
    except InvalidOperation:
        raise _invalid(dotted) from None


def _iso(value: Any, dotted: str) -> date:
    if not isinstance(value, str):
        raise _invalid(dotted)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid(dotted) from None


def _str(value: Any, dotted: str) -> str:
    if not isinstance(value, str):
        raise _invalid(dotted)
    return value


def _items(data: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    raw = data.get(name, [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise _invalid(name)
    return raw


def planning_input(planning: PlanningCapture) -> PlanningInput:
    """The typed view of the capture's verbatim document (validated when it was captured)."""
    try:
        data = json.loads(planning.input_json.removeprefix("\ufeff"))
    except ValueError:
        raise _invalid("board_planning") from None
    if not isinstance(data, dict):
        raise _invalid("board_planning")
    classes: list[RosterClass] = []
    for index, item in enumerate(_items(data, "classes")):
        dotted = f"classes[{index}]"
        count = item.get("student_count")
        if count is not None and (isinstance(count, bool) or not isinstance(count, int)):
            raise _invalid(f"{dotted}.student_count")
        rate = item.get("per_student_amount")
        classes.append(
            RosterClass(
                class_id=_str(item.get("class_id"), f"{dotted}.class_id"),
                teacher_label=_str(item.get("teacher_label"), f"{dotted}.teacher_label"),
                student_count=count,
                per_student_amount=None
                if rate is None
                else _decimal(rate, f"{dotted}.per_student_amount"),
                effective_start=_iso(item.get("effective_start"), f"{dotted}.effective_start"),
                effective_end=_iso(item.get("effective_end"), f"{dotted}.effective_end"),
                eligible=item.get("eligible") is True,
            )
        )
    aliases = {
        _str(item.get("source_payee"), "payee_aliases"): _str(item.get("class_id"), "payee_aliases")
        for item in _items(data, "payee_aliases")
    }
    # ``review_key`` is optional but never null (the capture refuses null), so its presence,
    # not ``.get``, decides it: a present null stays a broken input contract.
    allocations = tuple(
        PaymentAllocation(
            source_record_key=_str(item.get("source_record_key"), "payment_allocations"),
            source_revision_hash=_str(item.get("source_revision_hash"), "payment_allocations"),
            class_id=_str(item.get("class_id"), "payment_allocations"),
            amount=_decimal(item.get("amount"), "payment_allocations"),
            review_key=_str(item["review_key"], "payment_allocations")
            if "review_key" in item
            else None,
        )
        for item in _items(data, "payment_allocations")
    )
    roles = tuple(
        CategoryRole(
            source_category=_str(item.get("source_category"), "category_roles"),
            role=_str(item.get("role"), "category_roles"),
            budget_category=_str(item.get("budget_category"), "category_roles"),
        )
        for item in _items(data, "category_roles")
    )
    periods: list[PeriodAllocation] = []
    for item in _items(data, "period_allocations"):
        year = item.get("fiscal_year")
        if isinstance(year, bool) or not isinstance(year, int):
            raise _invalid("period_allocations")
        periods.append(
            PeriodAllocation(
                source_record_key=_str(item.get("source_record_key"), "period_allocations"),
                source_revision_hash=_str(item.get("source_revision_hash"), "period_allocations"),
                fiscal_year=year,
            )
        )
    categories = data.get("classroom_categories", [])
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise _invalid("classroom_categories")
    roster_complete = data.get("roster_complete")
    if not isinstance(roster_complete, bool):
        raise _invalid("roster_complete")
    return PlanningInput(
        schema_version=planning.schema_version,
        fiscal_year=planning.fiscal_year,
        roster_complete=roster_complete,
        roster_as_of=_iso(data.get("roster_as_of"), "roster_as_of"),
        classes=tuple(classes),
        payee_aliases=aliases,
        payment_allocations=allocations,
        category_roles=roles,
        classroom_categories=frozenset(categories),
        period_allocations=tuple(periods),
    )


# --------------------------------------------------------------------------------------
# The academic ledger (verbatim capture -> identified rows)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerRow:
    """One non-blank academic-ledger data row with its identity and parsed fields.

    ``amount`` is the signed source amount (an expense negative), ``None`` when missing or
    unreadable; ``fiscal_year`` the parsed source academic-year label (``None`` when blank or
    unreadable); ``payment_date`` ``None`` when blank or unreadable. ``unverified`` marks a
    formula money cell whose computed value has no entered number to check.
    """

    record_key: str
    revision_hash: str
    row_number: int
    payment_date: date | None
    description: str
    amount: Decimal | None
    category: str
    fiscal_year: int | None
    payment_reference: str
    payee: str
    occurrence: int = 0
    unverified: bool = False

    @property
    def spend(self) -> Decimal | None:
        """The row as spending: an expense positive, a refund or reversal negative."""
        return None if self.amount is None else -self.amount


def _year(raw: str) -> int | None:
    """The ending year of a D50 academic-year label, ``None`` for any other label (see
    :data:`_YEAR`); surrounding whitespace is trimmed as for every ledger cell."""
    text = raw.strip()
    match = _YEAR.fullmatch(text)
    if match is not None:
        return int(match.group(1))
    span = _YEAR_SPAN.fullmatch(text)
    if span is None:
        return None
    start, end = int(span.group(1)), span.group(2)
    expected = start + 1
    if (len(end) == 4 and int(end) == expected) or (len(end) == 2 and int(end) == expected % 100):
        return expected
    return None


def _date(raw: str) -> date | None:
    try:
        return parse_source_date(raw)
    except ValueError:
        return None


@dataclass
class _Draft:
    row_number: int
    identity: tuple[str, ...]
    revision: str
    fields: dict[str, Any] = field(default_factory=dict)


def read_ledger(
    values: Sequence[Sequence[str]],
    header_rows: int,
    columns: Mapping[str, int],
    *,
    entered_numbers: Iterable[EnteredNumber] = (),
    formulas: Iterable[FormulaCell] = (),
) -> tuple[LedgerRow, ...]:
    """Identify and parse every non-blank data row of an academic-ledger grid.

    ``values`` is the whole captured grid (header rows included) and ``columns`` maps each
    bound logical field to its zero-based column. Record keys follow the project's
    ``v1:<alias>:<sha256-of-identity>:<occurrence>`` convention under
    :data:`ACADEMIC_LEDGER_ALIAS`; occurrences are ordered by revision hash (then row), so an
    unchanged multiset keeps its keys under any row order and identical-looking rows are never
    collapsed. A money cell whose entered number disagrees with its display is unreadable.
    """
    entered = {(cell.row, cell.column): cell.value for cell in entered_numbers}
    formula_cells = {(cell.row, cell.column) for cell in formulas}

    def cell(row: Sequence[str], name: str) -> str:
        position = columns.get(name)
        if position is None or position >= len(row):
            return ""
        return row[position]

    drafts: list[_Draft] = []
    for offset, row in enumerate(values[header_rows:]):
        if all(not text.strip() for text in row):
            continue
        row_number = header_rows + offset + 1
        raw_amount = cell(row, "amount")
        amount: Decimal | None
        unverified = False
        try:
            amount = parse_money(raw_amount)
        except ValueError as error:
            amount = None
            position = columns.get("amount")
            typed = entered.get((row_number - 1, position)) if position is not None else None
            if str(error) == "dash_placeholder" and typed is not None:
                amount = _ZERO if entered_matches(typed, _ZERO) else None
        else:
            position = columns.get("amount")
            if amount is not None and position is not None:
                typed = entered.get((row_number - 1, position))
                if typed is not None and not entered_matches(typed, amount):
                    amount = None  # a display format hides the entered value
                elif typed is None and (row_number - 1, position) in formula_cells:
                    unverified = True
        payment_date = _date(cell(row, "payment_date"))
        description = cell(row, "description").strip()
        reference = cell(row, "payment_reference").strip()
        identity = (
            ACADEMIC_LEDGER_ROLE,
            payment_date.isoformat() if payment_date else cell(row, "payment_date").strip(),
            description,
            money_str(amount) if amount is not None else raw_amount.strip(),
            reference,
        )
        drafts.append(
            _Draft(
                row_number=row_number,
                identity=identity,
                revision=content_hash(
                    {
                        "alias": ACADEMIC_LEDGER_ALIAS,
                        "kind": ACADEMIC_LEDGER_ROLE,
                        "values": list(trim_trailing_blanks(row)),
                    }
                ),
                fields={
                    "payment_date": payment_date,
                    "description": description,
                    "amount": amount,
                    "category": cell(row, "category").strip(),
                    "fiscal_year": _year(cell(row, "fiscal_year")),
                    "payment_reference": reference,
                    "payee": cell(row, "payee").strip(),
                    "unverified": unverified,
                },
            )
        )
    groups: dict[tuple[str, ...], list[_Draft]] = defaultdict(list)
    for draft in drafts:
        groups[draft.identity].append(draft)
    keyed: dict[int, tuple[str, int]] = {}
    for shared, members in groups.items():
        ordered = sorted(members, key=lambda d: (d.revision, d.row_number))
        for occurrence, draft in enumerate(ordered):
            keyed[draft.row_number] = (
                make_record_key(ACADEMIC_LEDGER_ALIAS, shared, occurrence),
                occurrence,
            )
    return tuple(
        LedgerRow(
            record_key=keyed[draft.row_number][0],
            revision_hash=draft.revision,
            row_number=draft.row_number,
            occurrence=keyed[draft.row_number][1],
            **draft.fields,
        )
        for draft in drafts
    )


def ledger_rows(reference: PlanningReferenceCapture) -> tuple[LedgerRow, ...]:
    """:func:`read_ledger` over one captured academic-ledger tab."""
    return read_ledger(
        reference.values,
        len(reference.header_signature),
        dict(reference.columns),
        entered_numbers=reference.entered_numbers,
        formulas=reference.formulas,
    )


# --------------------------------------------------------------------------------------
# Classroom Budgets
# --------------------------------------------------------------------------------------


def _cents(value: Decimal) -> Decimal:
    try:
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise FactsError(
            "planning_input_invalid", "a planning amount exceeds the supported precision"
        ) from None


def _labels(classes: Sequence[RosterClass]) -> dict[str, str]:
    """Display labels: class-qualified wherever one teacher label names several classes."""
    counts: dict[str, int] = defaultdict(int)
    for item in classes:
        counts[item.teacher_label] += 1
    return {
        item.class_id: item.teacher_label
        if counts[item.teacher_label] == 1
        else f"{item.teacher_label} ({item.class_id})"
        for item in classes
    }


def _allocation(item: RosterClass, period: Period) -> tuple[str, Decimal | None]:
    if not item.eligible:
        return _NOT_ELIGIBLE, None
    if item.effective_end < period.start or item.effective_start > period.end_inclusive:
        return _OUTSIDE_YEAR, None
    if item.student_count is None:
        return _ENROLLMENT_MISSING, None
    if item.per_student_amount is None:
        return _RATE_MISSING, None
    return _ALLOCATED, _cents(item.student_count * item.per_student_amount)


@dataclass
class _Ledger:
    """The classroom view of the captured ledger: in-scope payments and exclusions."""

    payments: list[ClassroomPayment] = field(default_factory=list)
    excluded: dict[str, list[LedgerRow]] = field(default_factory=lambda: defaultdict(list))
    findings: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    allocations_unmatched: bool = False


def _attributed_year(row: LedgerRow, periods: Mapping[tuple[str, str], int]) -> int | None:
    """An operator-verified period allocation of this exact row and revision, else the
    source's own academic-year label (never inferred from the payment date)."""
    return periods.get((row.record_key, row.revision_hash), row.fiscal_year)


def _assign(
    row: LedgerRow,
    spend: Decimal,
    planning: PlanningInput,
    allocations: Mapping[tuple[str, str], list[PaymentAllocation]],
    used: set[tuple[str, str]],
) -> tuple[tuple[ClassroomAssignment, ...], Decimal]:
    """The row's classroom assignments and its unassigned rest (they add up to ``spend``)."""
    key = (row.record_key, row.revision_hash)
    splits = allocations.get(key)
    if splits:
        used.add(key)
        if any(item.amount != _cents(item.amount) for item in splits):
            raise FactsError(
                "payment_allocation_invalid",
                f"a payment allocation of ledger row {row.row_number} is not exact cents",
            )
        if sum((item.amount for item in splits), _ZERO) != spend:
            raise FactsError(
                "payment_allocation_mismatch",
                f"the payment allocations of ledger row {row.row_number} do not add up to "
                "its amount",
            )
        merged: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        for item in splits:
            merged[item.class_id] += item.amount
        return (
            tuple(
                ClassroomAssignment(class_id, amount, _BY_ALLOCATION)
                for class_id, amount in merged.items()
            ),
            _ZERO,
        )
    class_id = planning.payee_aliases.get(row.payee) if row.payee else None
    # A payee mapping applies only to a row that carries an explicit payment reference: a row
    # without one stays unassigned until an evidence-backed allocation names it exactly.
    if class_id is not None and row.payment_reference:
        return (ClassroomAssignment(class_id, spend, _BY_PAYEE),), _ZERO
    return (), spend


def _classroom_ledger(
    rows: Sequence[LedgerRow], planning: PlanningInput, period: Period
) -> _Ledger:
    out = _Ledger()
    periods = {
        (item.source_record_key, item.source_revision_hash): item.fiscal_year
        for item in planning.period_allocations
    }
    allocations: dict[tuple[str, str], list[PaymentAllocation]] = defaultdict(list)
    for item in planning.payment_allocations:
        allocations[(item.source_record_key, item.source_revision_hash)].append(item)
    used_allocations: set[tuple[str, str]] = set()
    identities: dict[str, int] = defaultdict(int)
    for row in rows:
        identities[row.record_key.rsplit(":", 1)[0]] += 1
        if planning.role_of(row.category) is None:
            out.findings[_FINDING_CATEGORY] += 1
        year = _attributed_year(row, periods)
        if year is None:
            out.findings[_FINDING_YEAR] += 1  # unmapped: never counted in any school year
        if not planning.is_classroom(row.category):
            continue
        if year is None:
            out.excluded[_YEAR_UNREADABLE].append(row)
            continue
        if year != planning.fiscal_year:
            out.excluded[_OTHER_YEAR].append(row)
            continue
        if row.payment_date is None:
            out.excluded[_UNDATED].append(row)
            continue
        if row.payment_date > period.as_of:
            out.excluded[_AFTER_AS_OF].append(row)
            continue
        spend = row.spend
        if spend is None:
            out.excluded[_AMOUNT_UNREADABLE].append(row)
            continue
        if row.unverified:
            out.findings[_FINDING_UNVERIFIED] += 1
        assignments, unassigned = _assign(row, spend, planning, allocations, used_allocations)
        out.payments.append(
            ClassroomPayment(
                record_key=row.record_key,
                revision_hash=row.revision_hash,
                row_number=row.row_number,
                payment_date=row.payment_date,
                amount=spend,
                category=row.category,
                source_fiscal_year=row.fiscal_year,
                fiscal_year=year,
                payment_reference=row.payment_reference or None,
                assignments=assignments,
                unassigned=unassigned,
            )
        )
    duplicates = sum(count for count in identities.values() if count > 1)
    if duplicates:
        out.findings[_FINDING_DUPLICATE] = duplicates
    present = {(row.record_key, row.revision_hash) for row in rows}
    for key in allocations:
        if key in used_allocations:
            continue
        if key in present:
            # The exact row exists but is outside this school year to date (for example it
            # posts after the as-of date): a visible count, not an incomplete figure.
            out.findings[_FINDING_ALLOCATION_OUT_OF_SCOPE] += len(allocations[key])
        else:
            # No captured row has that key and revision (stale or mistyped): the split is
            # not applied, so its row stays unassigned and the facts are partial.
            out.allocations_unmatched = True
            out.findings[_FINDING_ALLOCATION_UNMATCHED] += len(allocations[key])
    unmatched_periods = sum(1 for key in periods if key not in present)
    if unmatched_periods:
        out.findings[_FINDING_PERIOD_UNMATCHED] = unmatched_periods
    unassigned_rows = sum(1 for payment in out.payments if payment.unassigned != 0)
    if unassigned_rows:
        out.findings[_FINDING_UNASSIGNED] = unassigned_rows
    return out


def _classroom_items(ticket: Ticket, planning: PlanningInput) -> tuple[ReviewItem, ...]:
    return tuple(
        item
        for item in ticket.items
        if item.status == APPROVED_STATUS and planning.is_classroom_item(item.canonical_category)
    )


@dataclass(frozen=True)
class _PaidRequest:
    """One paid classroom request of the school year to date: the partition's domain.

    ``reference`` and ``recorded_amount`` come from its recorded payment event (``None``
    without one, or for a blank reference); ``items`` are its approved classroom items.
    """

    ticket: Ticket
    paid_on: date
    items: tuple[ReviewItem, ...]
    reference: str | None
    recorded_amount: Decimal | None

    @property
    def amount(self) -> Decimal:
        """Its approved classroom-item total: what it adds to paid or to issued."""
        return sum(
            (item.effective_amount for item in self.items if item.effective_amount is not None),
            _ZERO,
        )


def _paid_requests(
    bundle: ReimbursementReport, planning: PlanningInput, period: Period
) -> list[_PaidRequest]:
    """Every request recorded paid in the school year to date with an approved classroom
    item, in bundle order."""
    requests: list[_PaidRequest] = []
    for ticket in bundle.tickets:
        paid_on = ticket.live.payment_date
        if (
            ticket.live.payment_status != PAID_STATUS
            or paid_on is None
            or period.position(paid_on) != _CURRENT
        ):
            continue
        items = _classroom_items(ticket, planning)
        if not items:
            continue
        event = next(
            (e for e in bundle.events_for(ticket.review_key) if e.kind == RECORDED_PAYMENT_EVENT),
            None,
        )
        requests.append(
            _PaidRequest(
                ticket=ticket,
                paid_on=paid_on,
                items=items,
                reference=None if event is None else event.reference.strip() or None,
                recorded_amount=None if event is None else event.amount,
            )
        )
    return requests


@dataclass
class _Partition:
    """The paid classroom requests split in two: ``settled`` maps a posted row counted in
    paid to the requests it settles; ``issued`` lists the rest (never both, never neither)."""

    settled: dict[str, list[_PaidRequest]] = field(default_factory=lambda: defaultdict(list))
    issued: list[IssuedPayment] = field(default_factory=list)


def _check_partition(requests: Sequence[_PaidRequest], partition: _Partition) -> None:
    """The partition invariant: every paid classroom request is on exactly one side, and
    the two sides add up to the total of the paid classroom requests."""
    settled = [request for group in partition.settled.values() for request in group]
    keys = [request.ticket.review_key for request in settled]
    keys += [item.review_key for item in partition.issued]
    every = [request.ticket.review_key for request in requests]
    side_total = sum((request.amount for request in settled), _ZERO)
    side_total += sum((item.amount for item in partition.issued), _ZERO)
    total = sum((request.amount for request in requests), _ZERO)
    if sorted(keys) != sorted(every) or side_total != total:
        raise FactsError(
            "classroom_partition_mismatch",
            "a paid classroom request is not exactly once settled or issued",
        )


def _partition(
    requests: Sequence[_PaidRequest],
    payments: Sequence[ClassroomPayment],
    rows: Sequence[LedgerRow],
    planning: PlanningInput,
    period: Period,
    findings: dict[str, int],
) -> _Partition:
    """Partition the paid classroom requests into settled by a posted row, or issued (D49).

    ``payments`` are exactly the rows counted in paid, so the two sides are computed from the
    same rows as paid. A request is settled by a row when that row carries its exact
    recorded payment reference (the reimbursement case policy of
    :func:`~np_finance.main_reports.reconcile.reference_token`, over the whole cell) or an
    applied ``payment_allocations`` entry of that exact row and revision has its exact
    ``review_key``. Settled by exactly one row, it is counted in paid through that row only.
    Otherwise it is listed as issued with its reason: ``ambiguous`` (several rows),
    ``no_reference`` (no reference and no naming allocation), ``reference_out_of_scope`` (its
    reference is only on captured rows dated on or before the as-of date that feed no paid
    figure: another school year or category, undated or unreadable) or ``not_posted``. Every
    reason but ``not_posted`` adds a finding; an issued amount is never added to paid.
    """
    counted = {(payment.record_key, payment.revision_hash) for payment in payments}
    named: dict[str, set[str]] = defaultdict(set)
    for allocation in planning.payment_allocations:
        row_key = (allocation.source_record_key, allocation.source_revision_hash)
        if allocation.review_key is not None and row_key in counted:
            named[allocation.review_key].add(allocation.source_record_key)
    counted_keys = {payment.record_key for payment in payments}
    elsewhere = [
        row.payment_reference
        for row in rows
        if row.payment_reference
        and row.record_key not in counted_keys
        and (row.payment_date is None or row.payment_date <= period.as_of)
    ]
    out = _Partition()
    for request in requests:
        linked = set(named.get(request.ticket.review_key, ()))
        reason = _NO_REFERENCE
        if request.reference is not None:
            token = reference_token(request.reference, ignore_case=True)
            linked |= {
                payment.record_key
                for payment in payments
                if payment.payment_reference and token.fullmatch(payment.payment_reference)
            }
            outside = any(token.fullmatch(text) for text in elsewhere)
            reason = _REFERENCE_OUT_OF_SCOPE if outside else _NOT_POSTED
        if len(linked) == 1:
            out.settled[linked.pop()].append(request)
            continue
        if linked:
            reason = _AMBIGUOUS
        if reason in _ISSUED_FINDINGS:
            findings[_ISSUED_FINDINGS[reason]] += 1
        out.issued.append(
            IssuedPayment(
                review_key=request.ticket.review_key,
                ticket_ref=request.ticket.ref,
                payment_date=request.paid_on,
                amount=request.amount,
                item_keys=tuple(item.item_key for item in request.items),
                reason=reason,
            )
        )
    _check_partition(requests, out)
    amounts = {payment.record_key: payment.amount for payment in payments}
    for record_key, settled in out.settled.items():
        recorded = [request.recorded_amount for request in settled]
        total = sum((amount for amount in recorded if amount is not None), _ZERO)
        if None in recorded or total != amounts[record_key]:
            findings[_FINDING_AMOUNT_MISMATCH] += 1
    return out


def _review_key_findings(
    planning: PlanningInput,
    bundle: ReimbursementReport,
    requests: Sequence[_PaidRequest],
    findings: dict[str, int],
) -> None:
    """Count every allocation ``review_key`` that cannot settle a request (never dropped
    silently): unknown (no request of the staged bundle is recorded paid under it) or out
    of scope (a paid request that is not a classroom request paid in the school year to
    date)."""
    paid = {t.review_key for t in bundle.tickets if t.live.payment_status == PAID_STATUS}
    domain = {request.ticket.review_key for request in requests}
    for allocation in planning.payment_allocations:
        key = allocation.review_key
        if key is None or key in domain:
            continue
        findings[_FINDING_KEY_OUT_OF_SCOPE if key in paid else _FINDING_KEY_UNKNOWN] += 1


def _purchases(
    payments: Sequence[ClassroomPayment], partition: _Partition
) -> list[ClassroomPurchase]:
    purchases: list[ClassroomPurchase] = []
    for payment in payments:
        class_ids = tuple(item.class_id for item in payment.assignments)
        for request in partition.settled.get(payment.record_key, ()):
            for item in request.items:
                amount, day = item.effective_amount, item.effective_date
                if amount is None or day is None:
                    continue
                purchases.append(
                    ClassroomPurchase(
                        review_key=request.ticket.review_key,
                        ticket_ref=request.ticket.ref,
                        item_key=item.item_key,
                        expense_date=day,
                        description=item.effective_item,
                        amount=amount,
                        record_key=payment.record_key,
                        class_ids=class_ids,
                    )
                )
    purchases.sort(key=lambda p: (-p.amount, p.expense_date, p.review_key, p.item_key))
    return purchases


def _classroom_budget(lines: Sequence[BudgetLine], planning: PlanningInput) -> Decimal | None:
    """The adopted classroom envelope; unknown (never zero) when any line is unreadable."""
    selected = [
        line
        for line in lines
        if line.line_type == _EXPENSE_LINE and line.category in planning.classroom_categories
    ]
    if not selected or any(line.target is None for line in selected):
        return None
    return sum((line.target for line in selected if line.target is not None), _ZERO)


def _unavailable(reason: str, period: Period, planning: PlanningCapture | None) -> ClassroomFacts:
    return ClassroomFacts(
        status=_UNAVAILABLE,
        reasons=(reason,),
        fiscal_year=period.year_label,
        as_of=period.as_of,
        planning_sha256=None if planning is None else planning.sha256,
        planning_input_sha256=None if planning is None else planning.input_sha256,
        ledger_sha256=None,
        ledger_coverage_start=None,
        ledger_coverage_end=None,
        roster_complete=None,
        roster_as_of=None,
        classes=(),
        payments=(),
        source_total=None,
        assigned_total=_ZERO,
        unassigned_total=_ZERO,
        allocation_total=None,
        classroom_budget=None,
        issued=(),
        purchases=(),
        excluded=(),
        findings=(),
    )


def _check(facts: ClassroomFacts) -> ClassroomFacts:
    """The financial invariants every published classroom figure rests on."""
    for payment in facts.payments:
        if sum((a.amount for a in payment.assignments), _ZERO) + payment.unassigned != (
            payment.amount
        ):
            raise FactsError("classroom_totals_mismatch", "a payment's assignments do not add up")
    paid = sum((row.paid for row in facts.classes if row.paid is not None), _ZERO)
    checks = (
        facts.source_total is None
        or facts.source_total == facts.assigned_total + facts.unassigned_total,
        facts.source_total is None or paid == facts.assigned_total,
        facts.source_total is None
        or sum((p.amount for p in facts.payments), _ZERO) == facts.source_total,
    )
    if not all(checks):
        raise FactsError(
            "classroom_totals_mismatch",
            f"{checks.count(False)} classroom total(s) disagree between representations",
        )
    return facts


def classroom_facts(
    planning: PlanningCapture | None,
    period: Period,
    bundle: ReimbursementReport,
    budget_lines: Sequence[BudgetLine],
    *,
    journal_targets: Iterable[str] = (),
) -> ClassroomFacts:
    """Classroom Budgets facts of one school-year period (pure; see the module docstring).

    ``planning`` is the run's optional capture; without one, or for another school year, the
    facts are ``unavailable`` with that reason and every other report still publishes.
    ``bundle`` is the staged review bundle (read only) and ``budget_lines`` the adopted
    school-year lines (the classroom envelope). ``journal_targets`` are the record keys the
    adjustments journal targets: an operator period allocation of the same row conflicts with
    a recorded journal adjustment. Raises :class:`FactsError` for corrupt supplied data
    (``payment_allocation_invalid``, ``payment_allocation_mismatch``,
    ``period_allocation_conflict``) or a broken invariant (``classroom_totals_mismatch``,
    ``classroom_partition_mismatch``); missing optional data is never an error.
    """
    if planning is None:
        return _unavailable(_PLANNING_ABSENT, period, None)
    document = planning_input(planning)
    if document.fiscal_year != period.year_label:
        return _unavailable(_PLANNING_YEAR_MISMATCH, period, planning)
    targets = set(journal_targets)
    if any(item.source_record_key in targets for item in document.period_allocations):
        raise FactsError(
            "period_allocation_conflict",
            "a period allocation names a row a recorded journal adjustment also targets",
        )
    reasons: list[str] = []
    findings: dict[str, int] = defaultdict(int)
    if not document.classroom_categories:
        reasons.append(_CATEGORIES_ABSENT)
    reference = next(
        (item for item in planning.references if item.role == ACADEMIC_LEDGER_ROLE), None
    )
    rows = ledger_rows(reference) if reference is not None else ()
    # Without a captured ledger no row was searched, so no payment or period allocation is
    # unmatched: the ledger view (and its findings) exists only for a captured ledger.
    ledger = _classroom_ledger(rows, document, period) if reference is not None else _Ledger()
    for code, count in ledger.findings.items():
        findings[code] += count
    requests = _paid_requests(bundle, document, period)
    _review_key_findings(document, bundle, requests, findings)
    partition = _partition(requests, ledger.payments, rows, document, period, findings)
    payments = [
        replace(
            payment,
            review_keys=tuple(
                request.ticket.review_key
                for request in partition.settled.get(payment.record_key, ())
            ),
        )
        for payment in ledger.payments
    ]
    paid_by_class: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    keys_by_class: dict[str, list[str]] = defaultdict(list)
    for payment in payments:
        for assignment in payment.assignments:
            paid_by_class[assignment.class_id] += assignment.amount
            keys_by_class[assignment.class_id].append(payment.record_key)
    labels = _labels(document.classes)
    # Classroom spending is known only from a captured ledger and a declared classroom
    # category: without a category no row can be classroom spending, so paid is unknown
    # (rule 9), never an observed zero.
    spending = reference is not None and bool(document.classroom_categories)
    classes: list[ClassroomRow] = []
    for item in document.classes:
        state, allocation = _allocation(item, period)
        paid = paid_by_class[item.class_id] if spending else None
        classes.append(
            ClassroomRow(
                class_id=item.class_id,
                teacher_label=item.teacher_label,
                label=labels[item.class_id],
                eligible=item.eligible,
                effective_start=item.effective_start,
                effective_end=item.effective_end,
                student_count=item.student_count,
                per_student_amount=item.per_student_amount,
                allocation_state=state,
                allocation=allocation,
                paid=paid,
                remainder=allocation - paid
                if allocation is not None and paid is not None
                else None,
                payment_keys=tuple(keys_by_class[item.class_id]),
            )
        )
    known = [row.allocation for row in classes if row.allocation is not None]
    allocation_total = sum(known, _ZERO) if known else None
    if not classes:
        reasons.append(_ROSTER_ABSENT)
    elif not document.roster_complete:
        reasons.append(_ROSTER_INCOMPLETE)
    if any(row.allocation_state in (_ENROLLMENT_MISSING, _RATE_MISSING) for row in classes):
        reasons.append(_ALLOCATION_MISSING)
    source_total: Decimal | None = None
    if reference is None:
        reasons.append(_LEDGER_ABSENT)
    else:
        if spending:
            source_total = sum((payment.amount for payment in payments), _ZERO)
        if reference.coverage_start > period.start or reference.coverage_end < period.as_of:
            reasons.append(_LEDGER_COVERAGE_PARTIAL)
        if any(payment.unassigned != 0 for payment in payments):
            reasons.append(_PAYMENTS_UNASSIGNED)
        if any(reason in _UNREADABLE_EXCLUSIONS for reason in ledger.excluded):
            reasons.append(_ROWS_UNREADABLE)
        if ledger.allocations_unmatched:
            reasons.append(_ALLOCATIONS_UNMATCHED)
    budget = _classroom_budget(budget_lines, document)
    if budget is None and document.classroom_categories:
        findings[_FINDING_BUDGET_UNKNOWN] = 1
    unavailable = allocation_total is None and source_total is None
    status = _UNAVAILABLE if unavailable else (_PARTIAL if reasons else _COMPLETE)
    ordered_reasons = tuple(reason for reason in CLASSROOM_REASONS if reason in reasons)
    return _check(
        ClassroomFacts(
            status=status,
            reasons=ordered_reasons,
            fiscal_year=period.year_label,
            as_of=period.as_of,
            planning_sha256=planning.sha256,
            planning_input_sha256=planning.input_sha256,
            ledger_sha256=None if reference is None else reference.sha256,
            ledger_coverage_start=None if reference is None else reference.coverage_start,
            ledger_coverage_end=None if reference is None else reference.coverage_end,
            roster_complete=document.roster_complete,
            roster_as_of=document.roster_as_of,
            classes=tuple(classes),
            payments=tuple(payments),
            source_total=source_total,
            assigned_total=sum(
                (a.amount for payment in payments for a in payment.assignments), _ZERO
            ),
            unassigned_total=sum((payment.unassigned for payment in payments), _ZERO),
            allocation_total=allocation_total,
            classroom_budget=budget,
            issued=tuple(partition.issued),
            purchases=tuple(_purchases(payments, partition)),
            excluded=tuple(
                ClassroomExclusion(
                    reason=reason,
                    rows=len(ledger.excluded[reason]),
                    amount=sum(
                        (row.spend for row in ledger.excluded[reason] if row.spend is not None),
                        _ZERO,
                    ),
                    record_keys=tuple(row.record_key for row in ledger.excluded[reason]),
                )
                for reason in CLASSROOM_EXCLUSIONS
                if ledger.excluded.get(reason)
            ),
            findings=tuple(
                FactIssue(code, findings[code]) for code in CLASSROOM_FINDINGS if findings.get(code)
            ),
        )
    )
