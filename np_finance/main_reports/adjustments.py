"""Evidence-backed reporting adjustments: journal reader/writer and adjusted projection.

Contract: ``docs/plan-reference/cfo-main-report-set.md`` sections 6D and 10.

* **Journal.** Our own workbook's Assumptions tab holds a bounded, append-only journal below
  every existing cell: the marker :data:`JOURNAL_MARKER` alone in column A, then the
  :data:`JOURNAL_COLUMNS` header, then one row per :class:`~np_finance.main_reports.models.
  Adjustment`. :func:`read_journal` parses it from a capture (reads only); a missing section
  means "no adjustments" and is never created by a read. Duplicate, misplaced or malformed
  markers, a changed header, a formula or any other content inside the region fail closed.
* **Projection.** :func:`project` applies the entries in effect on ``as_of`` to a COPY of the
  reconciled bank source view and returns an
  :class:`~np_finance.main_reports.models.AdjustedLedger` with signed source-to-adjusted
  deltas. Source transactions, reconciliation states and discrepancies are never changed,
  and no entry resolves a discrepancy. A conflicting or unresolved target revision, a
  competing replacement, an unreadable row or a broken supersession chain is a blocking
  conflict (:func:`require_publishable`); recorded entries take effect immediately on the
  next projection, with no second approval gate.
* **Recording.** :func:`record` is the ONLY write in the Main Report Set, and it targets only
  our own workbook (never the CFO source, whose client is read-only). Under the local writer
  lock it re-reads the tab and requires the run's captured hash, validates every proposal's
  target revision and prior value, snapshots exact entered values/formulas
  (:func:`np_finance.backup.snapshot_raw_tab`), re-reads again, writes only new cells below
  existing content with ``RAW`` input in one request, and verifies the whole journal plus
  every pre-existing cell by readback. A failed write request is resolved by a whole-tab
  readback: the same hash as before the write means it has not landed; the planned journal
  cells with nothing else changed (:func:`_verify`) means it landed; anything else is a
  concurrent change and stops. The writer's own re-send rule (:func:`_resend_allowed`):
  only a failure that carries no HTTP status at all (any type: a lost connection or
  response, a timeout, a non-HTTP error from the worksheet lookup) or a status the Sheets
  client treats as transient (:func:`np_finance.sheets.is_transient_status`: 429/500/503)
  is sent again, under the client's attempt cap and backoff
  (:meth:`~np_finance.sheets.SheetsClient.backoff_delay` / ``pause``). Every re-send is
  preceded by the pause, a lock re-check and a fresh whole-tab readback: a write seen to
  have landed by then is not sent again, and an edit seen meanwhile is refused. A small
  window remains between that last readback and the re-send; a late landing inside it is
  harmless, because the re-send writes the same absolute ranges with identical values and
  the final readback (:func:`_verify`) still requires exactly the planned journal. Any
  other status stops after the readback with no re-send; only a first attempt refused with
  400/401/403/404 and the tab unchanged is reported as not landed. A later rerun skips
  proposals whose ID the journal already holds with the same content. Nothing is ever
  cleared, edited in place or restored automatically.

Limit (stated, not hidden): Google Sheets offers no compare-and-swap. The pre-write reads and
the post-write readback DETECT another editor's concurrent change and stop publication with
retained evidence, but they cannot prevent an edit landing between the last read and the
write. Keep journal edits to this writer during a write; record manual corrections as new
rows between runs.

Reporting corrections never approve, pay or alter a reimbursement claim: the kind vocabulary
(:data:`~np_finance.main_reports.models.ADJUSTMENT_KINDS`) is closed and this module touches
no reimbursement data. Error and issue text names codes, rows, fields and adjustment IDs only,
never a cell or money value.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Any

import gspread
from gspread.utils import rowcol_to_a1

from np_finance import backup
from np_finance.config import Config, MainReports
from np_finance.main_reports.models import (
    ADJUSTMENT_KINDS,
    ALLOCATION_ORIGINS,
    DISCREPANCY_ID_PREFIX,
    HEX_DIGEST_PATTERN,
    ISSUE_SEVERITIES,
    AdjustedAllocation,
    AdjustedLedger,
    Adjustment,
    AdjustmentDelta,
    AdjustmentIssue,
    AdjustmentJournal,
    JournalEntry,
    MonthlyCategoryCell,
    Reconciliation,
    SourceCapture,
    Transaction,
    canonical_json_bytes,
    content_hash,
    is_valid_adjustment_id,
    is_valid_record_key,
    money_str,
    month_totals_from,
    monthly_cells_from,
)
from np_finance.main_reports.reconcile import INTERNAL_TRANSFER_CATEGORY
from np_finance.main_reports.sources import (
    ASSUMPTIONS_ALIAS,
    HTTP_TIMEOUT_SECONDS,
    Clock,
    ReadOnlyWorkbook,
    capture_assumptions,
    entered_matches,
    parse_money,
    parse_source_date,
)
from np_finance.sheets import (
    SHEETS_FAILURES,
    SheetsClient,
    http_status,
    is_transient_status,
)

__all__ = [
    # constants
    "JOURNAL_MARKER",
    "JOURNAL_COLUMNS",
    "JOURNAL_GAP_ROWS",
    "MAX_JOURNAL_ENTRIES",
    "MAX_PROPOSALS",
    "MAX_FIELD_TEXT",
    "MAX_CATEGORY_TEXT",
    "MAX_PROPOSALS_FILE_BYTES",
    "MAX_AMOUNT",
    "PROPOSALS_SCHEMA_VERSION",
    "WRITE_SCOPE",
    "LOCK_FILENAME",
    "SNAPSHOT_DIR",
    # functions
    "read_journal",
    "load_proposals",
    "parse_proposals",
    "project",
    "require_publishable",
    "acquire_run_lock",
    "connect_journal_client",
    "record",
    # types
    "AdjustmentError",
    "JournalLayoutError",
    "ProposalError",
    "AdjustmentConflictError",
    "AdjustmentWriteError",
    "RunBusyError",
    "RunLock",
    "RecordResult",
]

JOURNAL_MARKER = "PTA_REPORT_ADJUSTMENTS_V1"
# Column order of the journal; the names are exactly the keys of ``Adjustment.to_dict``.
JOURNAL_COLUMNS: tuple[str, ...] = (
    "adjustment_id",
    "targets",
    "kind",
    "effective_date",
    "prior_value",
    "replacement_value",
    "signed_amount",
    "category",
    "reason",
    "evidence",
    "recorded_at",
    "supersedes",
)
# Blank rows left between existing Assumptions content and a newly reserved section.
JOURNAL_GAP_ROWS = 2
MAX_JOURNAL_ENTRIES = 1000
MAX_PROPOSALS = 50
MAX_FIELD_TEXT = 2000
# A new destination category must be short, printable text that no spreadsheet can read as
# a formula (it flows into later reports and Sheets).
MAX_CATEGORY_TEXT = 100
MAX_PROPOSALS_FILE_BYTES = 1_000_000
# Any amount (signed, prior or replacement) must be strictly below this magnitude: exact-cent
# sums then always stay inside the default decimal precision.
MAX_AMOUNT = Decimal("1000000000000")
PROPOSALS_SCHEMA_VERSION = 1
WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
LOCK_FILENAME = "main-report.lock"
# Pre-write snapshots and readback evidence live here, under the private output root.
SNAPSHOT_DIR = "adjustments"

_MARKER_PREFIX = "pta_report_adjustments"
_LIST_SEPARATOR = ";"
_TARGET_SEPARATOR = "@"
_WIDTH = len(JOURNAL_COLUMNS)
_ZERO = Decimal("0.00")
_ERROR, _WARNING = ISSUE_SEVERITIES
_SOURCE, _ADDITIVE = ALLOCATION_ORIGINS
# HTTP statuses that prove a write was rejected outright (auth, permission, request shape):
# never retried blindly.
_REJECTED_STATUSES = frozenset({400, 401, 403, 404})

# kind -> (required fields, forbidden fields, number of targets). One correction
# representation per kind: replacement kinds never carry a signed amount and vice versa.
_KIND_RULES: Mapping[str, tuple[frozenset[str], frozenset[str], int]] = {
    "category_override": (
        frozenset({"prior_value", "replacement_value"}),
        frozenset({"signed_amount", "category"}),
        1,
    ),
    "date_override": (
        frozenset({"prior_value", "replacement_value"}),
        frozenset({"signed_amount", "category"}),
        1,
    ),
    "amount_correction": (
        frozenset({"prior_value", "replacement_value", "category"}),
        frozenset({"signed_amount"}),
        1,
    ),
    "additive": (
        frozenset({"signed_amount", "category"}),
        frozenset({"prior_value", "replacement_value"}),
        0,
    ),
    "reversal": (
        frozenset({"supersedes"}),
        frozenset({"prior_value", "replacement_value", "signed_amount", "category"}),
        0,
    ),
}
if tuple(_KIND_RULES) != ADJUSTMENT_KINDS:  # pragma: no cover - import-time invariant
    raise RuntimeError("_KIND_RULES must cover models.ADJUSTMENT_KINDS exactly, in order")
# Kinds applied in this order, so each precondition is checked against source values.
_APPLY_ORDER: tuple[str, ...] = ("amount_correction", "category_override", "date_override")


# --------------------------------------------------------------------------------------
# Errors (messages name codes, rows, fields and adjustment IDs — never cell values)
# --------------------------------------------------------------------------------------


class AdjustmentError(Exception):
    """Base error carrying a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _describe(issues: Sequence[AdjustmentIssue]) -> str:
    shown = "; ".join(
        issue.code
        + (f" row {issue.row_number}" if issue.row_number is not None else "")
        + (f" ({issue.field})" if issue.field else "")
        + (f" {issue.adjustment_id}" if issue.adjustment_id else "")
        for issue in issues[:10]
    )
    more = "" if len(issues) <= 10 else f"; +{len(issues) - 10} more"
    return f"{len(issues)} issue(s): {shown}{more}"


