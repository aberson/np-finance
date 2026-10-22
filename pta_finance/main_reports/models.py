"""Immutable, exact-money records and identifier helpers for the Main Report Set.

Every record here is a frozen dataclass. Money is a USD :class:`~decimal.Decimal` quantized to
cents; persisted JSON uses decimal *strings*, ISO dates, UTC ISO timestamps, sorted keys and
UTF-8 (see :func:`canonical_json_bytes`). Floats are never used for arithmetic.

Source capture owns the records defined here: :class:`SourceCapture`, :class:`CaptureSet`,
:class:`SourceRef`, :class:`Transaction`, :class:`Allocation`, plus the row-level
:class:`RowIssue` / :class:`ExcludedRow` diagnostics and :class:`SourceChange`. Reconciliation
owns :class:`Reconciliation` and its parts (:class:`Discrepancy`, :class:`SourceMatch`,
:class:`MonthlyCategoryCell`, :class:`PnlControlCheck`, :class:`CrosswalkCell`, ...).
Adjustments own :class:`Adjustment`, :class:`AdjustmentJournal` and :class:`AdjustedLedger`
(with :class:`AdjustedAllocation`, :class:`AdjustmentDelta`, :class:`AdjustmentIssue`). Facts
and run manifests add their own records here and consume these unchanged.

Identifiers (contract section 10): ``record_key`` is
``v1:<source-alias>:<sha256-of-identity>:<occurrence>``; a revision hash covers every source
field of a row. Neither replaces reimbursement IDs or receipt fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "RECORD_KEY_VERSION",
    "CENT",
    "SOURCE_KINDS",
    "TRANSACTION_KINDS",
    "CONTROL_KINDS",
    "ROW_ROLES",
    "STATUS_CLASSES",
    "SOURCE_ALIAS_PATTERN",
    "HEX_DIGEST_PATTERN",
    "DISCREPANCY_ID_PREFIX",
    "RECONCILIATION_STATES",
    "MATCH_KINDS",
    "DISCREPANCY_STATES",
    "CELL_CLASSES",
    "CLASSIFICATION_STATUSES",
    "PNL_CONTROL_STATUSES",
    "ADJUSTMENT_KINDS",
    "ADJUSTMENT_ID_PATTERN",
    "ALLOCATION_ORIGINS",
    "ISSUE_SEVERITIES",
    "is_valid_source_alias",
    "is_valid_record_key",
    "canonical_json_bytes",
    "sha256_hex",
    "content_hash",
    "make_record_key",
    "make_discrepancy_id",
    "make_match_id",
    "make_adjustment_id",
    "is_valid_adjustment_id",
    "money_str",
    "monthly_cells_from",
    "month_totals_from",
    "CoverageInterval",
    "FormulaCell",
    "EnteredNumber",
    "SourceCapture",
    "AdoptedBudget",
    "CaptureConsistency",
    "CaptureSet",
    "SourceRef",
    "Allocation",
    "Transaction",
    "CategoryRule",
    "RowIssue",
    "ExcludedRow",
    "NormalizationResult",
    "SourceChange",
    "CoverageStatus",
    "Discrepancy",
    "SourceMatch",
    "MonthlyCategoryCell",
    "PnlMonthTotal",
    "PnlControlCheck",
    "CrosswalkCell",
    "ProcessorClassification",
    "ProcessorSummary",
    "CoverageFlag",
    "Reconciliation",
    "Adjustment",
    "AdjustmentIssue",
    "JournalEntry",
    "AdjustmentJournal",
    "AdjustedAllocation",
    "AdjustmentDelta",
    "AdjustedLedger",
]

SCHEMA_VERSION = 1
RECORD_KEY_VERSION = "v1"
CENT = Decimal("0.01")

# The CFO workbook tabs a configured source binding may name. Transaction kinds are normalized
# into :class:`Transaction` records; control kinds are captured verbatim for reconciliation
# ``credit_card`` is captured only to detect a newly populated, uncovered feed.
TRANSACTION_KINDS: tuple[str, ...] = ("bank", "wix", "paypal")
CONTROL_KINDS: tuple[str, ...] = ("pnl", "budget_tracker", "category_mapping", "credit_card")
SOURCE_KINDS: tuple[str, ...] = (*TRANSACTION_KINDS, *CONTROL_KINDS)

ROW_ROLES: tuple[str, ...] = ("bank", "payment", "detail", "fee", "refund", "transfer")

STATUS_CLASSES: tuple[str, ...] = (
    "successful",
    "pending",
    "authorized",
    "declined",
    "refunded",
    "partially_refunded",
    "chargeback",
    "reversed",
    "unknown",
)

SOURCE_ALIAS_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}\Z")
# A lowercase SHA-256 hex digest (content hashes, revision hashes, aggregate hashes).
HEX_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
DISCREPANCY_ID_PREFIX = "DISC-"

# How reconciliation treats each normalized row. ``unreconciled`` is the normalization default.
RECONCILIATION_STATES: tuple[str, ...] = (
    "unreconciled",
    "source_view",  # bank row contributing to the CFO source P&L
    "transfer_excluded",  # bank row allocated wholly to the exact transfer category
    "processor_primary",  # processor movement counted once in the processor view
    "overlap_secondary",  # the other feed's representation of a matched cross-feed overlap
    "detail_enrichment",  # PayPal item detail: allocation evidence, never a balance movement
    "processor_fee",
    "processor_refund",
    "processor_transfer",
    "non_movement",  # declined / authorized / pending: no money moved
    "conflict",  # unresolved identity or status conflict: excluded from every total
)
MATCH_KINDS: tuple[str, ...] = (
    "processor_overlap",
    "processor_detail",
    "processor_fee",
    "processor_refund",
    "bank_settlement",
)
DISCREPANCY_STATES: tuple[str, ...] = ("unresolved", "resolved")
CELL_CLASSES: tuple[str, ...] = ("income", "expense", "zero")
CLASSIFICATION_STATUSES: tuple[str, ...] = ("matched", "unmatched", "ambiguous", "no_text")
PNL_CONTROL_STATUSES: tuple[str, ...] = ("matched", "mismatched", "unverified", "absent")

# Reporting-correction kinds (contract sections 6D and 10). The vocabulary is closed: there is
# no kind that approves, pays or otherwise changes a reimbursement decision.
ADJUSTMENT_KINDS: tuple[str, ...] = (
    "category_override",  # move a bank row's allocation(s) of one category to another
    "date_override",  # move a bank row's allocations to another posting date
    "amount_correction",  # replace a bank row's net amount in one category
    "additive",  # an independently evidenced entry with no source row
    "reversal",  # withdraw the entry it supersedes
)
# ``ADJ-`` + UUID4 hex (version nibble 4, RFC 4122 variant).
ADJUSTMENT_ID_PATTERN = re.compile(r"ADJ-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}\Z")
ALLOCATION_ORIGINS: tuple[str, ...] = ("source", "additive")
ISSUE_SEVERITIES: tuple[str, ...] = ("error", "warning")


def is_valid_source_alias(alias: str) -> bool:
    """A private configured source alias is a short lowercase ASCII slug."""
    return SOURCE_ALIAS_PATTERN.match(alias) is not None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return money_str(value)
    if isinstance(value, datetime):
        return _utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float):
        raise TypeError("floats are not permitted in canonical record JSON")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 JSON: sorted keys, no whitespace, decimals/dates as strings."""
    return json.dumps(
        _jsonable(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """SHA-256 of :func:`canonical_json_bytes` of ``value``."""
    return sha256_hex(canonical_json_bytes(value))


def make_record_key(alias: str, identity: Sequence[str], occurrence: int) -> str:
    """Build ``v1:<alias>:<sha256-of-identity>:<occurrence>`` (occurrence is zero-based)."""
    if not is_valid_source_alias(alias):
        raise ValueError("source alias must be a short lowercase ASCII slug")
    if occurrence < 0:
        raise ValueError("occurrence must be non-negative")
    return f"{RECORD_KEY_VERSION}:{alias}:{content_hash(list(identity))}:{occurrence}"


def _sorted_pairs(pairs: Iterable[tuple[str, str]]) -> list[list[str]]:
    return sorted([key, revision] for key, revision in pairs)


def is_valid_record_key(value: str) -> bool:
    """True for the exact :func:`make_record_key` shape (any alias, digest and occurrence)."""
    parts = value.split(":")
    return (
        len(parts) == 4
        and parts[0] == RECORD_KEY_VERSION
        and is_valid_source_alias(parts[1])
        and HEX_DIGEST_PATTERN.match(parts[2]) is not None
        and parts[3].isascii()
        and parts[3].isdigit()
    )


def make_discrepancy_id(
    kind: str, affected: Iterable[tuple[str, str]], subject: Sequence[str] = ()
) -> str:
    """``DISC-`` + SHA-256 of the kind, sorted affected (key, revision) pairs and subject.

    ``subject`` distinguishes control-cell findings that affect no source row (for example a
    published P&L category/month cell); it is empty for row-level findings.
    """
    return DISCREPANCY_ID_PREFIX + content_hash(
        {"kind": kind, "affected": _sorted_pairs(affected), "subject": list(subject)}
    )


def make_match_id(kind: str, members: Iterable[tuple[str, str]]) -> str:
    """``MATCH-`` + SHA-256 of the match kind and its sorted member (key, revision) pairs."""
    return "MATCH-" + content_hash({"kind": kind, "members": _sorted_pairs(members)})


def make_adjustment_id() -> str:
    """A new ``ADJ-`` + UUID4 hex identifier, created once when a proposal is saved."""
    return "ADJ-" + uuid.uuid4().hex


def is_valid_adjustment_id(value: str) -> bool:
    """True for ``ADJ-`` + UUID4 hex (see :data:`ADJUSTMENT_ID_PATTERN`)."""
    return ADJUSTMENT_ID_PATTERN.match(value) is not None


def money_str(value: Decimal) -> str:
    """Render exact cents as a decimal string (``Decimal('-3')`` -> ``'-3.00'``)."""
    quantized = value.quantize(CENT)
    if quantized != value:
        raise ValueError("money must be exact cents")
    # Negative zero renders as "0.00": equal amounts always serialize (and hash) identically.
    return format(quantized if quantized else abs(quantized), "f")


_ZERO_MONEY = Decimal("0.00")


def monthly_cells_from(
    items: Iterable[tuple[date, str, Decimal, Sequence[SourceRef]]],
) -> tuple[MonthlyCategoryCell, ...]:
    """Net signed amounts by category and posting month, as the source P&L formula does.

    Each item is ``(posting_date, category, signed_amount, contributor_refs)``. The ONE rule
    shared by the source view and the adjusted view: the sign of each monthly category NET
    decides income or expense; ``inflow`` / ``outflow`` keep the gross activity behind it.
    Cells are ordered by month then category; contributors keep item order.
    """
    groups: dict[tuple[date, str], list[tuple[Decimal, Sequence[SourceRef]]]] = defaultdict(list)
    for posting, category, amount, refs in items:
        groups[(posting.replace(day=1), category)].append((amount, refs))
    cells: list[MonthlyCategoryCell] = []
    for (month, category), members in sorted(groups.items()):
        amounts = [amount for amount, _ in members]
        net = sum(amounts, _ZERO_MONEY)
        cells.append(
            MonthlyCategoryCell(
                category=category,
                month=month,
                net=net,
                inflow=sum((a for a in amounts if a > 0), _ZERO_MONEY),
                outflow=sum((a for a in amounts if a < 0), _ZERO_MONEY),
                classification="income" if net > 0 else "expense" if net < 0 else "zero",
                contributors=tuple(ref for _, refs in members for ref in refs),
            )
        )
    return tuple(cells)


def month_totals_from(cells: Iterable[MonthlyCategoryCell]) -> tuple[PnlMonthTotal, ...]:
    """Month totals: income/expense are the sums of positive/negative category NETS."""
    by_month: dict[date, list[Decimal]] = defaultdict(list)
    for cell in cells:
        by_month[cell.month].append(cell.net)
    totals: list[PnlMonthTotal] = []
    for month in sorted(by_month):
        income = sum((net for net in by_month[month] if net > 0), _ZERO_MONEY)
        expense = sum((net for net in by_month[month] if net < 0), _ZERO_MONEY)
        totals.append(
            PnlMonthTotal(month=month, income=income, expense=expense, net=income + expense)
        )
    return tuple(totals)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _opt_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _opt_money(value: Decimal | None) -> str | None:
    return None if value is None else money_str(value)


@dataclass(frozen=True)
class CoverageInterval:
    """A declared source-coverage interval: ``start`` inclusive, ``end_exclusive`` exclusive.

    Configuration states human-readable inclusive end dates; the half-open form is internal.
    ``evidence`` names the private proof that the source is complete for the interval.
    """

    start: date
    end_exclusive: date
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end_exclusive": self.end_exclusive.isoformat(),
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class FormulaCell:
    """One formula cell captured as a control value (zero-based row/column positions)."""

    row: int
    column: int
    formula: str

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "column": self.column, "formula": self.formula}


@dataclass(frozen=True)
class EnteredNumber:
    """One numeric user-entered cell (zero-based position), kept as its exact decimal text.

    The formatted ``values`` grid is what the source displays; this is what was typed. Money
    fields are cross-checked against it so a display format cannot hide sub-cent precision.
    """

    row: int
    column: int
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "column": self.column, "value": self.value}


