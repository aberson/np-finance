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

:func:`pointer_page` renders the current-run pointer the runner publishes beside the runs
folder. Every page carries :data:`CONTENT_SECURITY_POLICY` and the identity tags from
:func:`run_id_meta` / :func:`input_set_meta`, which the runner checks before publishing.

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
import math
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from pta_finance import reimbursement_report
from pta_finance.main_reports import export, facts
from pta_finance.main_reports.models import (
    ARTIFACT_MEDIA_TYPES,
    BUDGET_ACTUAL_STATUSES,
    CARRYOVER_BASES,
    EXPENSE_BUCKETS,
    HEX_DIGEST_PATTERN,
    PAYMENT_JOIN_STATES,
    PERIOD_BASES,
    TRANSACTION_KINDS,
    VIEW_BASES,
    Artifact,
    ArtifactSet,
    BudgetLine,
    CaptureSet,
    CoverageStatus,
    Period,
    PnlMonthTotal,
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
    "SHORT_BRIDGE_TITLES",
    "ADOPTED_BUDGET_KIND",
    "RENDER_ERROR_CODES",
    "CONTENT_SECURITY_POLICY",
    "RUN_ID_META_NAME",
    "INPUT_SET_META_NAME",
    "RECORDS_LINK_DIR",
    "RECORD_LINKS",
    "POINTER_TEMPLATE",
    # functions
    "format_money",
    "format_whole",
    "pct",
    "largest_remainder",
    "year_elapsed",
    "plural",
    "truncate_label",
    "captured_label",
    "run_id_meta",
    "input_set_meta",
    "pointer_page",
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

# Every page's restrictive policy: no script, no network, inline styles and data: images only.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
    "form-action 'none'"
)
# Identity meta tags every rendered page (and the current-run pointer) carries.
RUN_ID_META_NAME = "pta-run-id"
INPUT_SET_META_NAME = "pta-input-set"
# The current-run pointer page published beside the runs folder.
POINTER_TEMPLATE = "pointer.html.j2"

# The run records the index links (written by the runner into the same run folder).
RECORDS_LINK_DIR = "records"
RECORD_LINKS: tuple[str, ...] = (
    "facts.json",
    "reconciliation.json",
    "adjusted-ledger.json",
    "journal.json",
)
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
_PRIOR, _CURRENT = EXPENSE_BUCKETS[:2]
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
_OBSERVED = BUDGET_ACTUAL_STATUSES[0]
_BUDGET_REASONS: Mapping[str, str] = {
    "ambiguous": "Unknown: category on two lines",
    "crosswalk_missing": "Unknown: no crosswalk",
    "category_unmapped": "Unknown: no source category",
    "coverage_partial": "Unknown: coverage partial",
}
_UNTYPED_REASON = "Unknown: not income/expense"
# A blank adopted line type (shown in the narrow Type column).
_BLANK_TYPE = "Blank"
if {*_BUDGET_REASONS, _OBSERVED} != set(BUDGET_ACTUAL_STATUSES):  # pragma: no cover
    raise RuntimeError("render budget reasons must match BUDGET_ACTUAL_STATUSES")
if _COVERAGE_LIMIT != "coverage_partial":  # pragma: no cover - import-time invariant
    raise RuntimeError("render must read the fundraising coverage limit from facts")
# One-page board design (docs/plan-reference/main-report-design.md): display constants.
_ONE = Decimal(1)
_TENTH = Decimal("0.1")
_DASH = "–"
# ``data-state`` of a dash cell: no declared bank coverage, or no readable amount.
_UNCOVERED_STATE = "uncovered"
_UNKNOWN_STATE = "unknown"
# Categorical palette in rank order, then the "Other" remainder; green is never a category.
_SEA, _INK_3, _SUN, _CLR, _LINE, _GO = (
    "#147d83",
    "#71838d",
    "#edb528",
    "#8a5716",
    "#ccd9d6",
    "#236c48",
)
_PALETTE = (_SEA, _INK_3, _SUN, _CLR)
_METER_WIDTH = 365
# Character limits of truncated labels (the full label goes in a title attribute).
_FIRST_COLUMN = 34
_BAR_LABEL = 22
_MATRIX_LABEL = 34
# One-line widths (ems) of chart labels.
_BAR_EMS = 11.0
_CAT_EMS = 17.0
# One-line widths (ems) of table cells, from each column's share of the 729.6 px sheet.
_TABLE_EMS = 16.0
_INPUT_EMS = 12.0
_TYPE_EMS = 5.0
_BUDGET_CATEGORY_EMS = 11.5
_STATUS_EMS = 18.0
_MEASURE_EMS = 21.0
_MATRIX_EMS = 18.0
_NARRATIVE_EMS = 12.0
# The organization's share of the one-line masthead eyebrow, beside " · Private Main Report Set".
_EYEBROW_EMS = 33.0
# The eyebrow is bold (glyphs about 12% wider than _ems estimates) and tracked: the 0.105
# em per character is the ``.eyebrow{letter-spacing:.105em}`` token in style.css.j2.
_EYEBROW_BOLD = 1.12
_EYEBROW_TRACKING = 0.105
_FOLLOWUP_EMS = 26.0
# Row caps: every list on a brief is bounded, so a page's height is bounded by construction.
_OPEN_REQUEST_ROWS = 4
_INCOME_ROWS = 7
_BUDGET_ROWS = 4
_PNL_ROWS = 4
# Of those rows, how many each side (income, expenses) keeps before the other fills in.
_PNL_SIDE_ROWS = 1
# Body rows per landscape appendix page (§ 3.4): the matrix is cut into pages of this size.
_APPENDIX_ROWS = 40
_ROUTE_ROWS = 4
_TOP_SEGMENTS = 4
_FOLLOWUP_LIMIT = 4
# The Budget Snapshot carries one more section (progress meters), so fewer follow-ups.
_BUDGET_FOLLOWUPS = 2
_CLARIFY = "C"
if _CLARIFY not in STATUS_META:  # pragma: no cover - import-time invariant
    raise RuntimeError("render must name a reimbursement status the queue knows")
_MATCHED = PAYMENT_JOIN_STATES[0]
_INDEX = "index"
_CARRYOVER_CHIPS: Mapping[str, str] = {
    CARRYOVER_BASES[0]: "By expense date",
    CARRYOVER_BASES[1]: "By submission",
}
SHORT_BRIDGE_TITLES: Mapping[str, str] = {
    "school_source_scope": "Source months → school year",
    "calendar_source_scope": "Source months → calendar year",
    "school_adjustments": "Source view → adjusted view",
    "calendar_adjustments": "Source view → adjusted view",
    "calendar_to_school": "Calendar year → school year",
    "school_expense_basis": "Bank basis → expense basis",
    "school_budget_crosswalk": "Adjusted net → budget lines",
    "school_payment_timing": "Expense dates → payment dates",
}
if set(SHORT_BRIDGE_TITLES) != set(facts.BRIDGE_NAMES):  # pragma: no cover - import-time
    raise RuntimeError("render short bridge titles must match facts.BRIDGE_NAMES")
# The bridges each page reports in its audit line (the index reports all of them).
_PAGE_BRIDGES: Mapping[str, tuple[str, ...]] = {
    _REIMBURSEMENT: ("school_payment_timing", "school_expense_basis"),
    _BUDGET: ("school_source_scope", "school_adjustments", "school_budget_crosswalk"),
    _FUNDRAISING: (),
    _PNL: ("calendar_source_scope", "calendar_adjustments", "calendar_to_school"),
    _INDEX: facts.BRIDGE_NAMES,
}
_PAGES_LABELS: Mapping[str, str] = {_PNL: "1 page + appendix", _INDEX: ""}
# "Can we measure it yet?" per budget actual status (Fundraising Summary income lines).
_MEASURE: Mapping[str, str] = {
    "observed": "Yes · bank, crosswalked",
    "coverage_partial": "In part · bank coverage incomplete",
    "crosswalk_missing": "Not yet · no category crosswalk",
    "category_unmapped": "Not yet · no source category maps here",
    "ambiguous": "Not yet · more than one adopted line",
}
if set(_MEASURE) != set(BUDGET_ACTUAL_STATUSES):  # pragma: no cover - import-time invariant
    raise RuntimeError("render measure texts must match BUDGET_ACTUAL_STATUSES")
