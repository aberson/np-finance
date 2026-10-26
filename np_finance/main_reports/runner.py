"""Run the Main Report Set end to end and publish it only after the whole set validates.

:func:`run` is the production caller behind ``np-finance end-to-end-run``
(``docs/plan-reference/cfo-main-report-set.md`` sections 5, 6F and 10). One run:

1. takes the exclusive local writer lock in the private output root (a second writer fails
   with ``run_busy``); the lock is held through publication and released in ``finally``;
2. captures every bound CFO tab, our adopted budget and Assumptions once, through the
   read-only clients (:func:`~np_finance.main_reports.sources.capture`);
3. optionally acquires a Gmail window, then refreshes the private reimbursement bundle and
   prepares receipts IN PLACE with the same production components ``update-reimbursements``
   uses (the bundle is the private evidence store, refreshed atomically and idempotently,
   not a publication); the bundle and sidecar digests before and after are recorded;
4. records adjustment proposals ONLY for an explicit ``--adjustments-file`` (the single
   Sheets write, to our own workbook's journal) and then recaptures, so facts are always
   built from the journal as it now reads; reruns record nothing twice;
5. stages the refreshed bundle, its receipt sidecar and every referenced page byte for byte
   into the run's own ``inputs/`` folder, builds the facts from that staged copy and renders
   all five reports, the summary PDF/PNG exports and the run index into a fresh
   ``<output_dir>/<run-id>/`` folder whose rendered files never change afterwards;
6. re-hashes and checks the complete set (every page names this run and input set), writes
   the run manifest, and only then switches the single current-run pointer
   (``main-report-set.html`` in the folder above ``output_dir``, replaced atomically) and
   refreshes the compatibility filenames one by one, retaining the replaced files and
   reporting every copy that could not be refreshed.

Every failure after argument validation takes one path: a value-free record in
``failed-runs/<run-id>.json`` and a ``failed`` manifest in the run folder (stage, codes, the
type name of an unexpected error, and any journal write already made), the previous
publication left byte for byte as it was, and a non-zero result. A failed run may already
have refreshed the private evidence bundle; it never changes the published set. An interrupt
(``KeyboardInterrupt``) is recorded the same way and then re-raised; the CLI turns it into
exit 130. After the pointer switch, publication has succeeded: a compatibility copy that
fails, or an interrupt during the copies, is recorded per copy with a ``partial`` refresh
state; an interrupt is then re-raised. Multi-file copy refresh is never claimed to be atomic.

``dry_run`` reads and validates the live Sheets and the existing local evidence through the
same capture, reconciliation, journal projection, bundle-refresh plan and fact projection,
and writes nothing at all: no run folder, lock, capture store, snapshot, token, bundle,
report or Sheets cell. It refuses mail acquisition and adjustment writes. Reading the
service-account key file is its only local file access beyond the inputs it validates.

Never invoked: bank PDF extraction, any scheduler, mail sending, or a CFO workbook write.
Error text names stages, codes, counts and local paths only, never a cell or money value or
a workbook identifier; transport failures are reduced to their type and HTTP status, and an
unexpected error to its type name.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import np_finance
from np_finance import (
    gmail_source,
    receipt_refresh,
    receipt_viewer,
    reimbursement_pipeline,
    reimbursement_report,
)
from np_finance.config import (
    Config,
    ConfigError,
    MainReports,
    _private_output_path,
    load_config,
)
from np_finance.main_reports import adjustments, facts, reconcile, render, sources
from np_finance.main_reports.export import ExportError
from np_finance.main_reports.models import (
    ALIAS_REFRESH_STATES,
    ALIAS_STATUSES,
    RUN_STATUSES,
    SCHEMA_VERSION,
    AdjustedLedger,
    Adjustment,
    ArtifactSet,
    CaptureSet,
    Reconciliation,
    ReportFacts,
    RunManifest,
    canonical_json_bytes,
    content_hash,
    make_run_id,
    sha256_hex,
)
from np_finance.main_reports.sources import Clock
from np_finance.sheets import SHEETS_FAILURES, http_status

__all__ = [
    # constants
    "EXIT_OK",
    "EXIT_FAILED",
    "EXIT_INVALID",
    "EXIT_INTERRUPTED",
    "RUN_ERROR_CODES",
    "INVALID_INPUT_CODES",
    "RUN_STAGES",
    "INPUT_COMPONENTS",
    "MANIFEST_NAME",
    "INPUTS_DIR",
    "RECORDS_DIR",
    "PUBLICATION_DIR",
    "PREVIOUS_DIR",
    "FAILED_RUNS_DIR",
    "POINTER_NAME",
    "LEGACY_QUEUE_HTML",
    "LEGACY_QUEUE_COPY_TEXT",
    "COMPATIBILITY_FILES",
    # functions
    "check_request",
    "mail_window",
    "load_run_config",
    "input_set_sha256",
    "run",
    # types
    "RunnerError",
    "MailWindow",
    "RunOptions",
    "RunResult",
    "StagedBundle",
]

# Process exit codes (contract section 10): published / dry-run validated, operational
# failure or conflict (the prior pointer is kept), invalid arguments or configuration, and
# the conventional code for an interrupted command (used by the CLI).
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID = 2
EXIT_INTERRUPTED = 130

# The runner's own failure codes. A refused lock reports the code of
# :class:`~np_finance.main_reports.adjustments.RunBusyError` (``run_busy``), its owner.
RUN_ERROR_CODES: tuple[str, ...] = (
    "options_invalid",
    "config_invalid",
    "adjustments_file_invalid",
    "output_unavailable",
    "capture_failed",
    "reconcile_failed",
    "mail_failed",
    "reimbursement_failed",
    "receipts_failed",
    "adjustments_failed",
    "capture_store_failed",
    "staging_failed",
    "facts_failed",
    "records_failed",
    "render_failed",
    "validation_failed",
    "manifest_failed",
    "publish_failed",
    "alias_refresh_failed",
    "alias_refresh_interrupted",
    "unexpected_failure",
    "interrupted",
)
(
    _OPTIONS_INVALID,
    _CONFIG_INVALID,
    _ADJUSTMENTS_FILE_INVALID,
    _OUTPUT_UNAVAILABLE,
    _CAPTURE_FAILED,
    _RECONCILE_FAILED,
    _MAIL_FAILED,
    _REIMBURSEMENT_FAILED,
    _RECEIPTS_FAILED,
    _ADJUSTMENTS_FAILED,
    _CAPTURE_STORE_FAILED,
    _STAGING_FAILED,
    _FACTS_FAILED,
    _RECORDS_FAILED,
    _RENDER_FAILED,
    _VALIDATION_FAILED,
    _MANIFEST_FAILED,
    _PUBLISH_FAILED,
    _ALIAS_REFRESH_FAILED,
    _ALIAS_REFRESH_INTERRUPTED,
    _UNEXPECTED_FAILURE,
    _INTERRUPTED,
) = RUN_ERROR_CODES
# Codes that mean the request itself is invalid (exit 2); every other code exits 1.
INVALID_INPUT_CODES = frozenset({_OPTIONS_INVALID, _CONFIG_INVALID, _ADJUSTMENTS_FILE_INVALID})

# The stages a run passes through, in order; a failure record names the one it reached.
RUN_STAGES: tuple[str, ...] = (
    "start",
    "capture",
    "mail",
    "refresh",
    "adjustments",
    "staging",
    "facts",
    "render",
    "validation",
    "publication",
    "compatibility",
)
(
    _START,
    _CAPTURE,
    _MAIL,
    _REFRESH,
    _ADJUSTMENTS,
    _STAGING,
    _FACTS,
    _RENDER,
    _VALIDATION,
    _PUBLICATION,
    _COMPATIBILITY,
) = RUN_STAGES

_FAILED_STATUS, _VALIDATED, _PUBLISHED = RUN_STATUSES
_REFRESHED, _ALIAS_FAILED, _NOT_ATTEMPTED = ALIAS_STATUSES
_PENDING, _COMPLETE, _PARTIAL = ALIAS_REFRESH_STATES

# Everything the input-set hash covers (:func:`input_set_sha256`), recorded in the manifest.
INPUT_COMPONENTS: tuple[str, ...] = (
    "capture_aggregate_sha256",
    "journal_sha256",
    "crosswalk_sha256",
    "bundle_sha256",
    "sidecar_sha256",
    "receipt_pages",
    "start_month",
    "assumptions_tab",
    "as_of",
)

# Layout of one run folder and of the publication root (the parent of ``output_dir``).
MANIFEST_NAME = "run-manifest.json"
INPUTS_DIR = "inputs"
RECORDS_DIR = "records"
PUBLICATION_DIR = "publication"
PREVIOUS_DIR = "previous"
FAILED_RUNS_DIR = "failed-runs"
# The single current-run pointer; the summaries' footer links to this name, so their
# compatibility copies beside the pointer link back to it.
POINTER_NAME = render.INDEX_HTML
# The queue filename ``update-reimbursements`` and ``report-reimbursements`` publish.
LEGACY_QUEUE_HTML = "reimbursement-queue-breakdown.html"
LEGACY_QUEUE_COPY_TEXT = f"{Path(LEGACY_QUEUE_HTML).stem}.copy.txt"
# (run file, compatibility filename in the publication root), refreshed in this order after
# the pointer switch: every run file under its own name (so the copies' relative links keep
# working beside the pointer), then the queue and its copy text under the legacy names.
COMPATIBILITY_FILES: tuple[tuple[str, str], ...] = (
    *((name, name) for name in render.OUTPUT_NAMES if name != render.INDEX_HTML),
    (render.QUEUE_HTML, LEGACY_QUEUE_HTML),
    (render.QUEUE_COPY_TEXT, LEGACY_QUEUE_COPY_TEXT),
)

_RECORD_FILES = ("facts.json", "reconciliation.json", "adjusted-ledger.json", "journal.json")
_SUMMARY_HTML = tuple(f"{name}.html" for name in render.SUMMARY_NAMES)
_PACKAGE_SUFFIXES = frozenset({".py", ".j2"})

# Module errors whose text is value-free by contract (codes, counts, rows, fields). Sheets
# transport failures (sheets.SHEETS_FAILURES) are reduced to their type and HTTP status
# before they reach any output.
_TYPED_FAILURES: tuple[type[BaseException], ...] = (
    sources.SourceError,
    reconcile.ReconcileError,
    adjustments.AdjustmentError,
    facts.FactsError,
    render.RenderError,
    ExportError,
    gmail_source.GmailError,
    reimbursement_pipeline.ReimbursementPipelineError,
    reimbursement_report.ReimbursementReportError,
    receipt_refresh.ReceiptRefreshError,
    receipt_viewer.ReceiptViewerError,
)


# --------------------------------------------------------------------------------------
# Errors and requests
# --------------------------------------------------------------------------------------


class RunnerError(Exception):
    """One stage of the run failed. ``code`` is a :data:`RUN_ERROR_CODES` entry and
    ``exit_code`` follows from it; the text names the stage cause, never a cell or money
    value, and the exception carries no chained cause or context.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.exit_code = EXIT_INVALID if code in INVALID_INPUT_CODES else EXIT_FAILED
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class MailWindow:
    """An optional Gmail acquisition window (``--fetch-since`` semantics: ``until`` is
    exclusive; ``query`` is appended; ``limit`` caps the messages fetched)."""

    since: date
    until: date | None = None
    query: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class RunOptions:
    """One end-to-end request.

    The reimbursement inputs mirror ``update-reimbursements`` (resolved by the CLI with the
    same defaults); ``config_dir`` is the directory holding ``config.toml``, used to confine
    the publication root. ``adjustments_file`` is the explicit opt-in to the journal write.
    """

    as_of: date
    config_dir: Path
    bundle_path: Path
    source: Path
    category_map_path: Path
    anchors_path: Path | None = None
    subject_filter: str | None = None
    received_since: date | None = None
    dry_run: bool = False
    adjustments_file: Path | None = None
    mail_window: MailWindow | None = None