@dataclass(frozen=True)
class SourceCapture:
    """One dated, hashed, rectangular capture of a workbook tab.

    ``values`` are the formatted cell strings exactly as read (header rows included), padded to
    a rectangle. ``formulas`` lists every formula cell's text (never evaluated) and
    ``entered_numbers`` every numeric entered value. ``sha256`` covers the binding identity,
    declared coverage, values, formulas and entered numbers but NOT ``captured_at``, so an
    unchanged source re-captured later hashes identically (idempotent duplicate import).
    """

    alias: str
    kind: str
    tab_title: str
    tab_id: int | None
    captured_at: datetime
    header_rows: int
    header_signature: tuple[tuple[str, ...], ...]
    values: tuple[tuple[str, ...], ...]
    formulas: tuple[FormulaCell, ...]
    sha256: str
    # Resolved zero-based column position of every bound adapter field (absent optional
    # fields are omitted), so a capture is self-describing for later normalization/replay.
    columns: tuple[tuple[str, int], ...] = ()
    entered_numbers: tuple[EnteredNumber, ...] = ()
    observed_first: date | None = None
    observed_last: date | None = None
    coverage: tuple[CoverageInterval, ...] = ()
    warnings: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    @property
    def data_rows(self) -> tuple[tuple[str, ...], ...]:
        return self.values[self.header_rows :]

    def manifest_entry(self) -> dict[str, Any]:
        """Provenance summary without raw cell values."""
        return {
            "schema_version": self.schema_version,
            "alias": self.alias,
            "kind": self.kind,
            "tab_title": self.tab_title,
            "tab_id": self.tab_id,
            "captured_at": _utc_iso(self.captured_at),
            "header_rows": self.header_rows,
            "header_signature": [list(row) for row in self.header_signature],
            "columns": {name: position for name, position in self.columns},
            "row_count": len(self.values),
            "data_row_count": len(self.data_rows),
            "column_count": len(self.values[0]) if self.values else 0,
            "formula_count": len(self.formulas),
            "sha256": self.sha256,
            "observed_first": _opt_date(self.observed_first),
            "observed_last": _opt_date(self.observed_last),
            "coverage": [interval.to_dict() for interval in self.coverage],
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        entry = self.manifest_entry()
        entry["values"] = [list(row) for row in self.values]
        entry["formulas"] = [cell.to_dict() for cell in self.formulas]
        entry["entered_numbers"] = [cell.to_dict() for cell in self.entered_numbers]
        return entry


@dataclass(frozen=True)
class AdoptedBudget:
    """Adopted school-year budget targets from our own workbook (``proposed`` rows only).

    Rows are read through :func:`pta_finance.report_source.read_timeseries`. Annual ``actual``
    (and any other non-``proposed``) rows are counted but never retained here: they (and
    ``to_inputs``' synthetic year-end dates) are not transaction evidence and must not be
    layered onto CFO transactions.
    """

    tab_title: str
    rows: tuple[tuple[tuple[str, str], ...], ...]
    excluded_non_adopted_rows: int
    captured_at: datetime
    sha256: str
    warnings: tuple[str, ...] = ()

    def rows_as_dicts(self) -> list[dict[str, str]]:
        return [dict(row) for row in self.rows]

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "tab_title": self.tab_title,
            "adopted_row_count": len(self.rows),
            "excluded_non_adopted_rows": self.excluded_non_adopted_rows,
            "captured_at": _utc_iso(self.captured_at),
            "sha256": self.sha256,
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        entry = self.manifest_entry()
        entry["rows"] = [dict(row) for row in self.rows]
        return entry


@dataclass(frozen=True)
class CaptureConsistency:
    """Before/after verification result for one capture set (whole capture retried once)."""

    attempts: int
    consistent: bool
    changed_aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "consistent": self.consistent,
            "changed_aliases": list(self.changed_aliases),
        }


