"""Tests for np_finance.main_reports.adjustments — the Assumptions journal and projection.

Every fixture is fictional (``Example`` placeholders, fake ids). Scenarios run through the
production path: private config loaded by the real loader -> read-only capture over fake
gspread workbooks -> :func:`reconcile.from_capture` -> :func:`adjustments.read_journal` ->
:func:`adjustments.project`, and :func:`adjustments.record` writes only to our own fake
workbook's Assumptions tab. Nothing performs a live Google call.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError
from gspread.exceptions import WorksheetNotFound
from requests.models import Response

from np_finance import backup
from np_finance import sheets as sheets_module
from np_finance.config import Config, load_config
from np_finance.main_reports import adjustments, models, reconcile, sources
from np_finance.main_reports.adjustments import (
    JOURNAL_COLUMNS,
    JOURNAL_MARKER,
    LOCK_FILENAME,
    WRITE_SCOPE,
    AdjustmentConflictError,
    AdjustmentError,
    AdjustmentWriteError,
    JournalLayoutError,
    ProposalError,
    RunBusyError,
    acquire_run_lock,
    connect_journal_client,
    load_proposals,
    parse_proposals,
    project,
    read_journal,
    record,
    require_publishable,
)
from np_finance.main_reports.models import (
    ADJUSTMENT_KINDS,
    AdjustedLedger,
    Adjustment,
    AdjustmentJournal,
    CaptureSet,
    Reconciliation,
    SourceCapture,
    Transaction,
    canonical_json_bytes,
    is_valid_record_key,
    make_adjustment_id,
    make_discrepancy_id,
    make_record_key,
)
from np_finance.sheets import SheetsClient
from tests.conftest import (
    _FULL_CONFIG,
    ASSUMPTIONS_GRID,
    BANK_HEADER,
    CARD_HEADER,
    CFO_ID,
    MAPPING_HEADER,
    PAYPAL_HEADER,
    WIX_GROUPS,
    WIX_LABELS,
    CfoHarness,
    CfoWorksheet,
    FakeClient,
    JournalWorksheet,
    RecordingSleep,
    TimeoutClient,
    main_reports_toml,
    make_api_error,
)

# --------------------------------------------------------------------------------------
# Fictional source shapes
# --------------------------------------------------------------------------------------


def _bank(day: str, description: str, amount: str, final: str) -> list[str]:
    return [day, description, amount, "", "Posted", "", "", final]


DEPOSIT = "Deposit Example Store payout"
CHECK = "Check 1001"
TRANSFER = "Transfer to savings"
VENDOR = "Example vendor"
DONATION = "Example donation"
SPLIT_VENDOR = "Example vendor two"
BANK_ROWS = [
    _bank("1/5/2030", DEPOSIT, "1,250.00", "Fundraiser Income: 1,280.00, Processing Fees: -30.00"),
    _bank("1/9/2030", CHECK, "-75.50", "Classroom Supplies"),
    _bank("1/12/2030", TRANSFER, "-500.00", reconcile.INTERNAL_TRANSFER_CATEGORY),
    _bank("1/31/2030", VENDOR, "-40.00", "Field Trips"),
    _bank("2/3/2030", DONATION, "100.00", "Donations"),
    _bank("2/10/2030", SPLIT_VENDOR, "-15.00", "Field Trips: -10.00, Field Trips: -5.00"),
]
WIX_ROW = [
    "pi_ex_001",
    "1/4/2030",
    "2030-01-04 10:15:00",
    "-08:00",
    "USD",
    "50.00",
    "-1.75",
    "0.00",
    "48.25",
    "Successful",
    "",
    "Wix Payments",
    "10004",
    "Spirit Shirt",
    "1",
    "Fulfilled",
    "Example Buyer",
    "US",
    "Example Buyer",
    "US",
]
PNL_VALUES = [
    ["Category", "Jan 2030", "Feb 2030"],
    ["Classroom Supplies", "-75.50", ""],
    ["Donations", "", "100.00"],
    ["Field Trips", "-40.00", "-15.00"],
    ["Fundraiser Income", "1,280.00", ""],
    ["Processing Fees", "-30.00", ""],
]
SOURCE_CELLS = {
    ("Classroom Supplies", "2030-01"): Decimal("-75.50"),
    ("Field Trips", "2030-01"): Decimal("-40.00"),
    ("Fundraiser Income", "2030-01"): Decimal("1280.00"),
    ("Processing Fees", "2030-01"): Decimal("-30.00"),
    ("Donations", "2030-02"): Decimal("100.00"),
    ("Field Trips", "2030-02"): Decimal("-15.00"),
}
AS_OF = date(2030, 2, 28)
RECORDED_AT = datetime(2030, 2, 1, 12, 0, tzinfo=UTC)
# Zero-based position of the Assumptions formula cell that must survive every write.
FORMULA_CELL = (2, 1)


def _config(tmp_path: Path, toml: str | None = None) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "config.toml"
    path.write_text(toml or _FULL_CONFIG + main_reports_toml(), encoding="utf-8")
    return load_config(path)


def _harness(
    config: Config,
    *,
    bank: Sequence[Sequence[str]] = BANK_ROWS,
    assumptions: JournalWorksheet | None = None,
    own_extra: dict[str, CfoWorksheet] | None = None,
) -> CfoHarness:
    sheets = {
        "Bank Checking": CfoWorksheet([BANK_HEADER, *map(list, bank)], sheet_id=1001),
        "Store Transactions": CfoWorksheet([WIX_GROUPS, WIX_LABELS, list(WIX_ROW)], sheet_id=1002),
        "Processor Transactions": CfoWorksheet([PAYPAL_HEADER], sheet_id=1003),
        "Profit & Loss": CfoWorksheet([list(row) for row in PNL_VALUES], sheet_id=1004),
        "Budget Tracker": CfoWorksheet([["Category", "Budget", "Actual"]], sheet_id=1005),
        "Category Mapping": CfoWorksheet([MAPPING_HEADER], sheet_id=1006),
        "Credit Card Transactions": CfoWorksheet([CARD_HEADER], sheet_id=1007),
    }
    return CfoHarness(config, sheets, assumptions=assumptions, own_extra=own_extra)


def _clock() -> Callable[[], datetime]:
    counter = itertools.count()
    return lambda: RECORDED_AT + timedelta(seconds=next(counter))


class Scenario:
    """A config, fake workbooks, and the production capture/reconcile/journal readers."""

    def __init__(self, tmp_path: Path, **kwargs: Any) -> None:
        self.tmp_path = tmp_path
        self.config = _config(tmp_path)
        self.harness = _harness(self.config, **kwargs)

    @property
    def sheet(self) -> JournalWorksheet:
        return self.harness.assumptions

    def capture(self) -> tuple[CaptureSet, Reconciliation]:
        capture_set = self.harness.capture()
        return capture_set, reconcile.from_capture(capture_set, self.config)

    def ledger(self, as_of: date = AS_OF) -> AdjustedLedger:
        capture_set, rec = self.capture()
        return project(rec, read_journal(capture_set.assumptions), as_of)

    def record(
        self,
        proposals: Sequence[Adjustment],
        *,
        as_of: date = AS_OF,
        client: SheetsClient | None = None,
    ) -> adjustments.RecordResult:
        capture_set, rec = self.capture()
        with acquire_run_lock(self.config) as lock:
            return record(
                proposals,
                config=self.config,
                client=client or self.harness.own(),
                captured=capture_set.assumptions,
                reconciliation=rec,
                as_of=as_of,
                lock=lock,
                clock=_clock(),
            )

    def txn(self, description: str) -> Transaction:
        _, rec = self.capture()
        (found,) = [t for t in rec.transactions if t.description == description]
        return found

    def files(self) -> list[Path]:
        return sorted(p.relative_to(self.tmp_path) for p in self.tmp_path.rglob("*"))


def _adjustment(
    kind: str,
    txn: Transaction | None = None,
    *,
    effective: date = date(2030, 1, 31),
    **fields: Any,
) -> Adjustment:
    return Adjustment(
        adjustment_id=fields.pop("adjustment_id", make_adjustment_id()),
        kind=kind,
        effective_date=effective,
        reason=fields.pop("reason", "Example correction"),
        evidence=fields.pop("evidence", ("example-statement-2030-01",)),
        targets=() if txn is None else ((txn.record_key, txn.revision_hash),),
        **fields,
    )


def _recategorize(txn: Transaction, prior: str, to: str, **fields: Any) -> Adjustment:
    return _adjustment("category_override", txn, prior_value=prior, replacement_value=to, **fields)


def _reverse(entry: Adjustment, **fields: Any) -> Adjustment:
    return _adjustment("reversal", supersedes=entry.adjustment_id, **fields)


def _cells(ledger: AdjustedLedger) -> dict[tuple[str, str], Decimal]:
    return {(c.category, c.month.isoformat()[:7]): c.net for c in ledger.monthly_cells}


def _source_cells(rec: Reconciliation) -> dict[tuple[str, str], Decimal]:
    return {(c.category, c.month.isoformat()[:7]): c.net for c in rec.monthly_cells}


def _journal_row(entry: Adjustment) -> list[str]:
    """The documented journal row encoding (``;``-joined lists, canonical text)."""
    data = entry.to_dict()
    data["targets"] = ";".join(f"{t['record_key']}@{t['revision_hash']}" for t in data["targets"])
    data["evidence"] = "; ".join(data["evidence"])
    return ["" if data[name] is None else str(data[name]) for name in JOURNAL_COLUMNS]


def _journal_sheet(*rows: Sequence[str], **kwargs: Any) -> JournalWorksheet:
    grid = [list(row) for row in ASSUMPTIONS_GRID]
    grid += [[], [], [JOURNAL_MARKER], list(JOURNAL_COLUMNS), *map(list, rows)]
    return JournalWorksheet(grid, sheet_id=2002, **kwargs)


def _stamped(entry: Adjustment) -> Adjustment:
    return dataclasses.replace(entry, recorded_at=RECORDED_AT)


def _codes(issues: Sequence[Any]) -> list[str]:
    return sorted(issue.code for issue in issues)


def _assert_conserved(ledger: AdjustedLedger) -> None:
    """Source net + every delta == adjusted net, for every category/month."""
    totals = _source_cells(ledger.source)
    for delta in ledger.deltas:
        key = (delta.category, delta.month.isoformat()[:7])
        totals[key] = totals.get(key, Decimal("0.00")) + delta.amount
    assert {k: v for k, v in totals.items() if v} == {k: v for k, v in _cells(ledger).items() if v}


# --------------------------------------------------------------------------------------
# Production path: capture -> reconcile -> record -> recapture -> project
# --------------------------------------------------------------------------------------


def test_recorded_adjustments_take_effect_immediately(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, rec = scenario.capture()
    journal = read_journal(capture_set.assumptions)
    assert journal.marker_row is None and journal.entries == ()
    before = project(rec, journal, AS_OF)
    assert _cells(before) == SOURCE_CELLS == _source_cells(rec)
    assert before.applied == () and before.deltas == () and before.publishable

    check, vendor, deposit = (scenario.txn(d) for d in (CHECK, VENDOR, DEPOSIT))
    proposals = [
        _recategorize(check, "Classroom Supplies", "Field Trips", reason="=SUM(B2:B3)"),
        _adjustment(
            "date_override", vendor, prior_value="2030-01-31", replacement_value="2030-02-01"
        ),
        _adjustment(
            "amount_correction",
            deposit,
            category="Processing Fees",
            prior_value="-30.00",
            replacement_value="-32.00",
        ),
        _adjustment(
            "additive",
            effective=date(2030, 2, 10),
            category="Donations",
            signed_amount=Decimal("25.00"),
            evidence=("example-cash-count-2030-02",),
        ),
    ]
    result = scenario.record(proposals)

    # Only our own Assumptions tab was written, in one RAW batch, below existing content.
    scenario.harness.assert_no_cfo_writes()
    sheet = scenario.sheet
    assert sheet.batch_update_vios == ["RAW"]
    (requests,) = sheet.batch_update_calls
    assert [r["range"] for r in requests] == ["A6", "A7:L7", "A8:L8", "A9:L9", "A10:L10", "A11:L11"]
    assert sheet.grid[:3] == [list(row) for row in ASSUMPTIONS_GRID]
    assert sheet.grid[3:5] == [[], []]
    assert sheet.grid[5] == [JOURNAL_MARKER]
    assert sheet.tagged_grid()[FORMULA_CELL[0]][FORMULA_CELL[1]] == {
        "userEnteredValue": {"formulaValue": "=B2*2"}
    }
    # Formula-like text is stored as text, never as a formula.
    assert sheet.tagged_grid()[7][8] == {"userEnteredValue": {"stringValue": "=SUM(B2:B3)"}}
    assert result.written == tuple(p.adjustment_id for p in proposals)
    assert result.already_recorded == () and result.attempts == 1

    # The pre-write snapshot preserved exact entered values, formula included.
    assert result.snapshot_path is not None
    exact = json.loads(result.snapshot_path.with_suffix(".raw.json").read_text(encoding="utf-8"))
    assert exact["grid"][2][1] == {"userEnteredValue": {"formulaValue": "=B2*2"}}
    assert result.snapshot_path.is_relative_to(scenario.config.main_reports.output_path)  # type: ignore[union-attr]

    # A fresh production capture reads the verified journal back exactly as proposed.
    capture_set, rec = scenario.capture()
    journal = read_journal(capture_set.assumptions)
    assert journal.marker_row == 6
    assert [e.row_number for e in journal.entries] == [8, 9, 10, 11]
    assert [dataclasses.replace(e.adjustment, recorded_at=None) for e in journal.entries] == (
        proposals
    )
    assert all(e.adjustment.recorded_at is not None for e in journal.entries)
    assert journal == result.journal

    ledger = project(rec, journal, AS_OF)
    assert ledger.publishable and ledger.conflicts == ()
    assert ledger.applied == result.written
    assert _cells(ledger) == {
        ("Field Trips", "2030-01"): Decimal("-75.50"),
        ("Fundraiser Income", "2030-01"): Decimal("1280.00"),
        ("Processing Fees", "2030-01"): Decimal("-32.00"),
        ("Donations", "2030-02"): Decimal("125.00"),
        ("Field Trips", "2030-02"): Decimal("-55.00"),
    }
    assert [(t.month.month, t.income, t.expense) for t in ledger.pnl_totals] == [
        (1, Decimal("1280.00"), Decimal("-107.50")),
        (2, Decimal("125.00"), Decimal("-55.00")),
    ]
    by_id = {p.adjustment_id: p.kind for p in proposals}
    assert sorted(
        (by_id[d.adjustment_id], d.category, d.month.month, d.amount) for d in ledger.deltas
    ) == [
        ("additive", "Donations", 2, Decimal("25.00")),
        ("amount_correction", "Processing Fees", 1, Decimal("-2.00")),
        ("category_override", "Classroom Supplies", 1, Decimal("75.50")),
        ("category_override", "Field Trips", 1, Decimal("-75.50")),
        ("date_override", "Field Trips", 1, Decimal("40.00")),
        ("date_override", "Field Trips", 2, Decimal("-40.00")),
    ]
    _assert_conserved(ledger)

    # Source records are untouched: reconciliation, states and findings are carried as is.
    assert ledger.source == rec
    assert ledger.discrepancies == rec.discrepancies
    corrected = [a for a in ledger.allocations if a.adjustment_ids]
    assert {(a.source_category, a.source_amount) for a in corrected} == {
        ("Classroom Supplies", Decimal("-75.50")),
        ("Field Trips", Decimal("-40.00")),
        ("Processing Fees", Decimal("-30.00")),
        (None, Decimal("0.00")),
    }
    payload = json.loads(canonical_json_bytes(ledger.to_dict()))
    assert payload["publishable"] is True and payload["schema_version"] == 1


def test_source_only_mode_reads_the_journal_and_never_writes(tmp_path: Path) -> None:
    for sheet in (None, _journal_sheet()):
        scenario = Scenario(tmp_path / str(id(sheet)), assumptions=sheet)
        before = scenario.files()
        ledger = scenario.ledger()
        scenario.harness.assert_no_writes()
        assert scenario.files() == before
        assert _cells(ledger) == SOURCE_CELLS and ledger.publishable


def test_record_is_idempotent_across_reruns(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    first = scenario.record([entry])
    second = scenario.record([entry])

    assert first.written == (entry.adjustment_id,)
    assert second.written == () and second.already_recorded == (entry.adjustment_id,)
    assert second.snapshot_path is None and second.attempts == 0
    assert len(scenario.sheet.batch_update_calls) == 1
    assert len(read_journal(scenario.capture()[0].assumptions).entries) == 1

    # A partly recorded batch writes only the new proposal.
    other = _adjustment(
        "additive", category="Donations", signed_amount=Decimal("5.00"), effective=AS_OF
    )
    third = scenario.record([entry, other])
    assert third.written == (other.adjustment_id,)
    assert third.already_recorded == (entry.adjustment_id,)
    assert [r["range"] for r in scenario.sheet.batch_update_calls[-1]] == ["A9:L9"]


def test_recorded_id_with_a_different_payload_is_refused(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.record([entry])
    changed = dataclasses.replace(entry, reason="Another reason")

    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.record([changed])

    assert caught.value.code == "proposal_conflict"
    assert _codes(caught.value.issues) == ["adjustment_id_conflict"]
    assert len(scenario.sheet.batch_update_calls) == 1


# --------------------------------------------------------------------------------------
# Uncertain writes, concurrent edits and readback
# --------------------------------------------------------------------------------------


def _raise_once(
    error: BaseException, edit: Callable[[JournalWorksheet], None] | None = None
) -> Any:
    def hook(sheet: JournalWorksheet) -> None:
        sheet.after_batch_update = None
        if edit is not None:
            edit(sheet)
        raise error

    return hook


def test_uncertain_write_that_landed_is_recovered_by_id(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet.after_batch_update = _raise_once(ConnectionError("lost response"))

    result = scenario.record([entry])

    assert result.written == (entry.adjustment_id,) and result.attempts == 1
    assert len(scenario.sheet.batch_update_calls) == 1
    assert scenario.ledger().applied == (entry.adjustment_id,)


def test_uncertain_write_that_did_not_land_is_retried_once(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet._fail_first["batch_update"] = [ConnectionError("timeout")]

    result = scenario.record([entry])

    assert result.attempts == 2
    assert len(scenario.sheet.batch_update_calls) == 1
    assert scenario.ledger().applied == (entry.adjustment_id,)


def test_write_that_never_lands_fails_visibly_and_records_nothing(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    # Every attempt the production retry policy allows is lost (default five).
    scenario.sheet._fail_first["batch_update"] = [ConnectionError(str(n)) for n in range(5)]

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])

    assert caught.value.code == "write_failed"
    assert caught.value.may_have_landed is True
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()
    assert read_journal(scenario.capture()[0].assumptions).marker_row is None


def test_unreadable_outcome_after_a_failed_write_is_unverified(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet._fail_first["batch_update"] = [ConnectionError("a")]
    original = scenario.sheet.get_all_values
    reads = itertools.count()

    def failing_read(*, value_render_option: Any = None) -> list[list[str]]:
        # The 1st/2nd reads are the pre-write checks; the 3rd is the readback.
        if next(reads) == 2:
            raise ConnectionError("network down")
        return original()

    scenario.sheet.get_all_values = failing_read  # type: ignore[method-assign]
    capture_set, rec = scenario.capture()
    reads = itertools.count()  # count only the reads made by record()
    with acquire_run_lock(scenario.config) as lock, pytest.raises(AdjustmentWriteError) as caught:
        record(
            [entry],
            config=scenario.config,
            client=scenario.harness.own(),
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
            clock=_clock(),
        )
    assert caught.value.code == "write_unverified"
    assert caught.value.may_have_landed is True


def _edit_cell(row: int, column: int, value: str) -> Callable[[JournalWorksheet], None]:
    return lambda sheet: sheet.set_cell(row, column, value)


def _formula_to_text(sheet: JournalWorksheet) -> None:
    sheet.raw_text.add(FORMULA_CELL)  # same display, but no longer a formula


def _entered_number(sheet: JournalWorksheet) -> None:
    sheet.entered[(1, 1)] = 1.5000001  # same display, different entered number


def _typed_zero(sheet: JournalWorksheet) -> None:
    sheet.raw_text.discard((7, 6))  # a written blank cell now holds a typed 0 shown blank
    sheet.entered[(7, 6)] = 0.0


def _new_tab_id(sheet: JournalWorksheet) -> None:
    sheet.id = 9999


CONCURRENT_EDITS = {
    "preserved_value_changed": (_edit_cell(1, 1, "2.0"), "concurrent_edit_detected"),
    "content_added_elsewhere": (_edit_cell(0, 20, "note"), "concurrent_edit_detected"),
    "formula_replaced": (_formula_to_text, "concurrent_edit_detected"),
    "entered_number_changed": (_entered_number, "concurrent_edit_detected"),
    "tab_replaced": (_new_tab_id, "concurrent_edit_detected"),
    "journal_value_changed": (_edit_cell(7, 8, "Edited reason"), "journal_readback_mismatch"),
    "journal_header_changed": (_edit_cell(6, 0, "id"), "journal_readback_mismatch"),
    "journal_row_unreadable": (_edit_cell(7, 3, "not a date"), "journal_readback_mismatch"),
    # Parsing strips text, so only the exact-cell check sees these.
    "journal_value_padded": (
        _edit_cell(7, 8, "Example correction "),
        "journal_readback_mismatch",
    ),
    "journal_cell_typed": (
        _typed_zero,
        "journal_readback_mismatch",
    ),
}


@pytest.mark.parametrize("case", sorted(CONCURRENT_EDITS))
def test_readback_detects_concurrent_edits_and_never_restores(tmp_path: Path, case: str) -> None:
    edit, code = CONCURRENT_EDITS[case]
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")

    def concurrent(sheet: JournalWorksheet) -> None:
        sheet.after_batch_update = None
        edit(sheet)

    scenario.sheet.after_batch_update = concurrent
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])

    assert caught.value.code == code
    assert caught.value.may_have_landed is True
    snapshot, after = caught.value.evidence
    assert snapshot.exists() and after.name == "after-readback.json" and after.exists()
    # Nothing is rolled back or rewritten: exactly one write was issued.
    assert len(scenario.sheet.batch_update_calls) == 1
    assert scenario.sheet.grid[5] == [JOURNAL_MARKER]


def test_uncertain_write_with_a_concurrent_edit_is_a_conflict(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet.after_batch_update = _raise_once(
        ConnectionError("lost response"), _edit_cell(1, 1, "2.0")
    )

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])

    assert caught.value.code == "write_uncertain_conflict"
    assert caught.value.may_have_landed is True
    assert "concurrent_edit_detected" in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert len(caught.value.evidence) == 2
    assert len(scenario.sheet.batch_update_calls) == 1


def test_assumptions_changed_since_capture_blocks_the_write(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    capture_set, rec = scenario.capture()
    scenario.sheet.set_cell(1, 1, "1.75")  # an operator edit after the run's capture

    with acquire_run_lock(scenario.config) as lock, pytest.raises(AdjustmentWriteError) as caught:
        record(
            [entry],
            config=scenario.config,
            client=scenario.harness.own(),
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
        )

    assert caught.value.code == "assumptions_changed" and caught.value.evidence == ()
    assert caught.value.may_have_landed is False
    assert scenario.sheet.batch_update_calls == []
    assert not (scenario.config.main_reports.output_path / "adjustments").exists()  # type: ignore[union-attr]


def test_edit_between_snapshot_and_write_blocks_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    real = backup.snapshot_raw_tab

    def snapshot_then_edit(*args: Any, **kwargs: Any) -> Path:
        path = real(*args, **kwargs)
        scenario.sheet.set_cell(0, 5, "late edit")
        return path

    monkeypatch.setattr(backup, "snapshot_raw_tab", snapshot_then_edit)
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])

    assert caught.value.code == "assumptions_changed"
    assert caught.value.may_have_landed is False
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()
    assert scenario.sheet.batch_update_calls == []


def test_grid_is_grown_before_appending_beyond_its_rows_and_columns(tmp_path: Path) -> None:
    sheet = JournalWorksheet(
        [list(row) for row in ASSUMPTIONS_GRID], sheet_id=2002, row_count=5, col_count=4
    )
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")

    scenario.record([entry])

    assert sheet.add_rows_calls == [3] and sheet.add_cols_calls == [8]
    assert scenario.ledger().applied == (entry.adjustment_id,)


# --------------------------------------------------------------------------------------
# Preconditions, supersession and effective dates
# --------------------------------------------------------------------------------------


def _wix_txn(scenario: Scenario) -> Transaction:
    _, rec = scenario.capture()
    (found,) = [t for t in rec.transactions if t.source_kind == "wix"]
    return found


def _bad_target(scenario: Scenario, case: str) -> Adjustment:
    check = scenario.txn(CHECK)
    if case == "target_missing":
        moved = dataclasses.replace(check, record_key=check.record_key[:-1] + "9")
        return _recategorize(moved, "Classroom Supplies", "Field Trips")
    if case == "target_not_bank":
        return _recategorize(_wix_txn(scenario), "Classroom Supplies", "Field Trips")
    if case == "target_revision_mismatch":
        stale = dataclasses.replace(check, revision_hash="0" * 64)
        return _recategorize(stale, "Classroom Supplies", "Field Trips")
    if case == "category_prior":
        return _recategorize(check, "Field Trips", "Donations")
    if case == "date_prior":
        return _adjustment(
            "date_override", check, prior_value="2030-01-10", replacement_value="2030-02-01"
        )
    if case == "amount_prior":
        return _adjustment(
            "amount_correction",
            check,
            category="Classroom Supplies",
            prior_value="-75.51",
            replacement_value="-70.00",
        )
    assert case == "amount_category_absent"
    return _adjustment(
        "amount_correction",
        check,
        category="Donations",
        prior_value="0.00",
        replacement_value="-70.00",
    )


BAD_TARGETS = {
    "target_missing": "target_missing",
    "target_not_bank": "target_not_bank",
    "target_revision_mismatch": "target_revision_mismatch",
    "category_prior": "prior_value_mismatch",
    "date_prior": "prior_value_mismatch",
    "amount_prior": "prior_value_mismatch",
    "amount_category_absent": "prior_value_mismatch",
}


@pytest.mark.parametrize("case", sorted(BAD_TARGETS))
def test_exact_target_preconditions_are_required_before_any_write(
    tmp_path: Path, case: str
) -> None:
    scenario = Scenario(tmp_path)
    proposal = _bad_target(scenario, case)

    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.record([proposal])

    assert caught.value.code == "proposal_conflict"
    assert _codes(caught.value.issues) == [BAD_TARGETS[case]]
    assert scenario.sheet.batch_update_calls == []
    assert not (scenario.config.main_reports.output_path / "adjustments").exists()  # type: ignore[union-attr]

    # The same entry recorded by hand blocks adjusted publication and applies nothing.
    journal_sheet = _journal_sheet(_journal_row(_stamped(proposal)))
    ledger = Scenario(tmp_path / "manual", assumptions=journal_sheet).ledger()
    assert _codes(ledger.conflicts) == [BAD_TARGETS[case]]
    assert ledger.applied == () and _cells(ledger) == SOURCE_CELLS
    with pytest.raises(AdjustmentConflictError) as blocked:
        require_publishable(ledger)
    assert blocked.value.code == "adjusted_publication_blocked"


def test_future_entry_preconditions_are_checked_when_recorded(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    stale = dataclasses.replace(scenario.txn(CHECK), revision_hash="0" * 64)
    proposal = _recategorize(stale, "Classroom Supplies", "Field Trips", effective=date(2031, 1, 1))

    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.record([proposal])

    assert _codes(caught.value.issues) == ["target_revision_mismatch"]


def test_supersession_and_reversal_are_append_only(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    check = scenario.txn(CHECK)
    first = _recategorize(check, "Classroom Supplies", "Field Trips")
    scenario.record([first])
    first_row = list(scenario.sheet.grid[7])

    second = _recategorize(check, "Classroom Supplies", "Donations", supersedes=first.adjustment_id)
    scenario.record([second])
    ledger = scenario.ledger()
    assert ledger.applied == (second.adjustment_id,)
    assert ledger.superseded == (first.adjustment_id,)
    assert _cells(ledger)[("Donations", "2030-01")] == Decimal("-75.50")
    _assert_conserved(ledger)

    third = _reverse(second)
    scenario.record([third])
    ledger = scenario.ledger()
    assert ledger.applied == (third.adjustment_id,)
    assert set(ledger.superseded) == {first.adjustment_id, second.adjustment_id}
    assert _cells(ledger) == SOURCE_CELLS and ledger.deltas == ()

    # Earlier rows were never rewritten: each write touched only its own new row.
    assert scenario.sheet.grid[7] == first_row
    assert [[r["range"] for r in call] for call in scenario.sheet.batch_update_calls] == [
        ["A6", "A7:L7", "A8:L8"],
        ["A9:L9"],
        ["A10:L10"],
    ]


def test_entries_apply_only_from_their_effective_date(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    first = _stamped(_recategorize(check, "Classroom Supplies", "Field Trips"))
    later = _stamped(
        _recategorize(
            check,
            "Classroom Supplies",
            "Donations",
            supersedes=first.adjustment_id,
            effective=date(2030, 3, 15),
        )
    )
    sheet = _journal_sheet(_journal_row(first), _journal_row(later))
    scenario = Scenario(tmp_path, assumptions=sheet)

    early = scenario.ledger(date(2030, 1, 30))
    assert early.applied == () and early.pending == tuple(
        sorted((first.adjustment_id, later.adjustment_id))
    )
    assert _cells(early) == SOURCE_CELLS

    middle = scenario.ledger(date(2030, 2, 28))
    assert middle.applied == (first.adjustment_id,) and middle.pending == (later.adjustment_id,)
    assert _cells(middle)[("Field Trips", "2030-01")] == Decimal("-115.50")

    late = scenario.ledger(date(2030, 3, 15))
    assert late.applied == (later.adjustment_id,) and late.superseded == (first.adjustment_id,)
    assert _cells(late)[("Donations", "2030-01")] == Decimal("-75.50")


def test_source_revision_change_blocks_until_an_explicit_remap(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    original = scenario.txn(CHECK)
    first = _recategorize(original, "Classroom Supplies", "Field Trips")
    scenario.record([first])

    # The CFO changes that row's category: same identity, new revision.
    scenario.harness.cfo_sheets["Bank Checking"].grid[2][7] = "Classroom Supply"
    revised = scenario.txn(CHECK)
    assert revised.record_key == original.record_key
    assert revised.revision_hash != original.revision_hash
    blocked = scenario.ledger()
    assert _codes(blocked.conflicts) == ["target_revision_mismatch"]
    assert not blocked.publishable and blocked.applied == ()

    remap = _recategorize(
        revised,
        "Classroom Supply",
        "Field Trips",
        supersedes=first.adjustment_id,
        evidence=("example-remap-note",),
    )
    scenario.record([remap])
    ledger = scenario.ledger()
    assert ledger.publishable and ledger.applied == (remap.adjustment_id,)
    assert _cells(ledger)[("Field Trips", "2030-01")] == Decimal("-115.50")


def test_competing_active_replacements_are_refused(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    check = scenario.txn(CHECK)
    one = _recategorize(check, "Classroom Supplies", "Field Trips")
    two = _recategorize(check, "Classroom Supplies", "Donations")

    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.record([one, two])
    assert _codes(caught.value.issues) == ["competing_replacement", "competing_replacement"]
    assert scenario.sheet.batch_update_calls == []

    sheet = _journal_sheet(_journal_row(_stamped(one)), _journal_row(_stamped(two)))
    ledger = Scenario(tmp_path / "manual", assumptions=sheet).ledger()
    assert _codes(ledger.conflicts) == ["competing_replacement", "competing_replacement"]
    assert ledger.applied == () and _cells(ledger) == SOURCE_CELLS


def test_different_slots_on_one_row_compose(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    split = scenario.txn(SPLIT_VENDOR)
    amount = _adjustment(
        "amount_correction",
        split,
        category="Field Trips",
        prior_value="-15.00",
        replacement_value="-12.00",
    )
    category = _recategorize(split, "Field Trips", reconcile.INTERNAL_TRANSFER_CATEGORY)
    moved = _adjustment(
        "date_override", split, prior_value="2030-02-10", replacement_value="2030-01-20"
    )
    scenario.record([moved, category, amount])
    ledger = scenario.ledger()

    # Both same-category components merge into one corrected allocation, which is then
    # moved to the excluded transfer category: it leaves the P&L view entirely.
    (allocation,) = [a for a in ledger.allocations if a.record_key == split.record_key]
    assert (allocation.amount, allocation.source_amount) == (Decimal("-12.00"), Decimal("-15.00"))
    assert allocation.category == reconcile.INTERNAL_TRANSFER_CATEGORY and not allocation.counted
    assert allocation.posting_date == date(2030, 1, 20)
    assert allocation.adjustment_ids == (
        amount.adjustment_id,
        category.adjustment_id,
        moved.adjustment_id,
    )
    assert ("Field Trips", "2030-02") not in _cells(ledger)
    _assert_conserved(ledger)


def test_independent_slots_on_one_row_do_not_compete(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    deposit = scenario.txn(DEPOSIT)
    entries = [
        _recategorize(deposit, "Fundraiser Income", "Donations"),
        _recategorize(deposit, "Processing Fees", "Fees and Charges"),
        _adjustment(
            "amount_correction",
            deposit,
            category="Fundraiser Income",
            prior_value="1280.00",
            replacement_value="1290.00",
        ),
        _adjustment(
            "amount_correction",
            deposit,
            category="Processing Fees",
            prior_value="-30.00",
            replacement_value="-31.00",
        ),
    ]
    scenario.record(entries)
    ledger = scenario.ledger()
    assert ledger.publishable and len(ledger.applied) == 4
    cells = _cells(ledger)
    assert cells[("Donations", "2030-01")] == Decimal("1290.00")
    assert cells[("Fees and Charges", "2030-01")] == Decimal("-31.00")
    _assert_conserved(ledger)


def test_date_move_within_a_month_has_no_cell_delta(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _adjustment(
        "date_override",
        scenario.txn(CHECK),
        prior_value="2030-01-09",
        replacement_value="2030-01-20",
    )
    scenario.record([entry])
    ledger = scenario.ledger()
    assert ledger.applied == (entry.adjustment_id,)
    assert ledger.deltas == () and _cells(ledger) == SOURCE_CELLS
    (moved,) = [a for a in ledger.allocations if a.adjustment_ids]
    assert (moved.source_date, moved.posting_date) == (date(2030, 1, 9), date(2030, 1, 20))


def test_one_unreadable_row_stops_every_entry_from_applying(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    bad = _valid_row(check)
    bad[3] = "not a date"
    good = _journal_row(_stamped(_recategorize(check, "Classroom Supplies", "Field Trips")))
    ledger = Scenario(tmp_path, assumptions=_journal_sheet(good, bad)).ledger()
    assert _codes(ledger.conflicts) == ["invalid_date"]
    assert ledger.applied == () and _cells(ledger) == SOURCE_CELLS


@pytest.mark.parametrize("entered", ['=IF(FALSE, 1, "")', 7.0])
def test_new_section_goes_below_cells_that_display_blank(tmp_path: Path, entered: object) -> None:
    grid = [list(row) for row in ASSUMPTIONS_GRID] + [[], ["", ""]]
    sheet = JournalWorksheet(grid, sheet_id=2002, entered={(4, 1): entered})
    scenario = Scenario(tmp_path, assumptions=sheet)

    scenario.record([_recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")])

    # Row 5 holds a formula / typed number shown blank: two blank rows follow it.
    assert sheet.grid[7] == [JOURNAL_MARKER]
    assert sheet.tagged_grid()[4][1]["userEnteredValue"] is not None


def test_additive_entry_in_the_transfer_category_is_not_counted(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _adjustment(
        "additive",
        category=reconcile.INTERNAL_TRANSFER_CATEGORY,
        signed_amount=Decimal("50.00"),
    )
    scenario.record([entry])
    ledger = scenario.ledger()
    assert ledger.applied == (entry.adjustment_id,)
    assert _cells(ledger) == SOURCE_CELLS and ledger.deltas == ()
    assert [a.counted for a in ledger.allocations if a.origin == "additive"] == [False]


# --------------------------------------------------------------------------------------
# Journal structure and layout (fail closed)
# --------------------------------------------------------------------------------------


def _structure_rows(case: str, check: Transaction) -> list[list[str]]:
    a = _stamped(_recategorize(check, "Classroom Supplies", "Field Trips"))
    b = _stamped(_reverse(a))
    if case == "duplicate_adjustment_conflict":
        return [_journal_row(a), _journal_row(dataclasses.replace(a, reason="Other"))]
    if case == "supersedes_unknown":
        return [_journal_row(_stamped(_reverse(_adjustment("reversal", supersedes=None))))]
    if case == "supersedes_not_earlier":
        # A cycle: each entry supersedes the other.
        return [
            _journal_row(dataclasses.replace(a, supersedes=b.adjustment_id)),
            _journal_row(b),
        ]
    if case == "self_superseding":
        return [_journal_row(dataclasses.replace(a, supersedes=a.adjustment_id))]
    assert case == "competing_supersession"
    return [_journal_row(a), _journal_row(b), _journal_row(_stamped(_reverse(a)))]


STRUCTURE_CASES = {
    "duplicate_adjustment_conflict": ["duplicate_adjustment_conflict"],
    "supersedes_unknown": ["supersedes_unknown"],
    "supersedes_not_earlier": ["supersedes_not_earlier"],
    "self_superseding": ["supersedes_not_earlier"],
    "competing_supersession": ["competing_supersession", "competing_supersession"],
}


@pytest.mark.parametrize("case", sorted(STRUCTURE_CASES))
def test_broken_journal_structure_applies_nothing(tmp_path: Path, case: str) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    sheet = _journal_sheet(*_structure_rows(case, check))
    scenario = Scenario(tmp_path, assumptions=sheet)

    ledger = scenario.ledger()

    assert _codes(ledger.conflicts) == STRUCTURE_CASES[case]
    assert ledger.applied == () and _cells(ledger) == SOURCE_CELLS and not ledger.publishable

    # Recording onto a conflicting journal is refused until it is resolved.
    extra = _adjustment("additive", category="Donations", signed_amount=Decimal("1.00"))
    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.record([extra])
    assert caught.value.code == "proposal_conflict"
    assert scenario.sheet.batch_update_calls == []


def test_identical_duplicate_rows_apply_once_with_a_warning(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    entry = _stamped(_recategorize(check, "Classroom Supplies", "Field Trips"))
    later = dataclasses.replace(entry, recorded_at=RECORDED_AT + timedelta(minutes=5))
    sheet = _journal_sheet(_journal_row(entry), _journal_row(later))

    ledger = Scenario(tmp_path, assumptions=sheet).ledger()

    assert ledger.publishable and ledger.applied == (entry.adjustment_id,)
    assert [(w.code, w.severity, w.row_number) for w in ledger.warnings] == [
        ("duplicate_adjustment_row", "warning", 9)
    ]
    assert _cells(ledger)[("Field Trips", "2030-01")] == Decimal("-115.50")


def _layout_sheet(case: str) -> JournalWorksheet:
    grid = [list(row) for row in ASSUMPTIONS_GRID] + [[], []]
    header = list(JOURNAL_COLUMNS)
    layouts: dict[str, list[list[str]]] = {
        "journal_marker_invalid": [["PTA_REPORT_ADJUSTMENTS_V2"], header],
        "journal_marker_duplicate": [[JOURNAL_MARKER], header, [JOURNAL_MARKER]],
        "journal_marker_misplaced": [["", JOURNAL_MARKER], ["", *header]],
        "journal_header_mismatch": [[JOURNAL_MARKER], header[:-1]],
        "journal_foreign_content": [[JOURNAL_MARKER], header, [""] * 12 + ["note"]],
        "marker_row_content": [[JOURNAL_MARKER, "note"], header],
        "journal_formula_cell": [[JOURNAL_MARKER], header, ["=A1"]],
        "marker_text_above_journal": [["", "", JOURNAL_MARKER], [JOURNAL_MARKER], header],
        "marker_like_entry_id": [[JOURNAL_MARKER], header, ["pta_report_adjustments_x"]],
    }
    return JournalWorksheet(grid + layouts[case], sheet_id=2002)


LAYOUT_CASES = {
    "journal_marker_invalid": "journal_marker_invalid",
    "journal_marker_duplicate": "journal_marker_duplicate",
    "journal_marker_misplaced": "journal_marker_misplaced",
    "journal_header_mismatch": "journal_header_mismatch",
    "journal_foreign_content": "journal_foreign_content",
    "marker_row_content": "journal_foreign_content",
    "journal_formula_cell": "journal_formula_cell",
    "marker_text_above_journal": "journal_marker_misplaced",
    "marker_like_entry_id": "journal_marker_invalid",
}


@pytest.mark.parametrize("case", sorted(LAYOUT_CASES))
def test_unsafe_journal_layout_fails_closed(tmp_path: Path, case: str) -> None:
    scenario = Scenario(tmp_path, assumptions=_layout_sheet(case))
    capture_set, _ = scenario.capture()

    with pytest.raises(JournalLayoutError) as caught:
        read_journal(capture_set.assumptions)

    assert caught.value.code == LAYOUT_CASES[case]
    with pytest.raises(JournalLayoutError):
        scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(1))])
    assert scenario.sheet.batch_update_calls == []


def test_oversized_journal_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    rows = [_journal_row(_stamped(_recategorize(check, "Classroom Supplies", "Fees")))] * 2
    capture_set, _ = Scenario(tmp_path, assumptions=_journal_sheet(*rows)).capture()
    monkeypatch.setattr(adjustments, "MAX_JOURNAL_ENTRIES", 1)

    with pytest.raises(JournalLayoutError) as caught:
        read_journal(capture_set.assumptions)
    assert caught.value.code == "journal_too_large"


def test_full_journal_refuses_new_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = Scenario(tmp_path)
    scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(1))])
    monkeypatch.setattr(adjustments, "MAX_JOURNAL_ENTRIES", 1)

    with pytest.raises(AdjustmentError) as caught:
        scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(2))])
    assert caught.value.code == "journal_full"
    assert len(scenario.sheet.batch_update_calls) == 1


def test_only_an_assumptions_capture_holds_the_journal(tmp_path: Path) -> None:
    capture_set, _ = Scenario(tmp_path).capture()
    with pytest.raises(AdjustmentError) as caught:
        read_journal(capture_set.by_alias["bank-checking"])
    assert caught.value.code == "not_assumptions_capture"


def _valid_row(check: Transaction) -> list[str]:
    return _journal_row(
        _stamped(
            _adjustment(
                "amount_correction",
                check,
                category="Classroom Supplies",
                prior_value="-75.50",
                replacement_value="-70.00",
            )
        )
    )


GOOD_KEY = "v1:bank-checking:" + "a" * 64 + ":0"
GOOD_REV = "b" * 64
ROW_CASES: dict[str, tuple[dict[int, str], list[str]]] = {
    "invalid_id": ({0: "ADJ-123"}, ["invalid_adjustment_id"]),
    "missing_id": ({0: ""}, ["missing_field"]),
    "uuid_not_v4": ({0: "ADJ-" + "1" * 32}, ["invalid_adjustment_id"]),
    "payment_kind": ({2: "payment"}, ["unknown_kind"]),
    "missing_kind": ({2: ""}, ["missing_field"]),
    "invalid_date": ({3: "31/31/2030"}, ["invalid_date"]),
    "missing_date": ({3: ""}, ["missing_field"]),
    "invalid_money": ({5: "-70.001"}, ["invalid_money"]),
    "target_without_revision": ({1: GOOD_KEY}, ["invalid_target"]),
    "target_bad_revision": ({1: f"{GOOD_KEY}@{'g' * 64}"}, ["invalid_target"]),
    "target_short_revision": ({1: f"{GOOD_KEY}@{'b' * 63}"}, ["invalid_target"]),
    "target_extra_part": ({1: f"{GOOD_KEY}:1@{GOOD_REV}"}, ["invalid_target"]),
    "target_version": ({1: f"v2{GOOD_KEY[2:]}@{GOOD_REV}"}, ["invalid_target"]),
    "target_alias": (
        {1: f"{GOOD_KEY.replace('bank-checking', 'Bank Checking')}@{GOOD_REV}"},
        ["invalid_target"],
    ),
    "target_digest": (
        {1: f"{GOOD_KEY.replace('a' * 64, 'a' * 63 + 'g')}@{GOOD_REV}"},
        ["invalid_target"],
    ),
    "target_occurrence": ({1: f"{GOOD_KEY[:-1]}x@{GOOD_REV}"}, ["invalid_target"]),
    "missing_reason": ({8: ""}, ["missing_field"]),
    "missing_evidence": ({9: ""}, ["missing_field"]),
    "empty_evidence_item": ({9: "a;;b"}, ["invalid_evidence"]),
    "missing_recorded_at": ({10: ""}, ["missing_field"]),
    "naive_recorded_at": ({10: "2030-02-01T12:00:00"}, ["invalid_timestamp"]),
    "invalid_recorded_at": ({10: "yesterday"}, ["invalid_timestamp"]),
    "invalid_supersedes": ({11: "ADJ-x"}, ["invalid_adjustment_id"]),
    "too_long": ({8: "x" * (adjustments.MAX_FIELD_TEXT + 1)}, ["field_too_long"]),
    "too_long_evidence": ({9: "x" * (adjustments.MAX_FIELD_TEXT + 1)}, ["field_too_long"]),
    "unexpected_signed_amount": ({6: "5.00"}, ["unexpected_field"]),
    "missing_category": ({7: ""}, ["missing_field"]),
    "no_op": ({5: "-75.50"}, ["no_op_correction"]),
}


@pytest.mark.parametrize("case", sorted(ROW_CASES))
def test_unreadable_journal_rows_block_publication(tmp_path: Path, case: str) -> None:
    edits, codes = ROW_CASES[case]
    check = Scenario(tmp_path / "ids").txn(CHECK)
    row = _valid_row(check)
    for column, value in edits.items():
        row[column] = value
    capture_set, rec = Scenario(tmp_path, assumptions=_journal_sheet(row)).capture()

    journal = read_journal(capture_set.assumptions)
    ledger = project(rec, journal, AS_OF)

    assert _codes(journal.issues) == codes and journal.entries == ()
    assert {issue.row_number for issue in journal.issues} == {8}
    assert ledger.conflicts == journal.issues and not ledger.publishable
    assert _cells(ledger) == SOURCE_CELLS


def test_recording_onto_an_unreadable_journal_is_refused(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    row = _valid_row(check)
    row[3] = "not a date"
    scenario = Scenario(tmp_path, assumptions=_journal_sheet(row))
    with pytest.raises(AdjustmentConflictError) as caught:
        scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(1))])
    assert caught.value.code == "journal_invalid"
    assert _codes(caught.value.issues) == ["invalid_date"]
    assert scenario.sheet.batch_update_calls == []


def test_typed_numbers_in_the_journal_must_match_their_display(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    sheet = _journal_sheet(_valid_row(check))
    sheet.entered[(7, 5)] = -70.004  # display "-70.00" hides sub-cent precision
    capture_set, _ = Scenario(tmp_path, assumptions=sheet).capture()

    journal = read_journal(capture_set.assumptions)
    assert _codes(journal.issues) == ["display_precision_mismatch"]

    sheet.entered[(7, 5)] = -70.0
    capture_set, rec = Scenario(tmp_path / "ok", assumptions=sheet).capture()
    ledger = project(rec, read_journal(capture_set.assumptions), AS_OF)
    assert ledger.publishable and len(ledger.applied) == 1


def test_manual_rows_in_display_formats_are_accepted(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    row = _valid_row(check)
    row[3] = "1/31/2030"
    row[4] = "($75.50)"
    row[5] = "$ (70.00)"
    capture_set, rec = Scenario(tmp_path, assumptions=_journal_sheet(row)).capture()
    ledger = project(rec, read_journal(capture_set.assumptions), AS_OF)
    assert ledger.publishable
    assert _cells(ledger)[("Classroom Supplies", "2030-01")] == Decimal("-70.00")


def test_journal_hash_follows_the_recorded_region(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    row = _valid_row(check)
    first = read_journal(
        Scenario(tmp_path / "a", assumptions=_journal_sheet(row)).capture()[0].assumptions
    )
    again = read_journal(
        Scenario(tmp_path / "b", assumptions=_journal_sheet(row)).capture()[0].assumptions
    )
    edited = list(row)
    edited[8] = "Edited reason"
    other = read_journal(
        Scenario(tmp_path / "c", assumptions=_journal_sheet(edited)).capture()[0].assumptions
    )
    absent = read_journal(Scenario(tmp_path / "d").capture()[0].assumptions)

    assert first.sha256 == again.sha256
    assert len({first.sha256, other.sha256, absent.sha256}) == 3
    assert (
        project(Scenario(tmp_path / "e").capture()[1], first, AS_OF).journal_sha256 == first.sha256
    )


# --------------------------------------------------------------------------------------
# Proposal files
# --------------------------------------------------------------------------------------


def _proposal_payload(check: Transaction, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "adjustment_id": make_adjustment_id(),
        "kind": "category_override",
        "effective_date": "2030-01-31",
        "targets": [{"record_key": check.record_key, "revision_hash": check.revision_hash}],
        "prior_value": "Classroom Supplies",
        "replacement_value": "Field Trips",
        "signed_amount": None,
        "category": None,
        "reason": "Example correction",
        "evidence": ["example-statement-2030-01"],
        "supersedes": None,
    }
    item.update(overrides)
    return item


def _file(*items: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "adjustments": list(items)}


def test_proposals_file_round_trips_to_the_journal(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    check = scenario.txn(CHECK)
    item = _proposal_payload(check, reason="  Example correction  ")
    path = tmp_path / "proposals.json"
    path.write_text(json.dumps(_file(item)), encoding="utf-8")

    (proposal,) = load_proposals(path)

    assert proposal.reason == "Example correction"
    assert proposal.recorded_at is None
    result = scenario.record([proposal])
    (entry,) = result.journal.entries
    assert entry.adjustment.fingerprint() == proposal.fingerprint()
    assert set(JOURNAL_COLUMNS) == set(entry.adjustment.to_dict())


def _signed(**overrides: Any) -> dict[str, Any]:
    base = {
        "kind": "additive",
        "targets": [],
        "prior_value": None,
        "replacement_value": None,
        "signed_amount": "25.00",
        "category": "Donations",
    }
    base.update(overrides)
    return base


PROPOSAL_CASES: dict[str, tuple[dict[str, Any], list[str]]] = {
    "approval_kind": ({"kind": "approve_claim"}, ["unknown_kind"]),
    "formula_category": ({"replacement_value": "=HYPERLINK(1)"}, ["invalid_category"]),
    "control_category": ({"replacement_value": "Field\x07Trips"}, ["invalid_category"]),
    "long_category": ({"replacement_value": "x" * 101}, ["invalid_category"]),
    "additive_formula_category": (_signed(category="+Donations"), ["invalid_category"]),
    "payment_kind": ({"kind": "payment"}, ["unknown_kind"]),
    "recorded_at": ({"recorded_at": "2030-02-01T00:00:00Z"}, ["unexpected_field"]),
    "unknown_field": ({"approved": True}, ["unexpected_field"]),
    "number_money": (_signed(signed_amount=25.0), ["invalid_type"]),
    "invalid_money": (_signed(signed_amount="25.001"), ["invalid_money"]),
    "dash_money": (_signed(signed_amount="-"), ["invalid_money"]),
    "targets_not_list": ({"targets": "x"}, ["invalid_type"]),
    "target_extra_key": (
        {"targets": [{"record_key": GOOD_KEY, "revision_hash": GOOD_REV, "x": "c"}]},
        ["invalid_target"],
    ),
    "target_not_string": (
        {"targets": [{"record_key": GOOD_KEY, "revision_hash": int("1" * 64)}]},
        ["invalid_target"],
    ),
    "target_count": ({"targets": []}, ["target_count_invalid"]),
    "evidence_not_list": ({"evidence": "ref"}, ["invalid_type", "missing_field"]),
    "evidence_separator": ({"evidence": ["a;b"]}, ["invalid_evidence"]),
    "evidence_empty": ({"evidence": []}, ["missing_field"]),
    "missing_reason": ({"reason": None}, ["missing_field"]),
    "two_representations": ({"signed_amount": "5.00"}, ["unexpected_field"]),
    "replacement_missing": ({"replacement_value": None}, ["missing_field"]),
    "category_on_override": ({"category": "Fees"}, ["unexpected_field"]),
    "no_op": ({"replacement_value": "Classroom Supplies"}, ["no_op_correction"]),
    "additive_with_target": (
        _signed(targets=[{"record_key": "k", "revision_hash": "r"}]),
        ["invalid_target"],
    ),
    "additive_zero": (_signed(signed_amount="0.00"), ["no_op_correction"]),
    "additive_plug": (
        _signed(evidence=["DISC-" + "a" * 64]),
        ["additive_evidence_not_independent"],
    ),
    "additive_replacement": (_signed(replacement_value="5.00"), ["unexpected_field"]),
    "reversal_without_target": (
        {"kind": "reversal", "targets": [], "prior_value": None, "replacement_value": None},
        ["missing_field"],
    ),
    "invalid_supersedes": ({"supersedes": "ADJ-1"}, ["invalid_adjustment_id"]),
    "date_override_bad_date": (
        {"kind": "date_override", "prior_value": "2030-01-09", "replacement_value": "soon"},
        ["invalid_date"],
    ),
    "not_an_object": ({"__replace__": "x"}, ["invalid_type"]),
}


@pytest.mark.parametrize("case", sorted(PROPOSAL_CASES))
def test_invalid_proposals_are_rejected_with_codes(tmp_path: Path, case: str) -> None:
    overrides, codes = PROPOSAL_CASES[case]
    check = Scenario(tmp_path).txn(CHECK)
    item: Any = "x" if "__replace__" in overrides else _proposal_payload(check, **overrides)

    with pytest.raises(ProposalError) as caught:
        parse_proposals(_file(item))

    assert _codes(caught.value.issues) == codes
    assert caught.value.code == "proposals_invalid"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ([], "proposals_shape"),
        ({"schema_version": 1}, "proposals_shape"),
        ({"schema_version": 2, "adjustments": []}, "unsupported_schema_version"),
        ({"schema_version": True, "adjustments": []}, "unsupported_schema_version"),
        ({"schema_version": 1, "adjustments": {}}, "proposals_shape"),
        ({"schema_version": 1, "adjustments": []}, "no_proposals"),
    ],
)
def test_proposal_file_shape_is_exact(payload: Any, code: str) -> None:
    with pytest.raises(ProposalError) as caught:
        parse_proposals(payload)
    assert _codes(caught.value.issues) == [code]


def test_proposal_batch_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    check = Scenario(tmp_path).txn(CHECK)
    item = _proposal_payload(check)
    with pytest.raises(ProposalError) as caught:
        parse_proposals(_file(item, dict(item)))
    assert _codes(caught.value.issues) == ["duplicate_proposal_id"]

    monkeypatch.setattr(adjustments, "MAX_PROPOSALS", 1)
    with pytest.raises(ProposalError) as caught:
        parse_proposals(_file(item, _proposal_payload(check)))
    assert _codes(caught.value.issues) == ["too_many_proposals"]


def test_record_validates_the_batch_itself(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    for proposals, code in (
        ([], "no_proposals"),
        ([_stamped(entry)], "unexpected_field"),
        ([entry, entry], "duplicate_proposal_id"),
    ):
        with pytest.raises(ProposalError) as caught:
            scenario.record(proposals)
        assert _codes(caught.value.issues) == [code]
    assert scenario.sheet.batch_update_calls == []


def test_unreadable_proposal_files(tmp_path: Path) -> None:
    with pytest.raises(AdjustmentError) as missing:
        load_proposals(tmp_path / "absent.json")
    assert missing.value.code == "proposals_unreadable"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(AdjustmentError) as invalid:
        load_proposals(bad)
    assert invalid.value.code == "proposals_invalid_json"
    assert invalid.value.__cause__ is None and invalid.value.__suppress_context__
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe{}")
    with pytest.raises(AdjustmentError) as undecodable:
        load_proposals(binary)
    assert undecodable.value.code == "proposals_unreadable"


def test_proposal_file_size_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "proposals.json"
    path.write_text(json.dumps({"schema_version": 1, "adjustments": []}), encoding="utf-8")
    monkeypatch.setattr(adjustments, "MAX_PROPOSALS_FILE_BYTES", len(path.read_bytes()) - 1)
    with pytest.raises(AdjustmentError) as caught:
        load_proposals(path)
    assert caught.value.code == "proposals_too_large"
    monkeypatch.setattr(adjustments, "MAX_PROPOSALS_FILE_BYTES", len(path.read_bytes()))
    with pytest.raises(ProposalError):  # read in full: the (empty) batch itself is invalid
        load_proposals(path)


# --------------------------------------------------------------------------------------
# Writer lock, workbook binding and client scope
# --------------------------------------------------------------------------------------


def test_writer_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    config = _config(tmp_path)
    root = config.main_reports.output_path  # type: ignore[union-attr]
    with acquire_run_lock(config) as lock:
        assert lock.path == root / LOCK_FILENAME and lock.path.exists()
        with pytest.raises(RunBusyError) as caught:
            acquire_run_lock(config)
        assert caught.value.code == "run_busy"
    assert not lock.path.exists() and not lock.held
    lock.release()  # idempotent


def test_release_never_removes_another_writers_lock(tmp_path: Path) -> None:
    config = _config(tmp_path)
    lock = acquire_run_lock(config)
    lock.path.write_text(json.dumps({"token": "someone-else"}), encoding="utf-8")
    lock.release()
    assert lock.path.exists()
    lock.path.write_text("not json", encoding="utf-8")
    other = adjustments.RunLock(path=lock.path, token="x")
    other.release()
    assert lock.path.exists()


def test_record_requires_the_held_lock(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    capture_set, rec = scenario.capture()
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    released = acquire_run_lock(scenario.config)
    released.release()
    # Marked released while its file (and token) still exist.
    stale = acquire_run_lock(scenario.config)
    stale.held = False
    # A valid-looking lock file with a matching token, but outside the configured root.
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / LOCK_FILENAME).write_text(json.dumps({"token": "x"}), encoding="utf-8")
    elsewhere = adjustments.RunLock(path=tmp_path / "other" / LOCK_FILENAME, token="x")
    for lock in (released, stale, elsewhere):
        with pytest.raises(AdjustmentError) as caught:
            record(
                [entry],
                config=scenario.config,
                client=scenario.harness.own(),
                captured=capture_set.assumptions,
                reconciliation=rec,
                as_of=AS_OF,
                lock=lock,
            )
        assert caught.value.code == "lock_not_held"
    scenario.harness.assert_no_writes()


def test_journal_is_never_written_to_the_cfo_workbook(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    harness = scenario.harness
    refused = {
        CFO_ID: FakeClient(harness.cfo_spreadsheet),
        scenario.config.sheets.test_spreadsheet_id: FakeClient(harness.own_spreadsheet),
    }
    for spreadsheet_id, fake in refused.items():
        client = SheetsClient(scenario.config, spreadsheet_id=spreadsheet_id, gspread_client=fake)  # type: ignore[arg-type]
        with pytest.raises(AdjustmentError) as caught:
            scenario.record([entry], client=client)
        assert caught.value.code == "journal_target_not_own_workbook"
        assert fake.opened_keys == []  # refused before any read
    harness.assert_no_writes()


def test_source_bound_to_our_own_workbook_is_refused(tmp_path: Path) -> None:
    toml = _FULL_CONFIG + main_reports_toml().replace(CFO_ID, "fake-spreadsheet-id")
    scenario = Scenario(tmp_path)
    config = _config(tmp_path / "own", toml)
    capture_set, rec = scenario.capture()
    with acquire_run_lock(config) as lock, pytest.raises(AdjustmentError) as caught:
        record(
            [_recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")],
            config=config,
            client=SheetsClient(config, gspread_client=scenario.harness.own_client),
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
        )
    assert caught.value.code == "journal_target_not_own_workbook"


def test_journal_client_has_write_scope_and_a_finite_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    calls: list[dict[str, Any]] = []
    fake = TimeoutClient(scenario.harness.own_spreadsheet)

    def fake_service_account(**kwargs: Any) -> TimeoutClient:
        calls.append(kwargs)
        return fake

    monkeypatch.setattr(adjustments.gspread, "service_account", fake_service_account)
    client = connect_journal_client(scenario.config, sleep=RecordingSleep())

    assert calls == [
        {"filename": str(scenario.config.google.service_account_path), "scopes": [WRITE_SCOPE]}
    ]
    assert fake.timeouts == [adjustments.HTTP_TIMEOUT_SECONDS]
    assert client.spreadsheet_id == scenario.config.sheets.spreadsheet_id
    injected = connect_journal_client(scenario.config, gspread_client=fake)  # type: ignore[arg-type]
    assert injected.spreadsheet_id == scenario.config.sheets.spreadsheet_id


def test_main_reports_section_is_required(fake_config: Config) -> None:
    with pytest.raises(AdjustmentError) as caught:
        acquire_run_lock(fake_config)
    assert caught.value.code == "main_reports_missing"


# --------------------------------------------------------------------------------------
# Invariants: source preservation, privacy, no reimbursement authority
# --------------------------------------------------------------------------------------


def test_projection_requires_a_consistent_source_view(tmp_path: Path) -> None:
    capture_set, rec = Scenario(tmp_path).capture()
    tampered = dataclasses.replace(rec, monthly_cells=rec.monthly_cells[1:])
    with pytest.raises(AdjustmentError) as caught:
        project(tampered, read_journal(capture_set.assumptions), AS_OF)
    assert caught.value.code == "source_view_mismatch"


def test_reporting_corrections_cannot_approve_or_pay(tmp_path: Path) -> None:
    assert not any(word in kind for kind in ADJUSTMENT_KINDS for word in ("approv", "pay"))
    tree = ast.parse(inspect.getsource(adjustments))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("reimbursement" in name or "receipt" in name for name in imported)


def test_error_text_never_carries_cell_or_money_values(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    check = scenario.txn(CHECK)
    canary = "CANARY-SECRET-4417"
    proposal = _adjustment(
        "amount_correction",
        check,
        category="Classroom Supplies",
        prior_value="-75.51",
        replacement_value="-71.13",
        reason=canary,
        evidence=(canary,),
    )
    errors: list[BaseException] = []
    with pytest.raises(AdjustmentConflictError) as conflict:
        scenario.record([proposal])
    errors.append(conflict.value)
    for overrides in (
        {"reason": canary, "evidence": [canary], "kind": canary},
        {"adjustment_id": canary, canary: "x"},
    ):
        with pytest.raises(ProposalError) as invalid:
            parse_proposals(_file(_proposal_payload(check, **overrides)))
        errors.append(invalid.value)
    row = _valid_row(check)
    row[8] = canary
    row[5] = "-71.13x"
    capture_set, rec = Scenario(tmp_path / "rows", assumptions=_journal_sheet(row)).capture()
    ledger = project(rec, read_journal(capture_set.assumptions), AS_OF)
    with pytest.raises(AdjustmentConflictError) as blocked:
        require_publishable(ledger)
    errors.append(blocked.value)

    for error in errors:
        chain = [error, error.__cause__, error.__context__]
        text = " ".join(repr(item) + str(item) for item in chain if item is not None)
        for secret in (canary, "75.51", "71.13", "Classroom Supplies"):
            assert secret not in text
    assert all(canary not in json.dumps(i.to_dict()) for i in ledger.conflicts)


def test_journal_and_ledger_records_serialize_canonically(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    scenario.record([_recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")])
    capture_set, _ = scenario.capture()
    journal = read_journal(capture_set.assumptions)
    payload = json.loads(canonical_json_bytes(journal.to_dict()))
    assert payload["marker_row"] == 6
    assert payload["entries"][0]["adjustment"]["recorded_at"].endswith("Z")
    assert isinstance(journal, AdjustmentJournal)


# --------------------------------------------------------------------------------------
# Order independence, marker text, transport failures, lock and evidence
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("order", ["x_to_y_first", "y_to_z_first"])
def test_overrides_match_source_categories_in_any_order(tmp_path: Path, order: str) -> None:
    scenario = Scenario(tmp_path)
    deposit = scenario.txn(DEPOSIT)
    x_to_y = _recategorize(deposit, "Fundraiser Income", "Processing Fees")
    y_to_z = _recategorize(deposit, "Processing Fees", "Fees and Charges")
    entries = [x_to_y, y_to_z] if order == "x_to_y_first" else [y_to_z, x_to_y]
    for entry in entries:  # separate writes, so journal row order differs per case
        scenario.record([entry])

    ledger = scenario.ledger()

    # Each override moves only its own SOURCE allocation: nothing is chained.
    assert ledger.publishable and len(ledger.applied) == 2
    cells = _cells(ledger)
    assert cells[("Processing Fees", "2030-01")] == Decimal("1280.00")
    assert cells[("Fees and Charges", "2030-01")] == Decimal("-30.00")
    assert ("Fundraiser Income", "2030-01") not in cells
    _assert_conserved(ledger)


def test_overrides_of_one_source_allocation_compete_in_any_order(tmp_path: Path) -> None:
    check = Scenario(tmp_path / "ids").txn(CHECK)
    one = _stamped(_recategorize(check, "Classroom Supplies", "Field Trips"))
    two = _stamped(_recategorize(check, "Classroom Supplies", "Donations"))
    for rows in ([one, two], [two, one]):
        sheet = _journal_sheet(*map(_journal_row, rows))
        ledger = Scenario(tmp_path / str(id(rows)), assumptions=sheet).ledger()
        assert _codes(ledger.conflicts) == ["competing_replacement", "competing_replacement"]
        assert _cells(ledger) == SOURCE_CELLS


def test_marker_text_in_entry_fields_round_trips(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    hostile = [
        _recategorize(
            scenario.txn(CHECK),
            "Classroom Supplies",
            "PTA_REPORT_ADJUSTMENTS_V1 supplies",
            reason=JOURNAL_MARKER,
            evidence=("pta_report_adjustments_v2-note",),
        ),
        _adjustment(
            "additive",
            category="pta_report_adjustments_v1",
            signed_amount=Decimal("5.00"),
            reason="PTA_REPORT_ADJUSTMENTS_V2 reason",
        ),
    ]
    scenario.record(hostile)
    scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(1))])

    journal = read_journal(scenario.capture()[0].assumptions)
    assert [dataclasses.replace(e.adjustment, recorded_at=None) for e in journal.entries][
        :2
    ] == hostile
    assert scenario.ledger().publishable


def _http_error(status: int) -> BaseException:
    """A non-gspread transport error carrying an HTTP status (requests.HTTPError shape)."""
    response = Response()
    response.status_code = status
    return requests.HTTPError("rejected", response=response)


# Stands for "transient failures until the client's attempt cap is spent" (the count comes
# from the client policy itself, never restated here).
EXHAUST = "exhaust"
WRITE_FAILURES: dict[str, tuple[Any, BaseException | None, str | None]] = {
    # name: (batch failures queued before any write lands, raise after landing, cause)
    "landed_then_503": ([], make_api_error(503), None),
    "503_then_retry": ([make_api_error(503)], None, None),
    "timeout_then_retry": ([ConnectionError("timeout")], None, None),
    "429_429_then_ok": ([make_api_error(429), make_api_error(429)], None, None),
    "503_503_then_ok": ([make_api_error(503), make_api_error(503)], None, None),
    # A later attempt lands but its response is lost: the readback ends the loop.
    "503_then_landed_then_503": ([make_api_error(503)], make_api_error(503), None),
    "transient_exhausted": (EXHAUST, None, "APIError 503"),
    # An unobserved first attempt can still land even when the retry is then rejected.
    "timeout_then_rejected": (
        [ConnectionError("timeout"), make_api_error(403)],
        None,
        "APIError 403",
    ),
    "503_then_403": ([make_api_error(503), make_api_error(403)], None, "APIError 403"),
    # A status the writer does not re-send (not transient, not a clean rejection).
    "not_resent_409": ([make_api_error(409), make_api_error(409)], None, "APIError 409"),
    "not_resent_502": ([make_api_error(502), make_api_error(502)], None, "APIError 502"),
    "rejected_400": ([make_api_error(400), make_api_error(400)], None, "APIError 400"),
    "rejected_401": ([make_api_error(401), make_api_error(401)], None, "APIError 401"),
    "rejected_403": ([make_api_error(403), make_api_error(403)], None, "APIError 403"),
    "rejected_404": ([make_api_error(404), make_api_error(404)], None, "APIError 404"),
    "rejected_http_403": ([_http_error(403), _http_error(403)], None, "HTTPError 403"),
}


def _attempt_cap(client: SheetsClient) -> int:
    """How many attempts the client's retry policy allows one call."""
    return next(n for n in itertools.count(1) if client.backoff_delay(n) is None)