@dataclass(frozen=True)
class RunResult:
    """Outcome of :func:`run`. A dry run never has output paths."""

    exit_code: int
    run_id: str | None = None
    manifest_path: Path | None = None
    index_path: Path | None = None
    coverage_warnings: tuple[str, ...] = ()
    alias_failures: tuple[str, ...] = ()
    failure_code: str | None = None


@dataclass(frozen=True)
class StagedBundle:
    """The reimbursement bundle staged into a run, with the hashes of what was copied."""

    path: Path
    bundle_sha256: str
    sidecar_sha256: str | None
    pages: tuple[tuple[str, str], ...]


def _detail(error: BaseException) -> str:
    """A value-free description: module error text, or a transport type plus HTTP status."""
    if isinstance(error, _TYPED_FAILURES):
        return str(error)
    status = http_status(error)
    name = type(error).__name__
    return name if status is None else f"{name} {status}"


def _attempt[T](code: str, action: Callable[[], T]) -> T:
    """Run one stage; map its expected failures to :class:`RunnerError` ``code``.

    The new error is raised after the handler has finished, so it carries neither a cause
    nor a context that could hold a cell value or workbook identifier.
    """
    detail: str
    try:
        return action()
    except (*_TYPED_FAILURES, *SHEETS_FAILURES) as error:
        detail = _detail(error)
    raise RunnerError(code, detail)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def mail_window(
    since: date | None, until: date | None, query: str | None, limit: int | None
) -> MailWindow | None:
    """The ``--fetch-*`` options as a window; ``None`` without ``--fetch-since``.

    The other fetch options need ``--fetch-since`` (``options_invalid`` otherwise).
    """
    if since is None:
        if any(value is not None for value in (until, query, limit)):
            raise RunnerError(
                _OPTIONS_INVALID,
                "--fetch-until, --fetch-query, and --fetch-limit require --fetch-since",
            )
        return None
    return MailWindow(since=since, until=until, query=query, limit=limit)


