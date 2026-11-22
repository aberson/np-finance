"""Fictional local archive coverage for the private action proposal stage."""

from __future__ import annotations

import json
import mailbox
from email import message_from_bytes, policy
from pathlib import Path

import pytest

from pta_finance import cli, mail_actions, receipt_ingest

FIXTURES = Path(__file__).parent / "fixtures" / "mail_actions"


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    for name in (
        "purchase",
        "purchase_reply",
        "budget",
        "estimate",
        "unrelated",
        "reimbursement",
        "acknowledgment",
    ):
        (archive / f"{name}.eml").write_bytes((FIXTURES / f"{name}.txt").read_bytes())
    box = mailbox.mbox(str(archive / "duplicates.mbox"))
    box.add(message_from_bytes((FIXTURES / "purchase.txt").read_bytes(), policy=policy.default))
    box.flush()
    box.close()
    return archive


def _run(archive: Path, data: Path, *extra: str) -> int:
    return cli.main(["update-actions", "--source", str(archive), "--data", str(data), *extra])


def test_cli_mixed_archive_repeated_refresh_and_private_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = _archive(tmp_path)
    data = tmp_path / "reports" / "output" / "mail-actions.json"
    assert _run(archive, data) == 0
    first_output = capsys.readouterr().out
    assert "3 new" in first_output
    assert "3 proposed" in first_output
    assert "3 uncategorized" in first_output
    for private_value in (
        "volunteer@example.test",
        "wish-list",
        "fictional-estimate.xlsx",
        "purchase-1@example.test",
    ):
        assert private_value not in first_output
    inventory = mail_actions.load_inventory(data)
    assert inventory is not None
    assert {item["proposed_type"] for item in inventory["actions"]} == {
        "PURCHASE_APPROVAL",
        "BUDGET_FOLLOWUP",
        "PLANNING_ESTIMATE",
    }
    assert len(inventory["sources"]) == 7
    purchase = next(
        item for item in inventory["actions"] if item["proposed_type"] == "PURCHASE_APPROVAL"
    )
    assert len(purchase["source_keys"]) == 2
    duplicate = next(
        item for item in inventory["sources"] if item["message_id"] == "<purchase-1@example.test>"
    )
    assert len(duplicate["source_labels"]) == 2
    estimate = next(
        item for item in inventory["sources"] if item["message_id"] == "<estimate-1@example.test>"
    )
    attachment = estimate["attachments"][0]
    assert attachment["filename"] == "fictional-estimate.xlsx"
    assert attachment["decoded_size"] == len(b"fictional")
    assert len(attachment["content_sha256"]) == 64
    before = data.read_bytes()
    assert _run(archive, data) == 0
    assert "0 new" in capsys.readouterr().out
    assert data.read_bytes() == before


def test_conflicting_duplicate_key_and_missing_source_preserve_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = _archive(tmp_path)
    data = tmp_path / "mail-actions.json"
    assert _run(archive, data) == 0
    capsys.readouterr()
    before = data.read_bytes()
    changed = (
        (FIXTURES / "purchase.txt")
        .read_text(encoding="utf-8")
        .replace("listed supplies", "other supplies")
    )
    (archive / "conflict.eml").write_text(changed, encoding="utf-8")
    assert _run(archive, data) == 1
    assert "conflicting evidence" in capsys.readouterr().out
    assert data.read_bytes() == before
    (archive / "conflict.eml").unlink()
    (archive / "budget.eml").unlink()
    assert _run(archive, data) == 1
    assert "missing" in capsys.readouterr().out
    assert data.read_bytes() == before


def test_ambiguous_ancestry_is_quarantined_without_changing_actions(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    data = tmp_path / "mail-actions.json"
    assert _run(archive, data) == 0
    before = mail_actions.load_inventory(data)
    assert before is not None
    ambiguous = b"""From: Member <member@example.test>
To: Treasurer <treasurer@example.test>
Date: Tue, 22 Sep 2026 10:00:00 -0700
Message-ID: <ambiguous-1@example.test>
References: <purchase-1@example.test> <budget-1@example.test>
Subject: Re: Follow-up
Content-Type: text/plain; charset=utf-8

Thanks for the information.
"""
    (archive / "ambiguous.eml").write_bytes(ambiguous)
    assert _run(archive, data) == 0
    after = mail_actions.load_inventory(data)
    assert after is not None
    assert after["actions"] == before["actions"]
    assert len(after["quarantined_source_keys"]) == 1


def test_dry_run_scope_and_strict_inventory(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    data = tmp_path / "mail-actions.json"
    assert _run(archive, data, "--dry-run") == 0
    assert not data.exists()
    assert _run(archive, data) == 0
    before = data.read_bytes()
    assert _run(archive, data, "--received-since", "2026-09-15") == 1
    assert data.read_bytes() == before
    object_with_extra = json.loads(before)
    object_with_extra["private_unknown"] = "value"
    with pytest.raises(ValueError, match="fields"):
        mail_actions.validate_inventory(object_with_extra)
    data.write_text(
        before.decode().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        mail_actions.load_inventory(data)


def test_dry_run_does_not_create_output_directory(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    data = tmp_path / "never-created" / "mail-actions.json"
    assert _run(archive, data, "--dry-run") == 0
    assert not data.parent.exists()


def test_classifier_uses_top_authored_text_and_rejects_completed_task() -> None:
    raw = (FIXTURES / "purchase_reply.txt").read_bytes()
    msg = message_from_bytes(raw, policy=policy.default)
    mail = receipt_ingest.parse_mail_evidence(msg)
    record = mail_actions._source_record("reply.eml", msg, mail)
    assert mail_actions._classify(record, mail.top_authored_text, False) is None
    completed = (
        "Please record the adopted allocation and update the public budget. "
        "I already updated and recorded it."
    )
    assert mail_actions._classify(record, completed, False) is None


def test_missing_message_id_cannot_link_a_thread(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "no-id.eml").write_bytes(
        b"""From: Volunteer <volunteer@example.test>
To: Treasurer <treasurer@example.test>
Date: Tue, 22 Sep 2026 10:00:00 -0700
References: <purchase-1@example.test>
Subject: Re: Equipment wish-list
Content-Type: text/plain; charset=utf-8

Could you approve the equipment wish-list before we buy the supplies?
"""
    )
    data = tmp_path / "mail-actions.json"
    assert _run(archive, data) == 0
    inventory = mail_actions.load_inventory(data)
    assert inventory is not None
    purchases = [
        item for item in inventory["actions"] if item["proposed_type"] == "PURCHASE_APPROVAL"
    ]
    assert len(purchases) == 2
