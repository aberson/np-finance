"""School-year and calendar-year fact projections for the Main Report Set.

:func:`build` is the pure step between the adjusted ledger
(:func:`pta_finance.main_reports.adjustments.project`) and rendering
(``docs/plan-reference/cfo-main-report-set.md`` sections 5, 6B, 6E and 10).
:func:`build_from` is its production caller over one captured input set.

Signature note: section 10 names ``facts.build(ledger, bundle, budgets, periods)``. ``build``
keeps those four positional inputs and adds two REQUIRED keywords: ``captures`` (the same
input set's source captures, the only carrier of declared coverage evidence, which decides
whether a total is complete or partial) and ``crosswalk`` (the configured versioned
crosswalk, verified against the one the reconciliation used). Both are required so a caller
can never silently omit coverage or remap categories. :func:`build_from` derives every
argument from one capture set, the adjusted ledger, the bundle and the config.

* **Periods.** School summaries use the configured reporting-year start month (July 1 -
  June 30); the CFO P&L uses January 1 - December 31 (:func:`reporting_periods`). Filters are
  half-open and clipped to the as-of date. The budget-year configuration is read, never
  changed, and stored fiscal-year labels and IDs are never rewritten.
* **Bank basis.** Source and adjusted P&L views of both periods follow the one source P&L
  rule (monthly category nets). Coverage gaps mark a view partial; a blank month is never
  treated as zero.
* **Reimbursements.** Every item is placed by its own expense date (missing dates stay in a
  visible ``undated`` bucket, never guessed) and, separately, by its ticket's payment date,
  so cross-year claims split at item level and a June expense paid in July is a prior-year
  expense with a current-year payment, never counted twice. Every unsettled ticket stays in
  the queue whatever its dates. A recorded payment joins a bank row only on an exact
  whole-token reference plus corroborating amount and date; the bundle's adjudication,
  payment state, item keys and receipt annotations are read, never changed, and its mail
  collection window is reported as is. The bundle is refreshed on its own cadence, so its
  as-of date is carried as freshness information (``bundle_as_of``); it becomes a visible
  ``bundle_as_of_outside_period`` issue only when it is AFTER the report as-of date
  (evidence from the future) or BEFORE the school-year start (evidence older than the
  whole period). Neither is a failure.
* **Payment findings.** A ticket is PRIOR-PAID when its payment status is the legacy
  ``PAID_PRIOR`` or its payment date precedes the period. A prior-paid ticket needs no
  date or reference: neither a missing payment date nor a missing reference is a finding.
  For every other paid ticket, both are findings. A recorded reference that matches no
  bank row (``unmatched``) or several (``ambiguous``) is ALWAYS a finding, whatever the
  period. Only when every bank source DECLARES coverage and the whole corroborating
  window (payment date .. +PAYMENT_CLEARING_DAYS) lies outside all of it is the result
  ``outside_capture_window`` (informational: no declared capture could prove it). A
  window inside declared coverage with no bank match stays ``unmatched`` even for a
  quiet account, and unknown or partial coverage is never informational. References
  match as whole tokens, ignoring case (``reconcile.reference_token``).
* **Budget and fundraising.** Adopted annual targets (never ``to_inputs`` synthetic dates)
  sit beside crosswalked bank-basis actuals; an actual is a number only when it is observed
  (crosswalk configured, category mapped, coverage complete), otherwise unknown with a
  reason. Processor gross/fee/refund/net count each movement once and stay separate from,
  never added to, the bank view.
* **Bridges.** Every scope, adjustment, window, recognition and payment difference is a
  :class:`~pta_finance.main_reports.models.Bridge` whose rows link to source refs,
  adjustment IDs or item keys; residuals are computed, never forced to zero.

Nothing here reads or writes a workbook or a file. Error and issue text names codes, counts
and positions only, never a money or cell value.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from pta_finance import report_source
from pta_finance.config import CategoryCrosswalk, Config
from pta_finance.main_reports.adjustments import read_journal, require_publishable
from pta_finance.main_reports.models import (
    ALLOCATION_ORIGINS,
    BUDGET_ACTUAL_STATUSES,
    CARRYOVER_BASES,
    EXPENSE_BUCKETS,
    PAYMENT_BUCKETS,
    PAYMENT_JOIN_STATES,
    PERIOD_BASES,
    RECONCILIATION_STATES,
    TRANSACTION_KINDS,
    VIEW_BASES,
    AdjustedLedger,
    AdoptedBudget,
    Bridge,
    BridgeRow,
    BudgetFacts,
    BudgetLine,
    CaptureSet,
    CoverageFlag,
    CoverageStatus,
    FactIssue,
    FundraisingCategory,
    FundraisingTotals,
    PaymentJoin,
    Period,
    PnlView,
    QueueEntry,
    Reconciliation,
    ReimbursementFacts,
    ReimbursementItemFact,
    ReimbursementTotal,
    ReportFacts,
    ReportingPeriods,
    SourceCapture,
    SourceRef,
    Transaction,
    month_totals_from,
    monthly_cells_from,
)
from pta_finance.main_reports.reconcile import (
    INTERNAL_TRANSFER_CATEGORY,
    MIN_SETTLEMENT_REFERENCE_LENGTH,
    crosswalk_amounts,
    crosswalk_digest,
    reference_token,
)
from pta_finance.main_reports.sources import coverage_status, parse_money
from pta_finance.reimbursement_report import (
    STATUS_META,
    LiveState,
    ReimbursementReport,
    ReviewItem,
    Ticket,
)

__all__ = [
    # constants
    "PAYMENT_CLEARING_DAYS",
    "MIN_CHECK_REFERENCE_LENGTH",
    "RECORDED_PAYMENT_EVENT",
    "APPROVED_STATUS",
    "BRIDGE_NAMES",
    "BRIDGE_ROW_KINDS",
    "ISSUE_CODES",
    "COVERAGE_PARTIAL_CODES",
    "FUNDRAISING_LIMITS",
    "BUDGET_LINE_TYPES",
    # functions
    "reporting_periods",
    "build",
    "build_from",
    # types
    "FactsError",
]

# A bank row corroborates a recorded reimbursement payment only when it posts this many days
# after the recorded payment date, or fewer (checks clear later than electronic payments).
PAYMENT_CLEARING_DAYS = 45
# A payment reference shorter than this is never matched in a bank CHECK # cell (check
# numbers are short, so the floor is lower than the free-text description floor,
# reconcile.MIN_SETTLEMENT_REFERENCE_LENGTH). Both use whole-token boundaries.
MIN_CHECK_REFERENCE_LENGTH = 3
# The bundle's event kind for an exact, adjudicated payment (reimbursement_report validates it).
RECORDED_PAYMENT_EVENT = "PAYMENT_RECORDED"

_SCHOOL, _CALENDAR = PERIOD_BASES
_SOURCE_VIEW, _ADJUSTED_VIEW = VIEW_BASES
_PRIOR, _CURRENT, _LATER, _UNDATED = EXPENSE_BUCKETS
_UNPAID = PAYMENT_BUCKETS[0]
_MATCHED, _UNMATCHED, _AMBIGUOUS, _NO_REFERENCE, _OUTSIDE_CAPTURE = PAYMENT_JOIN_STATES
_OBSERVED, _ACTUAL_AMBIGUOUS, _CROSSWALK_MISSING, _CATEGORY_UNMAPPED, _ACTUAL_PARTIAL = (
    BUDGET_ACTUAL_STATUSES
)
_BY_EXPENSE_DATE, _BY_SUBMISSION = CARRYOVER_BASES
_SOURCE_ORIGIN = ALLOCATION_ORIGINS[0]
_BANK = TRANSACTION_KINDS[0]
_ZERO = Decimal("0.00")

# Bundle vocabulary read here (owned by reimbursement_report, which spells it inline): the
# approved item status, the item statuses that are no obligation (declined, informational)
# and the three ticket payment statuses. An unknown payment status fails closed at build.
APPROVED_STATUS = "A"
_APPROVED = APPROVED_STATUS
_NOT_OBLIGATION = frozenset({"D", "-"})
_NOT_PAID, _PAID, _PAID_PRIOR = "NOT_PAID", "PAID", "PAID_PRIOR"
_PAYMENT_STATUSES = frozenset({_NOT_PAID, _PAID, _PAID_PRIOR})
# Reconciliation states whose processor rows count as one movement each.
_PRIMARY, _FEE, _REFUND, _CONFLICT = (
    "processor_primary",
    "processor_fee",
    "processor_refund",
    "conflict",
)
if (
    _APPROVED not in STATUS_META
    or not _NOT_OBLIGATION <= set(STATUS_META)
    or not {_PRIMARY, _FEE, _REFUND, _CONFLICT} <= set(RECONCILIATION_STATES)
    or not set(EXPENSE_BUCKETS) <= set(PAYMENT_BUCKETS)
):  # pragma: no cover - import-time invariant
    raise RuntimeError("facts vocabulary must match its owning modules")

BRIDGE_NAMES: tuple[str, ...] = (
    "school_source_scope",
    "calendar_source_scope",
    "school_adjustments",
    "calendar_adjustments",
    "calendar_to_school",
    "school_expense_basis",
    "school_budget_crosswalk",
    "school_payment_timing",
)
(
    _SCHOOL_SCOPE,
    _CALENDAR_SCOPE,
    _SCHOOL_ADJUSTMENTS,
    _CALENDAR_ADJUSTMENTS,
    _CALENDAR_TO_SCHOOL,
    _EXPENSE_BASIS,
    _BUDGET_CROSSWALK,
    _PAYMENT_TIMING,
) = BRIDGE_NAMES


# Bucket-named row kinds: the ONE spelling of each template, used to build the explanation
# table and to emit the rows.
def _matched_kind(bucket: str) -> str:
    return f"matched_payment_{bucket}_items"


def _paid_kind(bucket: str) -> str:
    return f"paid_in_period_expense_{bucket}"


def _approved_kind(bucket: str) -> str:
    return f"approved_in_period_payment_{bucket}"


_REMAINDER = "matched_payment_remainder"
_JOINED_EXPENSE = "joined_item_expense"

# kind -> fixed explanation (never a value).
BRIDGE_ROW_KINDS: Mapping[str, str] = {
    "before_period": "Source activity dated before the period start.",
    "after_period": "Source activity dated after the period end or the as-of date.",
    "adjustment": "Recorded reporting adjustment(s) in effect on the as-of date.",
    "only_in_target_period": "Activity inside the target period but outside the base period.",
    "only_in_base_period": "Activity inside the base period but outside the target period.",
    **{
        _matched_kind(bucket): (
            "Bank payment joined to a recorded reimbursement payment, removed from the "
            f"expense basis: the part paying items whose expense date is {bucket}."
        )
        for bucket in EXPENSE_BUCKETS
    },
    _REMAINDER: (
        "Bank payment joined to a recorded reimbursement payment, removed from the expense "
        "basis: the part not explained by priced paid items."
    ),
    _JOINED_EXPENSE: (
        "Approved items of joined reimbursement payments, placed by item expense date."
    ),
    "unmapped_category": "Source category with no crosswalk entry; in no budget line.",
    **{
        _paid_kind(bucket): f"Paid in the period for items whose expense date is {bucket}."
        for bucket in EXPENSE_BUCKETS
        if bucket != _CURRENT
    },
    **{
        _approved_kind(bucket): f"Approved items dated in the period whose payment is {bucket}."
        for bucket in PAYMENT_BUCKETS
        if bucket != _CURRENT
    },
}

ISSUE_CODES: tuple[str, ...] = (
    "reimbursement_item_undated",
    "reimbursement_item_unpriced",
    "reimbursement_payment_undated",
    "reimbursement_payment_unmatched",
    "reimbursement_payment_ambiguous",
    "reimbursement_payment_no_reference",
    "bundle_as_of_outside_period",
    "budget_year_unreadable",
    "budget_type_unrecognized",
    "budget_amount_missing",
    "budget_amount_unreadable",
    "budget_line_ambiguous",
    "budget_actual_unknown",
    "processor_rows_excluded",
)
(
    _ITEM_UNDATED,
    _ITEM_UNPRICED,
    _PAYMENT_UNDATED,
    _PAYMENT_UNMATCHED,
    _PAYMENT_AMBIGUOUS,
    _PAYMENT_NO_REFERENCE,
    _BUNDLE_AS_OF,
    _BUDGET_YEAR,
    _BUDGET_TYPE,
    _BUDGET_MISSING,
    _BUDGET_UNREADABLE,
    _BUDGET_AMBIGUOUS,
    _BUDGET_ACTUAL_UNKNOWN,
    _PROCESSOR_EXCLUDED,
) = ISSUE_CODES
# Join states that are findings (``matched`` and ``outside_capture_window`` are not).
_JOIN_ISSUES: Mapping[str, str] = {
    _UNMATCHED: _PAYMENT_UNMATCHED,
    _AMBIGUOUS: _PAYMENT_AMBIGUOUS,
    _NO_REFERENCE: _PAYMENT_NO_REFERENCE,
}

# Coverage flags added per period basis when declared evidence does not cover the window.
COVERAGE_PARTIAL_CODES: Mapping[str, str] = {
    _SCHOOL: "school_coverage_partial",
    _CALENDAR: "calendar_coverage_partial",
}
_BANK_ABSENT = "bank_coverage_absent"

# Why a processor alias's fundraising totals are incomplete.
FUNDRAISING_LIMITS: tuple[str, ...] = (
    "processor_view_inconsistent",
    "processor_gross_unsettled",
    "coverage_partial",
    "rows_excluded",
)
_INCONSISTENT, _UNSETTLED, _COVERAGE_PARTIAL, _ROWS_EXCLUDED = FUNDRAISING_LIMITS

# Recognized adopted budget line types.
BUDGET_LINE_TYPES: tuple[str, ...] = ("income", "expense")
_BUDGET_TYPES = frozenset(BUDGET_LINE_TYPES)


# --------------------------------------------------------------------------------------
# Errors, periods and input checks
# --------------------------------------------------------------------------------------


class FactsError(Exception):
    """Fact projection input invariant broken. Carries a stable ``code``; its text never
    carries a money or cell value.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _period(basis: str, as_of: date, start_month: int) -> Period:
    year = as_of.year if as_of.month >= start_month else as_of.year - 1
    return Period(
        basis=basis,
        start=date(year, start_month, 1),
        end_exclusive=date(year + 1, start_month, 1),
        as_of=as_of,
    )


