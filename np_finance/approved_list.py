"""The operator-maintained approved list of reimbursement requesters (read-only).

The OPTIONAL ``[sheets] approved_list_tab`` names one tab in the toolkit's OWN spreadsheet
(never the CFO workbook). When it is configured, ``update-reimbursements`` reads that tab once
through the read-only client (:func:`np_finance.main_reports.sources.connect_own_read_client`,
``spreadsheets.readonly``) and validates it with :func:`parse_approved_list` before any mail
fetch or bundle refresh. Nothing here ever writes a Sheet.

This module is the ONE owner of the list rules:

* **Columns.** ``Name``, ``Email`` and ``Status`` are required; ``Other Names`` (semicolon
  separated), ``Role``, ``Class``, ``Grade`` and ``School Year`` are optional; any other column
  is ignored. Headers match trimmed and case-insensitively, and a repeated header fails.
* **Rows that count.** ``Status`` equal to ``Approved`` (trimmed, case-insensitive). An
  Approved row's non-blank normalized Email must be a mailbox address
  (:data:`np_finance.reimbursement_events.EMAIL_RE`), and its School Year must be blank or
  consecutive ``YYYY-YYYY``. A list with no Approved row fails.
* **Digest.** :attr:`ApprovedList.list_sha256` is the lowercase hex SHA-256 of the canonical
  JSON of the Approved rows in sheet order (see :func:`list_digest`).
* **Matching.** :func:`match_requester` applies the email-then-name rules; near matches never
  approve.

Error text is VALUE-FREE: it names columns, rules and counts, never a cell value, a name, an
email, the tab title or a workbook identifier.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from np_finance.reimbursement_events import EMAIL_RE

if TYPE_CHECKING:
    import gspread

    from np_finance.config import Config

__all__ = [
    "ApprovedList",
    "ApprovedListError",
    "ApprovedRow",
    "RequesterMatch",
    "email_digest",
    "list_digest",
    "match_requester",
    "normalize_email",
    "normalize_name",
    "parse_approved_list",
    "read_approved_list",
    "school_year_of",
]

# Header labels, compared trimmed and casefolded.
_NAME = "name"
_EMAIL = "email"
_STATUS = "status"
_OTHER_NAMES = "other names"
_ROLE = "role"
_CLASS = "class"
_GRADE = "grade"
_SCHOOL_YEAR = "school year"
_REQUIRED_COLUMNS = (_NAME, _EMAIL, _STATUS)
_APPROVED = "approved"

_SCHOOL_YEAR_RE = re.compile(r"([0-9]{4})-([0-9]{4})")
_NAME_SEPARATOR_RE = re.compile(r"[\W_]+")


class ApprovedListError(ValueError):
    """The configured approved list is unreadable or invalid. Messages are value-free."""


@dataclass(frozen=True)
class ApprovedRow:
    """One Approved row: trimmed cells, the normalized email and the normalized names."""

    name: str
    other_names: str
    email: str
    role: str
    class_: str
    grade: str
    school_year: str
    email_sha256: str | None
    name_keys: tuple[str, ...]


@dataclass(frozen=True)
class ApprovedList:
    """The Approved rows in sheet order, their digest and their count.

    ``approved_rows`` counts every row whose Status is Approved, before school-year scoping.
    """

    rows: tuple[ApprovedRow, ...]
    list_sha256: str

    @property
    def approved_rows(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class RequesterMatch:
    """The outcome of :func:`match_requester`.

    ``entry`` is the first matching in-scope row in sheet order, or ``None`` when the requester
    is not on the list. ``email_matched`` is true for an on-list match by email (otherwise an
    on-list match is by name). ``name_email_differs`` is true only for a not-on-list requester
    whose name matches a row whose email differs from the present form email.
    """

    entry: ApprovedRow | None
    email_matched: bool = False
    name_email_differs: bool = False

    @property
    def on_list(self) -> bool:
        return self.entry is not None


def normalize_email(raw: str) -> str:
    """Surrounding whitespace stripped, then casefolded (form and list emails alike)."""
    return raw.strip().casefold()


def email_digest(raw: str) -> str | None:
    """Lowercase hex SHA-256 of the normalized email's UTF-8 bytes; ``None`` when blank."""
    normalized = normalize_email(raw)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_name(raw: str) -> str:
    """Unicode-folded, case-insensitive full name with punctuation and spacing collapsed.

    Compatibility-decomposed with combining marks dropped, casefolded, and every run of
    punctuation, underscores and whitespace collapsed to one space. Blank -> ``""``.
    """
    decomposed = unicodedata.normalize("NFKD", raw)
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NAME_SEPARATOR_RE.sub(" ", folded.casefold()).strip()


def school_year_of(submitted: date, start_month: int) -> str:
    """The ``YYYY-YYYY`` school year that contains ``submitted``.

    A school year begins on the first day of ``[fiscal_year] start_month`` (``1..12``, as
    validated by the config loader).
    """
    first = submitted.year if submitted.month >= start_month else submitted.year - 1
    return f"{first}-{first + 1}"


