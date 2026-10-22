"""Reconcile normalized CFO feeds into a CFO-compatible source view.

:func:`build` is the pure reconciliation step between
:func:`pta_finance.main_reports.sources.normalize_with_report` and the adjustments projection
(``docs/plan-reference/cfo-main-report-set.md`` sections 5, 6A, 6C and 10).
:func:`from_capture` is its production caller over one captured input set; normalization row
warnings and incomplete Category Mapping rows are carried into the result, never dropped.

* **Source view.** Every bank row's signed FINAL CATEGORY allocations (conservation re-checked)
  are netted by category and bank DATE month, as the published P&L formula does. Only the
  EXACT category :data:`INTERNAL_TRANSFER_CATEGORY` is excluded. There is no status or
  calendar filter, so non-posted rows are counted and flagged. Income or expense follows the
  sign of each monthly category NET, never each transaction.
* **Controls.** Reproduced cells are compared with the captured published P&L. A difference,
  an unreadable cell or an unrecognized layout is a visible discrepancy, never parity.
* **Processor enrichment.** WIX/PayPal overlap pairs only on the exact provider payment ID plus
  currency and gross. PayPal detail rows are allocation evidence; fees and refunds link only
  through the exact reference ID and follow their payment's primary/secondary/conflict state.
  Processor rows never add to the bank source view. A bank settlement matches only on a
  source reference; amount/date proximity yields a candidate.
* **Crosswalk.** Monthly source cells map to budget categories through the configured,
  versioned crosswalk; exact-cent shares always sum to the source cell.

Ambiguity is never resolved by guessing: it becomes an unresolved
:class:`~pta_finance.main_reports.models.Discrepancy` and affected processor totals are marked
inconsistent. Nothing here reads or writes a workbook or a file. Error text names codes and
counts only, never a cell value.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import ROUND_DOWN, Decimal

from pta_finance.config import CategoryCrosswalk, Config, CrosswalkTarget
from pta_finance.main_reports.models import (
    CENT,
    TRANSACTION_KINDS,
    Allocation,
    CaptureSet,
    CategoryRule,
    CoverageFlag,
    CrosswalkCell,
    Discrepancy,
    MonthlyCategoryCell,
    PnlControlCheck,
    PnlMonthTotal,
    ProcessorClassification,
    ProcessorSummary,
    Reconciliation,
    RowIssue,
    SourceCapture,
    SourceMatch,
    SourceRef,
    Transaction,
)
from pta_finance.main_reports.sources import (
    SourceValidationError,
    classify_paypal_type,
    entered_matches,
    is_dash_placeholder,
    normalize_with_report,
    parse_money,
    read_category_mapping_with_report,
)

__all__ = [
    # constants
    "INTERNAL_TRANSFER_CATEGORY",
    "POSTED_STATUS",
    "SETTLEMENT_CANDIDATE_DAYS",
    "MIN_SETTLEMENT_REFERENCE_LENGTH",
    "IMPACTS",
    "DISCREPANCY_KINDS",
    # functions
    "build",
    "controls_from",
    "from_capture",
    "parse_month_label",
    "crosswalk_amounts",
    # types
    "ReconcileError",
    "ReconciliationControls",
]

# The source P&L formula excludes exactly this category text (case and spacing significant).
INTERNAL_TRANSFER_CATEGORY = "Internal Transfer"
# Bank STATUS value (compared case-insensitively) that is not flagged as non-posted.
POSTED_STATUS = "posted"
# A bank row this many days after a processor transfer is a settlement CANDIDATE, not a match.
SETTLEMENT_CANDIDATE_DAYS = 10
# A transfer ID shorter than this is never searched for in free-text bank descriptions.
MIN_SETTLEMENT_REFERENCE_LENGTH = 6

_SOURCE_PNL = "source_pnl"
_PROCESSOR_VIEW = "processor_view"
_SETTLEMENT = "settlement"
_CLASSIFICATION = "classification"
_CROSSWALK = "crosswalk"
IMPACTS: tuple[str, ...] = (_SOURCE_PNL, _PROCESSOR_VIEW, _SETTLEMENT, _CLASSIFICATION, _CROSSWALK)

# kind -> (impact, fixed explanation). Explanations never carry a cell value.
DISCREPANCY_KINDS: Mapping[str, tuple[str, str]] = {
    "transfer_category_variant": (
        _SOURCE_PNL,
        "Category resembles the excluded transfer category but is not an exact match; the "
        "source P&L counts it.",
    ),
    "bank_row_not_posted": (
        _SOURCE_PNL,
        "Bank row is not marked posted; the source P&L has no status filter and counts it.",
    ),
    "pnl_control_absent": (
        _SOURCE_PNL,
        "No published P&L control was captured; source parity is unverified.",
    ),
    "pnl_control_layout_unrecognized": (
        _SOURCE_PNL,
        "The published P&L has no unique month header row; source parity is unverified.",
    ),
    "pnl_control_cell_unreadable": (
        _SOURCE_PNL,
        "A published P&L cell is not an exact money value; that cell is unverified.",
    ),
    "pnl_control_duplicate_row": (
        _SOURCE_PNL,
        "A published P&L category row repeats; its cells are unverified.",
    ),
    "pnl_control_mismatch": (
        _SOURCE_PNL,
        "Published and reproduced monthly category nets differ (amount = published - reproduced).",
    ),
    "pnl_control_missing_cell": (
        _SOURCE_PNL,
        "A reproduced nonzero monthly category net is blank or absent in the published P&L.",
    ),
    "pnl_control_extra_cell": (
        _SOURCE_PNL,
        "A published nonzero P&L cell has no reproduced bank activity.",
    ),
    "pnl_control_month_absent": (
        _SOURCE_PNL,
        "Reproduced bank activity falls in a month with no published P&L column.",
    ),
    "pnl_control_total_mismatch": (
        _SOURCE_PNL,
        "A published total row does not equal the reproduced income, expense or net totals.",
    ),
    "overlap_unidentified": (
        _PROCESSOR_VIEW,
        "A store payment names the PayPal provider but has no payment ID to pair; it is "
        "excluded from processor totals so the sale cannot count twice.",
    ),
    "processor_type_unrecognized": (
        _PROCESSOR_VIEW,
        "PayPal row type is not recognized; it is excluded from processor totals, never "
        "counted as a sale.",
    ),
    "overlap_missing": (
        _PROCESSOR_VIEW,
        "A store payment names the PayPal provider but no PayPal payment has its ID.",
    ),
    "overlap_ambiguous": (
        _PROCESSOR_VIEW,
        "Several PayPal payments share a store payment ID; the overlap is unresolved.",
    ),
    "overlap_provider_conflict": (
        _PROCESSOR_VIEW,
        "A store payment shares a PayPal payment ID but does not name the PayPal provider.",
    ),
    "overlap_amount_conflict": (
        _PROCESSOR_VIEW,
        "Store and PayPal rows share a payment ID but differ in currency or gross.",
    ),
    "overlap_status_conflict": (
        _PROCESSOR_VIEW,
        "Store and PayPal rows share a payment ID but disagree on whether money moved, or one "
        "side has an unresolved status; both are excluded from processor totals.",
    ),
    "overlap_fee_conflict": (
        _PROCESSOR_VIEW,
        "Store and PayPal rows for one payment report different fees (amount = store - "
        "PayPal magnitude).",
    ),
    "processor_status_unresolved": (
        _PROCESSOR_VIEW,
        "Processor status is a chargeback, reversal, unknown or missing; the row is excluded "
        "from processor totals until resolved.",
    ),
    "processor_net_arithmetic": (
        _PROCESSOR_VIEW,
        "Processor gross, fee and refund do not reproduce the reported net.",
    ),
    "refund_status_conflict": (
        _PROCESSOR_VIEW,
        "Store refund amount disagrees with its transaction status.",
    ),
    "refund_exceeds_payment": (
        _PROCESSOR_VIEW,
        "Refunds exceed the original payment.",
    ),
    "refund_unlinked": (
        _PROCESSOR_VIEW,
        "A PayPal refund has no unique referenced payment.",
    ),
    "refund_cross_feed_conflict": (
        _PROCESSOR_VIEW,
        "Store refund and linked PayPal refunds differ for one payment (amount = store - PayPal).",
    ),
    "fee_unlinked": (
        _PROCESSOR_VIEW,
        "A PayPal fee row has no unique referenced payment.",
    ),
    "paypal_detail_orphan": (
        _PROCESSOR_VIEW,
        "A PayPal item detail row has no unique parent payment.",
    ),
    "paypal_detail_sum_mismatch": (
        _PROCESSOR_VIEW,
        "PayPal item detail gross does not sum to its parent (amount = details - parent).",
    ),
    "paypal_detail_sum_unverified": (
        _PROCESSOR_VIEW,
        "Some PayPal item details lack a gross, so their sum cannot be checked.",
    ),
    "settlement_conflict": (
        _SETTLEMENT,
        "Bank rows reference a processor transfer but none has its exact opposite amount.",
    ),
    "settlement_candidate": (
        _SETTLEMENT,
        "Bank rows match a processor transfer by amount and date only; that is a candidate, "
        "not a match.",
    ),
    "settlement_unmatched": (
        _SETTLEMENT,
        "No bank row corresponds to a processor transfer.",
    ),
    "category_mapping_ambiguous": (
        _CLASSIFICATION,
        "Category Mapping keywords give several target categories; none is chosen.",
    ),
    "crosswalk_unmapped": (
        _CROSSWALK,
        "Source category has no crosswalk entry; its budget category is unresolved.",
    ),
}

_MOVEMENT_STATUSES = frozenset({"successful", "refunded", "partially_refunded"})
_NON_MOVEMENT_STATUSES = frozenset({"declined", "authorized", "pending"})
_ROLE_STATES: Mapping[str, str] = {
    "fee": "processor_fee",
    "refund": "processor_refund",
    "transfer": "processor_transfer",
}
_PROCESSOR_KINDS = tuple(kind for kind in TRANSACTION_KINDS if kind != "bank")
_ZERO = Decimal("0.00")
_PAYPAL_PROVIDER = "paypal"
# A published row that is not a reproduced category is accepted as a verified total only when
# its LABEL names a total AND its values equal reproduced totals.
_TOTAL_LABEL = re.compile(r"\b(?:total|net|income|expenses?)\b", re.IGNORECASE)
# States whose rows move a processor balance that payouts must account for.
_BALANCE_STATES = frozenset(
    {"processor_primary", "overlap_secondary", "processor_fee", "processor_refund"}
)
_MAPPING_ROW_IGNORED = "category_mapping_row_ignored"
_MONTH_LABEL_LIMIT = 32
_MONTH_FORMATS = ("%b %Y", "%B %Y", "%b-%Y", "%B-%Y", "%Y-%m", "%m/%Y")
_FIRST_DAY_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")


# --------------------------------------------------------------------------------------
# Errors and controls
# --------------------------------------------------------------------------------------


class ReconcileError(Exception):
    """Reconciliation input or internal invariant broken (normalization guarantees, control
    duplication, crosswalk shares, discrepancy identity). Carries a stable ``code``; its text
    never carries a cell value.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ReconciliationControls:
    """Reference inputs for :func:`build`, taken from the same captured input set.

    ``pnl`` is the published P&L control capture; ``category_rules`` the Category Mapping
    guidance; ``crosswalk`` the configured versioned crosswalk; ``captures`` every capture
    whose warnings become coverage flags; ``row_warnings`` the row-level warnings
    (normalization and ignored Category Mapping rows) the result must keep visible.
    """

    pnl: SourceCapture | None = None
    category_rules: tuple[CategoryRule, ...] = ()
    crosswalk: CategoryCrosswalk | None = None
    captures: tuple[SourceCapture, ...] = ()
    row_warnings: tuple[RowIssue, ...] = ()


