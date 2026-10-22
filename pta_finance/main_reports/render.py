"""Render the Main Report Set from one :class:`~pta_finance.main_reports.models.ReportFacts`.

:func:`write` is the production caller (``docs/plan-reference/cfo-main-report-set.md``
sections 5, 6E and 10). Into one caller-provided run directory it writes:

* the **Reimbursement Queue** (``reimbursement-report.html`` plus its ``.copy.txt``) through
  the existing :func:`pta_finance.reimbursement_report.build_report`, unchanged, so the
  queue template, copy text and fingerprint-validated receipt sidecar (embedded receipt
  pages with their red marks) are reused as they are;
* four summaries rendered from the facts: **Reimbursement Summary** and **Budget Snapshot**
  and **Fundraising Summary** (school year, July-June) and the **CFO P&L Summary**
  (calendar year, monthly columns plus year to date), each as HTML plus a PDF and a PNG
  (:mod:`pta_finance.main_reports.export`);
* the private report index ``main-report-set.html`` linking all five.

Every page names its period and basis, the as-of date, the run ID, source freshness and
the adjustment, discrepancy and finding counts. Unknown amounts render as ``Unknown`` (never
``0.00``); an observed zero renders as ``$0.00``. Budget comparisons stay in the school-year
Budget Snapshot: no calendar-year budget is derived. Every bridge row lists the records
behind its amount and every residual stays visible.

Labels arrive raw from the sources and the bundle; Jinja autoescaping escapes every one and
each page carries a restrictive Content-Security-Policy, so source text is shown as text and
never interpreted. Every file is replaced atomically; nothing is written outside the run
directory. Error text names codes and counts, never a money or cell value.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from pta_finance import reimbursement_report
from pta_finance.main_reports import export, facts
from pta_finance.main_reports.models import (
    ARTIFACT_MEDIA_TYPES,
    BUDGET_ACTUAL_STATUSES,
    EXPENSE_BUCKETS,
    HEX_DIGEST_PATTERN,
    PAYMENT_BUCKETS,
    PERIOD_BASES,
    TRANSACTION_KINDS,
    VIEW_BASES,
    Artifact,
    ArtifactSet,
    Bridge,
    CaptureSet,
    CoverageStatus,
    Period,
    ReportFacts,
    SourceRef,
    is_valid_run_id,
    money_str,
)
from pta_finance.reimbursement_report import STATUS_META, ReimbursementReport

__all__ = [
    # constants
    "QUEUE_HTML",
    "QUEUE_COPY_TEXT",
    "INDEX_HTML",
    "OUTPUT_NAMES",
    "STAGING_PREFIX",
    "SUMMARY_NAMES",
    "REPORT_TITLES",
    "BRIDGE_TITLES",
    "ADOPTED_BUDGET_KIND",
    "RENDER_ERROR_CODES",
    # functions
    "format_money",
    "write",
    # types
    "RenderError",
    "SourceFreshness",
    "RenderContext",
]

# Artifact names (contract section 6E): the existing queue name, then the four summaries.
QUEUE_HTML = "reimbursement-report.html"
INDEX_HTML = "main-report-set.html"
SUMMARY_NAMES: tuple[str, ...] = (
    "reimbursement-summary",
    "budget-snapshot",
    "fundraising-summary",
    "cfo-pnl-summary",
)
_REIMBURSEMENT, _BUDGET, _FUNDRAISING, _PNL = SUMMARY_NAMES
# build_report's copy-text companion of the queue (checked against what it writes).
QUEUE_COPY_TEXT = f"{Path(QUEUE_HTML).stem}.copy.txt"
# Every file one rendered set holds; the index is listed (and moved into place) last.
OUTPUT_NAMES: tuple[str, ...] = (
    QUEUE_HTML,
    QUEUE_COPY_TEXT,
    *(f"{name}.{suffix}" for name in SUMMARY_NAMES for suffix in ("html", "pdf", "png")),
    INDEX_HTML,
)
# Private staging folders inside a run directory.
STAGING_PREFIX = ".render-"
_STAGING_ATTEMPTS = 3
_QUEUE = "reimbursement-queue"
REPORT_TITLES: Mapping[str, str] = {
    _QUEUE: "Reimbursement Queue",
    _REIMBURSEMENT: "Reimbursement Summary",
    _BUDGET: "Budget Snapshot",
    _FUNDRAISING: "Fundraising Summary",
    _PNL: "CFO P&L Summary",
}
_HTML, _PDF, _PNG, _TEXT = ARTIFACT_MEDIA_TYPES

BRIDGE_TITLES: Mapping[str, str] = {
    "school_source_scope": "Source P&L (all captured months) to the school-year source view",
    "calendar_source_scope": "Source P&L (all captured months) to the calendar-year source view",
    "school_adjustments": "School-year source view to adjusted view",
    "calendar_adjustments": "Calendar-year source view to adjusted view",
    "calendar_to_school": "Calendar-year adjusted net to school-year adjusted net",
    "school_expense_basis": "School-year bank basis to item expense basis",
    "school_budget_crosswalk": "School-year adjusted net to budget-mapped actuals",
    "school_payment_timing": "Approved expense dated in the school year to payments made in it",
}
if set(BRIDGE_TITLES) != set(facts.BRIDGE_NAMES):  # pragma: no cover - import-time invariant
    raise RuntimeError("render bridge titles must match facts.BRIDGE_NAMES")

# Freshness kind of our own adopted budget (the Assumptions capture keeps its own alias/kind).
ADOPTED_BUDGET_KIND = "adopted_budget"

RENDER_ERROR_CODES: tuple[str, ...] = (
    "run_dir_invalid",
    "context_invalid",
    "context_mismatch",
    "bundle_invalid",
    "bundle_mismatch",
    "queue_invalid",
    "totals_mismatch",
    "output_failed",
    "run_dir_not_empty",
    "output_incomplete",
    "staging_not_removed",
)
(
    _RUN_DIR_INVALID,
    _CONTEXT_INVALID,
    _CONTEXT_MISMATCH,
    _BUNDLE_INVALID,
    _BUNDLE_MISMATCH,
    _QUEUE_INVALID,
    _TOTALS_MISMATCH,
    _OUTPUT_FAILED,
    _RUN_DIR_NOT_EMPTY,
    _OUTPUT_INCOMPLETE,
    _STAGING_NOT_REMOVED,
) = RENDER_ERROR_CODES

_SCHOOL, _CALENDAR = PERIOD_BASES
_SOURCE_VIEW, _ADJUSTED_VIEW = VIEW_BASES
_PRIOR, _CURRENT, _LATER, _UNDATED = EXPENSE_BUCKETS
_UNPAID = PAYMENT_BUCKETS[0]
_BANK = TRANSACTION_KINDS[0]
_APPROVED = facts.APPROVED_STATUS
_INCOME, _EXPENSE = facts.BUDGET_LINE_TYPES
_COVERAGE_LIMIT = facts.FUNDRAISING_LIMITS[2]
_ZERO = Decimal("0.00")
_UNKNOWN = "Unknown"
_NOT_RECORDED = "Not recorded"
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "reports" / "templates"
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_BUCKET_LABELS: Mapping[str, str] = {
    _UNPAID: "Not paid",
    _PRIOR: "Before the period",
    _CURRENT: "In the period",
    _LATER: "After the as-of date",
    _UNDATED: "Undated",
}
_OBSERVED = BUDGET_ACTUAL_STATUSES[0]
_BUDGET_REASONS: Mapping[str, str] = {
    "ambiguous": "Unknown: the category has more than one adopted line",
    "crosswalk_missing": "Unknown: no category crosswalk is configured",
    "category_unmapped": "Unknown: no source category maps to this budget category",
    "coverage_partial": "Unknown: bank coverage is partial for the period",
}
_UNTYPED_REASON = "Unknown: the line type is not income or expense"
if {*_BUDGET_REASONS, _OBSERVED} != set(BUDGET_ACTUAL_STATUSES):  # pragma: no cover
    raise RuntimeError("render budget reasons must match BUDGET_ACTUAL_STATUSES")
if _COVERAGE_LIMIT != "coverage_partial":  # pragma: no cover - import-time invariant
    raise RuntimeError("render must read the fundraising coverage limit from facts")
# Exports one call's summaries (one job per summary) and says whether Chromium's sandbox
# was used (``None``: not applicable); see :func:`write`.
Exporter = Callable[[Sequence[export.ExportJob]], bool | None]


class RenderError(Exception):
    """The Main Report Set cannot be rendered safely. Carries a stable ``code``
    (:data:`RENDER_ERROR_CODES`); its text never carries a money or cell value.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class SourceFreshness:
    """When one input of the captured set was read, and what it observed.

    ``label`` is the source alias (or our own budget tab title); ``kind`` is the capture kind
    (:data:`~pta_finance.main_reports.models.SOURCE_KINDS`, the Assumptions alias, or
    :data:`ADOPTED_BUDGET_KIND`). ``observed_first`` / ``observed_last`` are the first and
    last dated rows, which never prove coverage on their own.
    """

    label: str
    kind: str
    captured_at: datetime
    sha256: str
    observed_first: date | None = None
    observed_last: date | None = None


