"""Load + validate the private ``config.toml`` (stdlib ``tomllib``).

Identity (org/school name, emails, spreadsheet/Drive IDs, grade labels, fiscal-year
setting) lives ONLY in ``config.toml`` (gitignored) — never in committed code. This
module reads that private file into typed, frozen dataclasses and fails fast with a
clear :class:`ConfigError` naming the missing field.

Secrets posture: this module resolves the service-account key *path* (relative to the
config file's directory) but NEVER reads, logs, or prints the key's contents. The same
holds for the optional ``[gmail]`` block's OAuth client-secrets and token files.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pta_finance.main_reports.models import SOURCE_KINDS, is_valid_source_alias

__all__ = [
    "ConfigError",
    "Organization",
    "Contacts",
    "FiscalYear",
    "Grades",
    "Sheets",
    "Google",
    "Gmail",
    "ReceiptMapping",
    "ReceiptRefresh",
    "ColumnBinding",
    "CoverageDeclaration",
    "SourceBinding",
    "CrosswalkTarget",
    "CrosswalkEntry",
    "CategoryCrosswalk",
    "MainReports",
    "Config",
    "load_config",
]


class ConfigError(Exception):
    """Raised when a required config field is missing or malformed.

    ``ConfigError.field`` names the offending field (dotted path) so the operator
    knows exactly what to fix in ``config.toml``.
    """

    def __init__(self, field: str, message: str | None = None) -> None:
        self.field = field
        super().__init__(message or f"missing or invalid required config field: {field}")


@dataclass(frozen=True)
class Organization:
    name: str
    school_name: str
    school_email: str


@dataclass(frozen=True)
class Contacts:
    president: tuple[str, ...]
    treasurer: str
    cfo: str
    account_holders: tuple[str, ...]


@dataclass(frozen=True)
class FiscalYear:
    start_month: int


@dataclass(frozen=True)
class Grades:
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Sheets:
    spreadsheet_id: str
    test_spreadsheet_id: str
    drive_receipts_folder_id: str
    drive_reports_folder_id: str
    budget_tab_template: str = "FY{fy} Budget"


@dataclass(frozen=True)
class Google:
    service_account_file: str
    # Absolute path to the service-account JSON, resolved relative to the config
    # file's directory. The path only — contents are never read here.
    service_account_path: Path


@dataclass(frozen=True)
class Gmail:
    """The OPTIONAL ``[gmail]`` block — read-only mail ingestion (see ``gmail_source``).

    Absent from ``config.toml`` for any org that never wires up Gmail, in which case
    ``Config.gmail`` is ``None`` and nothing else changes. As with :class:`Google`, the
    ``*_path`` fields are resolved relative to the config file's directory and are PATHS
    ONLY — neither the OAuth client-secrets file nor the minted token file is ever read,
    logged, or printed here.
    """

    client_secrets_file: str
    token_file: str
    inbox_dir: str
    client_secrets_path: Path
    token_path: Path
    inbox_path: Path


@dataclass(frozen=True)
class ReceiptMapping:
    """Optional policy for which received emails belong in the reimbursement ledger."""

    received_since: date


@dataclass(frozen=True)
class ReceiptRefresh:
    """Optional local receipt preparation settings.

    Paths are resolved relative to the private config file.  Tool paths are optional: image
    receipts can still be prepared without Chromium, and pages can still be linked without OCR.
    """

    allowlist: tuple[str, ...]
    cache_path: Path
    pages_path: Path
    tesseract_path: Path | None = None
    chromium_path: Path | None = None


@dataclass(frozen=True)
class ColumnBinding:
    """Where one adapter field lives in a configured header signature.

    ``label`` is matched against the LAST header row; ``group`` (a forward-filled first-row
    heading, for two-row headers) and ``occurrence`` (1-based among equal labels) disambiguate
    repeated labels. Field names themselves are owned by ``main_reports.sources``.
    """

    label: str
    group: str | None = None
    occurrence: int | None = None


@dataclass(frozen=True)
class CoverageDeclaration:
    """Evidence that a source is complete from ``start`` through ``end`` (both inclusive)."""

    start: date
    end: date
    evidence: str

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)


@dataclass(frozen=True)
class SourceBinding:
    """One private, explicit binding of a CFO workbook tab to a source adapter kind."""

    alias: str
    kind: str
    tab: str
    header_signature: tuple[tuple[str, ...], ...]
    tab_id: int | None = None
    columns: tuple[tuple[str, ColumnBinding], ...] = ()
    coverage: tuple[CoverageDeclaration, ...] = ()


@dataclass(frozen=True)
class CrosswalkTarget:
    category: str
    share: Decimal


@dataclass(frozen=True)
class CrosswalkEntry:
    """A documented map from one CFO category to budget categories (shares sum to 1)."""

    source_category: str
    targets: tuple[CrosswalkTarget, ...]
    note: str


@dataclass(frozen=True)
class CategoryCrosswalk:
    version: int
    entries: tuple[CrosswalkEntry, ...]


@dataclass(frozen=True)
class MainReports:
    """The OPTIONAL ``[main_reports]`` block: CFO workbook bindings for the Main Report Set.

    The CFO workbook is read through a separate, explicitly read-only client; our own
    workbook (``[sheets]``) and credentials (``[google]``) are unchanged. Real workbook IDs,
    tab bindings and coverage evidence live only in the private config.
    """

    source_spreadsheet_id: str
    output_dir: str
    output_path: Path
    assumptions_tab: str
    sources: tuple[SourceBinding, ...]
    crosswalk: CategoryCrosswalk | None = None


@dataclass(frozen=True)
class Config:
    organization: Organization
    contacts: Contacts
    fiscal_year: FiscalYear
    grades: Grades
    sheets: Sheets
    google: Google
    # Optional section: ``None`` when ``config.toml`` has no ``[gmail]`` block.
    gmail: Gmail | None = None
    # Optional section: absent preserves the legacy all-history receipt mapping behavior.
    receipt_mapping: ReceiptMapping | None = None
    receipt_refresh: ReceiptRefresh | None = None
    # Optional section: absent keeps every legacy command unchanged.
    main_reports: MainReports | None = None


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigError(name, f"missing required config section: [{name}]")
    return value


def _require(section: dict[str, Any], key: str, dotted: str) -> Any:
    if key not in section:
        raise ConfigError(dotted)
    value = section[key]
    if value is None:
        raise ConfigError(dotted)
    return value


def _require_str(section: dict[str, Any], key: str, dotted: str) -> str:
    value = _require(section, key, dotted)
    if not isinstance(value, str) or value == "":
        raise ConfigError(dotted, f"expected a non-empty string for {dotted}")
    return value


def _require_int(section: dict[str, Any], key: str, dotted: str) -> int:
    value = _require(section, key, dotted)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(dotted, f"expected an integer for {dotted}")
    return value


def _require_str_list(section: dict[str, Any], key: str, dotted: str) -> tuple[str, ...]:
    value = _require(section, key, dotted)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(dotted, f"expected a list of strings for {dotted}")
    return tuple(value)


def _resolve_path(raw: str, base_dir: Path) -> Path:
    """Resolve a config-declared path relative to the config file's directory.

    An already-absolute path is returned untouched. The file is never opened here.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def load_config(path: Path) -> Config:
    """Read, validate, and return the typed :class:`Config` from a ``config.toml``.

    Raises :class:`ConfigError` (naming the field) on any missing/invalid required
    field, and ``FileNotFoundError`` if ``path`` does not exist.
    """
    path = Path(path)
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    org_s = _section(data, "organization")
    organization = Organization(
        name=_require_str(org_s, "name", "organization.name"),
        school_name=_require_str(org_s, "school_name", "organization.school_name"),
        school_email=_require_str(org_s, "school_email", "organization.school_email"),
    )

    con_s = _section(data, "contacts")
    contacts = Contacts(
        president=_require_str_list(con_s, "president", "contacts.president"),
        treasurer=_require_str(con_s, "treasurer", "contacts.treasurer"),
        cfo=_require_str(con_s, "cfo", "contacts.cfo"),
        account_holders=_require_str_list(con_s, "account_holders", "contacts.account_holders"),
    )

    fy_s = _section(data, "fiscal_year")
    start_month = _require_int(fy_s, "start_month", "fiscal_year.start_month")
    if not 1 <= start_month <= 12:
        raise ConfigError(
            "fiscal_year.start_month",
            "fiscal_year.start_month must be in 1..12",
        )
    fiscal_year = FiscalYear(start_month=start_month)

    grades_s = _section(data, "grades")
    grades = Grades(labels=_require_str_list(grades_s, "labels", "grades.labels"))

    sheets_s = _section(data, "sheets")
    sheets = Sheets(
        spreadsheet_id=_require_str(sheets_s, "spreadsheet_id", "sheets.spreadsheet_id"),
        test_spreadsheet_id=_require_str(
            sheets_s, "test_spreadsheet_id", "sheets.test_spreadsheet_id"
        ),
        drive_receipts_folder_id=_require_str(
            sheets_s, "drive_receipts_folder_id", "sheets.drive_receipts_folder_id"
        ),
        drive_reports_folder_id=_require_str(
            sheets_s, "drive_reports_folder_id", "sheets.drive_reports_folder_id"
        ),
        budget_tab_template=(
            _require_str(sheets_s, "budget_tab_template", "sheets.budget_tab_template")
            if "budget_tab_template" in sheets_s
            else "FY{fy} Budget"
        ),
    )

    google_s = _section(data, "google")
    service_account_file = _require_str(
        google_s, "service_account_file", "google.service_account_file"
    )
    google = Google(
        service_account_file=service_account_file,
        service_account_path=_resolve_path(service_account_file, path.parent),
    )

    # [gmail] is OPTIONAL: `data.get` (never `_section`, which raises) so a config
    # without the block loads unchanged and `Config.gmail` is None.
    gmail = _load_gmail(data.get("gmail"), path.parent)
    receipt_mapping = _load_receipt_mapping(data.get("receipt_mapping"))
    receipt_refresh = _load_receipt_refresh(data.get("receipt_refresh"), path.parent)
    main_reports = _load_main_reports(data.get("main_reports"), path.parent)

    return Config(
        organization=organization,
        contacts=contacts,
        fiscal_year=fiscal_year,
        grades=grades,
        sheets=sheets,
        google=google,
        gmail=gmail,
        receipt_mapping=receipt_mapping,
        receipt_refresh=receipt_refresh,
        main_reports=main_reports,
    )