def _single_attempt_client(scenario: Scenario) -> SheetsClient:
    """One attempt per call: SheetsClient's own retry is exhausted, record() decides."""
    return SheetsClient(
        scenario.config,
        gspread_client=scenario.harness.own_client,  # type: ignore[arg-type]
        sleep=RecordingSleep(),
        max_retries=1,
    )


@pytest.mark.parametrize("case", sorted(WRITE_FAILURES))
def test_api_errors_during_the_write_are_resolved_by_reading_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    queued, after_landing, failed_cause = WRITE_FAILURES[case]
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    sheet = scenario.sheet
    # The production client policy (default attempts, backoff); its sleep is recorded and
    # the jitter draw is fixed so every pause can be compared with the policy's own value.
    monkeypatch.setattr(sheets_module.random, "uniform", lambda low, high: (low + high) / 2)
    sleep = RecordingSleep()
    client = SheetsClient(
        scenario.config,
        gspread_client=scenario.harness.own_client,  # type: ignore[arg-type]
        sleep=sleep,
    )
    if queued == EXHAUST:
        queued = [make_api_error(503) for _ in range(_attempt_cap(client))]
    sheet._fail_first["batch_update"] = list(queued)
    if after_landing is not None:
        sheet.after_batch_update = _raise_once(after_landing)
    policy = [client.backoff_delay(n) for n in range(1, len(queued) + 1)]

    if failed_cause is None:
        result = scenario.record([entry], client=client)
        assert result.written == (entry.adjustment_id,)
        assert result.attempts == len(queued) + 1  # the landing attempt ends the loop
        assert len(sheet.batch_update_calls) == 1  # exactly one landed write
        assert scenario.ledger().applied == (entry.adjustment_id,)
        # The client's backoff ran before every re-send, with the policy's own delays.
        assert sleep.calls == policy[: result.attempts - 1]
        return
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry], client=client)
    assert caught.value.code == "write_failed"
    # Only a first attempt rejected outright, with the tab unchanged, cannot have landed.
    assert caught.value.may_have_landed is (not case.startswith("rejected"))
    assert caught.value.cause == failed_cause and failed_cause in str(caught.value)
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()
    rejected = case.startswith("rejected")
    not_resent = rejected or case.startswith("not_resent")
    # A refused or non-transient status is never re-sent: one attempt, the second unused.
    assert len(sheet._fail_first["batch_update"]) == (1 if not_resent else 0)
    attempts = 1 if not_resent else len(queued)
    assert sleep.calls == policy[: attempts - 1]  # a pause before every re-send, none after
    assert sheet.batch_update_calls == []
    if rejected:
        assert "rejected; nothing was recorded" in str(caught.value)
    else:  # ambiguous: never claims that nothing was recorded
        assert "MAY still land" in str(caught.value) and "nothing" not in str(caught.value)
    assert read_journal(scenario.capture()[0].assumptions).marker_row is None


