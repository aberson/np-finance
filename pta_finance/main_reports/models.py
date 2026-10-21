"""Immutable, exact-money records and identifier helpers for the Main Report Set.

Every record here is a frozen dataclass. Money is a USD :class:`~decimal.Decimal` quantized to
cents; persisted JSON uses decimal *strings*, ISO dates, UTC ISO timestamps, sorted keys and
UTF-8 (see :func:`canonical_json_bytes`). Floats are never used for arithmetic.

Source capture owns the records defined here: :class:`SourceCapture`, :class:`CaptureSet`,
:class:`SourceRef`, :class:`Transaction`, :class:`Allocation`, plus the row-level
:class:`RowIssue` / :class:`ExcludedRow` diagnostics and :class:`SourceChange`. Reconciliation,
adjustments, facts and run manifests add their own records here and consume these unchanged.

Identifiers (contract section 10): ``record_key`` is
``v1:<source-alias>:<sha256-of-identity>:<occurrence>``; a revision hash covers every source
field of a row. Neither replaces reimbursement IDs or receipt fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
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
    "is_valid_source_alias",
    "canonical_json_bytes",
    "sha256_hex",
    "content_hash",
    "make_record_key",
    "money_str",
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


def money_str(value: Decimal) -> str:
    """Render exact cents as a decimal string (``Decimal('-3')`` -> ``'-3.00'``)."""
    quantized = value.quantize(CENT)
    if quantized != value:
        raise ValueError("money must be exact cents")
    # Negative zero renders as "0.00": equal amounts always serialize (and hash) identically.
    return format(quantized if quantized else abs(quantized), "f")


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
