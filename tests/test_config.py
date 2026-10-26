"""Tests for np_finance.config — typed load + fail-fast on missing required field."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from np_finance.config import ConfigError, load_config

# A complete, fake config used as the baseline for the happy-path and the
# field-removal tests. Identity is obviously-fake placeholders only.
_FULL_CONFIG = """\
[organization]
name = "Example Non-profit"
school_name = "Example Elementary"
school_email = "office@example.org"

[contacts]
president = ["president@example.org"]
treasurer = "treasurer@example.org"
cfo = "cfo@example.org"
account_holders = ["president@example.org", "treasurer@example.org"]

[fiscal_year]
start_month = 1

[grades]
labels = ["K", "1", "2", "3", "4", "5"]

[sheets]
spreadsheet_id = "fake-spreadsheet-id"
test_spreadsheet_id = "fake-test-sheet-id"
drive_receipts_folder_id = "fake-receipts-folder-id"
drive_reports_folder_id = "fake-reports-folder-id"

[google]
service_account_file = "secrets/service-account.json"
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_full(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, _FULL_CONFIG))

    assert cfg.organization.name == "Example Non-profit"
    assert cfg.organization.school_name == "Example Elementary"
    assert cfg.organization.school_email == "office@example.org"

    assert cfg.contacts.president == ("president@example.org",)
    assert cfg.contacts.treasurer == "treasurer@example.org"
    assert cfg.contacts.cfo == "cfo@example.org"
    assert cfg.contacts.account_holders == (
        "president@example.org",
        "treasurer@example.org",
    )

    assert cfg.fiscal_year.start_month == 1
    assert cfg.grades.labels == ("K", "1", "2", "3", "4", "5")

    assert cfg.sheets.spreadsheet_id == "fake-spreadsheet-id"
    assert cfg.sheets.test_spreadsheet_id == "fake-test-sheet-id"
    assert cfg.sheets.drive_receipts_folder_id == "fake-receipts-folder-id"
    assert cfg.sheets.drive_reports_folder_id == "fake-reports-folder-id"

    assert cfg.google.service_account_file == "secrets/service-account.json"
    # SA path is resolved relative to the config file's directory; contents untouched.
    assert (
        cfg.google.service_account_path == (tmp_path / "secrets" / "service-account.json").resolve()
    )


def test_missing_required_field_raises_naming_field(tmp_path: Path) -> None:
    # Drop `treasurer` from [contacts]; load_config must raise ConfigError naming it.
    text = _FULL_CONFIG.replace('treasurer = "treasurer@example.org"\n', "")
    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))
    assert exc_info.value.field == "contacts.treasurer"
    assert "contacts.treasurer" in str(exc_info.value)


def test_missing_required_section_raises(tmp_path: Path) -> None:
    # Remove the entire [google] section.
    text = _FULL_CONFIG.split("[google]")[0]
    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))
    assert exc_info.value.field == "google"


def test_bad_start_month_raises(tmp_path: Path) -> None:
    text = _FULL_CONFIG.replace("start_month = 1", "start_month = 13")
    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))
    assert exc_info.value.field == "fiscal_year.start_month"


def test_absolute_sa_path_preserved(tmp_path: Path) -> None:
    abs_path = (tmp_path / "elsewhere" / "sa.json").resolve()
    text = _FULL_CONFIG.replace(
        'service_account_file = "secrets/service-account.json"',
        f'service_account_file = "{abs_path.as_posix()}"',
    )
    cfg = load_config(_write(tmp_path, text))
    assert cfg.google.service_account_path == abs_path


def test_optional_receipt_refresh_resolves_private_paths(tmp_path: Path) -> None:
    text = (
        _FULL_CONFIG
        + """
[receipt_refresh]
allowlist = ["uploads.example.org", ".cdn.example.org"]
cache_dir = "private/cache"
pages_dir = "private/pages"
tesseract_path = "tools/tesseract.exe"
chromium_path = "tools/chromium.exe"
"""
    )
    refresh = load_config(_write(tmp_path, text)).receipt_refresh
    assert refresh is not None
    assert refresh.allowlist == ("uploads.example.org", ".cdn.example.org")
    assert refresh.cache_path == (tmp_path / "private/cache").resolve()
    assert refresh.pages_path == (tmp_path / "private/pages").resolve()
    assert refresh.tesseract_path == (tmp_path / "tools/tesseract.exe").resolve()
    assert refresh.chromium_path == (tmp_path / "tools/chromium.exe").resolve()