class _LateLandingSheet(JournalWorksheet):
    """The ``defer_call``-th write request times out but lands later, while the writer
    pauses (:meth:`land`); earlier calls behave as usual (queued failures included)."""

    defer_call = 1
    calls = 0
    deferred: tuple[list[dict[str, Any]], str | None] | None = None

    def batch_update(
        self, data: Iterable[Mapping[str, Any]], value_input_option: str | None = None
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == self.defer_call:
            self.deferred = ([dict(request) for request in data], value_input_option)
            raise requests.exceptions.ReadTimeout("fictional timeout")
        return super().batch_update(data, value_input_option)

    def land(self) -> None:
        """Apply the deferred write (a pause before it was deferred lands nothing)."""
        if self.deferred is not None:
            deferred, self.deferred = self.deferred, None
            super().batch_update(*deferred)


def _pausing_client(scenario: Scenario, during_pause: Callable[[float], None]) -> SheetsClient:
    return SheetsClient(
        scenario.config,
        gspread_client=scenario.harness.own_client,  # type: ignore[arg-type]
        sleep=during_pause,
    )


def test_a_write_that_lands_during_the_pause_is_not_sent_again(tmp_path: Path) -> None:
    sheet = _LateLandingSheet([list(row) for row in ASSUMPTIONS_GRID], sheet_id=2002)
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    client = _pausing_client(scenario, lambda _seconds: sheet.land())

    result = scenario.record([entry], client=client)

    assert result.written == (entry.adjustment_id,) and result.attempts == 1
    assert len(sheet.batch_update_calls) == 1  # the late landing only; no re-send
    assert scenario.ledger().applied == (entry.adjustment_id,)


def test_a_write_that_lands_during_the_second_pause_is_not_sent_again(tmp_path: Path) -> None:
    sheet = _LateLandingSheet([list(row) for row in ASSUMPTIONS_GRID], sheet_id=2002)
    sheet.defer_call = 2
    sheet._fail_first["batch_update"] = [make_api_error(503)]  # the first attempt
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    pauses: list[float] = []

    def pause(seconds: float) -> None:
        pauses.append(seconds)
        sheet.land()

    result = scenario.record([entry], client=_pausing_client(scenario, pause))

    assert result.written == (entry.adjustment_id,) and result.attempts == 2
    assert sheet.calls == 2 and len(pauses) == 2  # no third send
    assert len(sheet.batch_update_calls) == 1  # the late landing only
    assert scenario.ledger().applied == (entry.adjustment_id,)


def test_the_lock_is_re_checked_before_the_readback_after_a_pause(tmp_path: Path) -> None:
    sheet = _LateLandingSheet([list(row) for row in ASSUMPTIONS_GRID], sheet_id=2002)
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    lock_path = scenario.config.main_reports.output_path / LOCK_FILENAME  # type: ignore[union-attr]

    def pause(_seconds: float) -> None:
        sheet.land()  # the write lands during the pause...
        lock_path.unlink()  # ...and the lock is lost too

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry], client=_pausing_client(scenario, pause))

    assert caught.value.code == "lock_not_held"
    assert caught.value.may_have_landed is True
    assert sheet.calls == 1  # nothing sent after the pause
    assert len(sheet.batch_update_calls) == 1  # only the late landing


