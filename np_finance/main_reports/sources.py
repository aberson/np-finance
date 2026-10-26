"""Read-only CFO workbook capture, provenance, and per-source adapters.

This module is the ONE owner of the CFO source column definitions (:data:`ADAPTERS`). Private
configuration (``[main_reports]``) binds each configured source alias to a workbook tab, its
complete expected header signature, optional label overrides for repeated labels, and declared
coverage evidence; :func:`resolve_binding` turns that into exact column positions before any
workbook read.

Boundaries (``docs/plan-reference/cfo-main-report-set.md`` sections 5, 6 and 10):

* The CFO workbook is opened through :func:`connect_source_client`, a separate gspread client
  authorized ONLY for :data:`READONLY_SCOPE` and wrapped in :class:`ReadOnlyWorkbook`, which
  exposes no write method. Nothing here writes to any workbook. (The scope is the enforcement;
  the facade only narrows the surface. An injected test client is not scope-checked.)
* :func:`capture` reads every bound CFO tab, our adopted budget (through
  :func:`np_finance.report_source.read_timeseries`, never ``to_inputs``) and our Assumptions
  tab once, re-reads to verify nothing changed mid-capture, retries the whole capture once,
  then fails with ``capture_inconsistent``.
* Captured ``values`` are the formatted strings the source displays. Numeric user-entered
  values are captured beside them and money fields are cross-checked against them (binary
  float noise tolerated), so a display format cannot hide sub-cent precision in an entered
  number (``display_precision_mismatch``). A money cell that is a FORMULA has no entered
  number; it is flagged ``formula_money_unverified`` rather than silently trusted.
* :func:`normalize` turns bank / WIX / PayPal captures into exact-money
  :class:`~np_finance.main_reports.models.Transaction` records with stable ``record_key``
  identities, original values retained, subtotal rows excluded explicitly and malformed rows
  reported (never guessed). Annual synthetic budget rows are never transaction evidence.
* Error and issue text names aliases, rows, columns, fields and codes — NEVER a cell value.
* Bank statement PDF extraction is retired from this path: this module reads the CFO workbook
  only. Historical PDFs, the legacy parser, and receipt processing are untouched.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import gspread

from np_finance import report_source
from np_finance.config import ColumnBinding, Config, MainReports, SourceBinding
from np_finance.main_reports.models import (
    CENT,
    CONTROL_KINDS,
    HEX_DIGEST_PATTERN,
    SOURCE_KINDS,
    TRANSACTION_KINDS,
    AdoptedBudget,
    Allocation,
    CaptureConsistency,
    CaptureSet,
    CategoryRule,
    CoverageInterval,
    CoverageStatus,
    EnteredNumber,
    ExcludedRow,
    FormulaCell,
    NormalizationResult,
    RowIssue,
    SourceCapture,
    SourceChange,
    SourceRef,
    Transaction,
    canonical_json_bytes,
    content_hash,
    make_record_key,
    money_str,
)
from np_finance.models import parse_optional_amount
from np_finance.sheets import SheetsClient

__all__ = [
    # constants
    "READONLY_SCOPE",
    "HTTP_TIMEOUT_SECONDS",
    "CAPTURE_MAX_RETRIES",
    "CAPTURE_BASE_DELAY_SECONDS",
    "MAX_CAPTURE_ATTEMPTS",
    "ASSUMPTIONS_ALIAS",
    "UNALLOCATED_SPLIT_CATEGORY",
    "ADAPTERS",
    # functions
    "resolve_binding",
    "require_bindings",
    "connect_source_client",
    "connect_own_read_client",
    "capture",
    "capture_assumptions",
    "normalize",
    "normalize_with_report",
    "is_dash_placeholder",
    "entered_matches",
    "parse_money",
    "parse_source_date",
    "parse_allocations",
    "classify_status",
    "classify_paypal_type",
    "read_category_mapping",
    "read_category_mapping_with_report",
    "coverage_status",
    "compare_transactions",
    "compare_captures",
    "store_capture_set",
    # types
    "Clock",
    "FieldSpec",
    "AdapterSpec",
    "SourceError",
    "SourceConfigError",
    "SourceSchemaError",
    "SourceCaptureError",
    "SourceValidationError",
    "ResolvedBinding",
    "ReadOnlyWorkbook",
    "StoredCapture",
]

READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
HTTP_TIMEOUT_SECONDS = 20.0
# Quota-tolerant retry policy for the two read-only capture clients. A capture issues ~75
# reads within seconds, and the Sheets read quota is per MINUTE per user, so a 429 can
# outlast SheetsClient's shared default (~15 s of backoff). With these values the waits
# before the final attempt are 2+4+8+16+32+64 = 126 s (> 60 s). Other commands keep the
# SheetsClient defaults.
CAPTURE_MAX_RETRIES = 7
CAPTURE_BASE_DELAY_SECONDS = 1.0
MAX_CAPTURE_ATTEMPTS = 2
ASSUMPTIONS_ALIAS = "assumptions"
# The ONE category that carries a bank split's signed gap (amount minus its components) when
# the components do not add up. The row is published with a ``split_sum_mismatch`` warning;
# the gap is never absorbed into a real category (operator decision 2026-10-22).
UNALLOCATED_SPLIT_CATEGORY = "Unallocated split difference"
_USD = "USD"


# --------------------------------------------------------------------------------------
# Column definitions (single owner)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """One adapter field: internal name, default header label, and whether it must exist.

    Only for the DEFAULT label (never an explicit ``columns`` override), and only when no
    column carries the exact label: ``timezone_suffix`` accepts the label followed by an
    export time-zone suffix such as ``" GMT -07:00"``, and ``alternatives`` lists further
    labels (each with its own optional group) tried in order. Either fallback must match
    exactly one column, or the binding is ambiguous.
    """

    name: str
    label: str
    required: bool = True
    timezone_suffix: bool = False
    alternatives: tuple[ColumnBinding, ...] = ()


@dataclass(frozen=True)
class AdapterSpec:
    """How one source kind is laid out.

    ``header_rows`` is the exact number of header rows (``None`` = take it from the configured
    signature, for control grids). ``date_field`` drives observed first/last dates.
    """

    kind: str
    header_rows: int | None
    fields: tuple[FieldSpec, ...]
    date_field: str | None
    requires_signature: bool


ADAPTERS: Mapping[str, AdapterSpec] = {
    "bank": AdapterSpec(
        kind="bank",
        header_rows=1,
        fields=(
            FieldSpec("date", "DATE"),
            FieldSpec("description", "DESCRIPTION"),
            FieldSpec("amount", "AMOUNT"),
            FieldSpec("check_number", "CHECK #"),
            FieldSpec("status", "STATUS"),
            FieldSpec("category", "CATEGORY"),
            FieldSpec("override_category", "OVERRIDE CATEGORY"),
            FieldSpec("final_category", "FINAL CATEGORY"),
        ),
        date_field="date",
        requires_signature=True,
    ),
    "wix": AdapterSpec(
        kind="wix",
        header_rows=2,
        fields=(
            FieldSpec("provider_payment_id", "Provider Payment ID"),
            # The real export appends the account time zone: "Payment Date GMT -07:00".
            FieldSpec("payment_date", "Payment Date", timezone_suffix=True),
            FieldSpec("transaction_datetime", "Transaction Date", timezone_suffix=True),
            FieldSpec("timezone_offset", "Time Zone", required=False),
            FieldSpec("currency", "Currency"),
            FieldSpec("amount", "Amount"),
            FieldSpec("processing_fee", "Processing Fee"),
            FieldSpec("service_fee", "Service Fee"),
            FieldSpec("net", "Net"),
            FieldSpec("transaction_status", "Transaction Status"),
            FieldSpec("refund_amount", "Refund Amount"),
            FieldSpec("payment_provider", "Payment Provider"),
            FieldSpec("order_id", "Order ID"),
            FieldSpec(
                "product_name",
                "Product Name",
                alternatives=(ColumnBinding(label="Name", group="Products or Services"),),
            ),
            FieldSpec("quantity", "Quantity"),
        ),
        date_field="payment_date",
        requires_signature=True,
    ),
    "paypal": AdapterSpec(
        kind="paypal",
        header_rows=1,
        fields=(
            FieldSpec("transaction_id", "Transaction ID"),
            FieldSpec("reference_txn_id", "Reference Txn ID"),
            FieldSpec("date", "Date"),
            FieldSpec("time", "Time"),
            FieldSpec("timezone", "TimeZone"),
            FieldSpec("type", "Type"),
            FieldSpec("status", "Status"),
            FieldSpec("currency", "Currency"),
            FieldSpec("gross", "Gross"),
            FieldSpec("fee", "Fee"),
            FieldSpec("net", "Net"),
            FieldSpec("balance_impact", "Balance Impact"),
            FieldSpec("item_title", "Item Title", required=False),
            FieldSpec("quantity", "Quantity", required=False),
        ),
        date_field="date",
        requires_signature=True,
    ),
    "pnl": AdapterSpec(
        kind="pnl", header_rows=None, fields=(), date_field=None, requires_signature=False
    ),
    "budget_tracker": AdapterSpec(
        kind="budget_tracker",
        header_rows=None,
        fields=(),
        date_field=None,
        requires_signature=False,
    ),
    "category_mapping": AdapterSpec(
        kind="category_mapping",
        header_rows=1,
        fields=(FieldSpec("keyword", "Keyword"), FieldSpec("target_category", "Target Category")),
        date_field=None,
        requires_signature=True,
    ),
    # Empty at inspection: any signature (including none) may be bound; content beyond it,
    # or a changed header, is an uncovered-source WARNING, never a capture failure.
    "credit_card": AdapterSpec(
        kind="credit_card", header_rows=None, fields=(), date_field=None, requires_signature=False
    ),
}

# The kind vocabulary has one owner (models.SOURCE_KINDS); the adapter table must cover it
# exactly, or config validation could accept a kind no adapter understands.
if tuple(ADAPTERS) != SOURCE_KINDS:  # pragma: no cover - import-time invariant
    raise RuntimeError("ADAPTERS must cover models.SOURCE_KINDS exactly, in order")

# Control/reference kinds may be bound once; transaction kinds may repeat (several accounts).
_SINGLETON_KINDS = frozenset(CONTROL_KINDS)

# A summary LABEL is a whole cell such as "Total", "Subtotal:", "Grand total" or "Ending
# balance" — never a description that merely starts with "Total" (e.g. a store name). Cells
# longer than the limit cannot be labels, so matching is bounded and linear.
_SUMMARY_CELL_LIMIT = 64
_SUMMARY_LABEL = re.compile(
    r"(?:(?:grand|sub)[ -]?)?totals?|(?:beginning|ending|opening|closing) balance",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------------------
# Errors (messages name aliases, rows, columns, fields and codes — never cell values)
# --------------------------------------------------------------------------------------


class SourceError(Exception):
    """Base error carrying a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class SourceConfigError(SourceError):
    """``[main_reports]`` bindings are missing or cannot be resolved (before any read)."""