def test_present_receipt_refresh_requires_allowlist_and_directories(tmp_path: Path) -> None:
    text = _FULL_CONFIG + '\n[receipt_refresh]\nallowlist = []\ncache_dir = "cache"\n'
    with pytest.raises(ConfigError) as caught:
        load_config(_write(tmp_path, text))
    assert caught.value.field == "receipt_refresh.pages_dir"


# --------------------------------------------------------------------------------------
# The OPTIONAL [gmail] section (feature-plan Design Decision 5). Every test above loads a
# config with NO [gmail] block, which is itself the regression guard: making the section
# required would break all of them, plus conftest.py and test_reports.py.
# --------------------------------------------------------------------------------------

_GMAIL_SECTION = """
[gmail]
client_secrets_file = "secrets/gmail-client-secret.json"
token_file = "secrets/gmail-token.json"
inbox_dir = "mail_samples"
"""


def test_missing_gmail_section_yields_none(tmp_path: Path) -> None:
    # Absent [gmail] must NOT raise (unlike every required section) and must leave
    # Config.gmail as None, so an org that never wires up Gmail is unaffected.
    cfg = load_config(_write(tmp_path, _FULL_CONFIG))
    assert cfg.gmail is None


def test_gmail_section_parsed_with_resolved_paths(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, _FULL_CONFIG + _GMAIL_SECTION))

    assert cfg.gmail is not None
    assert cfg.gmail.client_secrets_file == "secrets/gmail-client-secret.json"
    assert cfg.gmail.token_file == "secrets/gmail-token.json"
    assert cfg.gmail.inbox_dir == "mail_samples"
    # Paths resolve against the config file's directory, exactly like the SA key path;
    # contents are never read here.
    assert (
        cfg.gmail.client_secrets_path
        == (tmp_path / "secrets" / "gmail-client-secret.json").resolve()
    )
    assert cfg.gmail.token_path == (tmp_path / "secrets" / "gmail-token.json").resolve()
    assert cfg.gmail.inbox_path == (tmp_path / "mail_samples").resolve()


def test_absolute_gmail_paths_preserved(tmp_path: Path) -> None:
    abs_token = (tmp_path / "elsewhere" / "gmail-token.json").resolve()
    text = (_FULL_CONFIG + _GMAIL_SECTION).replace(
        'token_file = "secrets/gmail-token.json"',
        f'token_file = "{abs_token.as_posix()}"',
    )
    cfg = load_config(_write(tmp_path, text))
    assert cfg.gmail is not None
    assert cfg.gmail.token_path == abs_token


def test_present_gmail_section_still_requires_every_key(tmp_path: Path) -> None:
    # Optional section, but not optional keys: a half-filled block fails fast by name.
    text = (_FULL_CONFIG + _GMAIL_SECTION).replace('token_file = "secrets/gmail-token.json"\n', "")
    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))
    assert exc_info.value.field == "gmail.token_file"


def test_gmail_section_that_is_not_a_table_raises(tmp_path: Path) -> None:
    # Root-level key (must precede the first section header, or TOML nests it).
    text = 'gmail = "secrets/gmail-token.json"\n' + _FULL_CONFIG
    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))
    assert exc_info.value.field == "gmail"


# --------------------------------------------------------------------------------------
# The OPTIONAL [receipt_mapping] section. Its received_since value is the authoritative,
# inclusive ledger-membership cutoff; older configs without the section remain all-history.
# --------------------------------------------------------------------------------------

_RECEIPT_MAPPING_SECTION = """
[receipt_mapping]
received_since = "2030-09-01"
"""