def controls_from(capture_set: CaptureSet, config: Config) -> ReconciliationControls:
    """Controls from one capture set plus the configured crosswalk (no workbook access).

    Category Mapping is guidance only: an incomplete rule row is ignored with a visible
    ``category_mapping_row_ignored`` warning and never halts the bank source view.
    """
    pnl = [item for item in capture_set.captures if item.kind == "pnl"]
    mapping = [item for item in capture_set.captures if item.kind == "category_mapping"]
    if len(pnl) > 1 or len(mapping) > 1:
        raise ReconcileError("duplicate_control", "a control kind is captured more than once")
    rules: tuple[CategoryRule, ...] = ()
    ignored: tuple[RowIssue, ...] = ()
    if mapping:
        rules, issues = read_category_mapping_with_report(mapping[0])
        ignored = tuple(
            RowIssue(
                issue.source_alias, issue.row_number, _MAPPING_ROW_IGNORED, issue.field, "warning"
            )
            for issue in issues
        )
    return ReconciliationControls(
        pnl=pnl[0] if pnl else None,
        category_rules=rules,
        crosswalk=config.main_reports.crosswalk if config.main_reports is not None else None,
        captures=capture_set.captures,
        row_warnings=ignored,
    )


def from_capture(capture_set: CaptureSet, config: Config) -> Reconciliation:
    """Production caller: normalize one capture set and reconcile it.

    Row errors fail closed (:class:`~pta_finance.main_reports.sources.SourceValidationError`,
    as :func:`~pta_finance.main_reports.sources.normalize` raises); row warnings travel into
    :attr:`Reconciliation.row_warnings` and coverage flags.
    """
    normalized = normalize_with_report(capture_set)
    if normalized.errors:
        raise SourceValidationError(normalized.errors)
    controls = controls_from(capture_set, config)
    controls = replace(controls, row_warnings=(*normalized.warnings, *controls.row_warnings))
    return build(normalized.transactions, controls)