def reporting_periods(as_of: date, start_month: int) -> ReportingPeriods:
    """The school year (starting in ``start_month``) and calendar year containing ``as_of``.

    ``start_month`` is the configured ``fiscal_year.start_month``; it is read, never changed.
    """
    if not 1 <= start_month <= 12:
        raise FactsError("start_month_invalid", "the reporting start month must be in 1..12")
    return ReportingPeriods(
        school=_period(_SCHOOL, as_of, start_month),
        calendar=_period(_CALENDAR, as_of, 1),
    )


def _check_periods(ledger: AdjustedLedger, periods: ReportingPeriods) -> None:
    for basis, period in ((_SCHOOL, periods.school), (_CALENDAR, periods.calendar)):
        expected_end = date(period.start.year + 1, period.start.month, 1)
        if (
            period.basis != basis
            or period.start.day != 1
            or period.end_exclusive != expected_end
            or (basis == _CALENDAR and period.start.month != 1)
        ):
            raise FactsError("periods_invalid", f"the {basis} period is not one whole year")
        if period.as_of != ledger.as_of:
            raise FactsError(
                "as_of_mismatch", f"the {basis} period and the adjusted ledger differ in as-of"
            )
        if period.as_of < period.start:
            raise FactsError("periods_invalid", f"the {basis} period starts after its as-of")