_PROCESSOR_EXCLUDED = "processor_rows_excluded"
_PROCESSOR_COVERAGE = "processor_coverage_partial"
_PROCESSOR_EXCLUDING = "processor_rows_excluded_reported"
# Flags that explain a page's unknown cells, shown before larger counts.
_FIRST_FOLLOWUPS = frozenset(
    {"crosswalk_absent", "school_coverage_partial", "bank_coverage_absent"}
)
_PROCESSOR_FLAGS = ("processor_gross_unsettled", "processor_view_inconsistent")
# A processor's incomplete reason as the follow-up code it is reported under.
_REASON_CODES: Mapping[str, str] = {
    "coverage_partial": _PROCESSOR_COVERAGE,
    "rows_excluded": _PROCESSOR_EXCLUDED,
}
# Data follow-up reader text (title, line) by issue or flag code; ``{n}`` is the count.
_FOLLOWUPS: Mapping[str, tuple[str, str]] = {
    "reimbursement_item_undated": (
        "Items without an expense date",
        "{n} item(s) have no expense date; they stay undated and are never assigned a year.",
    ),
    "reimbursement_item_unpriced": (
        "Items without an amount",
        "{n} item(s) have no amount; they are counted, never shown as $0.",
    ),
    "reimbursement_payment_undated": (
        "Payments without a date",
        "{n} recorded payment(s) have no payment date.",
    ),
    "reimbursement_payment_unmatched": (
        "Payments not found in the bank",
        "{n} recorded payment(s) have no matching bank row yet.",
    ),
    "reimbursement_payment_ambiguous": (
        "Payments with several bank matches",
        "{n} recorded payment(s) match more than one bank row.",
    ),
    "reimbursement_payment_no_reference": (
        "Payments without a reference",
        "{n} recorded payment(s) carry no reference to match.",
    ),
    "bundle_as_of_outside_period": (
        "Queue date outside the period",
        "The reimbursement queue's as-of date falls outside this period.",
    ),
    "budget_year_unreadable": (
        "Unreadable budget year",
        "{n} adopted row(s) have a fiscal year that cannot be read.",
    ),
    "budget_type_unrecognized": (
        "Line type not income or expense",
        "{n} line(s) are in neither target total.",
    ),
    "budget_amount_missing": (
        "Lines without a target",
        "{n} line(s) have no target; target totals are partial.",
    ),
    "budget_amount_unreadable": (
        "Unreadable targets",
        "{n} target(s) cannot be read; target totals are partial.",
    ),
    "budget_line_ambiguous": (
        "Category on more than one line",
        "{n} category(ies) have more than one adopted line.",
    ),
    "budget_actual_unknown": (
        "Lines with an unknown actual",
        "{n} line(s) have no comparable bank amount yet.",
    ),
    _PROCESSOR_EXCLUDED: (
        "Processor rows left out",
        "{n} conflicting processor row(s) are left out of every total.",
    ),
    "school_coverage_partial": (
        "Bank coverage incomplete",
        "Declared bank coverage does not span the whole period.",
    ),
    "calendar_coverage_partial": (
        "Bank coverage incomplete",
        "Declared bank coverage does not span the whole period.",
    ),
    "bank_coverage_absent": (
        "No bank coverage declared",
        "No declared bank coverage; bank totals are partial.",
    ),
    "pnl_control_mismatched": (
        "CFO P&L control check",
        "The control check against the CFO P&L is mismatched.",
    ),
    "pnl_control_unverified": (
        "CFO P&L control check",
        "The control check against the CFO P&L is unverified.",
    ),
    "pnl_control_absent": (
        "CFO P&L control check",
        "The control check against the CFO P&L is absent.",
    ),
    "crosswalk_absent": (
        "No category crosswalk",
        "Budget actuals stay unknown until a crosswalk is configured.",
    ),
    "processor_gross_unsettled": (
        "Processor sales not yet paid out",
        "Some processor sales have not reached the bank yet.",
    ),
    "processor_view_inconsistent": (
        "Processor views disagree",
        "Two feeds of one processor disagree; its totals are incomplete.",
    ),
    _PROCESSOR_EXCLUDING: (
        "Processor rows left out",
        "{n} processor(s) left conflicting rows out of their totals.",
    ),
    _PROCESSOR_COVERAGE: (
        "Processor coverage incomplete",
        "{n} processor(s) have no declared coverage for the whole period.",
    ),
}
_FOLLOWUP_FALLBACK = "{n} occurrence(s); see records/facts.json."

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


def _whole(value: Decimal) -> int:
    """Exact cents rounded once, half up, to whole dollars (display only)."""
    return int(Decimal(money_str(value)).quantize(_ONE, rounding=ROUND_HALF_UP))


def _dollars(whole: int) -> str:
    return f"{'-' if whole < 0 else ''}${abs(whole):,}"


def format_whole(value: Decimal | None) -> str:
    """Whole dollars as ``$1,234`` / ``-$1,234`` / ``$0``; ``None`` (unknown) as ``Unknown``.

    Display only: every sum is taken in exact cents first and rounded once, half up, here.
    """
    if value is None:
        return _UNKNOWN
    return _dollars(_whole(value))


def _half_up(value: Decimal) -> int:
    return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def pct(part: Decimal | int | None, whole: Decimal | int | None, *, share: bool = False) -> str:
    """A whole percent of ``part`` in ``whole`` for display.

    Unknown or non-positive ``whole`` is ``–``; ``part <= 0`` is ``0%``; below one percent is
    ``<1%``; below 100 it never rounds up to 100 (at most ``99%``); at or above 100 it is
    ``100%+`` for "of target" uses and the rounded percent for ``share`` uses.
    """
    if part is None or whole is None or whole <= 0:
        return _DASH
    if part <= 0:
        return "0%"
    exact = Decimal(part) * 100 / Decimal(whole)
    if exact < 1:
        return "<1%"
    if exact < 100:
        return f"{min(_half_up(exact), 99)}%"
    return f"{_half_up(exact)}%" if share else "100%+"


def largest_remainder(weights: Sequence[Decimal | int], total: int) -> list[int]:
    """Whole units of ``total`` shared in proportion to ``weights`` (negatives count as 0).

    The parts always sum to exactly ``total`` (or are all 0 when no weight is positive);
    remainders are assigned largest first, ties in input order.
    """
    clipped = [max(Decimal(weight), _ZERO) for weight in weights]
    whole = sum(clipped, _ZERO)
    if whole <= 0:
        return [0] * len(clipped)
    raw = [weight * total / whole for weight in clipped]
    parts = [int(value) for value in raw]
    order = sorted(range(len(raw)), key=lambda index: (parts[index] - raw[index], index))
    for index in order[: total - sum(parts)]:
        parts[index] += 1
    return parts


def year_elapsed(period: Period) -> tuple[Decimal, int]:
    """How much of the period has passed on its as-of date: (exact percent, whole percent)."""
    span = (period.end_exclusive - period.start).days
    days = (min(period.as_of, period.end_inclusive) - period.start).days + 1
    exact = Decimal(100 * min(max(days, 0), span)) / Decimal(span)
    return exact, _half_up(exact)


def plural(count: int, one: str, many: str) -> str:
    """``"1 request"`` / ``"2 requests"``."""
    return f"{count} {one if count == 1 else many}"


def truncate_label(label: str, limit: int) -> str:
    """``label`` cut to ``limit`` characters with an ellipsis (the full text goes in a title)."""
    return label if len(label) <= limit else label[: limit - 1] + "…"


def _ems(text: str) -> float:
    """A generous estimate of ``text``'s rendered width in ems (wide glyphs counted wide)."""
    width = 0.0
    for char in text:
        if char in "WMwm@%":
            width += 1.0
        elif char.isupper() or char.isdigit() or char in "&#$?":
            width += 0.68
        elif char.islower():
            width += 0.56
        elif char.isspace():
            width += 0.3
        elif char.isascii():
            width += 0.5
        else:
            width += 1.0
    return width


def _fit(label: str, limit: int, ems: float) -> str:
    """``label`` truncated to ``limit`` characters and, further, to one line of ``ems``."""
    text = truncate_label(label, limit)
    if _ems(text) <= ems:
        return text
    cut = min(len(label), limit - 1)
    while cut > 1 and _ems(label[:cut] + "…") > ems:
        cut -= 1
    return label[:cut] + "…"