# --------------------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------------------


class _Findings:
    def __init__(self) -> None:
        self.items: dict[str, Discrepancy] = {}

    def add(
        self,
        kind: str,
        *,
        affected: Iterable[SourceRef] = (),
        amount: Decimal | None = None,
        category: str | None = None,
        month: date | None = None,
        control_cell: tuple[int, int] | None = None,
    ) -> None:
        impact, explanation = DISCREPANCY_KINDS[kind]
        item = Discrepancy.create(
            kind=kind,
            impact=impact,
            explanation=explanation,
            affected=affected,
            amount=amount,
            category=category,
            month=month,
            control_cell=control_cell,
        )
        existing = self.items.get(item.discrepancy_id)
        if existing is not None and existing != item:
            raise ReconcileError("discrepancy_collision", f"two {kind} findings share one id")
        self.items[item.discrepancy_id] = item

    def count(self) -> int:
        return len(self.items)

    def ordered(self) -> tuple[Discrepancy, ...]:
        return tuple(
            sorted(self.items.values(), key=lambda d: (d.impact, d.kind, d.discrepancy_id))
        )


def _refs(transactions: Iterable[Transaction]) -> list[SourceRef]:
    return [txn.refs[0] for txn in transactions]


# --------------------------------------------------------------------------------------
# Input invariants
# --------------------------------------------------------------------------------------


def _validate(transactions: Sequence[Transaction]) -> None:
    keys = [txn.record_key for txn in transactions]
    if len(set(keys)) != len(keys):
        raise ReconcileError(
            "duplicate_record_key", f"{len(keys) - len(set(keys))} repeated record key(s)"
        )
    if any(txn.source_kind not in TRANSACTION_KINDS for txn in transactions):
        raise ReconcileError("unknown_source_kind", "a transaction has an unknown source kind")
    if any(not txn.refs for txn in transactions):
        raise ReconcileError("missing_source_ref", "a transaction has no source reference")
    currencies = {txn.currency for txn in transactions}
    if len(currencies) > 1:
        raise ReconcileError(
            "currency_mixing", f"{len(currencies)} currencies; no conversion is invented"
        )
    for txn in transactions:
        if txn.source_kind != "bank":
            continue
        if txn.posting_date is None or txn.gross is None or not txn.allocations:
            raise ReconcileError("bank_row_incomplete", "a bank row lacks date, amount or split")
        if any(
            item.record_key != txn.record_key or item.revision_hash != txn.revision_hash
            for item in txn.allocations
        ):
            raise ReconcileError(
                "allocation_identity_mismatch", "an allocation names another row or revision"
            )
        if sum((item.amount for item in txn.allocations), _ZERO) != txn.gross:
            raise ReconcileError(
                "split_not_conserved", "a bank row's allocations do not sum to its amount"
            )


# --------------------------------------------------------------------------------------
# Source view (bank allocations, monthly category nets)
# --------------------------------------------------------------------------------------


def _is_transfer_variant(category: str) -> bool:
    folded = " ".join(category.split()).casefold()
    return category != INTERNAL_TRANSFER_CATEGORY and folded == (
        INTERNAL_TRANSFER_CATEGORY.casefold()
    )


def _bank_view(
    bank: Sequence[Transaction], findings: _Findings, states: dict[str, str]
) -> tuple[list[Allocation], list[Allocation]]:
    counted: list[Allocation] = []
    transfers: list[Allocation] = []
    for txn in bank:
        ref = txn.refs[0]
        row_counted: list[Allocation] = []
        variants: dict[str, Decimal] = {}
        for allocation in txn.allocations:
            if allocation.category == INTERNAL_TRANSFER_CATEGORY:
                transfers.append(allocation)
                continue
            if _is_transfer_variant(allocation.category):
                variants[allocation.category] = (
                    variants.get(allocation.category, _ZERO) + allocation.amount
                )
            row_counted.append(allocation)
        for category, amount in variants.items():
            findings.add(
                "transfer_category_variant", affected=[ref], amount=amount, category=category
            )
        if row_counted and (txn.source_status or "").strip().casefold() != POSTED_STATUS:
            findings.add("bank_row_not_posted", affected=[ref], amount=txn.gross)
        counted.extend(row_counted)
        states[txn.record_key] = "source_view" if row_counted else "transfer_excluded"
    return counted, transfers