def _check_captures(ledger: AdjustedLedger, captures: Sequence[SourceCapture]) -> None:
    hashes = {capture.sha256 for capture in captures}
    unknown = sum(
        1
        for txn in ledger.source.transactions
        for ref in txn.refs
        if ref.snapshot_sha256 not in hashes
    )
    if unknown:
        raise FactsError(
            "capture_mismatch", f"{unknown} source ref(s) name no capture of this input set"
        )


def _check_crosswalk(source: Reconciliation, crosswalk: CategoryCrosswalk | None) -> None:
    """The caller's crosswalk must be the one the reconciliation applied.

    Checked two ways: the digest of the WHOLE crosswalk content, version included (so a
    category that only an adjustment introduces cannot be remapped under the same version),
    and the reproduction of every reconciled crosswalk cell (so the reconciliation's own
    cells really follow from that crosswalk).
    """
    if crosswalk_digest(crosswalk) != source.crosswalk_sha256:
        raise FactsError(
            "crosswalk_mismatch", "the crosswalk content differs from the reconciliation's"
        )
    if crosswalk is None:
        return
    entries = {entry.source_category: entry for entry in crosswalk.entries}
    expected = [
        (cell.category, cell.month, category, amount)
        for cell in source.monthly_cells
        if cell.category in entries
        for category, amount in crosswalk_amounts(cell.net, entries[cell.category].targets)
    ]
    recorded = [
        (cell.source_category, cell.month, cell.target_category, cell.amount)
        for cell in source.crosswalk_cells
    ]
    if expected != recorded:
        raise FactsError(
            "crosswalk_mismatch", "the crosswalk does not reproduce the reconciled crosswalk cells"
        )


def _check_bundle(bundle: ReimbursementReport) -> None:
    unknown = sum(1 for t in bundle.tickets if t.live.payment_status not in _PAYMENT_STATUSES)
    if unknown:
        raise FactsError(
            "payment_status_unrecognized", f"{unknown} ticket(s) have an unknown payment status"
        )


# --------------------------------------------------------------------------------------
# Bank-basis views
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    """One counted signed bank allocation with its date and evidence."""

    day: date
    category: str
    amount: Decimal
    refs: tuple[SourceRef, ...]
    record_key: str | None


def _source_lines(source: Reconciliation) -> list[_Line]:
    by_key = {txn.record_key: txn for txn in source.transactions}
    lines: list[_Line] = []
    for allocation in source.allocations:
        txn = by_key[allocation.record_key]
        if txn.posting_date is None:
            raise FactsError("bank_row_undated", "a counted bank allocation has no posting date")
        lines.append(
            _Line(
                txn.posting_date,
                allocation.category,
                allocation.amount,
                (txn.refs[0],),
                txn.record_key,
            )
        )
    return lines


def _adjusted_lines(ledger: AdjustedLedger) -> list[_Line]:
    return [
        _Line(
            item.posting_date,
            item.category,
            item.amount,
            () if item.ref is None else (item.ref,),
            item.record_key,
        )
        for item in ledger.allocations
        if item.counted
    ]


def _net(lines: Iterable[_Line]) -> Decimal:
    return sum((line.amount for line in lines), _ZERO)


def _unique_refs(refs: Iterable[SourceRef]) -> tuple[SourceRef, ...]:
    return tuple(dict.fromkeys(refs))


def _row(
    kind: str,
    amount: Decimal,
    *,
    refs: Iterable[SourceRef] = (),
    adjustment_ids: Sequence[str] = (),
    item_keys: Sequence[str] = (),
) -> BridgeRow:
    return BridgeRow(
        kind=kind,
        amount=amount,
        explanation=BRIDGE_ROW_KINDS[kind],
        refs=_unique_refs(refs),
        adjustment_ids=tuple(adjustment_ids),
        item_keys=tuple(item_keys),
    )


def _inside(period: Period, lines: Iterable[_Line]) -> list[_Line]:
    return [line for line in lines if period.position(line.day) == _CURRENT]


