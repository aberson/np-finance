"""Prepare future receipt pages and conservative automatic OCR suggestions.

This stage runs only from ``update-reimbursements`` when ``[receipt_refresh]`` is configured.
It is evidence preparation, never adjudication: automatic locations remain visibly labelled
suggestions, while every pre-existing (human-prepared) sidecar entry is preserved byte-for-byte
at the JSON object level.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import Any

from np_finance import receipt_assets, receipt_ingest, receipt_pages, receipt_viewer
from np_finance.config import ReceiptRefresh
from np_finance.receipt_geometry import NORMALIZATION
from np_finance.reimbursement_report import (
    ReimbursementReport,
    ReimbursementReportError,
    ReviewItem,
    Ticket,
    load_bundle,
)

__all__ = ["ReceiptRefreshError", "RefreshSummary", "refresh_receipts"]

_STOP_WORDS = frozenset(
    {
        "and",
        "expense",
        "for",
        "from",
        "item",
        "items",
        "misc",
        "other",
        "purchase",
        "receipt",
        "reimbursement",
        "supplies",
        "the",
    }
)
_TOKEN = re.compile(r"[a-z0-9]+")
_OCR_CAP = 2 * 1024 * 1024


class ReceiptRefreshError(ValueError):
    """Receipt preparation could not safely produce a valid candidate sidecar."""


@dataclass(frozen=True)
class RefreshSummary:
    configured: bool
    unlinked: int
    linked: int
    marked: int
    review_needed: int
    refused_assets: int
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class _OcrLine:
    text: str
    box: tuple[float, float, float, float]


def _pdf_pages(
    asset: receipt_assets.AssetResult,
    *,
    config: ReceiptRefresh,
    ticket_ref: str,
    asset_ordinal: int,
) -> list[receipt_pages.PageImage]:
    """Render a PDF in a bounded Chromium child, then normalize each PNG in the decode child."""

    if asset.path is None:
        return []
    with tempfile.TemporaryDirectory(prefix="pta-receipt-pdf-") as work:
        rendered = Path(work) / "rendered"
        command = [
            os.fspath(sys.executable),
            "-m",
            "np_finance.receipt_pdf_render",
            os.fspath(asset.path),
            os.fspath(rendered),
        ]
        if config.chromium_path is not None:
            if not config.chromium_path.is_file():
                raise ReceiptRefreshError("configured Chromium executable does not exist")
            command.append(os.fspath(config.chromium_path))
        creationflags = 0x08000000 if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReceiptRefreshError(
                "PDF receipt renderer did not complete within its limits"
            ) from exc
        if completed.returncode != 0 or len(completed.stdout) > 4096:
            raise ReceiptRefreshError(
                f"PDF receipt renderer refused the asset (code {completed.returncode})"
            )
        try:
            names = json.loads(completed.stdout)["pages"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ReceiptRefreshError("PDF receipt renderer returned an invalid manifest") from exc
        if not isinstance(names, list) or not 1 <= len(names) <= 12:
            raise ReceiptRefreshError("PDF receipt renderer returned an invalid page count")
        pages: list[receipt_pages.PageImage] = []
        for page_number, name in enumerate(names, 1):
            if name != f"page-{page_number}.png":
                raise ReceiptRefreshError("PDF receipt renderer returned an unsafe page name")
            path = rendered / name
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise ReceiptRefreshError("PDF receipt renderer omitted a page") from exc
            if len(data) > NORMALIZATION.max_source_bytes or not data.startswith(
                b"\x89PNG\r\n\x1a\n"
            ):
                raise ReceiptRefreshError("PDF receipt renderer returned an invalid page")
            rendered_asset = receipt_assets.AssetResult(
                url=asset.url,
                canonical_key=asset.canonical_key,
                asset_id=receipt_assets.ASSET_ID.prefix + hashlib.sha256(data).hexdigest(),
                media_type="png",
                path=path,
                byte_count=len(data),
                outcome="cached",
                detail="",
            )
            normalized = receipt_pages.to_pages(
                rendered_asset,
                pages_dir=config.pages_path,
                ticket_ref=ticket_ref,
                asset_ordinal=asset_ordinal * 100 + page_number,
            )
            if len(normalized) != 1:
                raise ReceiptRefreshError("PDF receipt page normalization returned extra pages")
            pages.append(
                replace(
                    normalized[0],
                    asset_page=page_number,
                    label=f"{ticket_ref} · upload {asset_ordinal} · page {page_number}",
                )
            )
        return pages


def _review_key(message: Message) -> str | None:
    # This deliberately mirrors reimbursement_pipeline._review_key: its input is the RAW,
    # stripped Message-ID.  normalize_message_id() has different semantics and must not be used.
    message_id = str(message.get("Message-ID", "")).strip()
    if not message_id:
        return None
    return "submission:v1:" + hashlib.sha256(message_id.encode("utf-8")).hexdigest()


def _submission_urls(source: Path, wanted: set[str]) -> tuple[dict[str, tuple[str, ...]], set[str]]:
    found: dict[str, tuple[str, ...]] = {}
    ambiguous: set[str] = set()
    for _label, message in receipt_ingest.iter_source(source):
        key = _review_key(message)
        if key not in wanted:
            continue
        submission = receipt_ingest.parse_submission(message)
        if submission is None:
            continue
        urls = tuple(submission.receipt_urls)
        if key in found and found[key] != urls:
            ambiguous.add(key)
        else:
            found[key] = urls
    return found, ambiguous


def _read_sidecar(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "pages": [], "items": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReceiptRefreshError("existing receipt sidecar is unreadable") from exc
    if not isinstance(value, dict):
        raise ReceiptRefreshError("existing receipt sidecar is invalid")
    return value


def _meaningful_tokens(text: str) -> set[str]:
    return {
        word
        for word in _TOKEN.findall(text.casefold())
        if len(word) >= 4 and word not in _STOP_WORDS
    }


def _amount_forms(amount: Decimal | None) -> set[str]:
    if amount is None:
        return set()
    plain = f"{amount:.2f}"
    grouped = f"{amount:,.2f}"
    return {plain, grouped}


def _suggest_box(item: ReviewItem, lines: Sequence[_OcrLine]) -> list[float] | None:
    """Return a box only for one line carrying amount and meaningful description evidence."""

    tokens = _meaningful_tokens(item.effective_item)
    amounts = _amount_forms(item.effective_amount)
    if not tokens or not amounts:
        return None
    candidates = []
    for line in lines:
        line_tokens = set(_TOKEN.findall(line.text.casefold()))
        has_amount = any(
            re.search(rf"(?<![0-9.($\-])\$?{re.escape(amount)}(?![0-9.])", line.text) is not None
            for amount in amounts
        )
        needed = 1 if len(tokens) == 1 else 2
        if has_amount and len(tokens.intersection(line_tokens)) >= needed:
            candidates.append(line)
    if len(candidates) != 1:
        return None
    return list(candidates[0].box)


def _ocr(page: receipt_pages.PageImage, executable: Path | None) -> tuple[_OcrLine, ...]:
    if executable is None:
        return ()
    if not executable.is_file():
        raise ReceiptRefreshError("configured Tesseract executable does not exist")
    with tempfile.TemporaryDirectory(prefix="pta-receipt-ocr-") as work:
        output = Path(work) / "page"
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        creationflags = 0x08000000 if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                [str(executable), str(page.path), str(output), "--psm", "3", "tsv"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
                check=False,
                env=env,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReceiptRefreshError("receipt OCR did not complete within its limits") from exc
        tsv = output.with_suffix(".tsv")
        if completed.returncode != 0 or not tsv.is_file() or tsv.stat().st_size > _OCR_CAP:
            raise ReceiptRefreshError("receipt OCR returned no bounded TSV result")
        payload = tsv.read_bytes()
    try:
        rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8")), delimiter="\t"))
    except (UnicodeError, csv.Error) as exc:
        raise ReceiptRefreshError("receipt OCR returned invalid TSV") from exc
    grouped: dict[tuple[str, str, str], list[Mapping[str, str]]] = {}
    for row in rows:
        if row.get("level") == "5" and (row.get("text") or "").strip():
            grouped.setdefault(
                (row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", "")), []
            ).append(row)
    result: list[_OcrLine] = []
    for words in grouped.values():
        try:
            left = min(int(row["left"]) for row in words)
            top = min(int(row["top"]) for row in words)
            right = max(int(row["left"]) + int(row["width"]) for row in words)
            bottom = max(int(row["top"]) + int(row["height"]) for row in words)
        except (KeyError, ValueError):
            continue
        if 0 <= left < right <= page.width and 0 <= top < bottom <= page.height:
            result.append(
                _OcrLine(
                    " ".join(row["text"] for row in words),
                    (
                        left / page.width,
                        top / page.height,
                        (right - left) / page.width,
                        (bottom - top) / page.height,
                    ),
                )
            )
    return tuple(result)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _page_row(page: receipt_pages.PageImage, sidecar: Path) -> dict[str, str]:
    root = sidecar.resolve().parent
    resolved = page.path.resolve()
    if not resolved.is_relative_to(root):
        raise ReceiptRefreshError("receipt_refresh.pages_dir must be inside the bundle directory")
    return {
        "id": page.page_id,
        "path": resolved.relative_to(root).as_posix(),
        "sha256": page.sha256,
        "label": page.label,
    }


def _item_entry(
    ticket: Ticket,
    item: ReviewItem,
    pages: Sequence[receipt_pages.PageImage],
    boxes: Mapping[str, list[float] | None],
) -> dict[str, Any]:
    marked = [page for page in pages if boxes.get(page.page_id) is not None]
    selected = marked if len(marked) == 1 else list(pages)
    return {
        "review_key": ticket.review_key,
        "item_key": item.item_key,
        "item_sha256": receipt_viewer.item_fingerprint(ticket, item),
        "regions": [
            {"page_id": page.page_id, "box": boxes.get(page.page_id) if len(marked) == 1 else None}
            for page in selected
        ],
        "match_method": "automatic-ocr-v1" if len(marked) == 1 else "automatic-ticket-source-v1",
    }


def refresh_receipts(
    *,
    bundle_path: Path,
    source: Path,
    config: ReceiptRefresh | None,
    dry_run: bool = False,
    report: ReimbursementReport | None = None,
) -> RefreshSummary:
    """Prepare unlinked items, preserving all existing verified sidecar entries."""

    if config is None:
        # The absent block is the opt-in boundary: do not even inspect private receipt state.
        return RefreshSummary(False, 0, 0, 0, 0, 0)
    if report is None:
        try:
            report = load_bundle(bundle_path)
        except ReimbursementReportError as exc:
            raise ReceiptRefreshError(str(exc)) from exc
    sidecar = bundle_path.with_suffix(".receipts.json")
    existing = _read_sidecar(sidecar)
    # Validate before using its keys or budget.  An absent sidecar is valid by construction.
    if sidecar.exists():
        try:
            receipt_viewer.load_receipts(sidecar, report)
        except receipt_viewer.ReceiptViewerError as exc:
            raise ReceiptRefreshError(
                f"existing receipt sidecar is stale or invalid: {exc}"
            ) from exc
    linked_keys = {(row["review_key"], row["item_key"]) for row in existing["items"]}
    existing_marked = sum(
        row.get("match_method") == "automatic-ocr-v1" for row in existing["items"]
    )
    existing_review_needed = sum(
        row.get("match_method") == "automatic-ticket-source-v1" for row in existing["items"]
    )
    missing = [
        (ticket, item)
        for ticket in report.tickets
        for item in ticket.items
        if (ticket.review_key, item.item_key) not in linked_keys
    ]
    urls, ambiguous = _submission_urls(source, {ticket.review_key for ticket, _item in missing})
    details: list[str] = []
    joinable: dict[str, tuple[str, ...]] = {}
    for ticket, _item in missing:
        if ticket.review_key in ambiguous:
            details.append(f"{ticket.ref}: source Message-ID is ambiguous")
        elif ticket.review_key not in urls:
            details.append(f"{ticket.ref}: original source email not found")
        elif not urls[ticket.review_key]:
            details.append(f"{ticket.ref}: original submission has no receipt URLs")
        else:
            joinable[ticket.review_key] = urls[ticket.review_key]
    if dry_run:
        return RefreshSummary(
            True,
            len(missing),
            len(linked_keys),
            existing_marked,
            existing_review_needed + len(missing),
            0,
            tuple(dict.fromkeys(details)),
        )

    try:
        remaining = receipt_viewer.headroom_bytes(sidecar)
    except receipt_viewer.ReceiptViewerError as exc:
        raise ReceiptRefreshError(str(exc)) from exc
    new_pages: list[dict[str, str]] = []
    new_items: list[dict[str, Any]] = []
    refused = 0
    marked = existing_marked
    review_needed = existing_review_needed
    pages_by_ticket: dict[str, list[receipt_pages.PageImage]] = {}
    existing_pages = {row["id"]: row for row in existing["pages"]}
    new_pages_by_id: dict[str, dict[str, str]] = {}
    for ticket in report.tickets:
        ticket_urls = joinable.get(ticket.review_key)
        if not ticket_urls:
            continue
        try:
            assets = receipt_assets.fetch_assets(
                ticket_urls,
                allowlist=config.allowlist,
                cache_dir=config.cache_path,
                max_bytes=NORMALIZATION.max_source_bytes,
                timeout=60,
                max_redirects=receipt_assets.FETCH_CEILINGS.max_redirects,
                max_parallel=receipt_assets.FETCH_CEILINGS.max_parallel,
                max_attempts=receipt_assets.FETCH_CEILINGS.max_attempts,
            )
        except receipt_assets.ReceiptAssetError as exc:
            raise ReceiptRefreshError(str(exc)) from exc
        pages: list[receipt_pages.PageImage] = []
        ticket_page_ids: set[str] = set()
        for ordinal, asset in enumerate(assets, 1):
            if asset.outcome not in receipt_assets.ACCEPTED_OUTCOMES:
                refused += 1
                details.append(f"{ticket.ref} upload {ordinal}: {asset.outcome} ({asset.detail})")
                continue
            try:
                produced = (
                    _pdf_pages(
                        asset,
                        config=config,
                        ticket_ref=ticket.ref,
                        asset_ordinal=ordinal,
                    )
                    if asset.media_type == "pdf"
                    else receipt_pages.to_pages(
                        asset,
                        pages_dir=config.pages_path,
                        ticket_ref=ticket.ref,
                        asset_ordinal=ordinal,
                    )
                )
            except receipt_pages.ReceiptDecodeUnavailableError as exc:
                raise ReceiptRefreshError(str(exc)) from exc
            except (receipt_pages.ReceiptPageError, ReceiptRefreshError) as exc:
                refused += 1
                reason = exc.reason if isinstance(exc, receipt_pages.ReceiptPageError) else str(exc)
                details.append(f"{ticket.ref} upload {ordinal}: {reason}")
                continue
            for page in produced:
                if page.page_id in ticket_page_ids:
                    continue
                ticket_page_ids.add(page.page_id)
                prior_page = existing_pages.get(page.page_id)
                if prior_page is not None:
                    if prior_page["sha256"] == page.sha256:
                        pages.append(page)
                    else:
                        refused += 1
                        details.append(
                            f"{ticket.ref} upload {ordinal}: existing page id has new content"
                        )
                    continue
                prior_new = new_pages_by_id.get(page.page_id)
                if prior_new is not None:
                    if prior_new["sha256"] == page.sha256:
                        pages.append(page)
                    else:
                        refused += 1
                        details.append(
                            f"{ticket.ref} upload {ordinal}: generated page id has new content"
                        )
                    continue
                size = page.path.stat().st_size
                if size > remaining:
                    refused += 1
                    details.append(
                        f"{ticket.ref} upload {ordinal}: report 100 MiB page budget exhausted"
                    )
                    continue
                remaining -= size
                row = _page_row(page, sidecar)
                new_pages.append(row)
                new_pages_by_id[page.page_id] = row
                pages.append(page)
        pages_by_ticket[ticket.review_key] = pages

    ocr_by_page: dict[str, tuple[_OcrLine, ...] | ReceiptRefreshError] = {}
    for ticket, item in missing:
        pages = pages_by_ticket.get(ticket.review_key, [])
        if not pages:
            review_needed += 1
            continue
        boxes: dict[str, list[float] | None] = {}
        for page in pages:
            if page.page_id not in ocr_by_page:
                try:
                    ocr_by_page[page.page_id] = _ocr(page, config.tesseract_path)
                except ReceiptRefreshError as exc:
                    ocr_by_page[page.page_id] = exc
            ocr_result = ocr_by_page[page.page_id]
            if isinstance(ocr_result, ReceiptRefreshError):
                boxes[page.page_id] = None
                details.append(f"{ticket.ref}: {ocr_result}")
            else:
                boxes[page.page_id] = _suggest_box(item, ocr_result)
        entry = _item_entry(ticket, item, pages, boxes)
        if entry["match_method"] == "automatic-ocr-v1":
            marked += 1
        else:
            review_needed += 1
        new_items.append(entry)

    automatic_regions: dict[tuple[str, tuple[float, ...]], list[dict[str, Any]]] = {}
    for entry in new_items:
        if entry["match_method"] != "automatic-ocr-v1":
            continue
        region = entry["regions"][0]
        automatic_regions.setdefault((region["page_id"], tuple(region["box"])), []).append(entry)
    for duplicates in automatic_regions.values():
        if len(duplicates) < 2:
            continue
        for entry in duplicates:
            pages = pages_by_ticket[entry["review_key"]]
            entry["regions"] = [{"page_id": page.page_id, "box": None} for page in pages]
            entry["match_method"] = "automatic-ticket-source-v1"
            marked -= 1
            review_needed += 1

    proposals = {
        "schema_version": 1,
        "notice": "Automatic receipt suggestions require human review; they are not verification.",
        "review_needed": review_needed,
        "details": list(dict.fromkeys(details)),
    }
    _atomic_json(sidecar.with_suffix(".review.json"), proposals)
    if joinable and not new_items:
        raise ReceiptRefreshError(
            "no unlinked receipt item could be attached; review the saved refusal summary"
        )
    referenced_pages = {region["page_id"] for entry in new_items for region in entry["regions"]}
    candidate = {
        "schema_version": 1,
        "pages": [
            *existing["pages"],
            *(page for page in new_pages if page["id"] in referenced_pages),
        ],
        "items": [*existing["items"], *new_items],
    }
    if candidate == existing:
        return RefreshSummary(
            True,
            len(missing),
            len(linked_keys),
            marked,
            review_needed,
            refused,
            tuple(dict.fromkeys(details)),
        )
    # Validate the full candidate through the production loader before publication.
    fd, name = tempfile.mkstemp(prefix=f".{sidecar.name}.", suffix=".candidate", dir=sidecar.parent)
    os.close(fd)
    candidate_path = Path(name)
    try:
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        receipt_viewer.load_receipts(candidate_path, report)
    except (OSError, receipt_viewer.ReceiptViewerError) as exc:
        raise ReceiptRefreshError(f"candidate receipt sidecar failed validation: {exc}") from exc
    finally:
        candidate_path.unlink(missing_ok=True)
    _atomic_json(sidecar, candidate)
    return RefreshSummary(
        True,
        len(missing),
        len(linked_keys) + len(new_items),
        marked,
        review_needed,
        refused,
        tuple(dict.fromkeys(details)),
    )
