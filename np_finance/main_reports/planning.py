"""Board-planning calculations for the Main Report Set (pure; no workbook or file access).

:func:`classroom_facts` is the Classroom Budgets projection
(``docs/plans/master_plan.md`` Phase CORE-BRIEFS, Step 66). Its production caller is
:func:`np_finance.main_reports.facts.build`, over the optional board-planning capture
(:class:`~np_finance.main_reports.models.PlanningCapture`) of the same captured input set:

* **Policy.** The private planning document is re-read from the capture's exact text and
  re-validated by the one capture validator before any field is used; the original file and
  the Sheets are never read again here.
* **Allocations.** A class's allocation is its enrollment times its per-student rate. A
  missing count or rate, or an ineligible class, leaves the allocation unknown: the adopted
  classroom budget is NEVER distributed across classes. The adopted classroom envelope is
  shown beside the allocations with its difference, never used to scale them.
* **Posted payments.** Academic-ledger rows get version-1 record keys under the planning
  alias :data:`PLANNING_LEDGER_ALIAS` (deterministic occurrence, ordered by revision, so
  identical-looking rows are never merged) and revision hashes of their exact cells. A row
  counts when its source category is explicitly mapped to a classroom budget category, its
  academic-year label (or an operator ``period_allocation`` of that exact key and revision)
  is the report's fiscal year, and it is dated on or before the as-of date. A payment paid
  before the school-year start stays in its academic year (``prepaid``).
* **Attribution.** An evidence-backed ``payment_allocation`` of the exact key and revision
  splits a row between classes (the parts must sum exactly to the row, or the input is
  refused); otherwise an exact ``payee_alias`` assigns the whole row; otherwise it stays
  visibly unassigned. Matching a check amount or a spelling is never attribution. Posted
  classroom spending always equals the assigned plus the unassigned amount.
* **Reimbursement evidence.** A paid request whose exact recorded payment reference is on
  no posted ledger row is ``issued but not posted``: shown separately and never added to
  paid spending, so the later posting is not counted twice. Larger purchases come only from
  paid, dated, approved itemized review lines in the period.

Errors (:class:`PlanningError`) carry a stable code and fixed text; neither ever carries a
key, name, money or cell value read from the private inputs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from np_finance.main_reports import sources
from np_finance.main_reports.models import (
    CLASSROOM_ASSIGNMENT_BASES,
    EXPENSE_BUCKETS,
    PLANNING_FACT_STATUSES,
    BudgetLine,
    ClassroomAssignment,
    ClassroomFacts,
    ClassroomPayment,
    ClassroomPurchase,
    ClassroomRow,
    FactIssue,
    IssuedPayment,
    Period,
    PlanningCapture,
    PlanningReferenceCapture,
    ReimbursementFacts,
    ReimbursementItemFact,
    SourceRef,
    content_hash,
    make_record_key,
    money_str,
)
from np_finance.main_reports.sources import parse_money, parse_source_date
from np_finance.reimbursement_report import STATUS_META, ReimbursementReport

__all__ = [
    # constants
    "PLANNING_LEDGER_ALIAS",
    "ACADEMIC_LEDGER_ROLE",
    "CLASSROOM_FINDING_CODES",
    "CLASSROOM_EXCLUSIONS",
    "PLANNING_ERROR_CODES",
    # functions
    "absent_classroom",
    "read_policy",
    "read_academic_ledger",
    "reference_key",
    "classroom_facts",
    # types
    "PlanningError",
    "RosterClass",
    "PaymentAllocation",
    "PeriodAllocation",
    "PlanningPolicy",
    "LedgerRow",
    "AcademicLedger",
]

# The distinct record-key alias of academic-ledger rows (never a configured source alias:
# those name CFO tabs, and a planning row is never a bank-feed transaction).
PLANNING_LEDGER_ALIAS = "planning-academic-ledger"
ACADEMIC_LEDGER_ROLE = sources.PLANNING_ROLES[0]
if ACADEMIC_LEDGER_ROLE != "academic_ledger":  # pragma: no cover - import-time invariant
    raise RuntimeError("planning must read the academic-ledger role from sources")

_COMPLETE, _PARTIAL, _UNAVAILABLE = PLANNING_FACT_STATUSES
_ALLOCATION_BASIS, _ALIAS_BASIS = CLASSROOM_ASSIGNMENT_BASES
_PRIOR, _CURRENT = EXPENSE_BUCKETS[:2]
_ZERO = Decimal("0.00")
# Bundle vocabulary read here (owned by reimbursement_report): the approved item status.
_APPROVED = "A"
if _APPROVED not in STATUS_META:  # pragma: no cover - import-time invariant
    raise RuntimeError("planning must name an approved status the queue knows")
_EXPENSE_ROLE = "expense"
_EXPENSE_LINE = "expense"

PLANNING_ERROR_CODES: tuple[str, ...] = (
    "planning_policy_invalid",
    "payment_allocation_mismatch",
)
_POLICY_INVALID, _ALLOCATION_MISMATCH = PLANNING_ERROR_CODES

# Classroom findings (visible, countable; never a money value). The first four make the
# whole section unavailable; the next five make it partial.
CLASSROOM_FINDING_CODES: tuple[str, ...] = (
    "planning_input_absent",
    "planning_year_mismatch",
    "academic_ledger_absent",
    "classroom_categories_absent",
    "roster_incomplete",
    "class_allocation_missing",
    "ledger_coverage_partial",
    "ledger_rows_unreadable",
    "ledger_category_unmapped",
    "roster_empty",
    "payment_unassigned",
    "payment_allocation_unused",
    "period_allocation_unused",
    "class_outside_period",
    "ledger_duplicate_identity",
    "reimbursement_issued_not_posted",
    "reimbursement_payment_unlinked",
    "payment_reference_ambiguous",
    "classroom_budget_unknown",
)
(
    _PLANNING_ABSENT,
    _YEAR_MISMATCH,
    _LEDGER_ABSENT,
    _CATEGORIES_ABSENT,
    _ROSTER_INCOMPLETE,
    _ALLOCATION_MISSING,
    _COVERAGE_PARTIAL,
    _ROWS_UNREADABLE,
    _CATEGORY_UNMAPPED,
    _ROSTER_EMPTY,
    _UNASSIGNED,
    _ALLOCATION_UNUSED,
    _PERIOD_UNUSED,
    _OUTSIDE_PERIOD,
    _DUPLICATE_IDENTITY,
    _ISSUED,
    _UNLINKED,
    _REFERENCE_AMBIGUOUS,
    _BUDGET_UNKNOWN,
) = CLASSROOM_FINDING_CODES
_PARTIAL_CODES = frozenset(
    {
        _ROSTER_INCOMPLETE,
        _ALLOCATION_MISSING,
        _COVERAGE_PARTIAL,
        _ROWS_UNREADABLE,
        _CATEGORY_UNMAPPED,
    }
)

# Why a readable captured ledger row is outside posted classroom spending (audit counts).
CLASSROOM_EXCLUSIONS: tuple[str, ...] = (
    "after_as_of",
    "other_fiscal_year",
    "not_classroom",
    "category_unmapped",
)
_AFTER_AS_OF, _OTHER_YEAR, _NOT_CLASSROOM, _UNMAPPED_ROW = CLASSROOM_EXCLUSIONS


class PlanningError(Exception):
    """Corrupt supplied planning data (never merely missing data). Carries a stable ``code``
    (:data:`PLANNING_ERROR_CODES`); its text never carries a key, name or money value."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.detail = message
        super().__init__(f"{code}: {message}")


