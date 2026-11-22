"""Private, deterministic proposals from a local email archive.

This module deliberately does not infer an approval, budget edit, or completion from mail.
The generated version-1 inventory is a review surface, not an operator decision file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from email.message import Message
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from pta_finance import receipt_ingest

ActionType = Literal["PURCHASE_APPROVAL", "BUDGET_FOLLOWUP", "PLANNING_ESTIMATE"]
_TYPES = {"PURCHASE_APPROVAL", "BUDGET_FOLLOWUP", "PLANNING_ESTIMATE"}
_KEY = re.compile(r"(?:mail|action):v1:[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_EXCERPT_LIMIT = 500


class AttachmentRecord(TypedDict):
    filename: str
    mime_type: str
    decoded_size: int
    content_sha256: str


class SourceRecord(TypedDict):
    message_key: str
    evidence_sha256: str
    source_labels: list[str]
    message_id: str
    in_reply_to: list[str]
    references: list[str]
    subject: str
    sender_address: str
    date: str
    top_authored_excerpt: str
    top_authored_sha256: str
    attachments: list[AttachmentRecord]


class ActionRecord(TypedDict):
    action_key: str
    proposed_type: ActionType | None
    reason: str
    source_keys: list[str]
    state: str
    decision: None


class ScanScope(TypedDict):
    source_path: str
    received_since: str | None


class ActionInventory(TypedDict):
    schema_version: int
    scan_scope: ScanScope
    sources: list[SourceRecord]
    actions: list[ActionRecord]
    uncategorized_source_keys: list[str]
    quarantined_source_keys: list[str]


class ActionSummary(TypedDict):
    new: int
    proposed: int
    open: int
    done: int
    uncategorized: int
    quarantined: int


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field in action inventory")
        result[key] = value
    return result


def _fields(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"invalid {label} fields")
    return cast(dict[str, Any], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid {label}")
    return value


def _digest(value: object, label: str) -> str:
    result = _string(value, label)
    if _SHA.fullmatch(result) is None:
        raise ValueError(f"invalid {label}")
    return result


def _key(value: object, prefix: str) -> str:
    result = _string(value, "key")
    if _KEY.fullmatch(result) is None or not result.startswith(f"{prefix}:v1:"):
        raise ValueError("invalid action inventory key")
    return result


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"invalid {label}")
    return [_string(item, label) for item in value]


def _sorted_unique(values: list[str], label: str) -> None:
    if values != sorted(set(values)):
        raise ValueError(f"{label} must be unique and sorted")


def validate_inventory(raw: object) -> ActionInventory:
    """Validate the entire generated schema, including nested fields and key relations."""
    data = _fields(
        raw,
        {
            "schema_version",
            "scan_scope",
            "sources",
            "actions",
            "uncategorized_source_keys",
            "quarantined_source_keys",
        },
        "action inventory",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported action inventory version")
    scope = _fields(data["scan_scope"], {"source_path", "received_since"}, "scan scope")
    _string(scope["source_path"], "source path")
    cutoff = scope["received_since"]
    if cutoff is not None:
        raw_cutoff = _string(cutoff, "received cutoff")
        try:
            if date.fromisoformat(raw_cutoff).isoformat() != raw_cutoff:
                raise ValueError("invalid received cutoff")
        except ValueError as exc:
            raise ValueError("invalid received cutoff") from exc
    sources_raw = data["sources"]
    actions_raw = data["actions"]
    if not isinstance(sources_raw, list) or not isinstance(actions_raw, list):
        raise ValueError("invalid action inventory lists")
    source_keys: list[str] = []
    for raw_source in sources_raw:
        source = _fields(raw_source, set(SourceRecord.__required_keys__), "source")
        source_keys.append(_key(source["message_key"], "mail"))
        _digest(source["evidence_sha256"], "evidence digest")
        _digest(source["top_authored_sha256"], "authored digest")
        for name in ("message_id", "subject", "sender_address", "date", "top_authored_excerpt"):
            _string(source[name], name)
        if len(source["top_authored_excerpt"]) > _EXCERPT_LIMIT:
            raise ValueError("source excerpt exceeds limit")
        labels = _strings(source["source_labels"], "source labels")
        _sorted_unique(labels, "source labels")
        if not labels:
            raise ValueError("source needs a label")
        _strings(source["in_reply_to"], "ancestry")
        _strings(source["references"], "ancestry")
        attachments = source["attachments"]
        if not isinstance(attachments, list):
            raise ValueError("invalid attachments")
        for raw_attachment in attachments:
            attachment = _fields(
                raw_attachment, set(AttachmentRecord.__required_keys__), "attachment"
            )
            _string(attachment["filename"], "attachment filename")
            _string(attachment["mime_type"], "attachment MIME type")
            _digest(attachment["content_sha256"], "attachment digest")
            if type(attachment["decoded_size"]) is not int or attachment["decoded_size"] < 0:
                raise ValueError("invalid attachment size")
    _sorted_unique(source_keys, "source keys")
    action_keys: list[str] = []
    assigned: set[str] = set()
    for raw_action in actions_raw:
        action = _fields(raw_action, set(ActionRecord.__required_keys__), "action")
        action_keys.append(_key(action["action_key"], "action"))
        if not isinstance(action["proposed_type"], str) or action["proposed_type"] not in _TYPES:
            raise ValueError("invalid proposed action type")
        _string(action["reason"], "action reason")
        if action["state"] != "PROPOSED" or action["decision"] is not None:
            raise ValueError("invalid proposal state")
        keys = [_key(item, "mail") for item in _strings(action["source_keys"], "action sources")]
        _sorted_unique(keys, "action sources")
        if not keys or any(key not in source_keys or key in assigned for key in keys):
            raise ValueError("invalid action source membership")
        if action["action_key"] not in {_action_key(key) for key in keys}:
            raise ValueError("action key does not match its source")
        assigned.update(keys)
    _sorted_unique(action_keys, "action keys")
    other = [
        _key(item, "mail") for item in _strings(data["uncategorized_source_keys"], "uncategorized")
    ]
    quarantine = [
        _key(item, "mail") for item in _strings(data["quarantined_source_keys"], "quarantine")
    ]
    _sorted_unique(other, "uncategorized")
    _sorted_unique(quarantine, "quarantine")
    if set(other) & set(quarantine) or set(other + quarantine) & assigned:
        raise ValueError("source is in multiple action inventory categories")
    if set(other + quarantine) | assigned != set(source_keys):
        raise ValueError("action inventory does not account for every source")
    return cast(ActionInventory, data)


def load_inventory(path: Path) -> ActionInventory | None:
    if not path.exists():
        return None
    try:
        return validate_inventory(
            json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid private action inventory") from exc


def _received_day(raw: str) -> date | None:
    return receipt_ingest.parse_received_date(raw)


def _source_record(label: str, msg: Message, mail: receipt_ingest.MailEvidence) -> SourceRecord:
    return {
        "message_key": mail.message_key,
        "evidence_sha256": mail.evidence_sha256,
        "source_labels": [label],
        "message_id": mail.message_id,
        "in_reply_to": list(mail.in_reply_to),
        "references": list(mail.references),
        "subject": str(msg.get("Subject", "")).strip(),
        "sender_address": mail.sender_address,
        "date": mail.date,
        "top_authored_excerpt": mail.top_authored_text[:_EXCERPT_LIMIT],
        "top_authored_sha256": mail.top_authored_sha256,
        "attachments": [
            {
                "filename": item.filename,
                "mime_type": item.mime_type,
                "decoded_size": item.decoded_size,
                "content_sha256": item.content_sha256,
            }
            for item in mail.attachments
        ],
    }


def _classify(source: SourceRecord, authored: str, is_form: bool) -> tuple[ActionType, str] | None:
    """Require a task-shaped request in the author's text; subjects only add context."""
    text = authored.casefold()
    context = f"{source['subject']}\n{authored}".casefold()
    if is_form or re.search(
        r"\b(reimburse(?:ment)?|receipt|paid|charged|invoice|expense form)\b", context
    ):
        return None
    if re.search(
        r"\b(?:already (?:bought|purchased|ordered|updated|recorded)|"
        r"(?:have|has) (?:been )?(?:bought|purchased|ordered|updated|recorded)|"
        r"no (?:need|action) to|do not (?:buy|purchase|update))\b",
        text,
    ):
        return None
    if (
        re.search(
            r"\b(?:please |could you |can you |request(?:ing)? )"
            r"(?:approve|authorize)\b|\bapproval\s+(?:before|prior to)\b",
            text,
        )
        and re.search(r"\b(?:before|prior to|pre[- ]purchase)\b", context)
        and re.search(r"\b(?:buy|purchase|order|equipment|wish[- ]list|supplies)\b", context)
        and not re.search(r"\b(?:approved|approval granted)\b", text)
    ):
        return "PURCHASE_APPROVAL", "pre-purchase approval request with purchase description"
    if (
        re.search(
            r"\b(?:please|must|need to|can you|could you)\b.{0,100}"
            r"\b(?:record|update|enter|reflect)\b",
            text,
        )
        and re.search(
            r"\b(?:adopted|approved|voted|board[- ]approved)\b.{0,100}"
            r"\b(?:allocation|budget)\b|\b(?:allocation|budget)\b.{0,100}"
            r"\b(?:adopted|approved|voted)\b",
            context,
        )
        and re.search(r"\b(?:budget|internal|public|sheet|tracker)\b", text)
    ):
        return "BUDGET_FOLLOWUP", "explicit adopted-allocation budget update instruction"
    spreadsheet = any(
        item["mime_type"]
        in {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "text/csv",
        }
        or item["filename"].casefold().endswith((".xlsx", ".xls", ".csv", ".ods"))
        for item in source["attachments"]
    )
    if (
        spreadsheet
        and re.search(r"\b(?:estimate|estimated|forecast|projection)\b", context)
        and re.search(r"\b(?:budget|planning|tracker)\b", context)
        and re.search(r"\b(?:please|could you|can you|need|request|for planning)\b", text)
    ):
        return "PLANNING_ESTIMATE", "planning estimate request with spreadsheet attachment"
    return None