def test_missing_receipt_mapping_section_yields_none(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, _FULL_CONFIG))
    assert cfg.receipt_mapping is None


def test_receipt_mapping_received_since_parses_iso_date(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, _FULL_CONFIG + _RECEIPT_MAPPING_SECTION))

    assert cfg.receipt_mapping is not None
    assert cfg.receipt_mapping.received_since == date(2030, 9, 1)


@pytest.mark.parametrize("value", ['"not-a-date"', '""', "123"])
def test_malformed_receipt_mapping_cutoff_names_field(tmp_path: Path, value: str) -> None:
    text = _FULL_CONFIG + f"\n[receipt_mapping]\nreceived_since = {value}\n"

    with pytest.raises(ConfigError) as exc_info:
        load_config(_write(tmp_path, text))

    assert exc_info.value.field == "receipt_mapping.received_since"
    assert "receipt_mapping.received_since" in str(exc_info.value)


# --------------------------------------------------------------------------------------
# The OPTIONAL [main_reports] section: private CFO workbook bindings (structure only here;
# adapter column resolution is tested in test_main_report_sources.py).
# --------------------------------------------------------------------------------------

_MAIN_REPORTS_SECTION = """
[main_reports]
source_spreadsheet_id = "fake-cfo-workbook-id"
output_dir = "reports/output/runs"

[main_reports.sources.bank-checking]
kind = "bank"
tab = "Bank Checking"
tab_id = 1001
header_signature = [["DATE", "DESCRIPTION", "AMOUNT"]]
coverage = [
  { start = "2030-01-01", end = "2030-01-31", evidence = "example-statement-index" },
  { start = 2030-02-01, end = 2030-02-28, evidence = "example-statement-index-2" },
]

[main_reports.sources.wix]
kind = "wix"
tab = "Store Transactions"
header_signature = [["Payment", ""], ["Provider Payment ID", "Status"]]

[main_reports.sources.wix.columns]
transaction_status = { label = "Status", group = "Payment" }
order_id = "Order Number"
quantity = { label = "Qty", occurrence = 2 }

[main_reports.crosswalk]
version = 2

[[main_reports.crosswalk.entries]]
source_category = "Example Fundraiser"
targets = [{ category = "Fundraiser Income", share = "0.75" },
           { category = "Spirit Wear", share = "0.25" }]
note = "documented split"
"""


def test_missing_main_reports_section_yields_none(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, _FULL_CONFIG)).main_reports is None


