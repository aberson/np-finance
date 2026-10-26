from __future__ import annotations

import hashlib
import json
import subprocess
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from np_finance import receipt_assets, receipt_refresh
from np_finance.config import ReceiptRefresh
from np_finance.receipt_pages import PageImage


def _message(message_id: str) -> EmailMessage:
    message = EmailMessage()
    message["Message-ID"] = message_id
    return message


def test_review_key_uses_the_raw_stripped_message_id() -> None:
    raw = "<Mixed.Case@Example.ORG>"
    expected = "submission:v1:" + hashlib.sha256(raw.encode()).hexdigest()
    assert receipt_refresh._review_key(_message(f"  {raw}  ")) == expected
    lowered = "submission:v1:" + hashlib.sha256(raw.casefold().encode()).hexdigest()
    assert expected != lowered


def test_two_page_pdf_keeps_generated_ids_but_reports_true_page_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-fictional")
    asset = receipt_assets.AssetResult(
        "https://uploads.example.org/fictional.pdf",
        "fictional-key",
        receipt_assets.ASSET_ID.prefix + hashlib.sha256(source.read_bytes()).hexdigest(),
        "pdf",
        source,
        source.stat().st_size,
        "cached",
        "",
    )

    def render(command: list[str], **_options: Any) -> subprocess.CompletedProcess[bytes]:
        rendered = Path(command[4])
        rendered.mkdir()
        (rendered / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\nfirst")
        (rendered / "page-2.png").write_bytes(b"\x89PNG\r\n\x1a\nsecond")
        return subprocess.CompletedProcess(
            command, 0, b'{"pages":["page-1.png","page-2.png"]}', b""
        )

    ordinals: list[int] = []

    def normalize(
        rendered_asset: receipt_assets.AssetResult,
        *,
        pages_dir: Path,
        ticket_ref: str,
        asset_ordinal: int,
    ) -> list[PageImage]:
        ordinals.append(asset_ordinal)
        return [
            PageImage(
                f"{ticket_ref}-a{asset_ordinal}-p1",
                rendered_asset.asset_id or "",
                1,
                pages_dir / f"{ticket_ref}-a{asset_ordinal}-p1.jpg",
                "a" * 64,
                f"generated upload {asset_ordinal}",
                100,
                200,
                1.0,
            )
        ]

    monkeypatch.setattr(receipt_refresh.subprocess, "run", render)
    monkeypatch.setattr(receipt_refresh.receipt_pages, "to_pages", normalize)
    config = ReceiptRefresh(("uploads.example.org",), tmp_path / "cache", tmp_path / "pages")
    pages = receipt_refresh._pdf_pages(asset, config=config, ticket_ref="NEW-01", asset_ordinal=1)
    assert ordinals == [101, 102]
    assert [page.page_id for page in pages] == ["NEW-01-a101-p1", "NEW-01-a102-p1"]
    assert [page.asset_page for page in pages] == [1, 2]
    assert [page.label for page in pages] == [
        "NEW-01 · upload 1 · page 1",
        "NEW-01 · upload 1 · page 2",
    ]


def test_ocr_match_requires_unique_amount_and_meaningful_description() -> None:
    item = SimpleNamespace(
        effective_item="Fictional classroom markers", effective_amount=Decimal("12.34")
    )
    match = receipt_refresh._OcrLine("Classroom markers $12.34", (0.1, 0.2, 0.3, 0.04))
    amount_only = receipt_refresh._OcrLine("TOTAL $12.34", (0.1, 0.8, 0.3, 0.04))
    assert receipt_refresh._suggest_box(item, [match, amount_only]) == [0.1, 0.2, 0.3, 0.04]
    assert receipt_refresh._suggest_box(item, [amount_only]) is None
    assert receipt_refresh._suggest_box(item, [match, match]) is None
    book = SimpleNamespace(effective_item="Book", effective_amount=Decimal("12.34"))
    assert (
        receipt_refresh._suggest_box(
            book,
            [receipt_refresh._OcrLine("Notebook $12.34", (0.1, 0.2, 0.3, 0.04))],
        )
        is None
    )
    assert (
        receipt_refresh._suggest_box(
            item,
            [receipt_refresh._OcrLine("Classroom markers -$12.34", (0.1, 0.2, 0.3, 0.04))],
        )
        is None
    )


def _report(review_key: str) -> Any:
    old = SimpleNamespace(
        item_key="old-item",
        effective_item="Previously verified item",
        effective_amount=Decimal("1.00"),
    )
    new = SimpleNamespace(
        item_key="new-item",
        effective_item="Fictional classroom markers",
        effective_amount=Decimal("12.34"),
    )
    new_two = SimpleNamespace(
        item_key="new-item-2",
        effective_item="Fictional glue sticks",
        effective_amount=Decimal("8.00"),
    )
    ticket = SimpleNamespace(review_key=review_key, ref="NEW-01", items=(old, new, new_two))
    return SimpleNamespace(tickets=(ticket,))


def _mail(path: Path, message_id: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Example Reimbursement Form got a new submission"
    message["From"] = "forms@example.org"
    message["To"] = "treasurer@example.org"
    message["Date"] = "Wed, 21 Oct 2026 09:00:00 -0700"
    message["Message-ID"] = message_id
    message.set_content(
        """Example Reimbursement Form got a new submission
Requestor First and Last Name:
Fictional Person
1. Date:
2026-10-20
1. Event or Budget Category:
Classroom Supplies
1. Description:
Fictional classroom markers
1. Amount:
12.34
Total Amount $:
12.34
Choose Payment Type:
Check
PDF:
https://uploads.example.org/fake.png
"""
    )
    path.write_bytes(message.as_bytes())


def test_refresh_wires_mail_asset_page_and_preserves_human_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_id = "<Fictional.Raw@Id.Example>"
    review_key = "submission:v1:" + hashlib.sha256(message_id.encode()).hexdigest()
    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}", encoding="utf-8")
    source = tmp_path / "mail"
    source.mkdir()
    _mail(source / "one.eml", message_id)
    pages = tmp_path / "pages"
    pages.mkdir()
    page_path = pages / "NEW-01-a1-p1.jpg"
    page_path.write_bytes(b"\xff\xd8\xfffictional")
    sidecar = bundle.with_suffix(".receipts.json")
    human = {
        "review_key": review_key,
        "item_key": "old-item",
        "item_sha256": "human-fingerprint",
        "regions": [{"page_id": "human-page", "box": [0.1, 0.1, 0.2, 0.1]}],
    }
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pages": [
                    {
                        "id": "human-page",
                        "path": "human.jpg",
                        "sha256": "human-digest",
                        "label": "Human verified",
                    }
                ],
                "items": [human],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(receipt_refresh, "load_bundle", lambda _path: _report(review_key))
    validations: list[Path] = []
    monkeypatch.setattr(
        receipt_refresh.receipt_viewer,
        "load_receipts",
        lambda path, _report: validations.append(path) or {},
    )
    monkeypatch.setattr(receipt_refresh.receipt_viewer, "headroom_bytes", lambda _path: 100_000)
    monkeypatch.setattr(
        receipt_refresh.receipt_viewer, "item_fingerprint", lambda *_args: "new-fingerprint"
    )
    asset = receipt_assets.AssetResult(
        "https://uploads.example.org/fake.png",
        "key",
        "asset:v1:" + "a" * 64,
        "png",
        tmp_path / "cache.png",
        10,
        "cached",
        "",
    )
    monkeypatch.setattr(receipt_refresh.receipt_assets, "fetch_assets", lambda *_a, **_kw: [asset])
    page = PageImage(
        "NEW-01-a1-p1",
        asset.asset_id or "",
        1,
        page_path,
        hashlib.sha256(page_path.read_bytes()).hexdigest(),
        "Fictional upload",
        1000,
        1000,
        1.0,
    )
    monkeypatch.setattr(receipt_refresh.receipt_pages, "to_pages", lambda *_a, **_kw: [page])
    ocr_calls: list[str] = []

    def ocr_once(
        current_page: PageImage, _executable: Path | None
    ) -> tuple[receipt_refresh._OcrLine, ...]:
        ocr_calls.append(current_page.page_id)
        return (
            receipt_refresh._OcrLine("Fictional classroom markers $12.34", (0.1, 0.2, 0.4, 0.04)),
        )

    monkeypatch.setattr(receipt_refresh, "_ocr", ocr_once)
    config = ReceiptRefresh(("uploads.example.org",), tmp_path / "cache", pages)
    summary = receipt_refresh.refresh_receipts(bundle_path=bundle, source=source, config=config)
    written = json.loads(sidecar.read_text(encoding="utf-8"))
    assert written["items"][0] == human
    assert written["items"][1]["match_method"] == "automatic-ocr-v1"
    assert written["items"][1]["regions"][0]["box"] == [0.1, 0.2, 0.4, 0.04]
    assert summary.marked == 1 and summary.review_needed == 1
    assert ocr_calls == [page.page_id]
    assert len(validations) == 2