def test_an_edit_during_the_pause_is_refused_and_not_overwritten(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet._fail_first["batch_update"] = [make_api_error(503)]
    client = _pausing_client(scenario, lambda _seconds: scenario.sheet.set_cell(1, 1, "2.5"))

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry], client=client)

    assert caught.value.code == "write_uncertain_conflict"
    assert caught.value.may_have_landed is True
    assert scenario.sheet.batch_update_calls == []  # never sent again over the edit
    assert scenario.sheet.grid[1][1] == "2.5"


def test_a_lock_lost_during_the_pause_stops_the_re_send(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet._fail_first["batch_update"] = [make_api_error(503)]
    lock_path = scenario.config.main_reports.output_path / LOCK_FILENAME  # type: ignore[union-attr]
    client = _pausing_client(scenario, lambda _seconds: lock_path.unlink())

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry], client=client)

    assert caught.value.code == "lock_not_held"
    assert caught.value.may_have_landed is True  # the first attempt is still unobserved
    assert scenario.sheet.batch_update_calls == []


def test_an_auth_refresh_failure_before_the_send_is_typed_and_cannot_have_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")

    def refresh_failed(*_args: Any, **_kwargs: Any) -> Path:
        raise RefreshError(f"{CFO_ID} fictional token text")

    monkeypatch.setattr(backup, "snapshot_raw_tab", refresh_failed)
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert (caught.value.code, caught.value.may_have_landed) == ("snapshot_failed", False)
    assert caught.value.cause == "RefreshError" and CFO_ID not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert scenario.sheet.batch_update_calls == []