@dataclass(frozen=True)
class RenderContext:
    """Run identity and source freshness shown on every page.

    ``run_id`` has the :func:`~pta_finance.main_reports.models.make_run_id` shape and
    ``input_sha256`` is the hash of the captured input set the facts were built from.
    """

    run_id: str
    input_sha256: str
    sources: tuple[SourceFreshness, ...]

    @classmethod
    def from_capture_set(
        cls, run_id: str, capture_set: CaptureSet, *, input_sha256: str | None = None
    ) -> RenderContext:
        """Freshness of every capture, our Assumptions and adopted budget, read once.

        ``input_sha256`` defaults to the capture set's aggregate hash.
        """
        sources = [
            SourceFreshness(
                label=capture.alias,
                kind=capture.kind,
                captured_at=capture.captured_at,
                sha256=capture.sha256,
                observed_first=capture.observed_first,
                observed_last=capture.observed_last,
            )
            for capture in (*capture_set.captures, capture_set.assumptions)
        ]
        budget = capture_set.adopted_budget
        sources.append(
            SourceFreshness(
                label=budget.tab_title,
                kind=ADOPTED_BUDGET_KIND,
                captured_at=budget.captured_at,
                sha256=budget.sha256,
            )
        )
        return cls(
            run_id=run_id,
            input_sha256=input_sha256 or capture_set.aggregate_sha256,
            sources=tuple(sources),
        )


# --------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------


def format_money(value: Decimal | None) -> str:
    """Exact cents as ``$1,234.56`` / ``-$1,234.56``; ``None`` (unknown) as ``Unknown``."""
    if value is None:
        return _UNKNOWN
    exact = Decimal(money_str(value))
    sign = "-" if exact < 0 else ""
    return f"{sign}${abs(exact):,.2f}"


def _iso(value: date | None) -> str:
    return _NOT_RECORDED if value is None else value.isoformat()