def _load_gmail(raw: Any, base_dir: Path) -> Gmail | None:
    """Parse the OPTIONAL ``[gmail]`` section; ``None`` when it is absent.

    A section that is PRESENT is validated like any other: every key is required and a
    missing one raises :class:`ConfigError` naming it.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("gmail", "expected a [gmail] table (or omit the section entirely)")

    client_secrets_file = _require_str(raw, "client_secrets_file", "gmail.client_secrets_file")
    token_file = _require_str(raw, "token_file", "gmail.token_file")
    inbox_dir = _require_str(raw, "inbox_dir", "gmail.inbox_dir")
    return Gmail(
        client_secrets_file=client_secrets_file,
        token_file=token_file,
        inbox_dir=inbox_dir,
        client_secrets_path=_resolve_path(client_secrets_file, base_dir),
        token_path=_resolve_path(token_file, base_dir),
        inbox_path=_resolve_path(inbox_dir, base_dir),
    )


def _load_receipt_mapping(raw: Any) -> ReceiptMapping | None:
    """Parse the OPTIONAL ``[receipt_mapping]`` section; ``None`` when absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(
            "receipt_mapping",
            "expected a [receipt_mapping] table (or omit the section entirely)",
        )

    dotted = "receipt_mapping.received_since"
    return ReceiptMapping(
        received_since=_config_date(_require(raw, "received_since", dotted), dotted)
    )