# --------------------------------------------------------------------------------------
# Typed policy (re-validated from the captured document text)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterClass:
    """One roster class. No student identity is collected."""

    class_id: str
    teacher_label: str
    student_count: int | None
    per_student_amount: Decimal | None
    effective_start: date
    effective_end: date
    eligible: bool


@dataclass(frozen=True)
class PaymentAllocation:
    """An evidence-backed reporting assignment of part of one exact source row to a class.

    ``amount`` is SPENDING (an expense of ``-40.00`` in the ledger allocates ``40.00``)."""

    record_key: str
    revision_hash: str
    class_id: str
    amount: Decimal
    evidence: str


@dataclass(frozen=True)
class PeriodAllocation:
    """An operator-verified academic-year attribution of one exact source row."""

    record_key: str
    revision_hash: str
    fiscal_year: int
    evidence: str


@dataclass(frozen=True)
class PlanningPolicy:
    """The fields of a validated planning document that Classroom Budgets uses.

    ``category_roles`` maps each source category to its ``(role, budget category)``;
    ``classroom_categories`` are budget categories.
    """

    fiscal_year: int
    roster_complete: bool
    roster_as_of: date
    classes: tuple[RosterClass, ...]
    payee_aliases: Mapping[str, str]
    payment_allocations: tuple[PaymentAllocation, ...]
    category_roles: Mapping[str, tuple[str, str]]
    classroom_categories: frozenset[str]
    period_allocations: tuple[PeriodAllocation, ...]

    def budget_category(self, source_category: str) -> str | None:
        role = self.category_roles.get(source_category)
        return None if role is None else role[1]

    def is_classroom(self, category: str) -> bool:
        """A classroom budget category, or a source category explicitly mapped to one as an
        expense (the reimbursement review's categories are matched the same way)."""
        role = self.category_roles.get(category)
        if role is not None:
            return role[0] == _EXPENSE_ROLE and role[1] in self.classroom_categories
        return category in self.classroom_categories


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def read_policy(planning: PlanningCapture) -> PlanningPolicy:
    """The typed policy of ``planning``'s exact captured text, re-validated first.

    The text was validated when it was captured (and a stored capture is hash-verified), so
    a failure here means the capture itself is corrupt: ``planning_policy_invalid``.
    """
    try:
        raw = json.loads(
            planning.input_json.removeprefix("\ufeff"), object_pairs_hook=sources._unique_object
        )
        sources._validate_planning_input(raw)
    except (ValueError, RecursionError, sources.SourceError):
        raw = None
    if raw is None:  # raised outside the handler so no input text is chained
        raise PlanningError(_POLICY_INVALID, "the captured planning input does not validate")
    classes = tuple(
        RosterClass(
            class_id=item["class_id"],
            teacher_label=item["teacher_label"],
            student_count=item["student_count"],
            per_student_amount=_decimal(item["per_student_amount"]),
            effective_start=date.fromisoformat(item["effective_start"]),
            effective_end=date.fromisoformat(item["effective_end"]),
            eligible=item["eligible"],
        )
        for item in raw["classes"]
    )
    return PlanningPolicy(
        fiscal_year=raw["fiscal_year"],
        roster_complete=raw["roster_complete"],
        roster_as_of=date.fromisoformat(raw["roster_as_of"]),
        classes=classes,
        payee_aliases={item["source_payee"]: item["class_id"] for item in raw["payee_aliases"]},
        payment_allocations=tuple(
            PaymentAllocation(
                record_key=item["source_record_key"],
                revision_hash=item["source_revision_hash"],
                class_id=item["class_id"],
                amount=Decimal(item["amount"]),
                evidence=item["evidence"],
            )
            for item in raw["payment_allocations"]
        ),
        category_roles={
            item["source_category"]: (item["role"], item["budget_category"])
            for item in raw["category_roles"]
        },
        classroom_categories=frozenset(raw["classroom_categories"]),
        period_allocations=tuple(
            PeriodAllocation(
                record_key=item["source_record_key"],
                revision_hash=item["source_revision_hash"],
                fiscal_year=item["fiscal_year"],
                evidence=item["evidence"],
            )
            for item in raw["period_allocations"]
        ),
    )