def test_configured_dry_run_never_fetches_decodes_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "submission:v1:" + "a" * 64
    bundle = tmp_path / "bundle.json"
    bundle.write_text("before", encoding="utf-8")
    monkeypatch.setattr(receipt_refresh, "load_bundle", lambda _path: _report(key))
    monkeypatch.setattr(receipt_refresh.receipt_viewer, "load_receipts", lambda *_a: {})
    monkeypatch.setattr(
        receipt_refresh,
        "_submission_urls",
        lambda *_a: ({key: ("https://uploads.example.org/x.png",)}, set()),
    )
    monkeypatch.setattr(
        receipt_refresh.receipt_assets,
        "fetch_assets",
        lambda *_a, **_kw: pytest.fail("dry run fetched an asset"),
    )
    config = ReceiptRefresh(("uploads.example.org",), tmp_path / "cache", tmp_path / "pages")
    summary = receipt_refresh.refresh_receipts(
        bundle_path=bundle, source=tmp_path / "mail", config=config, dry_run=True
    )
    assert summary.review_needed == 3
    assert bundle.read_text(encoding="utf-8") == "before"
    assert not bundle.with_suffix(".receipts.json").exists()


def test_page_budget_refusal_is_persisted_and_fails_when_nothing_attaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "submission:v1:" + "b" * 64
    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(receipt_refresh, "load_bundle", lambda _path: _report(key))
    monkeypatch.setattr(receipt_refresh.receipt_viewer, "headroom_bytes", lambda _path: 0)
    monkeypatch.setattr(
        receipt_refresh,
        "_submission_urls",
        lambda *_a: ({key: ("https://uploads.example.org/x.png",)}, set()),
    )
    cached = tmp_path / "cached.png"
    cached.write_bytes(b"cached")
    asset = receipt_assets.AssetResult(
        "https://uploads.example.org/x.png",
        "key",
        receipt_assets.ASSET_ID.prefix + "c" * 64,
        "png",
        cached,
        6,
        "cached",
        "",
    )
    monkeypatch.setattr(receipt_refresh.receipt_assets, "fetch_assets", lambda *_a, **_kw: [asset])
    page_path = tmp_path / "page.jpg"
    page_path.write_bytes(b"page")
    page = PageImage(
        "NEW-01-a1-p1", asset.asset_id or "", 1, page_path, "d" * 64, "Page", 10, 10, 1.0
    )
    monkeypatch.setattr(receipt_refresh.receipt_pages, "to_pages", lambda *_a, **_kw: [page])
    config = ReceiptRefresh(("uploads.example.org",), tmp_path / "cache", tmp_path)
    with pytest.raises(receipt_refresh.ReceiptRefreshError, match="no unlinked receipt item"):
        receipt_refresh.refresh_receipts(bundle_path=bundle, source=tmp_path, config=config)
    review = json.loads(bundle.with_suffix(".receipts.review.json").read_text("utf-8"))
    assert review["review_needed"] == 3
    assert any("100 MiB page budget exhausted" in detail for detail in review["details"])
    assert not bundle.with_suffix(".receipts.json").exists()


def test_stale_existing_sidecar_fails_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "submission:v1:" + "d" * 64
    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}", encoding="utf-8")
    bundle.with_suffix(".receipts.json").write_text(
        json.dumps({"schema_version": 1, "pages": [], "items": []}), encoding="utf-8"
    )
    monkeypatch.setattr(receipt_refresh, "load_bundle", lambda _path: _report(key))
    monkeypatch.setattr(
        receipt_refresh.receipt_viewer,
        "load_receipts",
        lambda *_a: (_ for _ in ()).throw(
            receipt_refresh.receipt_viewer.ReceiptViewerError("stale")
        ),
    )
    monkeypatch.setattr(
        receipt_refresh.receipt_assets,
        "fetch_assets",
        lambda *_a, **_kw: pytest.fail("stale sidecar reached fetch"),
    )
    config = ReceiptRefresh(("uploads.example.org",), tmp_path / "cache", tmp_path)
    with pytest.raises(receipt_refresh.ReceiptRefreshError, match="stale or invalid"):
        receipt_refresh.refresh_receipts(bundle_path=bundle, source=tmp_path, config=config)