def _load_receipt_refresh(raw: Any, base_dir: Path) -> ReceiptRefresh | None:
    """Parse the OPTIONAL receipt preparation block; absent means no network or OCR work."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(
            "receipt_refresh",
            "expected a [receipt_refresh] table (or omit the section entirely)",
        )
    allowlist = _require_str_list(raw, "allowlist", "receipt_refresh.allowlist")
    cache_dir = _require_str(raw, "cache_dir", "receipt_refresh.cache_dir")
    pages_dir = _require_str(raw, "pages_dir", "receipt_refresh.pages_dir")

    def optional_path(name: str) -> Path | None:
        value = raw.get(name)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ConfigError(
                f"receipt_refresh.{name}",
                f"expected a non-empty string for receipt_refresh.{name}",
            )
        return _resolve_path(value, base_dir)

    return ReceiptRefresh(
        allowlist=allowlist,
        cache_path=_resolve_path(cache_dir, base_dir),
        pages_path=_resolve_path(pages_dir, base_dir),
        tesseract_path=optional_path("tesseract_path"),
        chromium_path=optional_path("chromium_path"),
    )


def _optional_table(raw: Any, dotted: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(dotted, f"expected a [{dotted}] table")
    return raw


def _optional_str(section: dict[str, Any], key: str, dotted: str, default: str) -> str:
    if key not in section:
        return default
    return _require_str(section, key, dotted)


_OUTPUT_DIR_FIELD = "main_reports.output_dir"


def _same_file(a: Path, b: Path) -> bool:
    """Filesystem identity of two EXISTING paths; an unverifiable comparison fails closed."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        raise ConfigError(
            _OUTPUT_DIR_FIELD, f"{_OUTPUT_DIR_FIELD} location could not be verified"
        ) from None