def _long(value: date) -> str:
    return f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise RenderError(_CONTEXT_INVALID, "a capture time is not timezone-aware")
    return f"{value.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def _humanize(code: str) -> str:
    words = ["P&L" if word == "pnl" else word for word in code.replace("-", "_").split("_")]
    text = " ".join(word for word in words if word)
    return text[:1].upper() + text[1:]


def _range(start: date | None, end: date | None) -> str:
    if start is None and end is None:
        return "No dated rows"
    return f"{_iso(start)} to {_iso(end)}"


# --------------------------------------------------------------------------------------
# Input checks
# --------------------------------------------------------------------------------------


def _check_context(report: ReportFacts, context: RenderContext) -> None:
    if not is_valid_run_id(context.run_id):
        raise RenderError(_CONTEXT_INVALID, "the run ID does not have the run-ID shape")
    if HEX_DIGEST_PATTERN.match(context.input_sha256) is None:
        raise RenderError(_CONTEXT_INVALID, "the input-set hash is not a SHA-256 digest")
    labels = [source.label for source in context.sources]
    if len(set(labels)) != len(labels):
        raise RenderError(_CONTEXT_INVALID, "source freshness labels must be unique")
    for source in context.sources:
        _timestamp(source.captured_at)
    known = set(labels)
    missing = sum(1 for status in report.coverage if status.source_alias not in known)
    hashes = {source.sha256 for source in context.sources}
    refs = [ref for ref in _all_refs(report) if ref.snapshot_sha256 not in hashes]
    if missing or refs:
        raise RenderError(
            _CONTEXT_MISMATCH,
            f"{missing} coverage source(s) and {len(refs)} evidence ref(s) name no capture "
            "of this run's input set",
        )


def _all_refs(report: ReportFacts) -> Iterable[SourceRef]:
    for bridge in report.bridges:
        for row in bridge.rows:
            yield from row.refs
    for join in report.reimbursements.joins:
        yield from join.bank_refs


def _check_bundle(report: ReportFacts, bundle: ReimbursementReport) -> None:
    """The staged bundle must be the one the facts were projected from."""
    reimbursements = report.reimbursements
    window = (
        bundle.settings.as_of_date,
        bundle.settings.cutoff_date,
        bundle.source_summary.first_received,
        bundle.source_summary.last_received,
    )
    expected = (
        reimbursements.bundle_as_of,
        reimbursements.cutoff_date,
        reimbursements.first_received,
        reimbursements.last_received,
    )
    items = sorted((t.review_key, i.item_key) for t in bundle.tickets for i in t.items)
    fact_items = sorted((item.review_key, item.item_key) for item in reimbursements.items)
    queue = [ticket.review_key for ticket in bundle.active_tickets]
    fact_queue = [entry.review_key for entry in reimbursements.queue]
    mismatched = sum(
        (
            window != expected,
            items != fact_items,
            queue != fact_queue,
            bundle.summary.outstanding != reimbursements.outstanding,
        )
    )
    if mismatched:
        raise RenderError(
            _BUNDLE_MISMATCH,
            f"the staged bundle differs from the facts' bundle in {mismatched} check(s)",
        )


# --------------------------------------------------------------------------------------
# Shared page parts
# --------------------------------------------------------------------------------------


def _period(period: Period) -> dict[str, str]:
    return {
        "label": period.label,
        "range": f"{_long(period.start)} to {_long(period.end_inclusive)}",
        "through": _long(min(period.as_of, period.end_inclusive)),
        # The legacy fiscal-year label belongs to the school year only.
        "legacy": f"FY{period.year_label}" if period.basis == _SCHOOL else "",
    }


def _status_label(code: str) -> str:
    """The queue's status label, with a readable name for the queue's dash (no status)."""
    label = STATUS_META[code][0]
    return label if label.strip("—–- ") else "No status"


def _status_for(report: ReportFacts, alias: str, period: Period) -> CoverageStatus | None:
    for status in report.coverage:
        if (status.source_alias, status.start, status.end_exclusive) == (
            alias,
            period.start,
            period.clip_end,
        ):
            return status
    return None


def _coverage_text(status: CoverageStatus | None) -> str:
    if status is None:
        return "Not a transaction feed"
    if status.complete:
        return "Complete for the period"
    gaps = "; ".join(f"{a.isoformat()} to {b.isoformat()} (exclusive)" for a, b in status.uncovered)
    return f"Partial: no declared coverage {gaps}"


def _freshness(report: ReportFacts, context: RenderContext, period: Period) -> list[dict[str, Any]]:
    rows = []
    for source in context.sources:
        feed = source.kind in TRANSACTION_KINDS
        status = _status_for(report, source.label, period) if feed else None
        rows.append(
            {
                "label": source.label,
                "kind": _humanize(source.kind),
                "captured": _timestamp(source.captured_at),
                "observed": _range(source.observed_first, source.observed_last)
                if feed
                else "Not applicable",
                "coverage": _coverage_text(status) if feed else "Not a transaction feed",
                "partial": feed and (status is None or not status.complete),
                "sha": source.sha256[:12],
            }
        )
    return rows


def _counts(report: ReportFacts) -> list[dict[str, Any]]:
    return [
        {"label": "Adjustments applied", "value": len(report.applied_adjustments)},
        {
            "label": "Adjustments pending (after the as-of date)",
            "value": len(report.pending_adjustments),
        },
        {"label": "Adjustments superseded", "value": len(report.superseded_adjustments)},
        {"label": "Adjustment warnings", "value": len(report.adjustment_warnings)},
        {"label": "Unresolved discrepancies", "value": len(report.discrepancy_ids)},
        {"label": "Findings", "value": sum(issue.count for issue in report.issues)},
        {"label": "Coverage flags", "value": len(report.coverage_flags)},
    ]