def check_request(
    *, dry_run: bool, mail_window: MailWindow | None, adjustments_file: Path | None
) -> None:
    """Refuse an invalid request before configuration, authentication or any read.

    A dry run writes nothing, so it cannot acquire mail or record adjustments; a mail
    window must end after it starts (``until`` is exclusive). Raises ``options_invalid``.
    """
    if dry_run and mail_window is not None:
        raise RunnerError(
            _OPTIONS_INVALID, "--dry-run cannot acquire mail (remove the --fetch-* options)"
        )
    if dry_run and adjustments_file is not None:
        raise RunnerError(
            _OPTIONS_INVALID, "--dry-run cannot record adjustments (remove --adjustments-file)"
        )
    if mail_window is None:
        return
    if mail_window.until is not None and mail_window.until <= mail_window.since:
        raise RunnerError(
            _OPTIONS_INVALID,
            "--fetch-until must be after --fetch-since (the until date is exclusive)",
        )
    if mail_window.limit is not None and mail_window.limit < 1:
        raise RunnerError(_OPTIONS_INVALID, "--fetch-limit must be a positive number")


def load_run_config(path: Path) -> Config:
    """Load ``config.toml`` for a run; every failure is ``config_invalid`` (exit 2)."""
    detail: str
    try:
        return load_config(path)
    except ConfigError as error:
        detail = str(error)
    except tomllib.TOMLDecodeError:
        detail = "the config file is not valid TOML"
    except OSError as error:
        detail = f"the config file cannot be read ({type(error).__name__})"
    raise RunnerError(_CONFIG_INVALID, detail)


def _publication_root(main_reports: MainReports, config_dir: Path) -> Path:
    """The folder holding the current-run pointer and compatibility files: the parent of
    the runs folder, used ONLY if it passes the same private-output guard as
    ``main_reports.output_dir`` (inside the project: under ``reports/output/``; outside it:
    the operator's choice). Reads only.
    """
    detail: str
    try:
        return _private_output_path(str(main_reports.output_path.parent), config_dir)
    except ConfigError as error:
        detail = (
            "the folder above main_reports.output_dir holds the published pointer and must "
            f"also be under reports/output/ or outside the project ({error.field})"
        )
    except OSError as error:
        detail = (
            "the folder above main_reports.output_dir could not be verified "
            f"({type(error).__name__})"
        )
    raise RunnerError(_CONFIG_INVALID, detail)


def _load_proposals(path: Path | None) -> tuple[Adjustment, ...]:
    if path is None:
        return ()
    detail: str
    try:
        return adjustments.load_proposals(path)
    except adjustments.AdjustmentError as error:
        detail = str(error)
    raise RunnerError(_ADJUSTMENTS_FILE_INVALID, detail)


def _validate(options: RunOptions, config: Config) -> tuple[MainReports, Path]:
    check_request(
        dry_run=options.dry_run,
        mail_window=options.mail_window,
        adjustments_file=options.adjustments_file,
    )
    detail: str
    try:
        sources.require_bindings(config)  # the owner of the [main_reports] presence check
    except sources.SourceError as error:
        detail = str(error)
    else:
        main_reports = cast(MainReports, config.main_reports)  # present: bindings resolved
        return main_reports, _publication_root(main_reports, options.config_dir)
    raise RunnerError(_CONFIG_INVALID, detail)


# --------------------------------------------------------------------------------------
# Input-set identity
# --------------------------------------------------------------------------------------


def input_set_sha256(components: Mapping[str, Any]) -> str:
    """The one hash every artifact of a run is identified by.

    ``components`` must hold exactly :data:`INPUT_COMPONENTS` (JSON values: digests, the
    receipt-page ``[path, sha256]`` pairs, the fiscal start month, the Assumptions tab and
    the ISO as-of date); changing any one of them changes the hash.
    """
    if set(components) != set(INPUT_COMPONENTS):
        raise ValueError("the input-set components must be exactly INPUT_COMPONENTS")
    return content_hash({"schema_version": SCHEMA_VERSION, **components})


def _input_components(
    capture_set: CaptureSet,
    ledger: AdjustedLedger,
    staged: StagedBundle,
    config: Config,
    main_reports: MainReports,
    as_of: date,
) -> tuple[tuple[str, Any], ...]:
    values: dict[str, Any] = {
        "capture_aggregate_sha256": capture_set.aggregate_sha256,
        "journal_sha256": ledger.journal_sha256,
        "crosswalk_sha256": reconcile.crosswalk_digest(main_reports.crosswalk),
        "bundle_sha256": staged.bundle_sha256,
        "sidecar_sha256": staged.sidecar_sha256,
        "receipt_pages": [list(pair) for pair in staged.pages],
        "start_month": config.fiscal_year.start_month,
        "assumptions_tab": main_reports.assumptions_tab,
        "as_of": as_of.isoformat(),
    }
    return tuple((name, values[name]) for name in INPUT_COMPONENTS)