def _eyebrow_ems(text: str) -> float:
    """Estimated width of ``text`` in the masthead eyebrow (uppercase, bold, tracked)."""
    return _ems(text.upper()) * _EYEBROW_BOLD + _EYEBROW_TRACKING * len(text)


def _eyebrow(organization: str) -> str:
    """The organization as one masthead line: cut with an ellipsis to the eyebrow's width
    (the full name stays in a title attribute), so the masthead height never grows."""
    if _eyebrow_ems(organization) <= _EYEBROW_EMS:
        return organization
    cut = len(organization)
    while cut > 1 and _eyebrow_ems(organization[:cut] + "…") > _EYEBROW_EMS:
        cut -= 1
    return organization[:cut].rstrip() + "…"


def _lower_first(text: str) -> str:
    """``School year 2030–31`` as it reads mid-sentence."""
    return text[:1].lower() + text[1:]


def _label(label: str, limit: int, ems: float) -> dict[str, str]:
    """A table or chart label kept to one line; the full text goes in a title attribute."""
    text = _fit(label, limit, ems)
    return {"text": text, "title": "" if text == label else label}


def captured_label(times: Iterable[datetime]) -> str:
    """When the inputs were read, in UTC: one minute, a range within one day, or two stamps."""
    stamps = sorted(_utc(value) for value in times)
    if not stamps:
        return _NOT_RECORDED
    first, last = stamps[0], stamps[-1]
    if f"{first:%Y-%m-%d %H:%M}" == f"{last:%Y-%m-%d %H:%M}":
        return f"{first:%Y-%m-%d %H:%M} UTC"
    if first.date() == last.date():
        return f"{first:%Y-%m-%d %H:%M}–{last:%H:%M} UTC"
    return f"{first:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M} UTC"


def _iso(value: date | None) -> str:
    return _NOT_RECORDED if value is None else value.isoformat()


def _long(value: date) -> str:
    return f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"


def _medium(value: date) -> str:
    return f"{_MONTHS[value.month - 1][:3]} {value.day}, {value.year}"


def _short(value: date) -> str:
    return f"{_MONTHS[value.month - 1][:3]} {value.day}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise RenderError(_CONTEXT_INVALID, "a capture time is not timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return f"{_utc(value):%Y-%m-%d %H:%M} UTC"


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
# Charts (deterministic geometry; the templates only print it)
# --------------------------------------------------------------------------------------


def _num(value: float) -> str:
    """One-decimal SVG/CSS number without a negative zero."""
    text = f"{value:.1f}"
    return "0.0" if text == "-0.0" else text


def _pie(first: int, second: int) -> dict[str, Any]:
    """Two-part share: a full disc for the first part and a wedge for the second (§ 1.7).

    The legend percents follow :func:`pct` share rules, so a part that exists never reads
    ``0%`` and a part short of the whole never reads ``100%``.
    """
    total = first + second
    base = _SEA if first > 0 else (_SUN if total else _LINE)
    wedge = ""
    if total and 0 < second < total:
        fraction = second / total
        angle = -math.pi / 2 + 2 * math.pi * fraction
        x, y = 80 + 68 * math.cos(angle), 80 + 68 * math.sin(angle)
        large = 1 if fraction > 0.5 else 0
        wedge = f"M 80 80 L 80 12 A 68 68 0 {large} 1 {x:.4f} {y:.4f} Z"
    return {
        "base": base,
        "wedge": wedge,
        "first": first,
        "second": second,
        "first_pct": pct(first, total, share=True) if total else None,
        "second_pct": pct(second, total, share=True) if total else None,
    }


def _meter(
    amount: Decimal,
    target: Decimal | None,
    period: Period,
    verb: str,
    fill: str,
    ident: str,
    *,
    partial: bool = False,
    target_partial: bool = False,
) -> dict[str, Any]:
    """Amount toward a target with a marker for how much of the period has passed (§ 1.7).

    ``partial`` (bank coverage incomplete) stars the amount, ``target_partial`` (some adopted
    targets unreadable) stars the target; either stars the percent of target.
    """
    star = "*" if partial else ""
    if target is None or target <= 0:
        return {"missing": True, "id": ident, "partial": partial or target_partial}
    ratio = float(min(amount / target, _ONE)) if amount > 0 else 0.0
    width = _METER_WIDTH * ratio
    exact, whole = year_elapsed(period)
    marker = _METER_WIDTH * float(exact) / 100
    top = f"{_short(min(period.as_of, period.end_inclusive))} · {whole}% of the year"
    estimate = len(top) * 9.5 * 0.53
    top_x = min(max(marker, estimate / 2 + 1), _METER_WIDTH - estimate / 2 - 1)
    if width <= 0:
        shape = ""
    elif width >= _METER_WIDTH:
        shape = "full"
    elif width < 4:
        shape = "rect"
    else:
        shape = "path"
    return {
        "missing": False,
        "id": ident,
        "fill": fill,
        "shape": shape,
        "width": _num(width),
        "path": f"M0 15 H{_num(width - 4)} a4 4 0 0 1 4 4 v6 a4 4 0 0 1 -4 4 H0 Z",
        "marker": _num(marker),
        "top": top,
        "top_x": _num(top_x),
        "left": f"{format_whole(amount)}{star} {verb}",
        "right": f"Target {format_whole(target)}{'*' if target_partial else ''}",
        "of_target": pct(amount, target),
        "partial": partial or target_partial,
        "desc": (
            f"{format_whole(amount)} {verb} of a {format_whole(target)} target "
            f"({pct(amount, target)})"
            + ("; bank coverage is incomplete, so this is partial" if partial else "")
            + f"; {whole}% of the period has passed."
        ),
    }


def _share_text(share: int, amount: Decimal) -> str:
    """A largest-remainder share; a positive amount never reads ``0%``."""
    return "<1%" if share == 0 and amount > 0 else f"{share}%"


# One bar row: label, amount (``None`` unknown) and whether the amount is partial.
_BarRow = tuple[str, Decimal | None, bool]


def _bar_rows(rows: Sequence[_BarRow]) -> list[dict[str, Any]]:
    """Label | bar | value rows on one common scale with whole-percent shares (§ 1.7)."""
    known = [max(amount, _ZERO) for _, amount, _ in rows if amount is not None]
    peak = max(known, default=_ZERO)
    shares = iter(largest_remainder(known, 100))
    result = []
    for label, amount, partial in rows:
        if amount is None:
            result.append(
                {
                    "label": _label(label, _BAR_LABEL, _BAR_EMS),
                    "width": "",
                    "value": _DASH,
                    "partial": False,
                }
            )
            continue
        share = next(shares)
        width = (
            (Decimal(100) * max(amount, _ZERO) / peak).quantize(_TENTH, rounding=ROUND_HALF_UP)
            if peak > 0
            else _ZERO
        )
        result.append(
            {
                "label": _label(label, _BAR_LABEL, _BAR_EMS),
                "width": f"{width:.1f}",
                "value": f"{format_whole(amount)} · {_share_text(share, amount)}",
                "partial": partial,
            }
        )
    return result


def _ranked(items: Sequence[tuple[str, Decimal]], keep: int) -> list[tuple[str, Decimal]]:
    """Largest first (ties by name); beyond ``keep`` the rest is summed into one Other."""
    ordered = sorted(items, key=lambda item: (-item[1], item[0]))
    if len(ordered) <= keep:
        return ordered
    rest = ordered[keep:]
    other = plural(len(rest), "category", "categories")
    return [*ordered[:keep], (f"Other ({other})", sum((a for _, a in rest), _ZERO))]


def _stack(
    segments: Sequence[tuple[str, Decimal]], *, partial: bool = False
) -> list[dict[str, Any]]:
    """A stacked bar of magnitudes: widths to one decimal summing to 100.0 (§ 1.7)."""
    amounts = [amount for _, amount in segments]
    widths = largest_remainder(amounts, 1000)
    shares = largest_remainder(amounts, 100)
    result = []
    for index, (label, amount) in enumerate(segments):
        other = index >= len(_PALETTE) or label.startswith("Other (")
        result.append(
            {
                "label": _label(label, _BAR_LABEL, _CAT_EMS),
                "colour": _LINE if other else _PALETTE[index],
                "width": f"{widths[index] / 10:.1f}",
                "amount": format_whole(amount),
                "share": _share_text(shares[index], amount),
                "partial": partial,
            }
        )
    return result


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