def _action_key(message_key: str) -> str:
    return "action:v1:" + hashlib.sha256(message_key.encode("utf-8")).hexdigest()


def _order(source: SourceRecord) -> tuple[str, str]:
    day = _received_day(source["date"])
    return (day.isoformat() if day is not None else "9999-12-31", source["message_key"])


def scan_archive(
    source: Path, received_since: date | None, previous: ActionInventory | None = None
) -> tuple[ActionInventory, ActionSummary]:
    """Scan all local sources, preserving existing action keys and refusing evidence drift."""
    if not source.exists() or not (source.is_dir() or source.is_file()):
        raise ValueError("action source archive does not exist")
    scope: ScanScope = {
        "source_path": str(source.resolve()),
        "received_since": received_since.isoformat() if received_since else None,
    }
    if previous is not None and previous["scan_scope"] != scope:
        raise ValueError("action scan scope changed; use a new private --data/--output pair")
    records: dict[str, SourceRecord] = {}
    proposals: dict[str, tuple[ActionType, str]] = {}
    for label, msg in receipt_ingest.iter_source(source):
        try:
            mail = receipt_ingest.parse_mail_evidence(msg)
        except ValueError as exc:
            raise ValueError("malformed mail evidence in action archive") from exc
        day = _received_day(mail.date)
        if received_since is not None:
            if day is None:
                raise ValueError("mail has an invalid received date in action archive")
            if day < received_since:
                continue
        record = _source_record(label, msg, mail)
        key = mail.message_key
        existing = records.get(key)
        if existing is not None:
            if existing["evidence_sha256"] != mail.evidence_sha256:
                raise ValueError("conflicting evidence for an action source key")
            existing["source_labels"] = sorted(set(existing["source_labels"] + [label]))
            continue
        records[key] = record
        proposal = _classify(
            record, mail.top_authored_text, receipt_ingest.parse_submission(msg) is not None
        )
        if proposal is not None:
            proposals[key] = proposal
    if previous is not None:
        prior = {item["message_key"]: item for item in previous["sources"]}
        if not prior.keys() <= records.keys():
            raise ValueError("previously accounted action source is missing")
        if any(
            records[key]["evidence_sha256"] != item["evidence_sha256"]
            for key, item in prior.items()
        ):
            raise ValueError("previously accounted action source changed evidence")
    by_id = {item["message_id"]: key for key, item in records.items() if item["message_id"]}
    actions: dict[str, ActionRecord] = {}
    membership: dict[str, str] = {}
    quarantined: set[str] = set()
    if previous is not None:
        for prior_action in previous["actions"]:
            action = cast(ActionRecord, json.loads(json.dumps(prior_action)))
            actions[action["action_key"]] = action
            membership.update({key: action["action_key"] for key in action["source_keys"]})
        quarantined.update(previous["quarantined_source_keys"])
    # Iterate so a reply can precede its parent in archive order. Existing keys win over an
    # earlier newly discovered source; an edge reaching two actions is never guessed.
    pending = set(records) - set(membership) - quarantined
    for _ in range(len(records) + 1):
        changed = False
        for key in sorted(pending, key=lambda item: _order(records[item])):
            record = records[key]
            ancestors = (
                {
                    by_id[identifier]
                    for identifier in record["references"] + record["in_reply_to"]
                    if identifier in by_id and by_id[identifier] != key
                }
                if record["message_id"]
                else set()
            )
            matches = {membership[parent] for parent in ancestors if parent in membership}
            if len(matches) > 1:
                quarantined.add(key)
                pending.remove(key)
                changed = True
                continue
            if matches:
                action_key = next(iter(matches))
                membership[key] = action_key
                actions[action_key]["source_keys"] = sorted(
                    set(actions[action_key]["source_keys"] + [key])
                )
                pending.remove(key)
                changed = True
                continue
            if key in proposals and not ancestors:
                proposed_type, reason = proposals[key]
                action_key = _action_key(key)
                actions[action_key] = {
                    "action_key": action_key,
                    "proposed_type": proposed_type,
                    "reason": reason,
                    "source_keys": [key],
                    "state": "PROPOSED",
                    "decision": None,
                }
                membership[key] = action_key
                pending.remove(key)
                changed = True
        if not changed:
            break
    # Unresolved proposed replies may reference an ancestor outside the scan; they start a
    # standalone action. Unclassified mail stays visible in the private inventory.
    for key in sorted(pending, key=lambda item: _order(records[item])):
        if key not in proposals:
            continue
        proposed_type, reason = proposals[key]
        action_key = _action_key(key)
        actions[action_key] = {
            "action_key": action_key,
            "proposed_type": proposed_type,
            "reason": reason,
            "source_keys": [key],
            "state": "PROPOSED",
            "decision": None,
        }
        membership[key] = action_key
    uncategorized = sorted(set(records) - set(membership) - quarantined)
    inventory: ActionInventory = {
        "schema_version": 1,
        "scan_scope": scope,
        "sources": [records[key] for key in sorted(records)],
        "actions": [actions[key] for key in sorted(actions)],
        "uncategorized_source_keys": uncategorized,
        "quarantined_source_keys": sorted(quarantined),
    }
    validate_inventory(inventory)
    old_keys = {item["action_key"] for item in previous["actions"]} if previous else set()
    summary: ActionSummary = {
        "new": len(set(actions) - old_keys),
        "proposed": len(actions),
        "open": 0,
        "done": 0,
        "uncategorized": len(uncategorized),
        "quarantined": len(quarantined),
    }
    return inventory, summary


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("action refresh is already running") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def refresh_actions(
    source: Path, data: Path, received_since: date | None, *, dry_run: bool = False
) -> ActionSummary:
    """Validate first, then atomically replace only the generated private inventory."""
    if dry_run:
        _, summary = scan_archive(source, received_since, load_inventory(data))
        return summary
    with _lock(data):
        prior = load_inventory(data)
        inventory, summary = scan_archive(source, received_since, prior)
        serialized = json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=data.parent,
                prefix=".mail-actions-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(serialized)
            os.replace(temporary, data)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return summary