# --------------------------------------------------------------------------------------
# Progress and failure records
# --------------------------------------------------------------------------------------


@dataclass
class _Progress:
    """Where the run is and what it has established; every failure record is built from it.

    ``published`` turns true once the pointer names this run: later failures are recorded
    by the compatibility refresh, never as a failed run.
    """

    manifest: RunManifest
    stage: str = _START
    published: bool = False

    def enter(self, stage: str) -> None:
        self.stage = stage

    def note(self, **changes: Any) -> None:
        self.manifest = replace(self.manifest, **changes)


def _write_manifest(run_dir: Path, manifest: RunManifest) -> Path:
    path = run_dir / MANIFEST_NAME
    sources._atomic_write(path, canonical_json_bytes(manifest.to_dict()))
    return path


def _record_failure(
    root: Path, run_dir: Path, progress: _Progress, code: str, failure_type: str | None = None
) -> None:
    """Record a failed run (best effort) without touching publication.

    The record carries the stage, the code and, for an unexpected error, only its type name
    (never its text), plus everything the run had established, journal writes included.
    The run folder's manifest is marked ``failed`` so it can never be taken for a validated
    set (a never-published run carries no publication time or copy state); the folder itself
    stays as evidence.
    """
    failed = replace(
        progress.manifest,
        status=_FAILED_STATUS,
        stage=progress.stage,
        failure_codes=(code,),
        failure_type=failure_type,
        published_at=None,
        alias_refresh_state=None,
    )
    data = canonical_json_bytes(failed.to_dict())
    try:
        folder = root / FAILED_RUNS_DIR
        folder.mkdir(exist_ok=True)
        sources._atomic_write(folder / f"{failed.run_id}.json", data)
        if run_dir.is_dir():
            sources._atomic_write(run_dir / MANIFEST_NAME, data)
    except OSError:
        pass


def _journal_hint(progress: _Progress, out: Callable[[str], None]) -> None:
    """Tell the operator when a failed run's journal write may have reached the tab."""
    if progress.manifest.journal_write_may_have_landed:
        out(
            "  journal       : the Assumptions journal write may have landed; check the tab "
            "before rerunning (the failure record lists the snapshot and attempted IDs)"
        )


# --------------------------------------------------------------------------------------
# Sources, reimbursements and adjustments
# --------------------------------------------------------------------------------------


def _capture(config: Config, clock: Clock | None) -> tuple[CaptureSet, Reconciliation]:
    capture_set = _attempt(_CAPTURE_FAILED, lambda: sources.capture(config, clock=clock))
    reconciliation = _attempt(
        _RECONCILE_FAILED, lambda: reconcile.from_capture(capture_set, config)
    )
    return capture_set, reconciliation


def _project(
    capture_set: CaptureSet, reconciliation: Reconciliation, as_of: date
) -> AdjustedLedger:
    return _attempt(
        _ADJUSTMENTS_FAILED,
        lambda: adjustments.project(
            reconciliation, adjustments.read_journal(capture_set.assumptions), as_of
        ),
    )


def _refresh_kwargs(options: RunOptions, config: Config) -> dict[str, Any]:
    return {
        "bundle_path": options.bundle_path,
        "source": options.source,
        "category_map_path": options.category_map_path,
        "start_month": config.fiscal_year.start_month,
        "received_since": options.received_since,
        "as_of": options.as_of,
        "subject_filter": options.subject_filter,
        "anchors_path": options.anchors_path,
    }


def _fetch_mail(
    window: MailWindow, config: Config, source: Path, service: Any, out: Callable[[str], None]
) -> None:
    if source.exists() and not source.is_dir():
        raise RunnerError(_MAIL_FAILED, "the combined fetch source must be a directory")

    def fetch() -> gmail_source.FetchSummary:
        client = service
        if client is None:
            if gmail_source.needs_consent(config):
                out(
                    "no Gmail token on this machine yet — opening a browser for the one-time, "
                    "READ-ONLY consent"
                )
            client = gmail_source.build_service(gmail_source.load_or_mint_credentials(config))
        return gmail_source.fetch_window(
            client,
            since=window.since,
            until=window.until,
            extra_query=window.query,
            out_dir=source,
            limit=window.limit,
            dry_run=False,
        )

    fetched = _attempt(_MAIL_FAILED, fetch)
    out(
        f"  email archive : {fetched.new} new, {fetched.unchanged} unchanged, "
        f"{fetched.rewritten} rewritten"
    )


def _print_refresh(
    out: Callable[[str], None],
    summary: reimbursement_pipeline.BundleMergeSummary,
    receipts: receipt_refresh.RefreshSummary,
) -> None:
    out(
        f"  reimbursements: {summary.total_source_tickets} source submission(s), "
        f"{summary.mapped_rows} line(s); {summary.new_tickets} new, "
        f"{summary.unchanged_tickets} unchanged; {summary.supplemental_events} event(s), "
        f"{summary.unmatched_evidence} unmatched"
    )
    if receipts.configured:
        out(
            f"  receipt prep  : {receipts.linked} linked, {receipts.marked} automatic mark(s), "
            f"{receipts.review_needed} review-needed, {receipts.refused_assets} refused asset(s)"
        )
    else:
        out("  receipt prep  : not configured; automatic receipt preparation skipped")


def _digest(path: Path) -> str | None:
    """SHA-256 of a private evidence file, or ``None`` when it does not exist."""
    return sha256_hex(path.read_bytes()) if path.is_file() else None


def _evidence_digests(bundle: Path) -> tuple[str | None, str | None]:
    """Digests of the private bundle and its receipt sidecar (``None`` if absent)."""
    return _digest(bundle), _digest(bundle.with_suffix(".receipts.json"))