def _view(period: Period, view: str, lines: Sequence[_Line], complete: bool) -> PnlView:
    cells = monthly_cells_from(
        (line.day, line.category, line.amount, line.refs) for line in _inside(period, lines)
    )
    months = month_totals_from(cells)
    return PnlView(
        basis=period.basis,
        view=view,
        cells=cells,
        months=months,
        income=sum((month.income for month in months), _ZERO),
        expense=sum((month.expense for month in months), _ZERO),
        net=sum((month.net for month in months), _ZERO),
        complete=complete,
    )


def _scope_bridge(
    name: str, period: Period, source: Reconciliation, lines: Sequence[_Line], view: PnlView
) -> Bridge:
    """Every captured source P&L month -> this period's source view."""
    rows: list[BridgeRow] = []
    for position, kind in ((_PRIOR, "before_period"), (_LATER, "after_period")):
        members = [line for line in lines if period.position(line.day) == position]
        if members:
            refs = (ref for line in members for ref in line.refs)
            rows.append(_row(kind, -_net(members), refs=refs))
    return Bridge(
        name=name,
        from_label="source_pnl_all_months_net",
        from_amount=sum((total.net for total in source.pnl_totals), _ZERO),
        to_label=f"{period.basis}_source_net",
        to_amount=view.net,
        rows=tuple(rows),
    )


def _adjustment_bridge(
    name: str, period: Period, ledger: AdjustedLedger, source: PnlView, adjusted: PnlView
) -> Bridge:
    """This period's source view -> adjusted view, one row per adjustment group.

    Each adjusted allocation keeps its source amount, category and date beside it, so the
    in-period difference it makes is exact and attributed to the entries that changed it. An
    unattributed difference is never given a row: it remains in the residual.
    """
    amounts: dict[tuple[str, ...], Decimal] = defaultdict(lambda: _ZERO)
    refs: dict[tuple[str, ...], list[SourceRef]] = defaultdict(list)
    for item in ledger.allocations:
        after = (
            item.amount
            if item.counted and period.position(item.posting_date) == _CURRENT
            else _ZERO
        )
        before = (
            item.source_amount
            if item.origin == _SOURCE_ORIGIN
            and item.source_category != INTERNAL_TRANSFER_CATEGORY
            and period.position(item.source_date) == _CURRENT
            else _ZERO
        )
        if after != before and item.adjustment_ids:
            amounts[item.adjustment_ids] += after - before
            if item.ref is not None:
                refs[item.adjustment_ids].append(item.ref)
    rows = tuple(
        _row("adjustment", amount, refs=refs[ids], adjustment_ids=ids)
        for ids, amount in sorted(amounts.items())
        if amount != _ZERO
    )
    return Bridge(
        name=name,
        from_label=f"{period.basis}_source_net",
        from_amount=source.net,
        to_label=f"{period.basis}_adjusted_net",
        to_amount=adjusted.net,
        rows=rows,
    )


def _window_bridge(
    lines: Sequence[_Line], base: Period, base_view: PnlView, target: Period, target_view: PnlView
) -> Bridge:
    """The adjusted calendar-year view -> the adjusted school-year view."""
    only_target = [
        line
        for line in lines
        if target.position(line.day) == _CURRENT and base.position(line.day) != _CURRENT
    ]
    only_base = [
        line
        for line in lines
        if base.position(line.day) == _CURRENT and target.position(line.day) != _CURRENT
    ]
    rows: list[BridgeRow] = []
    for kind, members, sign in (
        ("only_in_target_period", only_target, 1),
        ("only_in_base_period", only_base, -1),
    ):
        if members:
            rows.append(_row(kind, sign * _net(members), refs=(r for m in members for r in m.refs)))
    return Bridge(
        name=_CALENDAR_TO_SCHOOL,
        from_label=f"{base.basis}_adjusted_net",
        from_amount=base_view.net,
        to_label=f"{target.basis}_adjusted_net",
        to_amount=target_view.net,
        rows=tuple(rows),
    )


def _coverage(
    periods: ReportingPeriods, captures: Sequence[SourceCapture]
) -> tuple[tuple[CoverageStatus, ...], dict[tuple[str, str], bool]]:
    """Declared coverage of every transaction source over each clipped period window."""
    statuses: list[CoverageStatus] = []
    complete: dict[tuple[str, str], bool] = {}
    for period in (periods.school, periods.calendar):
        for capture in captures:
            if capture.kind not in TRANSACTION_KINDS:
                continue
            status = coverage_status(capture, period.start, period.clip_end)
            statuses.append(status)
            complete[(period.basis, capture.alias)] = status.complete
    return tuple(statuses), complete


# --------------------------------------------------------------------------------------
# Reimbursements
# --------------------------------------------------------------------------------------


def _item_facts(bundle: ReimbursementReport, period: Period) -> list[ReimbursementItemFact]:
    facts: list[ReimbursementItemFact] = []
    for ticket in bundle.tickets:
        live = ticket.live
        ticket_paid = live.payment_status != _NOT_PAID
        for item in ticket.items:
            paid = ticket_paid and item.status == _APPROVED
            expense_date = item.effective_date
            facts.append(
                ReimbursementItemFact(
                    review_key=ticket.review_key,
                    ticket_ref=ticket.ref,
                    origin=ticket.origin,
                    item_key=item.item_key,
                    category=item.canonical_category,
                    status=item.status,
                    amount=item.effective_amount,
                    expense_date=expense_date,
                    expense_bucket=period.position(expense_date),
                    received=ticket.submitted,
                    payment_status=live.payment_status,
                    payment_date=live.payment_date,
                    payment_bucket=period.position(live.payment_date) if paid else _UNPAID,
                    open=not ticket.is_closed,
                )
            )
    return facts


def _totals(items: Sequence[ReimbursementItemFact]) -> tuple[ReimbursementTotal, ...]:
    groups: dict[tuple[str, str, str, bool], list[ReimbursementItemFact]] = defaultdict(list)
    for item in items:
        groups[(item.expense_bucket, item.payment_bucket, item.status, item.open)].append(item)
    statuses = list(STATUS_META)
    order = sorted(
        groups,
        key=lambda key: (
            EXPENSE_BUCKETS.index(key[0]),
            PAYMENT_BUCKETS.index(key[1]),
            statuses.index(key[2]),
            key[3],
        ),
    )
    return tuple(
        ReimbursementTotal(
            expense_bucket=key[0],
            payment_bucket=key[1],
            status=key[2],
            open=key[3],
            count=len(groups[key]),
            amount=sum((i.amount for i in groups[key] if i.amount is not None), _ZERO),
            unpriced=sum(1 for i in groups[key] if i.amount is None),
        )
        for key in order
    )


def _obligations(ticket: Ticket) -> list[ReviewItem]:
    """The ONE obligation-item rule: every item except declined and informational lines.

    Shared by the carryover flag, the earliest expense date and the undated-item count.
    """
    return [item for item in ticket.items if item.status not in _NOT_OBLIGATION]