class SourceSchemaError(SourceError):
    """A captured tab's identity or header signature differs from its binding.

    ``positions`` lists differing ``(row, column)`` header cells (zero-based) — positions
    only, never the cell values.
    """

    def __init__(self, code: str, message: str, positions: Sequence[tuple[int, int]] = ()) -> None:
        self.positions = tuple(positions)
        super().__init__(code, message)


class SourceCaptureError(SourceError):
    """A capture could not be completed consistently or stored without conflict."""


class SourceValidationError(SourceError):
    """One or more rows failed validation; ``issues`` lists every error finding."""

    def __init__(self, issues: Sequence[RowIssue]) -> None:
        self.issues = tuple(issues)
        shown = "; ".join(
            f"{issue.source_alias} row {issue.row_number}: {issue.code}"
            + (f" ({issue.field})" if issue.field else "")
            for issue in self.issues[:10]
        )
        more = "" if len(self.issues) <= 10 else f"; +{len(self.issues) - 10} more"
        super().__init__(
            "source_validation_failed", f"{len(self.issues)} row error(s): {shown}{more}"
        )


# --------------------------------------------------------------------------------------
# Binding resolution
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedBinding:
    binding: SourceBinding
    spec: AdapterSpec
    header_rows: int
    columns: tuple[tuple[str, int], ...]


def _trim(row: Sequence[str]) -> tuple[str, ...]:
    cells = list(row)
    while cells and cells[-1] == "":
        cells.pop()
    return tuple(cells)


def _forward_fill(row: Sequence[str], width: int) -> list[str]:
    out: list[str] = []
    current = ""
    for index in range(width):
        cell = row[index] if index < len(row) else ""
        if cell != "":
            current = cell
        out.append(current)
    return out


# An export time-zone suffix after a default label, e.g. "Payment Date GMT -07:00".
# ASCII digits only ([0-9], not \d, which also matches other Unicode digits).
_TIMEZONE_SUFFIX = r" GMT [+-][0-9]{1,2}:[0-9]{2}"
# How one matching tier compares a label (and group) with the signature cells.
_LITERAL, _STRIPPED, _SUFFIXED = "literal", "stripped", "suffixed"


def _candidates(
    alias: str,
    spec_field: FieldSpec,
    ref: ColumnBinding,
    labels: Sequence[str],
    groups: Sequence[str] | None,
    mode: str,
) -> list[int]:
    """Positions whose label (and group) match ``ref`` under one tier, before ``occurrence``.

    ``literal`` compares cells exactly; ``stripped`` ignores surrounding whitespace on both
    sides (padded headers such as ``" AMOUNT "``); ``suffixed`` accepts the stripped label
    followed by an anchored time-zone suffix.
    """
    if mode == _SUFFIXED:
        pattern = re.compile(re.escape(ref.label.strip()) + _TIMEZONE_SUFFIX)
        candidates = [
            index for index, label in enumerate(labels) if pattern.fullmatch(label.strip())
        ]
    elif mode == _STRIPPED:
        wanted = ref.label.strip()
        candidates = [index for index, label in enumerate(labels) if label.strip() == wanted]
    else:
        candidates = [index for index, label in enumerate(labels) if label == ref.label]
    if ref.group is not None:
        if groups is None:
            raise SourceConfigError(
                "column_group_unavailable",
                f"{alias}.{spec_field.name}: a group needs a two-row header signature",
            )
        if mode == _LITERAL:
            candidates = [index for index in candidates if groups[index] == ref.group]
        else:
            group = ref.group.strip()
            candidates = [index for index in candidates if groups[index].strip() == group]
    return candidates


def _describe(ref: ColumnBinding, mode: str) -> str:
    text = repr(ref.label) + (" with a time-zone suffix" if mode == _SUFFIXED else "")
    return text if ref.group is None else f"{text} under {ref.group!r}"


def _locate(
    alias: str,
    spec_field: FieldSpec,
    ref: ColumnBinding,
    labels: Sequence[str],
    groups: Sequence[str] | None,
    *,
    is_default: bool,
) -> int | None:
    # Labels come from private CONFIG (the expected signature), never from workbook cells.
    # Tiers, first non-empty wins: the literal label, then the same label ignoring padding;
    # for the DEFAULT label only, then its time-zone-suffixed form, then each alternative
    # (literal, then stripped). Explicit overrides never get the suffix/alternative tiers.
    # ``occurrence`` counts within the deciding tier, so it keeps its literal meaning.
    tiers: list[tuple[ColumnBinding, str]] = [(ref, _LITERAL), (ref, _STRIPPED)]
    if is_default:
        if spec_field.timezone_suffix:
            tiers.append((ref, _SUFFIXED))
        for alternative in spec_field.alternatives:
            tiers.extend(((alternative, _LITERAL), (alternative, _STRIPPED)))
    for tier_ref, mode in tiers:
        candidates = _candidates(alias, spec_field, tier_ref, labels, groups, mode)
        if not candidates:
            continue
        if tier_ref.occurrence is not None:
            if tier_ref.occurrence <= len(candidates):
                return candidates[tier_ref.occurrence - 1]
            break  # out of range in the deciding tier: missing, never a padded twin
        if len(candidates) > 1:
            raise SourceConfigError(
                "ambiguous_column",
                f"{alias}.{spec_field.name}: label {_describe(tier_ref, mode)} repeats; bind it "
                "with a group or occurrence",
            )
        return candidates[0]
    if spec_field.required:
        tried = list(dict.fromkeys(_describe(tier_ref, mode) for tier_ref, mode in tiers))
        raise SourceConfigError(
            "missing_column",
            f"{alias}.{spec_field.name}: header signature has no column {' or '.join(tried)}",
        )
    return None


def resolve_binding(binding: SourceBinding) -> ResolvedBinding:
    """Resolve a configured binding to exact column positions (no workbook access)."""
    spec = ADAPTERS[binding.kind]
    signature = binding.header_signature
    if spec.header_rows is not None and len(signature) != spec.header_rows:
        raise SourceConfigError(
            "header_signature_shape",
            f"{binding.alias}: {binding.kind} expects {spec.header_rows} header row(s)",
        )
    if spec.requires_signature and (not signature or not _trim(signature[-1])):
        raise SourceConfigError(
            "header_signature_missing", f"{binding.alias}: a complete header signature is required"
        )
    known = {spec_field.name for spec_field in spec.fields}
    overrides = dict(binding.columns)
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise SourceConfigError(
            "unknown_column_field", f"{binding.alias}: unknown column field(s) {unknown}"
        )
    labels = list(signature[-1]) if signature else []
    groups = _forward_fill(signature[0], len(labels)) if len(signature) >= 2 else None
    resolved: list[tuple[str, int]] = []
    used: set[int] = set()
    for spec_field in spec.fields:
        override = overrides.get(spec_field.name)
        ref = override if override is not None else ColumnBinding(label=spec_field.label)
        position = _locate(
            binding.alias, spec_field, ref, labels, groups, is_default=override is None
        )
        if position is None:
            continue
        if position in used:
            raise SourceConfigError(
                "column_bound_twice", f"{binding.alias}.{spec_field.name}: column already bound"
            )
        used.add(position)
        resolved.append((spec_field.name, position))
    return ResolvedBinding(
        binding=binding,
        spec=spec,
        header_rows=len(signature),
        columns=tuple(resolved),
    )