def _monthly_cells(
    allocations: Sequence[Allocation], by_key: Mapping[str, Transaction]
) -> tuple[MonthlyCategoryCell, ...]:
    groups: dict[tuple[date, str], list[Allocation]] = defaultdict(list)
    for allocation in allocations:
        posting = by_key[allocation.record_key].posting_date
        assert posting is not None  # validated
        groups[(posting.replace(day=1), allocation.category)].append(allocation)
    cells: list[MonthlyCategoryCell] = []
    for (month, category), items in sorted(groups.items()):
        amounts = [item.amount for item in items]
        net = sum(amounts, _ZERO)
        cells.append(
            MonthlyCategoryCell(
                category=category,
                month=month,
                net=net,
                inflow=sum((a for a in amounts if a > 0), _ZERO),
                outflow=sum((a for a in amounts if a < 0), _ZERO),
                classification="income" if net > 0 else "expense" if net < 0 else "zero",
                contributors=tuple(by_key[item.record_key].refs[0] for item in items),
            )
        )
    return tuple(cells)


def _month_totals(cells: Sequence[MonthlyCategoryCell]) -> tuple[PnlMonthTotal, ...]:
    by_month: dict[date, list[Decimal]] = defaultdict(list)
    for cell in cells:
        by_month[cell.month].append(cell.net)
    totals: list[PnlMonthTotal] = []
    for month in sorted(by_month):
        income = sum((net for net in by_month[month] if net > 0), _ZERO)
        expense = sum((net for net in by_month[month] if net < 0), _ZERO)
        totals.append(
            PnlMonthTotal(month=month, income=income, expense=expense, net=income + expense)
        )
    return tuple(totals)


# --------------------------------------------------------------------------------------
# Published P&L control
# --------------------------------------------------------------------------------------


def parse_month_label(text: str) -> date | None:
    """Parse a P&L month column heading to its first day; anything else -> ``None``.

    Accepts ``Jan 2030``, ``January 2030``, ``Jan-2030``, ``2030-01``, ``1/2030`` and a
    first-of-month date (``2030-01-01``, ``1/1/2030``). A date on another day is not a month.
    """
    label = text.strip()
    if not label or len(label) > _MONTH_LABEL_LIMIT:
        return None
    for fmt in _MONTH_FORMATS:
        try:
            return datetime.strptime(label, fmt).date().replace(day=1)
        except ValueError:
            continue
    for fmt in _FIRST_DAY_FORMATS:
        try:
            parsed = datetime.strptime(label, fmt).date()
        except ValueError:
            continue
        return parsed if parsed.day == 1 else None
    return None


def _month_header(values: Sequence[Sequence[str]]) -> tuple[int, dict[int, date]] | None:
    for row_index, row in enumerate(values):
        columns = {
            column: month
            for column, cell in enumerate(row)
            if column > 0 and (month := parse_month_label(cell)) is not None
        }
        if columns:
            return row_index, columns
    return None


def _control_amount(raw: str, entered: str | None) -> Decimal | None:
    """One published control cell as exact cents; blank -> ``None``; unprovable -> ValueError.

    Uses the source cell rule: a bare dash is 0.00 only over an entered numeric zero (the
    Sheets Accounting display); any entered number must equal the displayed cents, and a
    blank display over a nonzero entered number (a hiding format) is unprovable, not blank.
    """
    if is_dash_placeholder(raw):
        if entered is not None and entered_matches(entered, _ZERO):
            return _ZERO
        raise ValueError("dash_unverified")
    value = parse_money(raw)
    if entered is not None and not entered_matches(entered, value or _ZERO):
        raise ValueError("display_precision_mismatch")
    return value


def _total_row_matches(
    published: Mapping[date, Decimal | None], totals: Mapping[date, PnlMonthTotal]
) -> bool:
    """A row equal to the reproduced income, expense (either sign) or net totals."""

    def candidates(month: date) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        total = totals.get(month)
        if total is None:
            return _ZERO, _ZERO, _ZERO, _ZERO
        return total.income, total.expense, -total.expense, total.net

    return any(
        all((value or _ZERO) == candidates(month)[index] for month, value in published.items())
        for index in range(4)
    )


def _pnl_check(
    capture: SourceCapture | None,
    cells: Sequence[MonthlyCategoryCell],
    totals: Sequence[PnlMonthTotal],
    findings: _Findings,
) -> PnlControlCheck:
    if capture is None:
        findings.add("pnl_control_absent")
        return PnlControlCheck(status="absent")
    before = findings.count()
    header = _month_header(capture.values)
    months = list(header[1].values()) if header is not None else []
    if header is None or len(set(months)) != len(months):
        findings.add("pnl_control_layout_unrecognized")
        return PnlControlCheck(
            status="unverified", source_alias=capture.alias, snapshot_sha256=capture.sha256
        )
    header_index, month_columns = header
    header_row = capture.values[header_index]
    ignored = sum(
        1
        for column, cell in enumerate(header_row)
        if column > 0 and column not in month_columns and cell.strip()
    )

    rows_by_label: dict[str, list[tuple[int, dict[date, Decimal | None]]]] = defaultdict(list)
    unreadable: set[tuple[int, date]] = set()
    unreadable_rows: set[int] = set()
    entered = {(cell.row, cell.column): cell.value for cell in capture.entered_numbers}
    for row_index in range(header_index + 1, len(capture.values)):
        row = capture.values[row_index]
        label = row[0].strip() if row else ""
        parsed: dict[date, Decimal | None] = {}
        for column, month in month_columns.items():
            raw = row[column] if column < len(row) else ""
            try:
                parsed[month] = _control_amount(raw, entered.get((row_index, column)))
            except ValueError:
                unreadable.add((row_index, month))
                unreadable_rows.add(row_index)
                findings.add(
                    "pnl_control_cell_unreadable",
                    category=label or None,
                    month=month,
                    control_cell=(row_index + 1, column + 1),
                )
        if not label:
            for column, month in month_columns.items():
                if parsed.get(month):
                    findings.add(
                        "pnl_control_extra_cell",
                        amount=parsed[month],
                        month=month,
                        control_cell=(row_index + 1, column + 1),
                    )
            continue
        rows_by_label[label].append((row_index, parsed))

    reproduced = {(cell.category, cell.month): cell for cell in cells}
    categories = {cell.category for cell in cells}
    totals_by_month = {total.month: total for total in totals}
    compared = matched = total_rows = 0
    for label, entries in rows_by_label.items():
        if len(entries) > 1:
            findings.add("pnl_control_duplicate_row", category=label)
            continue
        row_index, readable = entries[0]
        if label not in categories:
            # Not a reproduced category. A total-labeled row must equal reproduced totals;
            # any other nonzero cell is unexplained published activity.
            if not any(readable.values()):
                continue
            if _TOTAL_LABEL.search(label):
                if row_index in unreadable_rows:
                    continue  # its unreadable cells are already findings
                if _total_row_matches(readable, totals_by_month):
                    total_rows += 1
                else:
                    findings.add(
                        "pnl_control_total_mismatch",
                        category=label,
                        control_cell=(row_index + 1, 1),
                    )
                continue
            for column, month in month_columns.items():
                if readable.get(month):
                    findings.add(
                        "pnl_control_extra_cell",
                        amount=readable[month],
                        category=label,
                        month=month,
                        control_cell=(row_index + 1, column + 1),
                    )
            continue
        for column, month in month_columns.items():
            if (row_index, month) in unreadable:
                continue
            published = readable.get(month)
            cell = reproduced.get((label, month))
            if published is None and cell is None:
                continue
            compared += 1
            net = cell.net if cell is not None else _ZERO
            if (published if published is not None else _ZERO) == net:
                matched += 1
                continue
            if published is None:
                kind, amount = "pnl_control_missing_cell", net
            elif cell is None:
                kind, amount = "pnl_control_extra_cell", published
            else:
                kind, amount = "pnl_control_mismatch", published - net
            findings.add(
                kind,
                affected=cell.contributors if cell is not None else (),
                amount=amount,
                category=label,
                month=month,
                control_cell=(row_index + 1, column + 1),
            )

    month_set = set(months)
    for cell in cells:
        if cell.category in rows_by_label or cell.month not in month_set:
            continue
        compared += 1
        if cell.net == _ZERO:
            matched += 1
        else:
            findings.add(
                "pnl_control_missing_cell",
                affected=cell.contributors,
                amount=cell.net,
                category=cell.category,
                month=cell.month,
            )
    absent: dict[date, list[SourceRef]] = defaultdict(list)
    for cell in cells:
        if cell.month not in month_set:
            absent[cell.month].extend(cell.contributors)
    for month, refs in absent.items():
        findings.add("pnl_control_month_absent", affected=refs, month=month)

    return PnlControlCheck(
        status="matched" if findings.count() == before else "mismatched",
        source_alias=capture.alias,
        snapshot_sha256=capture.sha256,
        months=tuple(sorted(months)),
        compared_cells=compared,
        matched_cells=matched,
        matched_total_rows=total_rows,
        ignored_columns=ignored,
    )