def _refresh_reimbursements(
    options: RunOptions, config: Config, progress: _Progress, out: Callable[[str], None]
) -> None:
    """Refresh the private evidence store in place and record its digests before/after."""
    before, sidecar_before = _attempt(
        _REIMBURSEMENT_FAILED, lambda: _evidence_digests(options.bundle_path)
    )
    progress.note(bundle_sha256_before_refresh=before, sidecar_sha256_before_refresh=sidecar_before)
    kwargs = _refresh_kwargs(options, config)
    try:
        summary = _attempt(
            _REIMBURSEMENT_FAILED, lambda: reimbursement_pipeline.refresh_bundle(**kwargs)
        )
        receipts = _attempt(
            _RECEIPTS_FAILED,
            lambda: receipt_refresh.refresh_receipts(
                bundle_path=options.bundle_path,
                source=options.source,
                config=config.receipt_refresh,
                dry_run=False,
            ),
        )
    finally:  # recorded on failure too: a failed refresh may still have changed the store
        try:
            after, sidecar_after = _evidence_digests(options.bundle_path)
        except OSError:
            after = sidecar_after = None
        progress.note(bundle_sha256_after_refresh=after, sidecar_sha256_after_refresh=sidecar_after)
    _print_refresh(out, summary, receipts)


def _relative(path: Path, root: Path) -> str:
    """``path`` relative to the private output root (POSIX), as manifests record it."""
    return Path(os.path.relpath(path, root)).as_posix()


def _record_adjustments(
    proposals: Sequence[Adjustment],
    config: Config,
    capture_set: CaptureSet,
    reconciliation: Reconciliation,
    options: RunOptions,
    lock: adjustments.RunLock,
    clock: Clock | None,
    progress: _Progress,
) -> tuple[str, ...]:
    """Record the proposals; the evidence goes into the progress at once (every later
    failure record carries it). Returns the IDs written in this run.

    The pre-write snapshot is noted as soon as the writer takes it (before anything is sent
    to the tab). If the call then fails in ANY way, interrupts included, the record says
    whether the write may have landed: the writer's own ``may_have_landed`` for its typed
    errors, otherwise ``True`` once the snapshot exists (the write may have begun) and
    ``False`` before it. All evidence paths are relative to the private output root.
    """

    root = cast(MainReports, config.main_reports).output_path
    attempted = tuple(proposal.adjustment_id for proposal in proposals)
    progress.note(adjustments_attempted=attempted)
    write_errors: list[adjustments.AdjustmentWriteError] = []

    def snapshot_taken(path: Path) -> None:
        relative = _relative(path, root)
        progress.note(journal_snapshot=relative, journal_evidence=(relative,))

    def write() -> adjustments.RecordResult:
        client = adjustments.connect_journal_client(config)
        try:
            return adjustments.record(
                proposals,
                config=config,
                client=client,
                captured=capture_set.assumptions,
                reconciliation=reconciliation,
                as_of=options.as_of,
                lock=lock,
                clock=clock,
                on_snapshot=snapshot_taken,
            )
        except adjustments.AdjustmentWriteError as error:
            write_errors.append(error)
            raise

    try:
        result = _attempt(_ADJUSTMENTS_FAILED, write)
    except BaseException:
        if write_errors:  # the writer classified it: keep its verdict and retained evidence
            error = write_errors[0]
            evidence = tuple(_relative(path, root) for path in error.evidence)
            progress.note(
                journal_write_error=error.code,
                journal_write_may_have_landed=error.may_have_landed,
                journal_evidence=evidence,
                journal_snapshot=evidence[0] if evidence else None,
            )
        else:  # unclassified or interrupted: landed is possible once the snapshot exists
            progress.note(
                journal_write_may_have_landed=progress.manifest.journal_snapshot is not None
            )
        raise
    snapshot = None if result.snapshot_path is None else _relative(result.snapshot_path, root)
    progress.note(
        adjustments_written=result.written,
        adjustments_already_recorded=result.already_recorded,
        journal_snapshot=snapshot,
    )
    return result.written


# --------------------------------------------------------------------------------------
# Staging, records and validation
# --------------------------------------------------------------------------------------


def _copy_bytes(source: Path, target: Path) -> str:
    """Copy ``source`` to ``target`` exactly; return the SHA-256 of the bytes written."""
    payload = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(payload)
    return sha256_hex(payload)


def _stage_bundle(live: Path, inputs: Path) -> StagedBundle:
    """Copy the bundle, its receipt sidecar and every page the sidecar names into ``inputs``.

    The sidecar is first checked with the viewer's own page guard (each page inside the
    sidecar folder, present, within the size budget); pages keep their relative paths, so
    the staged sidecar validates exactly as the live one does. Bytes are copied unchanged.
    Two entries naming one page (in any spelling) copy it once.
    """
    staged = inputs / live.name
    bundle_sha = _copy_bytes(live, staged)
    sidecar = live.with_suffix(".receipts.json")
    if not sidecar.exists():
        return StagedBundle(staged, bundle_sha, None, ())
    receipt_viewer.headroom_bytes(sidecar)
    sidecar_sha = _copy_bytes(sidecar, staged.with_suffix(".receipts.json"))
    document = json.loads(staged.with_suffix(".receipts.json").read_text(encoding="utf-8"))
    root = sidecar.resolve().parent
    pages: dict[str, str] = {}
    copied: set[str] = set()
    for page in document["pages"]:
        relative = str(page["path"])
        target = Path(os.path.normpath(inputs / relative))
        if not target.is_relative_to(inputs):
            raise receipt_viewer.ReceiptViewerError(
                "receipt page must be inside the sidecar directory"
            )
        key = os.path.normcase(str(target))
        if key not in copied:
            copied.add(key)
            pages[relative] = _copy_bytes((root / relative).resolve(), target)
    return StagedBundle(staged, bundle_sha, sidecar_sha, tuple(sorted(pages.items())))


def _write_records(
    run_dir: Path,
    report: ReportFacts,
    reconciliation: Reconciliation,
    ledger: AdjustedLedger,
    capture_set: CaptureSet,
) -> tuple[tuple[str, str], ...]:
    """Persist the run's private records; returns (run-relative path, SHA-256) pairs."""
    folder = run_dir / RECORDS_DIR
    folder.mkdir()
    payloads = (
        report.to_dict(),
        reconciliation.to_dict(),
        ledger.to_dict(),
        adjustments.read_journal(capture_set.assumptions).to_dict(),
    )
    written: list[tuple[str, str]] = []
    for name, payload in zip(_RECORD_FILES, payloads, strict=True):
        data = canonical_json_bytes(payload)
        sources._atomic_write(folder / name, data)
        written.append((f"{RECORDS_DIR}/{name}", sha256_hex(data)))
    return tuple(written)