def _month_header(month: date, covered: bool) -> str:
    return _MONTHS[month.month - 1][:3] + ("" if covered else "*")


def _monthly_bars(
    months: Sequence[date], totals: Mapping[date, PnlMonthTotal], covered: Mapping[date, bool]
) -> dict[str, Any]:
    """Income above and expenses below one baseline, one slot per month (§ 1.7)."""
    slot = _METER_WIDTH / max(len(months), 1)
    bar = min(12.0, 0.32 * slot)
    peak = max(
        [float(t.income) for t in totals.values()]
        + [float(abs(t.expense)) for t in totals.values()]
        + [1.0]
    )
    scale = 56 / peak
    slots = []
    words = []
    for index, month in enumerate(months):
        centre = slot * (index + 0.5)
        total = totals.get(month)
        name = _MONTHS[month.month - 1][:3]
        if total is None and not covered[month]:
            slots.append({"x": _num(centre), "label": name + "*", "muted": True, "bars": []})
            words.append(f"{name} unknown")
            continue
        income = float(total.income) if total else 0.0
        expense = float(abs(total.expense)) if total else 0.0
        bars = []
        if income * scale > 0:
            bars.append(
                {
                    "x": _num(centre - bar - 1),
                    "y": _num(70 - income * scale),
                    "w": _num(bar),
                    "h": _num(income * scale),
                    "fill": _SEA,
                }
            )
        if expense * scale > 0:
            bars.append(
                {"x": _num(centre + 1), "y": "70", "w": _num(bar), "h": _num(expense * scale)}
                | {"fill": _SUN}
            )
        slots.append(
            {
                "x": _num(centre),
                "label": _month_header(month, covered[month]),
                "muted": False,
                "bars": bars,
            }
        )
        words.append(
            f"{name} income {format_whole(total.income if total else _ZERO)}, expenses "
            f"{format_whole(-(total.expense if total else _ZERO))}"
        )
    return {"slots": slots, "desc": "; ".join(words) + "."}


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
        return "No declared coverage"
    if status.complete:
        return "Complete for the period"
    gaps = "; ".join(f"{a.isoformat()} to {b.isoformat()} (exclusive)" for a, b in status.uncovered)
    return f"Partial: no declared coverage {gaps}"


def _freshness(report: ReportFacts, context: RenderContext) -> dict[str, Any]:
    """The index "Inputs" table: transaction feeds with both periods' coverage, and a
    sentence naming every other capture."""
    school, calendar = report.periods.school, report.periods.calendar
    feeds = []
    others = []
    for source in context.sources:
        if source.kind not in TRANSACTION_KINDS:
            others.append(source.label)
            continue
        statuses = (
            _status_for(report, source.label, school),
            _status_for(report, source.label, calendar),
        )
        feeds.append(
            {
                "label": _label(source.label, _FIRST_COLUMN, _INPUT_EMS),
                "kind": _humanize(source.kind),
                "captured": _timestamp(source.captured_at),
                "school": _coverage_text(statuses[0]),
                "calendar": _coverage_text(statuses[1]),
                "partial": [status is None or not status.complete for status in statuses],
            }
        )
    return {"feeds": feeds, "others": others}


def _residual_text(value: Decimal) -> str:
    """A bridge residual in whole dollars, or in cents when a nonzero residual rounds to $0."""
    if value != 0 and _whole(value) == 0:
        return format_money(value)
    return format_whole(value)


def _audit(report: ReportFacts, names: Sequence[str]) -> dict[str, Any]:
    """Counts plus a pointer to the run records (§ 4); never lists."""
    bridges = [report.bridge(name) for name in names]
    return {
        "applied": len(report.applied_adjustments),
        "pending": len(report.pending_adjustments),
        "superseded": len(report.superseded_adjustments),
        "warnings": len(report.adjustment_warnings),
        "discrepancies": len(report.discrepancy_ids),
        "findings": sum(issue.count for issue in report.issues),
        "flags": len(report.coverage_flags),
        "bridges": len(bridges),
        "balanced": sum(1 for bridge in bridges if bridge.balanced),
        "residuals": [
            {
                "title": SHORT_BRIDGE_TITLES[bridge.name],
                "residual": _residual_text(bridge.residual),
            }
            for bridge in bridges
            if not bridge.balanced
        ],
    }


def _followup(code: str, count: int) -> dict[str, Any]:
    title, line = _FOLLOWUPS.get(code, (_humanize(code), _FOLLOWUP_FALLBACK))
    return {
        "code": code,
        "count": count,
        "title": _fit(title, _FIRST_COLUMN + 20, _FOLLOWUP_EMS),
        "line": line.format(n=count),
    }


def _followups(report: ReportFacts, name: str) -> list[dict[str, Any]]:
    """Reader-text cards for one summary, by count then code (§ 4); the page shows at most
    four. On the Budget Snapshot the coverage and crosswalk flags, which explain its dashes,
    come first."""
    counts: dict[str, int] = defaultdict(int)
    if name == _REIMBURSEMENT:
        for issue in report.issues:
            if (
                issue.code.startswith("reimbursement_")
                or issue.code == "bundle_as_of_outside_period"
            ):
                counts[issue.code] += issue.count
    elif name == _BUDGET:
        for issue in report.issues:
            if issue.code.startswith("budget_"):
                counts[issue.code] += issue.count
        for flag in report.coverage_flags:
            if flag.code in ("crosswalk_absent", "school_coverage_partial", "bank_coverage_absent"):
                counts[flag.code] += flag.count
    elif name == _FUNDRAISING:
        for issue in report.issues:
            if issue.code == _PROCESSOR_EXCLUDED:
                counts[issue.code] += issue.count
        for flag in report.coverage_flags:
            if flag.code in _PROCESSOR_FLAGS:
                counts[flag.code] += flag.count
        reasons: dict[str, int] = defaultdict(int)
        for item in report.fundraising:
            for reason in item.incomplete_reasons:
                reasons[_REASON_CODES.get(reason, reason)] += 1
        for code, count in reasons.items():
            if code == _PROCESSOR_EXCLUDED:  # a processor count, not a row count
                if code not in counts:
                    counts[_PROCESSOR_EXCLUDING] = count
                continue
            counts[code] = max(counts.get(code, 0), count)
    cards = [_followup(code, count) for code, count in counts.items()]
    cards.sort(
        key=lambda card: (card["code"] not in _FIRST_FOLLOWUPS, -card["count"], card["code"])
    )
    return cards


def _tile(
    value: str,
    label: str,
    *,
    state: str = "",
    note: str = "",
    partial: bool = False,
) -> dict[str, str]:
    numeric = bool(value) and (value[0] in "$-–0123456789<" or value.endswith("%"))
    classes = [] if numeric else ["word"]
    if partial:
        classes.append("partial")
    return {"value": value, "label": label, "state": state, "note": note, "cls": " ".join(classes)}


def _cell(
    value: Decimal | None, *, missing: str = _UNKNOWN_STATE, partial: bool = False
) -> dict[str, Any]:
    """A table amount: whole dollars, ``$0`` as an observed zero, the dash when unknown."""
    if value is None:
        return {"text": _DASH, "state": missing, "partial": False, "zero": False}
    return {
        "text": format_whole(value),
        "state": "",
        "partial": partial,
        "zero": value == 0,
    }


def _coverage_clause(report: ReportFacts, context: RenderContext, period: Period) -> str:
    banks = [source.label for source in context.sources if source.kind == _BANK]
    if not banks:
        return "No bank coverage declared; see the index"
    partial = sum(
        1
        for alias in banks
        if (status := _status_for(report, alias, period)) is None or not status.complete
    )
    if not partial:
        return "Bank coverage complete for the period"
    return f"Bank coverage partial for {plural(partial, 'source', 'sources')}; see the index"


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
            "whole": format_whole(school.net),
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
            "whole": format_whole(calendar.net),
            "partial": not calendar.complete,
            "reports": [REPORT_TITLES[_PNL]],
        },
        "outstanding": {
            "label": "Approved and not yet paid (all open requests)",
            "value": format_money(reimbursements.outstanding),
            "whole": format_whole(reimbursements.outstanding),
            "partial": False,
            "reports": [REPORT_TITLES[_REIMBURSEMENT], REPORT_TITLES[_QUEUE]],
        },
        "paid": {
            "label": f"Reimbursements paid in {report.periods.school.label}",
            "value": format_money(reimbursements.paid(_CURRENT)),
            "whole": format_whole(reimbursements.paid(_CURRENT)),
            "partial": False,
            "reports": [REPORT_TITLES[_REIMBURSEMENT]],
        },
    }


