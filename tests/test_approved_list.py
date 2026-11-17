"""The approved-list read, validation, digest and matching rules (fictional rows only).

Every name and email below is fictional; ``example.org`` addresses only. The fakes defined
here (``ListClient``, ``list_client``, ``LIST_GRID``) are reused by the CLI integration tests.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import date

import gspread
import pytest
from gspread.exceptions import WorksheetNotFound

from np_finance import approved_list
from np_finance.approved_list import ApprovedListError, match_requester, parse_approved_list
from np_finance.config import Config
from np_finance.main_reports.sources import READONLY_SCOPE
from tests.conftest import FakeClient, FakeSpreadsheet, FakeWorksheet, make_api_error

LIST_TAB = "Example Approved List"

HEADER = [
    " name ",
    "EMAIL",
    "Role",
    "Class",
    "Grade",
    "School Year",
    "Status",
    "Other Names",
    "Notes",
]
LIST_GRID: list[list[str]] = [
    HEADER,
    [
        "Avery Listed",
        " Avery.Listed@Example.ORG ",
        "Room Parent",
        "Room 4",
        "2",
        "2026-2027",
        " approved ",
        "",
        "",
    ],
    ["Blake Nomail", "", "Teacher", "Room 7", "", "", "Approved", "Blake N. Teacher", "x"],
    ["Casey Retired", "not-an-email", "Teacher", "", "", "1999", "Retired", "", ""],
]
# Every private value in the grid: none may ever appear in an error or a printed line.
CANARIES = (
    "Avery",
    "Blake",
    "Casey",
    "Listed",
    "Nomail",
    "example.org",
    "not-an-email",
    "Room",
    LIST_TAB,
)


def assert_value_free(text: str) -> None:
    lowered = text.casefold()
    for canary in CANARIES:
        assert canary.casefold() not in lowered


class _ListSpreadsheet(FakeSpreadsheet):
    """Raises gspread's own ``WorksheetNotFound`` for a missing tab, as the live API does."""

    def worksheet(self, title: str) -> FakeWorksheet:
        try:
            return super().worksheet(title)
        except KeyError:
            raise WorksheetNotFound(title) from None


class ListClient(FakeClient):
    """A fake gspread client for the toolkit's own spreadsheet."""

    def set_timeout(self, timeout: float) -> None:
        self.timeout = timeout


def list_client(grid: list[list[str]] | None = None, *, tab: str = LIST_TAB) -> ListClient:
    rows = LIST_GRID if grid is None else grid
    return ListClient(_ListSpreadsheet({tab: FakeWorksheet([list(row) for row in rows])}))


def _configured(config: Config) -> Config:
    return dataclasses.replace(
        config, sheets=dataclasses.replace(config.sheets, approved_list_tab=LIST_TAB)
    )


def test_parse_keeps_only_approved_rows_and_digests_them_exactly() -> None:
    parsed = parse_approved_list(LIST_GRID[0], LIST_GRID[1:])

    assert parsed.approved_rows == 2
    avery, blake = parsed.rows
    assert avery.email == "avery.listed@example.org"
    assert blake.name_keys == ("blake nomail", "blake n teacher")
    expected = [
        {
            "name": "Avery Listed",
            "other_names": "",
            "email": "avery.listed@example.org",
            "role": "Room Parent",
            "class": "Room 4",
            "grade": "2",
            "school_year": "2026-2027",
        },
        {
            "name": "Blake Nomail",
            "other_names": "Blake N. Teacher",
            "email": "",
            "role": "Teacher",
            "class": "Room 7",
            "grade": "",
            "school_year": "",
        },
    ]
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert parsed.list_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # Rows that do not count (and ignored columns) never move the digest.
    edited = [list(row) for row in LIST_GRID]
    edited[1][8] = "a changed note"
    edited[3][0] = "Casey Renamed"
    assert parse_approved_list(edited[0], edited[1:]).list_sha256 == parsed.list_sha256


def _with(row: int, column: int, value: str) -> list[list[str]]:
    grid = [list(cells) for cells in LIST_GRID]
    grid[row][column] = value
    return grid


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        pytest.param([], "missing required column(s): Name, Email, Status", id="empty-tab"),
        pytest.param(_with(0, 1, "Mail"), "missing required column(s): Email", id="no-email"),
        pytest.param(_with(0, 8, "STATUS"), "duplicate column header", id="duplicate-header"),
        pytest.param(_with(1, 1, "Avery Listed"), "row 2: Email is not", id="malformed-email"),
        pytest.param(_with(2, 5, "2026-2028"), "row 3: School Year", id="gapped-year"),
        pytest.param(_with(2, 5, "Room 7"), "row 3: School Year", id="free-text-year"),
        pytest.param([HEADER, LIST_GRID[3]], "no Approved rows", id="no-approved"),
    ],
)
def test_invalid_lists_fail_with_value_free_messages(grid: list[list[str]], message: str) -> None:
    header, rows = (grid[0], grid[1:]) if grid else ([], [])
    with pytest.raises(ApprovedListError) as exc_info:
        parse_approved_list(header, rows)
    assert message in str(exc_info.value)
    assert_value_free(str(exc_info.value))