def test_an_auth_transport_failure_after_the_send_is_typed_and_may_have_landed(
    tmp_path: Path,
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    sheet = scenario.sheet

    def readback_fails(ws: JournalWorksheet) -> None:
        ws.after_batch_update = None
        ws._fail_first["get_all_values"] = [TransportError(f"{CFO_ID} fictional text")]

    sheet.after_batch_update = readback_fails
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert (caught.value.code, caught.value.may_have_landed) == ("write_unverified", True)
    assert caught.value.cause == "TransportError" and CFO_ID not in str(caught.value)
    assert len(sheet.batch_update_calls) == 1


def test_a_failing_snapshot_hook_is_typed_and_nothing_is_sent(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    capture_set, rec = scenario.capture()

    def hook(_path: Path) -> None:
        raise RuntimeError("fictional hook failure")

    with acquire_run_lock(scenario.config) as lock, pytest.raises(AdjustmentWriteError) as caught:
        record(
            [entry],
            config=scenario.config,
            client=scenario.harness.own(),
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
            on_snapshot=hook,
        )
    assert caught.value.code == "snapshot_callback_failed"
    assert (caught.value.may_have_landed, caught.value.cause) == (False, "RuntimeError")
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert "fictional hook failure" not in str(caught.value)
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()
    assert scenario.sheet.batch_update_calls == []


def test_a_journal_unreadable_after_a_landed_write_is_typed_and_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    real = adjustments.read_journal
    before = scenario.capture()[0].assumptions.sha256

    def unreadable_once_written(capture: SourceCapture) -> AdjustmentJournal:
        if capture.sha256 != before:
            raise ValueError(f"{CFO_ID} fictional parse text")
        return real(capture)

    monkeypatch.setattr(adjustments, "read_journal", unreadable_once_written)
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert caught.value.code == "journal_unreadable_after_write"
    assert (caught.value.may_have_landed, caught.value.cause) == (True, "ValueError")
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert CFO_ID not in str(caught.value)
    snapshot, after = caught.value.evidence
    assert snapshot.exists() and after.exists()
    assert len(scenario.sheet.batch_update_calls) == 1


def _failing_reads(sheet: JournalWorksheet, fail_on: int, error: BaseException) -> None:
    """Make the ``fail_on``-th value read of ``sheet`` (0-based) raise ``error``."""
    original = sheet.get_all_values
    reads = itertools.count()

    def read(*, value_render_option: Any = None) -> list[list[str]]:
        if next(reads) == fail_on:
            raise error
        return original()

    sheet.get_all_values = read  # type: ignore[method-assign]


READ_ERRORS = {"timeout": ConnectionError("network down"), "api_503": make_api_error(503)}
READ_CAUSES = {"timeout": "ConnectionError", "api_503": "APIError 503"}


@pytest.mark.parametrize("read_error", sorted(READ_ERRORS))
@pytest.mark.parametrize("write_error", [None, make_api_error(503)])
def test_unreadable_readback_is_a_typed_unverified_result(
    tmp_path: Path, write_error: BaseException | None, read_error: str
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    if write_error is not None:
        scenario.sheet.after_batch_update = _raise_once(write_error)
    client = _single_attempt_client(scenario)
    capture_set, rec = scenario.capture()
    # record(): reads 0 and 1 are the pre-write checks; read 2 is the readback.
    _failing_reads(scenario.sheet, 2, READ_ERRORS[read_error])

    with acquire_run_lock(scenario.config) as lock, pytest.raises(AdjustmentWriteError) as caught:
        record(
            [entry],
            config=scenario.config,
            client=client,
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
        )

    assert caught.value.code == "write_unverified"
    assert caught.value.may_have_landed is True
    expected = READ_CAUSES[read_error] if write_error is None else "APIError 503"
    assert caught.value.cause == expected
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def _rename_tab(scenario: Scenario) -> Callable[[JournalWorksheet], None]:
    def missing(title: str) -> Any:
        raise WorksheetNotFound(title)

    def hook(sheet: JournalWorksheet) -> None:
        sheet.after_batch_update = None
        scenario.harness.own_spreadsheet.worksheet = missing  # type: ignore[method-assign]

    return hook


def _odd_metadata(scenario: Scenario) -> Callable[[JournalWorksheet], None]:
    def odd(params: Any) -> dict[str, Any]:
        return {"sheets": "unexpected"}

    def hook(sheet: JournalWorksheet) -> None:
        sheet.after_batch_update = None
        scenario.harness.own_spreadsheet.fetch_sheet_metadata = odd  # type: ignore[method-assign]

    return hook


@pytest.mark.parametrize(
    ("case", "cause"), [("renamed_tab", "WorksheetNotFound"), ("odd_metadata", "ValueError")]
)
def test_readback_of_a_renamed_tab_or_odd_metadata_is_typed(
    tmp_path: Path, case: str, cause: str
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    hook = _rename_tab(scenario) if case == "renamed_tab" else _odd_metadata(scenario)
    scenario.sheet.after_batch_update = hook

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])

    assert (caught.value.code, caught.value.cause) == ("write_unverified", cause)
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()


@pytest.mark.parametrize("read_error", sorted(READ_ERRORS))
@pytest.mark.parametrize("fail_on", [0, 1])
def test_pre_write_read_failures_are_typed(tmp_path: Path, read_error: str, fail_on: int) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    client = _single_attempt_client(scenario)
    capture_set, rec = scenario.capture()
    _failing_reads(scenario.sheet, fail_on, READ_ERRORS[read_error])

    with acquire_run_lock(scenario.config) as lock, pytest.raises(AdjustmentWriteError) as caught:
        record(
            [entry],
            config=scenario.config,
            client=client,
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
        )

    assert caught.value.code == "assumptions_unreadable"
    assert caught.value.may_have_landed is False
    assert caught.value.cause == READ_CAUSES[read_error]
    assert CFO_ID not in str(caught.value) and "fake-spreadsheet-id" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    # The entry read has no evidence yet; the read after the snapshot keeps the snapshot.
    assert len(caught.value.evidence) == fail_on
    assert scenario.sheet.batch_update_calls == []


SNAPSHOT_ERRORS = {
    "api_500": (make_api_error(500), "APIError 500"),
    "timeout": (ConnectionError("timeout"), "ConnectionError"),
    "disk": (PermissionError("denied"), "PermissionError"),
}


@pytest.mark.parametrize("case", sorted(SNAPSHOT_ERRORS))
def test_snapshot_failure_is_typed_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    error, cause = SNAPSHOT_ERRORS[case]
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")

    def failing(*args: Any, **kwargs: Any) -> Path:
        raise error

    monkeypatch.setattr(backup, "snapshot_raw_tab", failing)
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert (caught.value.code, caught.value.cause, caught.value.evidence) == (
        "snapshot_failed",
        cause,
        (),
    )
    assert scenario.sheet.batch_update_calls == []
    assert caught.value.may_have_landed is False


@pytest.mark.parametrize(
    ("error", "cause"),
    [(ConnectionError("timeout"), "ConnectionError"), (make_api_error(503), "APIError 503")],
)
def test_grid_growth_failure_is_typed_and_writes_nothing(
    tmp_path: Path, error: BaseException, cause: str
) -> None:
    sheet = JournalWorksheet([list(row) for row in ASSUMPTIONS_GRID], sheet_id=2002, row_count=5)
    sheet._fail_first["add_rows"] = [error]
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry], client=_single_attempt_client(scenario))
    assert (caught.value.code, caught.value.cause) == ("grid_resize_failed", cause)
    assert caught.value.may_have_landed is False
    assert len(caught.value.evidence) == 1
    assert sheet.batch_update_calls == []