# --------------------------------------------------------------------------------------
# Processor enrichment (overlap, details, fees, refunds, settlements)
# --------------------------------------------------------------------------------------


def _net_consistent(txn: Transaction) -> bool:
    """Net equals gross plus the SIGNED fee (each feed signs fees itself), less any refund.

    The fee keeps its source sign: a sale's fee is negative and a refund row's returned fee is
    positive, so a net that moves the wrong way by the fee is caught, never coerced.
    """
    if txn.gross is None or txn.net is None:
        return True
    fee = txn.fee if txn.fee is not None else _ZERO
    refund = abs(txn.refund) if txn.refund is not None else _ZERO
    return txn.net in {txn.gross + fee, txn.gross + fee - refund}


@dataclass
class _ProcessorPass:
    """Classify processor rows, pair cross-feed overlaps, link details/fees/refunds to their
    payments, check refunds and arithmetic, and match payout transfers to bank rows.

    Writes reconciliation states into ``states`` and findings into ``findings``; collects
    matches. Never touches bank allocations.
    """

    transactions: Sequence[Transaction]
    bank: Sequence[Transaction]
    findings: _Findings
    states: dict[str, str]
    matches: list[SourceMatch] = field(default_factory=list)
    # PayPal payment key -> the store payment that represents it (matched overlap).
    secondary_of: dict[str, Transaction] = field(default_factory=dict)
    # Processor alias -> exact SIGNED processor movement of its transfers reference-matched to
    # bank rows (a payout out of the processor is negative, a deposit into it is positive).
    matched_transfers: dict[str, Decimal] = field(default_factory=dict)
    # Processor alias -> number of its transfers NOT matched to a bank row.
    unmatched_payouts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_key = {txn.record_key: txn for txn in self.transactions}
        self.processor = [txn for txn in self.transactions if txn.source_kind in _PROCESSOR_KINDS]
        self.paypal_payments: dict[str, list[Transaction]] = defaultdict(list)
        for txn in self.processor:
            if txn.source_kind == "paypal" and txn.row_role == "payment" and txn.native_id:
                self.paypal_payments[txn.native_id].append(txn)

    def conflict(self, kind: str, rows: Sequence[Transaction]) -> None:
        self.findings.add(kind, affected=_refs(rows))
        for txn in rows:
            self.states[txn.record_key] = "conflict"

    def run(self) -> None:
        self.statuses()
        self.overlaps()
        self.details()
        refunds = self.linked_rows("refund", "processor_refund", "refund_unlinked")
        self.linked_rows("fee", "processor_fee", "fee_unlinked")
        self.refund_checks(refunds)
        self.arithmetic()
        self.settlements()

    def statuses(self) -> None:
        for txn in self.processor:
            key = txn.record_key
            if txn.source_kind == "paypal" and not classify_paypal_type(txn.source_type or "")[1]:
                # An unrecognized PayPal Type defaults to "payment" in normalization; it is
                # never counted as a sale here. The rule is re-derived from the row's retained
                # Type through the one classifier, so it holds whoever calls build(). A blank
                # Type is unrecognized here; normalization agrees by rejecting a blank Type as
                # a row error, so no blank-Type row is ever counted as a sale on either path.
                self.conflict("processor_type_unrecognized", [txn])
            elif txn.row_role == "detail":
                self.states[key] = "detail_enrichment"
            elif txn.row_role == "payment" and txn.status_class in _MOVEMENT_STATUSES:
                self.states[key] = "processor_primary"
            elif txn.row_role == "payment" and txn.status_class in _NON_MOVEMENT_STATUSES:
                self.states[key] = "non_movement"
            elif txn.row_role in _ROLE_STATES and txn.status_class == "successful":
                self.states[key] = _ROLE_STATES[txn.row_role]
            else:
                self.conflict("processor_status_unresolved", [txn])

    def overlaps(self) -> None:
        stores: dict[str, list[Transaction]] = defaultdict(list)
        for txn in self.processor:
            if txn.source_kind != "wix":
                continue
            if txn.native_id:
                stores[txn.native_id].append(txn)
            elif (
                _PAYPAL_PROVIDER in (txn.payment_provider or "").casefold()
                and self.states[txn.record_key] != "non_movement"
            ):
                # No ID to pair on: excluded so the PayPal side can never be counted twice.
                self.conflict("overlap_unidentified", [txn])
        for payment_id, same_id in stores.items():
            store = same_id[0]
            candidates = self.paypal_payments.get(payment_id, [])
            names_paypal = _PAYPAL_PROVIDER in (store.payment_provider or "").casefold()
            if not candidates:
                for row in same_id:
                    provider = (row.payment_provider or "").casefold()
                    if (
                        _PAYPAL_PROVIDER in provider
                        and self.states[row.record_key] == "processor_primary"
                    ):
                        self.findings.add("overlap_missing", affected=_refs([row]))
                continue
            group = [*same_id, *candidates]
            paypal = candidates[0]
            moved = {self.states[t.record_key] == "processor_primary" for t in group}
            if len(candidates) > 1 or len(same_id) > 1:
                self.conflict("overlap_ambiguous", group)
            elif not names_paypal:
                self.conflict("overlap_provider_conflict", group)
            elif paypal.currency != store.currency or paypal.gross != store.gross:
                self.conflict("overlap_amount_conflict", group)
            elif len(moved) > 1 or any(self.states[t.record_key] == "conflict" for t in group):
                # One side moved money and the other did not, or one side's status is itself
                # unresolved: neither representation may stand in for the other.
                self.conflict("overlap_status_conflict", group)
            else:
                self.matches.append(
                    SourceMatch.create(
                        kind="processor_overlap",
                        rule="provider_payment_id+currency+gross",
                        members=_refs(group),
                    )
                )
                self.states[paypal.record_key] = "overlap_secondary"
                self.secondary_of[paypal.record_key] = store
                if (
                    store.fee is not None
                    and paypal.fee is not None
                    and abs(store.fee) != abs(paypal.fee)
                ):
                    self.findings.add(
                        "overlap_fee_conflict",
                        affected=_refs(group),
                        amount=abs(store.fee) - abs(paypal.fee),
                    )

    def details(self) -> None:
        by_parent: dict[str, list[Transaction]] = defaultdict(list)
        for txn in self.processor:
            if txn.row_role != "detail":
                continue
            if txn.parent_key is None or txn.parent_key not in self.by_key:
                self.findings.add("paypal_detail_orphan", affected=_refs([txn]))
                continue
            by_parent[txn.parent_key].append(txn)
        for parent_key, details in by_parent.items():
            parent = self.by_key[parent_key]
            self.matches.append(
                SourceMatch.create(
                    kind="processor_detail",
                    rule="transaction_id",
                    members=_refs([parent, *details]),
                )
            )
            grosses = [detail.gross for detail in details]
            group = _refs([parent, *details])
            if all(gross is not None for gross in grosses):
                total = sum((gross for gross in grosses if gross is not None), _ZERO)
                if parent.gross is not None and total != parent.gross:
                    self.findings.add(
                        "paypal_detail_sum_mismatch", affected=group, amount=total - parent.gross
                    )
            elif any(gross is not None for gross in grosses):
                self.findings.add("paypal_detail_sum_unverified", affected=group)

    def referenced_payment(self, txn: Transaction) -> Transaction | None:
        candidates = self.paypal_payments.get(txn.reference_id or "", [])
        return candidates[0] if len(candidates) == 1 else None

    def linked_rows(self, role: str, kind: str, unlinked: str) -> dict[str, list[Transaction]]:
        by_parent: dict[str, list[Transaction]] = defaultdict(list)
        for txn in self.processor:
            if txn.source_kind != "paypal" or txn.row_role != role:
                continue
            parent = self.referenced_payment(txn)
            if parent is None:
                self.findings.add(unlinked, affected=_refs([txn]), amount=txn.gross)
                continue
            self.matches.append(
                SourceMatch.create(kind=kind, rule="reference_txn_id", members=_refs([parent, txn]))
            )
            # A fee/refund follows its payment: unresolved with an unresolved payment, and
            # represented by the store row when the payment is an overlap's secondary side.
            parent_state = self.states[parent.record_key]
            if self.states[txn.record_key] != "conflict" and parent_state in {
                "conflict",
                "overlap_secondary",
            }:
                self.states[txn.record_key] = parent_state
            by_parent[parent.record_key].append(txn)
        return by_parent

    def refund_checks(self, refunds: Mapping[str, list[Transaction]]) -> None:
        for parent_key, rows in refunds.items():
            parent = self.by_key[parent_key]
            total = sum((abs(row.gross) for row in rows if row.gross is not None), _ZERO)
            if parent.gross is not None and total > abs(parent.gross):
                self.findings.add(
                    "refund_exceeds_payment",
                    affected=_refs([parent, *rows]),
                    amount=total - abs(parent.gross),
                )
        for paypal_key, store in self.secondary_of.items():
            rows = refunds.get(paypal_key, [])
            paypal_total = sum((abs(row.gross) for row in rows if row.gross is not None), _ZERO)
            store_total = abs(store.refund) if store.refund is not None else _ZERO
            if paypal_total != store_total:
                self.findings.add(
                    "refund_cross_feed_conflict",
                    affected=_refs([store, self.by_key[paypal_key], *rows]),
                    amount=store_total - paypal_total,
                )
        for store in self.processor:
            if store.source_kind != "wix" or store.gross is None:
                continue
            refund = abs(store.refund) if store.refund is not None else None
            gross = abs(store.gross)
            if refund is not None and refund > gross:
                self.findings.add(
                    "refund_exceeds_payment", affected=_refs([store]), amount=refund - gross
                )
                continue
            status = store.status_class
            conflict = (
                (status == "refunded" and refund != gross)
                or (status == "partially_refunded" and not (refund and refund < gross))
                or (status == "successful" and bool(refund))
            )
            if conflict:
                self.findings.add("refund_status_conflict", affected=_refs([store]), amount=refund)

    def arithmetic(self) -> None:
        for txn in self.processor:
            if txn.row_role != "detail" and not _net_consistent(txn):
                self.findings.add("processor_net_arithmetic", affected=_refs([txn]))

    def settlements(self) -> None:
        # One bank row can settle at most one processor transfer.
        used: set[str] = set()
        for transfer in self.processor:
            if transfer.row_role != "transfer":
                continue
            alias = transfer.source_alias
            # Counted unmatched until a reference match below proves otherwise.
            self.unmatched_payouts[alias] = self.unmatched_payouts.get(alias, 0) + 1
            if self.states.get(transfer.record_key) != "processor_transfer":
                continue  # an unresolved transfer is never matched (its finding exists)
            movement = transfer.net if transfer.net is not None else transfer.gross
            if movement is None:
                self.findings.add("settlement_unmatched", affected=_refs([transfer]))
                continue
            target = -movement
            referenced: list[Transaction] = []
            reference = transfer.native_id or ""
            if len(reference) >= MIN_SETTLEMENT_REFERENCE_LENGTH:
                token = re.compile(rf"(?<![0-9A-Za-z]){re.escape(reference)}(?![0-9A-Za-z])")
                referenced = [
                    row
                    for row in self.bank
                    if row.record_key not in used and token.search(row.description or "")
                ]
            if referenced:
                exact = [row for row in referenced if row.gross == target]
                if len(exact) == 1:
                    used.add(exact[0].record_key)
                    self.unmatched_payouts[alias] -= 1
                    # Signed: an inbound deposit raises the balance, it never cancels a payout.
                    self.matched_transfers[alias] = (
                        self.matched_transfers.get(alias, _ZERO) + movement
                    )
                    self.matches.append(
                        SourceMatch.create(
                            kind="bank_settlement",
                            rule="settlement_reference+amount",
                            members=_refs([transfer, exact[0]]),
                        )
                    )
                else:
                    self.findings.add(
                        "settlement_conflict", affected=_refs([transfer, *referenced])
                    )
                continue
            sent = transfer.payment_date
            candidates = [
                row
                for row in self.bank
                if row.record_key not in used
                and row.gross == target
                and sent is not None
                and row.posting_date is not None
                and 0 <= (row.posting_date - sent).days <= SETTLEMENT_CANDIDATE_DAYS
            ]
            kind = "settlement_candidate" if candidates else "settlement_unmatched"
            self.findings.add(kind, affected=_refs([transfer, *candidates]), amount=target)