def _scope_extra(name: str, report: ReportFacts) -> list[str]:
    """Scope-line clauses beyond period and basis: carryovers and adjustments."""
    if name == _REIMBURSEMENT:
        carry = sum(1 for entry in report.reimbursements.queue if entry.carryover)
        if carry:
            return [f"includes {plural(carry, 'prior-year carryover', 'prior-year carryovers')}"]
    if name == _PNL:
        applied = len(report.applied_adjustments)
        if not applied:
            return ["no adjustments recorded; figures equal the CFO workbook"]
        return [f"{plural(applied, 'adjustment', 'adjustments')} applied"]
    return []


def _page(
    name: str,
    report: ReportFacts,
    bundle: ReimbursementReport,
    context: RenderContext,
    period: Period,
) -> dict[str, Any]:
    settings = bundle.settings
    return {
        "name": name,
        "title": REPORT_TITLES.get(name, "Main Report Set"),
        "organization": settings.organization,
        "eyebrow": _eyebrow(settings.organization),
        "logo": settings.logo_data_uri,
        "period": _period(period),
        "basis": _BASES.get(name, ""),
        "scope_extra": _scope_extra(name, report),
        "as_of": _long(report.as_of),
        "run_id": context.run_id,
        "input_sha": context.input_sha256,
        "captured": captured_label(source.captured_at for source in context.sources),
        "coverage": _coverage_clause(report, context, period),
        "bundle": {"as_of": _long(report.reimbursements.bundle_as_of)},
        "reimbursement_backed": name in (_REIMBURSEMENT, _INDEX),
        "footnotes": list(_FOOTNOTES.get(name, ())),
        "pages_label": _PAGES_LABELS.get(name, "1 page"),
        "audit": _audit(report, _PAGE_BRIDGES.get(name, ())),
        "followups": _followups(report, name)[
            : _BUDGET_FOLLOWUPS if name == _BUDGET else _FOLLOWUP_LIMIT
        ],
        "followups_total": len(_followups(report, name)),
        "index": INDEX_HTML,
        "queue": QUEUE_HTML,
    }


# --------------------------------------------------------------------------------------
# Summaries (sections and facts mapping: docs/plan-reference/main-report-design.md § 3)
# --------------------------------------------------------------------------------------


def _queue_anchors(bundle: ReimbursementReport) -> dict[str, str]:
    """Queue card anchors by review key, only where the anchor is unique in the queue."""
    anchors = {
        ticket.review_key: (ticket.ref + ("-" + ticket.form_label if ticket.form_label else ""))
        .lower()
        .replace(" ", "-")
        for ticket in bundle.tickets
    }
    seen: dict[str, int] = defaultdict(int)
    for anchor in anchors.values():
        seen[anchor] += 1
    return {key: anchor for key, anchor in anchors.items() if seen[anchor] == 1}


def _reimbursement_summary(report: ReportFacts, bundle: ReimbursementReport) -> dict[str, Any]:
    data = report.reimbursements
    period = report.periods.school
    tracked = len({item.review_key for item in data.items} | {e.review_key for e in data.queue})
    still_open = len(data.queue)
    closed = tracked - still_open
    clarification = sum((data.open_amount(b, _CLARIFY) for b in EXPENSE_BUCKETS), _ZERO)
    unpriced = sum(t.unpriced for t in data.totals if t.open and t.status == _CLARIFY)
    carry = sum(1 for entry in data.queue if entry.carryover)
    paid = data.paid(_CURRENT)
    paid_requests = len({i.review_key for i in data.items if i.payment_bucket == _CURRENT})
    joins = [j for j in data.joins if period.position(j.payment_date) == _CURRENT]
    matched = sum(1 for join in joins if join.state == _MATCHED)
    unmatched = len(joins) - matched
    pie = _pie(closed, still_open)

    anchors = _queue_anchors(bundle)
    ordered = sorted(data.queue, key=lambda e: (-e.pay_now, e.submitted, e.ticket_ref))
    shown, rest = ordered[:_OPEN_REQUEST_ROWS], ordered[_OPEN_REQUEST_ROWS:]
    rows = [
        {
            "ref": _label(entry.ticket_ref, _FIRST_COLUMN, _TABLE_EMS),
            "anchor": quote(anchors[entry.review_key], safe="")
            if entry.review_key in anchors
            else "",
            "submitted": _iso(entry.submitted),
            "earliest": _medium(entry.earliest_expense_date)
            if entry.earliest_expense_date
            else _NOT_RECORDED,
            "undated": entry.undated_items,
            "pay_now": _cell(entry.pay_now),
            "carryover": _CARRYOVER_CHIPS.get(entry.carryover_basis or "", ""),
        }
        for entry in shown
    ]

    tiles = [
        _tile(str(tracked), "Requests tracked"),
        _tile(str(closed), "Closed", state="closed"),
        _tile(str(still_open), "Still open", state="open"),
        _tile(
            format_whole(clarification),
            "Needs clarification",
            state="amount",
            note=f"{plural(unpriced, 'item', 'items')} without an amount" if unpriced else "",
        ),
    ]
    sentence = (
        f"{plural(tracked, 'request is', 'requests are')} tracked for "
        f"{_lower_first(period.label)}: "
        f"{closed} closed and {still_open} open"
    )
    if carry:
        sentence += (
            f", {carry} of them "
            f"{'a prior-year carryover' if carry == 1 else 'prior-year carryovers'}"
        )
    sentence += (
        f". {format_whole(paid)} was paid in the period across "
        f"{plural(paid_requests, 'request', 'requests')}; "
    )
    if joins:
        sentence += (
            f"{matched} of {plural(len(joins), 'payment', 'payments')} "
            f"{'matches' if matched == 1 else 'match'} a bank row. "
        )
    else:
        sentence += "no recorded payment in the period awaits a bank match. "
    sentence += f"{format_whole(data.outstanding)} is approved and not yet paid"
    if clarification > 0:
        sentence += f", and {format_whole(clarification)} needs clarification"
    return {
        "tiles": tiles,
        "pie": pie,
        "closed": closed,
        "open": still_open,
        "pie_title": f"{pie['first_pct']} of requests are closed"
        if pie["first_pct"] is not None
        else "No requests are tracked",
        "paid": format_whole(paid),
        "paid_requests": plural(paid_requests, "request", "requests"),
        "matched": matched,
        "unmatched": unmatched,
        "prior_paid": format_whole(data.paid(_CURRENT, _PRIOR)),
        "outstanding": format_whole(data.outstanding),
        "rows": rows,
        "other": {
            "text": f"{plural(len(rest), 'more open request', 'more open requests')} in the "
            "Reimbursement Queue",
            "pay_now": _cell(sum((entry.pay_now for entry in rest), _ZERO)),
        }
        if rest
        else None,
        "total": _cell(data.outstanding),
        "carry": carry,
        "narrative": sentence + ".",
    }


def _target(report: ReportFacts, line_type: str) -> tuple[Decimal | None, bool]:
    """Sum of the readable adopted targets of one line type, and whether any is unreadable."""
    lines = [line for line in report.budget.lines if line.line_type == line_type]
    known = [line.target for line in lines if line.target is not None]
    if not known:
        return None, bool(lines)
    return sum(known, _ZERO), len(known) != len(lines)


def _of_target(amount: Decimal, target: Decimal | None) -> str:
    return pct(amount, target) if target is not None and target > 0 else "an unknown share"


def _summed(values: Sequence[Decimal | None]) -> dict[str, Any]:
    """A table total: the exact sum of the known values (partial when some are unknown),
    or the dash when none is known; never an invented zero."""
    found = [value for value in values if value is not None]
    if not found:
        return _cell(None)
    return _cell(sum(found, _ZERO), partial=len(found) != len(values))