@pytest.mark.parametrize("entered", ['=IF(FALSE, 1, "")', 7.0])
def test_planned_cells_holding_blank_looking_entries_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entered: object
) -> None:
    grid = [list(row) for row in ASSUMPTIONS_GRID] + [[], ["", ""]]
    sheet = JournalWorksheet(grid, sheet_id=2002, entered={(4, 1): entered})
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    # A placement whose header row would cover the blank-looking cell in column B.
    monkeypatch.setattr(adjustments, "JOURNAL_GAP_ROWS", -2)

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert caught.value.code == "planned_cells_occupied"
    assert caught.value.may_have_landed is False
    assert sheet.batch_update_calls == []


def test_occupied_planned_cells_are_refused_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    monkeypatch.setattr(adjustments, "JOURNAL_GAP_ROWS", -1)  # a placement that would overlap

    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert caught.value.code == "planned_cells_occupied"
    assert caught.value.may_have_landed is False
    assert scenario.sheet.batch_update_calls == []


@pytest.mark.parametrize("cell", [["", " "], ["", "", "\t"]])
def test_whitespace_only_cells_count_as_occupied(tmp_path: Path, cell: list[str]) -> None:
    grid = [list(row) for row in ASSUMPTIONS_GRID] + [list(cell)]
    sheet = JournalWorksheet(grid, sheet_id=2002)
    scenario = Scenario(tmp_path, assumptions=sheet)

    scenario.record([_recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")])

    assert sheet.grid[3] == cell
    assert sheet.grid[4:6] == [[], []] and sheet.grid[6] == [JOURNAL_MARKER]


def test_after_evidence_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    real = backup.snapshot_raw_tab

    def snapshot_with_existing_evidence(*args: Any, **kwargs: Any) -> Path:
        path = real(*args, **kwargs)
        (path.parent / "after-readback.json").write_text("earlier evidence", encoding="utf-8")
        return path

    monkeypatch.setattr(backup, "snapshot_raw_tab", snapshot_with_existing_evidence)
    scenario.sheet.after_batch_update = _raise_once(
        ConnectionError("lost"), _edit_cell(1, 1, "2.0")
    )
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])

    (snapshot,) = caught.value.evidence
    assert caught.value.code == "write_uncertain_conflict"
    assert caught.value.may_have_landed is True
    assert (snapshot.parent / "after-readback.json").read_text(encoding="utf-8") == (
        "earlier evidence"
    )