def _untied(
    rows: Sequence[Transaction], states: Mapping[str, str], matched_transfers: Decimal
) -> Decimal | None:
    """Processor balance left unaccounted for after reference-matched transfers.

    ``(sum of NET over every balance row: primary and secondary payments, fee and refund
    rows, across all captured rows of the alias) + (sum of SIGNED net movement of transfers
    reference-matched to bank rows)``. A payout out of the processor is negative and offsets
    sales; a deposit into the processor is positive and adds to what must be accounted for.
    ``None`` when it cannot be known exactly: an unresolved (``conflict``) row, or a balance
    row without a net.
    """
    if any(states[txn.record_key] == "conflict" for txn in rows):
        return None
    nets = [txn.net for txn in rows if states[txn.record_key] in _BALANCE_STATES]
    if any(net is None for net in nets):
        return None
    return sum((net for net in nets if net is not None), _ZERO) + matched_transfers


def _summaries(
    processor: Sequence[Transaction],
    states: Mapping[str, str],
    findings: _Findings,
    matched_transfers: Mapping[str, Decimal],
    unmatched_payouts: Mapping[str, int],
) -> tuple[ProcessorSummary, ...]:
    inconsistent = {
        ref.source_alias
        for item in findings.items.values()
        if item.impact == _PROCESSOR_VIEW
        for ref in item.affected
    }
    by_alias: dict[str, list[Transaction]] = defaultdict(list)
    for txn in processor:
        by_alias[txn.source_alias].append(txn)
    summaries: list[ProcessorSummary] = []
    for alias in sorted(by_alias):
        rows = by_alias[alias]

        def with_state(state: str, rows: Sequence[Transaction] = rows) -> list[Transaction]:
            return [txn for txn in rows if states[txn.record_key] == state]

        primary = with_state("processor_primary")
        untied = _untied(rows, states, matched_transfers.get(alias, _ZERO))
        secondary = [t for t in with_state("overlap_secondary") if t.row_role == "payment"]
        fees = sum((abs(t.fee) for t in primary if t.fee is not None), _ZERO) + sum(
            (abs(t.gross) for t in with_state("processor_fee") if t.gross is not None), _ZERO
        )
        refunds = sum((abs(t.refund) for t in primary if t.refund is not None), _ZERO) + sum(
            (abs(t.gross) for t in with_state("processor_refund") if t.gross is not None), _ZERO
        )
        summaries.append(
            ProcessorSummary(
                source_alias=alias,
                gross=sum((t.gross for t in primary if t.gross is not None), _ZERO),
                fees=fees,
                refunds=refunds,
                primary_count=len(primary),
                secondary_count=len(secondary),
                non_movement_count=len(with_state("non_movement")),
                conflict_count=len(with_state("conflict")),
                consistent=alias not in inconsistent,
                settled=untied == _ZERO and unmatched_payouts.get(alias, 0) == 0,
                untied=untied,
            )
        )
    return tuple(summaries)