@dataclass(frozen=True)
class CaptureSet:
    """Every source/control capture plus our adopted budget and Assumptions, read once."""

    source_spreadsheet_id: str
    captures: tuple[SourceCapture, ...]
    adopted_budget: AdoptedBudget
    assumptions: SourceCapture
    consistency: CaptureConsistency
    aggregate_sha256: str
    schema_version: int = SCHEMA_VERSION

    @property
    def by_alias(self) -> dict[str, SourceCapture]:
        return {capture.alias: capture for capture in self.captures}

    def manifest(self) -> dict[str, Any]:
        """Private provenance manifest (no raw cell values; workbook binding is private)."""
        return {
            "schema_version": self.schema_version,
            "source_spreadsheet_id": self.source_spreadsheet_id,
            "aggregate_sha256": self.aggregate_sha256,
            "consistency": self.consistency.to_dict(),
            "captures": {c.alias: c.manifest_entry() for c in self.captures},
            "adopted_budget": self.adopted_budget.manifest_entry(),
            "assumptions": self.assumptions.manifest_entry(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_spreadsheet_id": self.source_spreadsheet_id,
            "aggregate_sha256": self.aggregate_sha256,
            "consistency": self.consistency.to_dict(),
            "captures": {c.alias: c.to_dict() for c in self.captures},
            "adopted_budget": self.adopted_budget.to_dict(),
            "assumptions": self.assumptions.to_dict(),
        }


@dataclass(frozen=True)
class SourceRef:
    """Evidence pointer to one captured row. Row numbers are one-based and never identity."""

    source_alias: str
    snapshot_sha256: str
    tab_id: int | None
    row_number: int
    record_key: str
    revision_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_alias": self.source_alias,
            "snapshot_sha256": self.snapshot_sha256,
            "tab_id": self.tab_id,
            "row_number": self.row_number,
            "record_key": self.record_key,
            "revision_hash": self.revision_hash,
        }