def _activity(line: BudgetLine) -> Decimal | None:
    """Money received (income) or spent (expense) on one adopted line; ``None`` if unknown."""
    if line.actual is None or line.line_type not in facts.BUDGET_LINE_TYPES:
        return None
    return line.actual if line.line_type == _INCOME else -line.actual


def _remaining(line: BudgetLine) -> Decimal | None:
    """Target less activity to date; ``None`` when either is unknown."""
    activity = _activity(line)
    return None if line.target is None or activity is None else line.target - activity


def _budget_snapshot(report: ReportFacts) -> dict[str, Any]:
    budget = report.budget
    period = report.periods.school
    school = report.view(_SCHOOL, _ADJUSTED_VIEW)
    partial = not school.complete
    income_target, income_partial = _target(report, _INCOME)
    expense_target, expense_partial = _target(report, _EXPENSE)
    spent = -school.expense
    unknown = sum(1 for line in budget.lines if line.actual is None)
    totals = school.category_totals()
    went = _ranked([(name, -amount) for name, amount in totals if amount < 0], _TOP_SEGMENTS)
    came = _ranked([(name, amount) for name, amount in totals if amount > 0], _TOP_SEGMENTS)
    _, year = year_elapsed(period)

    ordered = sorted(
        budget.lines,
        key=lambda line: (line.target is None, -(line.target or _ZERO), line.position),
    )
    shown, rest = ordered[:_BUDGET_ROWS], ordered[_BUDGET_ROWS:]
    rows = []
    for line in shown:
        typed = line.line_type in facts.BUDGET_LINE_TYPES
        activity: Decimal | None = None
        if line.actual is not None and typed:
            activity = line.actual if line.line_type == _INCOME else -line.actual
        remaining = (
            line.target - activity if line.target is not None and activity is not None else None
        )
        if line.actual is None:
            status = _BUDGET_REASONS[line.actual_status]
        elif not typed:
            status = _UNTYPED_REASON
        else:
            status = "Observed"
        rows.append(
            {
                "type": _label(
                    _humanize(line.line_type) if line.line_type else _BLANK_TYPE,
                    _FIRST_COLUMN,
                    _TYPE_EMS,
                ),
                "category": _label(line.category, _FIRST_COLUMN, _BUDGET_CATEGORY_EMS),
                "target": _cell(line.target),
                "activity": _cell(activity),
                "remaining": _cell(remaining),
                "status": _label(status, _FIRST_COLUMN, _STATUS_EMS),
                "unknown": activity is None,
            }
        )
    outside = sum((amount for _, amount in (*budget.unmapped, *budget.unbudgeted)), _ZERO)
    outside_count = len(budget.unmapped) + len(budget.unbudgeted)
    untyped = sum(1 for line in budget.lines if line.line_type not in facts.BUDGET_LINE_TYPES)
    note = (
        f"{plural(outside_count, 'line', 'lines')} outside the adopted lines: "
        f"{format_whole(outside)} · "
        f"{plural(budget.other_year_rows, 'row', 'rows')} of other fiscal years · "
        f"{plural(untyped, 'line', 'lines')} neither income nor expense"
    )
    other = None
    if rest:
        kinds: dict[str, int] = defaultdict(int)
        for line in rest:
            kinds[line.line_type if line.line_type in facts.BUDGET_LINE_TYPES else "other"] += 1
        other = {
            "text": f"Other lines ({len(rest)})",
            "target": _summed([line.target for line in rest]),
            "activity": _summed([_activity(line) for line in rest]),
            "remaining": _summed([_remaining(line) for line in rest]),
            "meta": " · ".join(
                plural(kinds[kind], f"{kind} line", f"{kind} lines")
                for kind in (_INCOME, _EXPENSE, "other")
                if kinds[kind]
            ),
        }
    sentence = (
        f"So far in {_lower_first(period.label)}, the bank view shows "
        f"{format_whole(school.income)} received "
        f"and {format_whole(spent)} spent, a net of {format_whole(school.net)}"
        + (" (partial: bank coverage is incomplete)" if partial else "")
        + f". That is {_of_target(school.income, income_target)} of the adopted income target "
        f"and {_of_target(spent, expense_target)} of the adopted expense target, with {year}% "
        f"of the year elapsed. {plural(unknown, 'budget line has', 'budget lines have')} an "
        "unknown actual."
    )
    return {
        "tiles": [
            _tile(
                format_whole(school.income),
                "Received (bank basis)",
                state="closed",
                partial=partial,
            ),
            _tile(format_whole(spent), "Spent (bank basis)", state="spent", partial=partial),
            _tile(
                str(unknown),
                "Unknown actuals",
                state="open" if unknown else "",
                note=f"of {plural(len(budget.lines), 'adopted line', 'adopted lines')}",
            ),
            _tile(
                format_whole(school.net),
                f"{period.label} adjusted bank net",
                note="A change over the period, not a balance",
                partial=partial,
            ),
        ],
        "went": _stack(went, partial=partial),
        "came": _bar_rows([(name, amount, partial) for name, amount in came]),
        "income_meter": _meter(
            school.income,
            income_target,
            period,
            "received",
            _GO,
            "income-meter",
            partial=partial,
            target_partial=income_partial,
        ),
        "expense_meter": _meter(
            spent,
            expense_target,
            period,
            "spent",
            _CLR,
            "expense-meter",
            partial=partial,
            target_partial=expense_partial,
        ),
        "income_target_partial": income_partial,
        "expense_target_partial": expense_partial,
        "year": year,
        "crosswalk": "No category crosswalk"
        if budget.crosswalk_version is None
        else f"Crosswalk version {budget.crosswalk_version}",
        "rows": rows,
        "other": other,
        "note": note,
        "narrative": sentence,
    }