def _findings(report: ReportFacts) -> dict[str, Any]:
    return {
        "issues": [
            {"code": _humanize(i.code), "count": i.count, "subject": i.subject or ""}
            for i in report.issues
        ],
        "flags": [
            {"code": _humanize(f.code), "source": f.source_alias or "All sources", "count": f.count}
            for f in report.coverage_flags
        ],
        "warnings": [
            {
                "code": _humanize(w.code),
                "severity": w.severity,
                "adjustment": w.adjustment_id or "",
                "row": "" if w.row_number is None else str(w.row_number),
                "field": w.field or "",
            }
            for w in report.adjustment_warnings
        ],
        "applied": list(report.applied_adjustments),
        "pending": list(report.pending_adjustments),
        "superseded": list(report.superseded_adjustments),
        "discrepancies": list(report.discrepancy_ids),
        "control": _humanize(report.pnl_control_status),
    }


def _ref_text(ref: SourceRef) -> str:
    return f"{ref.source_alias} row {ref.row_number} (revision {ref.revision_hash[:8]})"


def _bridge(bridge: Bridge) -> dict[str, Any]:
    rows = []
    for row in bridge.rows:
        evidence = [
            *(_ref_text(ref) for ref in row.refs),
            *(f"Adjustment {adjustment}" for adjustment in row.adjustment_ids),
            *(f"Reimbursement item {key}" for key in row.item_keys),
        ]
        rows.append(
            {
                "kind": _humanize(row.kind),
                "explanation": row.explanation,
                "amount": format_money(row.amount),
                "evidence": evidence,
            }
        )
    return {
        "name": bridge.name,
        "title": BRIDGE_TITLES[bridge.name],
        "from_label": _humanize(bridge.from_label),
        "from_amount": format_money(bridge.from_amount),
        "to_label": _humanize(bridge.to_label),
        "to_amount": format_money(bridge.to_amount),
        "rows": rows,
        "residual": format_money(bridge.residual),
        "balanced": bridge.balanced,
    }


def _shared_totals(report: ReportFacts, bundle: ReimbursementReport) -> dict[str, dict[str, Any]]:
    """Totals shown in more than one report, with the reports that show them.

    Each value is computed once and checked against every other representation of the same
    scope (bridge endpoints, the queue's pay-now reducer); a difference is a render error.
    """
    school = report.view(_SCHOOL, _ADJUSTED_VIEW)
    calendar = report.view(_CALENDAR, _ADJUSTED_VIEW)
    reimbursements = report.reimbursements
    checks = (
        report.bridge("school_budget_crosswalk").from_amount == school.net,
        report.bridge("calendar_to_school").to_amount == school.net,
        report.bridge("calendar_to_school").from_amount == calendar.net,
        report.bridge("calendar_adjustments").to_amount == calendar.net,
        report.bridge("school_payment_timing").to_amount == reimbursements.paid(_CURRENT),
        bundle.summary.outstanding == reimbursements.outstanding,
        sum((reimbursements.open_amount(b, _APPROVED) for b in EXPENSE_BUCKETS), _ZERO)
        == reimbursements.outstanding,
    )
    if not all(checks):
        raise RenderError(
            _TOTALS_MISMATCH,
            f"{checks.count(False)} shared-scope total(s) disagree between representations",
        )
    return {
        "school_net": {
            "label": f"{report.periods.school.label} adjusted bank net",
            "value": format_money(school.net),
            "partial": not school.complete,
            "reports": [
                REPORT_TITLES[_BUDGET],
                REPORT_TITLES[_FUNDRAISING],
                REPORT_TITLES[_PNL],
            ],
        },
        "calendar_net": {
            "label": f"{report.periods.calendar.label} adjusted bank net",
            "value": format_money(calendar.net),
            "partial": not calendar.complete,
            "reports": [REPORT_TITLES[_PNL]],
        },
        "outstanding": {
            "label": "Approved and not yet paid (all open requests)",
            "value": format_money(reimbursements.outstanding),
            "partial": False,
            "reports": [REPORT_TITLES[_REIMBURSEMENT], REPORT_TITLES[_QUEUE]],
        },
        "paid": {
            "label": f"Reimbursements paid in {report.periods.school.label}",
            "value": format_money(reimbursements.paid(_CURRENT)),
            "partial": False,
            "reports": [REPORT_TITLES[_REIMBURSEMENT]],
        },
    }


def _page(
    name: str,
    report: ReportFacts,
    bundle: ReimbursementReport,
    context: RenderContext,
    period: Period,
    basis: str,
) -> dict[str, Any]:
    settings = bundle.settings
    return {
        "name": name,
        "title": REPORT_TITLES[name],
        "organization": settings.organization,
        "logo": settings.logo_data_uri,
        "period": _period(period),
        "basis": basis,
        "as_of": _long(report.as_of),
        "run_id": context.run_id,
        "input_sha": context.input_sha256,
        "freshness": _freshness(report, context, period),
        "bundle": {
            "as_of": _iso(report.reimbursements.bundle_as_of),
            "received": _range(
                report.reimbursements.first_received, report.reimbursements.last_received
            ),
            "cutoff": _iso(report.reimbursements.cutoff_date),
        },
        "counts": _counts(report),
        "findings": _findings(report),
        "index": INDEX_HTML,
        "queue": QUEUE_HTML,
    }