# --------------------------------------------------------------------------------------
# Academic ledger rows (record keys, revisions and readable values)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerRow:
    """One readable academic-ledger row. ``amount`` is the signed source amount (expenses
    negative); ``fiscal_year`` is the ledger's own academic-year label."""

    ref: SourceRef
    payment_date: date
    description: str
    amount: Decimal
    category: str
    fiscal_year: int
    payment_reference: str | None
    payee: str | None


@dataclass(frozen=True)
class AcademicLedger:
    """Every readable row of one captured academic ledger, plus what could not be read.

    ``unreadable`` counts non-blank rows missing a date, amount, description, category or
    academic year (or holding an unreadable one); ``unreadable_categories`` holds the category
    text of each (blank when absent). ``duplicates`` counts rows sharing an identity with a
    row of different content.
    """

    rows: tuple[LedgerRow, ...]
    unreadable: int
    unreadable_categories: tuple[str, ...]
    duplicates: int


def _trimmed(cells: Sequence[str]) -> list[str]:
    values = list(cells)
    while values and values[-1] == "":
        values.pop()
    return values


def _money(
    cells: Sequence[str], position: int | None, entered: Mapping[int, str]
) -> Decimal | None:
    if position is None or position >= len(cells):
        return None
    try:
        return parse_money(cells[position])
    except ValueError as error:
        # A bare dash is exact zero only over an entered numeric zero (Accounting display).
        if str(error) == "dash_placeholder" and position in entered:
            if sources.entered_matches(entered[position], _ZERO):
                return _ZERO
        return None