@dataclass(frozen=True)
class Allocation:
    """One signed category component of a bank row; components sum exactly to the row."""

    record_key: str
    revision_hash: str
    category: str
    amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "revision_hash": self.revision_hash,
            "category": self.category,
            "amount": money_str(self.amount),
        }


@dataclass(frozen=True)
class Transaction:
    """One normalized source row with its original values and exact money retained."""

    record_key: str
    revision_hash: str
    refs: tuple[SourceRef, ...]
    source_kind: str
    row_role: str
    currency: str
    source_values: tuple[str, ...]
    native_id: str | None = None
    reference_id: str | None = None
    order_id: str | None = None
    parent_key: str | None = None
    description: str | None = None
    check_number: str | None = None
    source_status: str | None = None
    status_class: str | None = None
    source_type: str | None = None
    payment_provider: str | None = None
    balance_impact: str | None = None
    product_name: str | None = None
    quantity: str | None = None
    gross: Decimal | None = None
    fee: Decimal | None = None
    fee_components: tuple[tuple[str, Decimal], ...] = ()
    refund: Decimal | None = None
    net: Decimal | None = None
    expense_date: date | None = None
    posting_date: date | None = None
    payment_date: date | None = None
    original_timestamp: str | None = None
    original_offset: str | None = None
    raw_category: str | None = None
    override_category: str | None = None
    final_category: str | None = None
    allocations: tuple[Allocation, ...] = ()
    reconciliation_state: str = "unreconciled"

    @property
    def source_alias(self) -> str:
        return self.refs[0].source_alias

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "revision_hash": self.revision_hash,
            "refs": [ref.to_dict() for ref in self.refs],
            "source_kind": self.source_kind,
            "row_role": self.row_role,
            "currency": self.currency,
            "source_values": list(self.source_values),
            "native_id": self.native_id,
            "reference_id": self.reference_id,
            "order_id": self.order_id,
            "parent_key": self.parent_key,
            "description": self.description,
            "check_number": self.check_number,
            "source_status": self.source_status,
            "status_class": self.status_class,
            "source_type": self.source_type,
            "payment_provider": self.payment_provider,
            "balance_impact": self.balance_impact,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "gross": _opt_money(self.gross),
            "fee": _opt_money(self.fee),
            "fee_components": [[name, money_str(amount)] for name, amount in self.fee_components],
            "refund": _opt_money(self.refund),
            "net": _opt_money(self.net),
            "expense_date": _opt_date(self.expense_date),
            "posting_date": _opt_date(self.posting_date),
            "payment_date": _opt_date(self.payment_date),
            "original_timestamp": self.original_timestamp,
            "original_offset": self.original_offset,
            "raw_category": self.raw_category,
            "override_category": self.override_category,
            "final_category": self.final_category,
            "allocations": [allocation.to_dict() for allocation in self.allocations],
            "reconciliation_state": self.reconciliation_state,
        }