# --------------------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------------------


def _reimbursement_summary(report: ReportFacts) -> dict[str, Any]:
    data = report.reimbursements
    statuses = list(STATUS_META)
    by_expense: dict[tuple[str, str], tuple[int, Decimal, int]] = {}
    for total in data.totals:
        count, amount, unpriced = by_expense.get(
            (total.expense_bucket, total.status), (0, _ZERO, 0)
        )
        by_expense[(total.expense_bucket, total.status)] = (
            count + total.count,
            amount + total.amount,
            unpriced + total.unpriced,
        )
    expense_rows = []
    for bucket in EXPENSE_BUCKETS:
        cells = []
        for status in statuses:
            count, amount, unpriced = by_expense.get((bucket, status), (0, _ZERO, 0))
            cells.append(
                {
                    "amount": format_money(amount),
                    "count": count,
                    "unpriced": unpriced,
                }
            )
        expense_rows.append({"bucket": _BUCKET_LABELS[bucket], "cells": cells})
    paid_rows = [
        {"bucket": _BUCKET_LABELS[bucket], "amount": format_money(data.paid(_CURRENT, bucket))}
        for bucket in EXPENSE_BUCKETS
    ]
    open_rows = [
        {
            "bucket": _BUCKET_LABELS[bucket],
            "amount": format_money(data.open_amount(bucket, _APPROVED)),
        }
        for bucket in EXPENSE_BUCKETS
    ]
    queue = [
        {
            "ref": entry.ticket_ref,
            "origin": _humanize(entry.origin),
            "submitted": _iso(entry.submitted),
            "earliest": _iso(entry.earliest_expense_date),
            "undated": entry.undated_items,
            "pay_now": format_money(entry.pay_now),
            "carryover": _humanize(entry.carryover_basis) if entry.carryover_basis else "",
        }
        for entry in data.queue
    ]
    joins = [
        {
            "ref": join.ticket_ref,
            "state": _humanize(join.state),
            "date": _iso(join.payment_date),
            "reference": join.reference or _NOT_RECORDED,
            "amount": format_money(join.amount) if join.amount is not None else _NOT_RECORDED,
            "bank": [_ref_text(ref) for ref in join.bank_refs],
        }
        for join in data.joins
    ]
    groups = [
        {
            "expense": _BUCKET_LABELS[t.expense_bucket],
            "payment": _BUCKET_LABELS[t.payment_bucket],
            "status": _status_label(t.status),
            "open": "Open" if t.open else "Settled",
            "count": t.count,
            "amount": format_money(t.amount),
            "unpriced": t.unpriced,
        }
        for t in data.totals
    ]
    return {
        "headline": [
            ("Approved, not yet paid", format_money(data.outstanding), "a"),
            ("Requests in the queue", str(len(data.queue)), ""),
            ("Prior-year carryovers", str(sum(1 for e in data.queue if e.carryover)), "c"),
            (
                "Approved expense dated in the period",
                format_money(data.expense(_CURRENT, _APPROVED)),
                "",
            ),
            ("Paid in the period", format_money(data.paid(_CURRENT)), "a"),
            (
                "Paid in the period for prior-year expenses",
                format_money(data.paid(_CURRENT, _PRIOR)),
                "q",
            ),
        ],
        "statuses": [(_status_label(s), STATUS_META[s][1]) for s in statuses],
        "expense_rows": expense_rows,
        "paid_rows": paid_rows,
        "open_rows": open_rows,
        "outstanding": format_money(data.outstanding),
        "queue": queue,
        "joins": joins,
        "groups": groups,
        "bridges": [
            _bridge(report.bridge("school_payment_timing")),
            _bridge(report.bridge("school_expense_basis")),
        ],
    }


def _budget_snapshot(report: ReportFacts) -> dict[str, Any]:
    budget = report.budget
    lines = []
    targets: dict[str, list[Decimal]] = defaultdict(list)
    missing: dict[str, int] = defaultdict(int)
    for line in budget.lines:
        typed = line.line_type in facts.BUDGET_LINE_TYPES
        activity: Decimal | None = None
        if line.actual is not None and typed:
            activity = line.actual if line.line_type == _INCOME else -line.actual
        if line.target is None:
            missing[line.line_type] += 1
        else:
            targets[line.line_type].append(line.target)
        remaining = (
            line.target - activity if line.target is not None and activity is not None else None
        )
        if line.actual is None:
            status = _BUDGET_REASONS[line.actual_status]
        elif not typed:
            status = _UNTYPED_REASON
        else:
            status = "Observed"
        lines.append(
            {
                "type": _humanize(line.line_type) if line.line_type else _NOT_RECORDED,
                "category": line.category,
                "target": format_money(line.target),
                "target_unknown": line.target is None,
                "actual": format_money(line.actual),
                "activity": format_money(activity),
                "remaining": format_money(remaining),
                "status": status,
                "unknown": activity is None,
            }
        )

    def total(line_type: str) -> dict[str, Any]:
        return {
            "value": format_money(sum(targets[line_type], _ZERO)),
            "missing": missing[line_type],
        }

    return {
        "fiscal_year": budget.fiscal_year,
        "crosswalk": "Not configured"
        if budget.crosswalk_version is None
        else f"version {budget.crosswalk_version}",
        "lines": lines,
        "unknown_actuals": sum(1 for line in budget.lines if line.actual is None),
        "target_income": total(_INCOME),
        "target_expense": total(_EXPENSE),
        "untyped": sum(1 for line in budget.lines if line.line_type not in facts.BUDGET_LINE_TYPES),
        "unmapped": [(name, format_money(amount)) for name, amount in budget.unmapped],
        "unbudgeted": [(name, format_money(amount)) for name, amount in budget.unbudgeted],
        "other_year_rows": budget.other_year_rows,
        "bridges": [
            _bridge(report.bridge("school_source_scope")),
            _bridge(report.bridge("school_adjustments")),
            _bridge(report.bridge("school_budget_crosswalk")),
        ],
    }