def test_a_forged_lock_is_refused(tmp_path: Path) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    capture_set, rec = scenario.capture()
    with acquire_run_lock(scenario.config) as real:
        forged = adjustments.RunLock(path=real.path, token="forged-token")
        with pytest.raises(AdjustmentError) as caught:
            record(
                [entry],
                config=scenario.config,
                client=scenario.harness.own(),
                captured=capture_set.assumptions,
                reconciliation=rec,
                as_of=AS_OF,
                lock=forged,
            )
        assert caught.value.code == "lock_not_held"
        # Refused at entry: no snapshot or other evidence was taken.
        assert not (real.path.parent / adjustments.SNAPSHOT_DIR).exists()
        real.path.write_text("not json", encoding="utf-8")
        with pytest.raises(AdjustmentError) as corrupt:
            record(
                [entry],
                config=scenario.config,
                client=scenario.harness.own(),
                captured=capture_set.assumptions,
                reconciliation=rec,
                as_of=AS_OF,
                lock=real,
            )
        assert corrupt.value.code == "lock_not_held"
    scenario.harness.assert_no_writes()


@pytest.mark.parametrize(
    "queued",
    [
        (503, 403),
        (500, 401),
        (429, 404),
        (503, 400),
    ],
    ids=lambda statuses: "_".join(map(str, statuses)),
)
def test_a_rejection_after_an_unobserved_attempt_may_have_landed(
    tmp_path: Path, queued: tuple[int, int]
) -> None:
    """The production client (default retries): the writer sees every attempt itself."""
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet._fail_first["batch_update"] = [make_api_error(status) for status in queued]
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert caught.value.code == "write_failed"
    assert caught.value.may_have_landed is True
    assert "MAY still land" in str(caught.value)
    assert scenario.sheet.batch_update_calls == []