@dataclass(frozen=True)
class CategoryRule:
    """One Category Mapping keyword rule: classification guidance, never an override."""

    keyword: str
    target_category: str
    row_number: int


@dataclass(frozen=True)
class RowIssue:
    """A row-level validation finding. Messages never carry financial row values."""

    source_alias: str
    row_number: int
    code: str
    field: str | None
    severity: str  # "error" | "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_alias": self.source_alias,
            "row_number": self.row_number,
            "code": self.code,
            "field": self.field,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class ExcludedRow:
    """A data row deliberately not normalized (e.g. a subtotal/summary row)."""

    source_alias: str
    row_number: int
    reason: str
    revision_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_alias": self.source_alias,
            "row_number": self.row_number,
            "reason": self.reason,
            "revision_hash": self.revision_hash,
        }


@dataclass(frozen=True)
class NormalizationResult:
    transactions: tuple[Transaction, ...]
    excluded: tuple[ExcludedRow, ...] = ()
    issues: tuple[RowIssue, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[RowIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[RowIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")


@dataclass(frozen=True)
class SourceChange:
    """One record-level difference between two normalizations of a source.

    ``kind`` is ``added`` (new key), ``missing`` (key no longer present), or ``revised`` (same
    key, different revision hash). A changed bank fingerprint surfaces as a missing/added pair;
    it is never silently treated as the same transaction.
    """

    kind: str
    record_key: str
    previous_revision: str | None
    current_revision: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "record_key": self.record_key,
            "previous_revision": self.previous_revision,
            "current_revision": self.current_revision,
        }


@dataclass(frozen=True)
class CoverageStatus:
    """Declared-coverage check of one source against a half-open reporting window.

    ``complete`` is true only when declared evidence covers the whole window. Observed first/
    last dates are reported separately: an earliest transaction is not proof of coverage
    start, and a blank month is not proof of zero activity.
    """

    source_alias: str
    start: date
    end_exclusive: date
    complete: bool
    uncovered: tuple[tuple[date, date], ...]
    observed_first: date | None
    observed_last: date | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_alias": self.source_alias,
            "start": self.start.isoformat(),
            "end_exclusive": self.end_exclusive.isoformat(),
            "complete": self.complete,
            "uncovered": [[a.isoformat(), b.isoformat()] for a, b in self.uncovered],
            "observed_first": _opt_date(self.observed_first),
            "observed_last": _opt_date(self.observed_last),
        }


def _ref_pairs(refs: Iterable[SourceRef]) -> list[tuple[str, str]]:
    return [(ref.record_key, ref.revision_hash) for ref in refs]


@dataclass(frozen=True)
class Discrepancy:
    """One visible reconciliation finding (contract section 10).

    ``affected`` names the source rows involved; ``category`` / ``month`` / ``control_cell``
    (one-based row and column of a published control cell) locate findings that affect no
    single row. ``amount`` is set only when it is known exactly. ``explanation`` is fixed text
    per ``kind`` and never carries a cell value. Findings are created ``unresolved``; only a
    recorded, evidence-backed resolution may change that.
    """

    discrepancy_id: str
    kind: str
    impact: str
    explanation: str
    affected: tuple[SourceRef, ...] = ()
    amount: Decimal | None = None
    category: str | None = None
    month: date | None = None
    control_cell: tuple[int, int] | None = None
    state: str = "unresolved"
    resolution_evidence: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        impact: str,
        explanation: str,
        affected: Iterable[SourceRef] = (),
        amount: Decimal | None = None,
        category: str | None = None,
        month: date | None = None,
        control_cell: tuple[int, int] | None = None,
    ) -> Discrepancy:
        subject: list[str] = []
        if category is not None or month is not None or control_cell is not None:
            subject = [
                category or "",
                _opt_date(month) or "",
                "" if control_cell is None else f"{control_cell[0]}:{control_cell[1]}",
            ]
        refs = tuple(sorted(set(affected), key=lambda ref: (ref.record_key, ref.revision_hash)))
        return cls(
            discrepancy_id=make_discrepancy_id(kind, _ref_pairs(refs), subject),
            kind=kind,
            impact=impact,
            explanation=explanation,
            affected=refs,
            amount=amount,
            category=category,
            month=month,
            control_cell=control_cell,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "discrepancy_id": self.discrepancy_id,
            "kind": self.kind,
            "impact": self.impact,
            "explanation": self.explanation,
            "affected": [ref.to_dict() for ref in self.affected],
            "amount": _opt_money(self.amount),
            "category": self.category,
            "month": _opt_date(self.month),
            "control_cell": None if self.control_cell is None else list(self.control_cell),
            "state": self.state,
            "resolution_evidence": list(self.resolution_evidence),
        }