def _fundraising_summary(report: ReportFacts) -> dict[str, Any]:
    """Processor totals. An incomplete processor's amounts are marked partial; one with no
    rows and no declared coverage for the period is Unknown, never an invented $0.00.
    """
    processors = []
    sums: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for item in report.fundraising:
        rows = item.payment_count + item.fee_rows + item.refund_rows + item.excluded_rows
        unknown = _COVERAGE_LIMIT in item.incomplete_reasons and rows == 0
        amounts: dict[str, str] = {}
        for key in ("gross", "fees", "refunds", "net"):
            value: Decimal = getattr(item, key)
            sums[key] += value
            amounts[key] = _UNKNOWN if unknown else format_money(value)
        processors.append(
            {
                "alias": item.source_alias,
                **amounts,
                "payments": item.payment_count,
                "fee_rows": item.fee_rows,
                "refund_rows": item.refund_rows,
                "excluded": item.excluded_rows,
                "complete": item.complete,
                "unknown": unknown,
                "reasons": [_humanize(reason) for reason in item.incomplete_reasons],
                "categories": [
                    {
                        "category": category.category or "Not attributed",
                        "attributed": category.category is not None,
                        "classification": _humanize(category.classification),
                        "count": category.count,
                        "gross": format_money(category.gross),
                    }
                    for category in item.categories
                ],
            }
        )
    school = report.view(_SCHOOL, _ADJUSTED_VIEW)
    unknown_count = sum(1 for item in processors if item["unknown"])
    every_unknown = bool(processors) and unknown_count == len(processors)
    return {
        "processors": processors,
        "combined": {
            key: _UNKNOWN if every_unknown else format_money(value) for key, value in sums.items()
        }
        if processors
        else None,
        "unknown_count": unknown_count,
        "every_unknown": every_unknown,
        "complete": all(item.complete for item in report.fundraising),
        "bank_income": format_money(school.income),
        "bank_complete": school.complete,
    }


def _month_starts(period: Period) -> list[date]:
    last = min(period.as_of, period.end_inclusive)
    months = []
    current = period.start
    while current <= last:
        months.append(current)
        current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
    return months


def _month_covered(
    report: ReportFacts, context: RenderContext, period: Period, month: date
) -> bool:
    """Declared bank coverage spans the clipped month for every bank source."""
    end = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    window = (max(month, period.start), min(end, period.clip_end))
    banks = [source.label for source in context.sources if source.kind == _BANK]
    if not banks:
        return False
    for alias in banks:
        status = _status_for(report, alias, period)
        if status is None:
            return False
        if any(a < window[1] and b > window[0] for a, b in status.uncovered):
            return False
    return True


def _pnl_summary(report: ReportFacts, context: RenderContext) -> dict[str, Any]:
    period = report.periods.calendar
    source = report.view(_CALENDAR, _SOURCE_VIEW)
    adjusted = report.view(_CALENDAR, _ADJUSTED_VIEW)
    months = _month_starts(period)
    covered = {month: _month_covered(report, context, period, month) for month in months}
    cells = {(cell.category, cell.month): cell.net for cell in adjusted.cells}
    categories = sorted({cell.category for cell in adjusted.cells})

    def cell(value: Decimal | None, month: date) -> dict[str, Any]:
        if value is None:
            if covered[month]:
                return {"text": format_money(_ZERO), "kind": "zero"}
            return {"text": "Not covered", "kind": "uncovered"}
        return {"text": format_money(value), "kind": "value" if covered[month] else "partial"}

    adjusted_months = {total.month: total for total in adjusted.months}
    source_months = {total.month: total for total in source.months}
    category_rows = [
        {
            "label": category,
            "cells": [cell(cells.get((category, month)), month) for month in months],
            "ytd": format_money(
                sum((cells.get((category, month), _ZERO) for month in months), _ZERO)
            ),
        }
        for category in categories
    ]

    def total_row(
        label: str, values: Mapping[date, Any], attr: str, ytd: Decimal
    ) -> dict[str, Any]:
        return {
            "label": label,
            "cells": [cell(getattr(values[m], attr) if m in values else None, m) for m in months],
            "ytd": format_money(ytd),
        }

    adjustment_cells = []
    for month in months:
        before = source_months[month].net if month in source_months else _ZERO
        after = adjusted_months[month].net if month in adjusted_months else _ZERO
        adjustment_cells.append({"text": format_money(after - before), "kind": "value"})
    return {
        "months": [f"{_MONTHS[m.month - 1][:3]} {m.year}" for m in months],
        "category_rows": category_rows,
        "total_rows": [
            total_row("Income", adjusted_months, "income", adjusted.income),
            total_row("Expenses", adjusted_months, "expense", adjusted.expense),
            total_row("Net", adjusted_months, "net", adjusted.net),
        ],
        "source_row": total_row("Source net (CFO view)", source_months, "net", source.net),
        "adjustment_row": {
            "label": "Adjustments",
            "cells": adjustment_cells,
            "ytd": format_money(adjusted.net - source.net),
        },
        "complete": adjusted.complete,
        "uncovered_months": sum(1 for month in months if not covered[month]),
        "walk": [
            {
                "label": label,
                "source": format_money(getattr(source, attr)),
                "delta": format_money(getattr(adjusted, attr) - getattr(source, attr)),
                "adjusted": format_money(getattr(adjusted, attr)),
                "total": attr == "net",
            }
            for label, attr in (("Income", "income"), ("Expenses", "expense"), ("Net", "net"))
        ],
        "control": _humanize(report.pnl_control_status),
        "bridges": [
            _bridge(report.bridge("calendar_source_scope")),
            _bridge(report.bridge("calendar_adjustments")),
            _bridge(report.bridge("calendar_to_school")),
        ],
    }