# --------------------------------------------------------------------------------------
# Category Mapping guidance and crosswalk
# --------------------------------------------------------------------------------------


def _classify(
    processor: Sequence[Transaction], rules: Sequence[CategoryRule], findings: _Findings
) -> tuple[ProcessorClassification, ...]:
    folded = [(rule, rule.keyword.casefold()) for rule in rules]
    out: list[ProcessorClassification] = []
    for txn in processor:
        if txn.row_role not in {"payment", "detail"}:
            continue
        text = (txn.product_name or "").casefold()
        if not text:
            out.append(ProcessorClassification(txn.record_key, txn.revision_hash, "no_text"))
            continue
        hits = [rule for rule, keyword in folded if keyword and keyword in text]
        targets = sorted({rule.target_category for rule in hits})
        rows = tuple(rule.row_number for rule in hits)
        if not hits:
            status, target = "unmatched", None
        elif len(targets) == 1:
            status, target = "matched", targets[0]
        else:
            status, target = "ambiguous", None
            findings.add("category_mapping_ambiguous", affected=_refs([txn]))
        out.append(ProcessorClassification(txn.record_key, txn.revision_hash, status, target, rows))
    return tuple(out)


def crosswalk_amounts(
    amount: Decimal, targets: Sequence[CrosswalkTarget]
) -> tuple[tuple[str, Decimal], ...]:
    """Split exact cents by share; the parts always sum exactly to ``amount``.

    Each share is first truncated toward zero to whole cents; the remaining cents go one at a
    time to the largest truncated remainders (ties: configured order). Deterministic.
    """
    if not targets:
        raise ReconcileError("crosswalk_empty", "a crosswalk entry has no targets")
    raw = [amount * target.share for target in targets]
    parts = [value.quantize(CENT, rounding=ROUND_DOWN) for value in raw]
    residual = amount - sum(parts, _ZERO)
    steps = int(abs(residual) / CENT)
    if steps > len(parts):
        raise ReconcileError("crosswalk_shares_invalid", "crosswalk shares do not sum to one")
    step = CENT if residual > 0 else -CENT
    order = sorted(range(len(parts)), key=lambda index: (-abs(raw[index] - parts[index]), index))
    for index in order[:steps]:
        parts[index] += step
    return tuple((target.category, part) for target, part in zip(targets, parts, strict=True))