def _existing_ancestors(path: Path) -> list[Path]:
    """``path`` (if it exists) and every existing ancestor, nearest first."""
    return [item for item in (path, *path.parents) if item.exists()]


def _normcased_parts(path: Path) -> tuple[str, ...]:
    return tuple(os.path.normcase(part) for part in path.parts)


def _lexically_within(child: Path, parent: Path) -> bool:
    parent_parts = _normcased_parts(parent)
    return _normcased_parts(child)[: len(parent_parts)] == parent_parts


def _private_output_path(raw: str, base_dir: Path) -> Path:
    r"""Resolve ``main_reports.output_dir``; refuse a location that could be committed.

    Captures hold raw CFO cell values, so the directory must sit under the project's
    gitignored ``reports/output/`` or entirely outside the project directory (the directory
    holding ``config.toml``). One structural invariant decides it:

    * ``real_candidate`` is the path resolved like every config path (:func:`_resolve_path`)
      and then FULLY (``Path.resolve`` follows existing symlinks/junctions and keeps the
      non-existent tail). A ``reports`` or ``reports/output`` link/junction pointing anywhere
      else therefore resolves to that other location.
    * The project root or any ancestor of it is refused.
    * The candidate is inside the project when an existing ancestor is the project by
      FILESYSTEM IDENTITY (:func:`os.path.samefile`, volume + file identity on Windows) — so
      ``..``, ``\\?\``, ``//?/``, ``\\.\``, UNC admin-share, case and 8.3 aliases all count.
      The resolved form must agree (lexically within the resolved project); if the two checks
      disagree the location is unverifiable and refused (fail closed).
    * Inside the project, ``real_candidate`` relative to the project must start with exactly
      ``reports/output`` (case-normalized per component).

    An identity check that raises also fails closed. Loading config never creates anything
    (dry-run performs no local writes).
    """
    real_project = base_dir.resolve()
    real_candidate = _resolve_path(raw, base_dir).resolve()
    if not real_candidate.is_absolute():  # e.g. a drive-relative "a:b" resolves to "a:b"
        raise ConfigError(_OUTPUT_DIR_FIELD, f"{_OUTPUT_DIR_FIELD} must be an absolute location")
    message = (
        f"{_OUTPUT_DIR_FIELD} must be under reports/output/ (gitignored) or outside "
        "the project directory"
    )
    if _lexically_within(real_project, real_candidate) or (
        real_candidate.exists()
        and any(_same_file(real_candidate, item) for item in (real_project, *real_project.parents))
    ):
        raise ConfigError(_OUTPUT_DIR_FIELD, message)  # the project root or one of its ancestors
    by_identity = any(
        _same_file(item, real_project) for item in _existing_ancestors(real_candidate)
    )
    by_resolved_form = _lexically_within(real_candidate, real_project)
    if by_identity != by_resolved_form:
        raise ConfigError(_OUTPUT_DIR_FIELD, f"{_OUTPUT_DIR_FIELD} location could not be verified")
    if not by_identity:
        return real_candidate
    tail = _normcased_parts(real_candidate)[len(real_project.parts) :]
    if tail[:2] != (os.path.normcase("reports"), os.path.normcase("output")):
        raise ConfigError(_OUTPUT_DIR_FIELD, message)
    return real_candidate