def _main_reports(config: Config) -> MainReports:
    if config.main_reports is None:
        raise SourceConfigError("main_reports_missing", "config.toml has no [main_reports] section")
    return config.main_reports


def require_bindings(config: Config) -> tuple[ResolvedBinding, ...]:
    """Validate that every required source kind is bound and resolvable — before side effects."""
    main_reports = _main_reports(config)
    if main_reports.source_spreadsheet_id in {
        config.sheets.spreadsheet_id,
        config.sheets.test_spreadsheet_id,
    }:
        raise SourceConfigError(
            "source_is_own_workbook", "the CFO source workbook must not be our own workbook"
        )
    counts: dict[str, int] = {}
    tabs: set[str] = set()
    for binding in main_reports.sources:
        counts[binding.kind] = counts.get(binding.kind, 0) + 1
        if binding.tab in tabs:
            raise SourceConfigError(
                "duplicate_tab_binding", f"{binding.alias}: tab bound by another alias"
            )
        tabs.add(binding.tab)
    missing = [kind for kind in SOURCE_KINDS if counts.get(kind, 0) == 0]
    if missing:
        raise SourceConfigError("missing_binding", f"no [main_reports] binding for {missing}")
    repeated = sorted(kind for kind in _SINGLETON_KINDS if counts.get(kind, 0) > 1)
    if repeated:
        raise SourceConfigError("duplicate_binding", f"bound more than once: {repeated}")
    if any(binding.alias == ASSUMPTIONS_ALIAS for binding in main_reports.sources):
        raise SourceConfigError("reserved_alias", f"{ASSUMPTIONS_ALIAS!r} is reserved")
    return tuple(resolve_binding(binding) for binding in main_reports.sources)


# --------------------------------------------------------------------------------------
# Read-only workbook access
# --------------------------------------------------------------------------------------


class ReadOnlyWorkbook:
    """Read-only facade: keeps only bound READ methods of a :class:`SheetsClient`."""

    def __init__(self, client: SheetsClient) -> None:
        self._values = client.read_values
        self._snapshot = client.read_snapshot_values
        self._worksheet = client.worksheet

    def read_values(self, tab: str) -> list[list[str]]:
        return self._values(tab)

    def read_entered_cells(
        self, tab: str
    ) -> tuple[tuple[FormulaCell, ...], tuple[EnteredNumber, ...]]:
        """Formula text and numeric entered values from one ``userEnteredValue`` read."""
        formulas: list[FormulaCell] = []
        numbers: list[EnteredNumber] = []
        for row_index, row in enumerate(self._snapshot(tab)):
            for column_index, cell in enumerate(row):
                entered = cell.get("userEnteredValue")
                if not isinstance(entered, Mapping):
                    continue
                formula = entered.get("formulaValue")
                number = entered.get("numberValue")
                if isinstance(formula, str):
                    formulas.append(FormulaCell(row_index, column_index, formula))
                elif isinstance(number, (int, float)) and not isinstance(number, bool):
                    numbers.append(EnteredNumber(row_index, column_index, str(number)))
        return tuple(formulas), tuple(numbers)

    def tab_id(self, tab: str) -> int | None:
        value = getattr(self._worksheet(tab), "id", None)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value


def connect_source_client(
    config: Config,
    *,
    gspread_client: gspread.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ReadOnlyWorkbook:
    """Open the CFO workbook through a separate client authorized only for read access.

    Production authorizes the service account with exactly :data:`READONLY_SCOPE` (Google then
    rejects any write) and a finite HTTP timeout; 429/500/503 retries use
    :class:`SheetsClient` with the quota-tolerant :data:`CAPTURE_MAX_RETRIES` /
    :data:`CAPTURE_BASE_DELAY_SECONDS` policy. Tests inject ``gspread_client`` (its scopes are
    the caller's concern).
    """
    main_reports = _main_reports(config)
    if gspread_client is None:
        gspread_client = gspread.service_account(
            filename=str(config.google.service_account_path), scopes=[READONLY_SCOPE]
        )
        gspread_client.set_timeout(HTTP_TIMEOUT_SECONDS)
    client = SheetsClient(
        config,
        spreadsheet_id=main_reports.source_spreadsheet_id,
        gspread_client=gspread_client,
        sleep=sleep,
        max_retries=CAPTURE_MAX_RETRIES,
        base_delay=CAPTURE_BASE_DELAY_SECONDS,
    )
    return ReadOnlyWorkbook(client)


# --------------------------------------------------------------------------------------
# Parsing helpers (exact money, source-native dates)
# --------------------------------------------------------------------------------------

# Integer part: plain digits, or 1-3 digits then ",ddd" groups; optional 1-2 decimal places.
_MONEY_NUMBER = r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?"
_MONEY_CURRENCY = r"(?:\$ *)?"
_MONEY_SHAPE = re.compile(
    rf"[-+]?{_MONEY_CURRENCY}{_MONEY_NUMBER}"  # 1,234.56  -$3.00  +5  $ 12
    rf"|{_MONEY_CURRENCY}[-+]{_MONEY_NUMBER}"  # $-3.00
    rf"|\({_MONEY_CURRENCY}{_MONEY_NUMBER}\)"  # (3.00)  ($3.00)
    rf"|{_MONEY_CURRENCY}\({_MONEY_NUMBER}\)"  # $(3.00)  $ (3.00)  (Sheets Accounting)
)
# A bare dash ("$ -" or "-"): Google Sheets' Accounting format shows an exact zero this way,
# but the same text is also a common TEXT placeholder. Text alone cannot tell them apart, so
# parse_money raises "dash_placeholder" and the caller decides from the entered value.
_ACCOUNTING_ZERO = re.compile(r"(?:\$ *)?-")
_MONEY_TEXT_LIMIT = 64
# Binary-float noise tolerated when an entered number is compared with displayed cents.
_FLOAT_NOISE = Decimal("0.000001")
_ZERO_CENTS = Decimal("0.00")
# Optional-field dash outcomes that leave a value unproven, and the WIX fee components.
_UNPROVEN_DASH_CODES = frozenset({"dash_placeholder", "formula_dash_unverified"})
_WIX_FEE_FIELDS = frozenset({"processing_fee", "service_fee"})


def is_dash_placeholder(raw: str) -> bool:
    """True for a bare ``-`` / ``$ -`` money cell (Accounting zero OR a text placeholder)."""
    return _ACCOUNTING_ZERO.fullmatch(raw.strip()) is not None


def entered_matches(entered: str, value: Decimal) -> bool:
    """True when a numeric entered value equals ``value`` within binary-float noise.

    The one rule for both checks on a displayed money cell: an entered number must agree with
    the displayed cents (a format cannot hide sub-cent precision), and a bare dash is exact
    zero only over an entered numeric zero (``entered_matches(entered, Decimal(0))``).
    """
    try:
        return abs(Decimal(entered) - value) <= _FLOAT_NOISE
    except InvalidOperation:
        return False


def _exact_cents(value: Decimal) -> Decimal:
    quantized: Decimal | None
    try:
        quantized = value.quantize(CENT)
    except InvalidOperation:  # beyond Decimal context precision (oversized cell)
        quantized = None
    # Raised outside the handler so no exception context is chained.
    if quantized is None:
        raise ValueError("invalid_money")
    if quantized != value:
        raise ValueError("money_precision")
    # Negative zero ("-0.00") is the same amount as 0.00: one canonical form for identities.
    return quantized if quantized else _ZERO_CENTS


def parse_money(raw: str) -> Decimal | None:
    """Parse a formatted money cell to exact cents; blank -> ``None``. Fails closed.

    The raw text must have an exact money SHAPE first: optional ``$`` and sign, or a
    parenthesised negative (also ``$(x)`` / ``$ (x)`` as Sheets' Accounting format shows it);
    an integer part of plain digits or correctly grouped thousands (``1,234,567``); and at most
    two decimal places. Mis-grouped text such as ``12,34`` or ``1,2,3`` is never reinterpreted.
    A bare dash raises ``ValueError("dash_placeholder")``: it is 0.00 only when the cell's
    entered value is numeric zero (the Sheets Accounting display), which the row reader checks.
    The validated canonical text is then parsed by the ONE shared parser,
    :func:`np_finance.models.parse_optional_amount` (unchanged for its existing callers).
    Raises ``ValueError("invalid_money")`` (or ``"money_precision"``) with no chained
    exception, so the cell text never travels with it. ``-0.00`` is returned as ``0.00``.
    """
    text = raw.strip()
    if not text:
        return None
    if len(text) > _MONEY_TEXT_LIMIT:
        raise ValueError("invalid_money")
    if _ACCOUNTING_ZERO.fullmatch(text):
        raise ValueError("dash_placeholder")
    if not _MONEY_SHAPE.fullmatch(text):
        raise ValueError("invalid_money")
    canonical = text.replace("$", "").replace(" ", "")
    value: Decimal | None
    try:
        value = parse_optional_amount(canonical)
    except (ValueError, InvalidOperation):
        value = None
    if value is None or not value.is_finite():
        raise ValueError("invalid_money")
    return _exact_cents(value)


_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y, %I:%M:%S %p",  # store export: "1/5/2030, 10:15:00 AM"
    "%m/%d/%Y, %I:%M %p",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d, %Y %I:%M %p",
    "%b %d, %Y %H:%M",
    "%d %b %Y",
)
# Plausible source-date window; anything outside is a typo, never silently used.
_MIN_SOURCE_DATE = date(1900, 1, 1)
_MAX_SOURCE_DATE = date(2199, 12, 31)