def _crosswalk(
    cells: Sequence[MonthlyCategoryCell],
    crosswalk: CategoryCrosswalk | None,
    findings: _Findings,
) -> tuple[CrosswalkCell, ...]:
    if crosswalk is None:
        return ()
    entries = {entry.source_category: entry for entry in crosswalk.entries}
    unmapped: dict[str, list[SourceRef]] = defaultdict(list)
    out: list[CrosswalkCell] = []
    for cell in cells:
        entry = entries.get(cell.category)
        if entry is None:
            unmapped[cell.category].extend(cell.contributors)
            continue
        for target, (category, amount) in zip(
            entry.targets, crosswalk_amounts(cell.net, entry.targets), strict=True
        ):
            out.append(
                CrosswalkCell(
                    source_category=cell.category,
                    month=cell.month,
                    target_category=category,
                    share=target.share,
                    amount=amount,
                    crosswalk_version=crosswalk.version,
                )
            )
    for category, refs in unmapped.items():
        findings.add("crosswalk_unmapped", affected=refs, category=category)
    return tuple(out)


def _coverage_flags(
    controls: ReconciliationControls,
    pnl: PnlControlCheck,
    summaries: Sequence[ProcessorSummary],
) -> tuple[CoverageFlag, ...]:
    flags = [
        CoverageFlag(code=warning, source_alias=item.alias)
        for item in controls.captures
        for warning in item.warnings
    ]
    row_counts: dict[tuple[str, str], int] = defaultdict(int)
    for issue in controls.row_warnings:
        row_counts[(issue.code, issue.source_alias)] += 1
    flags.extend(
        CoverageFlag(code=code, source_alias=alias, count=count)
        for (code, alias), count in row_counts.items()
    )
    if pnl.status in {"absent", "unverified"}:
        flags.append(CoverageFlag(code=f"pnl_control_{pnl.status}", source_alias=pnl.source_alias))
    if controls.crosswalk is None:
        flags.append(CoverageFlag(code="crosswalk_absent"))
    for summary in summaries:
        if not summary.settled:
            flags.append(
                CoverageFlag(
                    code="processor_gross_unsettled",
                    source_alias=summary.source_alias,
                    count=summary.primary_count,
                )
            )
        if not summary.consistent:
            flags.append(
                CoverageFlag(code="processor_view_inconsistent", source_alias=summary.source_alias)
            )
    return tuple(sorted(flags, key=lambda flag: (flag.code, flag.source_alias or "")))


# --------------------------------------------------------------------------------------
# Production entry point
# --------------------------------------------------------------------------------------


def build(transactions: Sequence[Transaction], controls: ReconciliationControls) -> Reconciliation:
    """Reconcile normalized transactions into the CFO-compatible source view (pure).

    Raises :class:`ReconcileError` only for broken invariants (duplicate keys, unconserved
    splits, mixed currency, invalid crosswalk shares). Every data ambiguity is returned as an
    unresolved discrepancy instead.
    """
    transactions = tuple(transactions)
    _validate(transactions)
    findings = _Findings()
    states: dict[str, str] = {}
    by_key = {txn.record_key: txn for txn in transactions}
    bank = [txn for txn in transactions if txn.source_kind == "bank"]

    allocations, transfers = _bank_view(bank, findings, states)
    cells = _monthly_cells(allocations, by_key)
    totals = _month_totals(cells)
    pnl = _pnl_check(controls.pnl, cells, totals, findings)

    processor_pass = _ProcessorPass(transactions, bank, findings, states)
    processor_pass.run()
    processor = processor_pass.processor
    classifications = _classify(processor, controls.category_rules, findings)
    crosswalk_cells = _crosswalk(cells, controls.crosswalk, findings)
    summaries = _summaries(
        processor,
        states,
        findings,
        processor_pass.matched_transfers,
        processor_pass.unmatched_payouts,
    )

    return Reconciliation(
        transactions=tuple(
            replace(txn, reconciliation_state=states[txn.record_key]) for txn in transactions
        ),
        allocations=tuple(allocations),
        transfer_allocations=tuple(transfers),
        monthly_cells=cells,
        pnl_totals=totals,
        pnl_control=pnl,
        crosswalk_version=controls.crosswalk.version if controls.crosswalk else None,
        crosswalk_cells=crosswalk_cells,
        matches=tuple(sorted(processor_pass.matches, key=lambda m: (m.kind, m.match_id))),
        classifications=classifications,
        processor_summaries=summaries,
        discrepancies=findings.ordered(),
        coverage_flags=_coverage_flags(controls, pnl, summaries),
        row_warnings=tuple(controls.row_warnings),
    )