def _date(cells: Sequence[str], position: int | None) -> date | None:
    if position is None or position >= len(cells):
        return None
    try:
        return parse_source_date(cells[position])
    except ValueError:
        return None


def _text(cells: Sequence[str], position: int | None) -> str | None:
    if position is None or position >= len(cells):
        return None
    text = cells[position].strip()
    return text or None


def _year(text: str | None) -> int | None:
    if text is None or not text.isascii() or not text.isdigit() or len(text) != 4:
        return None
    return int(text)


def read_academic_ledger(reference: PlanningReferenceCapture) -> AcademicLedger:
    """Read every data row of a captured academic ledger (rows below its header signature).

    Record keys: ``v1:planning-academic-ledger:<sha256 of date, description, amount and
    payment reference>:<occurrence>``, occurrences ordered by revision hash then row, so an
    unchanged multiset keeps its keys under any row order. Revision hashes cover the row's
    exact cells (trailing blanks ignored).
    """
    columns = dict(reference.columns)
    header_rows = len(reference.header_signature)
    entered_by_row: dict[int, dict[int, str]] = defaultdict(dict)
    for cell in reference.entered_numbers:
        entered_by_row[cell.row][cell.column] = cell.value
    drafts: list[tuple[tuple[str, ...], str, int, LedgerRow]] = []
    unreadable_categories: list[str] = []
    for index in range(header_rows, len(reference.values)):
        cells = reference.values[index]
        if all(cell.strip() == "" for cell in cells):
            continue
        payment_date = _date(cells, columns.get("payment_date"))
        amount = _money(cells, columns.get("amount"), entered_by_row.get(index, {}))
        description = _text(cells, columns.get("description"))
        category = _text(cells, columns.get("category"))
        fiscal_year = _year(_text(cells, columns.get("fiscal_year")))
        if (
            payment_date is None
            or amount is None
            or description is None
            or category is None
            or fiscal_year is None
        ):
            unreadable_categories.append(category or "")
            continue
        payment_reference = _text(cells, columns.get("payment_reference"))
        identity: tuple[str, ...] = (
            ACADEMIC_LEDGER_ROLE,
            payment_date.isoformat(),
            description,
            money_str(amount),
            payment_reference or "",
        )
        revision = content_hash(
            {
                "alias": PLANNING_LEDGER_ALIAS,
                "role": ACADEMIC_LEDGER_ROLE,
                "values": _trimmed(cells),
            }
        )
        ref = SourceRef(
            source_alias=PLANNING_LEDGER_ALIAS,
            snapshot_sha256=reference.sha256,
            tab_id=reference.tab_id,
            row_number=index + 1,
            record_key="",  # assigned below
            revision_hash=revision,
        )
        row = LedgerRow(
            ref=ref,
            payment_date=payment_date,
            description=description,
            amount=amount,
            category=category,
            fiscal_year=fiscal_year,
            payment_reference=payment_reference,
            payee=_text(cells, columns.get("payee")),
        )
        drafts.append((identity, revision, index, row))
    groups: dict[tuple[str, ...], list[tuple[str, int, LedgerRow]]] = defaultdict(list)
    for draft_identity, revision, index, row in drafts:
        groups[draft_identity].append((revision, index, row))
    keyed: dict[int, LedgerRow] = {}
    duplicates = 0
    for group_identity, members in groups.items():
        if len(members) > 1 and len({revision for revision, _, _ in members}) > 1:
            duplicates += len(members)
        ordered = sorted(members, key=lambda member: (member[0], member[1]))
        for occurrence, (_, index, row) in enumerate(ordered):
            key = make_record_key(PLANNING_LEDGER_ALIAS, group_identity, occurrence)
            keyed[index] = replace(row, ref=replace(row.ref, record_key=key))
    return AcademicLedger(
        rows=tuple(keyed[index] for index in sorted(keyed)),
        unreadable=len(unreadable_categories),
        unreadable_categories=tuple(unreadable_categories),
        duplicates=duplicates,
    )