_LIST = parse_approved_list(LIST_GRID[0], LIST_GRID[1:])
_AVERY_EMAIL = approved_list.email_digest("avery.listed@example.org")
_OTHER_EMAIL = approved_list.email_digest("someone.else@example.org")


@pytest.mark.parametrize(
    ("name", "email_sha256", "year", "entry", "email_matched", "differs"),
    [
        pytest.param("Unrelated Name", _AVERY_EMAIL, "2026-2027", 0, True, False, id="email"),
        pytest.param("Avery Listed", _AVERY_EMAIL, "2025-2026", None, False, False, id="scoped"),
        pytest.param("  AVERY   listed ", None, "2026-2027", 0, False, False, id="name-no-form"),
        pytest.param("Avery Listed", _OTHER_EMAIL, "2026-2027", None, False, True, id="differs"),
        pytest.param("Blaké Nomail", _OTHER_EMAIL, "2001-2002", 1, False, False, id="no-row-email"),
        pytest.param("Blake N Teacher", None, "2026-2027", 1, False, False, id="other-name"),
        pytest.param("Blake Nomai", None, "2026-2027", None, False, False, id="near-miss"),
        pytest.param("", None, "2026-2027", None, False, False, id="blank"),
    ],
)
def test_match_requester_applies_the_email_then_name_rules(
    name: str,
    email_sha256: str | None,
    year: str,
    entry: int | None,
    email_matched: bool,
    differs: bool,
) -> None:
    match = match_requester(_LIST, name=name, email_sha256=email_sha256, school_year=year)

    assert match.entry is (None if entry is None else _LIST.rows[entry])
    assert match.on_list is (entry is not None)
    assert (match.email_matched, match.name_email_differs) == (email_matched, differs)


def test_match_entry_is_the_first_qualifying_row_in_sheet_order() -> None:
    first = ["Dana Twice", "", "Teacher", "Room 1", "", "", "Approved", "", ""]
    second = ["Dana Twice", "", "Room Parent", "Room 2", "", "", "Approved", "", ""]
    parsed = parse_approved_list(HEADER, [first, second])

    match = match_requester(parsed, name="Dana Twice", email_sha256=None, school_year="2026-2027")

    assert match.entry is parsed.rows[0]


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [(date(2026, 7, 1), "2026-2027"), (date(2026, 6, 30), "2025-2026")],
)
def test_school_year_begins_in_the_configured_start_month(submitted: date, expected: str) -> None:
    assert approved_list.school_year_of(submitted, 7) == expected


def test_email_digest_normalizes_and_blank_has_none() -> None:
    expected = hashlib.sha256(b"avery.listed@example.org").hexdigest()
    assert approved_list.email_digest("  Avery.Listed@EXAMPLE.org\t") == expected
    assert approved_list.email_digest("   ") is None


def _forbid_service_account(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_kwargs: object) -> None:
        raise AssertionError("an unconfigured approved list must not open a Sheets client")

    monkeypatch.setattr(gspread, "service_account", forbidden)


def test_unconfigured_list_is_not_read(
    fake_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_service_account(monkeypatch)
    assert approved_list.read_approved_list(fake_config) is None


def test_configured_list_is_read_through_the_read_only_client(
    fake_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = list_client()
    recorded: list[tuple[str, ...]] = []

    def service_account(*, filename: str, scopes: Sequence[str]) -> ListClient:
        recorded.append(tuple(scopes))
        return client

    monkeypatch.setattr(gspread, "service_account", service_account)

    parsed = approved_list.read_approved_list(_configured(fake_config))

    assert parsed == _LIST
    assert recorded == [(READONLY_SCOPE,)]
    assert client.opened_keys == [fake_config.sheets.spreadsheet_id]


def _denied_client() -> ListClient:
    denied = make_api_error(
        403, message=f"no access to {LIST_TAB} for avery.listed@example.org", api_status="DENIED"
    )
    worksheet = FakeWorksheet(LIST_GRID, fail_first={"get_all_values": [denied]})
    return ListClient(_ListSpreadsheet({LIST_TAB: worksheet}))


@pytest.mark.parametrize(
    ("make_client", "message"),
    [
        pytest.param(lambda: list_client(tab="Another Tab"), "tab was not found", id="missing"),
        pytest.param(_denied_client, "could not be read (APIError, HTTP 403)", id="forbidden"),
    ],
)
def test_unreadable_list_fails_value_free(
    fake_config: Config, make_client: Callable[[], ListClient], message: str
) -> None:
    with pytest.raises(ApprovedListError) as exc_info:
        approved_list.read_approved_list(_configured(fake_config), gspread_client=make_client())
    assert message in str(exc_info.value)
    assert_value_free(str(exc_info.value))