def _fundraising_summary(report: ReportFacts, context: RenderContext) -> dict[str, Any]:
    """Bank-basis income against the adopted income targets (D3) beside the processor view.

    A processor with no rows and no declared coverage for the period is unknown (a dash),
    never an invented $0.
    """
    period = report.periods.school
    school = report.view(_SCHOOL, _ADJUSTED_VIEW)
    partial = not school.complete
    received = school.income
    target, target_partial = _target(report, _INCOME)
    _, year = year_elapsed(period)

    processors = []
    for item in report.fundraising:
        moved = item.payment_count + item.fee_rows + item.refund_rows + item.excluded_rows
        unknown = _COVERAGE_LIMIT in item.incomplete_reasons and moved == 0
        processors.append((item, unknown))
    known = [item for item, unknown in processors if not unknown]
    no_rows = len(processors) - len(known)
    complete = sum(1 for item, _ in processors if item.complete)
    gross = sum((item.gross for item in known), _ZERO)
    fees = sum((item.fees for item in known), _ZERO)
    refunds = sum((item.refunds for item in known), _ZERO)
    net = sum((item.net for item in known), _ZERO)
    attributed = sum(
        (c.gross for item in known for c in item.categories if c.category is not None), _ZERO
    )
    not_attributed = sum(c.count for item in known for c in item.categories if c.category is None)
    # Any incomplete processor (unknown ones included) makes a combined processor figure partial.
    combined_partial = complete != len(processors)
    routes: list[_BarRow] = [
        (item.source_alias, None if unknown else item.gross, not item.complete)
        for item, unknown in processors
    ]
    if len(routes) > _ROUTE_ROWS:
        ranked = sorted(routes, key=lambda r: (r[1] is None, -(r[1] or _ZERO), r[0]))
        rest = ranked[_ROUTE_ROWS - 1 :]
        rest_known = [amount for _, amount, _ in rest if amount is not None]
        routes = [
            *ranked[: _ROUTE_ROWS - 1],
            (
                f"Other ({plural(len(rest), 'processor', 'processors')})",
                sum(rest_known, _ZERO) if rest_known else None,
                any(flag for _, _, flag in rest),
            ),
        ]

    if target is None or target <= 0:
        of_target = _UNKNOWN
        gap_tile = _tile(_UNKNOWN, f"Still to reach the target by {_short(period.end_inclusive)}")
    else:
        of_target = pct(received, target)
        gap = _whole(target) - _whole(received)
        gap_tile = (
            _tile(
                _dollars(gap) if gap > 0 else "<$1",
                f"Still to reach the target by {_short(period.end_inclusive)}",
                state="amount",
                partial=partial or target_partial,
            )
            if received < target
            else _tile(
                "Target reached",
                f"Above target: {format_whole(received - target)}",
                state="closed",
                partial=partial or target_partial,
            )
        )
    months = []
    totals = {total.month: total for total in school.months}
    for month in _month_starts(period):
        covered = _month_covered(report, context, period, month)
        total = totals.get(month)
        months.append(
            {
                "name": _MONTHS[month.month - 1][:3],
                "text": format_whole(total.income if total else _ZERO)
                if total is not None or covered
                else _DASH,
                "partial": total is not None and not covered,
                "unknown": total is None and not covered,
            }
        )

    if not processors:
        processor_sentence = "No online processor is configured."
    else:
        processor_sentence = (
            f"Online processors recorded {format_whole(gross) if known else _UNKNOWN} gross and "
            f"{format_whole(net) if known else _UNKNOWN} after fees and refunds"
        )
        incomplete = len(processors) - complete
        if incomplete:
            processor_sentence += (
                f"; {incomplete} of {plural(len(processors), 'processor is', 'processors are')} "
                "incomplete"
            )
        processor_sentence += "."
    if target is None or target <= 0:
        target_clause = "with no readable adopted income target"
    else:
        target_clause = f"{of_target} of the {format_whole(target)} adopted income target" + (
            " (some adopted targets are unreadable)" if target_partial else ""
        )
    sentence = (
        f"{format_whole(received)} of income has reached the bank so far this school year"
        + (" (partial: bank coverage is incomplete)" if partial else "")
        + f", {target_clause}, with {year}% of the year elapsed. {processor_sentence}"
    )

    income_lines = [line for line in report.budget.lines if line.line_type == _INCOME]
    ordered = sorted(
        income_lines,
        key=lambda line: (line.target is None, -(line.target or _ZERO), line.position),
    )
    shown, rest_lines = ordered[:_INCOME_ROWS], ordered[_INCOME_ROWS:]

    def summed(values: Sequence[Decimal | None]) -> dict[str, Any]:
        found = [value for value in values if value is not None]
        if not found:
            return _cell(None)
        return _cell(sum(found, _ZERO), partial=len(found) != len(values))

    lines = [
        {
            "label": _label(line.category, _FIRST_COLUMN, _TABLE_EMS),
            "target": _cell(line.target),
            "received": _cell(line.actual),
            "measure": _label(
                _MEASURE.get(line.actual_status, _humanize(line.actual_status)),
                _FIRST_COLUMN + 10,
                _MEASURE_EMS,
            ),
        }
        for line in shown
    ]
    other_lines = (
        {
            "text": f"Other income lines ({len(rest_lines)})",
            "target": summed([line.target for line in rest_lines]),
            "received": summed([line.actual for line in rest_lines]),
        }
        if rest_lines
        else None
    )
    total_lines = {
        "target": summed([line.target for line in income_lines]),
        "received": summed([line.actual for line in income_lines]),
    }
    return {
        "tiles": [
            _tile(
                format_whole(received),
                f"Income received since {_short(period.start)}",
                state="closed",
                partial=partial,
            ),
            _tile(
                of_target,
                f"Of the {format_whole(target)} adopted income target"
                if target is not None and target > 0
                else "Of the adopted income target",
                partial=target is not None and target > 0 and (partial or target_partial),
            ),
            gap_tile,
            _tile(
                f"{complete} of {len(processors)}",
                "Processors complete",
                state="" if complete == len(processors) else "open",
                note=f"{no_rows} with no rows or coverage" if no_rows else "",
            ),
        ],
        "of_target": of_target,
        "target_known": target is not None and target > 0,
        "of_target_partial": partial or target_partial,
        "meter": _meter(
            received,
            target,
            period,
            "received",
            _GO,
            "income-meter",
            partial=partial,
            target_partial=target_partial,
        ),
        "months": months,
        "routes": _bar_rows(routes),
        "processors": len(processors),
        "combined_partial": combined_partial,
        "excluded": plural(no_rows, "processor", "processors") if no_rows else "",
        "fees": format_whole(fees) if known else _UNKNOWN,
        "refunds": format_whole(refunds) if known else _UNKNOWN,
        "net": format_whole(net) if known else _UNKNOWN,
        "attributed": pct(attributed, gross, share=True),
        "not_attributed": plural(not_attributed, "sale", "sales"),
        "lines": lines,
        "other": other_lines,
        "total": total_lines,
        "narrative": sentence,
    }


def _pnl_summary(report: ReportFacts, context: RenderContext) -> dict[str, Any]:
    period = report.periods.calendar
    source = report.view(_CALENDAR, _SOURCE_VIEW)
    adjusted = report.view(_CALENDAR, _ADJUSTED_VIEW)
    partial = not adjusted.complete
    months = _month_starts(period)
    covered = {month: _month_covered(report, context, period, month) for month in months}
    covered_count = sum(1 for month in months if covered[month])
    month_totals = {total.month: total for total in adjusted.months}
    source_months = {total.month: total for total in source.months}
    cells = {(cell.category, cell.month): cell.net for cell in adjusted.cells}
    active: dict[str, int] = defaultdict(int)
    for cell in adjusted.cells:
        if cell.net != 0:
            active[cell.category] += 1
    totals = adjusted.category_totals()

    def month_cell(value: Decimal | None, month: date) -> dict[str, Any]:
        if value is None:
            return _cell(_ZERO) if covered[month] else _cell(None, missing=_UNCOVERED_STATE)
        return _cell(value)

    # Page 1: the largest income and the largest expense categories by |year to date|.
    ranked = sorted(totals, key=lambda item: (-abs(item[1]), item[0]))
    picked = {
        name
        for side in (
            [n for n, a in ranked if a > 0][:_PNL_SIDE_ROWS],
            [n for n, a in ranked if a < 0][:_PNL_SIDE_ROWS],
        )
        for name in side
    }
    for name, _ in ranked:  # one side short: the other fills the remaining rows
        if len(picked) >= _PNL_ROWS:
            break
        picked.add(name)
    shown = [item for item in ranked if item[0] in picked]
    rest = [item for item in ranked if item[0] not in picked]
    top = [
        {
            "label": _label(name, _FIRST_COLUMN, _TABLE_EMS),
            "type": "Income" if amount > 0 else ("Expense" if amount < 0 else "Zero"),
            "ytd": _cell(amount, partial=partial),
            "share": pct(amount, adjusted.income, share=True)
            if amount > 0
            else pct(-amount, -adjusted.expense, share=True),
            "months": active[name],
        }
        for name, amount in shown
    ]
    other = (
        {
            "text": f"Other, net ({plural(len(rest), 'category', 'categories')})",
            "ytd": _cell(sum((amount for _, amount in rest), _ZERO), partial=partial),
        }
        if rest
        else None
    )

    bridges = []
    for name in _PAGE_BRIDGES[_PNL]:
        bridge = report.bridge(name)
        records = sum(
            len(row.refs) + len(row.adjustment_ids) + len(row.item_keys) for row in bridge.rows
        )
        bridges.append(
            {
                "name": name,
                "title": SHORT_BRIDGE_TITLES[name],
                "full": BRIDGE_TITLES[name],
                "from": format_whole(bridge.from_amount),
                "explained": format_whole(sum((row.amount for row in bridge.rows), _ZERO)),
                "residual": _residual_text(bridge.residual),
                "balanced": bridge.balanced,
                "records": records,
            }
        )
    balanced = sum(1 for bridge in bridges if bridge["balanced"])

    # Appendix: the monthly matrix, grouped income then expenses.
    def ytd(name: str) -> Decimal:
        return sum((cells.get((name, month), _ZERO) for month in months), _ZERO)

    by_ytd = sorted(
        {cell.category for cell in adjusted.cells}, key=lambda name: (-abs(ytd(name)), name)
    )

    def matrix_row(name: str) -> dict[str, Any]:
        return {
            "label": _label(name, _MATRIX_LABEL, _MATRIX_EMS),
            "cells": [month_cell(cells.get((name, month)), month) for month in months],
            "ytd": _cell(ytd(name), partial=partial),
        }

    def total_row(
        label: str, values: Mapping[date, PnlMonthTotal], attr: str, value: Decimal
    ) -> dict[str, Any]:
        return {
            "label": {"text": label, "title": ""},
            "cells": [
                month_cell(getattr(values[m], attr) if m in values else None, m) for m in months
            ],
            "ytd": _cell(value, partial=partial),
        }

    extra_rows = []
    if report.applied_adjustments or adjusted.net != source.net:
        extra_rows.append(total_row("Source net (CFO view)", source_months, "net", source.net))
        extra_rows.append(
            {
                "label": {"text": "Adjustments", "title": ""},
                "cells": [
                    _cell(
                        (month_totals[m].net if m in month_totals else _ZERO)
                        - (source_months[m].net if m in source_months else _ZERO)
                    )
                    for m in months
                ],
                "ytd": _cell(adjusted.net - source.net),
            }
        )

    largest_income = next(((n, a) for n, a in ranked if a > 0), None)
    largest_expense = next(((n, a) for n, a in ranked if a < 0), None)
    sentence = (
        f"Through {_long(min(period.as_of, period.end_inclusive))}, the calendar year shows "
        f"{format_whole(adjusted.income)} income, {format_whole(-adjusted.expense)} expenses "
        f"and a net of {format_whole(adjusted.net)}. "
    )
    if largest_income:
        sentence += (
            "The largest income category is "
            f"{_fit(largest_income[0], _BAR_LABEL, _NARRATIVE_EMS)} "
            f"({format_whole(largest_income[1])}); "
        )
    else:
        sentence += "There is no income category yet; "
    if largest_expense:
        sentence += (
            "the largest expense category is "
            f"{_fit(largest_expense[0], _BAR_LABEL, _NARRATIVE_EMS)} "
            f"({format_whole(-largest_expense[1])}). "
        )
    else:
        sentence += "there is no expense category yet. "
    sentence += (
        f"{covered_count} of {plural(len(months), 'month has', 'months have')} declared bank "
        "coverage"
        + ("; the others are unknown, not zero" if covered_count != len(months) else "")
        + "."
    )
    control = _humanize(report.pnl_control_status)
    return {
        "tiles": [
            _tile(format_whole(adjusted.income), "Income year to date", partial=partial),
            _tile(
                format_whole(-adjusted.expense),
                "Expenses year to date",
                state="spent",
                partial=partial,
            ),
            _tile(format_whole(adjusted.net), "Net year to date", partial=partial),
            _tile(
                f"{covered_count} of {len(months)}",
                "Months with declared bank coverage",
                state="" if covered_count == len(months) else "open",
                note=f"Control check: {control}",
            ),
        ],
        "bars": _monthly_bars(months, month_totals, covered),
        "balanced": balanced,
        "bridge_count": len(bridges),
        "control": control.lower(),
        "applied": len(report.applied_adjustments),
        "pending": len(report.pending_adjustments),
        "top": top,
        "other": other,
        "net": _cell(adjusted.net, partial=partial),
        "bridges": bridges,
        "headers": [_month_header(month, covered[month]) for month in months],
        "pages": _appendix_pages(
            [
                {"kind": "group", "label": {"text": "Income", "title": ""}},
                *({"kind": "row", **matrix_row(n)} for n in by_ytd if ytd(n) > 0),
                {"kind": "group", "label": {"text": "Expenses", "title": ""}},
                *({"kind": "row", **matrix_row(n)} for n in by_ytd if ytd(n) <= 0),
                {"kind": "total", **total_row("Income", month_totals, "income", adjusted.income)},
                {
                    "kind": "total",
                    **total_row("Expenses", month_totals, "expense", adjusted.expense),
                },
                {"kind": "total", **total_row("Net", month_totals, "net", adjusted.net)},
                *({"kind": "other", **row} for row in extra_rows),
            ]
        ),
        "narrative": sentence,
    }