def reference_key(reference: str | None) -> str | None:
    """The comparison form of an exact payment reference: the whole value, case ignored.

    Never a token search or an amount match: two references link only when they are the
    same value."""
    if reference is None:
        return None
    text = reference.strip().casefold()
    return text or None


# --------------------------------------------------------------------------------------
# Classroom Budgets
# --------------------------------------------------------------------------------------


def _unavailable(
    code: str,
    *,
    planning: PlanningCapture | None = None,
    policy: PlanningPolicy | None = None,
    classes: Sequence[ClassroomRow] = (),
    extra: Sequence[FactIssue] = (),
) -> ClassroomFacts:
    return ClassroomFacts(
        status=_UNAVAILABLE,
        fiscal_year=None if policy is None else policy.fiscal_year,
        roster_complete=None if policy is None else policy.roster_complete,
        roster_as_of=None if policy is None else policy.roster_as_of,
        planning_sha256=None if planning is None else planning.sha256,
        ledger_sha256=None,
        ledger_coverage=None,
        ledger_coverage_complete=False,
        classes=tuple(classes),
        payments=(),
        issued_unposted=(),
        purchases=(),
        adopted_envelope=None,
        excluded=(),
        findings=(FactIssue(code, 1), *extra),
    )


def absent_classroom() -> ClassroomFacts:
    """The explicitly unavailable section of a run without a board-planning input."""
    return _unavailable(_PLANNING_ABSENT)


def _active(item: RosterClass, period: Period) -> bool:
    """The class's effective window overlaps the school year."""
    return item.effective_start <= period.end_inclusive and item.effective_end >= period.start


def _labels(classes: Sequence[RosterClass]) -> dict[str, str]:
    """Class-qualified labels: a teacher with several classes is shown once per class."""
    per_teacher: dict[str, int] = defaultdict(int)
    for item in classes:
        per_teacher[item.teacher_label] += 1
    return {
        item.class_id: item.teacher_label
        if per_teacher[item.teacher_label] == 1
        else f"{item.teacher_label} · {item.class_id}"
        for item in classes
    }


def _allocation(item: RosterClass) -> Decimal | None:
    if not item.eligible or item.student_count is None or item.per_student_amount is None:
        return None
    return (item.per_student_amount * item.student_count).quantize(Decimal("0.01"))


def _envelope(lines: Sequence[BudgetLine], categories: frozenset[str]) -> Decimal | None:
    """The adopted classroom budget: every adopted expense line of a classroom category."""
    targets = [
        line.target
        for line in lines
        if line.line_type == _EXPENSE_LINE and line.category in categories
    ]
    if not targets or any(target is None for target in targets):
        return None
    return sum((target for target in targets if target is not None), _ZERO)


@dataclass
class _Attribution:
    payments: list[ClassroomPayment]
    excluded: dict[str, int]
    used_allocations: set[tuple[str, str]]
    used_periods: set[tuple[str, str]]
    outside_period: int


def _assign(
    row: LedgerRow,
    spend: Decimal,
    policy: PlanningPolicy,
    allocations: Mapping[tuple[str, str], Sequence[PaymentAllocation]],
    active: frozenset[str],
) -> tuple[tuple[ClassroomAssignment, ...], Decimal, int]:
    """(assignments, unassigned amount, parts naming a class outside the period)."""
    key = (row.ref.record_key, row.ref.revision_hash)
    parts = allocations.get(key, ())
    if parts:
        if sum((part.amount for part in parts), _ZERO) != spend:
            raise PlanningError(
                _ALLOCATION_MISMATCH,
                "the payment allocations of one source row do not sum to its amount",
            )
        assigned = tuple(
            ClassroomAssignment(part.class_id, part.amount, _ALLOCATION_BASIS, part.evidence)
            for part in parts
            if part.class_id in active
        )
        outside = sum(1 for part in parts if part.class_id not in active)
        unassigned = spend - sum((item.amount for item in assigned), _ZERO)
        return assigned, unassigned, outside
    class_id = None if row.payee is None else policy.payee_aliases.get(row.payee)
    if class_id is None:
        return (), spend, 0
    if class_id not in active:
        return (), spend, 1
    return (ClassroomAssignment(class_id, spend, _ALIAS_BASIS),), _ZERO, 0