def _check_set(run_dir: Path, artifacts: ArtifactSet, run_id: str, input_sha: str) -> None:
    """The complete set is on disk exactly as rendered and every page names this run and
    this input set."""
    problems = 0
    if artifacts.run_id != run_id or sorted(artifacts.paths) != sorted(render.OUTPUT_NAMES):
        problems += 1
    for artifact in artifacts.artifacts:
        payload = (run_dir / artifact.path).read_bytes()
        if len(payload) != artifact.byte_length or sha256_hex(payload) != artifact.sha256:
            problems += 1
    markers = (str(render.run_id_meta(run_id)), str(render.input_set_meta(input_sha)))
    for name in (*_SUMMARY_HTML, render.INDEX_HTML):
        html = (run_dir / name).read_text(encoding="utf-8")
        problems += sum(1 for marker in markers if marker not in html)
    if any(entry.name.startswith(render.STAGING_PREFIX) for entry in run_dir.iterdir()):
        problems += 1
    if problems:
        raise RunnerError(
            _VALIDATION_FAILED, f"{problems} check(s) of the rendered set failed; not published"
        )


def _check_pointer(page: str, manifest: RunManifest) -> None:
    """The pointer about to be published names this run and its input set."""
    markers = (
        str(render.run_id_meta(manifest.run_id)),
        str(render.input_set_meta(cast(str, manifest.input_sha256))),
        f"/{manifest.run_id}/{render.INDEX_HTML}",
    )
    missing = sum(1 for marker in markers if marker not in page)
    if missing:
        raise RunnerError(
            _PUBLISH_FAILED, f"{missing} check(s) of the current-run pointer failed; not published"
        )


def _pointer_names(root: Path, run_id: str) -> bool:
    """Whether the published pointer already names ``run_id`` (an interrupt can land just
    after the atomic switch, before the runner noted it)."""
    try:
        page = (root / POINTER_NAME).read_text(encoding="utf-8")
    except OSError:
        return False
    return str(render.run_id_meta(run_id)) in page


def _code_revision() -> str:
    """Package version plus a digest of the installed package's code and templates."""
    package = Path(np_finance.__file__).resolve().parent
    digest = hashlib.sha256()
    files = sorted(
        (path.relative_to(package).as_posix(), path)
        for path in package.rglob("*")
        if path.suffix in _PACKAGE_SUFFIXES and path.is_file()
    )
    for name, path in files:
        digest.update(name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return f"{np_finance.__version__}+{digest.hexdigest()[:16]}"


# --------------------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------------------


def _retain(path: Path, backup: Path) -> None:
    """Keep the bytes ``path`` holds now (a hard link where possible, else a copy)."""
    if not path.is_file():
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(path, backup)
    except OSError:
        shutil.copyfile(path, backup)


def _copy_atomic(source: Path, target: Path) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, name)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _refresh_copies(
    root: Path, run_dir: Path, previous: Path
) -> tuple[list[tuple[str, str]], BaseException | None]:
    """Refresh every compatibility copy; any failure marks that copy and the loop goes on.

    An interrupt stops the loop: the copy in progress is ``failed`` (it holds either its old
    or its new complete bytes), the rest ``not_attempted``; the interrupt is returned so the
    caller can record the results before re-raising it.
    """
    results: list[tuple[str, str]] = []
    for index, (run_name, alias) in enumerate(COMPATIBILITY_FILES):
        try:
            _retain(root / alias, previous / alias)
            _copy_atomic(run_dir / run_name, root / alias)
        except Exception:
            results.append((alias, _ALIAS_FAILED))
        except BaseException as interrupt:
            results.append((alias, _ALIAS_FAILED))
            results.extend((name, _NOT_ATTEMPTED) for _r, name in COMPATIBILITY_FILES[index + 1 :])
            return results, interrupt
        else:
            results.append((alias, _REFRESHED))
    return results, None


def _publish(
    root: Path,
    run_dir: Path,
    progress: _Progress,
    clock: Clock,
    out: Callable[[str], None],
) -> RunResult:
    """Switch the pointer, then refresh the compatibility files; never roll the pointer back.

    A pointer that cannot be replaced raises ``publish_failed`` (nothing was published).
    """
    progress.enter(_PUBLICATION)
    manifest = progress.manifest
    pointer = root / POINTER_NAME
    previous = run_dir / PUBLICATION_DIR / PREVIOUS_DIR
    published = replace(manifest, published_at=clock())
    page = render.pointer_page(
        run_id=manifest.run_id,
        input_sha256=cast(str, manifest.input_sha256),
        as_of=manifest.as_of,
        published_at=cast(datetime, published.published_at),
        run_link=Path(os.path.relpath(run_dir, root)).as_posix(),
        manifest_name=MANIFEST_NAME,
    )
    _check_pointer(page, manifest)
    # The manifest says "published, copies pending" BEFORE the pointer names the run, so an
    # interrupt at any point after the switch never leaves a pointer that contradicts it. A
    # failure before the switch rewrites it as failed.
    progress.note(
        status=_PUBLISHED, published_at=published.published_at, alias_refresh_state=_PENDING
    )
    _attempt(_MANIFEST_FAILED, lambda: _write_manifest(run_dir, progress.manifest))
    try:
        _retain(pointer, previous / POINTER_NAME)
        reimbursement_report.write_html_atomic(pointer, page)
    except OSError:
        raise RunnerError(
            _PUBLISH_FAILED, "the current-run pointer could not be replaced"
        ) from None
    progress.published = True
    progress.enter(_COMPATIBILITY)
    out(f"  published     : {pointer}")

    results, interrupt = _refresh_copies(root, run_dir, previous)
    failures = tuple(alias for alias, status in results if status != _REFRESHED)
    codes: list[str] = []
    if any(status == _ALIAS_FAILED for _a, status in results):
        codes.append(_ALIAS_REFRESH_FAILED)
    if interrupt is not None:
        codes.append(_ALIAS_REFRESH_INTERRUPTED)
    final = replace(
        progress.manifest,
        alias_refresh=tuple(results),
        alias_refresh_state=_PARTIAL if failures else _COMPLETE,
        failure_codes=tuple(codes),
    )
    exit_code = EXIT_FAILED if failures else EXIT_OK
    failure = codes[0] if codes else None
    try:
        manifest_path = _write_manifest(run_dir, final)
    except Exception:
        out(f"end-to-end-run: {_MANIFEST_FAILED}: the published run's manifest was not updated")
        manifest_path, exit_code, failure = run_dir / MANIFEST_NAME, EXIT_FAILED, _MANIFEST_FAILED
    refreshed = sum(1 for _a, status in results if status == _REFRESHED)
    out(
        f"  compatibility : {refreshed} refreshed, {len(failures)} not refreshed "
        f"({final.alias_refresh_state} refresh)"
    )
    for alias in failures:
        out(f"    - not refreshed: {alias} (the pointer still names the new run)")
    if interrupt is not None:
        raise interrupt
    return RunResult(
        exit_code,
        run_id=manifest.run_id,
        manifest_path=manifest_path,
        index_path=pointer,
        coverage_warnings=manifest.coverage_warnings,
        alias_failures=failures,
        failure_code=failure,
    )