@dataclass(frozen=True)
class SourceMatch:
    """A matched group of source rows. Every member's raw row is retained, never deleted."""

    match_id: str
    kind: str
    rule: str
    members: tuple[SourceRef, ...]

    @classmethod
    def create(cls, *, kind: str, rule: str, members: Iterable[SourceRef]) -> SourceMatch:
        refs = tuple(members)
        return cls(
            match_id=make_match_id(kind, _ref_pairs(refs)), kind=kind, rule=rule, members=refs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "kind": self.kind,
            "rule": self.rule,
            "members": [ref.to_dict() for ref in self.members],
        }


@dataclass(frozen=True)
class MonthlyCategoryCell:
    """One CFO source P&L cell: the net of every bank allocation to a category in a month.

    ``classification`` follows the source P&L: the SIGN OF THE MONTHLY NET decides income or
    expense. ``inflow`` / ``outflow`` are the explicitly labeled gross activity behind it
    (positive and negative allocations), which a transaction-sign view would report instead.
    ``month`` is the first day of the bank DATE month.
    """

    category: str
    month: date
    net: Decimal
    inflow: Decimal
    outflow: Decimal
    classification: str
    contributors: tuple[SourceRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "month": self.month.isoformat(),
            "net": money_str(self.net),
            "inflow": money_str(self.inflow),
            "outflow": money_str(self.outflow),
            "classification": self.classification,
            "allocation_count": len(self.contributors),
            "contributors": [ref.to_dict() for ref in self.contributors],
        }


@dataclass(frozen=True)
class PnlMonthTotal:
    """Source P&L month totals: income/expense are sums of positive/negative category nets."""

    month: date
    income: Decimal
    expense: Decimal
    net: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month.isoformat(),
            "income": money_str(self.income),
            "expense": money_str(self.expense),
            "net": money_str(self.net),
        }


@dataclass(frozen=True)
class PnlControlCheck:
    """Comparison of the reproduced source view with the published P&L control capture.

    ``status`` is ``matched`` only when every compared cell agrees exactly and no control
    finding exists; ``unverified`` when the published layout could not be read; ``absent``
    when no control was captured. Details are :class:`Discrepancy` records.
    """

    status: str
    source_alias: str | None = None
    snapshot_sha256: str | None = None
    months: tuple[date, ...] = ()
    compared_cells: int = 0
    matched_cells: int = 0
    matched_total_rows: int = 0
    ignored_columns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_alias": self.source_alias,
            "snapshot_sha256": self.snapshot_sha256,
            "months": [month.isoformat() for month in self.months],
            "compared_cells": self.compared_cells,
            "matched_cells": self.matched_cells,
            "matched_total_rows": self.matched_total_rows,
            "ignored_columns": self.ignored_columns,
        }


@dataclass(frozen=True)
class CrosswalkCell:
    """One share of a source monthly category cell mapped to a budget category.

    The amounts of every target of one source cell sum exactly to that cell's net.
    """

    source_category: str
    month: date
    target_category: str
    share: Decimal
    amount: Decimal
    crosswalk_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_category": self.source_category,
            "month": self.month.isoformat(),
            "target_category": self.target_category,
            "share": str(self.share),
            "amount": money_str(self.amount),
            "crosswalk_version": self.crosswalk_version,
        }


@dataclass(frozen=True)
class ProcessorClassification:
    """Category Mapping guidance for one processor row (never applied to bank categories)."""

    record_key: str
    revision_hash: str
    status: str
    target_category: str | None = None
    rule_rows: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "revision_hash": self.revision_hash,
            "status": self.status,
            "target_category": self.target_category,
            "rule_rows": list(self.rule_rows),
        }


@dataclass(frozen=True)
class ProcessorSummary:
    """Processor enrichment totals for one source alias: each movement counted once.

    ``gross`` sums ``processor_primary`` rows as the source signs them; ``fees`` and
    ``refunds`` are magnitudes. ``secondary_count`` counts PAYMENTS represented by another
    feed's row (overlap secondaries); their linked fee/refund rows are not counted.
    ``consistent`` is false when a processor-view discrepancy touches this alias. Neither
    total is ever added to the bank-based source view.

    ``untied`` = (NET of every primary or secondary payment, fee and refund row across all
    captured rows of the alias) + (SIGNED net movement of its transfers reference-matched to
    bank rows). Sign convention: the processor's own sign, so a payout out of the processor
    (withdrawal to the bank) is negative and offsets sales, while a deposit into the processor
    (bank-funded top-up) is positive and adds to what must be accounted for; it never cancels
    a payout. ``untied`` is ``None`` when it cannot be known exactly (an unresolved row, or a
    balance row without a net). ``settled`` is true only when ``untied`` is exactly 0.00 AND
    every transfer is matched: matched transfers then account for all processor money in the
    capture. An alias with no balance movement and no transfers is trivially settled.
    """

    source_alias: str
    gross: Decimal
    fees: Decimal
    refunds: Decimal
    primary_count: int
    secondary_count: int
    non_movement_count: int
    conflict_count: int
    consistent: bool
    settled: bool
    untied: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_alias": self.source_alias,
            "gross": money_str(self.gross),
            "fees": money_str(self.fees),
            "refunds": money_str(self.refunds),
            "primary_count": self.primary_count,
            "secondary_count": self.secondary_count,
            "non_movement_count": self.non_movement_count,
            "conflict_count": self.conflict_count,
            "consistent": self.consistent,
            "settled": self.settled,
            "untied": _opt_money(self.untied),
        }


