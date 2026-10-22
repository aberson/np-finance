"""Headless Chromium PDF/PNG export of rendered Main Report Set summaries.

Each summary is a self-contained local HTML file. :func:`export_documents` opens every file
in one headless Playwright Chromium browser (the browser dependency the receipt viewer and
receipt preparation already use). JavaScript is disabled, the context is offline, and one
route handler lets through only the document being exported: every other request (``http``,
``https``, another local ``file://`` path, anything else) is aborted, so the export never
depends on the page's own Content-Security-Policy. Inline ``data:`` images are not network
requests and still render. Each document is printed to a PDF (page size from its CSS
``@page`` rule) and captured as a full-page PNG.

Every output is first written to a temporary sibling and checked (PDF and PNG signatures);
only when ALL of them succeed are they moved into place, each by an atomic replace. An export
failure raises :class:`ExportError` with a stable ``code`` and leaves every existing output
untouched.

Playwright is the optional ``reports`` extra (it is also in ``dev``); its browser must be
installed with ``uv run playwright install chromium``.
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pta_finance.reimbursement_report import PNG_SIGNATURE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Browser, BrowserContext, Route

__all__ = [
    # constants
    "EXPORT_ERROR_CODES",
    "VIEWPORT_WIDTH",
    "EXPORT_TIMEOUT_MS",
    # functions
    "default_sandbox",
    "export_documents",
    "verify_outputs",
    # types
    "ExportError",
    "ExportJob",
    "UnsandboxedExportWarning",
]

EXPORT_ERROR_CODES: tuple[str, ...] = (
    "export_unavailable",  # Playwright or its Chromium cannot be loaded or started
    "export_failed",  # the browser could not load, print or capture a document
    "export_output_invalid",  # a produced file is not a PDF/PNG
    "export_input_invalid",  # a job names a missing document or clashing outputs
)
_UNAVAILABLE, _FAILED, _OUTPUT_INVALID, _INPUT_INVALID = EXPORT_ERROR_CODES

# Desktop layout width of the PNG capture (CSS pixels).
VIEWPORT_WIDTH = 1100
# Per-operation browser timeout.
EXPORT_TIMEOUT_MS = 60_000

_PDF_SIGNATURE = b"%PDF-"
# Context network emulation; the route handler below blocks requests on its own.
_OFFLINE = True


def default_sandbox() -> bool:
    """Whether Chromium's process sandbox is used when the caller does not choose.

    It is on for the supported Windows operator host (as the receipt PDF renderer does). On
    other platforms it can need kernel features a CI runner lacks, so it is off by default
    there: the exported pages run no script and load nothing but themselves, and every
    unsandboxed export raises :class:`UnsandboxedExportWarning` and is reported to the caller.
    """
    return sys.platform == "win32"


class UnsandboxedExportWarning(UserWarning):
    """The PDF/PNG export ran without Chromium's process sandbox."""