def parse_source_date(raw: str) -> date | None:
    """Parse a source-native date or date-time cell to its calendar date; blank -> ``None``.

    The date shown by the source is used as-is (no timezone conversion); the original text and
    any declared offset are retained on the record. Raises ``ValueError("invalid_date")``.
    """
    text = raw.strip()
    if not text:
        return None
    parsed = _parse_date_text(text)
    if parsed is None:
        raise ValueError("invalid_date")
    if not _MIN_SOURCE_DATE <= parsed <= _MAX_SOURCE_DATE:
        # e.g. a 9999-12-31 typo: a visible row issue, never an overflow downstream.
        raise ValueError("date_out_of_range")
    return parsed


def _parse_date_text(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _split_components(category: str) -> list[str]:
    """Split ``"A: 1,000.00, B: -3.00"`` at each comma that starts a new ``name:`` part.

    Linear (no regex backtracking): a comma begins a new part only when the text after it, up
    to the next comma, contains a colon that is not its first character.
    """
    pieces = category.split(",")
    parts = [pieces[0]]
    for piece in pieces[1:]:
        if piece.find(":") > 0:
            parts.append(piece.lstrip())
        else:
            parts[-1] = f"{parts[-1]},{piece}"
    return parts


# ``: <money>`` followed by a comma or the end: the text was meant as a signed split.
_SPLIT_HINT = re.compile(r":\s*\(?[-+]?\$?[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)\)?\s*(?:,|$)")


def parse_allocations(text: str, amount: Decimal) -> tuple[tuple[str, Decimal], ...]:
    """Expand a bank FINAL CATEGORY into signed category components.

    A plain category allocates the whole ``amount``. ``"A: 100.00, B: -3.00"`` allocates signed
    components, which must sum exactly to ``amount``. Raises ``ValueError`` with code
    ``unparseable_split``, ``split_sum_mismatch`` or ``split_dash_placeholder`` (a component
    amount written as a bare dash has no entered number to prove it is zero, so it is a
    placeholder in a required amount — never a silent zero or a spurious sum mismatch).
    """
    components, remainder = _split_allocations(text, amount)
    if remainder:
        raise ValueError("split_sum_mismatch")
    return components


def _split_allocations(
    text: str, amount: Decimal
) -> tuple[tuple[tuple[str, Decimal], ...], Decimal]:
    """:func:`parse_allocations` without the sum check: ``(components, amount - their sum)``.

    Raises ``unparseable_split`` / ``split_dash_placeholder`` exactly as the strict parser does;
    the caller decides what a nonzero remainder means.
    """
    category = text.strip()
    if ":" not in category:
        return ((category, amount),), Decimal(0)
    parts = _split_components(category)
    parsed: list[tuple[str, Decimal] | None] = []
    for part in parts:
        name, sep, raw_amount = part.rpartition(":")
        if sep and name.strip() and is_dash_placeholder(raw_amount):
            raise ValueError("split_dash_placeholder")
        value: Decimal | None
        try:
            value = parse_money(raw_amount) if sep else None
        except ValueError:
            value = None
        parsed.append(None if value is None or not name.strip() else (name.strip(), value))
    if any(item is None for item in parsed):
        if _SPLIT_HINT.search(category):
            raise ValueError("unparseable_split")
        # e.g. "Programs: Field Trips" — a category name containing a colon, not a split.
        return ((category, amount),), Decimal(0)
    components = tuple(item for item in parsed if item is not None)
    return components, amount - sum((value for _, value in components), Decimal(0))


def classify_status(raw: str) -> str:
    """Map a processor status to a coarse class in ``models.STATUS_CLASSES``.

    The raw text is always retained on the record; ``unknown`` raises a row warning.
    """
    text = raw.strip().casefold()
    if "chargeback" in text or "dispute" in text:
        return "chargeback"
    if "partial" in text and "refund" in text:
        return "partially_refunded"
    if "refund" in text:
        return "refunded"
    if "revers" in text:
        return "reversed"
    if any(word in text for word in ("declin", "fail", "denied", "reject")):
        return "declined"
    if "authoriz" in text:
        return "authorized"
    if "pending" in text:
        return "pending"
    if text in {"successful", "success", "succeeded", "paid", "completed", "complete", "approved"}:
        return "successful"
    return "unknown"


_PAYPAL_EXACT_ROLES: Mapping[str, str] = {
    "shopping cart item": "detail",
    "partner fee": "fee",
    "general withdrawal": "transfer",
}
_PAYPAL_PAYMENT_TYPES = frozenset(
    {
        "website payment",
        "express checkout payment",
        "payment received",
        "mobile payment",
        "donation payment",
        "subscription payment",
        "shopping cart payment",
        "general payment",
        "invoice payment",
        "pre-approved payment",
        "pos payment",
        # "Mass Pay Payment" is deliberately absent: an outgoing payout stays unknown_type.
    }
)


def classify_paypal_type(raw_type: str) -> tuple[str, bool]:
    """Map a PayPal ``Type`` to a row role in ``models.ROW_ROLES``; flag unrecognized types.

    Returns ``(role, recognized)``. Unrecognized types default to ``payment`` but the caller
    raises an ``unknown_type`` warning so they stay reviewable, never silently counted as sales.
    """
    text = raw_type.strip().casefold()
    if text in _PAYPAL_EXACT_ROLES:
        return _PAYPAL_EXACT_ROLES[text], True
    if "hold" in text:  # e.g. "Reversal of General Account Hold" is a hold release
        return "payment", False
    if any(word in text for word in ("refund", "reversal", "chargeback")):
        return "refund", True
    if any(word in text for word in ("withdraw", "transfer", "bank deposit")):
        return "transfer", True
    if text.endswith(" fee"):
        return "fee", True
    if text in _PAYPAL_PAYMENT_TYPES:
        return "payment", True
    return "payment", False


# --------------------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------------------

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _rectangular(raw: Sequence[Sequence[Any]]) -> tuple[tuple[str, ...], ...]:
    rows = [["" if cell is None else str(cell) for cell in row] for row in raw]
    width = max((len(row) for row in rows), default=0)
    return tuple(tuple(row + [""] * (width - len(row))) for row in rows)


def _is_blank(row: Sequence[str]) -> bool:
    return all(cell.strip() == "" for cell in row)


def _capture_hash(
    *,
    alias: str,
    kind: str,
    tab_title: str,
    tab_id: int | None,
    header_rows: int,
    columns: Sequence[tuple[str, int]],
    coverage: Sequence[CoverageInterval],
    values: Sequence[Sequence[str]],
    formulas: Sequence[FormulaCell],
    entered_numbers: Sequence[EnteredNumber],
) -> str:
    return content_hash(
        {
            "alias": alias,
            "kind": kind,
            "tab_title": tab_title,
            "tab_id": tab_id,
            "header_rows": header_rows,
            "columns": sorted([name, position] for name, position in columns),
            "coverage": [interval.to_dict() for interval in coverage],
            "values": [list(row) for row in values],
            "formulas": [cell.to_dict() for cell in formulas],
            "entered_numbers": [cell.to_dict() for cell in entered_numbers],
        }
    )


def _observed_dates(
    values: Sequence[Sequence[str]], header_rows: int, position: int | None
) -> tuple[date | None, date | None]:
    if position is None:
        return None, None
    seen: list[date] = []
    for row in values[header_rows:]:
        if position >= len(row):
            continue
        try:
            parsed = parse_source_date(row[position])
        except ValueError:
            continue
        if parsed is not None:
            seen.append(parsed)
    return (min(seen), max(seen)) if seen else (None, None)


def _uncovered(
    intervals: Iterable[CoverageInterval], start: date, end_exclusive: date
) -> tuple[tuple[date, date], ...]:
    gaps: list[tuple[date, date]] = []
    cursor = start
    for interval in sorted(intervals, key=lambda item: (item.start, item.end_exclusive)):
        if interval.end_exclusive <= cursor:
            continue
        if interval.start >= end_exclusive:
            break
        if interval.start > cursor:
            gaps.append((cursor, interval.start))
        cursor = max(cursor, interval.end_exclusive)
        if cursor >= end_exclusive:
            break
    if cursor < end_exclusive:
        gaps.append((cursor, end_exclusive))
    return tuple(gaps)


def _header_differences(
    expected: Sequence[Sequence[str]], actual: Sequence[Sequence[str]]
) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    for row_index in range(max(len(expected), len(actual))):
        want = expected[row_index] if row_index < len(expected) else ()
        got = actual[row_index] if row_index < len(actual) else ()
        for column_index in range(max(len(want), len(got))):
            a = want[column_index] if column_index < len(want) else ""
            b = got[column_index] if column_index < len(got) else ""
            if a != b:
                positions.append((row_index, column_index))
    return positions


def _capture_tab(
    workbook: ReadOnlyWorkbook, resolved: ResolvedBinding, clock: Clock
) -> SourceCapture:
    binding = resolved.binding
    spec = resolved.spec
    tab_id = workbook.tab_id(binding.tab)
    if binding.tab_id is not None and tab_id != binding.tab_id:
        raise SourceSchemaError("tab_id_mismatch", f"{binding.alias}: bound tab id differs")
    captured_at = clock()
    values = _rectangular(workbook.read_values(binding.tab))
    formulas, entered_numbers = workbook.read_entered_cells(binding.tab)

    expected = tuple(_trim(row) for row in binding.header_signature)
    actual = tuple(
        _trim(values[index]) if index < len(values) else () for index in range(resolved.header_rows)
    )
    header_changed = actual != expected
    warnings: list[str] = []
    data_rows = values[resolved.header_rows :]
    if spec.kind == "credit_card":
        has_content = any(not _is_blank(row) for row in values)
        if has_content and (header_changed or any(not _is_blank(row) for row in data_rows)):
            warnings.append("uncovered_source_populated")
        if has_content and header_changed:
            warnings.append("header_signature_changed")
    elif header_changed:
        positions = _header_differences(expected, actual)
        shown = positions[:10]
        raise SourceSchemaError(
            "header_signature_mismatch",
            f"{binding.alias}: {len(positions)} header cell(s) differ from the configured "
            f"signature at (row, column) {shown}",
            positions,
        )

    columns = dict(resolved.columns)
    first, last = _observed_dates(
        values,
        resolved.header_rows,
        columns.get(spec.date_field) if spec.date_field else None,
    )
    coverage = tuple(
        CoverageInterval(start=item.start, end_exclusive=item.end_exclusive, evidence=item.evidence)
        for item in binding.coverage
    )
    if spec.kind in TRANSACTION_KINDS:
        if not any(not _is_blank(row) for row in data_rows):
            warnings.append("no_data_rows")
        if not coverage:
            warnings.append("no_declared_coverage")
        elif first is not None and last is not None:
            if _uncovered(coverage, first, last + timedelta(days=1)):
                warnings.append("observed_outside_declared_coverage")

    return SourceCapture(
        alias=binding.alias,
        kind=binding.kind,
        tab_title=binding.tab,
        tab_id=tab_id,
        captured_at=captured_at,
        header_rows=resolved.header_rows,
        header_signature=binding.header_signature,
        values=values,
        formulas=formulas,
        sha256=_capture_hash(
            alias=binding.alias,
            kind=binding.kind,
            tab_title=binding.tab,
            tab_id=tab_id,
            header_rows=resolved.header_rows,
            columns=resolved.columns,
            coverage=coverage,
            values=values,
            formulas=formulas,
            entered_numbers=entered_numbers,
        ),
        columns=resolved.columns,
        entered_numbers=entered_numbers,
        observed_first=first,
        observed_last=last,
        coverage=coverage,
        warnings=tuple(warnings),
    )


def capture_assumptions(workbook: ReadOnlyWorkbook, tab: str, clock: Clock) -> SourceCapture:
    """Capture our Assumptions tab (values, formulas, entered numbers) with its content hash.

    The one capture rule for that tab: :func:`capture` uses it inside a capture set and the
    adjustments journal writer uses it for its fresh pre-write and readback reads, so both
    hashes are directly comparable. Reads only.
    """
    tab_id = workbook.tab_id(tab)
    captured_at = clock()
    values = _rectangular(workbook.read_values(tab))
    formulas, entered_numbers = workbook.read_entered_cells(tab)
    return SourceCapture(
        alias=ASSUMPTIONS_ALIAS,
        kind=ASSUMPTIONS_ALIAS,
        tab_title=tab,
        tab_id=tab_id,
        captured_at=captured_at,
        header_rows=0,
        header_signature=(),
        values=values,
        formulas=formulas,
        sha256=_capture_hash(
            alias=ASSUMPTIONS_ALIAS,
            kind=ASSUMPTIONS_ALIAS,
            tab_title=tab,
            tab_id=tab_id,
            header_rows=0,
            columns=(),
            coverage=(),
            values=values,
            formulas=formulas,
            entered_numbers=entered_numbers,
        ),
        entered_numbers=entered_numbers,
    )


def _budget_rows_hash(rows: Sequence[Mapping[str, str]]) -> str:
    return content_hash(
        {
            "tab": report_source.BUDGET_TIMESERIES_TAB,
            "rows": [sorted(row.items()) for row in rows],
        }
    )


def _capture_budget(client: SheetsClient, clock: Clock) -> AdoptedBudget:
    captured_at = clock()
    rows = report_source.read_timeseries(client)
    warnings: list[str] = []
    if not rows:
        warnings.append("no_budget_rows")
    else:
        missing = [col for col in report_source.TIMESERIES_COLUMNS if col not in rows[0]]
        if missing:
            raise SourceSchemaError(
                "budget_schema_mismatch", f"adopted budget tab lacks columns {missing}"
            )
    proposed = report_source.MEASURE_PROPOSED.casefold()
    known = {proposed, report_source.MEASURE_ACTUAL.casefold()}
    adopted = tuple(
        tuple(sorted(row.items())) for row in rows if report_source.row_measure(row) == proposed
    )
    if any(report_source.row_measure(row) not in known for row in rows):
        warnings.append("unrecognized_measure")
    return AdoptedBudget(
        tab_title=report_source.BUDGET_TIMESERIES_TAB,
        rows=adopted,
        excluded_non_adopted_rows=len(rows) - len(adopted),
        captured_at=captured_at,
        sha256=_budget_rows_hash([dict(row) for row in adopted]),
        warnings=tuple(warnings),
    )


def _changed_aliases(
    source: ReadOnlyWorkbook,
    own: ReadOnlyWorkbook,
    own_client: SheetsClient,
    captures: Sequence[SourceCapture],
    assumptions: SourceCapture,
    budget: AdoptedBudget,
) -> tuple[str, ...]:
    """Re-read values AND entered cells (formulas/numbers); name every capture that moved."""

    def moved(workbook: ReadOnlyWorkbook, item: SourceCapture) -> bool:
        if _rectangular(workbook.read_values(item.tab_title)) != item.values:
            return True
        return workbook.read_entered_cells(item.tab_title) != (
            item.formulas,
            item.entered_numbers,
        )

    changed = [item.alias for item in captures if moved(source, item)]
    if moved(own, assumptions):
        changed.append(ASSUMPTIONS_ALIAS)
    proposed = report_source.MEASURE_PROPOSED.casefold()
    reread = [
        row
        for row in report_source.read_timeseries(own_client)
        if report_source.row_measure(row) == proposed
    ]
    if _budget_rows_hash(reread) != budget.sha256:
        changed.append("adopted_budget")
    return tuple(changed)


def _aggregate_hash(
    source_spreadsheet_id: str,
    capture_hashes: Mapping[str, str],
    adopted_budget_sha256: str,
    assumptions_sha256: str,
) -> str:
    return content_hash(
        {
            "source_spreadsheet_id": source_spreadsheet_id,
            "captures": dict(capture_hashes),
            "adopted_budget": adopted_budget_sha256,
            "assumptions": assumptions_sha256,
        }
    )


def connect_own_read_client(
    config: Config,
    *,
    gspread_client: gspread.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SheetsClient:
    """Our own workbook, opened read-only: capture only READS the budget and Assumptions.

    The write-scoped client stays reserved for the adjustments journal
    (:func:`np_finance.main_reports.adjustments.connect_journal_client`). Tests inject
    ``gspread_client``.
    """
    if gspread_client is None:
        gspread_client = gspread.service_account(
            filename=str(config.google.service_account_path), scopes=[READONLY_SCOPE]
        )
        gspread_client.set_timeout(HTTP_TIMEOUT_SECONDS)
    return SheetsClient(
        config,
        gspread_client=gspread_client,
        sleep=sleep,
        max_retries=CAPTURE_MAX_RETRIES,
        base_delay=CAPTURE_BASE_DELAY_SECONDS,
    )


def capture(
    config: Config,
    *,
    source_workbook: ReadOnlyWorkbook | None = None,
    own_client: SheetsClient | None = None,
    clock: Clock | None = None,
) -> CaptureSet:
    """Capture every bound CFO tab, our adopted budget and Assumptions once, consistently.

    Bindings are validated before any read. Google multi-tab reads are not transactional, so
    each capture is followed by a verification read; if anything changed, the WHOLE capture is
    retried once and then fails with ``capture_inconsistent``. Reads only — nothing is written.
    """
    resolved = require_bindings(config)
    main_reports = _main_reports(config)
    now = clock or _utc_now
    source = source_workbook if source_workbook is not None else connect_source_client(config)
    own_sheets = own_client if own_client is not None else connect_own_read_client(config)
    own = ReadOnlyWorkbook(own_sheets)

    previously_changed: tuple[str, ...] = ()
    for attempt in range(1, MAX_CAPTURE_ATTEMPTS + 1):
        captures = tuple(
            sorted(
                (_capture_tab(source, item, now) for item in resolved),
                key=lambda c: c.alias,
            )
        )
        assumptions = capture_assumptions(own, main_reports.assumptions_tab, now)
        budget = _capture_budget(own_sheets, now)
        changed = _changed_aliases(source, own, own_sheets, captures, assumptions, budget)
        if not changed:
            aggregate = _aggregate_hash(
                main_reports.source_spreadsheet_id,
                {c.alias: c.sha256 for c in captures},
                budget.sha256,
                assumptions.sha256,
            )
            return CaptureSet(
                source_spreadsheet_id=main_reports.source_spreadsheet_id,
                captures=captures,
                adopted_budget=budget,
                assumptions=assumptions,
                consistency=CaptureConsistency(
                    attempts=attempt, consistent=True, changed_aliases=previously_changed
                ),
                aggregate_sha256=aggregate,
            )
        previously_changed = changed
    raise SourceCaptureError(
        "capture_inconsistent",
        f"sources changed during capture on every attempt: {list(previously_changed)}",
    )


# --------------------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------------------


@dataclass
class _Row:
    """One non-blank data row with its bound columns and numeric entered values."""

    alias: str
    row_number: int
    cells: tuple[str, ...]
    columns: Mapping[str, int]
    entered: Mapping[tuple[int, int], str]
    formula_cells: frozenset[tuple[int, int]] = frozenset()

    def get(self, name: str) -> str:
        position = self.columns.get(name)
        if position is None or position >= len(self.cells):
            return ""
        return self.cells[position]

    def entered_number(self, name: str) -> str | None:
        position = self.columns.get(name)
        if position is None:
            return None
        return self.entered.get((self.row_number - 1, position))

    def is_formula(self, name: str) -> bool:
        position = self.columns.get(name)
        return position is not None and (self.row_number - 1, position) in self.formula_cells


@dataclass
class _RowCheck:
    row: _Row
    issues: list[RowIssue] = field(default_factory=list)

    def error(self, code: str, field_name: str | None) -> None:
        self.issues.append(RowIssue(self.row.alias, self.row.row_number, code, field_name, "error"))

    def warning(self, code: str, field_name: str | None) -> None:
        self.issues.append(
            RowIssue(self.row.alias, self.row.row_number, code, field_name, "warning")
        )

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def text(self, name: str, *, required: bool) -> str | None:
        value = self.row.get(name).strip()
        if value:
            return value
        if required:
            self.error("missing_value", name)
        return None

    def source_date(self, name: str, *, required: bool) -> date | None:
        return self.date_text(self.row.get(name), name, required=required)

    def date_text(self, raw: str, name: str, *, required: bool) -> date | None:
        try:
            value = parse_source_date(raw)
        except ValueError as exc:
            self.error(str(exc), name)  # invalid_date | date_out_of_range
            return None
        if value is None and required:
            self.error("missing_value", name)
        return value

    def money(self, name: str, *, required: bool) -> Decimal | None:
        entered = self.row.entered_number(name)
        try:
            value = parse_money(self.row.get(name))
        except ValueError as exc:
            code = str(exc)
            if code != "dash_placeholder":
                self.error(code, name)
                return None
            return self._dash(name, entered, required=required)
        if value is None:
            if required:
                self.error("missing_value", name)
            return None
        if entered is not None:
            # Binary-float noise (0.30000000000000004) is tolerated; hidden sub-cent
            # precision (>= 0.0001) is not.
            if not entered_matches(entered, value):
                # The display format hides the entered value (e.g. sub-cent precision).
                self.error("display_precision_mismatch", name)
                return None
        elif self.row.is_formula(name):
            # A computed money cell has no entered number to verify against; say so.
            self.warning("formula_money_unverified", name)
        return value

    def _dash(self, name: str, entered: str | None, *, required: bool) -> Decimal | None:
        """A bare dash is 0.00 only when the entered value is numeric zero (Accounting zero).

        A nonzero entered number shown as a dash is ``display_precision_mismatch``. A FORMULA
        cell has no entered number, so even a computed zero cannot be proven: it fails closed as
        ``formula_dash_unverified`` (error when required, warning + ``None`` when optional) —
        deliberately NOT ``missing_value``, because the value exists but is unverifiable. A TEXT
        dash is a placeholder: ``missing_value`` when required; otherwise absent (``None``) with
        a countable ``dash_placeholder`` warning.
        """
        if entered is not None:
            if entered_matches(entered, _ZERO_CENTS):
                return _ZERO_CENTS
            self.error("display_precision_mismatch", name)
            return None
        if self.row.is_formula(name):
            if required:
                self.error("formula_dash_unverified", name)
            else:
                self.warning("formula_dash_unverified", name)
            return None
        if required:
            self.error("missing_value", name)
        else:
            self.warning("dash_placeholder", name)
        return None

    def currency(self, *, required: bool) -> str | None:
        value = self.text("currency", required=required)
        if value is None:
            return None
        if value.upper() != _USD:
            self.error("unsupported_currency", "currency")
            return None
        return _USD


@dataclass
class _Collected:
    excluded: list[ExcludedRow] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)


@dataclass
class _Draft:
    row_number: int
    identity: tuple[str, ...]
    revision: str
    fields: dict[str, Any]
    allocations: tuple[tuple[str, Decimal], ...] = ()
    group_id: str | None = None
    # True when identity rests on a source-native ID: repeats are ambiguous, not legitimate.
    native_identity: bool = False


def _rows(capture_item: SourceCapture) -> Iterator[_Row]:
    columns = dict(capture_item.columns)
    entered = {(cell.row, cell.column): cell.value for cell in capture_item.entered_numbers}
    formula_cells = frozenset((cell.row, cell.column) for cell in capture_item.formulas)
    for offset, cells in enumerate(capture_item.data_rows):
        if not _is_blank(cells):
            yield _Row(
                alias=capture_item.alias,
                row_number=capture_item.header_rows + offset + 1,
                cells=cells,
                columns=columns,
                entered=entered,
                formula_cells=formula_cells,
            )


def _revision(capture_item: SourceCapture, row: _Row) -> str:
    """Hash of the row's source fields (trailing padding ignored, so widening never matters)."""
    return content_hash(
        {"alias": capture_item.alias, "kind": capture_item.kind, "values": list(_trim(row.cells))}
    )


def _is_summary_label(cell: str) -> bool:
    text = cell.strip().rstrip(":").rstrip()
    return len(text) <= _SUMMARY_CELL_LIMIT and _SUMMARY_LABEL.fullmatch(text) is not None


def _exclude_summary(
    capture_item: SourceCapture,
    row: _Row,
    primary: Sequence[str],
    out: _Collected,
    label_fields: Sequence[str] = (),
) -> bool:
    """Exclude a subtotal/summary row — always visibly (excluded list AND a warning issue).

    A row is a summary row when (a) a ``label_fields`` cell (the bank DESCRIPTION) is exactly
    a summary label ("Total", "Ending balance", ...), even on a dated row; or (b) some cell is
    exactly a summary label and every primary field (date / native ID) is blank or itself that
    label — so a label in the leftmost DATE column is recognized. A real row whose description
    merely begins with "Total" (a store name) is NOT excluded and is validated normally.
    """
    labelled = any(_is_summary_label(row.get(name)) for name in label_fields)
    if not labelled:
        if not any(_is_summary_label(cell) for cell in row.cells if cell):
            return False
        for name in primary:
            value = row.get(name)
            if value.strip() and not _is_summary_label(value):
                return False
    out.excluded.append(
        ExcludedRow(capture_item.alias, row.row_number, "summary_row", _revision(capture_item, row))
    )
    out.issues.append(
        RowIssue(capture_item.alias, row.row_number, "summary_row_excluded", None, "warning")
    )
    return True


def _bank_drafts(capture_item: SourceCapture, out: _Collected) -> list[_Draft]:
    drafts: list[_Draft] = []
    for row in _rows(capture_item):
        if _exclude_summary(capture_item, row, ("date",), out, label_fields=("description",)):
            continue
        check = _RowCheck(row)
        posting = check.source_date("date", required=True)
        description = check.text("description", required=True)
        amount = check.money("amount", required=True)
        check_number = check.text("check_number", required=False)
        status = check.text("status", required=False)
        category = check.text("category", required=False)
        override = check.text("override_category", required=False)
        final = check.text("final_category", required=False)
        effective = final or override or category
        if final is None and effective is not None:
            check.warning("final_category_fallback", "final_category")
        if effective is None:
            check.error("missing_value", "final_category")
        allocations: tuple[tuple[str, Decimal], ...] = ()
        if effective is not None and amount is not None:
            try:
                allocations, remainder = _split_allocations(effective, amount)
            except ValueError as exc:
                check.error(str(exc), "final_category")
            else:
                if remainder:
                    # Published, not halted: the signed gap is its own explicit component, so
                    # the allocations still conserve the bank amount exactly.
                    check.warning("split_sum_mismatch", "final_category")
                    allocations = (*allocations, (UNALLOCATED_SPLIT_CATEGORY, remainder))
        out.issues.extend(check.issues)
        if not check.ok or posting is None or amount is None or description is None:
            continue
        identity = ("bank", posting.isoformat(), description, money_str(amount), check_number or "")
        drafts.append(
            _Draft(
                row_number=row.row_number,
                identity=identity,
                revision=_revision(capture_item, row),
                allocations=allocations,
                fields={
                    "source_kind": "bank",
                    "row_role": "bank",
                    "currency": _USD,
                    "source_values": row.cells,
                    "description": description,
                    "check_number": check_number,
                    "source_status": status,
                    "gross": amount,
                    "net": amount,
                    "posting_date": posting,
                    "original_timestamp": row.get("date").strip() or None,
                    "raw_category": category,
                    "override_category": override,
                    "final_category": final,
                },
            )
        )
    return drafts


def _wix_drafts(capture_item: SourceCapture, out: _Collected) -> list[_Draft]:
    drafts: list[_Draft] = []
    for row in _rows(capture_item):
        if _exclude_summary(capture_item, row, ("payment_date", "provider_payment_id"), out):
            continue
        check = _RowCheck(row)
        payment_id = check.text("provider_payment_id", required=False)
        payment_date = check.source_date("payment_date", required=True)
        timestamp = check.text("transaction_datetime", required=True)
        if timestamp is not None:
            check.date_text(timestamp, "transaction_datetime", required=True)
        offset = check.text("timezone_offset", required=False)
        currency = check.currency(required=True)
        amount = check.money("amount", required=True)
        processing_fee = check.money("processing_fee", required=False)
        service_fee = check.money("service_fee", required=False)
        if any(
            issue.code in _UNPROVEN_DASH_CODES and issue.field in _WIX_FEE_FIELDS
            for issue in check.issues
        ):
            # A dash fee component is absent, so the summed fee would silently understate.
            check.error("fee_component_unresolved", "fee")
        net = check.money("net", required=False)
        refund = check.money("refund_amount", required=False)
        status = check.text("transaction_status", required=True)
        provider = check.text("payment_provider", required=True)
        order_id = check.text("order_id", required=False)
        product = check.text("product_name", required=False)
        quantity = check.text("quantity", required=False)
        status_class = classify_status(status) if status else None
        if status_class == "unknown":
            check.warning("unknown_status", "transaction_status")
        if payment_id is None:
            check.warning("missing_native_id", "provider_payment_id")
        out.issues.extend(check.issues)
        if not check.ok or amount is None:
            continue
        components = tuple(
            (name, value)
            for name, value in (("processing_fee", processing_fee), ("service_fee", service_fee))
            if value is not None
        )
        fee = sum((value for _, value in components), Decimal(0)) if components else None
        identity = (
            ("wix", "payment", payment_id)
            if payment_id
            else (
                "wix",
                "payment",
                "fallback",
                order_id or "",
                timestamp or "",
                money_str(amount),
                product or "",
            )
        )
        drafts.append(
            _Draft(
                row_number=row.row_number,
                identity=identity,
                revision=_revision(capture_item, row),
                native_identity=payment_id is not None,
                fields={
                    "source_kind": "wix",
                    "row_role": "payment",
                    "currency": currency,
                    "source_values": row.cells,
                    "native_id": payment_id,
                    "order_id": order_id,
                    "source_status": status,
                    "status_class": status_class,
                    "payment_provider": provider,
                    "product_name": product,
                    "quantity": quantity,
                    "gross": amount,
                    "fee": fee,
                    "fee_components": components,
                    "refund": refund,
                    "net": net,
                    "payment_date": payment_date,
                    "original_timestamp": timestamp,
                    "original_offset": offset,
                },
            )
        )
    return drafts


def _paypal_drafts(capture_item: SourceCapture, out: _Collected) -> list[_Draft]:
    drafts: list[_Draft] = []
    for row in _rows(capture_item):
        if _exclude_summary(capture_item, row, ("transaction_id", "date"), out):
            continue
        check = _RowCheck(row)
        txn_id = check.text("transaction_id", required=True)
        raw_type = check.text("type", required=True)
        role, recognized = classify_paypal_type(raw_type) if raw_type else ("payment", True)
        if not recognized:
            check.warning("unknown_type", "type")
        parent_row = role != "detail"
        payment_date = check.source_date("date", required=True)
        time_text = check.text("time", required=False)
        timezone = check.text("timezone", required=False)
        status = check.text("status", required=parent_row)
        currency = check.currency(required=parent_row)
        gross = check.money("gross", required=parent_row)
        fee = check.money("fee", required=False)
        net = check.money("net", required=parent_row)
        balance_impact = check.text("balance_impact", required=False)
        reference = check.text("reference_txn_id", required=False)
        item_title = check.text("item_title", required=False)
        quantity = check.text("quantity", required=False)
        status_class = classify_status(status) if status else None
        if status_class == "unknown":
            check.warning("unknown_status", "status")
        out.issues.extend(check.issues)
        if not check.ok or txn_id is None:
            continue
        revision = _revision(capture_item, row)
        identity = (
            ("paypal", "detail", txn_id, revision) if role == "detail" else ("paypal", role, txn_id)
        )
        original_timestamp = " ".join(
            part for part in (row.get("date").strip(), time_text or "") if part
        )
        drafts.append(
            _Draft(
                row_number=row.row_number,
                identity=identity,
                revision=revision,
                group_id=txn_id,
                native_identity=role != "detail",
                fields={
                    "source_kind": "paypal",
                    "row_role": role,
                    "currency": currency,
                    "source_values": row.cells,
                    "native_id": txn_id,
                    "reference_id": reference,
                    "source_status": status,
                    "status_class": status_class,
                    "source_type": raw_type,
                    "balance_impact": balance_impact,
                    "product_name": item_title,
                    "quantity": quantity,
                    "gross": gross,
                    "fee": fee,
                    "fee_components": (("fee", fee),) if fee is not None else (),
                    "net": net,
                    "payment_date": payment_date,
                    "original_timestamp": original_timestamp or None,
                    "original_offset": timezone,
                },
            )
        )
    return drafts


_DRAFTERS: Mapping[str, Callable[[SourceCapture, _Collected], list[_Draft]]] = {
    "bank": _bank_drafts,
    "wix": _wix_drafts,
    "paypal": _paypal_drafts,
}
if tuple(_DRAFTERS) != TRANSACTION_KINDS:  # pragma: no cover - import-time invariant
    raise RuntimeError("_DRAFTERS must cover models.TRANSACTION_KINDS exactly, in order")


def _assign_keys(
    capture_item: SourceCapture, drafts: Sequence[_Draft], out: _Collected
) -> dict[int, str]:
    """Deterministic occurrence over equal identities: reordering never collapses rows.

    Occurrences are ordered by revision hash, so an unchanged multiset keeps its keys under
    any row order. Equal identities with DIFFERENT revisions (or repeated native IDs) cannot
    be told apart reliably after an edit, so every member gets a reviewable warning; a
    ``(record_key, revision_hash)`` pair still always names a row with exactly that content.
    """
    groups: dict[tuple[str, ...], list[_Draft]] = {}
    for draft in drafts:
        groups.setdefault(draft.identity, []).append(draft)
    keys: dict[int, str] = {}
    for identity, members in groups.items():
        if len(members) > 1:
            code = None
            if members[0].native_identity:
                code = "duplicate_native_id"
            elif len({draft.revision for draft in members}) > 1:
                code = "ambiguous_duplicate_identity"
            if code is not None:
                for draft in members:
                    out.issues.append(
                        RowIssue(capture_item.alias, draft.row_number, code, None, "warning")
                    )
        for occurrence, draft in enumerate(
            sorted(members, key=lambda d: (d.revision, d.row_number))
        ):
            keys[draft.row_number] = make_record_key(capture_item.alias, identity, occurrence)
    return keys


def _paypal_parents(
    capture_item: SourceCapture,
    drafts: Sequence[_Draft],
    keys: Mapping[int, str],
    out: _Collected,
) -> dict[int, str | None]:
    by_group: dict[str, list[_Draft]] = {}
    for draft in drafts:
        if draft.fields["row_role"] != "detail" and draft.group_id is not None:
            by_group.setdefault(draft.group_id, []).append(draft)
    parents: dict[int, str | None] = {}
    for draft in drafts:
        if draft.fields["row_role"] != "detail":
            continue
        candidates = by_group.get(draft.group_id or "", [])
        preferred = [c for c in candidates if c.fields["row_role"] == "payment"] or candidates
        if len(preferred) == 1:
            parents[draft.row_number] = keys[preferred[0].row_number]
            continue
        code = "orphan_detail" if not preferred else "ambiguous_parent"
        out.issues.append(
            RowIssue(capture_item.alias, draft.row_number, code, "transaction_id", "warning")
        )
        parents[draft.row_number] = None
    return parents


def _as_captures(
    captures: CaptureSet | Mapping[str, SourceCapture] | Iterable[SourceCapture],
) -> list[SourceCapture]:
    if isinstance(captures, CaptureSet):
        return list(captures.captures)
    if isinstance(captures, Mapping):
        return [captures[alias] for alias in sorted(captures)]
    return sorted(captures, key=lambda c: c.alias)


def normalize_with_report(
    captures: CaptureSet | Mapping[str, SourceCapture] | Iterable[SourceCapture],
) -> NormalizationResult:
    """Normalize every transaction-kind capture; report excluded rows and row issues.

    Rows with an error-severity issue are NOT emitted (never guessed); control captures are
    skipped. The result is a pure function of the capture values: re-normalizing an unchanged
    capture yields identical records.
    """
    collected = _Collected()
    transactions: list[Transaction] = []
    for item in _as_captures(captures):
        drafter = _DRAFTERS.get(item.kind)
        if drafter is None:
            continue
        drafts = drafter(item, collected)
        keys = _assign_keys(item, drafts, collected)
        parents = _paypal_parents(item, drafts, keys, collected) if item.kind == "paypal" else {}
        currency_by_key = {keys[d.row_number]: d.fields["currency"] for d in drafts}
        for draft in sorted(drafts, key=lambda d: d.row_number):
            key = keys[draft.row_number]
            if draft.fields["currency"] is None:
                # A PayPal detail row without its own Currency inherits its unambiguous
                # parent's currency explicitly; otherwise it is an error, never assumed USD.
                parent_key = parents.get(draft.row_number)
                inherited = currency_by_key.get(parent_key) if parent_key else None
                if inherited is None:
                    collected.issues.append(
                        RowIssue(
                            item.alias, draft.row_number, "currency_unresolved", "currency", "error"
                        )
                    )
                    continue
                draft.fields["currency"] = inherited
            ref = SourceRef(
                source_alias=item.alias,
                snapshot_sha256=item.sha256,
                tab_id=item.tab_id,
                row_number=draft.row_number,
                record_key=key,
                revision_hash=draft.revision,
            )
            allocations = tuple(
                Allocation(record_key=key, revision_hash=draft.revision, category=c, amount=a)
                for c, a in draft.allocations
            )
            transactions.append(
                Transaction(
                    record_key=key,
                    revision_hash=draft.revision,
                    refs=(ref,),
                    parent_key=parents.get(draft.row_number),
                    allocations=allocations,
                    **draft.fields,
                )
            )
    issues = sorted(collected.issues, key=lambda i: (i.source_alias, i.row_number, i.code))
    return NormalizationResult(
        transactions=tuple(transactions),
        excluded=tuple(collected.excluded),
        issues=tuple(issues),
    )


def normalize(
    captures: CaptureSet | Mapping[str, SourceCapture] | Iterable[SourceCapture],
) -> tuple[Transaction, ...]:
    """Normalize captures to transactions; raise :class:`SourceValidationError` on row errors."""
    result = normalize_with_report(captures)
    if result.errors:
        raise SourceValidationError(result.errors)
    return result.transactions


def read_category_mapping(capture_item: SourceCapture) -> tuple[CategoryRule, ...]:
    """Read Category Mapping keyword rules (guidance only; never overrides FINAL CATEGORY)."""
    rules, issues = read_category_mapping_with_report(capture_item)
    if issues:
        raise SourceValidationError(issues)
    return rules


def read_category_mapping_with_report(
    capture_item: SourceCapture,
) -> tuple[tuple[CategoryRule, ...], tuple[RowIssue, ...]]:
    """Category Mapping rules from complete rows, plus a row issue for each incomplete row.

    Guidance consumers that must not halt on one half-filled row use this form and surface
    the issues; :func:`read_category_mapping` raises on them instead.
    """
    if capture_item.kind != "category_mapping":
        raise SourceConfigError("wrong_kind", f"{capture_item.alias} is not a category mapping")
    rules: list[CategoryRule] = []
    issues: list[RowIssue] = []
    for row in _rows(capture_item):
        check = _RowCheck(row)
        keyword = check.text("keyword", required=True)
        target = check.text("target_category", required=True)
        issues.extend(check.issues)
        if keyword is not None and target is not None:
            rules.append(
                CategoryRule(keyword=keyword, target_category=target, row_number=row.row_number)
            )
    return tuple(rules), tuple(issues)


# --------------------------------------------------------------------------------------
# Coverage and change detection
# --------------------------------------------------------------------------------------


def coverage_status(
    capture_item: SourceCapture, start: date, end_exclusive: date
) -> CoverageStatus:
    """Which parts of ``[start, end_exclusive)`` lack declared coverage evidence."""
    if end_exclusive <= start:
        raise ValueError("empty_coverage_window")
    uncovered = _uncovered(capture_item.coverage, start, end_exclusive)
    return CoverageStatus(
        source_alias=capture_item.alias,
        start=start,
        end_exclusive=end_exclusive,
        complete=not uncovered,
        uncovered=uncovered,
        observed_first=capture_item.observed_first,
        observed_last=capture_item.observed_last,
    )


def compare_transactions(
    previous: Iterable[Transaction], current: Iterable[Transaction]
) -> tuple[SourceChange, ...]:
    """Record-level differences between two normalizations (added / missing / revised)."""
    before = {txn.record_key: txn.revision_hash for txn in previous}
    after = {txn.record_key: txn.revision_hash for txn in current}
    changes: list[SourceChange] = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old is None:
            changes.append(SourceChange("added", key, None, new))
        elif new is None:
            changes.append(SourceChange("missing", key, old, None))
        elif old != new:
            changes.append(SourceChange("revised", key, old, new))
    return tuple(changes)


def compare_captures(previous: CaptureSet, current: CaptureSet) -> tuple[str, ...]:
    """Names of captures whose content hash differs (or that appeared/disappeared)."""
    before = {c.alias: c.sha256 for c in previous.captures}
    after = {c.alias: c.sha256 for c in current.captures}
    changed = [
        alias for alias in sorted(set(before) | set(after)) if before.get(alias) != after.get(alias)
    ]
    if previous.adopted_budget.sha256 != current.adopted_budget.sha256:
        changed.append("adopted_budget")
    if previous.assumptions.sha256 != current.assumptions.sha256:
        changed.append(ASSUMPTIONS_ALIAS)
    return tuple(changed)


# --------------------------------------------------------------------------------------
# Private provenance persistence
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredCapture:
    path: Path
    manifest_path: Path
    created: bool


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _stored_capture_hash(entry: Mapping[str, Any]) -> str:
    columns = entry["columns"]
    return _capture_hash(
        alias=entry["alias"],
        kind=entry["kind"],
        tab_title=entry["tab_title"],
        tab_id=entry["tab_id"],
        header_rows=entry["header_rows"],
        columns=[(str(name), int(position)) for name, position in columns.items()],
        coverage=[
            CoverageInterval(
                start=date.fromisoformat(item["start"]),
                end_exclusive=date.fromisoformat(item["end_exclusive"]),
                evidence=item["evidence"],
            )
            for item in entry["coverage"]
        ],
        values=entry["values"],
        formulas=[FormulaCell(f["row"], f["column"], f["formula"]) for f in entry["formulas"]],
        entered_numbers=[
            EnteredNumber(n["row"], n["column"], n["value"]) for n in entry["entered_numbers"]
        ],
    )


def _verify_stored(stored: Any, digest: str) -> bool:
    """Recompute every content hash from the stored file; never trust declared hashes."""
    try:
        captures = stored["captures"]
        hashes: dict[str, str] = {}
        for alias, entry in captures.items():
            recomputed = _stored_capture_hash(entry)
            if recomputed != entry["sha256"] or alias != entry["alias"]:
                return False
            hashes[alias] = recomputed
        assumptions = stored["assumptions"]
        assumptions_hash = _stored_capture_hash(assumptions)
        budget = stored["adopted_budget"]
        budget_hash = _budget_rows_hash(budget["rows"])
        if assumptions_hash != assumptions["sha256"] or budget_hash != budget["sha256"]:
            return False
        aggregate = _aggregate_hash(
            stored["source_spreadsheet_id"], hashes, budget_hash, assumptions_hash
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return bool(aggregate == digest and stored.get("aggregate_sha256") == digest)


def store_capture_set(capture_set: CaptureSet, root: Path) -> StoredCapture:
    """Persist a capture set content-addressed under ``<root>/captures/`` (private output).

    ``root`` is the configured ``main_reports.output_path``, which the config loader confines
    to the gitignored ``reports/output/`` tree or a location outside the project. Writes
    ``<aggregate>.json`` (full values/formulas) and ``<aggregate>.manifest.json`` (provenance
    without cell values). The aggregate hash covers the workbook binding, declared coverage
    and all captured content, so re-storing an identical input set is a no-op that keeps the
    first evidence (idempotent duplicate import). An existing file is accepted only if every
    content hash recomputed from its stored values matches; anything else is a conflict and is
    never overwritten. The digest must be a 64-character lowercase hex string (path-safe).
    """
    digest = capture_set.aggregate_sha256
    if HEX_DIGEST_PATTERN.match(digest) is None:
        raise SourceCaptureError("invalid_digest", "aggregate hash is not a sha256 hex digest")
    directory = Path(root) / "captures"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.json"
    manifest_path = directory / f"{digest}.manifest.json"
    if path.exists():
        stored: Any
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = None
        if not isinstance(stored, dict) or not _verify_stored(stored, digest):
            raise SourceCaptureError("stored_capture_conflict", "stored capture does not verify")
        if not manifest_path.exists():
            _atomic_write(manifest_path, canonical_json_bytes(capture_set.manifest()))
        return StoredCapture(path=path, manifest_path=manifest_path, created=False)
    _atomic_write(path, canonical_json_bytes(capture_set.to_dict()))
    _atomic_write(manifest_path, canonical_json_bytes(capture_set.manifest()))
    return StoredCapture(path=path, manifest_path=manifest_path, created=True)