_BASES: Mapping[str, str] = {
    _REIMBURSEMENT: (
        "Reimbursement items by their own expense date; payments by the ticket payment date; "
        "the queue keeps every unsettled request whatever its dates."
    ),
    _BUDGET: (
        "Adopted school-year targets beside the adjusted CFO bank view (bank DATE, monthly "
        "category nets) crosswalked to budget categories."
    ),
    _FUNDRAISING: (
        "Processor activity by payment date: gross, fees, refunds and net, each movement "
        "counted once. Shown beside, never added to, the bank view."
    ),
    _PNL: (
        "CFO bank view by bank DATE: the sign of each monthly category net decides income or "
        "expense; Internal Transfer is excluded. Source totals, our recorded adjustments and "
        "adjusted totals are shown separately."
    ),
}


# --------------------------------------------------------------------------------------
# Production entry point
# --------------------------------------------------------------------------------------


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render(environment: Environment, template: str, **values: Any) -> str:
    return environment.get_template(f"main_reports/{template}").render(**values).rstrip() + "\n"


def _artifact(run_dir: Path, name: str, media_type: str) -> Artifact:
    payload = (run_dir / name).read_bytes()
    return Artifact(
        path=name,
        media_type=media_type,
        byte_length=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _check_run_dir(run_dir: Path) -> None:
    """A run directory is written once (spec D3): it must exist and hold no rendered output."""
    if not run_dir.is_dir():
        raise RenderError(_RUN_DIR_INVALID, "the run directory does not exist")
    taken = sum(1 for name in OUTPUT_NAMES if os.path.lexists(run_dir / name))
    staged = sum(1 for entry in run_dir.iterdir() if entry.name.startswith(STAGING_PREFIX))
    if taken or staged:
        raise RenderError(
            _RUN_DIR_NOT_EMPTY,
            f"the run directory already holds {taken} output file(s) and {staged} staging "
            "folder(s); render each run into a fresh directory",
        )


def _publish(source: Path, target: Path) -> None:
    """Move one complete staged file into the run directory."""
    os.replace(source, target)


def _withdraw(path: Path) -> None:
    """Remove one file this call already moved into the run directory."""
    path.unlink()


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path)


def _remove_staging(staging: Path) -> bool:
    """Remove the staging folder, retrying briefly (a scanner can hold a file open)."""
    for attempt in range(_STAGING_ATTEMPTS):
        try:
            _remove_tree(staging)
        except FileNotFoundError:
            return True
        except OSError:
            if attempt + 1 < _STAGING_ATTEMPTS:
                time.sleep(0.2 * (attempt + 1))
        else:
            return True
    return not os.path.lexists(staging)


def _move_into(staging: Path, run_dir: Path, names: Sequence[str]) -> None:
    """Move ``names`` (index last) into ``run_dir``; on failure withdraw what was moved."""
    moved: list[str] = []
    try:
        for name in names:
            _publish(staging / name, run_dir / name)
            moved.append(name)
    except OSError:
        left = 0
        for name in reversed(moved):
            try:
                _withdraw(run_dir / name)
            except OSError:
                left += 1
        if left:
            raise RenderError(
                _OUTPUT_INCOMPLETE,
                f"{left} file(s) of an incomplete set remain in the run directory; "
                "the run must not be published",
            ) from None
        raise RenderError(
            _OUTPUT_FAILED, "the rendered set could not be moved; nothing was published"
        ) from None