class ExportError(Exception):
    """A summary could not be exported. Carries a stable ``code`` (:data:`EXPORT_ERROR_CODES`);
    its text names the code and a fixed reason, never document content.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ExportJob:
    """One local HTML document and the PDF and PNG files it is exported to."""

    html: Path
    pdf: Path
    png: Path


def _check_jobs(jobs: Sequence[ExportJob]) -> None:
    outputs: list[Path] = []
    for job in jobs:
        if not job.html.is_file():
            raise ExportError(_INPUT_INVALID, "an export job names a missing HTML document")
        outputs.extend((job.pdf.resolve(), job.png.resolve()))
    inputs = {job.html.resolve() for job in jobs}
    if len(set(outputs)) != len(outputs) or inputs & set(outputs):
        raise ExportError(_INPUT_INVALID, "export outputs must be distinct from each other")


def _temporary(target: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    return Path(name)


@contextmanager
def _browser(executable: Path | None, sandbox: bool) -> Iterator[Browser]:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        raise ExportError(
            _UNAVAILABLE, "Playwright is not installed (install the reports extra)"
        ) from None
    try:
        with sync_playwright() as driver:
            try:
                browser = (
                    driver.chromium.launch(
                        headless=True,
                        chromium_sandbox=sandbox,
                        executable_path=os.fspath(executable),
                    )
                    if executable is not None
                    else driver.chromium.launch(
                        headless=True, chromium_sandbox=sandbox, channel="chromium"
                    )
                )
            except Error:
                raise ExportError(_UNAVAILABLE, "headless Chromium could not be started") from None
            try:
                yield browser
            finally:
                _quietly(browser.close)
    except Error:
        raise ExportError(_FAILED, "the headless browser failed") from None


def _quietly(close: Callable[[], None]) -> None:
    """Close a browser object; a crashed browser cannot mask the outcome of the export."""
    from playwright.sync_api import Error

    try:
        close()
    except Error:
        pass


def _only(document: str) -> Callable[[Route], None]:
    """A route handler that continues ``document`` and aborts every other request."""

    def handle(route: Route) -> None:
        if route.request.url == document:
            route.continue_()
        else:
            route.abort()

    return handle


def _render(browser: Browser, job: ExportJob, pdf: Path, png: Path) -> None:
    from playwright.sync_api import Error

    document = job.html.resolve().as_uri()
    context: BrowserContext | None = None
    try:
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": 900},
            device_scale_factor=1,
            java_script_enabled=False,
            offline=_OFFLINE,
        )
        context.set_default_timeout(EXPORT_TIMEOUT_MS)
        context.route("**/*", _only(document))
        page = context.new_page()
        page.goto(document, wait_until="load")
        page.pdf(path=os.fspath(pdf), print_background=True, prefer_css_page_size=True)
        page.screenshot(path=os.fspath(png), type="png", full_page=True)
    except Error:
        raise ExportError(_FAILED, "a summary could not be printed or captured") from None
    finally:
        if context is not None:
            _quietly(context.close)


def _check_output(path: Path, signature: bytes) -> None:
    try:
        with path.open("rb") as handle:
            head = handle.read(len(signature))
    except OSError:
        raise ExportError(_OUTPUT_INVALID, "an exported file is missing or unreadable") from None
    if head != signature:
        raise ExportError(_OUTPUT_INVALID, "an exported file is not the expected format")


def verify_outputs(jobs: Sequence[ExportJob]) -> None:
    """Every job's PDF and PNG exists and carries its signature, whoever exported it.

    The same checks :func:`export_documents` applies to its own output; raises
    :class:`ExportError` (``export_output_invalid``).
    """
    for job in jobs:
        _check_output(job.pdf, _PDF_SIGNATURE)
        _check_output(job.png, PNG_SIGNATURE)


def export_documents(
    jobs: Sequence[ExportJob],
    *,
    executable: Path | None = None,
    sandbox: bool | None = None,
) -> bool:
    """Export every job's HTML to its PDF and PNG; returns whether the sandbox was used.

    ``executable`` optionally names a Chromium binary (otherwise Playwright's Chromium).
    ``sandbox`` chooses Chromium's process sandbox (default :func:`default_sandbox`); an
    unsandboxed export also raises :class:`UnsandboxedExportWarning`.
    Nothing is moved into place until every document has been exported and checked; each
    output is then replaced atomically. Raises :class:`ExportError`: a failure before that
    point changes no existing output, and every temporary file is always removed. (A
    filesystem error while moving the checked files into place can leave earlier outputs of
    the same call replaced; each file is still either its old or its new complete version.)
    """
    _check_jobs(jobs)
    sandboxed = default_sandbox() if sandbox is None else sandbox
    staged: list[tuple[Path, Path]] = []
    try:
        for job in jobs:
            for target in (job.pdf, job.png):
                target.parent.mkdir(parents=True, exist_ok=True)
                staged.append((_temporary(target), target))
        with _browser(executable, sandboxed) as browser:
            for index, job in enumerate(jobs):
                pdf_temp, png_temp = staged[2 * index][0], staged[2 * index + 1][0]
                _render(browser, job, pdf_temp, png_temp)
                _check_output(pdf_temp, _PDF_SIGNATURE)
                _check_output(png_temp, PNG_SIGNATURE)
        for temp, target in staged:
            os.replace(temp, target)
    except OSError:
        raise ExportError(_FAILED, "an export file could not be written") from None
    finally:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)
    if not sandboxed:
        warnings.warn(
            "the PDF/PNG export ran without Chromium's process sandbox",
            UnsandboxedExportWarning,
            stacklevel=2,
        )
    return sandboxed