def test_main_reports_section_parses_bindings(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, _FULL_CONFIG + _MAIN_REPORTS_SECTION))
    main = cfg.main_reports
    assert main is not None
    assert main.source_spreadsheet_id == "fake-cfo-workbook-id"
    assert main.output_path == (tmp_path / "reports" / "output" / "runs").resolve()
    assert main.assumptions_tab == "Assumptions"
    assert [s.alias for s in main.sources] == ["bank-checking", "wix"]

    bank, wix = main.sources
    assert (bank.kind, bank.tab, bank.tab_id) == ("bank", "Bank Checking", 1001)
    assert bank.header_signature == (("DATE", "DESCRIPTION", "AMOUNT"),)
    assert [(c.start, c.end, c.end_exclusive) for c in bank.coverage] == [
        (date(2030, 1, 1), date(2030, 1, 31), date(2030, 2, 1)),
        (date(2030, 2, 1), date(2030, 2, 28), date(2030, 3, 1)),
    ]
    assert wix.tab_id is None
    columns = dict(wix.columns)
    assert (columns["transaction_status"].label, columns["transaction_status"].group) == (
        "Status",
        "Payment",
    )
    assert columns["order_id"].label == "Order Number" and columns["order_id"].group is None
    assert columns["quantity"].occurrence == 2

    assert main.crosswalk is not None and main.crosswalk.version == 2
    (entry,) = main.crosswalk.entries
    assert [(t.category, t.share) for t in entry.targets] == [
        ("Fundraiser Income", Decimal("0.75")),
        ("Spirit Wear", Decimal("0.25")),
    ]


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        (
            'source_spreadsheet_id = "fake-cfo-workbook-id"\n',
            "",
            "main_reports.source_spreadsheet_id",
        ),
        (
            "[main_reports.sources.wix]\n",
            "[main_reports.sources.Bad_Alias]\n",
            "main_reports.sources.Bad_Alias",
        ),
        (
            'output_dir = "reports/output/runs"',
            'output_dir = "docs/runs"',
            "main_reports.output_dir",
        ),
        (
            'output_dir = "reports/output/runs"',
            'output_dir = "reports/../docs"',
            "main_reports.output_dir",
        ),
        ('kind = "bank"', 'kind = "ledger"', "main_reports.sources.bank-checking.kind"),
        ("tab_id = 1001", 'tab_id = "1001"', "main_reports.sources.bank-checking.tab_id"),
        (
            'header_signature = [["DATE", "DESCRIPTION", "AMOUNT"]]',
            'header_signature = ["DATE", "DESCRIPTION"]',
            "main_reports.sources.bank-checking.header_signature",
        ),
        (
            'start = "2030-01-01", end = "2030-01-31"',
            'start = "2030-01-31", end = "2030-01-01"',
            "main_reports.sources.bank-checking.coverage[0]",
        ),
        (
            'end = "2030-01-31"',
            'end = "2030/01/31"',
            "main_reports.sources.bank-checking.coverage[0].end",
        ),
        (
            ', evidence = "example-statement-index" }',
            " }",
            "main_reports.sources.bank-checking.coverage[0].evidence",
        ),
        (
            "occurrence = 2",
            "occurrence = 0",
            "main_reports.sources.wix.columns.quantity.occurrence",
        ),
        ('share = "0.25"', 'share = "0.20"', "main_reports.crosswalk.entries[0].targets"),
        ('share = "0.25"', 'share = "-0.25"', "main_reports.crosswalk.entries[0].targets[1].share"),
    ],
)
def test_main_reports_section_fails_fast_naming_field(
    tmp_path: Path, old: str, new: str, field: str
) -> None:
    text = _FULL_CONFIG + _MAIN_REPORTS_SECTION
    assert old in text
    with pytest.raises(ConfigError) as caught:
        load_config(_write(tmp_path, text.replace(old, new, 1)))
    assert caught.value.field == field


@pytest.mark.parametrize(
    "spelling",
    [
        "{project}/reports/output/../../docs",  # absolute with '..' (lexically "under" output)
        "{project}/reports/output/..",
        "{project}/docs",
        "reports/output/../../docs",  # relative with '..'
        "./reports/../docs/runs",
    ],
)
def test_main_reports_output_dir_cannot_escape_into_the_project(
    tmp_path: Path, spelling: str
) -> None:
    raw = spelling.format(project=tmp_path.resolve().as_posix())
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f'output_dir = "{raw}"'
    )
    with pytest.raises(ConfigError) as caught:
        load_config(_write(tmp_path, text))
    assert caught.value.field == "main_reports.output_dir"


def _alias_spellings_of_docs(project: Path) -> dict[str, str]:
    """Every known spelling of ``<project>/docs`` (structural regression for the guard)."""
    windows = str(project)
    drive, rest = os.path.splitdrive(windows)
    return {
        "plain-absolute": f"{windows}\\docs",
        "relative-dotdot": "reports/output/../../docs",
        "extended-backslash": f"\\\\?\\{windows}\\docs",
        "extended-forward": f"//?/{project.as_posix()}/docs",
        "device": f"\\\\.\\{windows}\\docs",
        "unc-admin-share": f"\\\\localhost\\{drive.rstrip(':')}$" + f"{rest}\\docs",
    }


# Derived from the one table of spellings, so a new spelling can never go unexercised.
_ALIAS_NAMES = tuple(_alias_spellings_of_docs(Path("C:/example-project")))