def write(
    report: ReportFacts,
    staged_bundle: Path,
    run_dir: Path,
    *,
    context: RenderContext,
    chromium_path: Path | None = None,
    sandbox: bool | None = None,
    exporter: Exporter | None = None,
) -> ArtifactSet:
    """Render all five reports, the summary PDF/PNG exports and the index into ``run_dir``.

    ``report`` comes from :func:`pta_finance.main_reports.facts.build_from`; ``staged_bundle``
    is the reimbursement bundle those facts were projected from (its receipt sidecar, if any,
    beside it); ``run_dir`` is the run's own fresh private directory; ``context`` carries the
    run ID and source freshness of the same captured input set. ``exporter`` replaces the
    headless Chromium export (:func:`~pta_finance.main_reports.export.export_documents` with
    ``chromium_path`` and ``sandbox``); it receives one job per summary, and its files get the
    same format checks as the real export's.

    Run directories are written once: one already holding any rendered output (or a staging
    folder) is refused with ``run_dir_not_empty`` before anything is written. All inputs are
    checked and every summary is rendered first; the queue, summaries, exports and index are
    then written into a fresh staging folder inside ``run_dir`` and moved into place with the
    index last. A failure before the moves leaves ``run_dir`` as it was. A failed move
    withdraws the files already moved (``output_failed``); if that is impossible it raises
    ``output_incomplete`` and the run must not be published. A staging folder that cannot be
    removed after a complete set is reported as ``staging_not_removed`` (do not publish
    either). ``ArtifactSet.export_sandboxed`` records whether the export used Chromium's
    sandbox. Raises :class:`RenderError` or
    :class:`~pta_finance.main_reports.export.ExportError`.
    """
    _check_run_dir(run_dir)
    _check_context(report, context)
    try:
        bundle = reimbursement_report.load_bundle(staged_bundle)
    except reimbursement_report.ReimbursementReportError:
        raise RenderError(_BUNDLE_INVALID, "the staged reimbursement bundle is invalid") from None
    _check_bundle(report, bundle)
    shared = _shared_totals(report, bundle)

    school, calendar = report.periods.school, report.periods.calendar
    builders: dict[str, tuple[Period, dict[str, Any]]] = {
        _REIMBURSEMENT: (school, _reimbursement_summary(report)),
        _BUDGET: (school, _budget_snapshot(report)),
        _FUNDRAISING: (school, _fundraising_summary(report)),
        _PNL: (calendar, _pnl_summary(report, context)),
    }
    environment = _environment()
    documents = {
        name: _render(
            environment,
            f"{name}.html.j2",
            page=_page(name, report, bundle, context, period, _BASES[name]),
            data=data,
            shared=shared,
        )
        for name, (period, data) in builders.items()
    }
    index = _render(
        environment,
        "index.html.j2",
        page=_index_page(report, bundle, context),
        links=_links(builders),
        shared=shared,
    )

    def run_export(jobs: Sequence[export.ExportJob]) -> bool | None:
        if exporter is not None:
            return exporter(jobs)
        return export.export_documents(jobs, executable=chromium_path, sandbox=sandbox)

    staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=run_dir))
    try:
        try:
            sandboxed = _write_set(report, staged_bundle, staging, documents, run_export)
            reimbursement_report.write_html_atomic(staging / INDEX_HTML, index)
        except OSError:
            raise RenderError(_OUTPUT_FAILED, "the rendered set could not be written") from None
        artifacts = tuple(_artifact(staging, name, _media_type(name)) for name in OUTPUT_NAMES)
        _move_into(staging, run_dir, OUTPUT_NAMES)
    except BaseException as exc:
        if not _remove_staging(staging):
            exc.add_note(f"private staging folder left behind: {staging.name}")
        raise
    if not _remove_staging(staging):
        raise RenderError(
            _STAGING_NOT_REMOVED,
            f"the set is complete but the private staging folder {staging.name} could not be "
            "removed; the run must not be published until it is",
        )
    return ArtifactSet(
        run_id=context.run_id,
        artifacts=tuple(sorted(artifacts, key=_path_of)),
        export_sandboxed=sandboxed,
    )


def _media_type(name: str) -> str:
    suffix = name.rsplit(".", 1)[1]
    return {"html": _HTML, "pdf": _PDF, "png": _PNG, "txt": _TEXT}[suffix]


def _path_of(artifact: Artifact) -> str:
    return artifact.path


def _write_set(
    report: ReportFacts,
    staged_bundle: Path,
    staging: Path,
    documents: Mapping[str, str],
    run_export: Exporter,
) -> bool | None:
    """Write the queue, its copy text, the summaries and their checked exports into
    ``staging``; returns whether the export used Chromium's sandbox."""
    try:
        built = reimbursement_report.build_report(staged_bundle, staging / QUEUE_HTML)
    except reimbursement_report.ReimbursementReportError:
        raise RenderError(
            _QUEUE_INVALID, "the reimbursement queue or its receipt sidecar is invalid"
        ) from None
    if built.summary.outstanding != report.reimbursements.outstanding:
        raise RenderError(_BUNDLE_MISMATCH, "the queue changed while the set was rendered")
    if built.text_output_path is None or built.text_output_path.name != QUEUE_COPY_TEXT:
        raise RenderError(_QUEUE_INVALID, "the queue copy text is missing")  # pragma: no cover
    for name, html in documents.items():
        reimbursement_report.write_html_atomic(staging / f"{name}.html", html)
    jobs = [
        export.ExportJob(
            html=staging / f"{name}.html",
            pdf=staging / f"{name}.pdf",
            png=staging / f"{name}.png",
        )
        for name in SUMMARY_NAMES
    ]
    sandboxed = run_export(jobs)
    export.verify_outputs(jobs)
    return sandboxed


def _links(builders: Mapping[str, tuple[Period, dict[str, Any]]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = [
        {
            "title": REPORT_TITLES[_QUEUE],
            "period": "All open requests, prior-year carryovers included",
            "html": QUEUE_HTML,
            "extras": [("Copy text", QUEUE_COPY_TEXT)],
        }
    ]
    for name in SUMMARY_NAMES:
        period = _period(builders[name][0])
        links.append(
            {
                "title": REPORT_TITLES[name],
                "period": f"{period['label']} ({period['range']})",
                "html": f"{name}.html",
                "extras": [("PDF", f"{name}.pdf"), ("PNG", f"{name}.png")],
            }
        )
    return links


def _index_page(
    report: ReportFacts, bundle: ReimbursementReport, context: RenderContext
) -> dict[str, Any]:
    school, calendar = report.periods.school, report.periods.calendar
    page = _page(_PNL, report, bundle, context, calendar, "")
    page.update(
        {
            "title": "Main Report Set",
            "period": {
                "label": f"{school.label} and {calendar.label}",
                "range": "school-year summaries and the calendar-year CFO P&L",
                "through": _long(report.as_of),
                "legacy": "",
            },
            "school": _period(school),
            "calendar": _period(calendar),
            "school_freshness": _freshness(report, context, school),
        }
    )
    return page