# --------------------------------------------------------------------------------------
# Production entry point
# --------------------------------------------------------------------------------------


def _coverage(report: ReportFacts) -> tuple[str, ...]:
    return tuple(
        flag.code if flag.source_alias is None else f"{flag.code}:{flag.source_alias}"
        for flag in report.coverage_flags
    )


def _print_facts(out: Callable[[str], None], report: ReportFacts, ledger: AdjustedLedger) -> None:
    out(
        f"  adjustments   : {len(ledger.applied)} applied, {len(ledger.pending)} pending, "
        f"{len(ledger.superseded)} superseded"
    )
    out(
        f"  findings      : {len(report.discrepancy_ids)} unresolved discrepancy(ies), "
        f"{len(report.issues)} issue(s), {len(report.coverage_flags)} coverage flag(s)"
    )


def _dry_run(options: RunOptions, config: Config, out: Callable[[str], None]) -> RunResult:
    capture_set, reconciliation = _capture(config, None)
    out(f"  captured      : {len(capture_set.captures)} source tab(s), budget and Assumptions")
    ledger = _project(capture_set, reconciliation, options.as_of)
    kwargs = _refresh_kwargs(options, config)
    planned, summary = _attempt(
        _REIMBURSEMENT_FAILED, lambda: reimbursement_pipeline.plan_bundle_refresh(**kwargs)
    )
    bundle = _attempt(_REIMBURSEMENT_FAILED, lambda: reimbursement_report._load_data(planned))
    receipts = _attempt(
        _RECEIPTS_FAILED,
        lambda: receipt_refresh.refresh_receipts(
            bundle_path=options.bundle_path,
            source=options.source,
            config=config.receipt_refresh,
            dry_run=True,
            report=bundle,
        ),
    )
    _print_refresh(out, summary, receipts)
    report = _attempt(_FACTS_FAILED, lambda: facts.build_from(capture_set, ledger, bundle, config))
    _print_facts(out, report, ledger)
    out(
        "end-to-end-run [dry-run]: inputs validated (sources, journal, evidence refresh plan "
        "and facts; staging, rendering and publication are not exercised); no run folder, "
        "lock, snapshot, token, bundle, report or Sheets cell was written"
    )
    return RunResult(EXIT_OK, coverage_warnings=_coverage(report))


def _guarded_dry_run(options: RunOptions, config: Config, out: Callable[[str], None]) -> RunResult:
    """The dry run under the same value-free failure path as a real run, writing nothing:
    a typed failure prints its code, an unexpected error only its type name, and an
    interrupt a fixed line before it is re-raised (no failed-run record is ever written)."""
    try:
        return _dry_run(options, config, out)
    except RunnerError as error:
        out(f"end-to-end-run [dry-run]: {error}; nothing was written")
        return RunResult(error.exit_code, failure_code=error.code)
    except Exception as error:
        out(
            f"end-to-end-run [dry-run]: {_UNEXPECTED_FAILURE}: {type(error).__name__}; "
            "nothing was written"
        )
        return RunResult(EXIT_FAILED, failure_code=_UNEXPECTED_FAILURE)
    except BaseException:
        out(f"end-to-end-run [dry-run]: {_INTERRUPTED}; nothing was written")
        raise