def _attribute(
    ledger: AcademicLedger,
    policy: PlanningPolicy,
    period: Period,
    active: frozenset[str],
    linked: Mapping[str, tuple[str, ...]],
) -> _Attribution:
    allocations: dict[tuple[str, str], list[PaymentAllocation]] = defaultdict(list)
    for allocation in policy.payment_allocations:
        allocations[(allocation.record_key, allocation.revision_hash)].append(allocation)
    periods = {(item.record_key, item.revision_hash): item for item in policy.period_allocations}
    result = _Attribution([], defaultdict(int), set(), set(), 0)
    for row in ledger.rows:
        key = (row.ref.record_key, row.ref.revision_hash)
        corrected = periods.get(key)
        if corrected is not None:
            result.used_periods.add(key)
        fiscal_year = corrected.fiscal_year if corrected is not None else row.fiscal_year
        if row.payment_date > period.as_of:
            result.excluded[_AFTER_AS_OF] += 1
            continue
        if fiscal_year != policy.fiscal_year:
            result.excluded[_OTHER_YEAR] += 1
            continue
        budget_category = policy.budget_category(row.category)
        if budget_category is None:
            result.excluded[_UNMAPPED_ROW] += 1
            continue
        if not policy.is_classroom(row.category):
            result.excluded[_NOT_CLASSROOM] += 1
            continue
        spend = -row.amount
        assignments, unassigned, outside = _assign(row, spend, policy, allocations, active)
        if key in allocations:
            result.used_allocations.add(key)
        result.outside_period += outside
        result.payments.append(
            ClassroomPayment(
                ref=row.ref,
                payment_date=row.payment_date,
                description=row.description,
                source_category=row.category,
                budget_category=budget_category,
                source_fiscal_year=row.fiscal_year,
                fiscal_year=fiscal_year,
                period_evidence=None if corrected is None else corrected.evidence,
                amount=spend,
                payment_reference=row.payment_reference,
                assignments=assignments,
                unassigned=unassigned,
                prepaid=row.payment_date < period.start,
                linked_review_keys=linked.get(reference_key(row.payment_reference) or "", ()),
            )
        )
    return result


@dataclass(frozen=True)
class _Evidence:
    issued: tuple[IssuedPayment, ...]
    purchases: tuple[ClassroomPurchase, ...]
    unlinked: int
    ambiguous: int
    # exact reference -> review keys of the requests recorded with it
    linked: Mapping[str, tuple[str, ...]]