@dataclass(frozen=True)
class CoverageFlag:
    """A coverage or basis limitation that marks affected totals partial or incomplete."""

    code: str
    source_alias: str | None = None
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "source_alias": self.source_alias, "count": self.count}


@dataclass(frozen=True)
class Reconciliation:
    """The CFO-compatible source view plus processor enrichment and visible findings.

    ``allocations`` are the signed bank allocations the source P&L counts; allocations to the
    exact transfer category are kept separately in ``transfer_allocations``. ``monthly_cells``
    and ``pnl_totals`` derive ONLY from bank allocations: processor rows never add to them.
    """

    transactions: tuple[Transaction, ...]
    allocations: tuple[Allocation, ...]
    transfer_allocations: tuple[Allocation, ...]
    monthly_cells: tuple[MonthlyCategoryCell, ...]
    pnl_totals: tuple[PnlMonthTotal, ...]
    pnl_control: PnlControlCheck
    crosswalk_version: int | None
    crosswalk_cells: tuple[CrosswalkCell, ...]
    matches: tuple[SourceMatch, ...]
    classifications: tuple[ProcessorClassification, ...]
    processor_summaries: tuple[ProcessorSummary, ...]
    discrepancies: tuple[Discrepancy, ...]
    coverage_flags: tuple[CoverageFlag, ...]
    # Row-level warnings from normalization and Category Mapping, kept visible (never dropped).
    row_warnings: tuple[RowIssue, ...] = ()
    schema_version: int = SCHEMA_VERSION

    @property
    def unresolved(self) -> tuple[Discrepancy, ...]:
        return tuple(item for item in self.discrepancies if item.state == "unresolved")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transactions": [txn.to_dict() for txn in self.transactions],
            "allocations": [item.to_dict() for item in self.allocations],
            "transfer_allocations": [item.to_dict() for item in self.transfer_allocations],
            "monthly_cells": [cell.to_dict() for cell in self.monthly_cells],
            "pnl_totals": [total.to_dict() for total in self.pnl_totals],
            "pnl_control": self.pnl_control.to_dict(),
            "crosswalk_version": self.crosswalk_version,
            "crosswalk_cells": [cell.to_dict() for cell in self.crosswalk_cells],
            "matches": [match.to_dict() for match in self.matches],
            "classifications": [item.to_dict() for item in self.classifications],
            "processor_summaries": [item.to_dict() for item in self.processor_summaries],
            "discrepancies": [item.to_dict() for item in self.discrepancies],
            "coverage_flags": [flag.to_dict() for flag in self.coverage_flags],
            "row_warnings": [issue.to_dict() for issue in self.row_warnings],
        }


@dataclass(frozen=True)
class Adjustment:
    """One evidence-backed reporting correction (contract sections 6D and 10).

    Exactly one correction representation per kind: ``category_override``,
    ``date_override`` and ``amount_correction`` use ``prior_value`` -> ``replacement_value``
    (the prior value is the precondition checked against the targeted source revision);
    ``additive`` uses ``signed_amount`` in ``category`` with no target; ``reversal`` carries no
    value and withdraws the entry it ``supersedes``. A later entry replaces or reverses an
    earlier one only through ``supersedes``; recorded entries are never edited.

    Canonical text: amounts as exact-cent decimal strings, dates ISO. ``recorded_at`` is set
    by the journal writer (``None`` on an unrecorded proposal) and excluded from
    :meth:`fingerprint`, so an identical retried proposal is recognized as already recorded.
    Adjustments change reporting only: they never approve, pay or alter a reimbursement.
    """

    adjustment_id: str
    kind: str
    effective_date: date
    reason: str
    evidence: tuple[str, ...]
    targets: tuple[tuple[str, str], ...] = ()
    prior_value: str | None = None
    replacement_value: str | None = None
    signed_amount: Decimal | None = None
    category: str | None = None
    supersedes: str | None = None
    recorded_at: datetime | None = None

    def payload(self) -> dict[str, Any]:
        """Every field except ``recorded_at`` (the identity compared on retries)."""
        return {
            "adjustment_id": self.adjustment_id,
            "kind": self.kind,
            "effective_date": self.effective_date.isoformat(),
            "targets": [
                {"record_key": key, "revision_hash": revision} for key, revision in self.targets
            ],
            "prior_value": self.prior_value,
            "replacement_value": self.replacement_value,
            "signed_amount": _opt_money(self.signed_amount),
            "category": self.category,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "supersedes": self.supersedes,
        }

    def fingerprint(self) -> str:
        return content_hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        entry = self.payload()
        entry["recorded_at"] = None if self.recorded_at is None else _utc_iso(self.recorded_at)
        return entry


@dataclass(frozen=True)
class AdjustmentIssue:
    """A journal, proposal or projection finding. Never carries a cell or money value.

    ``row_number`` is the one-based sheet row of a journal entry or the one-based position
    of a proposal; ``severity`` is in :data:`ISSUE_SEVERITIES` (errors block publication).
    """

    code: str
    severity: str
    adjustment_id: str | None = None
    row_number: int | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "adjustment_id": self.adjustment_id,
            "row_number": self.row_number,
            "field": self.field,
        }