def _build_run(
    options: RunOptions,
    config: Config,
    main_reports: MainReports,
    proposals: Sequence[Adjustment],
    lock: adjustments.RunLock,
    run_dir: Path,
    progress: _Progress,
    *,
    mail_service: Any,
    exporter: render.Exporter | None,
    clock: Clock | None,
    out: Callable[[str], None],
) -> None:
    """Every stage up to a validated set and its manifest (nothing is published here)."""
    root = main_reports.output_path
    run_id = progress.manifest.run_id
    progress.enter(_CAPTURE)
    capture_set, reconciliation = _capture(config, clock)
    out(f"  captured      : {len(capture_set.captures)} source tab(s), budget and Assumptions")
    if options.mail_window is not None:
        progress.enter(_MAIL)
        _fetch_mail(options.mail_window, config, options.source, mail_service, out)
    progress.enter(_REFRESH)
    _refresh_reimbursements(options, config, progress, out)

    if proposals:
        progress.enter(_ADJUSTMENTS)
        written = _record_adjustments(
            proposals, config, capture_set, reconciliation, options, lock, clock, progress
        )
        out(
            f"  journal       : {len(written)} recorded, "
            f"{len(progress.manifest.adjustments_already_recorded)} already recorded"
        )
        if written:  # facts must read the journal as it now stands
            progress.enter(_CAPTURE)
            capture_set, reconciliation = _capture(config, clock)
    stored = _attempt(_CAPTURE_STORE_FAILED, lambda: sources.store_capture_set(capture_set, root))
    progress.note(
        capture_aggregate_sha256=capture_set.aggregate_sha256,
        capture_ref=Path(os.path.relpath(stored.path, root)).as_posix(),
        capture_hashes=tuple(sorted((c.alias, c.sha256) for c in capture_set.captures)),
        adopted_budget_sha256=capture_set.adopted_budget.sha256,
        assumptions_sha256=capture_set.assumptions.sha256,
        crosswalk_sha256=reconciliation.crosswalk_sha256,
    )
    progress.enter(_ADJUSTMENTS)
    ledger = _project(capture_set, reconciliation, options.as_of)
    progress.note(journal_sha256=ledger.journal_sha256)

    progress.enter(_STAGING)
    staged = _attempt(
        _STAGING_FAILED, lambda: _stage_bundle(options.bundle_path, run_dir / INPUTS_DIR)
    )
    progress.note(
        bundle_sha256=staged.bundle_sha256,
        sidecar_sha256=staged.sidecar_sha256,
        receipt_pages=staged.pages,
    )
    bundle = _attempt(_STAGING_FAILED, lambda: reimbursement_report.load_bundle(staged.path))
    progress.enter(_FACTS)
    report = _attempt(_FACTS_FAILED, lambda: facts.build_from(capture_set, ledger, bundle, config))
    _print_facts(out, report, ledger)
    components = _input_components(capture_set, ledger, staged, config, main_reports, options.as_of)
    input_sha = input_set_sha256(dict(components))
    progress.note(
        input_sha256=input_sha,
        input_components=components,
        applied_adjustments=report.applied_adjustments,
        coverage_warnings=_coverage(report),
    )
    records = _attempt(
        _RECORDS_FAILED,
        lambda: _write_records(run_dir, report, reconciliation, ledger, capture_set),
    )
    progress.note(records=records)

    progress.enter(_RENDER)
    context = render.RenderContext.from_capture_set(run_id, capture_set, input_sha256=input_sha)
    artifacts = _attempt(
        _RENDER_FAILED,
        lambda: render.write(report, staged.path, run_dir, context=context, exporter=exporter),
    )
    progress.enter(_VALIDATION)
    _attempt(_VALIDATION_FAILED, lambda: _check_set(run_dir, artifacts, run_id, input_sha))
    progress.note(status=_VALIDATED, artifacts=artifacts)
    _attempt(_MANIFEST_FAILED, lambda: _write_manifest(run_dir, progress.manifest))
    out(f"  run           : {run_id} ({len(artifacts.artifacts)} file(s) validated)")


def run(
    options: RunOptions,
    config: Config,
    *,
    mail_service: Any = None,
    exporter: render.Exporter | None = None,
    clock: Clock | None = None,
    out: Callable[[str], None] = print,
) -> RunResult:
    """Run the Main Report Set end to end (see the module docstring).

    Returns a :class:`RunResult` for every outcome except an interrupt
    (``KeyboardInterrupt`` or another non-``Exception``), which is recorded (never for a dry
    run, which writes nothing) and re-raised.
    Never prints exception text other than the runner's own value-free messages.
    ``mail_service`` replaces the Gmail client (tests), ``exporter`` the headless Chromium
    export (:func:`np_finance.main_reports.render.write`), ``clock`` the UTC clock used for
    the run ID, captures and publication time. ``out`` receives every console line.
    """
    try:
        main_reports, root = _validate(options, config)
        proposals = () if options.dry_run else _load_proposals(options.adjustments_file)
    except RunnerError as error:
        out(f"end-to-end-run: {error}")
        return RunResult(error.exit_code, failure_code=error.code)
    if options.dry_run:
        return _guarded_dry_run(options, config, out)

    now = clock or _utc_now
    try:
        lock = adjustments.acquire_run_lock(config, clock=now)
    except adjustments.RunBusyError as busy:
        out(f"end-to-end-run: {busy}")
        return RunResult(EXIT_FAILED, failure_code=busy.code)
    except OSError:
        out(f"end-to-end-run: {_OUTPUT_UNAVAILABLE}: the private output folder is not writable")
        return RunResult(EXIT_FAILED, failure_code=_OUTPUT_UNAVAILABLE)
    try:
        run_id = make_run_id(now())
        run_dir = main_reports.output_path / run_id
        progress = _Progress(
            RunManifest(
                run_id=run_id,
                as_of=options.as_of,
                status=_FAILED_STATUS,
                code_revision=_code_revision(),
                created_at=now(),
            )
        )
        out(f"end-to-end-run: run {run_id} as of {options.as_of.isoformat()}")
        unchanged = "the previous publication is unchanged"
        try:
            _attempt(_OUTPUT_UNAVAILABLE, run_dir.mkdir)
            _build_run(
                options,
                config,
                main_reports,
                proposals,
                lock,
                run_dir,
                progress,
                mail_service=mail_service,
                exporter=exporter,
                clock=clock,
                out=out,
            )
            return _publish(root, run_dir, progress, now, out)
        except RunnerError as error:  # raised only before the pointer switch
            _record_failure(main_reports.output_path, run_dir, progress, error.code)
            out(f"end-to-end-run: {error}; {unchanged}")
            _journal_hint(progress, out)
            return RunResult(error.exit_code, run_id=run_id, failure_code=error.code)
        except Exception as error:
            failure_type = type(error).__name__
            if progress.published or _pointer_names(root, run_id):
                out(
                    f"end-to-end-run: {_UNEXPECTED_FAILURE}: {failure_type} after publication; "
                    "the pointer names the new run"
                )
                return RunResult(EXIT_FAILED, run_id=run_id, failure_code=_UNEXPECTED_FAILURE)
            _record_failure(
                main_reports.output_path, run_dir, progress, _UNEXPECTED_FAILURE, failure_type
            )
            out(
                f"end-to-end-run: {_UNEXPECTED_FAILURE}: {failure_type} during the "
                f"{progress.stage} stage; {unchanged}"
            )
            _journal_hint(progress, out)
            return RunResult(EXIT_FAILED, run_id=run_id, failure_code=_UNEXPECTED_FAILURE)
        except BaseException as interrupt:
            if progress.published or _pointer_names(root, run_id):
                out(
                    f"end-to-end-run: {_INTERRUPTED} after publication; the pointer names the "
                    "new run and its manifest lists each compatibility copy's state"
                )
            else:
                _record_failure(
                    main_reports.output_path,
                    run_dir,
                    progress,
                    _INTERRUPTED,
                    type(interrupt).__name__,
                )
                out(
                    f"end-to-end-run: {_INTERRUPTED} during the {progress.stage} stage; {unchanged}"
                )
                _journal_hint(progress, out)
            raise
    finally:
        lock.release()