def _evidence(
    reimbursements: ReimbursementFacts,
    bundle: ReimbursementReport,
    policy: PlanningPolicy,
    ledger: AcademicLedger,
    period: Period,
) -> _Evidence:
    """Issued-but-unposted classroom payments and larger purchases from the review bundle."""
    posted: dict[str, int] = defaultdict(int)
    for row in ledger.rows:
        reference = reference_key(row.payment_reference)
        if reference is not None and row.payment_date <= period.as_of:
            posted[reference] += 1
    descriptions = {
        (ticket.review_key, item.item_key): (item.display_item or item.source_description).strip()
        for ticket in bundle.tickets
        for item in ticket.items
    }
    classroom_items: dict[str, list[ReimbursementItemFact]] = defaultdict(list)
    for item in reimbursements.items:
        if (
            item.status == _APPROVED
            and item.amount is not None
            and item.expense_bucket == _CURRENT
            and policy.is_classroom(item.category)
        ):
            classroom_items[item.review_key].append(item)
    linked: dict[str, list[str]] = defaultdict(list)
    posted_tickets: set[str] = set()
    issued: list[IssuedPayment] = []
    unlinked = ambiguous = 0
    for join in reimbursements.joins:
        items = classroom_items.get(join.review_key)
        if not items or join.payment_date is None:
            continue
        if period.position(join.payment_date) != _CURRENT:
            continue
        reference = reference_key(join.reference)
        if reference is None:
            unlinked += 1
            continue
        if posted.get(reference):
            posted_tickets.add(join.review_key)
            linked[reference].append(join.review_key)
            ambiguous += int(posted[reference] > 1)
            continue
        issued.append(
            IssuedPayment(
                review_key=join.review_key,
                ticket_ref=join.ticket_ref,
                payment_date=join.payment_date,
                reference=(join.reference or "").strip(),
                amount=sum((item.amount for item in items if item.amount is not None), _ZERO),
                item_keys=tuple(item.item_key for item in items),
            )
        )
    purchases: list[ClassroomPurchase] = []
    for items in classroom_items.values():
        for item in items:
            if (
                item.payment_bucket not in (_PRIOR, _CURRENT)
                or item.expense_date is None
                or item.amount is None
                or item.amount <= 0
            ):
                continue
            purchases.append(
                ClassroomPurchase(
                    review_key=item.review_key,
                    ticket_ref=item.ticket_ref,
                    item_key=item.item_key,
                    expense_date=item.expense_date,
                    category=item.category,
                    description=descriptions.get((item.review_key, item.item_key), "")
                    or item.category,
                    amount=item.amount,
                    posted=item.review_key in posted_tickets,
                )
            )
    purchases.sort(key=lambda p: (-p.amount, p.expense_date, p.ticket_ref, p.item_key))
    return _Evidence(
        issued=tuple(sorted(issued, key=lambda i: (i.payment_date, i.ticket_ref, i.review_key))),
        purchases=tuple(purchases),
        unlinked=unlinked,
        ambiguous=ambiguous,
        linked={key: tuple(sorted(value)) for key, value in linked.items()},
    )


def _rows(
    classes: Sequence[RosterClass],
    payments: Sequence[ClassroomPayment] | None,
) -> tuple[ClassroomRow, ...]:
    labels = _labels(classes)
    by_class: dict[str, list[tuple[str, str, Decimal]]] = defaultdict(list)
    for payment in payments or ():
        for item in payment.assignments:
            by_class[item.class_id].append(
                (payment.ref.record_key, payment.ref.revision_hash, item.amount)
            )
    return tuple(
        ClassroomRow(
            class_id=item.class_id,
            teacher_label=item.teacher_label,
            label=labels[item.class_id],
            eligible=item.eligible,
            student_count=item.student_count,
            per_student_amount=item.per_student_amount,
            effective_start=item.effective_start,
            effective_end=item.effective_end,
            allocation=_allocation(item),
            paid=None
            if payments is None
            else sum((amount for _, _, amount in by_class[item.class_id]), _ZERO),
            payments=tuple(by_class[item.class_id]),
        )
        for item in classes
    )


def _covered(reference: PlanningReferenceCapture, period: Period) -> bool:
    """Declared ledger coverage spans the school year from its start through the as-of date."""
    through = min(period.as_of, period.end_inclusive)
    return reference.coverage_start <= period.start and reference.coverage_end >= through


def _issue(counts: Mapping[str, int]) -> tuple[FactIssue, ...]:
    return tuple(
        FactIssue(code, counts[code]) for code in CLASSROOM_FINDING_CODES if counts.get(code)
    )