def _carryover(ticket: Ticket, period: Period) -> str | None:
    """The :data:`CARRYOVER_BASES` reason an outstanding request is a prior-year carryover.

    Only obligation items count (declined and informational lines do not). A prior-year
    expense date decides first; otherwise an UNDATED obligation item on a request submitted
    before the period start is prior-year too, because an expense never postdates the
    request that claims it.
    """
    obligations = _obligations(ticket)
    if any(period.position(item.effective_date) == _PRIOR for item in obligations):
        return _BY_EXPENSE_DATE
    undated = any(item.effective_date is None for item in obligations)
    if undated and period.position(ticket.submitted) == _PRIOR:
        return _BY_SUBMISSION
    return None


def _queue(bundle: ReimbursementReport, period: Period) -> tuple[QueueEntry, ...]:
    entries: list[QueueEntry] = []
    for ticket in bundle.active_tickets:
        obligations = _obligations(ticket)
        dates = [item.effective_date for item in obligations if item.effective_date is not None]
        basis = _carryover(ticket, period)
        entries.append(
            QueueEntry(
                review_key=ticket.review_key,
                ticket_ref=ticket.ref,
                origin=ticket.origin,
                submitted=ticket.submitted,
                pay_now=ticket.pay_now,
                earliest_expense_date=min(dates, default=None),
                carryover=basis is not None,
                carryover_basis=basis,
                undated_items=sum(1 for item in obligations if item.effective_date is None),
            )
        )
    return tuple(entries)


def _references(txn: Transaction, reference: str, token: re.Pattern[str]) -> bool:
    """The whole reference ``token`` in the bank CHECK # cell or description, above each floor."""
    if len(reference) >= MIN_CHECK_REFERENCE_LENGTH and token.search(txn.check_number or ""):
        return True
    return len(reference) >= MIN_SETTLEMENT_REFERENCE_LENGTH and bool(
        token.search(txn.description or "")
    )


@dataclass(frozen=True)
class _Candidate:
    ticket: Ticket
    reference: str | None
    amount: Decimal | None
    # ``None``: the ticket has no recorded payment event.
    rows: list[Transaction] | None = None
    sent: date | None = None


def _candidates(
    ticket: Ticket, bundle: ReimbursementReport, bank: Sequence[Transaction]
) -> _Candidate:
    """The recorded reference, amount and corroborating bank rows of one paid ticket."""
    events = [
        event
        for event in bundle.events_for(ticket.review_key)
        if event.kind == RECORDED_PAYMENT_EVENT
    ]
    if not events:
        return _Candidate(ticket, None, None)
    event = events[0]  # the bundle allows at most one recorded payment per ticket
    reference = event.reference.strip()
    sent, amount = event.occurred_on, event.amount
    if not reference or sent is None or amount is None:
        return _Candidate(ticket, reference or None, amount, [], sent)
    # Reimbursement references ignore case (policy owned by reconcile.reference_token).
    token = reference_token(reference, ignore_case=True)
    rows = [
        txn
        for txn in bank
        if txn.posting_date is not None
        and 0 <= (txn.posting_date - sent).days <= PAYMENT_CLEARING_DAYS
        and txn.gross == -amount
        and _references(txn, reference, token)
    ]
    return _Candidate(ticket, reference, amount, rows, sent)


def _outside(sent: date, bank_captures: Sequence[SourceCapture]) -> bool:
    """The whole ``sent .. sent + PAYMENT_CLEARING_DAYS`` window misses DECLARED coverage.

    True only when every bank capture declares coverage and none of it touches the
    window. No bank capture, or one without declared coverage, is unknown coverage: the
    payment stays unmatched (visible), never informational.
    """
    if not bank_captures or any(not capture.coverage for capture in bank_captures):
        return False
    end = sent + timedelta(days=PAYMENT_CLEARING_DAYS + 1)
    return all(
        coverage_status(capture, sent, end).uncovered == ((sent, end),) for capture in bank_captures
    )


def _joins(
    bundle: ReimbursementReport,
    source: Reconciliation,
    bank_captures: Sequence[SourceCapture],
) -> tuple[PaymentJoin, ...]:
    bank = [txn for txn in source.transactions if txn.source_kind == _BANK]
    found: list[_Candidate] = []
    claims: dict[str, int] = defaultdict(int)
    for ticket in bundle.tickets:
        if ticket.live.payment_status == _NOT_PAID:
            continue
        candidate = _candidates(ticket, bundle, bank)
        found.append(candidate)
        for row in candidate.rows or ():
            claims[row.record_key] += 1
    joins: list[PaymentJoin] = []
    for candidate in found:
        rows = candidate.rows
        sent = candidate.sent
        if rows is None:
            state = _NO_REFERENCE
        elif not rows and sent is not None and _outside(sent, bank_captures):
            state = _OUTSIDE_CAPTURE
        elif not rows:
            state = _UNMATCHED
        elif len(rows) > 1 or claims[rows[0].record_key] > 1:
            state = _AMBIGUOUS
        else:
            state = _MATCHED
        joins.append(
            PaymentJoin(
                review_key=candidate.ticket.review_key,
                ticket_ref=candidate.ticket.ref,
                state=state,
                payment_date=candidate.ticket.live.payment_date,
                reference=candidate.reference,
                amount=candidate.amount,
                bank_refs=tuple(row.refs[0] for row in rows or ()),
            )
        )
    return tuple(joins)