def list_digest(rows: tuple[ApprovedRow, ...]) -> str:
    """Lowercase hex SHA-256 of the UTF-8 canonical JSON of the Approved rows in sheet order.

    Each row is an object of its trimmed Name, Other Names, Email (normalized), Role, Class,
    Grade and School Year cells; canonical JSON is ``sort_keys=True``,
    ``separators=(",", ":")``, ``ensure_ascii=False``.
    """
    payload = [
        {
            "name": row.name,
            "other_names": row.other_names,
            "email": row.email,
            "role": row.role,
            "class": row.class_,
            "grade": row.grade,
            "school_year": row.school_year,
        }
        for row in rows
    ]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _column_positions(header: list[str]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for index, cell in enumerate(header):
        label = cell.strip().casefold()
        if not label:
            continue
        if label in positions:
            raise ApprovedListError("the approved list has a duplicate column header")
        positions[label] = index
    missing = [label for label in _REQUIRED_COLUMNS if label not in positions]
    if missing:
        raise ApprovedListError(
            "the approved list is missing required column(s): "
            + ", ".join(label.title() for label in missing)
        )
    return positions


def _valid_school_year(value: str) -> bool:
    if not value:
        return True
    match = _SCHOOL_YEAR_RE.fullmatch(value)
    return match is not None and int(match.group(2)) == int(match.group(1)) + 1


def parse_approved_list(header: list[str], rows: list[list[str]]) -> ApprovedList:
    """Validate the header and data rows (sheet order) and return the Approved rows.

    Raises :class:`ApprovedListError` (value-free; a failing row is named by its sheet row
    number) for a missing required column, a duplicate header, a malformed email or School
    Year on an Approved row, or no Approved row at all.
    """
    positions = _column_positions(header)

    approved: list[ApprovedRow] = []
    for offset, raw in enumerate(rows):
        sheet_row = offset + 2  # 1-based, after the header row

        def cell(label: str, raw: list[str] = raw) -> str:
            index = positions.get(label)
            if index is None or index >= len(raw):
                return ""
            return raw[index].strip()

        if cell(_STATUS).casefold() != _APPROVED:
            continue
        email = normalize_email(cell(_EMAIL))
        if email and EMAIL_RE.fullmatch(email) is None:
            raise ApprovedListError(
                f"approved list row {sheet_row}: Email is not a mailbox address"
            )
        school_year = cell(_SCHOOL_YEAR)
        if not _valid_school_year(school_year):
            raise ApprovedListError(
                f"approved list row {sheet_row}: School Year must be blank or consecutive YYYY-YYYY"
            )
        name = cell(_NAME)
        other_names = cell(_OTHER_NAMES)
        keys = (normalize_name(name), *(normalize_name(part) for part in other_names.split(";")))
        approved.append(
            ApprovedRow(
                name=name,
                other_names=other_names,
                email=email,
                role=cell(_ROLE),
                class_=cell(_CLASS),
                grade=cell(_GRADE),
                school_year=school_year,
                email_sha256=email_digest(email),
                name_keys=tuple(dict.fromkeys(key for key in keys if key)),
            )
        )
    if not approved:
        raise ApprovedListError("the approved list has no Approved rows")
    frozen = tuple(approved)
    return ApprovedList(rows=frozen, list_sha256=list_digest(frozen))


def read_approved_list(
    config: Config, *, gspread_client: gspread.Client | None = None
) -> ApprovedList | None:
    """Read and validate the configured tab; ``None`` (no Sheets access) when unconfigured.

    The toolkit's own spreadsheet is opened through the read-only client; tests inject
    ``gspread_client``. Every read failure becomes a value-free :class:`ApprovedListError`
    naming only the failure type and any HTTP status.
    """
    tab = config.sheets.approved_list_tab
    if tab is None:
        return None
    # The Sheets client is imported only here, so an unconfigured install never loads it.
    from gspread.exceptions import WorksheetNotFound

    from np_finance.main_reports.sources import connect_own_read_client
    from np_finance.sheets import SHEETS_FAILURES, http_status

    try:
        grid = connect_own_read_client(config, gspread_client=gspread_client).read_values(tab)
    except WorksheetNotFound:
        raise ApprovedListError("the configured approved list tab was not found") from None
    except SHEETS_FAILURES as exc:
        status = http_status(exc)
        detail = type(exc).__name__ + (f", HTTP {status}" if status is not None else "")
        raise ApprovedListError(
            f"the configured approved list tab could not be read ({detail})"
        ) from None
    if not grid:
        return parse_approved_list([], [])
    return parse_approved_list(grid[0], grid[1:])


def match_requester(
    approved_list: ApprovedList,
    *,
    name: str,
    email_sha256: str | None,
    school_year: str,
) -> RequesterMatch:
    """Match one request's requester against the Approved rows in scope for its school year.

    In scope: rows whose School Year is blank or equals ``school_year``. Rules, in order:

    1. The form email digest equals a row's email digest: on list, by email.
    2. Otherwise the normalized full name equals a row's Name or Other Name, and the form has
       no email or that row has none: on list, by name.
    3. A name match whose row email differs from the present form email: not on list, with
       ``name_email_differs``.
    4. Otherwise: not on list.

    ``entry`` is the first qualifying row in sheet order.
    """
    in_scope = [
        row for row in approved_list.rows if not row.school_year or row.school_year == school_year
    ]
    if email_sha256 is not None:
        for row in in_scope:
            if row.email_sha256 == email_sha256:
                return RequesterMatch(entry=row, email_matched=True)
    key = normalize_name(name)
    if not key:
        return RequesterMatch(entry=None)
    named = [row for row in in_scope if key in row.name_keys]
    for row in named:
        if email_sha256 is None or row.email_sha256 is None:
            return RequesterMatch(entry=row)
    return RequesterMatch(entry=None, name_email_differs=bool(named))