@pytest.mark.parametrize(
    "layout", ["docs-exists", "docs-absent", "private-root-exists", "reports-only"]
)
@pytest.mark.parametrize("alias", _ALIAS_NAMES)
def test_main_reports_output_dir_guard_uses_filesystem_identity(
    tmp_path: Path, alias: str, layout: str
) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    if layout == "docs-exists":
        (project / "docs").mkdir()
    elif layout == "private-root-exists":
        (project / "reports" / "output").mkdir(parents=True)
    elif layout == "reports-only":
        (project / "reports").mkdir()
    raw = _alias_spellings_of_docs(project)[alias]
    if alias == "unc-admin-share" and not Path(raw).parent.exists():
        pytest.skip("UNC admin share \\\\localhost\\<drive>$ is not reachable on this host")
    # TOML literal string (single quotes): backslashes are taken verbatim.
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f"output_dir = '{raw}'"
    )
    with pytest.raises(ConfigError) as caught:
        load_config(_write(project, text))
    assert caught.value.field == "main_reports.output_dir"


@pytest.mark.parametrize("inside", [True, False], ids=["under-reports-output", "outside"])
def test_main_reports_output_dir_guard_accepts_private_and_outside_paths(
    tmp_path: Path, inside: bool
) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    target = project / "reports" / "output" / "x" if inside else tmp_path / "elsewhere" / "x"
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f"output_dir = '{target}'"
    )
    main = load_config(_write(project, text)).main_reports
    assert main is not None and main.output_path == target.resolve()


@pytest.mark.parametrize(
    ("layout", "raw"),
    [
        ("empty-project", "reports/output/runs"),
        ("reports-only", "reports/output/runs"),
        ("empty-project", "reports/output"),
        ("reports-only", "{project}\\reports\\output\\runs"),
    ],
)
def test_loading_config_never_creates_the_private_output_directory(
    tmp_path: Path, layout: str, raw: str
) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    if layout == "reports-only":
        (project / "reports").mkdir()
    before = sorted(path.relative_to(project) for path in project.rglob("*"))
    value = raw.format(project=project)
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f"output_dir = '{value}'"
    )
    config_path = _write(project, text)
    main = load_config(config_path).main_reports
    assert main is not None
    assert main.output_path == (project / Path(value)).resolve()
    assert not (project / "reports" / "output").exists()
    after = sorted(path.relative_to(project) for path in project.rglob("*") if path != config_path)
    assert after == before  # nothing created (dry-run performs no local writes)


@pytest.mark.parametrize("raw", ["reports", "reports/outputs/x", "reports/other/output", "."])
def test_absent_private_root_tail_must_start_with_reports_output(tmp_path: Path, raw: str) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f"output_dir = '{raw}'"
    )
    with pytest.raises(ConfigError) as caught:
        load_config(_write(project, text))
    assert caught.value.field == "main_reports.output_dir"
    assert not (project / "reports").exists()


def test_main_reports_absolute_output_dir_under_private_root_is_normalized(
    tmp_path: Path,
) -> None:
    raw = f"{tmp_path.resolve().as_posix()}/reports/output/x/../runs"
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f'output_dir = "{raw}"'
    )
    main = load_config(_write(tmp_path, text)).main_reports
    assert main is not None
    assert main.output_path == (tmp_path / "reports" / "output" / "runs").resolve()
    assert ".." not in main.output_path.parts


def test_main_reports_output_dir_may_live_outside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = (tmp_path / "private-drive" / "runs").resolve()
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f'output_dir = "{outside.as_posix()}"'
    )
    main = load_config(_write(project, text)).main_reports
    assert main is not None and main.output_path == outside


# --------------------------------------------------------------------------------------
# output_dir guard: existing reports/output, ancestors, fail-closed, links
# --------------------------------------------------------------------------------------


def _config_with_output_dir(project: Path, value: str) -> Path:
    text = (_FULL_CONFIG + _MAIN_REPORTS_SECTION).replace(
        'output_dir = "reports/output/runs"', f"output_dir = '{value}'"
    )
    return _write(project, text)


def _project_with_private_root(tmp_path: Path) -> Path:
    project = (tmp_path / "project").resolve()
    (project / "reports" / "output").mkdir(parents=True)
    return project