@dataclass(frozen=True)
class JournalEntry:
    """A parsed journal row and its one-based sheet row number."""

    adjustment: Adjustment
    row_number: int

    def to_dict(self) -> dict[str, Any]:
        return {"row_number": self.row_number, "adjustment": self.adjustment.to_dict()}


@dataclass(frozen=True)
class AdjustmentJournal:
    """The adjustments journal as read from one Assumptions capture.

    ``marker_row`` is ``None`` when the section does not exist yet (nothing to apply).
    ``sha256`` hashes the raw journal region, so any change to a recorded row changes it;
    ``assumptions_sha256`` names the capture it was read from. ``last_occupied_row`` is the
    last one-based row holding any value or formula anywhere on the tab (placement anchor).
    Row-level ``issues`` are errors: an unreadable row blocks adjusted publication.
    """

    tab_title: str
    assumptions_sha256: str
    marker_row: int | None
    entries: tuple[JournalEntry, ...]
    issues: tuple[AdjustmentIssue, ...]
    last_occupied_row: int
    sha256: str
    schema_version: int = SCHEMA_VERSION

    @property
    def adjustments(self) -> tuple[Adjustment, ...]:
        return tuple(entry.adjustment for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tab_title": self.tab_title,
            "assumptions_sha256": self.assumptions_sha256,
            "marker_row": self.marker_row,
            "entries": [entry.to_dict() for entry in self.entries],
            "issues": [issue.to_dict() for issue in self.issues],
            "last_occupied_row": self.last_occupied_row,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class AdjustedAllocation:
    """One allocation in the adjusted view, with its source values kept beside it.

    ``origin`` is ``source`` (a bank allocation, possibly corrected) or ``additive`` (created
    by an additive entry; no source row, zero source amount). ``counted`` is false for the
    exact transfer category, which the P&L view excludes. ``adjustment_ids`` lists every
    applied entry that changed this allocation, in application order. Amounts are signed
    exactly as the bank signs them (inflow positive, outflow negative).
    """

    origin: str
    category: str
    amount: Decimal
    posting_date: date
    counted: bool
    record_key: str | None = None
    revision_hash: str | None = None
    ref: SourceRef | None = None
    source_category: str | None = None
    source_amount: Decimal = _ZERO_MONEY
    source_date: date | None = None
    adjustment_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "category": self.category,
            "amount": money_str(self.amount),
            "posting_date": self.posting_date.isoformat(),
            "counted": self.counted,
            "record_key": self.record_key,
            "revision_hash": self.revision_hash,
            "ref": None if self.ref is None else self.ref.to_dict(),
            "source_category": self.source_category,
            "source_amount": money_str(self.source_amount),
            "source_date": _opt_date(self.source_date),
            "adjustment_ids": list(self.adjustment_ids),
        }


@dataclass(frozen=True)
class AdjustmentDelta:
    """Signed source-to-adjusted change one applied entry makes to one P&L cell.

    For every category/month: source net + the sum of its deltas == adjusted net.
    """

    adjustment_id: str
    kind: str
    category: str
    month: date
    amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjustment_id": self.adjustment_id,
            "kind": self.kind,
            "category": self.category,
            "month": self.month.isoformat(),
            "amount": money_str(self.amount),
        }


@dataclass(frozen=True)
class AdjustedLedger:
    """The source reconciliation plus the journal entries applied to a copy of its view.

    ``source`` is never modified: source transactions, allocations, discrepancies and
    reconciliation states stay exactly as reconciled, and adjustments never resolve a
    discrepancy. ``applied`` lists entries in effect on ``as_of``; ``pending`` entries take
    effect later; ``superseded`` entries were replaced or reversed. Any ``conflicts`` (errors)
    block adjusted publication (:attr:`publishable`).
    """

    source: Reconciliation
    as_of: date
    journal_sha256: str
    applied: tuple[str, ...]
    pending: tuple[str, ...]
    superseded: tuple[str, ...]
    allocations: tuple[AdjustedAllocation, ...]
    monthly_cells: tuple[MonthlyCategoryCell, ...]
    pnl_totals: tuple[PnlMonthTotal, ...]
    deltas: tuple[AdjustmentDelta, ...]
    conflicts: tuple[AdjustmentIssue, ...] = ()
    warnings: tuple[AdjustmentIssue, ...] = ()
    schema_version: int = SCHEMA_VERSION

    @property
    def publishable(self) -> bool:
        return not self.conflicts

    @property
    def discrepancies(self) -> tuple[Discrepancy, ...]:
        return self.source.discrepancies

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of.isoformat(),
            "journal_sha256": self.journal_sha256,
            "publishable": self.publishable,
            "applied": list(self.applied),
            "pending": list(self.pending),
            "superseded": list(self.superseded),
            "allocations": [item.to_dict() for item in self.allocations],
            "monthly_cells": [cell.to_dict() for cell in self.monthly_cells],
            "pnl_totals": [total.to_dict() for total in self.pnl_totals],
            "deltas": [delta.to_dict() for delta in self.deltas],
            "conflicts": [issue.to_dict() for issue in self.conflicts],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "source": self.source.to_dict(),
        }