def classroom_facts(
    planning: PlanningCapture | None,
    period: Period,
    reimbursements: ReimbursementFacts,
    bundle: ReimbursementReport,
    budget_lines: Sequence[BudgetLine],
) -> ClassroomFacts:
    """Project the Classroom Budgets facts of the school ``period`` (pure; see the module).

    ``reimbursements`` and ``bundle`` are the facts and the staged review bundle of the same
    run; ``budget_lines`` the adopted lines of the school year. Missing optional data yields
    an ``unavailable`` or ``partial`` section with findings; corrupt supplied data raises
    :class:`PlanningError`.
    """
    if planning is None:
        return absent_classroom()
    policy = read_policy(planning)
    if policy.fiscal_year != period.year_label:
        return _unavailable(_YEAR_MISMATCH, planning=planning, policy=policy)
    roster = tuple(item for item in policy.classes if _active(item, period))
    active = frozenset(item.class_id for item in roster)
    counts: dict[str, int] = defaultdict(int)
    counts[_OUTSIDE_PERIOD] = len(policy.classes) - len(roster)
    if not roster:
        counts[_ROSTER_EMPTY] = 1
    if not policy.roster_complete:
        counts[_ROSTER_INCOMPLETE] = 1
    counts[_ALLOCATION_MISSING] = sum(
        1 for item in roster if item.eligible and _allocation(item) is None
    )
    references = {item.role: item for item in planning.references}
    reference = references.get(ACADEMIC_LEDGER_ROLE)
    if reference is None or not policy.classroom_categories:
        code = _LEDGER_ABSENT if reference is None else _CATEGORIES_ABSENT
        return _unavailable(
            code,
            planning=planning,
            policy=policy,
            classes=_rows(roster, None),
            extra=_issue(counts),
        )
    ledger = read_academic_ledger(reference)
    evidence = _evidence(reimbursements, bundle, policy, ledger, period)
    attribution = _attribute(ledger, policy, period, active, evidence.linked)
    payments = attribution.payments
    allocation_keys = {(a.record_key, a.revision_hash) for a in policy.payment_allocations}
    period_keys = {(a.record_key, a.revision_hash) for a in policy.period_allocations}
    counts[_ALLOCATION_UNUSED] = len(allocation_keys - attribution.used_allocations)
    counts[_PERIOD_UNUSED] = len(period_keys - attribution.used_periods)
    counts[_OUTSIDE_PERIOD] += attribution.outside_period
    counts[_UNASSIGNED] = sum(1 for payment in payments if payment.unassigned)
    counts[_CATEGORY_UNMAPPED] = attribution.excluded.get(_UNMAPPED_ROW, 0)
    # An unreadable row whose category is blank, unmapped or classroom could be classroom.
    counts[_ROWS_UNREADABLE] = sum(
        1
        for category in ledger.unreadable_categories
        if not category or policy.budget_category(category) is None or policy.is_classroom(category)
    )
    counts[_DUPLICATE_IDENTITY] = ledger.duplicates
    covered = _covered(reference, period)
    counts[_COVERAGE_PARTIAL] = int(not covered)
    counts[_ISSUED] = len(evidence.issued)
    counts[_UNLINKED] = evidence.unlinked
    counts[_REFERENCE_AMBIGUOUS] = evidence.ambiguous
    envelope = _envelope(budget_lines, policy.classroom_categories)
    counts[_BUDGET_UNKNOWN] = int(envelope is None)
    findings = _issue(counts)
    status = _PARTIAL if any(issue.code in _PARTIAL_CODES for issue in findings) else _COMPLETE
    facts = ClassroomFacts(
        status=status,
        fiscal_year=policy.fiscal_year,
        roster_complete=policy.roster_complete,
        roster_as_of=policy.roster_as_of,
        planning_sha256=planning.sha256,
        ledger_sha256=reference.sha256,
        ledger_coverage=(reference.coverage_start, reference.coverage_end),
        ledger_coverage_complete=covered,
        classes=_rows(roster, payments),
        payments=tuple(payments),
        issued_unposted=evidence.issued,
        purchases=evidence.purchases,
        adopted_envelope=envelope,
        excluded=tuple(
            (reason, attribution.excluded[reason])
            for reason in CLASSROOM_EXCLUSIONS
            if attribution.excluded.get(reason)
        ),
        findings=findings,
    )
    _check(facts)
    return facts


def _check(facts: ClassroomFacts) -> None:
    """The conservation invariants every Classroom Budgets figure rests on."""
    for payment in facts.payments:
        parts = sum((item.amount for item in payment.assignments), _ZERO)
        if parts + payment.unassigned != payment.amount:  # pragma: no cover - by construction
            raise PlanningError(_ALLOCATION_MISMATCH, "a payment's parts do not sum to it")
    by_class = sum((row.paid or _ZERO for row in facts.classes), _ZERO)
    if by_class + facts.unassigned != facts.source_total:  # pragma: no cover - by construction
        raise PlanningError(
            _ALLOCATION_MISMATCH, "classroom payments do not reconcile to assigned plus unassigned"
        )