def _expense_basis_bridge(
    period: Period,
    lines: Sequence[_Line],
    view: PnlView,
    joins: Sequence[PaymentJoin],
    items: Sequence[ReimbursementItemFact],
) -> Bridge:
    """The adjusted school-year bank view -> an explicitly labeled expense-basis view.

    Only JOINED payments take part. A joined bank row inside the period leaves the
    comparison, and the amount removed is broken down by the expense-date bucket of the paid
    items it settled (prior, current, later, undated) plus any part no priced item explains,
    so money for items outside the period stays visible with its item keys. Paid items dated
    in the period then enter by item expense date (as outflows). Unjoined payments stay on
    the bank basis alone, so no expense and settlement is ever counted twice.
    """
    matched = [join for join in joins if join.state == _MATCHED]
    row_keys = {ref.record_key for join in matched for ref in join.bank_refs}
    inside = _inside(period, lines)
    paid = [item for item in items if item.payment_bucket != _UNPAID]
    portions: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    portion_refs: dict[str, list[SourceRef]] = defaultdict(list)
    portion_items: dict[str, list[str]] = defaultdict(list)
    for join in matched:
        keys = {ref.record_key for ref in join.bank_refs}
        removed = [line for line in inside if line.record_key in keys]
        if not removed:
            continue  # the joined bank row is outside the period: nothing leaves this view
        refs = [ref for line in removed for ref in line.refs]
        explained = _ZERO
        settled = [i for i in paid if i.review_key == join.review_key and i.amount is not None]
        for bucket in EXPENSE_BUCKETS:
            members = [item for item in settled if item.expense_bucket == bucket]
            if members:
                amount = sum((m.amount for m in members if m.amount is not None), _ZERO)
                explained += amount
                portions[_matched_kind(bucket)] += amount
                portion_refs[_matched_kind(bucket)].extend(refs)
                portion_items[_matched_kind(bucket)].extend(m.item_key for m in members)
        remainder = -_net(removed) - explained
        if remainder:
            portions[_REMAINDER] += remainder
            portion_refs[_REMAINDER].extend(refs)
    tickets = {join.review_key for join in matched}
    added = [i for i in paid if i.review_key in tickets and i.expense_bucket == _CURRENT]
    added_expense = -sum((item.amount for item in added if item.amount is not None), _ZERO)
    rows = [
        _row(kind, portions[kind], refs=portion_refs[kind], item_keys=portion_items[kind])
        for kind in (*map(_matched_kind, EXPENSE_BUCKETS), _REMAINDER)
        if kind in portions
    ]
    if added:
        rows.append(_row(_JOINED_EXPENSE, added_expense, item_keys=[i.item_key for i in added]))
    return Bridge(
        name=_EXPENSE_BASIS,
        from_label=f"{period.basis}_adjusted_net",
        from_amount=view.net,
        to_label=f"{period.basis}_expense_basis_net",
        to_amount=_net(line for line in inside if line.record_key not in row_keys) + added_expense,
        rows=tuple(rows),
    )


def _payment_timing_bridge(period: Period, facts: ReimbursementFacts) -> Bridge:
    """Approved expense dated in the period -> payments made in the period (item level)."""
    rows: list[BridgeRow] = []
    priced = [item for item in facts.items if item.amount is not None]
    for bucket in EXPENSE_BUCKETS:
        if bucket == _CURRENT:
            continue
        members = [i for i in priced if i.payment_bucket == _CURRENT and i.expense_bucket == bucket]
        if members:
            amount = sum((i.amount for i in members if i.amount is not None), _ZERO)
            rows.append(_row(_paid_kind(bucket), amount, item_keys=[i.item_key for i in members]))
    for bucket in PAYMENT_BUCKETS:
        if bucket == _CURRENT:
            continue
        members = [
            i
            for i in priced
            if i.status == _APPROVED and i.expense_bucket == _CURRENT and i.payment_bucket == bucket
        ]
        if members:
            amount = sum((i.amount for i in members if i.amount is not None), _ZERO)
            rows.append(
                _row(_approved_kind(bucket), -amount, item_keys=[i.item_key for i in members])
            )
    return Bridge(
        name=_PAYMENT_TIMING,
        from_label=f"{period.basis}_approved_expense",
        from_amount=facts.expense(_CURRENT, _APPROVED),
        to_label=f"{period.basis}_paid",
        to_amount=facts.paid(_CURRENT),
        rows=tuple(rows),
    )


def _prior_paid(live: LiveState, period: Period) -> bool:
    """Legacy ``PAID_PRIOR``, or paid before the period: needs no date or reference."""
    return live.payment_status == _PAID_PRIOR or period.position(live.payment_date) == _PRIOR


def _reimbursements(
    bundle: ReimbursementReport,
    source: Reconciliation,
    period: Period,
    bank_captures: Sequence[SourceCapture],
) -> tuple[ReimbursementFacts, list[FactIssue]]:
    items = _item_facts(bundle, period)
    queue = _queue(bundle, period)
    joins = _joins(bundle, source, bank_captures)
    facts = ReimbursementFacts(
        items=tuple(items),
        totals=_totals(items),
        queue=queue,
        outstanding=sum((entry.pay_now for entry in queue), _ZERO),
        joins=joins,
        cutoff_date=bundle.settings.cutoff_date,
        first_received=bundle.source_summary.first_received,
        last_received=bundle.source_summary.last_received,
        bundle_as_of=bundle.settings.as_of_date,
    )
    bundle_as_of = bundle.settings.as_of_date
    live = {ticket.review_key: ticket.live for ticket in bundle.tickets}
    counts = {
        _ITEM_UNDATED: sum(1 for item in items if item.expense_bucket == _UNDATED),
        _ITEM_UNPRICED: sum(1 for item in items if item.amount is None),
        _PAYMENT_UNDATED: sum(
            1
            for state in live.values()
            if state.payment_status != _NOT_PAID
            and state.payment_date is None
            and not _prior_paid(state, period)
        ),
        _BUNDLE_AS_OF: int(bundle_as_of > period.as_of or bundle_as_of < period.start),
    }
    for join in joins:
        if join.state not in _JOIN_ISSUES:
            continue
        if join.state == _NO_REFERENCE and _prior_paid(live[join.review_key], period):
            continue
        counts[_JOIN_ISSUES[join.state]] = counts.get(_JOIN_ISSUES[join.state], 0) + 1
    issues = [FactIssue(code, count) for code, count in counts.items() if count]
    return facts, issues


# --------------------------------------------------------------------------------------
# Budget and fundraising
# --------------------------------------------------------------------------------------