@pytest.mark.parametrize("raw", ["reports/output/x", "{project}\\reports\\output\\x\\y"])
def test_existing_private_root_accepts_paths_below_it(tmp_path: Path, raw: str) -> None:
    project = _project_with_private_root(tmp_path)
    value = raw.format(project=project)
    main = load_config(_config_with_output_dir(project, value)).main_reports
    assert main is not None and main.output_path == (project / Path(value)).resolve()


@pytest.mark.parametrize("raw", ["reports/outputs/x", "reports/x", "reports", "docs"])
def test_existing_private_root_rejects_siblings(tmp_path: Path, raw: str) -> None:
    project = _project_with_private_root(tmp_path)
    with pytest.raises(ConfigError) as caught:
        load_config(_config_with_output_dir(project, raw))
    assert caught.value.field == "main_reports.output_dir"


@pytest.mark.parametrize("raw", ["..", ".", "{parent}", "{project}"])
def test_output_dir_may_not_be_the_project_or_an_ancestor(tmp_path: Path, raw: str) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    value = raw.format(parent=project.parent, project=project)
    with pytest.raises(ConfigError) as caught:
        load_config(_config_with_output_dir(project, value))
    assert caught.value.field == "main_reports.output_dir"


def test_output_dir_identity_check_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    config_path = _config_with_output_dir(project, str(tmp_path / "elsewhere"))

    def unverifiable(a: object, b: object) -> bool:
        raise OSError("identity unavailable")

    monkeypatch.setattr(os.path, "samefile", unverifiable)
    with pytest.raises(ConfigError) as caught:
        load_config(config_path)
    assert caught.value.field == "main_reports.output_dir"
    assert "could not be verified" in str(caught.value)


def _make_directory_link(link: Path, target: Path) -> None:
    """A junction on Windows (no privilege needed), a symlink elsewhere; skip if neither."""
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return
    except (ImportError, AttributeError, OSError):
        pass
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"cannot create a directory junction or symlink on this host: {exc}")


@pytest.mark.parametrize("raw", ["reports/output/x", "reports/output"])
def test_private_root_linked_into_tracked_docs_is_rejected(tmp_path: Path, raw: str) -> None:
    project = (tmp_path / "project").resolve()
    (project / "docs").mkdir(parents=True)
    (project / "reports").mkdir()
    _make_directory_link(project / "reports" / "output", project / "docs")
    with pytest.raises(ConfigError) as caught:
        load_config(_config_with_output_dir(project, raw))
    assert caught.value.field == "main_reports.output_dir"


# --------------------------------------------------------------------------------------
# output_dir guard: a ``reports`` junction into tracked ``docs/`` is refused
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("output_present", [False, True], ids=["output-absent", "output-present"])
@pytest.mark.parametrize("raw", ["reports/output/x", "reports/output"])
def test_reports_linked_into_tracked_docs_is_rejected(
    tmp_path: Path, output_present: bool, raw: str
) -> None:
    project = (tmp_path / "project").resolve()
    (project / "docs").mkdir(parents=True)
    if output_present:
        (project / "docs" / "output").mkdir()  # so <project>/reports/output exists via the link
    _make_directory_link(project / "reports", project / "docs")
    before = sorted(path.name for path in (project / "docs").rglob("*"))
    with pytest.raises(ConfigError) as caught:
        load_config(_config_with_output_dir(project, raw))
    assert caught.value.field == "main_reports.output_dir"
    assert sorted(path.name for path in (project / "docs").rglob("*")) == before  # no writes


def test_output_dir_that_resolves_to_a_relative_location_is_rejected(tmp_path: Path) -> None:
    if Path("a:/").exists():
        pytest.skip("drive a: exists on this host, so a:b resolves to an absolute path")
    project = (tmp_path / "project").resolve()
    project.mkdir()
    with pytest.raises(ConfigError) as caught:
        load_config(_config_with_output_dir(project, "a:b"))
    assert caught.value.field == "main_reports.output_dir"