class JournalLayoutError(AdjustmentError):
    """The journal section cannot be located or bounded safely; nothing is applied."""


class ProposalError(AdjustmentError):
    """An adjustments file or proposal batch is invalid; ``issues`` lists every finding."""

    def __init__(self, issues: Sequence[AdjustmentIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("proposals_invalid", _describe(self.issues))


class AdjustmentConflictError(AdjustmentError):
    """Recording or adjusted publication is blocked by the listed conflicts."""

    def __init__(self, code: str, issues: Sequence[AdjustmentIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(code, _describe(self.issues))


class AdjustmentWriteError(AdjustmentError):
    """A journal write failed, could not be verified, or met a concurrent edit.

    ``evidence`` lists the private before/after files retained for review. The live tab is
    never restored automatically. ``cause`` names the underlying transport failure (error
    type and HTTP status, e.g. ``APIError 503``); the raw exception is not chained because
    its text can carry the private workbook binding. ``may_have_landed`` is set by each raise
    site: ``False`` only when no journal cell can have been written (the failure came before
    the write request, or the request was rejected and the readback shows the tab unchanged);
    otherwise ``True`` (recapture and check before trusting the journal either way).
    """

    def __init__(
        self,
        code: str,
        message: str,
        evidence: Sequence[Path] = (),
        cause: str | None = None,
        *,
        may_have_landed: bool,
    ) -> None:
        self.evidence = tuple(evidence)
        self.cause = cause
        self.may_have_landed = may_have_landed
        super().__init__(code, message if cause is None else f"{message} (cause: {cause})")


class RunBusyError(AdjustmentError):
    """Another local writer holds the Main Report Set lock."""


def _main_reports(config: Config) -> MainReports:
    if config.main_reports is None:
        raise AdjustmentError("main_reports_missing", "config.toml has no [main_reports] section")
    return config.main_reports


# --------------------------------------------------------------------------------------
# Field parsing (one builder for journal rows and proposal files)
# --------------------------------------------------------------------------------------


@dataclass
class _RawEntry:
    """Stripped text of one entry; list fields are already split."""

    position: int
    text: dict[str, str]
    targets: list[str]
    evidence: list[str]
    entered: dict[str, str] = field(default_factory=dict)
    issues: list[AdjustmentIssue] = field(default_factory=list)

    def issue(self, code: str, field_name: str | None) -> None:
        # Only a well-formed ID is echoed; any other text in that cell is never repeated.
        candidate = self.text.get("adjustment_id", "")
        identifier = candidate if is_valid_adjustment_id(candidate) else None
        self.issues.append(AdjustmentIssue(code, _ERROR, identifier, self.position, field_name))


def _money(raw: _RawEntry, name: str) -> Decimal | None:
    text = raw.text.get(name, "")
    try:
        value = parse_money(text)
    except ValueError:
        raw.issue("invalid_money", name)
        return None
    if value is not None and abs(value) >= MAX_AMOUNT:
        raw.issue("money_out_of_range", name)
        return None
    entered = raw.entered.get(name)
    if value is not None and entered is not None and not entered_matches(entered, value):
        raw.issue("display_precision_mismatch", name)
        return None
    return value


def _date(raw: _RawEntry, name: str) -> date | None:
    try:
        return parse_source_date(raw.text.get(name, ""))
    except ValueError:
        raw.issue("invalid_date", name)
        return None


def _timestamp(raw: _RawEntry, name: str) -> datetime | None:
    text = raw.text.get(name, "")
    parsed: datetime | None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raw.issue("invalid_timestamp", name)
        return None
    return parsed.astimezone(UTC)


def _canonical_value(raw: _RawEntry, name: str, kind: str) -> str | None:
    """A prior/replacement value in its kind's canonical text; blank -> ``None``."""
    if not raw.text.get(name):
        return None
    if kind == "amount_correction":
        amount = _money(raw, name)
        return None if amount is None else money_str(amount)
    if kind == "date_override":
        parsed = _date(raw, name)
        return None if parsed is None else parsed.isoformat()
    return raw.text[name]


def _build(raw: _RawEntry, *, recorded: bool) -> Adjustment | None:
    """Parse one entry; every finding goes to ``raw.issues``. ``None`` when any error."""
    text = raw.text
    for name, value in text.items():
        if len(value) > MAX_FIELD_TEXT:
            raw.issue("field_too_long", name)
    for item in (*raw.targets, *raw.evidence):
        if len(item) > MAX_FIELD_TEXT:
            raw.issue("field_too_long", "targets" if item in raw.targets else "evidence")

    adjustment_id = text.get("adjustment_id", "")
    if not adjustment_id:
        raw.issue("missing_field", "adjustment_id")
    elif not is_valid_adjustment_id(adjustment_id):
        raw.issue("invalid_adjustment_id", "adjustment_id")
    kind = text.get("kind", "")
    if not kind:
        raw.issue("missing_field", "kind")
    elif kind not in _KIND_RULES:
        raw.issue("unknown_kind", "kind")
    effective = _date(raw, "effective_date")
    if effective is None and not text.get("effective_date"):
        raw.issue("missing_field", "effective_date")

    targets: list[tuple[str, str]] = []
    for item in raw.targets:
        key, _, revision = item.rpartition(_TARGET_SEPARATOR)
        # A missing separator leaves an empty key, which is never a record key.
        if not is_valid_record_key(key) or HEX_DIGEST_PATTERN.match(revision) is None:
            raw.issue("invalid_target", "targets")
        else:
            targets.append((key, revision))
    if not text.get("reason"):
        raw.issue("missing_field", "reason")
    if not raw.evidence:
        raw.issue("missing_field", "evidence")
    elif not all(raw.evidence):
        raw.issue("invalid_evidence", "evidence")
    supersedes = text.get("supersedes") or None
    if supersedes is not None and not is_valid_adjustment_id(supersedes):
        raw.issue("invalid_adjustment_id", "supersedes")
    recorded_at: datetime | None = None
    if recorded:
        if not text.get("recorded_at"):
            raw.issue("missing_field", "recorded_at")
        else:
            recorded_at = _timestamp(raw, "recorded_at")

    prior = _canonical_value(raw, "prior_value", kind)
    replacement = _canonical_value(raw, "replacement_value", kind)
    signed = _money(raw, "signed_amount")
    if raw.issues or effective is None:
        return None
    adjustment = Adjustment(
        adjustment_id=adjustment_id,
        kind=kind,
        effective_date=effective,
        reason=text["reason"],
        evidence=tuple(raw.evidence),
        targets=tuple(targets),
        prior_value=prior,
        replacement_value=replacement,
        signed_amount=signed,
        category=text.get("category") or None,
        supersedes=supersedes,
        recorded_at=recorded_at,
    )
    _check_shape(adjustment, raw)
    return None if raw.issues else adjustment


def _check_shape(adjustment: Adjustment, raw: _RawEntry) -> None:
    """Per-kind required/forbidden fields, target count and no-op / plug guards."""
    required, forbidden, target_count = _KIND_RULES[adjustment.kind]
    for name in sorted(required):
        if getattr(adjustment, name) is None:
            raw.issue("missing_field", name)
    for name in sorted(forbidden):
        if getattr(adjustment, name) is not None:
            raw.issue("unexpected_field", name)
    if len(adjustment.targets) != target_count:
        raw.issue("target_count_invalid", "targets")
    if (
        adjustment.prior_value is not None
        and adjustment.prior_value == adjustment.replacement_value
    ):
        raw.issue("no_op_correction", "replacement_value")
    destination = {
        "category_override": ("replacement_value", adjustment.replacement_value),
        "additive": ("category", adjustment.category),
    }.get(adjustment.kind)
    if destination is not None:
        name, text = destination
        if text is not None and (
            len(text) > MAX_CATEGORY_TEXT
            or not text.isprintable()
            or backup.is_formula_like_text(text)
        ):
            raw.issue("invalid_category", name)
    if adjustment.kind == "additive":
        if adjustment.signed_amount == _ZERO:
            raw.issue("no_op_correction", "signed_amount")
        # An additive entry needs evidence of its own: a reconciliation finding is not
        # evidence, so an entry citing only findings would be an unexplained balancing plug.
        if all(item.startswith(DISCREPANCY_ID_PREFIX) for item in adjustment.evidence):
            raw.issue("additive_evidence_not_independent", "evidence")


def _row_entry(cells: Sequence[str], position: int, entered: Mapping[str, str]) -> _RawEntry:
    """One journal row's cells (in :data:`JOURNAL_COLUMNS` order) as a raw entry."""
    text = {name: cell.strip() for name, cell in zip(JOURNAL_COLUMNS, cells, strict=True)}
    return _RawEntry(
        position=position,
        text={k: v for k, v in text.items() if k not in {"targets", "evidence"}},
        targets=_split(text["targets"]),
        evidence=_split(text["evidence"]),
        entered=dict(entered),
    )


def _split(cell: str) -> list[str]:
    text = cell.strip()
    return [] if not text else [item.strip() for item in text.split(_LIST_SEPARATOR)]


# --------------------------------------------------------------------------------------
# Journal reader
# --------------------------------------------------------------------------------------


def _cell(values: Sequence[Sequence[str]], row: int, column: int) -> str:
    if row < len(values) and column < len(values[row]):
        return values[row][column]
    return ""


def _last_occupied_row(capture: SourceCapture) -> int:
    # Any non-empty value counts, whitespace included: a new row never lands on a cell
    # that holds something, visible or not.
    rows = [index for index, row in enumerate(capture.values) if any(c != "" for c in row)]
    rows.extend(cell.row for cell in capture.formulas)
    rows.extend(cell.row for cell in capture.entered_numbers)
    return max(rows, default=-1) + 1


def _absent_journal(capture: SourceCapture) -> AdjustmentJournal:
    return AdjustmentJournal(
        tab_title=capture.tab_title,
        assumptions_sha256=capture.sha256,
        marker_row=None,
        entries=(),
        issues=(),
        last_occupied_row=_last_occupied_row(capture),
        sha256=content_hash({"marker": JOURNAL_MARKER, "present": False}),
    )


def _is_marker_like(raw: str) -> bool:
    return raw.strip().casefold().startswith(_MARKER_PREFIX)


def _locate_marker(values: Sequence[Sequence[str]]) -> int | None:
    """Zero-based row of the unique, well-formed marker in column A; ``None`` when absent.

    Only column A can hold the marker. Inside the journal, every other column is entry data
    (a reason or evidence text may legitimately start with the marker text); column A holds
    adjustment IDs, which can never look like a marker. Above the journal, or anywhere when
    there is none, every cell is operator content: marker-like text there means a moved or
    damaged section and fails closed.
    """
    column_a = [
        (index, row[0].strip())
        for index, row in enumerate(values)
        if row and _is_marker_like(row[0])
    ]
    similar = [(index + 1, 1) for index, text in column_a if text != JOURNAL_MARKER]
    if similar:
        raise JournalLayoutError(
            "journal_marker_invalid",
            f"{len(similar)} cell(s) resemble the journal marker at (row, column) {similar[:10]}",
        )
    if len(column_a) > 1:
        raise JournalLayoutError(
            "journal_marker_duplicate", f"{len(column_a)} journal markers; exactly one is allowed"
        )
    marker = column_a[0][0] if column_a else None
    limit = len(values) if marker is None else marker
    misplaced = [
        (index + 1, column + 1)
        for index in range(limit)
        for column, raw in enumerate(values[index])
        if column > 0 and _is_marker_like(raw)
    ]
    if misplaced:
        raise JournalLayoutError(
            "journal_marker_misplaced",
            f"{len(misplaced)} marker-like cell(s) outside column A at (row, column) "
            f"{misplaced[:10]}",
        )
    return marker


def read_journal(capture: SourceCapture) -> AdjustmentJournal:
    """Parse the adjustments journal from one Assumptions capture (reads nothing, writes nothing).

    A missing marker means no section yet: an empty journal (source-only runs never create
    it). The region from the marker down must hold only the marker, the exact header and
    journal rows within the journal columns, with no formula; anything else raises
    :class:`JournalLayoutError`. Rows that fail validation become blocking ``issues``.
    """
    if capture.kind != ASSUMPTIONS_ALIAS:
        raise AdjustmentError("not_assumptions_capture", "the journal lives only on Assumptions")
    values = capture.values
    marker = _locate_marker(values)
    if marker is None:
        return _absent_journal(capture)
    header = tuple(_cell(values, marker + 1, column) for column in range(_WIDTH))
    if header != JOURNAL_COLUMNS:
        raise JournalLayoutError(
            "journal_header_mismatch", f"row {marker + 2} is not the journal column header"
        )
    foreign = [
        (row_index + 1, column + 1)
        for row_index in range(marker, len(values))
        for column, raw in enumerate(values[row_index])
        if raw.strip() and (column >= _WIDTH or (row_index == marker and column > 0))
    ]
    if foreign:
        raise JournalLayoutError(
            "journal_foreign_content",
            f"{len(foreign)} cell(s) outside the journal columns at (row, column) {foreign[:10]}",
        )
    formulas = [(cell.row + 1, cell.column + 1) for cell in capture.formulas if cell.row >= marker]
    if formulas:
        raise JournalLayoutError(
            "journal_formula_cell",
            f"{len(formulas)} formula cell(s) inside the journal at (row, column) {formulas[:10]}",
        )
    rows = [
        row_index
        for row_index in range(marker + 2, len(values))
        if any(_cell(values, row_index, column).strip() for column in range(_WIDTH))
    ]
    if len(rows) > MAX_JOURNAL_ENTRIES:
        raise JournalLayoutError(
            "journal_too_large", f"{len(rows)} journal rows exceed {MAX_JOURNAL_ENTRIES}"
        )
    entered = {(cell.row, cell.column): cell.value for cell in capture.entered_numbers}
    entries: list[JournalEntry] = []
    issues: list[AdjustmentIssue] = []
    for row_index in rows:
        raw = _row_entry(
            [_cell(values, row_index, column) for column in range(_WIDTH)],
            row_index + 1,
            {
                name: entered[(row_index, column)]
                for column, name in enumerate(JOURNAL_COLUMNS)
                if (row_index, column) in entered
            },
        )
        adjustment = _build(raw, recorded=True)
        issues.extend(raw.issues)
        if adjustment is not None:
            entries.append(JournalEntry(adjustment, row_index + 1))
    region = [
        [_cell(values, row_index, column) for column in range(_WIDTH)]
        for row_index in range(marker, len(values))
    ]
    return AdjustmentJournal(
        tab_title=capture.tab_title,
        assumptions_sha256=capture.sha256,
        marker_row=marker + 1,
        entries=tuple(entries),
        issues=tuple(issues),
        last_occupied_row=_last_occupied_row(capture),
        sha256=content_hash({"marker": JOURNAL_MARKER, "present": True, "rows": region}),
    )


# --------------------------------------------------------------------------------------
# Proposals file
# --------------------------------------------------------------------------------------

_PROPOSAL_FIELDS = frozenset(JOURNAL_COLUMNS) - {"recorded_at"}
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")


def _proposal(item: Mapping[str, Any], position: int) -> _RawEntry:
    raw = _RawEntry(position=position, text={}, targets=[], evidence=[])
    for name in sorted(set(item) - _PROPOSAL_FIELDS, key=str):
        # A key is named only when it looks like a field name; other text is never echoed.
        shown = name if isinstance(name, str) and _FIELD_NAME.fullmatch(name) else None
        raw.issue("unexpected_field", shown)
    for name in sorted(_PROPOSAL_FIELDS - {"targets", "evidence"}):
        value = item.get(name)
        if value is None:
            raw.text[name] = ""
        elif isinstance(value, str):
            raw.text[name] = value.strip()
        else:
            raw.text[name] = ""
            raw.issue("invalid_type", name)
    targets = item.get("targets") or []
    if not isinstance(targets, list):
        raw.issue("invalid_type", "targets")
        targets = []
    for target in targets:
        if (
            isinstance(target, Mapping)
            and set(target) == {"record_key", "revision_hash"}
            and all(isinstance(target[k], str) for k in target)
        ):
            raw.targets.append(
                f"{target['record_key']}{_TARGET_SEPARATOR}{target['revision_hash']}"
            )
        else:
            raw.issue("invalid_target", "targets")
    evidence = item.get("evidence")
    if evidence is not None and (
        not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence)
    ):
        raw.issue("invalid_type", "evidence")
        evidence = None
    for ref in evidence or []:
        if _LIST_SEPARATOR in ref:
            raw.issue("invalid_evidence", "evidence")
        raw.evidence.append(ref.strip())
    return raw


def _check_batch(proposals: Sequence[Adjustment], issues: list[AdjustmentIssue]) -> None:
    if not proposals:
        issues.append(AdjustmentIssue("no_proposals", _ERROR))
    if len(proposals) > MAX_PROPOSALS:
        issues.append(AdjustmentIssue("too_many_proposals", _ERROR))
    seen: set[str] = set()
    for position, proposal in enumerate(proposals, 1):
        if proposal.adjustment_id in seen:
            issues.append(
                AdjustmentIssue(
                    "duplicate_proposal_id", _ERROR, proposal.adjustment_id, position, None
                )
            )
        seen.add(proposal.adjustment_id)
        if proposal.recorded_at is not None:
            issues.append(
                AdjustmentIssue(
                    "unexpected_field", _ERROR, proposal.adjustment_id, position, "recorded_at"
                )
            )


def parse_proposals(payload: Any) -> tuple[Adjustment, ...]:
    """Validate a decoded adjustments file: ``{"schema_version": 1, "adjustments": [...]}``.

    Each adjustment has the journal fields except ``recorded_at`` (the writer assigns it):
    money and dates are JSON strings (never numbers), ``targets`` is a list of
    ``{"record_key", "revision_hash"}`` objects and ``evidence`` a list of strings. Every
    finding is collected; any finding raises :class:`ProposalError`.
    """
    issues: list[AdjustmentIssue] = []
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "adjustments"}:
        raise ProposalError([AdjustmentIssue("proposals_shape", _ERROR)])
    version = payload["schema_version"]
    if isinstance(version, bool) or version != PROPOSALS_SCHEMA_VERSION:
        raise ProposalError([AdjustmentIssue("unsupported_schema_version", _ERROR)])
    items = payload["adjustments"]
    if not isinstance(items, list):
        raise ProposalError([AdjustmentIssue("proposals_shape", _ERROR, field="adjustments")])
    proposals: list[Adjustment] = []
    for position, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            issues.append(AdjustmentIssue("invalid_type", _ERROR, row_number=position))
            continue
        raw = _proposal(item, position)
        adjustment = _build(raw, recorded=False)
        issues.extend(raw.issues)
        if adjustment is not None:
            proposals.append(adjustment)
    if not issues:
        _check_batch(proposals, issues)
    if issues:
        raise ProposalError(issues)
    return tuple(proposals)


def load_proposals(path: Path) -> tuple[Adjustment, ...]:
    """Read and validate a private adjustments JSON file (reads only, size-capped)."""
    unreadable = AdjustmentError("proposals_unreadable", "the adjustments file cannot be read")
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(MAX_PROPOSALS_FILE_BYTES + 1)
    except OSError:
        raise unreadable from None
    if len(data) > MAX_PROPOSALS_FILE_BYTES:
        raise AdjustmentError(
            "proposals_too_large", f"the adjustments file exceeds {MAX_PROPOSALS_FILE_BYTES} bytes"
        )
    try:
        # A leading UTF-8 byte-order mark (Windows PowerShell's utf8 encoding) is accepted.
        payload = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise unreadable from None
    except ValueError:
        raise AdjustmentError(
            "proposals_invalid_json", "the adjustments file is not JSON"
        ) from None
    except RecursionError:
        raise AdjustmentError(
            "proposals_too_nested", "the adjustments file nests too deeply to read"
        ) from None
    return parse_proposals(payload)


# --------------------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------------------


def _target_issue(adjustment: Adjustment, by_key: Mapping[str, Transaction]) -> str | None:
    """Exact precondition of a targeted entry against the current source revision."""
    key, revision = adjustment.targets[0]
    txn = by_key.get(key)
    if txn is None:
        return "target_missing"
    if txn.source_kind != "bank":
        return "target_not_bank"
    if txn.revision_hash != revision:
        return "target_revision_mismatch"
    if adjustment.kind == "category_override":
        matches = any(item.category == adjustment.prior_value for item in txn.allocations)
    elif adjustment.kind == "date_override":
        matches = txn.posting_date is not None and (
            txn.posting_date.isoformat() == adjustment.prior_value
        )
    else:
        amounts = [item.amount for item in txn.allocations if item.category == adjustment.category]
        matches = bool(amounts) and money_str(sum(amounts, _ZERO)) == adjustment.prior_value
    return None if matches else "prior_value_mismatch"


def _slot(adjustment: Adjustment) -> tuple[str, ...]:
    """The SOURCE value a replacement entry occupies; two active entries may not share one.

    A category override occupies one source category of its row: two overrides of the same
    source allocation compete (never chained), while overrides of different source
    categories are independent.
    """
    discriminator = {
        "category_override": adjustment.prior_value,
        "amount_correction": adjustment.category,
    }.get(adjustment.kind)
    return (adjustment.targets[0][0], adjustment.kind, discriminator or "")


def _conflict(code: str, entry: JournalEntry, field_name: str | None = None) -> AdjustmentIssue:
    return AdjustmentIssue(
        code, _ERROR, entry.adjustment.adjustment_id, entry.row_number, field_name
    )


def _structure(
    journal: AdjustmentJournal,
) -> tuple[list[list[JournalEntry]], list[AdjustmentIssue], list[AdjustmentIssue]]:
    """Supersession chains (root first), structural conflicts and duplicate-row warnings.

    Chains are only meaningful when there is no conflict; :func:`project` applies nothing
    otherwise.
    """
    conflicts: list[AdjustmentIssue] = []
    warnings: list[AdjustmentIssue] = []
    first: dict[str, JournalEntry] = {}
    unique: list[JournalEntry] = []
    for entry in journal.entries:
        identifier = entry.adjustment.adjustment_id
        previous = first.get(identifier)
        if previous is None:
            first[identifier] = entry
            unique.append(entry)
        elif previous.adjustment.fingerprint() == entry.adjustment.fingerprint():
            warnings.append(
                AdjustmentIssue("duplicate_adjustment_row", _WARNING, identifier, entry.row_number)
            )
        else:
            conflicts.append(_conflict("duplicate_adjustment_conflict", entry))
    successors: dict[str, list[JournalEntry]] = defaultdict(list)
    for entry in unique:
        target = entry.adjustment.supersedes
        if target is None:
            continue
        if target not in first:
            conflicts.append(_conflict("supersedes_unknown", entry, "supersedes"))
        elif first[target].row_number >= entry.row_number:
            # Only an earlier row may be superseded; this also rules out every cycle.
            conflicts.append(_conflict("supersedes_not_earlier", entry, "supersedes"))
        else:
            successors[target].append(entry)
    for entries in successors.values():
        if len(entries) > 1:
            conflicts.extend(_conflict("competing_supersession", e, "supersedes") for e in entries)
    chains: list[list[JournalEntry]] = []
    for entry in unique:
        if entry.adjustment.supersedes is not None:
            continue
        chain = [entry]
        while chain[-1].adjustment.adjustment_id in successors:
            chain.append(successors[chain[-1].adjustment.adjustment_id][0])
        chains.append(chain)
    return chains, conflicts, warnings


def _base_allocations(reconciliation: Reconciliation) -> list[AdjustedAllocation]:
    base: list[AdjustedAllocation] = []
    for txn in reconciliation.transactions:
        if txn.source_kind != "bank":
            continue
        assert txn.posting_date is not None  # reconciliation validated every bank row
        for item in txn.allocations:
            base.append(
                AdjustedAllocation(
                    origin=_SOURCE,
                    category=item.category,
                    amount=item.amount,
                    posting_date=txn.posting_date,
                    counted=item.category != INTERNAL_TRANSFER_CATEGORY,
                    record_key=txn.record_key,
                    revision_hash=txn.revision_hash,
                    ref=txn.refs[0],
                    source_category=item.category,
                    source_amount=item.amount,
                    source_date=txn.posting_date,
                )
            )
    return base


def _cells(allocations: Iterable[AdjustedAllocation]) -> tuple[MonthlyCategoryCell, ...]:
    return monthly_cells_from(
        (item.posting_date, item.category, item.amount, () if item.ref is None else (item.ref,))
        for item in allocations
        if item.counted
    )


class _Deltas:
    def __init__(self) -> None:
        self.amounts: dict[tuple[str, str, date, str], Decimal] = defaultdict(lambda: _ZERO)

    def move(
        self,
        adjustment: Adjustment,
        before: Sequence[AdjustedAllocation],
        after: Sequence[AdjustedAllocation],
    ) -> None:
        for sign, items in ((-1, before), (1, after)):
            for item in items:
                if item.counted:
                    key = (
                        adjustment.adjustment_id,
                        adjustment.kind,
                        item.posting_date.replace(day=1),
                        item.category,
                    )
                    self.amounts[key] += sign * item.amount

    def records(self) -> tuple[AdjustmentDelta, ...]:
        return tuple(
            AdjustmentDelta(identifier, kind, category, month, amount)
            for (identifier, kind, month, category), amount in sorted(self.amounts.items())
            if amount != _ZERO
        )


def _apply(
    allocations: list[AdjustedAllocation], adjustment: Adjustment, deltas: _Deltas
) -> list[AdjustedAllocation]:
    identifier = adjustment.adjustment_id
    if adjustment.kind == "additive":
        assert adjustment.signed_amount is not None and adjustment.category is not None
        added = AdjustedAllocation(
            origin=_ADDITIVE,
            category=adjustment.category,
            amount=adjustment.signed_amount,
            posting_date=adjustment.effective_date,
            counted=adjustment.category != INTERNAL_TRANSFER_CATEGORY,
            adjustment_ids=(identifier,),
        )
        deltas.move(adjustment, [], [added])
        return [*allocations, added]
    key = adjustment.targets[0][0]
    # Category-scoped kinds select by SOURCE category (the precondition's basis), never by
    # an already-adjusted category, so journal row order cannot change the result.
    if adjustment.kind in {"amount_correction", "category_override"}:
        scope = (
            adjustment.category
            if adjustment.kind == "amount_correction"
            else adjustment.prior_value
        )
        hit = [a for a in allocations if a.record_key == key and a.source_category == scope]
    else:
        hit = [a for a in allocations if a.record_key == key]
    replacement = adjustment.replacement_value
    assert replacement is not None and hit  # validated by _target_issue
    if adjustment.kind == "amount_correction":
        # Every allocation of the category in the row becomes one corrected allocation.
        changed = [
            replace(
                hit[0],
                amount=Decimal(replacement),
                source_amount=sum((a.source_amount for a in hit), _ZERO),
                adjustment_ids=(*hit[0].adjustment_ids, identifier),
            )
        ]
    elif adjustment.kind == "category_override":
        changed = [
            replace(
                a,
                category=replacement,
                counted=replacement != INTERNAL_TRANSFER_CATEGORY,
                adjustment_ids=(*a.adjustment_ids, identifier),
            )
            for a in hit
        ]
    else:
        moved_to = date.fromisoformat(replacement)
        changed = [
            replace(a, posting_date=moved_to, adjustment_ids=(*a.adjustment_ids, identifier))
            for a in hit
        ]
    deltas.move(adjustment, hit, changed)
    position = allocations.index(hit[0])
    remaining = [a for a in allocations if not any(a is h for h in hit)]
    return [*remaining[:position], *changed, *remaining[position:]]


def project(
    reconciliation: Reconciliation, journal: AdjustmentJournal, as_of: date
) -> AdjustedLedger:
    """Apply the journal entries in effect on ``as_of`` to a copy of the source view (pure).

    Each supersession chain contributes its LATEST member effective on or before ``as_of``
    (a reversal contributes nothing); later members are ``pending`` and earlier ones
    ``superseded``. Replacement kinds apply in a fixed order (amount, category, date) with
    preconditions checked against the source revision, then additive entries. Unreadable
    rows or a broken chain apply nothing; a target conflict or competing replacement skips
    only the entries involved. Every conflict blocks adjusted publication.
    """
    base = _base_allocations(reconciliation)
    if _cells(base) != reconciliation.monthly_cells:
        raise AdjustmentError(
            "source_view_mismatch",
            "the reconciliation's monthly cells do not follow from its bank allocations",
        )
    chains, conflicts, warnings = _structure(journal)
    conflicts = [*journal.issues, *conflicts]
    applied: list[JournalEntry] = []
    pending: list[str] = []
    superseded: list[str] = []
    if not conflicts:
        for chain in chains:
            effective = [i for i, e in enumerate(chain) if e.adjustment.effective_date <= as_of]
            cut = effective[-1] if effective else -1
            superseded.extend(e.adjustment.adjustment_id for e in chain[: max(cut, 0)])
            pending.extend(e.adjustment.adjustment_id for e in chain[cut + 1 :])
            if cut >= 0:
                applied.append(chain[cut])

    by_key = {txn.record_key: txn for txn in reconciliation.transactions}
    usable: list[JournalEntry] = []
    for entry in applied:
        adjustment = entry.adjustment
        if adjustment.targets:
            code = _target_issue(adjustment, by_key)
            if code is not None:
                conflicts.append(_conflict(code, entry, "targets"))
                continue
        usable.append(entry)
    slots: dict[tuple[str, ...], list[JournalEntry]] = defaultdict(list)
    for entry in usable:
        if entry.adjustment.targets:
            slots[_slot(entry.adjustment)].append(entry)
    competing = {id(e) for group in slots.values() if len(group) > 1 for e in group}
    conflicts.extend(_conflict("competing_replacement", e) for e in usable if id(e) in competing)
    usable = [e for e in usable if id(e) not in competing]

    allocations = list(base)
    deltas = _Deltas()
    for kind in (*_APPLY_ORDER, "additive"):
        for entry in sorted(usable, key=lambda e: e.row_number):
            if entry.adjustment.kind == kind:
                allocations = _apply(allocations, entry.adjustment, deltas)
    cells = _cells(allocations)
    in_effect = sorted(usable, key=lambda e: e.row_number)
    return AdjustedLedger(
        source=reconciliation,
        as_of=as_of,
        journal_sha256=journal.sha256,
        applied=tuple(e.adjustment.adjustment_id for e in in_effect),
        pending=tuple(sorted(pending)),
        superseded=tuple(sorted(superseded)),
        allocations=tuple(allocations),
        monthly_cells=cells,
        pnl_totals=month_totals_from(cells),
        deltas=deltas.records(),
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
    )


def require_publishable(ledger: AdjustedLedger) -> None:
    """Raise :class:`AdjustmentConflictError` when any conflict blocks adjusted publication."""
    if ledger.conflicts:
        raise AdjustmentConflictError("adjusted_publication_blocked", ledger.conflicts)


# --------------------------------------------------------------------------------------
# Local writer lock
# --------------------------------------------------------------------------------------


@dataclass
class RunLock:
    """The exclusive local writer lock in the private output root (one writer at a time).

    Released in ``finally`` (or by ``with``). Release removes the file only while it still
    holds this lock's token; an abandoned lock is inspected (recorded PID) and removed by the
    operator, never by another run.
    """

    path: Path
    token: str
    held: bool = True

    def release(self) -> None:
        self.held = False
        try:
            recorded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(recorded, dict) and recorded.get("token") == self.token:
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> RunLock:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def acquire_run_lock(config: Config, *, clock: Clock | None = None) -> RunLock:
    """Create the lock file exclusively under ``main_reports.output_path``; else ``run_busy``."""
    root = _main_reports(config).output_path
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_FILENAME
    token = uuid.uuid4().hex
    stamp = (clock or _utc_now)()
    contents = {"pid": os.getpid(), "token": token, "created_at": stamp.isoformat()}
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(contents, sort_keys=True))
    except FileExistsError:
        raise RunBusyError(
            "run_busy",
            "another Main Report Set writer holds the local lock; inspect the process recorded "
            "in the lock file before removing only that file",
        ) from None
    return RunLock(path=path, token=token)


# --------------------------------------------------------------------------------------
# Journal writer
# --------------------------------------------------------------------------------------


def connect_journal_client(
    config: Config,
    *,
    gspread_client: gspread.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SheetsClient:
    """Our own workbook with write scope (the only writable client in the Main Report Set).

    The CFO workbook stays on its read-only client; :func:`record` refuses any client not
    bound to ``[sheets] spreadsheet_id``. Tests inject ``gspread_client``.
    """
    if gspread_client is None:
        gspread_client = gspread.service_account(
            filename=str(config.google.service_account_path), scopes=[WRITE_SCOPE]
        )
        gspread_client.set_timeout(HTTP_TIMEOUT_SECONDS)
    return SheetsClient(config, gspread_client=gspread_client, sleep=sleep)


@dataclass(frozen=True)
class _WritePlan:
    ranges: dict[str, list[list[str]]]
    # Zero-based (row, column) -> exact text every planned cell holds after the write.
    values: Mapping[tuple[int, int], str]
    new_ids: tuple[str, ...]
    last_row: int


@dataclass(frozen=True)
class RecordResult:
    """Outcome of :func:`record`.

    ``assumptions`` is the verified post-write capture (or the fresh pre-write capture when
    every proposal was already recorded) and ``journal`` its parsed journal: project from it
    for the immediate effect. ``snapshot_path`` is the pre-write snapshot (``None`` when
    nothing was written); a run manifest references it as the journal-write evidence.
    """

    written: tuple[str, ...]
    already_recorded: tuple[str, ...]
    snapshot_path: Path | None
    assumptions: SourceCapture
    journal: AdjustmentJournal
    attempts: int


def _journal_row(adjustment: Adjustment) -> list[str]:
    entry = adjustment.to_dict()
    entry["targets"] = _LIST_SEPARATOR.join(
        f"{target['record_key']}{_TARGET_SEPARATOR}{target['revision_hash']}"
        for target in entry["targets"]
    )
    entry["evidence"] = f"{_LIST_SEPARATOR} ".join(entry["evidence"])
    return ["" if entry[name] is None else str(entry[name]) for name in JOURNAL_COLUMNS]


def _round_trip_issues(stamped: Adjustment, position: int) -> list[AdjustmentIssue]:
    """Validate a proposal exactly as the journal reader will read its row back.

    The row is encoded as it will be written and parsed by the reader's own row parser and
    builder; any finding, or any field that would read back differently, refuses the
    proposal. Whatever :func:`record` writes therefore always reads back as itself.
    """
    try:
        cells = _journal_row(stamped)
    except (ValueError, ArithmeticError):  # not exact cents, or beyond decimal precision
        raw = _RawEntry(
            position=position,
            text={"adjustment_id": stamped.adjustment_id},
            targets=[],
            evidence=[],
        )
        raw.issue("invalid_money", "signed_amount")
        return raw.issues
    raw = _row_entry(cells, position, {})
    reread = _build(raw, recorded=True)
    if reread is None:
        return raw.issues
    written, read = stamped.to_dict(), reread.to_dict()
    changed = sorted(name for name in written if written[name] != read[name])
    if not changed:
        return []
    raw.issue("round_trip_mismatch", changed[0])
    return raw.issues


def _row_range(row: int, width: int) -> str:
    return f"{rowcol_to_a1(row, 1)}:{rowcol_to_a1(row, width)}"


def _plan(
    proposals: Sequence[Adjustment],
    journal: AdjustmentJournal,
    reconciliation: Reconciliation,
    as_of: date,
    recorded_at: datetime,
) -> tuple[_WritePlan | None, tuple[str, ...]]:
    batch: list[AdjustmentIssue] = []
    _check_batch(proposals, batch)
    stamped = [replace(proposal, recorded_at=recorded_at) for proposal in proposals]
    if not batch:
        for position, proposal in enumerate(stamped, 1):
            batch.extend(_round_trip_issues(proposal, position))
    if batch:
        raise ProposalError(batch)
    if journal.issues:
        raise AdjustmentConflictError("journal_invalid", journal.issues)
    existing = {entry.adjustment.adjustment_id: entry.adjustment for entry in journal.entries}
    by_key = {txn.record_key: txn for txn in reconciliation.transactions}
    issues: list[AdjustmentIssue] = []
    new: list[Adjustment] = []
    already: list[str] = []
    for position, proposal in enumerate(stamped, 1):
        identifier = proposal.adjustment_id
        recorded = existing.get(identifier)
        if recorded is not None:
            if recorded.fingerprint() == proposal.fingerprint():
                already.append(identifier)
            else:
                issues.append(
                    AdjustmentIssue("adjustment_id_conflict", _ERROR, identifier, position)
                )
            continue
        if proposal.targets:
            code = _target_issue(proposal, by_key)
            if code is not None:
                issues.append(AdjustmentIssue(code, _ERROR, identifier, position, "targets"))
        new.append(proposal)
    if issues:
        raise AdjustmentConflictError("proposal_conflict", issues)
    if not new:
        return None, tuple(already)
    if len(journal.entries) + len(new) > MAX_JOURNAL_ENTRIES:
        raise AdjustmentError("journal_full", f"the journal holds at most {MAX_JOURNAL_ENTRIES}")

    ranges: dict[str, list[list[str]]] = {}
    values: dict[tuple[int, int], str] = {}

    def put(row: int, cells: list[str]) -> None:
        a1 = rowcol_to_a1(row, 1) if len(cells) == 1 else _row_range(row, len(cells))
        ranges[a1] = [cells]
        values.update(((row - 1, column), text) for column, text in enumerate(cells))

    if journal.marker_row is None:
        marker_row = journal.last_occupied_row + JOURNAL_GAP_ROWS + 1
        put(marker_row, [JOURNAL_MARKER])
        put(marker_row + 1, list(JOURNAL_COLUMNS))
        first_row = marker_row + 2
    else:
        marker_row = journal.marker_row
        first_row = journal.last_occupied_row + 1
    added: list[JournalEntry] = []
    for offset, proposal in enumerate(new):
        put(first_row + offset, _journal_row(proposal))
        added.append(JournalEntry(proposal, first_row + offset))
    expected = (*journal.entries, *added)

    # The journal as it will read after the write must project without any conflict.
    combined = replace(journal, marker_row=marker_row, entries=expected)
    ledger = project(reconciliation, combined, as_of)
    if ledger.conflicts:
        raise AdjustmentConflictError("proposal_conflict", ledger.conflicts)
    plan = _WritePlan(
        ranges=ranges,
        values=values,
        new_ids=tuple(p.adjustment_id for p in new),
        last_row=first_row + len(new) - 1,
    )
    return plan, tuple(already)


def _entered_cells(capture: SourceCapture) -> set[tuple[int, int]]:
    return {(f.row, f.column) for f in capture.formulas} | {
        (n.row, n.column) for n in capture.entered_numbers
    }


def _occupied_plan_cells(before: SourceCapture, plan: _WritePlan) -> int:
    """Planned cells that already hold a value, formula or typed number (must be zero)."""
    entered = _entered_cells(before)
    return sum(1 for cell in plan.values if _cell(before.values, *cell) != "" or cell in entered)


def _verify(before: SourceCapture, after: SourceCapture, plan: _WritePlan) -> str | None:
    """``None`` when ``after`` is exactly ``before`` plus the planned journal cells."""
    if after.tab_id != before.tab_id:
        return "concurrent_edit_detected"
    # A formula's displayed RESULT may legitimately change when rows are appended (COUNTA(A:A),
    # NOW()); formula cells are compared by their formula text below instead.
    formula_cells = {(f.row, f.column) for f in (*before.formulas, *after.formulas)}
    for row in range(max(len(before.values), len(after.values))):
        width = max(
            len(before.values[row]) if row < len(before.values) else 0,
            len(after.values[row]) if row < len(after.values) else 0,
        )
        for column in range(width):
            if (row, column) in plan.values or (row, column) in formula_cells:
                continue
            if _cell(before.values, row, column) != _cell(after.values, row, column):
                return "concurrent_edit_detected"
    outside_formulas = {f for f in after.formulas if (f.row, f.column) not in plan.values}
    outside_numbers = {n for n in after.entered_numbers if (n.row, n.column) not in plan.values}
    if outside_formulas != set(before.formulas) or outside_numbers != set(before.entered_numbers):
        return "concurrent_edit_detected"
    # Every planned cell holds exactly the written text, as plain text.
    entered = _entered_cells(after)
    for cell, text in plan.values.items():
        if _cell(after.values, *cell) != text or cell in entered:
            return "journal_readback_mismatch"
    # Cells outside the plan are unchanged and every planned cell holds exactly its text, so
    # the journal now reads as planned (the caller re-parses it for the result).
    return None


def _require_own_workbook(config: Config, main_reports: MainReports, client: SheetsClient) -> None:
    if (
        client.spreadsheet_id != config.sheets.spreadsheet_id
        or client.spreadsheet_id == main_reports.source_spreadsheet_id
    ):
        raise AdjustmentError(
            "journal_target_not_own_workbook",
            "the adjustments journal is written only to our own workbook, never the CFO source",
        )


def _require_lock(lock: RunLock, root: Path) -> None:
    """The held lock's file must exist at the configured root and still carry its token."""
    recorded: Any = None
    if lock.held and lock.path == root / LOCK_FILENAME:
        try:
            recorded = json.loads(lock.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recorded = None
    if not isinstance(recorded, dict) or recorded.get("token") != lock.token:
        raise AdjustmentError(
            "lock_not_held", "record requires the held Main Report Set lock (token on disk)"
        )


def _cause(error: BaseException) -> str:
    """A value-free description of a transport failure: type plus HTTP status."""
    status = http_status(error)
    return type(error).__name__ if status is None else f"{type(error).__name__} {status}"


def _rejected(error: BaseException) -> bool:
    return http_status(error) in _REJECTED_STATUSES


def _resend_allowed(error: BaseException) -> bool:
    """The journal writer's re-send rule (its one owner).

    Re-send when the failure carries NO HTTP status at all (whatever its type: a lost
    connection or response, a timeout, or a non-HTTP error such as a worksheet lookup
    failure) or a status the Sheets client itself retries. Every re-send is guarded by the
    pause, lock re-check and whole-tab readback in :func:`record`. Any other status
    (including permanent 4xx outside the rejected set, 501, 502, 504) is not re-sent; the
    readback alone decides whether it landed.
    """
    status = http_status(error)
    return status is None or is_transient_status(status)


def _with_after(evidence: tuple[Path, ...], after: SourceCapture) -> tuple[Path, ...]:
    """Retain the post-write readback beside the pre-write snapshot (private evidence).

    Created exclusively; if it cannot be written the classified error is still raised with
    the evidence that exists.
    """
    path = evidence[0].parent / "after-readback.json"
    try:
        with path.open("xb") as handle:
            handle.write(canonical_json_bytes(after.to_dict()))
    except OSError:
        return evidence
    return (*evidence, path)


def record(
    proposals: Sequence[Adjustment],
    *,
    config: Config,
    client: SheetsClient,
    captured: SourceCapture,
    reconciliation: Reconciliation,
    as_of: date,
    lock: RunLock,
    clock: Clock | None = None,
    on_snapshot: Callable[[Path], None] | None = None,
) -> RecordResult:
    """Append validated proposals to our Assumptions journal and verify them by readback.

    Calling this IS the explicit write opt-in: the end-to-end command must reach it only
    for an explicit ``--adjustments-file`` and never in source-only or ``--dry-run`` mode,
    which read the journal through :func:`read_journal` / :func:`project` and write nothing.

    ``captured`` is the Assumptions capture the run is based on: the live tab must still hash
    the same (``assumptions_changed`` otherwise; recapture and review). Proposals whose ID is
    already recorded with identical content are skipped (idempotent rerun); a different
    payload under a recorded ID, a failed target precondition or any conflict in the
    resulting journal refuses the whole batch before any write. ``lock`` must be the held
    writer lock (:func:`acquire_run_lock`); its token is re-checked on disk at entry and
    again just before the write. Every failure after validation is an
    :class:`AdjustmentWriteError` with a code, retained evidence, a value-free cause and
    ``may_have_landed``. ``on_snapshot`` is called with the pre-write snapshot path immediately
    before the first write request (after the snapshot, the second read, the grid growth and
    the lock re-check), so a caller can record the evidence even if the call is then
    interrupted. The write itself is sent once per attempt, without the client's hidden
    retry; the re-send rule, pause, lock re-check and fresh readback are described in the
    module docstring. ``may_have_landed`` is ``False`` only for a failure before the first
    request or an outright rejection of that first request with the tab unchanged. See the module
    docstring for the race limit.
    """
    main_reports = _main_reports(config)
    root = main_reports.output_path
    _require_lock(lock, root)
    _require_own_workbook(config, main_reports, client)
    now = clock or _utc_now
    tab = main_reports.assumptions_tab
    workbook = ReadOnlyWorkbook(client)
    evidence: tuple[Path, ...] = ()

    def fresh() -> SourceCapture:
        try:
            current = capture_assumptions(workbook, tab, now)
        except SHEETS_FAILURES as error:
            raise AdjustmentWriteError(
                "assumptions_unreadable",
                "the Assumptions tab could not be read before writing; nothing was written",
                evidence,
                _cause(error),
                may_have_landed=False,
            ) from None
        if current.sha256 != captured.sha256:
            raise AdjustmentWriteError(
                "assumptions_changed",
                "the Assumptions tab changed since the run captured it; recapture and review",
                evidence,
                may_have_landed=False,
            )
        return current

    def read_back(cause: str | None) -> SourceCapture:
        try:
            return capture_assumptions(workbook, tab, now)
        except SHEETS_FAILURES as error:
            raise AdjustmentWriteError(
                "write_unverified",
                "the journal write outcome could not be read back; recapture before retrying",
                evidence,
                cause or _cause(error),
                may_have_landed=True,
            ) from None

    current = fresh()
    journal = read_journal(current)
    plan, already = _plan(proposals, journal, reconciliation, as_of, now())
    if plan is None:
        return RecordResult(
            written=(),
            already_recorded=already,
            snapshot_path=None,
            assumptions=current,
            journal=journal,
            attempts=0,
        )

    try:
        snapshot = backup.snapshot_raw_tab(client, tab, root / SNAPSHOT_DIR)
    except SHEETS_FAILURES as error:
        raise AdjustmentWriteError(
            "snapshot_failed",
            "no pre-write snapshot; nothing was written",
            (),
            _cause(error),
            may_have_landed=False,
        ) from None
    evidence = (snapshot,)
    before = fresh()
    occupied = _occupied_plan_cells(before, plan)
    if occupied:
        raise AdjustmentWriteError(
            "planned_cells_occupied",
            f"{occupied} planned journal cell(s) are not empty; nothing was written",
            evidence,
            may_have_landed=False,
        )
    try:
        client.ensure_grid_size(tab, plan.last_row, _WIDTH)
    except SHEETS_FAILURES as error:
        raise AdjustmentWriteError(
            "grid_resize_failed",
            "the tab could not be grown for the journal rows; nothing was written",
            evidence,
            _cause(error),
            may_have_landed=False,
        ) from None
    try:
        _require_lock(lock, root)
    except AdjustmentError as error:
        raise AdjustmentWriteError(
            error.code,
            "the run lock was lost before writing; nothing was written",
            evidence,
            may_have_landed=False,
        ) from None
    if on_snapshot is not None:  # the last step before the first request to the tab
        try:
            on_snapshot(snapshot)
        except Exception as error:
            raise AdjustmentWriteError(
                "snapshot_callback_failed",
                "the caller's snapshot hook failed; nothing was written",
                evidence,
                type(error).__name__,
                may_have_landed=False,
            ) from None

    def landed(observed: SourceCapture, cause: str | None) -> SourceCapture:
        """A changed tab must be exactly the planned journal; anything else stops."""
        failure = _verify(before, observed, plan)
        if failure is not None:
            raise AdjustmentWriteError(
                "write_uncertain_conflict",
                f"after an uncertain write the tab is not the planned journal ({failure}); "
                "nothing was restored",
                _with_after(evidence, observed),
                cause,
                may_have_landed=True,
            ) from None  # called while handling a transport error: never chain its text
        return observed

    attempts = 0
    while True:
        attempts += 1
        try:
            # One request per attempt (no hidden client retry): this loop sees every attempt,
            # so an earlier unobserved attempt is never mistaken for a clean rejection.
            client.write_raw_ranges(tab, plan.ranges, retry=False)
        except SHEETS_FAILURES as error:
            # The outcome is uncertain: decide it from a whole-tab readback.
            cause = _cause(error)
            observed = read_back(cause)
            if observed.sha256 != before.sha256:
                after = landed(observed, cause)
                break
            rejected = _rejected(error)
            delay = client.backoff_delay(attempts) if _resend_allowed(error) else None
            if delay is None:
                # Only a first attempt that was rejected outright, with the tab unchanged,
                # cannot have landed; an earlier unobserved attempt still might.
                may_have_landed = not rejected or attempts > 1
                message = (
                    f"the journal write was not observed after {attempts} attempt(s) and MAY "
                    "still land: recapture and rerun (a rerun skips every adjustment ID the "
                    "journal already holds)"
                    if may_have_landed
                    else "the journal write was rejected; nothing was recorded"
                )
                raise AdjustmentWriteError(
                    "write_failed",
                    message,
                    evidence,
                    cause,
                    may_have_landed=may_have_landed,
                ) from None
            # Before the re-send: pause, re-check the lock, then read the whole tab again so
            # a write seen to have landed during the pause is not sent twice and an edit seen
            # meanwhile is refused rather than overwritten. (A landing after this read is
            # rewritten with identical values to the same ranges and checked by _verify.)
            client.pause(delay)
            try:
                _require_lock(lock, root)
            except AdjustmentError as lost:
                raise AdjustmentWriteError(
                    lost.code,
                    "the run lock was lost between write attempts; not sent again",
                    evidence,
                    cause,
                    may_have_landed=True,
                ) from None
            observed = read_back(cause)
            if observed.sha256 != before.sha256:
                after = landed(observed, cause)
                break
            continue
        after = read_back(None)
        failure = _verify(before, after, plan)
        if failure is not None:
            raise AdjustmentWriteError(
                failure,
                "the readback differs from the planned journal; publication must stop and "
                "nothing was restored",
                _with_after(evidence, after),
                may_have_landed=True,
            )
        break
    try:
        recorded = read_journal(after)
    except Exception as error:
        raise AdjustmentWriteError(
            "journal_unreadable_after_write",
            "the journal was written and verified but could not be parsed back; recapture "
            "before trusting it",
            _with_after(evidence, after),
            type(error).__name__,
            may_have_landed=True,
        ) from None
    return RecordResult(
        written=plan.new_ids,
        already_recorded=already,
        snapshot_path=snapshot,
        assumptions=after,
        journal=recorded,
        attempts=attempts,
    )