def _crosswalked(
    view: PnlView, crosswalk: CategoryCrosswalk | None
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Mapped budget-category and unmapped source-category totals of the period view."""
    entries = {} if crosswalk is None else {e.source_category: e for e in crosswalk.entries}
    mapped: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    unmapped: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for cell in view.cells:
        entry = entries.get(cell.category)
        if entry is None:
            unmapped[cell.category] += cell.net
            continue
        for category, amount in crosswalk_amounts(cell.net, entry.targets):
            mapped[category] += amount
    return dict(mapped), dict(unmapped)


@dataclass(frozen=True)
class _Target:
    position: int
    line_type: str
    category: str
    target: Decimal | None


def _targets(budget: AdoptedBudget, fiscal_year: int) -> tuple[list[_Target], int, list[FactIssue]]:
    """Adopted rows of ``fiscal_year`` (annual targets: no dates are attached or inferred)."""
    targets: list[_Target] = []
    other = 0
    issues: list[FactIssue] = []
    for position, row in enumerate(budget.rows_as_dicts(), 1):
        subject = f"adopted row {position}"
        try:
            year = int(row.get(report_source.FISCAL_YEAR, "").strip())
        except ValueError:
            issues.append(FactIssue(_BUDGET_YEAR, 1, subject))
            continue
        if year != fiscal_year:
            other += 1
            continue
        line_type = row.get(report_source.TYPE, "").strip().casefold()
        if line_type not in _BUDGET_TYPES:
            issues.append(FactIssue(_BUDGET_TYPE, 1, subject))
        target: Decimal | None
        try:
            target = parse_money(row.get(report_source.AMOUNT, ""))
        except ValueError:
            target = None
            issues.append(FactIssue(_BUDGET_UNREADABLE, 1, subject))
        else:
            if target is None:
                issues.append(FactIssue(_BUDGET_MISSING, 1, subject))
        category = row.get(report_source.RAW_CATEGORY, "").strip()
        targets.append(_Target(position, line_type, category, target))
    return targets, other, issues


def _actual_status(
    category: str, ambiguous: bool, crosswalk: CategoryCrosswalk | None, view: PnlView
) -> str:
    """Why a budget actual is (or is not) an observed amount; the first reason wins."""
    if ambiguous:
        return _ACTUAL_AMBIGUOUS
    if crosswalk is None:
        return _CROSSWALK_MISSING
    if category not in {t.category for entry in crosswalk.entries for t in entry.targets}:
        return _CATEGORY_UNMAPPED
    if not view.complete:
        return _ACTUAL_PARTIAL
    return _OBSERVED


def _budget(
    budget: AdoptedBudget,
    period: Period,
    view: PnlView,
    crosswalk: CategoryCrosswalk | None,
) -> tuple[BudgetFacts, Bridge, list[FactIssue]]:
    mapped, unmapped = _crosswalked(view, crosswalk)
    targets, other, issues = _targets(budget, period.year_label)
    # Actuals join on the category name alone, so a repeated name cannot take one actual.
    repeated: dict[str, int] = defaultdict(int)
    for item in targets:
        repeated[item.category] += 1
    lines: list[BudgetLine] = []
    unknown: dict[str, int] = defaultdict(int)
    for item in targets:
        ambiguous = repeated[item.category] > 1
        if ambiguous:
            issues.append(FactIssue(_BUDGET_AMBIGUOUS, 1, f"adopted row {item.position}"))
        status = _actual_status(item.category, ambiguous, crosswalk, view)
        if status != _OBSERVED:
            unknown[status] += 1
        lines.append(
            BudgetLine(
                position=item.position,
                fiscal_year=period.year_label,
                line_type=item.line_type,
                category=item.category,
                target=item.target,
                # An observed zero (mapped, complete, no activity) is 0.00; unknown is None.
                actual=mapped.get(item.category, _ZERO) if status == _OBSERVED else None,
                actual_status=status,
            )
        )
    issues.extend(
        FactIssue(_BUDGET_ACTUAL_UNKNOWN, unknown[status], status)
        for status in BUDGET_ACTUAL_STATUSES
        if unknown[status]
    )
    budgeted = {item.category for item in targets}
    facts = BudgetFacts(
        fiscal_year=period.year_label,
        crosswalk_version=None if crosswalk is None else crosswalk.version,
        lines=tuple(lines),
        mapped_actuals=tuple(sorted(mapped.items())),
        unmapped=tuple(sorted(unmapped.items())),
        unbudgeted=tuple(sorted((k, v) for k, v in mapped.items() if k not in budgeted)),
        other_year_rows=other,
    )
    unmapped_cells = [cell for cell in view.cells if cell.category in unmapped]
    rows: tuple[BridgeRow, ...] = ()
    if unmapped:
        rows = (
            _row(
                "unmapped_category",
                -sum(unmapped.values(), _ZERO),
                refs=(ref for cell in unmapped_cells for ref in cell.contributors),
            ),
        )
    bridge = Bridge(
        name=_BUDGET_CROSSWALK,
        from_label=f"{period.basis}_adjusted_net",
        from_amount=view.net,
        to_label=f"{period.basis}_budget_mapped_actuals",
        to_amount=sum(mapped.values(), _ZERO),
        rows=rows,
    )
    return facts, bridge, issues


def _fundraising(
    source: Reconciliation,
    period: Period,
    captures: Sequence[SourceCapture],
    complete: Mapping[tuple[str, str], bool],
) -> tuple[tuple[FundraisingTotals, ...], list[FactIssue]]:
    """Processor totals by payment date in the period, each movement counted once."""
    aliases = {c.alias for c in captures if c.kind in TRANSACTION_KINDS and c.kind != _BANK}
    aliases |= {t.source_alias for t in source.transactions if t.source_kind != _BANK}
    summaries = {summary.source_alias: summary for summary in source.processor_summaries}
    classes = {item.record_key: item for item in source.classifications}
    out: list[FundraisingTotals] = []
    issues: list[FactIssue] = []
    for alias in sorted(aliases):
        gross = fees = refunds = _ZERO
        payments = fee_rows = refund_rows = excluded = 0
        categories: dict[tuple[str | None, str], list[Decimal]] = defaultdict(list)
        for txn in source.transactions:
            if txn.source_kind == _BANK or txn.source_alias != alias:
                continue
            if txn.payment_date is None:
                raise FactsError("processor_row_undated", f"a {alias} row has no payment date")
            if period.position(txn.payment_date) != _CURRENT:
                continue
            state = txn.reconciliation_state
            if state == _CONFLICT:
                excluded += 1
            elif state == _PRIMARY:
                payments += 1
                sale = txn.gross if txn.gross is not None else _ZERO
                gross += sale
                fees += abs(txn.fee) if txn.fee is not None else _ZERO
                refunds += abs(txn.refund) if txn.refund is not None else _ZERO
                guidance = classes.get(txn.record_key)
                if guidance is None:
                    raise FactsError(
                        "classification_missing", f"a {alias} payment has no classification"
                    )
                # Reconciliation sets a target only for a unique keyword match.
                categories[(guidance.target_category, guidance.status)].append(sale)
            elif state == _FEE:
                fee_rows += 1
                fees += abs(txn.gross) if txn.gross is not None else _ZERO
            elif state == _REFUND:
                refund_rows += 1
                refunds += abs(txn.gross) if txn.gross is not None else _ZERO
        reasons: list[str] = []
        summary = summaries.get(alias)
        if summary is not None and not summary.consistent:
            reasons.append(_INCONSISTENT)
        if summary is not None and not summary.settled:
            reasons.append(_UNSETTLED)
        if not complete.get((period.basis, alias), False):
            reasons.append(_COVERAGE_PARTIAL)
        if excluded:
            reasons.append(_ROWS_EXCLUDED)
            issues.append(FactIssue(_PROCESSOR_EXCLUDED, excluded, alias))
        out.append(
            FundraisingTotals(
                source_alias=alias,
                gross=gross,
                fees=fees,
                refunds=refunds,
                net=gross - fees - refunds,
                payment_count=payments,
                fee_rows=fee_rows,
                refund_rows=refund_rows,
                excluded_rows=excluded,
                categories=tuple(
                    FundraisingCategory(
                        category=category,
                        classification=status,
                        count=len(amounts),
                        gross=sum(amounts, _ZERO),
                    )
                    for (category, status), amounts in sorted(
                        categories.items(), key=lambda pair: (pair[0][1], pair[0][0] or "")
                    )
                ),
                incomplete_reasons=tuple(reasons),
            )
        )
    return tuple(out), issues


# --------------------------------------------------------------------------------------
# Production entry points
# --------------------------------------------------------------------------------------


def build(
    ledger: AdjustedLedger,
    bundle: ReimbursementReport,
    budget: AdoptedBudget,
    periods: ReportingPeriods,
    *,
    captures: Sequence[SourceCapture],
    crosswalk: CategoryCrosswalk | None,
) -> ReportFacts:
    """Project one adjusted ledger, reimbursement bundle and adopted budget into facts (pure).

    ``captures`` are the source captures of the same input set (declared coverage evidence);
    ``crosswalk`` is the configured versioned crosswalk, which must be the one the
    reconciliation applied (``None`` only when it applied none). Raises
    :class:`~pta_finance.main_reports.adjustments.AdjustmentConflictError` when adjusted
    publication is blocked, and :class:`FactsError` when inputs are inconsistent
    (``periods_invalid``, ``as_of_mismatch``, ``capture_mismatch``, ``crosswalk_mismatch``,
    ``payment_status_unrecognized``, ...). Nothing in the ledger or bundle is modified;
    payment adjudication is never re-run.
    """
    require_publishable(ledger)
    _check_periods(ledger, periods)
    _check_captures(ledger, captures)
    _check_crosswalk(ledger.source, crosswalk)
    _check_bundle(bundle)
    school, calendar = periods.school, periods.calendar
    statuses, complete = _coverage(periods, captures)
    bank_aliases = [c.alias for c in captures if c.kind == _BANK]

    def bank_complete(period: Period) -> bool:
        return bool(bank_aliases) and all(complete[(period.basis, a)] for a in bank_aliases)

    source_lines = _source_lines(ledger.source)
    adjusted_lines = _adjusted_lines(ledger)
    views: dict[tuple[str, str], PnlView] = {}
    for period in (school, calendar):
        for view, lines in ((_SOURCE_VIEW, source_lines), (_ADJUSTED_VIEW, adjusted_lines)):
            views[(period.basis, view)] = _view(period, view, lines, bank_complete(period))

    bank_captures = [c for c in captures if c.kind == _BANK]
    reimbursements, issues = _reimbursements(bundle, ledger.source, school, bank_captures)
    budget_facts, budget_bridge, budget_issues = _budget(
        budget, school, views[(_SCHOOL, _ADJUSTED_VIEW)], crosswalk
    )
    fundraising, fundraising_issues = _fundraising(ledger.source, school, captures, complete)
    bridges = (
        _scope_bridge(
            _SCHOOL_SCOPE, school, ledger.source, source_lines, views[(_SCHOOL, _SOURCE_VIEW)]
        ),
        _scope_bridge(
            _CALENDAR_SCOPE,
            calendar,
            ledger.source,
            source_lines,
            views[(_CALENDAR, _SOURCE_VIEW)],
        ),
        _adjustment_bridge(
            _SCHOOL_ADJUSTMENTS,
            school,
            ledger,
            views[(_SCHOOL, _SOURCE_VIEW)],
            views[(_SCHOOL, _ADJUSTED_VIEW)],
        ),
        _adjustment_bridge(
            _CALENDAR_ADJUSTMENTS,
            calendar,
            ledger,
            views[(_CALENDAR, _SOURCE_VIEW)],
            views[(_CALENDAR, _ADJUSTED_VIEW)],
        ),
        _window_bridge(
            adjusted_lines,
            calendar,
            views[(_CALENDAR, _ADJUSTED_VIEW)],
            school,
            views[(_SCHOOL, _ADJUSTED_VIEW)],
        ),
        _expense_basis_bridge(
            school,
            adjusted_lines,
            views[(_SCHOOL, _ADJUSTED_VIEW)],
            reimbursements.joins,
            reimbursements.items,
        ),
        budget_bridge,
        _payment_timing_bridge(school, reimbursements),
    )

    flags = list(ledger.source.coverage_flags)
    if not bank_aliases:
        flags.append(CoverageFlag(code=_BANK_ABSENT))
    for period in (school, calendar):
        for capture in captures:
            key = (period.basis, capture.alias)
            if key in complete and not complete[key]:
                flags.append(
                    CoverageFlag(
                        code=COVERAGE_PARTIAL_CODES[period.basis], source_alias=capture.alias
                    )
                )
    return ReportFacts(
        as_of=ledger.as_of,
        periods=periods,
        journal_sha256=ledger.journal_sha256,
        applied_adjustments=ledger.applied,
        pnl_views=tuple(views.values()),
        bridges=bridges,
        reimbursements=reimbursements,
        budget=budget_facts,
        fundraising=fundraising,
        coverage=statuses,
        coverage_flags=tuple(sorted(flags, key=lambda f: (f.code, f.source_alias or ""))),
        issues=(*issues, *budget_issues, *fundraising_issues),
        pnl_control_status=ledger.source.pnl_control.status,
        discrepancy_ids=tuple(item.discrepancy_id for item in ledger.source.unresolved),
        pending_adjustments=ledger.pending,
        superseded_adjustments=ledger.superseded,
        adjustment_warnings=ledger.warnings,
    )


def build_from(
    capture_set: CaptureSet,
    ledger: AdjustedLedger,
    bundle: ReimbursementReport,
    config: Config,
) -> ReportFacts:
    """Production caller: facts from one captured input set and its adjusted ledger.

    Periods come from the ledger's as-of date and the configured
    ``fiscal_year.start_month`` (read, never changed); the crosswalk from ``[main_reports]``
    (verified against the reconciliation's). The ledger must have been projected from this
    capture set's journal (``journal_mismatch`` otherwise: recapture after any journal write
    before finalizing facts).
    """
    if read_journal(capture_set.assumptions).sha256 != ledger.journal_sha256:
        raise FactsError(
            "journal_mismatch", "the adjusted ledger was not projected from this capture's journal"
        )
    main_reports = config.main_reports
    return build(
        ledger,
        bundle,
        capture_set.adopted_budget,
        reporting_periods(ledger.as_of, config.fiscal_year.start_month),
        captures=capture_set.captures,
        crosswalk=None if main_reports is None else main_reports.crosswalk,
    )