def test_a_clean_first_rejection_through_the_production_client_cannot_have_landed(
    tmp_path: Path,
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    scenario.sheet._fail_first["batch_update"] = [make_api_error(403)]
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert (caught.value.code, caught.value.may_have_landed) == ("write_failed", False)
    assert "nothing was recorded" in str(caught.value)


def test_the_snapshot_is_announced_immediately_before_the_first_write(
    tmp_path: Path,
) -> None:
    sheet = JournalWorksheet([list(row) for row in ASSUMPTIONS_GRID], sheet_id=2002, row_count=5)
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    capture_set, rec = scenario.capture()
    seen: list[tuple[bool, int, int]] = []

    def announced(path: Path) -> None:
        seen.append((path.exists(), len(sheet.add_rows_calls), len(sheet.batch_update_calls)))

    with acquire_run_lock(scenario.config) as lock:
        record(
            [entry],
            config=scenario.config,
            client=scenario.harness.own(),
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
            clock=_clock(),
            on_snapshot=announced,
        )
    # After the snapshot and the grid growth, before the one write request.
    assert seen == [(True, 1, 0)]
    assert len(sheet.batch_update_calls) == 1


def test_no_snapshot_is_announced_when_the_write_is_refused_before_sending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    monkeypatch.setattr(adjustments, "JOURNAL_GAP_ROWS", -2)  # planned cells occupied
    capture_set, rec = scenario.capture()
    seen: list[Path] = []
    with acquire_run_lock(scenario.config) as lock, pytest.raises(AdjustmentWriteError):
        record(
            [entry],
            config=scenario.config,
            client=scenario.harness.own(),
            captured=capture_set.assumptions,
            reconciliation=rec,
            as_of=AS_OF,
            lock=lock,
            on_snapshot=seen.append,
        )
    assert seen == []


def test_lock_removed_mid_run_refuses_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = Scenario(tmp_path)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")
    real = backup.snapshot_raw_tab
    lock_path = scenario.config.main_reports.output_path / LOCK_FILENAME  # type: ignore[union-attr]

    def snapshot_then_remove_lock(*args: Any, **kwargs: Any) -> Path:
        path = real(*args, **kwargs)
        lock_path.unlink()  # an operator clears the lock as if it were stale
        return path

    monkeypatch.setattr(backup, "snapshot_raw_tab", snapshot_then_remove_lock)
    with pytest.raises(AdjustmentWriteError) as caught:
        scenario.record([entry])
    assert caught.value.code == "lock_not_held"
    assert caught.value.may_have_landed is False  # nothing was sent
    (snapshot,) = caught.value.evidence
    assert snapshot.exists()
    assert scenario.sheet.batch_update_calls == []


def test_identifier_shapes_have_one_owner() -> None:
    assert sources.HEX_DIGEST_PATTERN is models.HEX_DIGEST_PATTERN
    assert adjustments.HEX_DIGEST_PATTERN is models.HEX_DIGEST_PATTERN
    assert adjustments.DISCREPANCY_ID_PREFIX is models.DISCREPANCY_ID_PREFIX
    assert make_discrepancy_id("kind", []).startswith(models.DISCREPANCY_ID_PREFIX)
    key = make_record_key("bank-checking", ["bank", "2030-01-09"], 3)
    assert is_valid_record_key(key)
    assert not is_valid_record_key(key + ":0")


def test_adjustments_never_touch_reimbursement_decisions(tmp_path: Path) -> None:
    """A reimbursement-bearing input set: corrections change reporting views only."""
    claims = CfoWorksheet(
        [
            ["request_id", "decision", "payment_status", "amount"],
            ["REQ-EX-1", "approved", "unpaid", "75.50"],
            ["REQ-EX-2", "declined", "", "12.00"],
        ],
        sheet_id=2003,
    )
    scenario = Scenario(tmp_path, own_extra={"Reimbursements": claims})
    bundle = tmp_path / "reports" / "output" / "reimbursement-report.json"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(
        json.dumps({"requests": [{"id": "REQ-EX-1", "decision": "approved", "paid": False}]}),
        encoding="utf-8",
    )
    bundle_bytes = bundle.read_bytes()
    claims_before = [list(row) for row in claims.grid]
    before = set(scenario.files())
    check = scenario.txn(CHECK)

    # The bank check that pays the claim is recategorized and its amount corrected.
    scenario.record(
        [
            _recategorize(check, "Classroom Supplies", "Field Trips"),
            _adjustment(
                "amount_correction",
                check,
                category="Classroom Supplies",
                prior_value="-75.50",
                replacement_value="-70.00",
            ),
        ]
    )
    capture_set, rec = scenario.capture()
    ledger = project(rec, read_journal(capture_set.assumptions), AS_OF)

    assert ledger.publishable and _cells(ledger)[("Field Trips", "2030-01")] == Decimal("-110.00")
    assert bundle.read_bytes() == bundle_bytes
    assert claims.grid == claims_before
    assert claims.batch_update_calls == [] and claims.update_calls == []
    assert claims.append_rows_calls == [] and claims.delete_rows_calls == []
    # Every new file is private adjustment evidence under the output root; source records
    # (including the paying bank row) are unchanged.
    output = scenario.config.main_reports.output_path  # type: ignore[union-attr]
    created = set(scenario.files()) - before
    assert created and all((tmp_path / path).is_relative_to(output) for path in created)
    assert ledger.source.transactions == rec.transactions


# --------------------------------------------------------------------------------------
# Direct callers get the reader's validation; amounts, files and formula results
# --------------------------------------------------------------------------------------


def _direct_case(case: str, check: Transaction) -> Adjustment:
    if case == "bogus_kind":
        entry = _recategorize(check, "Classroom Supplies", "Field Trips")
        return dataclasses.replace(entry, kind="bogus")
    if case == "empty_reason":
        return _recategorize(check, "Classroom Supplies", "Field Trips", reason="")
    if case == "separator_in_evidence":
        return _recategorize(check, "Classroom Supplies", "Field Trips", evidence=("a;b", "c"))
    if case == "formula_category":
        return _recategorize(check, "Classroom Supplies", "=HYPERLINK(1)")
    if case == "huge_amount":
        return _adjustment(
            "additive", category="Donations", signed_amount=Decimal("1" * 24 + ".00")
        )
    if case == "sub_cent_amount":
        return _adjustment("additive", category="Donations", signed_amount=Decimal("1.005"))
    if case == "beyond_precision":
        return _adjustment(
            "additive", category="Donations", signed_amount=Decimal("1" * 30 + ".00")
        )
    assert case == "padded_reason"
    return _recategorize(check, "Classroom Supplies", "Field Trips", reason=" Example ")


DIRECT_CASES = {
    "bogus_kind": ("unknown_kind", "kind"),
    "empty_reason": ("missing_field", "reason"),
    "separator_in_evidence": ("round_trip_mismatch", "evidence"),
    "formula_category": ("invalid_category", "replacement_value"),
    "huge_amount": ("money_out_of_range", "signed_amount"),
    "sub_cent_amount": ("invalid_money", "signed_amount"),
    "beyond_precision": ("invalid_money", "signed_amount"),
    "padded_reason": ("round_trip_mismatch", "reason"),
}


@pytest.mark.parametrize("case", sorted(DIRECT_CASES))
def test_record_validates_hand_built_adjustments_like_the_reader(tmp_path: Path, case: str) -> None:
    scenario = Scenario(tmp_path)
    proposal = _direct_case(case, scenario.txn(CHECK))

    with pytest.raises(ProposalError) as caught:
        scenario.record([proposal])

    assert [(i.code, i.field, i.row_number) for i in caught.value.issues] == [
        (*DIRECT_CASES[case], 1)
    ]
    assert scenario.sheet.batch_update_calls == []
    assert not (scenario.config.main_reports.output_path / "adjustments").exists()  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("amount", "codes"),
    [
        ("999999999999.99", []),
        ("1000000000000.00", ["money_out_of_range"]),
        ("-1000000000000.00", ["money_out_of_range"]),
        ("1" * 26 + ".00", ["money_out_of_range"]),
        ("1" * 40, ["invalid_money"]),
    ],
)
def test_amount_magnitude_is_capped(tmp_path: Path, amount: str, codes: list[str]) -> None:
    check = Scenario(tmp_path).txn(CHECK)
    item = _proposal_payload(check, **_signed(signed_amount=amount))
    if not codes:
        (proposal,) = parse_proposals(_file(item))
        assert proposal.signed_amount == Decimal(amount)
        return
    with pytest.raises(ProposalError) as caught:
        parse_proposals(_file(item))
    assert _codes(caught.value.issues) == codes


def test_proposal_file_with_a_byte_order_mark_is_accepted(tmp_path: Path) -> None:
    check = Scenario(tmp_path).txn(CHECK)
    path = tmp_path / "proposals.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(_file(_proposal_payload(check))).encode())
    (proposal,) = load_proposals(path)
    assert proposal.kind == "category_override"


def test_deeply_nested_proposal_file_is_typed(tmp_path: Path) -> None:
    path = tmp_path / "proposals.json"
    path.write_text("[" * 200_000, encoding="utf-8")
    with pytest.raises(AdjustmentError) as caught:
        load_proposals(path)
    assert caught.value.code == "proposals_too_nested"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_formula_results_that_move_with_the_append_are_not_concurrent_edits(
    tmp_path: Path,
) -> None:
    grid = [list(row) for row in ASSUMPTIONS_GRID]
    grid[2][1] = "3"  # displayed result of a counting formula
    sheet = JournalWorksheet(grid, sheet_id=2002, entered={(2, 1): "=COUNTA(A:A)"})
    scenario = Scenario(tmp_path, assumptions=sheet)
    entry = _recategorize(scenario.txn(CHECK), "Classroom Supplies", "Field Trips")

    def recount(written: JournalWorksheet) -> None:
        written.after_batch_update = None
        written.grid[2][1] = "9"  # the formula now counts the journal rows too

    sheet.after_batch_update = recount
    result = scenario.record([entry])
    assert result.written == (entry.adjustment_id,)


def test_additive_evidence_may_cite_findings_beside_independent_evidence(
    tmp_path: Path,
) -> None:
    check = Scenario(tmp_path).txn(CHECK)
    item = _proposal_payload(
        check, **_signed(evidence=["DISC-" + "a" * 64, "example-deposit-slip"])
    )
    (proposal,) = parse_proposals(_file(item))
    assert proposal.evidence == ("DISC-" + "a" * 64, "example-deposit-slip")


def test_journal_entry_limit_is_inclusive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adjustments, "MAX_JOURNAL_ENTRIES", 2)
    scenario = Scenario(tmp_path)
    scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(1))])
    # Reaching exactly the limit is allowed, and a journal of exactly the limit reads.
    scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(2))])
    assert len(read_journal(scenario.capture()[0].assumptions).entries) == 2
    with pytest.raises(AdjustmentError) as caught:
        scenario.record([_adjustment("additive", category="Donations", signed_amount=Decimal(3))])
    assert caught.value.code == "journal_full"


def test_sheets_failures_and_http_status_have_one_owner() -> None:
    """Every Sheets failure is caught through sheets.SHEETS_FAILURES and every HTTP status is
    read through sheets.http_status: no main_reports module keeps its own copy."""
    assert set(sheets_module.SHEETS_FAILURES) >= {OSError, ValueError, RefreshError}
    package = Path(adjustments.__file__).resolve().parent
    status_parse = re.compile(r"status_code|getattr\([^)]*[\"']code[\"']")
    local_tuple = re.compile(r"_(?:SHEETS|TRANSPORT)_FAILURES")
    for module in sorted(package.glob("*.py")):
        text = module.read_text(encoding="utf-8")
        assert status_parse.search(text) is None, module.name
        assert local_tuple.search(text) is None, module.name
    for name in ("adjustments", "runner"):
        source = (package / f"{name}.py").read_text(encoding="utf-8")
        assert "SHEETS_FAILURES" in source, name