def _appendix_pages(rows: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The matrix body cut into landscape pages of at most :data:`_APPENDIX_ROWS` rows, so
    the appendix runs to exactly ``ceil(rows / 40)`` pages and never a header-only page."""
    return [list(rows[i : i + _APPENDIX_ROWS]) for i in range(0, len(rows), _APPENDIX_ROWS)]


_BASES: Mapping[str, str] = {
    _REIMBURSEMENT: "items by their own expense date; payments by payment date",
    _BUDGET: "adopted targets beside the adjusted bank view",
    _FUNDRAISING: "processor activity by payment date; the bank view is shown separately",
    _PNL: "adjusted bank view by bank date; internal transfers excluded",
}
_FOOTNOTES: Mapping[str, tuple[str, ...]] = {
    _BUDGET: ("No calendar-year budget is derived from these annual targets.",),
    _PNL: ("Budgets are school-year targets; see the Budget Snapshot.",),
}


# --------------------------------------------------------------------------------------
# Production entry point
# --------------------------------------------------------------------------------------


def run_id_meta(run_id: str) -> Markup:
    """The exact ``<meta>`` tag naming a page's run (escaped)."""
    return Markup('<meta name="{}" content="{}">').format(RUN_ID_META_NAME, run_id)


def input_set_meta(input_sha256: str) -> Markup:
    """The exact ``<meta>`` tag naming the captured input set a page was rendered from."""
    return Markup('<meta name="{}" content="{}">').format(INPUT_SET_META_NAME, input_sha256)


def _environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.globals.update(
        csp=Markup(CONTENT_SECURITY_POLICY),
        run_id_meta=run_id_meta,
        input_set_meta=input_set_meta,
    )
    return environment


def _render(environment: Environment, template: str, **values: Any) -> str:
    return environment.get_template(f"main_reports/{template}").render(**values).rstrip() + "\n"


# A rendered dash cell, starred header or partial total: the page needs its one legend line.
_MARKED = re.compile(r'class="[^"]*\b(?:unk|partial|starred)\b')


def _render_summary(
    environment: Environment, name: str, *, page: dict[str, Any], **values: Any
) -> str:
    """One summary; the unknown/partial legend line is added only when the page shows a
    dash or a star, so it appears exactly once or not at all."""
    html = _render(environment, f"{name}.html.j2", page={**page, "legend": False}, **values)
    if _MARKED.search(html) is None:
        return html
    return _render(environment, f"{name}.html.j2", page={**page, "legend": True}, **values)


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
        _REIMBURSEMENT: (school, _reimbursement_summary(report, bundle)),
        _BUDGET: (school, _budget_snapshot(report)),
        _FUNDRAISING: (school, _fundraising_summary(report, context)),
        _PNL: (calendar, _pnl_summary(report, context)),
    }
    environment = _environment()
    documents = {
        name: _render_summary(
            environment,
            name,
            page=_page(name, report, bundle, context, period),
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


def pointer_page(
    *,
    run_id: str,
    input_sha256: str,
    as_of: date,
    published_at: datetime,
    run_link: str,
    manifest_name: str,
) -> str:
    """The current-run pointer: one small page linking every report of the published run.

    ``run_link`` is the run folder relative to the pointer (POSIX). Rendered through the same
    autoescaping environment, policy and identity tags as every report page.
    """
    files = [
        ("Main Report Set index", INDEX_HTML),
        (REPORT_TITLES[_QUEUE], QUEUE_HTML),
        (f"{REPORT_TITLES[_QUEUE]} copy text", QUEUE_COPY_TEXT),
        *((REPORT_TITLES[name], f"{name}.html") for name in SUMMARY_NAMES),
        ("Run manifest", manifest_name),
    ]
    return _render(
        _environment(),
        POINTER_TEMPLATE,
        page={
            "run_id": run_id,
            "input_sha": input_sha256,
            "as_of": _long(as_of),
            "published": _timestamp(published_at),
        },
        links=[{"title": title, "href": f"{run_link}/{name}"} for title, name in files],
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
    """The index: a short link page with the shared totals, inputs and run records (§ 3.5)."""
    school, calendar = report.periods.school, report.periods.calendar
    page = _page(_INDEX, report, bundle, context, calendar)
    page.update(
        {
            "title": "Main Report Set",
            "period": {
                "label": f"{school.label} and {calendar.label}",
                "range": "",
                "through": _long(report.as_of),
                "legacy": "",
            },
            "coverage": "Declared coverage per source is in the Inputs table",
            "inputs": _freshness(report, context),
            "records": [f"{RECORDS_LINK_DIR}/{name}" for name in RECORD_LINKS],
        }
    )
    return page