def _config_date(value: Any, dotted: str) -> date:
    """An ISO ``YYYY-MM-DD`` config date (native TOML date or exact ISO string)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(dotted, f"{dotted} must be an ISO date (YYYY-MM-DD)") from exc
        if parsed.isoformat() == value:
            return parsed
    raise ConfigError(dotted, f"{dotted} must be an ISO date (YYYY-MM-DD)")


def _load_header_signature(raw: Any, dotted: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(raw, list) or not all(
        isinstance(row, list) and all(isinstance(cell, str) for cell in row) for row in raw
    ):
        raise ConfigError(dotted, f"{dotted} must be a list of header rows (lists of strings)")
    return tuple(tuple(row) for row in raw)


def _load_column_binding(raw: Any, dotted: str) -> ColumnBinding:
    if isinstance(raw, str) and raw:
        return ColumnBinding(label=raw)
    if not isinstance(raw, dict):
        raise ConfigError(dotted, f"{dotted} must be a header label or a label table")
    unknown = set(raw) - {"label", "group", "occurrence"}
    if unknown:
        raise ConfigError(dotted, f"{dotted} has unsupported keys: {sorted(unknown)}")
    label = _require_str(raw, "label", f"{dotted}.label")
    group = raw.get("group")
    if group is not None and (not isinstance(group, str) or not group):
        raise ConfigError(f"{dotted}.group", f"expected a non-empty string for {dotted}.group")
    occurrence = raw.get("occurrence")
    if occurrence is not None and (
        isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1
    ):
        raise ConfigError(f"{dotted}.occurrence", f"{dotted}.occurrence must be a positive integer")
    return ColumnBinding(label=label, group=group, occurrence=occurrence)


def _load_coverage(raw: Any, dotted: str) -> tuple[CoverageDeclaration, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(dotted, f"{dotted} must be a list of start/end/evidence tables")
    out: list[CoverageDeclaration] = []
    for index, item in enumerate(raw):
        item_dotted = f"{dotted}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(item_dotted, f"{item_dotted} must be a table")
        start = _config_date(
            _require(item, "start", f"{item_dotted}.start"), f"{item_dotted}.start"
        )
        end = _config_date(_require(item, "end", f"{item_dotted}.end"), f"{item_dotted}.end")
        if end < start:
            raise ConfigError(item_dotted, f"{item_dotted} ends before it starts")
        if end >= date.max:
            raise ConfigError(f"{item_dotted}.end", f"{item_dotted}.end must be before 9999-12-31")
        evidence = _require_str(item, "evidence", f"{item_dotted}.evidence")
        out.append(CoverageDeclaration(start=start, end=end, evidence=evidence))
    return tuple(out)


def _load_source_binding(alias: str, raw: Any) -> SourceBinding:
    dotted = f"main_reports.sources.{alias}"
    if not is_valid_source_alias(alias):
        raise ConfigError(dotted, f"{dotted} must be a lowercase ASCII slug (source alias)")
    if not isinstance(raw, dict):
        raise ConfigError(dotted, f"expected a [{dotted}] table")
    kind = _require_str(raw, "kind", f"{dotted}.kind")
    if kind not in SOURCE_KINDS:
        raise ConfigError(f"{dotted}.kind", f"{dotted}.kind must be one of {list(SOURCE_KINDS)}")
    tab = _require_str(raw, "tab", f"{dotted}.tab")
    tab_id = raw.get("tab_id")
    if tab_id is not None and (isinstance(tab_id, bool) or not isinstance(tab_id, int)):
        raise ConfigError(f"{dotted}.tab_id", f"{dotted}.tab_id must be an integer sheet id")
    signature = _load_header_signature(
        _require(raw, "header_signature", f"{dotted}.header_signature"),
        f"{dotted}.header_signature",
    )
    columns_raw = _optional_table(raw.get("columns"), f"{dotted}.columns")
    columns = tuple(
        (name, _load_column_binding(value, f"{dotted}.columns.{name}"))
        for name, value in sorted(columns_raw.items())
    )
    coverage = _load_coverage(raw.get("coverage"), f"{dotted}.coverage")
    return SourceBinding(
        alias=alias,
        kind=kind,
        tab=tab,
        header_signature=signature,
        tab_id=tab_id,
        columns=columns,
        coverage=coverage,
    )


def _load_crosswalk(raw: Any) -> CategoryCrosswalk | None:
    if raw is None:
        return None
    dotted = "main_reports.crosswalk"
    if not isinstance(raw, dict):
        raise ConfigError(dotted, f"expected a [{dotted}] table")
    version = _require_int(raw, "version", f"{dotted}.version")
    if version < 1:
        raise ConfigError(f"{dotted}.version", f"{dotted}.version must be >= 1")
    entries_raw = raw.get("entries", [])
    if not isinstance(entries_raw, list):
        raise ConfigError(f"{dotted}.entries", f"{dotted}.entries must be an array of tables")
    entries: list[CrosswalkEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(entries_raw):
        item_dotted = f"{dotted}.entries[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(item_dotted, f"{item_dotted} must be a table")
        source_category = _require_str(item, "source_category", f"{item_dotted}.source_category")
        if source_category in seen:
            raise ConfigError(
                f"{item_dotted}.source_category", f"{item_dotted} repeats a source_category"
            )
        seen.add(source_category)
        note = _require_str(item, "note", f"{item_dotted}.note")
        targets_raw = _require(item, "targets", f"{item_dotted}.targets")
        if not isinstance(targets_raw, list) or not targets_raw:
            raise ConfigError(f"{item_dotted}.targets", f"{item_dotted}.targets must be non-empty")
        targets: list[CrosswalkTarget] = []
        for t_index, target in enumerate(targets_raw):
            t_dotted = f"{item_dotted}.targets[{t_index}]"
            if not isinstance(target, dict):
                raise ConfigError(t_dotted, f"{t_dotted} must be a table")
            category = _require_str(target, "category", f"{t_dotted}.category")
            share_raw = _require_str(target, "share", f"{t_dotted}.share")
            try:
                share = Decimal(share_raw)
            except InvalidOperation as exc:
                raise ConfigError(f"{t_dotted}.share", f"{t_dotted}.share must be decimal") from exc
            if not share.is_finite() or share <= 0:
                raise ConfigError(f"{t_dotted}.share", f"{t_dotted}.share must be positive")
            targets.append(CrosswalkTarget(category=category, share=share))
        if sum((t.share for t in targets), Decimal(0)) != Decimal(1):
            raise ConfigError(f"{item_dotted}.targets", f"{item_dotted} shares must sum to 1")
        entries.append(
            CrosswalkEntry(source_category=source_category, targets=tuple(targets), note=note)
        )
    return CategoryCrosswalk(version=version, entries=tuple(entries))


def _load_main_reports(raw: Any, base_dir: Path) -> MainReports | None:
    """Parse the OPTIONAL ``[main_reports]`` section; ``None`` when absent.

    Structural validation only (types, aliases, kinds, dates, crosswalk shares). Header
    signatures and column bindings are resolved against the adapter field definitions by
    ``main_reports.sources`` before any workbook read.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(
            "main_reports", "expected a [main_reports] table (or omit the section entirely)"
        )
    source_spreadsheet_id = _require_str(
        raw, "source_spreadsheet_id", "main_reports.source_spreadsheet_id"
    )
    output_dir = _optional_str(
        raw, "output_dir", "main_reports.output_dir", "reports/output/main-report-runs"
    )
    assumptions_tab = _optional_str(
        raw, "assumptions_tab", "main_reports.assumptions_tab", "Assumptions"
    )
    sources_raw = _require(raw, "sources", "main_reports.sources")
    if not isinstance(sources_raw, dict) or not sources_raw:
        raise ConfigError(
            "main_reports.sources", "main_reports.sources must contain at least one binding"
        )
    sources = tuple(
        _load_source_binding(alias, value) for alias, value in sorted(sources_raw.items())
    )
    return MainReports(
        source_spreadsheet_id=source_spreadsheet_id,
        output_dir=output_dir,
        output_path=_private_output_path(output_dir, base_dir),
        assumptions_tab=assumptions_tab,
        sources=sources,
        crosswalk=_load_crosswalk(raw.get("crosswalk")),
    )
