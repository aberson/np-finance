> Supporting specification extracted on 2026-10-14. The [master](../plans/master_plan.md) owns current status, sequencing and dispatch; dated baseline statements below are source context, not a second queue. Section numbers retain their source meaning.

# receipt-autofill supporting contract

Phase 9 — Steps 38–49. Planned 2026-09-16 against `main` at `7eb0c4f`.

**Goal:** Make `pta-finance update-reimbursements` produce receipt evidence instead of only
consuming it, so newly arrived review items stop rendering "Receipt not linked" until someone
hand-builds a sidecar.
**Status:** STEP 38 DONE (2026-09-23); Step 39 BLOCKED (2026-10-09) after stop-and-audit, with
the Option A1 decision (decode every PNG/JPEG upload in a resource-capped child process, § 6.3)
recorded the same day and the step ready to resume; Steps 40–49 planned.

Master plan: [`plan.md`](../plans/master_plan.md). Steps 1–37 are reserved by earlier phases; this feature
continues at **Step 38**.

Related: [receipt viewer and source backfill](../plans/master_plan.md) (shipped 2026-09-14, the consumer this
feature feeds), [reimbursement refresh plan](../plans/master_plan.md) (the bundle producer),
[treasurer summary Wave 1](../plans/master_plan.md) (owner of the Windows low-privilege AppContainer (LPAC) native worker this
feature extends).

---

## 1. What This Feature Does

`pta-finance update-reimbursements` refreshes the private reimbursement bundle and re-renders the
queue HTML, but it has never produced the receipt sidecar the queue reads. The sidecar is an
*input*: `build_report` looks for `<bundle>.receipts.json` beside the bundle and embeds it if
present. That file was hand-built once, by a bespoke offline backfill. Every review item that
arrives after that build therefore renders **"Receipt not linked"** forever, no matter how many
times the refresh runs.

This feature adds a fourth stage to the refresh that *produces* receipt evidence instead of only
consuming it: it fetches each ticket's own uploaded receipt assets from an operator-configured
host allowlist into a private content-addressed cache, renders them to display pages (PDFs
through the existing attested Windows LPAC worker; PNG/JPEG uploads in a short-lived,
resource-capped decode child, § 5A), and writes sidecar links for the cases where
page-to-item provenance is a fact rather than a guess. Everything ambiguous is staged into a
private proposals file that an operator confirms explicitly.

Red outlines are deliberately **not** automated. `receipt_viewer.py:4-5` states the rule this
feature must not break: *"Never infer a location from an amount or description: an absent box
means the exact line has not been identified."* Machine-placed boxes would make a link assert
something no human checked. This feature gets the right page in front of the reviewer; a human
still marks the line.

**Triggering event.** Operator report, 2026-09-16: the end-to-end run "doesn't seem to fill
receipts". Confirmed — the run went from 80 to 84 unlinked items with zero fingerprint drift,
purely because two tickets arrived on 2026-09-13 and nothing regenerates the sidecar.

**Autonomous-behavior trigger: does not fire.** Every stage here runs inside one operator-invoked
CLI run that completes and exits. The fill stage spawns short-lived, resource-capped decode
children — one per PNG/JPEG asset, one at a time — and each is killed or exits before the next
starts and before the run ends. No scheduler, daemon, watcher or background loop is added.
The monthly GitHub Actions workflow is untouched and still does reports only. Reviewers should
confirm this classification rather than assume it.

---

## 2. Existing Context

Baseline inspected at `7eb0c4f`, branch `main`, 2026-09-16. Findings below come from producing
files, not from documentation. Line citations in §§ 2, 4, 5A, 6.1 and 9 that later commits moved
(`a421c94`, `d150bb6`) were re-baselined at `09b1a45` on 2026-10-09, and every citation added or
touched by the second 2026-10-09 fold-in (§§ 4, 5A, 6.3, 7, 8 and 9) or by the plan-wrap fold-in
(§ 5A's LPAC envelope and response citations) was read at `09b1a45`; any other line number is as of
`7eb0c4f`. Re-grep a cited symbol at dispatch rather than trusting its line number — Phase 10's
paused `cli.py` change will shift those lines again.

| Producer | Behavior verified in source |
|---|---|
| `pta_finance/reimbursement_report.py:1615` | `build_report` (`:1609`) computes `receipts_path = data_path.with_suffix(".receipts.json")`. |
| `pta_finance/reimbursement_report.py:1617-1619` | Loads the sidecar only `if receipts_path.exists()`; otherwise `None`. |
| `pta_finance/reimbursement_report.py:1562` | `render_html` falls back to `{"pages": {}, "items": {}}`, silently dropping every item without an entry. |
| `pta_finance/reports/templates/reimbursement_queue.html.j2:74` | Emits `View source receipt` vs `Receipt not linked` from `receipts['items'].get(receipt_id(ticket, item))`. |
| `pta_finance/cli.py:1079-1193` (`_cmd_update_reimbursements`) | `update-reimbursements` is exactly three stages: Gmail acquisition, `refresh_bundle`, `build_report`. No stage writes the sidecar. |
| `pta_finance/receipt_viewer.py:20-21` | `MAX_PAGE_BYTES = 20 MiB`, `MAX_TOTAL_BYTES = 100 MiB`, counted on **raw** bytes before base64. |
| `pta_finance/receipt_viewer.py:28-43` | `item_fingerprint` folds in `ticket.source_evidence_sha256` plus the item's source and effective fields. |
| `pta_finance/reimbursement_pipeline.py:314-328` | `evidence_payload` is the digest surface behind `source_evidence_sha256`. Receipt URLs (`:323`) and attachment filenames (`:324`) are hashed into it and then **dropped** — the bundle keeps no pointer to a receipt. |
| `pta_finance/reimbursement_pipeline.py:140-142` | `review_key = "submission:v1:" + sha256(<b>raw</b> `Message-ID` header, stripped)` — `_review_key(submission.message_id.strip())` at `:266`/`:273`. **Not** the normalized form: `normalize_message_id` lowercases the domain and feeds the separate `source_message_id` at `:329`. This is the only durable one-way join from a ticket back to its `.eml`. |
| `pta_finance/receipt_ingest.py:787`, `:889`, `:892` | `_extract_receipt_urls` already parses the submission's labeled upload fields into `Submission.receipt_urls`; `source_receipt_urls_v1` (`:153`, `:707-713`) is the frozen digest-surface subset. |
| `pta_finance/treasurer_slides/native_sandbox.py:1773` | `start_native_pdf_worker` — the attested Windows LPAC boundary. One capability (`registryRead`), no network, no inherited handles, no source path. |
| `pta_finance/treasurer_slides/bank_statements.py:69-95` | Eleven public limits, each paired with a `_HARD_MAX_*` ceiling; re-validated inside the worker by exact key-set equality. |
| `pta_finance/config.py:284-307` | `_load_receipt_mapping` is the exact shape a new optional config block must follow: `None` when absent, `ConfigError` when malformed. |
| `.gitignore:10` | `reports/output/` is already fully ignored — cache and page directories placed under it need no new rule. |
| `pyproject.toml:17-27` | Extras are `pdf`, `slides` (`pypdfium2>=5.13.0`), `web`, `dev`. Core dependencies at `:7-15` must not grow. Pillow is already installed everywhere as a transitive core dependency through `matplotlib` (`:11`; `uv.lock:1063`, pinned `12.2.0` at `:1291-1292`). |
| `.github/workflows/ci.yml:3-5`, `:22`, `:63-64`, `:137-143` | Three jobs, triggered on every push and pull request. **There are no workflow path filters;** jobs scope their tests with explicit file lists or `-k`. Only `shared-workflow` installs Chromium (`:64`). `windows-native-sandbox` runs a fixed pytest file list (`:139-143`), so a test file it does not name never runs there. |

### Measured state of the gap (2026-09-16)

| | count |
|---|---|
| Review items in the live bundle | 231 |
| Items with a sidecar link | 147 |
| Items showing "Receipt not linked" | 84 |
| — of those, one legacy ticket adjudicated 2026-09-14 as having no locatable invoice | 69 |
| — structurally unlinkable (paper totals, blank form rows, duplicate/reissue markers, one absent original) | 11 |
| — **arrived 2026-09-13, never had a chance to be linked** | **4** |
| Fingerprint drift across the 2026-09-14 → 2026-09-16 runs | 0 |

All four new items carry an upload URL in their own submission email that has never been
downloaded. Corpus-wide the intake form delivers receipts as hosted URLs, never as MIME
attachments: only 4 of 319 parsed submissions carry any attachment at all, and none of the 84
unlinked items' source forms do. Exactly two upload hosts appear anywhere in the corpus, both
belonging to the intake form vendor's CDN. Their real values are private configuration and must
never appear in a committed file.

### Measured page-budget state

**Current, 2026-10-09** — after that day's manual receipt backfill, which is Step 49's cutoff.
Aggregate counts only:

| metric | value |
|---|---|
| Items with a sidecar link | 190 |
| Embedded sidecar pages / raw bytes | 221 / 96,800,197 B (92.3 MiB) |
| Cap consumption | 92.3% of `MAX_TOTAL_BYTES`; about 7.7 MiB (8,057,403 B) free |

**Implication.** A normalized page averages about 0.25 MiB (41.34 MiB over 164 pages at 2200/q85,
below), so roughly 30 new pages fit before the cap. Step 45's budget pre-check will therefore
refuse soon, possibly during Step 49's own fill run. That refusal aborts the whole merge, so it
links nothing (§ 5A Errors), and it names the crossing page and the remaining bytes. For that
reason every merge prints the remaining headroom (§ 5A, Printed receipt summary), and Step 49
records it. `link-receipts compact` stays out of scope (§ 3, § 8).

**Historical, 2026-09-14/16** — 164 pages and 147 links. These figures are the basis of § 6.5's
projection and § 6.6's normalization choice:

| metric | value |
|---|---|
| Sidecar pages / raw bytes | 164 / 71,349,077 B (68.04 MiB) |
| Cap consumption | 68.0% of `MAX_TOTAL_BYTES`; 31.96 MiB free |
| Largest single page | 1.047 MiB (5.2% of the 20 MiB per-page cap — not binding) |
| Stored mix | 108 PNG (44.64 MiB) / 56 JPEG (23.40 MiB) |
| Rendered HTML | 95,558,877 B (base64 inflates raw page bytes ~1.37x) |
| Pages produced per fetched asset | PDF 1.537, PNG 1.000, JPEG 1.000 |
| Asset mix already fetched | 67 PDF / 36 PNG / 33 JPEG of 136 |

Those ratios describe *pages produced* (172 from the 136 fetched assets), not pages *embedded*: the
sidecar holds 164 because unreferenced pages are pruned and 8 pages were staged separately. The
§ 6.5 cap projections use the produced-pages ratio, which is the conservative direction.

Re-encode measurements over all 164 pages live on 2026-09-16 (Pillow 12.2.0, LANCZOS, downscale
only when the page exceeds the limit):

| variant | total | vs as stored | median fine-print line height |
|---|---:|---:|---:|
| as stored on 2026-09-16 | 68.04 MiB | 100% | 19.0 px |
| **long edge 2200 / JPEG q85** | **41.34 MiB** | **60.7%** | **19.0 px** |
| long edge 1800 / q82 | 30.18 MiB | 44.3% | 17.2 px |
| long edge 1600 / q80 | 24.34 MiB | 35.8% | 15.3 px |

Only 7 of 164 pages exceed a 2200 long edge, so the 2200/q85 variant is effectively a PNG→JPEG
transcode: it saves 39% with **identical** fine-print geometry and zero pages pushed under 8 px.
The tighter variants buy their extra saving by shrinking pixels on receipts that contain small
print. 2200/q85 is therefore the normalization default.

---

## 3. Scope

### Included

- A `fill-receipts` stage inside `update-reimbursements`, between the refresh summary and
  `build_report`, plus a `link-receipts` verb group for the staged half.
- Fetching a ticket's own uploaded receipt assets over HTTPS from an operator-configured host
  allowlist, into a gitignored content-addressed cache, with magic-byte sniffing, size ceilings
  and per-asset failure isolation.
- Rendering PDF assets to page images through the existing attested Windows LPAC worker,
  extended with a render response. Non-Windows hosts fail closed: PDFs are cached and counted,
  never parsed. (If Step 41 records a blocked verdict, the boundary recorded by Step 42 replaces
  the LPAC, and "fails closed" applies to the hosts that boundary does not support.)
- Decoding every PNG/JPEG upload in a short-lived, resource-capped child (`receipt_decode`): a
  Windows Job Object or Linux rlimits plus a broker wall clock, with any other host aborting the
  stage before a spawn (§ 5A, § 6.3). The broker never decodes an untrusted image byte.
- A behavior-preserving extraction of `native_sandbox`'s Job Object primitive into the shared
  stdlib-only leaf `process_limits`, used by both the LPAC launcher and the decode child (§ 4).
- Deterministic page normalization (EXIF transpose, long edge ≤ 2200, JPEG q85) shared by every
  producer, with one source of truth for the geometry constants.
- Auto-committing `box: null` sidecar regions only under § 5A's three conditions — exactly one
  distinct receipt asset, at least one page produced from it, and no item on the ticket already
  linked — then linking every item on that ticket to every page of that one asset.
- A private `<bundle>.receipt-proposals.json` listing every ticket that has at least one unlinked
  item and at least one candidate page (the one membership rule, § 5), and
  `link-receipts confirm` to merge an operator-edited proposals file into the sidecar.
- A page-budget pre-check that refuses before crossing `MAX_TOTAL_BYTES`, naming the page and the
  remaining budget, plus a printed headroom line after every merge (§ 5A).
- The CI browser-guard repair: the guard was red at planning time, and Step 38 fixed it (DONE
  2026-09-23).

### Explicitly out

- **Automatic box placement.** No OCR, no description matching, no amount matching. Forbidden by
  `receipt_viewer.py:4-5`, and the 2026-09-14 backfill is evidence that mechanical matching needs
  per-item adversarial review to be trustworthy.
- **Re-encoding the existing human-verified pages** (221 as of 2026-10-09). On the 164 pages
  measured on 2026-09-16 it would have saved 39% (§ 2), but it rewrites evidence a human already
  checked. Reserved as an explicit, separately-invoked
  `link-receipts compact` verb in a later phase, never an automatic step.
- **A local HTML picker for confirming multi-asset tickets.** Reserved as Step 50 in a later
  phase; the CLI confirm path ships first so the feature is complete and testable.
- Recovering the 80 items that § 2 splits into 69 adjudicated-no-locatable-invoice and 11
  structurally unlinkable. Their originals are absent from the evidence.
- Any Sheets write, any outbound mail, any change to the monthly workflow, any change to
  adjudication, amounts, or review decisions.
- Harvesting receipt images from `.eml` MIME attachments. Measured at 0 of the 84 unlinked items
  and 4 of 319 submissions corpus-wide; it would close nothing today. Noted as a cheap follow-up
  because it shares the sidecar-merge half and skips transport entirely.

---

## 4. Impact Analysis

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `pta_finance/receipt_viewer.py` | extend | Export the page-budget constants and a headroom helper so producers cannot redefine them. `load_receipts` and `item_fingerprint` are **unchanged**. | grep'd `MAX_TOTAL_BYTES` / `MAX_PAGE_BYTES` — 1 definition + 1 use each, both in this file (`:20-21`, `:114`, `:118`); no external consumer. `item_fingerprint` — 3 sites: def `:28`, use `:145`, `tests/test_receipt_viewer.py:61`. All three keep calling it; nothing re-derives it. |
| `pta_finance/reimbursement_report.py` | none | Sidecar detection and render already do the right thing once the file exists. | grep'd `render_html` — 2 production (`:1537` def, `:1622` call) + test sites (`test_reimbursement_pipeline.py:1951`; `test_reimbursement_report.py:316,365,389,495,592,712`). Signature unchanged, so all are unaffected. |
| `pta_finance/cli.py` | modify | New stage inside `_cmd_update_reimbursements`, after the refresh summary and before its `build_report` call (`:1185`); new `link-receipts` subparser group in `build_parser` (`:1325`); new flags on `update-reimbursements`. Anchor to these function names, not line numbers: Phase 10 Step 51 adds its own `update-actions` subparser in `build_parser`, Phase 10 Step 54 edits `_cmd_update_reimbursements`, and Phase 6 Steps 26–28 add their own commands to `build_parser` (§ 8). | grep'd `build_report` across `pta_finance/`, `tests/`, `scripts/` — **14 sites**: 1 definition (`reimbursement_report.py:1609`), 2 production callers in `cli.py` (`:1071` `report-reimbursements`, `:1185` `update-reimbursements`), **1 in `scripts/capture_readme.py`** (the README screenshot helper — it renders fictional data and must keep doing so; verify it never picks up a real sidecar), and 10 test sites (`test_receipt_viewer.py` ×5, `test_reimbursement_cli.py` ×3, `test_reimbursement_report.py` ×2). Only `:1185`'s enclosing function changes; `:1071` stays offline and untouched. |
| `pta_finance/config.py` | extend | New optional `[receipt_assets]` block following `_load_receipt_mapping` exactly. | Read `:100-126` (dataclass + `Config` optional fields) and `:284-307` (parser). Additive optional field; absent block = today's behavior. |
| `config.example.toml` | extend | Ship the block with **fake** hosts. Real allowlist stays in gitignored `config.toml`. | Identity rule, `CLAUDE.md:3-8`. |
| `pta_finance/receipt_ingest.py` | extend | Expose the already-parsed `Submission.receipt_urls` to the fill stage. **No change to `source_receipt_urls_v1`.** This file also ships in the hosted Cloud Run image (see the `source-manifest.txt` row below). | grep'd — `receipt_urls` set at `:889` from `_extract_receipt_urls` (`:787`), read at `:1102`; `source_receipt_urls_v1` at `:153`, `:707-713`, `:892`. The frozen-digest-surface split already exists and is the precedent to follow. |
| `pta_finance/reimbursement_pipeline.py` | **none — hard constraint** | Nothing may enter `evidence_payload`. | Read `:314-328` (payload), `:351` (digest), and the fail-closed guards at `:1789-1812`. Adding one field rotates every `source_evidence_sha256`, which rotates every `item_fingerprint`, which invalidates every live link (190 as of 2026-10-09) and makes the refresh refuse. `refresh_bundle`/`plan_bundle_refresh` signatures unchanged — grep'd `refresh_bundle` across `pta_finance/`, `tests/`, `scripts/`: **59 sites** (1 production caller `cli.py:1160`, 2 in `reimbursement_pipeline.py`, 3 in `test_reimbursement_cli.py`, and **53 in `test_reimbursement_pipeline.py`**). The signature is heavily pinned; the new stage must therefore be its own call, never a new kwarg. |
| `pta_finance/treasurer_slides/bank_statements.py` | extend | Render limits, render request/response, and the page-raster path: Step 41 adds the minimal render branch its spike needs, plus its validated frame reader, `RenderedPage` and the `ReceiptRenderError` base. Step 43 extends them into the full protocol. Landing the code here means `native_sandbox.py` needs **no protocol** changes; its only change is Step 39's behavior-preserving wrapper refactor of the job helper (next row). | Read `_PUBLIC_WORKER_PACKAGE_FILES` (`native_sandbox.py:36-42`) — a closed 5-file allowlist that already includes `bank_statements.py`. A new module would have to be added to it. |
| `pta_finance/treasurer_slides/native_sandbox.py` | behavior-preserving wrapper refactor (Step 39) | Protocol parameters ride the existing limits envelope. Step 39 moves the Job Object ctypes work — job creation, its structures, its limit-flag constants and the `IsProcessInJob` binding — into the shared leaf `pta_finance/process_limits.py`, which the image decode child also uses, so the primitive is extracted rather than restated. This is **not** import-only: the leaf cannot raise `NativeSandboxUnavailable` or defer a handle, so `native_sandbox._make_job_object` stays as a thin wrapper that calls `process_limits.make_job_object` (default `active_processes=1`), maps `ProcessLimitsError` to `NativeSandboxUnavailable`, and keeps the deferred close of a handle the leaf could not close (§ 5A). `_launch_worker` (`:1627`) and every other caller are unchanged. **Every** `native_sandbox` call into the leaf maps `ProcessLimitsError` to `NativeSandboxUnavailable` at that call site: the job wrapper, and the attestation check at `:1427-1442`, which calls the leaf's `is_process_in_job` and raises `NativeSandboxUnavailable` both when the leaf raises and when it answers no — exactly the two cases it raises for today. No `OSError` may escape where `NativeSandboxUnavailable` was raised, because `bank_statements.py:4105` catches only `NativeSandboxUnavailable` to turn a worker-start failure into a page error. The argument check `memory_bytes < 1 or cpu_seconds < 1` (`:725-726`) stays in the wrapper and still raises `NativeSandboxUnavailable` before any leaf call; the leaf repeats it for its own callers (§ 5A error contract). **Collision:** treasurer-summary Wave 1 Step 16 (issue #43, still PENDING) claims this file for its separately launched Tesseract Job; whichever lands second rebases. Step 16's brief carries a reciprocal note (added 2026-10-09) that its Job Object creation goes through this wrapper rather than restating it (§ 8). | `_NATIVE_LIMIT_FIELD_CEILINGS` (`bank_statements.py:1040-1045`) is a flat name→ceiling table and `_deserialize_native_limits` (`:1065-1084`) validates by key-set equality, so new int fields are covered without touching the launcher or `native_worker._parse_arguments` (`native_worker.py:173-209`). Read `_make_job_object` (`native_sandbox.py:724-776`; it raises through `_raise_sandbox_unavailable` at `:726`, `:735`, `:759` and defers an unclosable handle at `:761-776`), the flag constants (`:60-65`) and the structures (`:134-167`): its one caller is `_launch_worker` (`:1627`). `native_sandbox.py` is outside the staged worker allowlist `_PUBLIC_WORKER_PACKAGE_FILES` (`:36-42`), so the LPAC runtime is unaffected. |
| `pta_finance/treasurer_slides/native_worker.py` | none — duplicate acknowledged | Its own Job Object flags (`:27-45`) and structures (`:102-136`), used by `_job_limits_match` (`:566-594`), restate what `process_limits` holds. The duplicate is **forced**: the worker runs from the staged closed allowlist (`native_sandbox.py:36-42`), which does not include `process_limits.py`, and widening that allowlist is a release-reviewed LPAC change outside this phase. | Step 39 adds a parity test across `process_limits` and `native_worker` (`is` is impossible across the staging boundary), so the two copies cannot drift silently. A literal `_fields_` equality cannot hold, because each module's `_ExtendedLimitInformation` embeds its own `_BasicLimitInformation` and `_IoCounters` classes (`native_worker.py:127-130`, `native_sandbox.py:159-162`). The test therefore compares each structure recursively: field names in order, the scalar ctypes type of every leaf field, every field's offset, and `ctypes.sizeof` of each structure and nested structure, plus equal flag values. |
| `pta_finance/receipt_decode.py` | new (Step 39) | The image decode child (§ 5, § 5A): every untrusted PNG/JPEG byte is decoded here, never in the broker (§ 6.3). It also owns the stdlib-only size/scale derivation that `receipt_pages` imports for validation. | New file. Its only process caller is `receipt_pages.to_pages`; Step 44's broker-derived PDF pages never use it. |
| `pta_finance/process_limits.py` | new (Step 39) | Shared leaf holding the Windows Job Object primitive extracted from `native_sandbox.py`; imported by `native_sandbox.py`, `receipt_pages.py` and `receipt_decode.py` (the child's self-attestation). Error contract in § 5A. | ctypes and stdlib only; it imports nothing from `pta_finance`, so no importer gains a dependency, and it is importable (but inert) on Linux. |
| `tests/test_receipt_viewer.py` | modify | Repair the vacuous browser guard (Step 38); add the `headroom_bytes` tests (`test_headroom_*`, including the refusal parametrize and the Windows same-drive and UNC path rules) with Step 39's helper; add the fill-stage fail-closed cases beside the 19-case parametrize (Step 47 lists the classes). | Read `:91-114` (parametrize), `:158-161` (prior-HTML-preserved assertion), `:189` (`importorskip`). The paused Step 39 worktree already carries the `test_headroom_*` cases. |
| `tests/test_reimbursement_cli.py` | modify | Stage ordering and `refresh_kwargs` equality are pinned and will fail. | Read `:200-340`. `:238-247` pins exact `refresh_kwargs`; `:311` pins `['refresh','report']`. The new stage must be its own call, never a new kwarg. Phase 10 Step 54 and Phase 6 Step 26 also edit this file (§ 8). |
| `.github/workflows/ci.yml` | modify | Step 38 repaired the browser gate (DONE). Step 39 adds the `receipts` extra to each job's fixed `--extra` list, wires the new test files into `lint-type-test`'s JUnit required set and `windows-native-sandbox`'s file list, and adds a `windows-native-sandbox` step `uv run pytest -q tests/test_receipt_viewer.py -k headroom` (the `headroom_bytes` Windows drive and UNC rules). Its calibration runs through a temporary step in both jobs that is removed before merge (§ 5A). Step 41 adds its spike test to the Windows file list. | Read all 3 jobs. The workflow runs on every push and pull request (`:3-5`) — there are **no** workflow path filters, and none may be added (an `on.paths` filter would gate all three jobs). `lint-type-test` (`:22` install, `:33` pytest, `:34-45` JUnit case/skip checks) collects every test file except the native statement suite; `shared-workflow` (`:63-64` install + Chromium, `:90-102` receipt browser step, `:103-104` the only `mypy --strict` run); `windows-native-sandbox` (`:137` install, `:139-143`) runs a fixed pytest file list. |
| `pyproject.toml` + `uv.lock` | extend | New optional `receipts` extra that pins the Pillow floor. | `:7-15` core deps must not grow — and do not: Pillow is already a transitive core dependency through `matplotlib` (`:11`; `uv.lock:1063`, pinned `12.2.0` at `:1291-1292`), so the extra adds no package. It exists to pin the `>=12.2` floor the decoder was reviewed against for unlocked installs. CI installs `--locked` in all three jobs (`:22`, `:63`, `:137`) — an unrefreshed lock fails every job before a test runs. Phase 6 Step 28 also edits these two files for its own `[summary]` extra (§ 8). |
| `deployment/shared-workflow/source-manifest.txt` (hosted image inputs) | none — keep green | `pyproject.toml`, `uv.lock` and `pta_finance/receipt_ingest.py` are staged into the Cloud Run image, whose Dockerfile runs `uv sync --locked --no-dev --extra web`. Steps 39 and 48 re-lock and Step 45 adds an accessor to `receipt_ingest.py`. That accessor imports nothing outside the manifest's files (none of the new Phase 9 modules is staged), and Step 45's Done-when includes `tests/test_shared_workflow_packaging.py` passing. The `receipts` extra is not installed by `--extra web`, so the image gains no package. Any image rebuilt for M8 (the hosted shared-workflow acceptance milestone, Step 37 in `plan.md`) after Phase 9 lands picks up the new lock. | Read the manifest (it lists `pyproject.toml`, `uv.lock`, `pta_finance/receipt_ingest.py` and `pta_finance/reimbursement_report.py`), `deployment/shared-workflow/Dockerfile:7`, and `tests/test_shared_workflow_packaging.py:115-160`, which builds a wheel from the staged files and imports `load_source` from it. |
| `CLAUDE.md`, `docs/receipt-viewer.md`, `docs/loading-receipts.md`, `README.md` | modify | The "prepared offline" and "never downloads" wording needs a refresh-time carve-out; the new modules, the fill stage's supported hosts and the calibrated decode limits need recording; `CLAUDE.md` § 2 Stack needs the `receipts` extra and § 3 Key commands needs the new `link-receipts` verbs and `update-reimbursements`' new write set (Step 48). | `CLAUDE.md:197` (the "prepared offline" sentence), `CLAUDE.md` § 2 (`:20`, one row per extra), § 3 (`:37`; `:72` says `update-reimbursements` writes ".eml + private bundle + HTML; no Sheet"), § 4 layout and § 7 environment; `docs/receipt-viewer.md:24-27`, `:81-85`; `docs/loading-receipts.md:321-380`. Phase 6 Step 29 and Phase 10 Step 54 also edit `README.md` and `CLAUDE.md` (§ 8). |

---

## 5. New Components

| Module | Responsibility |
|---|---|
| `pta_finance/receipt_geometry.py` | The single definition of the **Python-side** page-normalization limits (long edge 2200, JPEG q85, the 80 MP decode ceiling, the 65,535 source-edge ceiling, the 25 MiB source-byte cap, the white flatten background, and the decode child's memory, CPU, wall-clock, ready-line and Linux address-space-baseline budget) and the box padding, imported by every producer rather than restated. The PNG→JPEG threshold is **zero by design** and so has no constant: every page, whatever its source format or size, is re-encoded as JPEG, which is the variant § 2 measured. It deliberately does **not** own the viewer's ellipse inflation: that geometry is JavaScript at `pta_finance/reports/templates/receipt_viewer.js.j2:46-47` (`rx = min(w*.60 + .006, …)`, `ry = min(h*.72 + .003, …)`) and is rendered in the browser, so a Python constant cannot be its source of truth. Instead this module records the same numbers as the documented mirror of that template, and a test asserts the two agree by parsing the template — so a change to either side fails CI. (The private backfill scripts that also restate the padding are untracked and out of scope; no step edits them.) |
| `pta_finance/receipt_assets.py` | Transport only; full signature in § 5A. Exact-or-suffix hostname allowlist, HTTPS only, `read(cap + 1)` so oversize is detected rather than truncated, magic-byte sniffing that decides the type (`Content-Type` never trusted), content-addressed cache keyed by the digest of the bytes and found from a URL through the ledger, a cache-only `offline` mode that never opens a socket, the one `canonical_key(url)` function, per-asset failure recorded and isolated. Bounded by config's `max_asset_mib`; the page-budget constants belong to `receipt_link`. Signature in § 5A. |
| `pta_finance/receipt_pages.py` | Asset → display pages. PNG/JPEG decode and normalization run in a resource-capped child (`receipt_decode`); the broker validates the raw pixels it returns and re-encodes the page. PDF is delegated to the LPAC worker. Both producers end in **one** function, `pixels_to_page` (§ 5A): validated raw pixels in, long-edge downscale (a no-op for child output, which is already within the limit) and baseline-JPEG encode out, so the PDF path is downscaled and encoded exactly like an upload. Deterministic, in this order (the first three in the child, the encode in the broker): apply the EXIF/XMP orientation from a fixed transpose table (EXIF is read, never re-serialised), alpha-flatten onto white, downscale only when over the limit, then re-encode from pixels alone so no source comment, EXIF, XMP, ICC or text chunk reaches the page. Flattening precedes scaling because Pillow resamples palette and bilevel images nearest-neighbour. Records display size, scale and digest on each `PageImage`, and raw size, applied orientation and the decode child's measured `DecodeUsage` on its per-page `PageProgress`. Writes progress **per page**, never once at the end. Carries the invariant that uniform scaling preserves fractional box geometry while rotation destroys it. |
| `pta_finance/receipt_decode.py` | The image decode child, run only as `-I -m pta_finance.receipt_decode` and launched as **one** process (§ 5A: on Windows the base interpreter `sys._base_executable`, never the venv launcher), once per PNG/JPEG asset, under OS-enforced memory and CPU limits and a broker wall clock: on Windows a Job Object the broker builds with `process_limits` and the child self-attests; on Linux `RLIMIT_AS`/`RLIMIT_CPU`, which the child applies and reads back. Either way the limits hold before it reads any asset byte. Everything that touches untrusted image bytes runs here — open, orientation, flatten, LANCZOS resize — and it returns only bounded raw pixels plus a fixed-key header. It imports only the standard library, Pillow (inside `main()` only) and the stdlib-only `process_limits` leaf, and every value it applies arrives in the request, so the protocol (§ 5A) can later move into the attested LPAC worker unchanged. |
| `pta_finance/receipt_link.py` | Provenance and merge; full signatures in § 5A, including the `mail_root` that carries the archive for the ticket->.eml join and `record_fill_ledger`, the one writer of the ledger's `page_outcomes[]` and `unjoinable_tickets[]`. `fill_working_set` chooses what the fill stage fetches, `propose` builds the proposals document, `write_proposals` is its one writer, and `apply` merges and returns the `MergeResult` behind the printed summary. Owns the unambiguity gate, the refusal rules, the budget pre-check, and self-validation through the production `load_receipts` + `build_report` before any replacement. |
| `<bundle>.receipt-proposals.json` | Private, gitignored, per-ticket staging — the only surface an operator hand-edits, and only its `items[].confirmed_page_ids`. Specified inline below. |
| `<cache_dir>/fill-ledger.json` | Private fetch provenance (URL, digest, timestamp, outcome), the per-(ticket, asset) page outcome — including every decode refusal and child error — and so the one per-asset triage surface behind the run's aggregate counts. Kept out of the sidecar, whose `pages[]` objects require the exact key set `{id, path, sha256, label}` and cannot carry a URL. |

### The proposals document, specified

Read with `object_pairs_hook` so a duplicated JSON key is a refusal, and validate every object
against an **exact** key set. All values below are fictional.

```json
{
  "document_type": "receipt-proposals",
  "schema_version": 1,
  "generated_at": "2026-01-02T03:04:05Z",
  "bundle_path": "reports/output/reimbursement-report.json",
  "bundle_sha256": "<64 lowercase hex of the bundle file at propose time>",
  "page_root": "receipt-pages/auto",
  "tickets": [
    {
      "review_key": "submission:v1:<64 hex>",
      "ref": "EX-01",
      "display_order": 1,
      "asset_count": 2,
      "auto_eligible": false,
      "assets": [
        {"asset_id": "asset:v1:<64 hex A>", "ordinal": 1, "origin": "form-upload",
         "canonical_key": "cdn.example-forms.invalid/u/abc"},
        {"asset_id": "asset:v1:<64 hex B>", "ordinal": 2, "origin": "form-upload",
         "canonical_key": "cdn.example-forms.invalid/u/def"}
      ],
      "candidates": [
        {"page_id": "EX-01-a1-p1", "asset_id": "asset:v1:<64 hex A>", "asset_page": 1,
         "path": "receipt-pages/auto/EX-01-a1-p1.jpg", "sha256": "<64 hex>",
         "label": "Ticket EX-01 · upload 1 · page 1"},
        {"page_id": "EX-01-a2-p1", "asset_id": "asset:v1:<64 hex B>", "asset_page": 1,
         "path": "receipt-pages/auto/EX-01-a2-p1.jpg", "sha256": "<64 hex>",
         "label": "Ticket EX-01 · upload 2 · page 1"}
      ],
      "items": [
        {"item_key": "<exact item key from the bundle>", "source_index": 1,
         "item_sha256": "<receipt_viewer.item_fingerprint(ticket, item)>",
         "confirmed_page_ids": []}
      ]
    }
  ]
}
```

**Membership — the one rule** (§ 3, § 5A and Steps 45, 46 and 49 all use it). The document
lists every ticket that has at least one **unlinked** item (an item with no sidecar entry) and at
least one **candidate page** (a page produced from one of that ticket's fetched assets). A fully
linked ticket never appears, and `items[]` lists only the ticket's unlinked items. If every asset
on a ticket yielded zero pages, the ticket has nothing to confirm. It is reported through the
ledger's `page_outcomes[]` and `link-receipts audit` instead of this file. `auto_eligible` records
§ 5A's auto-commit rule for the ticket. When it is `true`, `propose` pre-fills each item's
`confirmed_page_ids` with every page of the ticket's one asset, in page order, and the fill stage
merges the ticket itself (§ 5A, fill-stage order). Every other ticket waits for `confirm`. A
successful merge, whether by the fill stage or by `confirm`, removes in the same write every item
it linked and every ticket left with no items. The file therefore never lists an already-linked
item. `link-receipts propose` never merges, so an auto-eligible ticket it writes stays pre-filled
until `confirm` or the next fill run merges it.

**Generated fields.** `display_order` is the bundle's `Ticket.display_order`, the queue's own
1-based ticket order. It is copied so the operator can place the ticket in the queue, and tickets
are sorted by it. `candidates` are sorted by asset ordinal, then page; `items` by `source_index`.
`asset_count` counts the ticket's distinct `canonical_key`s, fetched or not. `bundle_sha256` is
the sha256 of the bundle file the document was built from.

**What an operator may edit: only `items[].confirmed_page_ids`.** Every other field is generated.
An item is **confirmed** when `confirmed_page_ids` is a non-empty list of page ids drawn from that
same ticket's `candidates`. `link-receipts confirm` merges every confirmed item, as regions with
`box: null`; every other item is left alone. Before merging, it checks each confirmed item against
the current bundle, sidecar and page files: `item_sha256` must equal `item_fingerprint`, each
confirmed id must be one of the ticket's `candidates`, and each candidate file must exist under
`pages_dir` with its `sha256`. Any mismatch refuses the whole merge. Labels are ordinal-only —
never a source filename, URL, vendor, requestor or line-item description, because `pages[].label`
reaches the rendered HTML and the viewer's `img alt`.

**Irreconcilable edits.** When `propose` regenerates over an existing file, it carries every
non-empty `confirmed_page_ids` across by `(review_key, item_key)`. It refuses with
`ReceiptLinkError`, which names the ticket ref and the item's `source_index` and leaves the file
byte-unchanged, when an edited item:
(1) names a page id that is no longer among the ticket's regenerated `candidates`, or whose
candidate `sha256` changed; (2) has a different `item_sha256`, meaning its evidence changed;
(3) has vanished from the bundle; or (4) is on a ticket whose `assets[]` changed (a different
`asset_count`, ordinal or `asset_id`). An item with an empty `confirmed_page_ids` carries no edit
and is simply regenerated.

**Stale bundle.** `confirm` first compares `bundle_sha256` with the current bundle file. If they
differ, it refuses before any other read or write with `ReceiptProposalsStaleError`, a
`ReceiptLinkError`, and names the remedy: re-run `link-receipts propose`, which regenerates the
file and keeps the edits. A refresh with the fill stage off rewrites the bundle and so makes the
file stale. The fill stage always regenerates the file.

**It can never be loaded as a sidecar, in either direction.** `receipt_viewer._object` requires the
top-level key set to *equal* `{schema_version, pages, items}`; this document's key set is different
(it shares `schema_version` but carries no top-level `pages` or `items`), so `load_receipts` raises
on its first check —
asserted by a regression test that feeds the committed fictional example to the production loader.
Symmetrically, `link-receipts confirm` refuses a document carrying the sidecar's key set with a
named error, so a swapped `--proposals`/`--sidecar` pair fails loudly rather than half-merging.

---

## 5A. Interfaces, identifiers, and configuration

Everything a zero-context implementer needs that the prose above assumes. All example values are
fictional; the real allowlist and archive paths live only in gitignored `config.toml`.

### Dependencies

| Choice | Value | Why |
|---|---|---|
| Imaging | new extra `receipts = ["pillow>=12.2"]` in `pyproject.toml` | Pillow performed every measurement in § 2; no other dependency is added. Pillow is **already** a transitive core dependency through `matplotlib` (`uv.lock` pins `12.2.0`), so the extra adds no package: it pins the `>=12.2` floor the decoder was reviewed against, for unlocked installs. The floor is the reviewed, locked line. PNG/JPEG uploads are decoded in a capped child (§ 6.3) and the broker encodes the pixels it returns, so child and broker must run the same Pillow version (output is deterministic only under one build). The broker checks its own Pillow against the floor before the first spawn and compares the child's version on its **ready line**, before any asset byte is written; either failure is a stage abort (`ReceiptDecodeUnavailableError`), never N per-asset refusals. |
| HTTP | stdlib `urllib.request` | No new dependency, and this lane needs low-level control the convenience clients hide: redirects disabled per-hop, a capped `read(n+1)`, and no implicit retry. |
| PDF raster | reuse `pypdfium2>=5.13.0` from `[slides]` | Already present; adding a second raster library would duplicate the shape it decodes. |

### `[receipt_assets]` config block

Optional. Absent ⇒ the fill stage is a no-op and behavior is byte-identical to today. Present but
malformed ⇒ `ConfigError`, never a silent skip. Parsed by `_load_receipt_assets(raw)` following
`_load_receipt_mapping` (`config.py:284-307`) exactly: `None` for absent, `ConfigError` for
non-dict, paths through `_resolve_path`. Paths are resolved, never read, at config time.

```toml
# config.example.toml — FAKE values only; the real hosts are private
[receipt_assets]
enabled        = true                                    # bool, required
allowed_hosts  = ["cdn.example-forms.invalid",           # exact host
                  ".uploads.example-forms.invalid"]      # leading dot = label-boundary suffix
cache_dir      = "reports/output/.receipt-cache"         # path, required
pages_dir      = "reports/output/receipt-pages/auto"     # path, required
mail_root      = "mail_samples"                          # path, required when enabled = true
max_asset_mib  = 25                                      # int 1..25 (upper bound imported), default 25
timeout_s      = 30                                      # int 1..120, default 30
max_redirects  = 3                                       # int 0..5,   default 3
max_parallel   = 4                                       # int 1..8,   default 4
max_attempts   = 3                                       # int 1..5,   default 3
```

`max_asset_mib` is its **own** bound, not `receipt_viewer.MAX_PAGE_BYTES`: those two constants cap
rendered *pages*, and a 24 MiB source PDF can legitimately yield pages well under the page cap. The
25 MiB ceiling matches the worker's own `max_pdf_bytes` so a fetched asset can never exceed what the
renderer will accept. Its upper bound is not restated in `config.py`: the parser holds the
`receipt_geometry.NORMALIZATION` object and derives the MiB bound from its `max_source_bytes`
(26,214,400 bytes) at use, never storing a separate 25. That byte value is also the cap `to_pages`
applies when it reads any cached asset (§ 5A decode child), so the fetch cap and the read cap have
one source of truth. The renderer's own cap is a separate literal (`bank_statements.py:69`
`MAX_PDF_BYTES`, ceiling `:86` `_HARD_MAX_PDF_BYTES`): `bank_statements` is staged into the LPAC
and cannot import `receipt_geometry`, so `is` is impossible there, and Step 44 instead pins the
two together with a test asserting `NORMALIZATION.max_source_bytes <= bank_statements.MAX_PDF_BYTES`.
Backoff is `2**attempt` seconds, capped at 30.

Accepted asset types are exactly three magic-byte signatures — `%PDF-`, `\x89PNG\r\n\x1a\n`,
`\xff\xd8\xff`. Everything else is refused; `Content-Type` is never consulted.

### Module signatures

```python
# receipt_assets.py
@dataclass(frozen=True)
class AssetResult:
    url: str                 # the requested URL (never printed, never enters the sidecar)
    canonical_key: str       # normalized identity; see below
    asset_id: str | None     # "asset:v1:" + sha256 of the fetched BYTES; None when no bytes
                             # were accepted (every outcome except "fetched" and "cached")
    media_type: str | None   # "pdf" | "png" | "jpeg", decided by magic bytes (on a cache hit, by
                             # the cache file's extension, itself from magic bytes); None as above
    path: Path | None        # cache file, or None when no bytes were accepted
    byte_count: int          # 0 when no bytes were accepted
    outcome: str             # "fetched" | "cached" | "uncached" | "refused" | "unreachable"
                             # | "oversize" | "gone"
    detail: str              # short reason; a path or status class, never a URL or vendor string

def canonical_key(url: str) -> str: ...
    # THE one canonicalization (Identifiers); receipt_link imports it to number asset ordinals
    # before anything is fetched
def fetch_assets(urls, *, allowlist, cache_dir, max_bytes, timeout,
                 max_redirects, max_parallel, max_attempts,
                 offline: bool = False) -> list[AssetResult]: ...

# receipt_pages.py
@dataclass(frozen=True)
class PageImage:
    page_id: str; asset_id: str; asset_page: int
    path: Path; sha256: str; label: str
    width: int; height: int; scale: float

@dataclass(frozen=True)
class DecodeUsage:      # what the broker measured for one decode child (§ 5A calibration)
    peak_memory_bytes: int | None  # Windows: the child job's PeakProcessMemoryUsed (commit);
                                   # Linux: None — the calibration unit there is bisected RLIMIT_AS
    cpu_seconds: float   # Windows: job TotalUserTime (user time, what PerProcessUserTimeLimit counts);
                         # Linux: ru_utime + ru_stime delta of getrusage(RUSAGE_CHILDREN) across the
                         # reap (user + system, what RLIMIT_CPU counts); children run one at a time
    wall_seconds: float  # time.monotonic() from spawn to reap

@dataclass(frozen=True)
class PageProgress:     # passed to `progress` once per page, after the page is on disk
    page: PageImage; page_count: int
    source_width: int; source_height: int; orientation: int; byte_count: int
    decode_usage: DecodeUsage | None   # None for broker-derived PDF pages (no decode child)

class PageSource(Protocol):  # read-only asset_id, media_type, path (None = failed fetch)
    ...                      # AssetResult satisfies it structurally

PAGE_SUFFIX = ".jpg"

def to_pages(asset: PageSource, *, pages_dir: Path, ticket_ref: str, asset_ordinal: int,
             progress: Callable[[PageProgress], None] | None = None) -> list[PageImage]: ...

@dataclass(frozen=True)
class EncodedPage:
    data: bytes; width: int; height: int; scale: float   # scale of this step alone

def pixels_to_page(pixels: bytes, *, mode: Literal["L", "RGB"], width: int,
                   height: int) -> EncodedPage: ...
    # THE one pixels-to-page step for both producers: the image child's validated output
    # (Step 39) and the LPAC worker's validated gray8 render (Steps 43-44). Requires
    # len(pixels) == width * height * C; Image.frombytes; LANCZOS downscale only when
    # max(width, height) > NORMALIZATION.max_long_edge (never for child output); baseline JPEG.
    # The only Pillow calls that ever see producer output. Pillow is imported here, lazily.

# receipt_decode.py — run only as `-I -m pta_finance.receipt_decode`; protocol below
def main() -> int: ...  # one request on stdin -> one response on stdout; never imported to decode
def scaled_size(source_width: int, source_height: int, orientation: int,
                max_long_edge: int) -> tuple[int, int, float]: ...
    # stdlib-only; the ONE size/scale derivation — the child applies it, the broker imports it
    # to validate the response
EXIT_BUDGET = 3          # MemoryError at the top of main(); see "Exit status" below
EXIT_CHILD_ERROR = 4     # any other uncaught exception after the ready line

# process_limits.py — moved from native_sandbox.py; ctypes and stdlib only, imports no pta_finance
# Every `kernel32` argument is loaded by the caller as WinDLL("kernel32", use_last_error=True),
# through a getattr(ctypes, "WinDLL", None) loader like native_sandbox._windows_dll
# (native_sandbox.py:262-268), so Linux mypy never sees a Windows-only ctypes member and
# ctypes.get_last_error() yields the Win32 code ProcessLimitsError carries.
class ProcessLimitsError(OSError):
    handle: int | None   # a job handle the leaf created but could not close; caller now owns it
def make_job_object(kernel32, *, memory_bytes: int, cpu_seconds: int,
                    active_processes: int = 1) -> int: ...
def assign_process(kernel32, job: int, process_handle: int) -> None: ...
def is_process_in_job(kernel32, process_handle: int, job: int | None) -> bool: ...
def query_job_limits(kernel32, job: int | None) -> JobLimits: ...  # None = the caller's own job
    # JobLimits: limit flags, ActiveProcessLimit, process/job memory limits,
    # PerProcessUserTimeLimit and PeakProcessMemoryUsed, read via QueryInformationJobObject
def query_job_accounting(kernel32, job: int) -> JobAccounting: ...
    # JobAccounting: TotalUserTime and TotalKernelTime (100 ns units), read via
    # QueryInformationJobObject(JobObjectBasicAccountingInformation); the calibration CPU source
def terminate_job(kernel32, job: int) -> None: ...
def close_handle(kernel32, handle: int) -> bool: ...  # False on failure; never raises

# receipt_link.py
@dataclass(frozen=True)
class TicketUrls:
    urls: Mapping[str, tuple[str, ...]]      # review_key -> upload URLs in form order
    unjoinable: tuple[tuple[str, str], ...]  # (review_key, reason) for unjoinable_tickets[]

@dataclass(frozen=True)
class PageOutcome:      # one ledger page_outcomes[] row (§ 5A fetch ledger)
    review_key: str; asset_ordinal: int; canonical_key: str
    asset_id: str | None              # None only for "not-fetched"
    outcome: str                      # the closed page_outcomes[] vocabulary
    page_count: int; usage: DecodeUsage | None

class Proposals: ...     # the frozen in-memory form of the § 5 document, same exact key sets;
                         # tickets in display_order

@dataclass(frozen=True)
class MergeResult:      # what apply returns; the printed receipt summary (below) reads it
    items_linked: int         # items newly linked by this merge (0 when nothing was merged)
    pages_added: int          # pages newly entering the sidecar's pages[]
    linked_total: int         # items with a sidecar entry after the merge
    unlinked_total: int       # bundle item lines minus linked_total, as report-reimbursements counts
    headroom_bytes: int       # receipt_viewer.headroom_bytes(sidecar_path) after the merge
    backup_path: Path | None  # the prior sidecar's backup; None when none existed or nothing merged

# `report` is always reimbursement_report.ReimbursementReport (from load_bundle)
def receipt_urls_by_ticket(report: ReimbursementReport, *, mail_root: Path) -> TicketUrls: ...
    # read-only; writes nothing — its unjoinable tickets reach the ledger only through
    # record_fill_ledger
def fill_working_set(report: ReimbursementReport, urls: TicketUrls, *,
                     sidecar_path: Path) -> Mapping[str, tuple[str, ...]]: ...
    # review_key -> the FIRST URL per distinct canonical_key, in asset-ordinal order, for every
    # ticket with >= 1 unlinked item; fully linked tickets and later size-variant URLs are omitted
def record_fill_ledger(ledger_path: Path, *, page_outcomes: Sequence[PageOutcome],
                       unjoinable: Sequence[tuple[str, str]]) -> None: ...
    # THE writer of page_outcomes[] and unjoinable_tickets[] at <cache_dir>/fill-ledger.json:
    # read-modify-write under the exact top-level key set, rows updated in place by key,
    # and an outcome outside the closed vocabulary refused
def propose(report: ReimbursementReport, assets: Sequence[AssetResult],
            pages: Mapping[tuple[str, int], Sequence[PageImage]], *, mail_root: Path,
            sidecar_path: Path, existing: Path | None) -> Proposals: ...
    # pages keyed by (review_key, asset ordinal); builds the § 5 document in memory against the
    # current sidecar under § 5's membership rule, carrying edits across from `existing` and
    # refusing an irreconcilable one; writes nothing
def write_proposals(path: Path, proposals: Proposals) -> None: ...
    # THE writer of <bundle>.receipt-proposals.json: atomic replace; items already linked dropped
def apply(sidecar_path: Path, report: ReimbursementReport,
          confirmed: Proposals) -> MergeResult: ...
    # merges every confirmed item; an empty set writes nothing and returns items_linked and
    # pages_added of 0, with the totals and headroom still computed
```

**Cache lookup and offline mode.** Before opening any socket, `fetch_assets` looks each URL up in
the ledger. The `assets[]` row whose `url` equals the requested URL exactly and whose outcome is
`fetched` or `cached` gives an `asset_id`; if several rows match, the latest `last_seen` wins. If
`<cache_dir>/<asset_id hex>.<ext>` exists, the outcome is `cached`, `path` is that file, and no
socket opens. `to_pages` re-verifies those bytes against `asset_id` and records `digest-mismatch`
if they differ. On a miss, online mode fetches. With `offline=True`, no socket ever opens and a
miss is `uncached` (`path`, `asset_id` and `media_type` are `None`), which the page stage records
as `not-fetched`. The parameter belongs to Step 40; Step 46's `--fill-receipts-offline` only passes
`offline=True`.

`propose` takes `mail_root` explicitly — that is the parameter carrying the mail archive the
`review_key` → `.eml` join reads. It is not discovered and never defaults silently. The join
itself is `receipt_urls_by_ticket`: the fill stage calls it first to learn what to fetch, and
`propose` calls it again through `mail_root`. It is read-only and deterministic, so running it
twice is safe and both calls see the same URLs in the same order; the unjoinable tickets it returns
reach the ledger only through `record_fill_ledger`.

`to_pages` takes `ticket_ref` and `asset_ordinal` because the `page_id` is ticket context, not an
asset property: one upload's bytes can appear on two tickets, so `AssetResult` stays
transport-only and `receipt_assets` never imports `receipt_pages`. The asset ordinal is defined
under **Identifiers** below.

**The fill stage, in order.** Step 46 wires it inside `_cmd_update_reimbursements`, after the
refresh summary:

1. `receipt_urls_by_ticket(report, mail_root=…)` joins each ticket to its `Submission.receipt_urls`.
2. `fill_working_set` keeps only tickets with at least one unlinked item, so a fully linked ticket
   is never fetched or paged. For each kept ticket it keeps only the **first URL per distinct
   `canonical_key`**, in form order, which is the stateless asset-ordinal rule (Identifiers).
   Later size-variant URLs under the same key are never fetched.
3. `fetch_assets(…, offline=…)` resolves each kept URL as a cache hit, a network fetch or, offline,
   `uncached`. It writes the `assets[]` rows.
4. `to_pages` runs once per (ticket, asset ordinal), sequentially, so at most one decode child or
   PDF boundary is alive. It writes the pages to `pages_dir`.
5. `record_fill_ledger` receives every page outcome and unjoinable ticket once. This happens before
   any sidecar or proposals write, so a later merge refusal still leaves this run's outcomes for
   `link-receipts audit`.
6. `propose(…, sidecar_path=…, existing=<bundle>.receipt-proposals.json)` builds the § 5 document
   in memory against the current sidecar and carries operator edits across.
7. `apply(sidecar_path, report, <the auto-eligible tickets of that document>)` merges them. It runs
   the budget pre-check, then self-validates the merged candidate through the production
   `load_receipts` and `build_report` in a temporary location (never the live sidecar or HTML),
   then backs up the prior sidecar, then replaces the sidecar atomically. An empty auto-eligible
   set writes nothing.
8. `write_proposals` replaces `<bundle>.receipt-proposals.json` without the items step 7 linked.
   It is the file's one writer, and it writes on every completed stage run, with an empty
   `tickets` list when nothing awaits `confirm`.
9. The stage prints the receipt summary below from step 7's `MergeResult`.
10. The existing `build_report` call renders the HTML from the new sidecar.

A stage abort at any step applies the workspace rule below, so no proposals file or sidecar is
written. `link-receipts propose` runs the same order with `offline=True` in step 3 and without
step 7, so it opens no socket and never merges. `link-receipts confirm` runs § 5's stale-bundle
check, then step 7 over the file's confirmed items, then step 8's removal of the items it linked,
then step 9.

**Printed receipt summary.** After step 7 and after `confirm`, the command prints these
aggregate-only lines. Step 49's clauses (c), (d) and (g) read them. The fill stage prints all three,
with the counts and bytes filled in:

```text
  receipt assets : <fetched> fetched, <cached> cached, <uncached> uncached, <failed> failed
  receipt fill   : <items_linked> newly linked, <linked_total> linked, <unlinked_total> unlinked
  page budget    : <headroom_bytes, thousands-separated> bytes (<MiB, 2 dp> MiB) free of 104,857,600
```

`confirm` prints only the last two, with its first line beginning `link-receipts confirm:` in place
of `  receipt fill   :`. MiB is bytes ÷ 1,048,576. `<failed>` counts `refused`, `unreachable`,
`oversize` and `gone` together, and the private ledger path is printed beside it whenever it is
non-zero. The linked and unlinked totals are computed exactly as `report-reimbursements` computes
its `receipt links` line, so the two agree after a successful merge. A merge that links nothing
still prints `0 newly linked` and the headroom.

Every page — an
auto-linked one or a multi-asset ticket's candidate — is written to the one configured `pages_dir`,
so a candidate awaiting `confirm` is referenced only by the proposals file, which is why
`link-receipts audit` counts proposals references (Workspace state, below). A failed
fetch (`path is None`) yields zero pages. Output is byte-identical only under one Pillow/libjpeg
build, and a different file already holding a `page_id` is refused, never replaced — so callers
(Steps 45–46) must not re-normalize an asset whose pages a sidecar already references. Pages are
published by hard link, so `pages_dir` must be on a filesystem that supports hard links (NTFS,
ext4 — not FAT or exFAT). Pillow is imported lazily (in `pixels_to_page`), so importing
`receipt_pages` never loads it. Untrusted image bytes are decoded only in the decode child
(protocol below), whose stderr is discarded, so Pillow warnings for a hostile upload never reach
operator output.

**`process_limits` error contract.** A failing Win32 call in any leaf function raises
`ProcessLimitsError` (an `OSError` subclass carrying the Win32 error code) and nothing else — never a
caller's exception type — except `close_handle`, which reports failure by returning `False`, and
the queries, whose "no" answer is a value, not an error. On a non-Windows host the Windows
functions raise `ProcessLimitsError` without touching `ctypes.windll`, so the module imports
everywhere. **Argument validation:** `make_job_object` rejects `memory_bytes`, `cpu_seconds` or
`active_processes` below 1 before creating any handle, raising `ProcessLimitsError` with Win32 code
87 (`ERROR_INVALID_PARAMETER`), so a direct leaf caller can never create an unlimited job and the
contract still raises one type. `native_sandbox._make_job_object` keeps its own existing check
(`native_sandbox.py:725-726`) in front of the leaf, so its argument refusal is unchanged. When
`make_job_object` fails after creating the job, it closes the handle itself; only if that
`CloseHandle` also fails does it set `ProcessLimitsError.handle`, and the caller then owns the
handle. **Mapping at every call site:** `native_sandbox` maps `ProcessLimitsError` to
`NativeSandboxUnavailable` wherever it calls the leaf — `_make_job_object`, which also passes a
carried handle to its existing `_defer_sandbox_process`, and the attestation at
`native_sandbox.py:1427-1442`, which raises `NativeSandboxUnavailable` both on a raised error and
on a "no" answer, as it does today — so `_launch_worker`, `bank_statements.py:4105` (which catches
only `NativeSandboxUnavailable`) and the native suites see identical behavior. `receipt_pages` maps it to
`ReceiptDecodeUnavailableError` and keeps a carried handle referenced until the stage ends (no
process is in that job, so nothing is left running). `make_job_object`'s `active_processes`
defaults to 1, the value every production caller uses; only the § 9 outer test harness passes 2, so
the broker inside it can start its decode child. `native_worker.py` keeps its own copy of the flags
and structures because the staged worker allowlist excludes this leaf (§ 4); a parity test pins the
two copies together.

### Identifiers

| Identifier | Format | Generated by | Used by |
|---|---|---|---|
| `review_key` | `submission:v1:<64 lowercase hex>` — sha256 of the **raw** `Message-ID` header after `.strip()`, **never** the normalized form (`normalize_message_id` lowercases the domain and feeds a different field); or `legacy:v1:<ref>[:<form>]` | `_review_key` at `reimbursement_pipeline.py:140-142`, called at `:266`/`:273` | the ticket↔`.eml` join; sidecar item entries |
| `item_key` | opaque stable string minted by the pipeline per review line; treated as an exact token, never parsed | `reimbursement_pipeline` | refusal keys, proposals items, sidecar entries |
| `source_index` | 1-based index of the line **as submitted on the form**, not its list offset | the bundle | proposals ordering; never used to guess an asset |
| `asset_id` | `asset:v1:<64 lowercase hex>` — sha256 of the **fetched bytes**; `null` in a ledger row whose fetch accepted no bytes | `receipt_assets` | cache filename stem, page provenance |
| `canonical_key` | `<lowercased host><path>`, query string and fragment discarded | `receipt_assets.canonical_key(url)`, the one canonicalizer, which `receipt_link` imports | the one-asset gate (so two CDN size-variants of one file count once), and the ledger's per-asset row |
| asset ordinal | 1-based position of an asset's `canonical_key` among that ticket's distinct canonical keys, in `Submission.receipt_urls` order (first occurrence wins). **Stateless:** the asset for (ticket, ordinal) is always the bytes fetched from the first URL in form order under that canonical key; if that fetch fails, the ordinal yields zero pages this run. No later URL or size variant ever stands in, so no ledger or proposals state is needed and a different variant can never reach an existing `page_id`. `to_pages` raises a plain `ValueError` (never a recorded `ReceiptPageError`) for an ordinal that is not a positive integer, so an off-by-one fails loudly | `receipt_link` (Step 45) | `page_id`, proposals `assets[].ordinal` |
| `page_id` | `<ticket ref>-a<asset ordinal>-p<page number>`, unique within the sidecar; the ref must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` | `receipt_pages.to_pages`, from its `ticket_ref` and `asset_ordinal` arguments | the proposals↔sidecar join key |
| `item_sha256` | 64 lowercase hex from `receipt_viewer.item_fingerprint(ticket, item)` — **called, never re-derived** | `receipt_viewer.py:28` | staleness detection |
| cache filename | `<asset_id hex>.pdf` / `.png` / `.jpg` — extension from magic bytes | `receipt_assets` | idempotent re-fetch |

`asset_id` and `canonical_key` answer different questions and both exist deliberately: identity of
*bytes* (dedup the cache, prove provenance) versus identity of *the upload* (count a ticket's
distinct receipts). Neither substitutes for the other.

### The auto-commit rule, stated exactly

A ticket is auto-eligible when **all** of these hold; otherwise its unlinked items wait in the
proposals file for `confirm` (§ 5 membership):

1. Its receipt assets — the submission's upload URLs; MIME attachments are out of scope for this
   phase per § 3 — have exactly **one** distinct `canonical_key`.
2. That asset produced **at least one** page. A 404, an oversize refusal, a decode refusal, or a PDF
   on a host the recorded PDF boundary does not support (non-Windows for the LPAC; whatever
   `docs/findings/step-42-pdf-boundary.md` says if Step 42 ran) yields zero pages, so the
   ticket is reported unlinkable rather than auto-linked.
3. **No item on the ticket already has a sidecar entry.** Existing links are never re-linked,
   re-hashed, or touched — this is what protects the human-verified entries (190 as of
   2026-10-09).

When it holds, every item on that ticket gains one region **per page of that one asset**, each with
`box: null`. A three-page PDF therefore links all three pages and the viewer offers page navigation.

`box: null` from this stage means "this is the ticket's only uploaded receipt". A human-placed box
means "this exact line was identified". The two are distinguishable because only a human writes a
non-null box, and the merge refuses to overwrite one.

### The sidecar entry this stage emits

```json
{"review_key": "submission:v1:<64 hex>", "item_key": "<exact item key>",
 "item_sha256": "<64 hex>", "regions": [{"page_id": "EX-01-a1-p1", "box": null}]}
```

`pages[].path` is relative to the **sidecar's own directory** — that is what `receipt_viewer`
enforces — so a page under `receipt-pages/auto/` has `path: "receipt-pages/auto/EX-01-a1-p1.jpg"`.
The proposals document's `page_root` is the configured `pages_dir` relative to that same directory
(`receipt-pages/auto` in the example), because candidate and auto-linked pages share the one
`pages_dir`; it is advisory context for the operator and is never joined to `path`. Only pages referenced by a merged region may enter `pages[]`; the merge prunes the rest,
because `load_receipts` refuses an unreferenced page.

### The fetch ledger

`<cache_dir>/fill-ledger.json` — private, gitignored, the per-asset triage surface behind the run's
aggregate counts, where every page outcome (including each decode refusal and child error) is
recorded, and where an unjoinable ticket is recorded.

```json
{"schema_version": 1, "updated_at": "2026-01-02T03:04:05Z",
 "assets": [{"url": "https://cdn.example-forms.invalid/u/abc?v=2", "canonical_key": "cdn.example-forms.invalid/u/abc",
             "asset_id": "asset:v1:<64 hex>", "media_type": "pdf",
             "outcome": "fetched", "byte_count": 128904, "attempts": 1,
             "first_seen": "2026-01-02T03:04:05Z", "last_seen": "2026-01-02T03:04:05Z",
             "detail": ""},
            {"url": "https://cdn.example-forms.invalid/u/def", "canonical_key": "cdn.example-forms.invalid/u/def",
             "asset_id": null, "media_type": null,
             "outcome": "gone", "byte_count": 0, "attempts": 1,
             "first_seen": "2026-01-02T03:04:05Z", "last_seen": "2026-01-02T03:04:05Z",
             "detail": "status 404"}],
 "page_outcomes": [{"review_key": "submission:v1:<64 hex>", "asset_ordinal": 1,
                    "canonical_key": "cdn.example-forms.invalid/u/abc", "asset_id": "asset:v1:<64 hex>",
                    "outcome": "budget", "page_count": 0,
                    "usage": {"peak_memory_bytes": 1610612736, "cpu_seconds": 2.5, "wall_seconds": 3.1},
                    "last_seen": "2026-01-02T03:04:05Z"}],
 "unjoinable_tickets": [{"review_key": "legacy:v1:P-900", "reason": "no archived message for this key"}]}
```

`assets[].outcome` is exactly the `AssetResult.outcome` vocabulary. `page_outcomes[].outcome` is
exactly one of `paged`, `not-fetched` (the asset's fetch accepted no bytes, or offline it was
not cached; its `assets[]` row says why),
`too-large`, `unreadable`, `too-many-pixels`, `source-edge`, `unsupported-mode`, `animated`,
`budget`, `child-error`, `failed-validation`, `digest-mismatch`, `pdf-not-rendered`,
`pdf-too-many-pages`, `pdf-page-too-large`, `pdf-render-failed`, `pdf-render-invalid`,
`bad-ticket-ref` and `conflict` — one value per `ReceiptPageError` class below, which carries it
as its `reason` attribute so the writer never parses a message. The image child's refused response
is `failed-validation` and the PDF boundary's is `pdf-render-invalid`, so the two boundaries'
misbehaviour is never pooled. `asset_id` is `null` only for
`not-fetched`; `usage` is the broker's `DecodeUsage` for that asset (carried on `PageProgress` for a
page and on `ReceiptPageError.usage` for a child-side refusal) or `null` when no child ran. The
ledger holds URLs because it is private; nothing from it reaches the sidecar, and stdout carries
only what `link-receipts audit` prints (counts, ticket refs, asset ordinals and outcomes — never a
URL).

**Ownership:** `receipt_assets` writes `assets[]`; `receipt_link` writes `unjoinable_tickets[]` and
`page_outcomes[]` through `record_fill_ledger` (the fill stage hands it each `to_pages` result or
refusal as a `PageOutcome`). Both
read-modify-write the whole file under the exact top-level key set
`{schema_version, updated_at, assets, page_outcomes, unjoinable_tickets}`, so each must emit the
lists it does not own (as empty lists) when it creates the file. `assets[]` rows are keyed by
`(canonical_key, asset_id)` — a canonical key can legitimately carry more than one byte-digest
across CDN variants. A row for a fetch that accepted no bytes has `asset_id` and `media_type`
`null` and is keyed `(canonical_key, null)`: there is one such row per canonical key, updated in
place by the latest failed or `uncached` attempt, and a later success adds its own
`(canonical_key, asset_id)` row beside it. The cache lookup (Module signatures) reads these rows.
`page_outcomes[]` rows are keyed by `(review_key, asset_ordinal)`, because a
conflict or a bad ticket ref is per ticket even when two tickets share one asset. A re-run updates
`last_seen`/`attempts` (or the page outcome) in place rather than appending a duplicate.
`link-receipts audit` prints the page-outcome counts and every non-`paged` row, so Step 46's audit
and Step 49's triage read decode refusals from this one place.

### Errors and the raise-vs-record boundary

Exception types: `ReceiptAssetError` (transport and validation), `ReceiptLinkError` (merge
refusals and irreconcilable proposals edits, with its subclass `ReceiptProposalsStaleError` for a
`confirm` against a changed bundle, § 5), the PDF render refusals that `bank_statements.py`
raises (the `ReceiptRenderError` subclasses in the LPAC section below, which `receipt_pages` maps
to their ledger values), and in `receipt_pages` `ReceiptPageError` (a per-asset normalization refusal carrying
`reason`, its ledger `page_outcomes[]` value, and `usage`, the child's `DecodeUsage` or `None`; its
subclass `ReceiptPageConflictError` means a different page file already holds the `page_id`) and
`ReceiptPagesDirectoryError` (the pages directory cannot be written; deliberately **not** a
`ReceiptPageError`, so a record-and-continue handler cannot swallow it), and
`ReceiptDecodeUnavailableError(RuntimeError)` (the decode child cannot be started or limited;
deliberately **not** a `ReceiptPageError`, for the same reason, and deliberately neither an
`OSError` nor a `ValueError`, so no transport or validation handler can swallow it — the same base
as `NativeSandboxUnavailable`, `native_sandbox.py:83`), and its PDF counterpart
`ReceiptRenderUnavailableError(RuntimeError)` (the PDF boundary cannot be started on a host it
supports; not a `ReceiptPageError`, an `OSError` or a `ValueError`, for the same reasons). Each follows the message
discipline of `gmail_source` — paths and remediation only, never a URL, requestor, vendor or
subject.

**Recorded, never raised:** any per-asset outcome — unreachable, oversize, wrong magic bytes,
disallowed redirect target, 404. One bad asset never aborts the batch. `receipt_pages` raises
`ReceiptPageError` for its per-asset outcomes, each named here by its ledger value: source file
larger than `NORMALIZATION.max_source_bytes` (`too-large`), undecodable image (`unreadable`), too
many pixels (`too-many-pixels`), source edge too long (`source-edge`), unsupported pixel format
(`unsupported-mode`), animated PNG (`animated`), **exceeded the decode budget** (`budget`),
**decode child error** (`child-error`), a decode response that fails validation
(`failed-validation`), a cached asset whose bytes no longer match its `asset_id`
(`digest-mismatch`), a PDF on a host the recorded PDF boundary does not support, cached and counted
as needing manual export (`pdf-not-rendered`), a PDF over Step 44's page-count ceiling, refused
whole and never truncated (`pdf-too-many-pages`), a PDF page outside Step 43's render dimension gate
(`pdf-page-too-large`), a render the started boundary could not complete — a PDF it cannot parse, or
a worker ended by its own limits (`pdf-render-failed`), a render response that fails the
broker validation (Step 41 lands it, Step 43 completes it) — malformed, bomb-shaped (the bounded decompression overruns or leaves leftover
bytes), wrong-length or digest-mismatched (`pdf-render-invalid`), ticket ref outside the `page_id`
grammar (`bad-ticket-ref`), and page conflict (`conflict`). The child-side ones are mapped exactly
as "Exit status" below states. The stage catches each and records it in the ledger's
`page_outcomes[]` (above) against that ticket and asset. The run's aggregate output counts
budget refusals and child errors **separately**, so a systemic child bug shows as N child errors,
never as N budget refusals (pinned by § 9's direct exit-status mapper test). An invalid `asset_ordinal` is a caller bug,
not an outcome: it raises `ValueError` and must never be caught as a per-asset refusal.
**Raised, aborting the stage before `build_report`:** malformed config, an unwritable cache or
pages directory, or one without hard-link support (`ReceiptPagesDirectoryError`), a **decode child
that cannot start** (`ReceiptDecodeUnavailableError`) — an unsupported host (see "Supported hosts"
under the decode child below), a
broker Pillow older than the `receipts` floor, a child that cannot be spawned, whose limits cannot
be applied or confirmed, whose ready line is late, malformed, from a different pid, reports a
different Pillow version, or (Linux) reports an `rlimit_as` outside its band — a **PDF boundary
that cannot start** on a host it supports (`ReceiptRenderUnavailableError`; for the LPAC,
`start_native_pdf_worker` raising `NativeSandboxUnavailable` because launch or attestation failed;
under a recorded Step 42 boundary, that boundary's own start failure), an irreconcilable
proposals edit (§ 5), and every merge
refusal (unknown key, stale fingerprint, attempted override of a human-verified box, duplicate
entry, budget crossing). A merge refusal aborts the **whole merge** — never a partial sidecar.
**The PDF abort/refusal boundary is the started boundary**, mirroring the decode child's accepted
ready line: a failure before the boundary has started and attested aborts the stage once, never as
N per-asset refusals for one systemic fault; once it has started, every failure is a per-asset
`ReceiptPageError` from the list above. The receipt render path therefore never reuses the statement
path's catch at `bank_statements.py:4105`, which turns a worker-start failure into a page error; it
lets `NativeSandboxUnavailable` from the start reach `receipt_pages`, which maps it to
`ReceiptRenderUnavailableError`.

**Workspace state after a stage abort.** The stage tracks the page files it newly created during
the current run (a `page_id` whose identical file already existed is not one of them). On any stage
abort it unlinks exactly those files before re-raising, writes no
proposals file and no sidecar, and leaves the asset cache and fetch ledger in place (their
contents are still true). An abort after asset *k* therefore leaves `pages_dir` as it was before
the run, so a later Pillow move cannot turn an orphan from the aborted run into a permanent
`ReceiptPageConflictError`. Files a killed process left behind (no cleanup ran) are listed by page
id by `link-receipts audit` as unreferenced page files for the operator to delete; they are never
silently replaced. **Unreferenced** means referenced by neither the sidecar's `pages[]` nor a
`candidates[]` entry of the current proposals file, so a multi-asset ticket's candidate page
awaiting `confirm` is never listed for deletion.

### The LPAC render request and response

Both sides validate by exact key-set equality, so the field names are part of the contract.

**The existing envelope.** The broker passes one JSON object of bounded ints on the worker's
command line (`_serialize_native_limits`). The worker re-validates it with
`_deserialize_native_limits` (`bank_statements.py:1065-1084`): its key set must equal
`_NATIVE_LIMIT_FIELD_CEILINGS` (`:1040-1052`), and every value must be an int from 1 to its
`_HARD_MAX_*` ceiling. Today it has eleven fields, each with a public value (`:69-80`) equal to its
ceiling (`:85-95`): `max_pages` 25, `max_transaction_rows` 2,500, `max_pdf_bytes` 25 MiB,
`max_characters` 2,000,000, `max_rendered_pixels_per_page` 20,000,000, `max_tokens_per_page`
25,000, `max_lines_per_page` 10,000, `max_wire_bytes` 16 MiB (the response frame cap),
`wall_seconds` 15, `worker_memory_bytes` 512 MiB and `worker_cpu_seconds` 10. One launch serves
one request. After the worker's `{"status":"ready","nonce":…}` frame, the broker sends the PDF as
one frame of at most `max_pdf_bytes` and reads one response frame. Extraction answers
`{"status":"ok","pages":[…]}`, `{"status":"rejected"}`, `{"status":"rejected","page_number":N}` or
`{"status":"failed"}` (`:3736`, `:3826`, `:4041`, `:4051`).

**New envelope fields (Step 41 adds what its spike needs; Step 43 completes them).** Six ints join
`_NATIVE_LIMIT_FIELD_CEILINGS`, so every request carries all seventeen, extraction included. The
statement path and the render path each fill the new fields from their public constants:

| field | public value | `_HARD_MAX_*` | meaning |
|---|---|---|---|
| `operation` | 1 (extraction) or 2 (render) | 2 | **The request selector.** For 1 the worker runs statement extraction, today's behavior, and ignores the render fields the request carries. For 2 it runs the receipt render. The operation is never inferred from any other field. |
| `render_page_first` | set per launch by the broker | 25 | the 1-based page this launch renders |
| `render_page_count` | 1 | 1 | **one page per launch**, so each page gets the whole `worker_cpu_seconds` and its own response frame |
| `render_scale_permille` | 2,778: 200 DPI (200/72), so US Letter renders at exactly 1,700 × 2,200, the normalization long edge | 4,167 (300 DPI, the statement path's resolution) | pixels per PDF point × 1,000; width and height = the page size in points × `render_scale_permille` / 1,000, rounded half up |
| `max_render_raw_bytes_per_page` | 12,000,000 | 12,000,000 | gray8 bytes, which equals pixels, of one rendered page |
| `max_render_wire_bytes` | 16 MiB | 16 MiB | the render response frame cap (the `recv_bytes` limit), equal to `max_wire_bytes` |

`max_render_raw_bytes_per_page` is derived as the largest page whose worst-case wire form fits one
16 MiB frame. zlib's `deflateBound` for 12,000,000 bytes is 12,003,674 (12,003,671 measured on
random bytes), base64 makes that 16,004,900, and with a JSON header of at most 1 KiB the frame
stays under 16,777,216. It is also below the existing `max_rendered_pixels_per_page`
(20,000,000).

**Render dimension gate (Step 43).** A page passes only when, at the request's scale,
`1 ≤ width, height ≤ RENDER_MAX_EDGE` and `width × height ≤ max_render_raw_bytes_per_page`.
`RENDER_MAX_EDGE = 65_535` is a `bank_statements.py` literal equal to
`NORMALIZATION.max_source_edge`; `bank_statements.py` cannot import `receipt_geometry`, so Step 44
pins the two with an equality test. The edge bound keeps `pixels_to_page`'s in-broker LANCZOS
downscale of a long, thin PDF page within the cost measured for uploads at that edge (about 3 MiB,
Exit status caveat below). The worker applies the gate from the page's size in points **before**
it allocates a bitmap, so a refused page costs no render, and the broker re-applies it to every
response's `width` and `height`. The gate replaces `_page_dimensions`' US-Letter-only rule on this
path; the statement path keeps that rule.

**Page count and launch granularity (Steps 43–44).** The page-count ceiling is the existing
`max_pages`, 25. Every render launch opens the document, and the worker refuses it whole, before
rendering anything, when its page count exceeds `max_pages`. The broker launches page 1 first.
That response carries the document's `page_count`, and the broker then launches pages 2 to
`page_count` one at a time. Every response must report the same `page_count` and the
`page_number` its launch asked for. A PDF over the ceiling therefore yields zero pages without
rendering one.

**Responses.** Each is ASCII JSON in one frame, with an exact key set per `status`. A rendered page
(`pages` holds exactly `render_page_count` = 1 entry):

```json
{"status": "rendered", "page_count": 2,
 "pages": [{"page_number": 1, "width": 1700, "height": 2200, "format": "gray8",
            "raw_sha256": "<64 hex>", "raw_length": 3740000, "zlib": "<base64>"}]}
```

| worker outcome | exact response | broker raises | ledger value (Step 44) |
|---|---|---|---|
| more pages than `max_pages` | `{"status": "rejected", "reason": "too-many-pages"}` | `ReceiptRenderTooManyPagesError` | `pdf-too-many-pages` |
| a page outside the gate | `{"status": "rejected", "reason": "page-too-large", "page_number": N}` | `ReceiptRenderPageTooLargeError` | `pdf-page-too-large` |
| a document pdfium cannot open or render (corrupt or encrypted) | `{"status": "rejected", "reason": "unreadable"}` | `ReceiptRenderFailedError` | `pdf-render-failed` |
| any other worker-side exception (the existing `_send_worker_failure` frame) | `{"status": "failed"}` | `ReceiptRenderFailedError` | `pdf-render-failed` |
| no frame: the worker was ended by its own Job limits, or the broker's `wall_seconds` passed | — | `ReceiptRenderFailedError` | `pdf-render-failed` |
| anything else: an unknown `status` or `reason`, a wrong key set or type, a bomb-shaped or leftover-bearing `zlib`, a decompressed length that differs from `raw_length` or from `width × height`, a digest mismatch, a `width` or `height` outside the gate, or a `page_count` or `page_number` that disagrees with the launch | — | `ReceiptRenderInvalidError` | `pdf-render-invalid` |

All four errors subclass `ReceiptRenderError(Exception)` in `bank_statements.py`. Step 41 lands
the base class with its spike, and Step 43 adds the four subclasses. They carry no
message beyond their ledger value, and none is a `StatementExtractionError`. A worker that cannot
start or attest raises `NativeSandboxUnavailable` out of the entry point unchanged; `receipt_pages`
maps it to the stage abort `ReceiptRenderUnavailableError` (Errors above).

**The broker entry point (Step 43 builds it; Step 44 calls it).** Step 41's spike already lands
`RenderedPage`, `RENDER_SCALE_PERMILLE` and the validated single-page frame reader. Step 43
builds `render_receipt_pdf` and `RENDER_MAX_EDGE` on top of them.

```python
# bank_statements.py, broker side
@dataclass(frozen=True)
class RenderedPage:
    page_number: int; width: int; height: int
    pixels: bytes          # validated raw gray8; len(pixels) == width * height; row-major, top row first

RENDER_SCALE_PERMILLE = 2778
RENDER_MAX_EDGE = 65_535

def render_receipt_pdf(pdf: bytes, *, on_page: Callable[[RenderedPage], None],
                       scale_permille: int = RENDER_SCALE_PERMILLE) -> int: ...
    # Renders pages 1..page_count, one LPAC launch per page (render_page_first = k,
    # render_page_count = 1), calling on_page with each validated page in order; returns
    # page_count. Input is the PDF bytes the broker already read under max_source_bytes (it never
    # opens a path), at most max_pdf_bytes. Raises a ReceiptRenderError subclass (table above) or
    # NativeSandboxUnavailable, never StatementExtractionError.
```

Step 44's `to_pages` passes each page's pixels to `pixels_to_page` inside `on_page` and keeps the
encoded pages in memory. It writes the page files only after `render_receipt_pdf` returns, so a
refusal on any page leaves zero pages for the asset. For a PDF page, `PageProgress.source_width`
and `source_height` are the rendered `width` and `height`, `orientation` is 1 (no EXIF applies),
`byte_count` is the asset's byte count as for an image, and `decode_usage` is `None`.

Grayscale is deliberate: receipts are read for their *text*, the viewer draws its own red outline
over the page, and gray8 is a third of BGRA on the wire — which matters against a 16 MiB frame cap
and a 10-second worker CPU limit. Color is not evidence here; legibility is.

### The image decode child request and response

Every PNG/JPEG asset is decoded by a fresh child running `-I -m pta_finance.receipt_decode`, never
by the broker (§ 6.3). The shape mirrors the LPAC render protocol above — limits travel in the request,
the child returns raw pixels, the broker re-derives everything it is sent — so the child can later
move into the attested worker unchanged. The child imports only the standard library, Pillow
(inside `main()`) and the stdlib-only `process_limits` leaf, and reads every value it applies from
the request, so a test that lowers a limit with `dataclasses.replace` still reaches the real child
(§ 9's outer harness applies such overrides inside its own process, where `to_pages` builds the
request). There is **no in-process seam**: no flag, environment variable or private helper decodes untrusted
bytes in the broker, and tests drive the real child (§ 9) — the Step 40 "opener seam" trap applied
to decoding. The one permitted exception is narrow: the broker's ready-line and response validator,
its capped stdout reader and its exit-status mapper are tested **directly** on crafted bytes or
crafted exit outcomes (§ 9 names the cases), because they parse JSON, count bytes or map an exit
status but decode no image, so no input that only a misbehaving child could produce goes untested —
including exit `EXIT_CHILD_ERROR`, which no crafted image can make the real child produce.

**Supported hosts.** Before any spawn the broker checks `sys.platform` against the explicit
allowlist `{"win32", "linux"}` and raises `ReceiptDecodeUnavailableError` otherwise. The allowlist
is needed because the child's read-back cannot detect an unenforced limit: macOS accepts and
reports `RLIMIT_AS` without enforcing it, so a read-back there would attest a limit that does not
exist. A test monkeypatches `sys.platform` to `darwin` and asserts the abort happens before any
spawn.

**Before the spawn.** `to_pages` `stat()`s the cached asset and reads it with
`read(max_source_bytes + 1)`, refusing a larger file per asset ("source file too large") before any
child exists. Step 40's fetch cap bounds downloads, but a hand-placed or offline-cache file reaches
`to_pages` directly, and without this cap the broker's own read, digest and pipe write would be
unbounded. Decode cost is bounded by the child; the broker's read is bounded only by this cap.

**Launch: one process, minimal environment.**

- **One process.** On Windows the uv venv's `python.exe` is a launcher that starts a *second*
  interpreter process (measured: the `Popen` pid differs from the pid the interpreter reports, and
  that interpreter's parent is the launcher). A Job assigned to the `Popen` handle would hold the
  launcher while the decoder ran outside it, and a Job applied before the launcher starts its
  interpreter would hit `ActiveProcessLimit = 1`. The broker therefore launches the **base**
  interpreter directly, `[sys._base_executable, "-I", "-m", "pta_finance.receipt_decode"]`, with
  `__PYVENV_LAUNCHER__ = sys.executable` in its environment so it resolves the venv's `sys.prefix`
  and site-packages (the pattern `multiprocessing` uses on Windows). `Popen.pid` is then the
  decoding interpreter's own pid. On Linux, `[sys.executable, "-I", "-m", ...]` is already one
  process. **Typing:** `sys._base_executable` and `Popen._handle` are absent from mypy's typeshed,
  so the broker reads both through `getattr` with a runtime type check (or opens the process
  handle with `OpenProcess` from `Popen.pid`), following the `native_sandbox._windows_dll` pattern
  (`native_sandbox.py:262-268`), and loads `kernel32` as `WinDLL("kernel32", use_last_error=True)`
  through that same kind of loader, so `mypy --strict` passes on both hosts.
- **Creation flags (Windows):** `CREATE_NO_WINDOW`, matching `native_sandbox`'s own worker launch
  (`native_sandbox.py:1596-1599`), so no console window flashes per asset.
- **Environment:** explicit and minimal, never inherited. Windows:
  `{"SYSTEMROOT": <the Windows directory from Win32>, "__PYVENV_LAUNCHER__": sys.executable}`.
  Linux: empty. No credential, token path or configuration variable reaches the child.
- **Working directory:** a fresh, empty temporary directory. It is removed only after the broker
  has reaped the child (Linux: after `wait()`; Windows: after the process handle is signalled),
  because a terminated process can still hold it briefly. A removal failure is counted in the
  run's aggregate output as a cleanup warning and never raised: the directory never held an asset
  byte, which arrives over stdin.
- **Streams:** stdin and stdout are pipes opened in binary mode, and stderr is `DEVNULL`; no other
  handle is inherited (`close_fds=True`).
- **Linux process group:** `start_new_session=True`. On every exit path (wall clock, validation
  failure, normal exit) the broker sends `SIGKILL` to the whole group with `os.killpg` **before** it
  reaps the child — the unreaped child keeps its process-group id reserved, so the signal can never
  reach a reused id — and tolerates `ProcessLookupError` (`ESRCH`) when the group is already empty.
  A forked descendant therefore cannot outlive the child or escape the wall clock. On Windows,
  `ActiveProcessLimit = 1` forbids any descendant inside the Job; a process started outside it
  under code execution is part of the § 6.3 residual.

**Order: attest before bytes.**

1. The broker spawns the child (above). On Windows it creates a fresh Job Object with
   `process_limits.make_job_object` (process and job memory `memory_bytes`,
   `PerProcessUserTimeLimit` `cpu_seconds`, `ActiveProcessLimit = 1`, kill-on-close,
   die-on-unhandled-exception), assigns the child with `assign_process`, and confirms
   `is_process_in_job` on the child's handle. Assigning after the spawn is safe only because the
   child is one process and blocks reading stdin: it reads nothing until the broker writes the
   request line, which happens only after the assignment is confirmed. (`native_sandbox` instead
   creates its worker suspended with the job attached through `PROC_THREAD_ATTRIBUTE_JOB_LIST` and
   then resumes it — `native_sandbox.py:1596`, `:1652-1658`, `:1708` — because that worker has no
   stdin to block on.)
2. The broker writes the request line. The child reads that one line (at most 4 KiB), refuses a
   `byte_count` above `max_source_bytes`, sets `Image.MAX_IMAGE_PIXELS` from `max_source_pixels`
   (so Pillow's own bomb check moves with the request), and applies and **self-attests** its
   limits:
   - **Windows:** `process_limits.query_job_limits(None)` reads the child's own job, which must
     show the required limit flags, `ActiveProcessLimit == 1`, process and job memory equal to
     `memory_bytes`, and `PerProcessUserTimeLimit` equal to `cpu_seconds`; and
     `is_process_in_job` on the current process must be true. This is the check
     `native_worker._job_limits_match` already performs inside the LPAC (`native_worker.py:566-594`).
   - **Linux:** the child reads its own `VmSize` from `/proc/self/status` as the interpreter
     baseline that `RLIMIT_AS` also counts, sets `RLIMIT_AS = memory_bytes + baseline` and
     `RLIMIT_CPU = cpu_seconds`, each with soft = hard so it cannot raise them later, and reads
     both back with `getrlimit`.

   Only then does it write its ready line, one ASCII JSON line (at most 256 bytes) with exactly the
   keys `{"status": "ready", "protocol": "receipt-decode/1", "pid": <os.getpid()>, "pillow": "<PIL.__version__>"}`
   on Windows, and on Linux exactly those keys plus `"rlimit_as": <the RLIMIT_AS it applied and read
   back>`. Only the child knows its baseline, so `rlimit_as` is how the broker and the § 9 pid test
   learn the applied limit. A failed attestation exits non-zero with no ready line.
3. The broker requires the ready line within `ready_seconds`, with `pid` equal to `Popen.pid` (the
   process it put in the job), `pillow` equal to its own Pillow version, and, on Linux,
   `memory_bytes <= rlimit_as <= memory_bytes + NORMALIZATION.max_as_baseline`. `max_as_baseline`
   is pinned at 256 MiB and, like `wall_seconds`, never leaves the broker. For scale: `python3 -I`
   with the standard-library modules the child imports measured a 23 MiB `VmSize` (WSL, Python
   3.12.3, before Pillow loads). Step 39 records the Pillow-loaded baseline on the `lint-type-test`
   runner in its checkpoint, and the bound must stay at least 4× that reading. Only then does
   it write exactly `byte_count` asset bytes and close stdin. No untrusted byte reaches the child
   before its limits hold. **The abort/refusal boundary is the accepted ready line:** every failure
   before the broker accepts it (spawn, job assignment, attestation, a late, malformed, mismatched
   or out-of-band ready line) raises `ReceiptDecodeUnavailableError` and aborts the stage; once it
   is accepted, every failure — including a `BrokenPipeError` on the first body write — is a
   per-asset `ReceiptPageError`.
4. One broker wall clock, `wall_seconds`, runs from spawn to exit. When it passes, the broker kills
   the child: on Windows by terminating its job, on Linux by killing its process group.
   **Precedence with the ready deadline:** until the broker accepts the ready line, the effective
   deadline is `min(ready_seconds, wall_seconds)` and its expiry is a late ready line — a stage
   abort under step 3's boundary, never a budget refusal; only after acceptance does the wall clock's
   expiry become the per-asset **exceeded the decode budget**. A test that lowers `wall_seconds`
   must therefore keep it above the child's start time (§ 9 wall-clock sentinel).

**Wire rules for all three lines (request, ready, response).** Each is one ASCII JSON object
terminated by exactly one LF (`\n`), read and written on the binary streams (`sys.stdin.buffer`,
`sys.stdout.buffer`, binary `Popen` pipes), never text mode, so Windows can never emit CRLF.
Each side parses with `object_pairs_hook` refusing a duplicate key (as for proposals, § 5) and
`parse_constant` refusing `NaN`, `Infinity` and `-Infinity`, then checks the exact key set and every
value's type. **Types:** an *int* field must satisfy `type(value) is int` — a `bool` (`True == 1`) and
a float (`1650.0 == 1650`) are both refused, as `bank_statements.py:977` already does for its own
ints; a *float* field must satisfy `type(value) is float` and be finite; a *string* field must be
ASCII from the closed set given; `background` is a list of exactly three ints in 0–255. **Caps:**
request 4 KiB, ready line 256 bytes, response header 1 KiB. A type or cap failure on the request
(child side) or the ready line is a stage abort under step 3's boundary; on the response it is a
per-asset **failed validation**.

**Request line.** Validated by exact key-set equality:

| Key | Type | Value |
|---|---|---|
| `protocol` | string | `"receipt-decode/1"` |
| `media_type` | string | `"png"` or `"jpeg"`; selects exactly one Pillow plugin, with no fallback |
| `byte_count` | int | exact length of the asset body the broker writes after the ready line |
| `max_source_bytes` | int | source-byte cap; the child refuses a larger `byte_count` before its ready line |
| `max_source_pixels` | int | header pixel ceiling (fast path); also sets `Image.MAX_IMAGE_PIXELS` |
| `max_source_edge` | int | source edge ceiling (policy fast path) |
| `max_long_edge` | int | display long edge |
| `background` | list of 3 ints | flatten colour, `[255, 255, 255]` |
| `memory_bytes`, `cpu_seconds` | int | the OS limits applied in steps 1–2 above (whole bytes; whole seconds) |

The ready line's `status`, `protocol` and `pillow` are strings and `pid` and `rlimit_as` are ints.
The response's `status`, `mode` and `reason` are strings from their closed sets; `width`, `height`,
`source_width`, `source_height` and `orientation` are ints; `scale` is a finite float.

Every limit, ceiling and the background come from `receipt_geometry.NORMALIZATION`.
`wall_seconds`, `ready_seconds` and `max_as_baseline` come from there too but never leave the
broker, which is the only side that can enforce them.

**Response.** After the body the child writes one ASCII JSON line (at most 1 KiB, exact key set per
`status`) and exits 0 — either a decoded page, followed immediately by its pixel body:

```json
{"status": "decoded", "mode": "RGB", "width": 1650, "height": 2200,
 "source_width": 4032, "source_height": 3024, "orientation": 6,
 "scale": 0.5456349206349206}
```

or a fast-path refusal with no body, `{"status": "refused", "reason": "too-many-pixels"}`, where
`reason` is exactly one of `unreadable`, `too-many-pixels`, `source-edge`, `unsupported-mode`,
`animated`, each mapped to its `ReceiptPageError` message. The Pillow version is not repeated here:
the ready line already proved it.

**Mode allowlist.** The child reads the decoded source mode from the header and maps it to the
output `mode`. This is the prior iteration's rule (`_GRAY_MODES` / `_COLOR_MODES` in the paused
worktree's `receipt_pages.py`), moved into the child unchanged:

| source mode (Pillow) | output `mode` |
|---|---|
| `1`, `L`, `LA`, `La` | `L` |
| `P`, `RGB`, `RGBA`, `RGBa`, `CMYK` | `RGB` |
| anything else, including `I;16`, `I`, `F`, `YCbCr`, `LAB`, `HSV` and `PA` | refused as `unsupported-mode`: 16-bit and float pixels would clip rather than scale, so they are refused, never guessed |

A source with transparency data is flattened onto `background` before any scaling (§ 5).

**Length rule and layout.** `mode` is `L` or `RGB` (C = 1 or 3), `1 ≤ width, height ≤ max_long_edge`,
and the body is exactly `width × height × C` raw 8-bit bytes with nothing after it, laid out exactly
as `Image.frombytes(mode, (width, height), body)` reads with the default raw decoder: row-major,
top row first, no row padding, channels interleaved for RGB. The broker derives its stdout cap from
the request it sent — 1 KiB of header plus `max_long_edge² × 3` plus one byte (2200 × 2200 × 3 =
14.52 MB at the default) — so an oversize stream is detected, never buffered, and a test-lowered
`max_long_edge` lowers the cap with it. "Too much output" has exactly two classes: a stream past
this cap is **exceeded the decode budget** (the Exit status table below), while a header line over
its 1 KiB cap, or a body whose length disagrees with the header while the stream stays within this
cap, is **failed validation**.

**Exit status — the child failure taxonomy.** Inside the child, the per-image handler that maps a
decoder failure to `refused`/`unreadable` must re-raise `MemoryError` (an `except MemoryError: raise`
ahead of any `except Exception`). Only the top of `main()` catches it, and exits with
`os._exit(EXIT_BUDGET)` without allocating; any other uncaught exception after the ready line exits
`EXIT_CHILD_ERROR`. The broker maps, in one pure exit-status mapper that § 9 tests directly:

| Child outcome | Per-asset result |
|---|---|
| exit 0 with a valid response | a page, or the closed-set fast-path refusal |
| exit 0 with a malformed response | **failed validation** |
| exit `EXIT_BUDGET` (3) | **exceeded the decode budget** |
| exit `EXIT_CHILD_ERROR` (4) | **decode child error** — a bug, not a breach; counted separately in the run's output |
| any other non-zero exit, a signal (with soft = hard, Linux delivers `SIGKILL` directly at the `RLIMIT_CPU` limit — no `SIGXCPU` first), a job kill, a native crash, the wall clock, or an oversize stream | **exceeded the decode budget** — native code can fail an allocation that way |

Caveat: libjpeg reports some allocation failures as an `OSError`, which the child maps to
`unreadable`. The § 9 memory sentinel is therefore the LANCZOS strip, whose coefficient allocation
fails as a `MemoryError`, and its test asserts exit `EXIT_BUDGET`, not merely a non-zero exit.
**Under the production fast paths the strip never reaches LANCZOS:** `max_source_edge` = 65,535
exists for exactly this vector, so a 44.7M-edge strip is refused from its header as `source-edge`
(exit 0), and a strip within that edge cannot amplify (the coefficient buffer scales with source
edge ÷ 2200; measured on Pillow 12.2.0, a 65,535-wide strip resized to 2200 adds about 3 MiB). The
sentinel's request therefore lifts `max_source_edge` and `max_source_pixels` to `2**31 - 1`, exactly
as the § 9 guard-independence run does, while `memory_bytes` stays at the chosen production value.

**Broker validation and refusals.** Any failure is a per-asset `ReceiptPageError`, never a partial
page. The broker requires an exit status that maps to a page or refusal within the wall clock; the
exact key set for the `status`; `reason` in its closed set; `orientation` in 1–8; source dimensions
positive and within the request's ceilings; `width`, `height` and `scale` equal to what
`receipt_decode.scaled_size` derives from the source size, orientation and `max_long_edge` (the one
derivation, imported rather than restated); and the exact body length. It then builds the page with
`pixels_to_page` — `Image.frombytes`, a resize that is a no-op for child output, and the
baseline-JPEG save — the only Pillow calls that ever see child output. They read pixels alone, so a
compromised child cannot add a metadata segment to a page.

**Limits: starting values and calibration.**

| Limit | Starting value | Enforced by |
|---|---|---|
| `memory_bytes` | 1.5 GiB | Job Object process and job memory; Linux `RLIMIT_AS` (plus the child's runtime-measured baseline) |
| `cpu_seconds` | 15 s | Job Object `PerProcessUserTimeLimit`; Linux `RLIMIT_CPU` |
| `wall_seconds` | 30 s | the broker |
| `ready_seconds` | 5 s | the broker, from spawn to the ready line |
| `max_as_baseline` | 256 MiB (pinned, not calibrated) | the broker, against the Linux ready line's `rlimit_as` |
| `max_source_bytes` | 25 MiB | `to_pages`' capped read; the child, against `byte_count`; config's `max_asset_mib` bound |
| `max_source_pixels` | 80 MP | the child, from the image header (fast path) |
| `max_source_edge` | 65,535 | the child, from the image header (policy; JPEG's own format limit) |

`memory_bytes`, `cpu_seconds` and `wall_seconds` are starting values, not measurements. Under the
measurement-validity discipline, Step 39 measures each § 9 known-good anchor at production limits on
both supported hosts — in its PR's CI run (`lint-type-test` for Linux, `windows-native-sandbox` for
Windows) and on the Windows dev box — in the unit each host's limit actually counts:

- **Windows memory:** the job's `PeakProcessMemoryUsed` (commit), which the broker reads with
  `query_job_limits(job)` after the child exits and before it closes the job. Working set is not
  used; it under-reports.
- **Linux memory:** `RLIMIT_AS` counts address space, not commit, so the measure is the smallest
  `memory_bytes` above the runtime baseline at which the anchor still yields a page, found by
  bisection at 64 MiB resolution.
- **CPU, per host:** Windows counts user time only (`PerProcessUserTimeLimit`), so its reading is the
  job's `TotalUserTime` from `process_limits.query_job_accounting`; Linux `RLIMIT_CPU` counts user
  plus system time, so its reading is the `ru_utime + ru_stime` delta of
  `getrusage(RUSAGE_CHILDREN)` across the child's reap.
- **Wall:** the broker's `time.monotonic()` from spawn to reap.

**Instruments and channel.** The broker measures each child into a `DecodeUsage` (§ 5A signatures),
carried on that page's `PageProgress` or on the refusal's `ReceiptPageError.usage`. The § 9 outer
harness writes the usage on its result line, and the ledger keeps it per asset. The calibration
vehicle is the committed script `scripts/calibrate_receipt_decode.py`. It drives the production
`to_pages` and real child through the § 9 outer harness, loading the anchor generators and harness
source from `tests/test_receipt_decode_budget.py` by path, never a restated copy. It runs N = 3
times per anchor, bisects the Linux memory need, and prints one JSON calibration record per host:
host, runner CPU model, Pillow version, and every reading with its per-anchor maximum and spread
(max ÷ min). It runs once on the Windows dev box and once in each CI job, through a temporary
`Calibrate decode limits` step that Step 39 adds to `lint-type-test` and `windows-native-sandbox`
and removes before merge. The builder copies each record from the CI log into the step checkpoint
and § 6.3.

It then sets, with M the largest reading over all runs on all hosts (each host in its own unit
above, CPU and wall taken on the slowest runner), these **exact** values, not floors, so an inflated
cap disagrees with the recorded readings:

- `memory_bytes` = 1.5 × M_memory, rounded **up** to a multiple of 64 MiB;
- `cpu_seconds` = max(5, ⌈1.5 × M_cpu⌉) and `wall_seconds` = max(`cpu_seconds`, ⌈1.5 × M_wall⌉),
  whole seconds rounded **up**, because `RLIMIT_CPU` and the Job time limit are integral.

**Tolerance band (default applied 2026-10-09):** every known-good anchor must finish at or below 80%
of each limit. The § 9 headroom tests re-run each 80 MP anchor at `memory_bytes × 4 // 5` rounded
down to a whole MiB (page-aligned, so the Job read-back stays exact), at ⌈0.8 × `cpu_seconds`⌉ and at
⌈0.8 × `wall_seconds`⌉ whole seconds — CPU-second limits always round up, and the 5 s floor keeps
each headroom value strictly below its production value — all carried as integers, and require a
page. Calibrating at 1.5× while testing at 80% leaves a band of 0.667 to 0.8 of each limit for
run-to-run and runner variance. A spread above 1.2 on any reading means that band is not enough.
The calibration is then invalid: run it again, never relax the factor. The calibration is also valid
only if, at the chosen values, every known-good anchor still yields a page and the memory sentinel
— the LANCZOS strip with `max_source_edge` and `max_source_pixels` lifted to `2**31 - 1` (Exit
status caveat above) — still exits `EXIT_BUDGET`. The CPU sentinel runs at its explicitly lowered
1 s (§ 9). The measurements, N, the spread, the chosen values and the Pillow version they were
measured under are recorded in the step checkpoint and in § 6.3. A later change of the locked
Pillow version is a gate failure at Step 48, never an in-place re-tune there (Step 48).

### Development commands

```bash
uv sync --extra dev --extra slides --extra receipts   # add --extra web for the full gate
uv run playwright install chromium                    # full gate: the shared-workflow browser tests need the binary
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict pta_finance
uv run python scripts/check_no_identity.py            # the identity guard referenced in § 6.8
```

The full-suite DONE gate additionally needs the Firestore emulator for the `web` suites — start it
per [docs/shared-workflow-proof.md](../shared-workflow-proof.md) and export
`FIRESTORE_EMULATOR_HOST`; those test modules fail loudly rather than skipping when `web` is
installed without it. It also needs the Chromium binary from the `playwright install` line above.
With `web` installed, `tests/test_shared_workflow_browser.py` and
`tests/test_shared_workflow_queue_browser.py` launch Chromium and fail without it (`CLAUDE.md`
§ 7).

---

## 6. Design Decisions

**6.1 The stage produces pages, never locations.** The policy sentence in `CLAUDE.md:197`
has two clauses. *"the toolkit never OCRs, downloads, or auto-matches at render time"* is
time-scoped and survives intact — rendering still touches no socket. *"Locations are prepared
offline by an operator or assistant"* is not time-scoped, and this feature must amend it in the
same change to say that **pages** may be acquired during a refresh while **locations** remain
operator-prepared. Amending it silently, or ignoring it, would leave the repo asserting something
false about itself.

**6.2 The auto-commit gate is one asset per ticket.** Stated exactly, with its two guard
conditions, in § 5A; the reasoning is here. When a ticket has exactly one uploaded receipt asset,
"this asset is this ticket's receipt" is a provenance fact taken from the requestor's own upload
field, not an inference from an amount or a description. Every item on that ticket links to every
page of that one asset with `box: null`, which the viewer already renders as a source page with an
explicit no-outline explanation. The two guards exist because the fact fails quietly otherwise: a
ticket whose one asset produced zero pages has no provenance to assert, and a ticket carrying an
existing link must never have human-verified evidence overwritten by a machine. When a ticket has two or more
assets, the binding genuinely is a guess: the 2026-09-14 backfill measured upload order diverging
from form row order (one six-item ticket mapped to uploads 4, 5, 3, 2, 1, 6), and aggregate rows
fan out across several receipts. Those tickets go to proposals. Asset identity is normalized on
host plus path with query strings discarded, because the form CDN serves size variants of one
file under different query strings.

**6.3 PDFs go through the LPAC worker.** A requestor-uploaded PDF is attacker-influenced input,
and this project already built capability-level isolation for exactly that class of risk. The
alternative considered was pypdfium2 in a capped subprocess — cross-platform, roughly a third of
the work, and it would run in CI — but it grants a pdfium exploit an ordinary user-level process
holding the bundle and Sheets credentials, which is a clear step down from the bar set for bank
statements. The LPAC route costs more and is Windows-only; on other hosts PDFs are cached,
counted, and reported as needing manual export. The existing `[summary]` carve-out
(`docs/plans/master_plan.md:303-308`, *"does not open external receipt or
bank PDFs"*) was re-read on 2026-10-09 and stays true as written: it scopes the summary workflow's
own `pypdfium2`, which checks only PDFs that workflow generates, while Phase 9 renders receipt PDFs
through the separate `[slides]` LPAC worker. It therefore needs no amendment, and no Phase 9 build
step edits that plan (§ 8, Phase 6 row). If
Step 41's spike records a blocked verdict, Step 42 supersedes this decision and
`docs/findings/step-42-pdf-boundary.md` becomes authoritative for Steps 43–44.
**PNG and JPEG uploads are decoded in a resource-capped child, never in the broker** (Option A1,
decided 2026-10-09 after Step 39's stop-and-audit). They are attacker-influenced input too: decoding them
in-process would run libjpeg-turbo, zlib-ng and Pillow's parsers inside the broker itself, which
holds the bundle and Sheets credentials — strictly below the capped subprocess this section rejects
for PDFs. Four
review rounds also showed that guards predicting decoder cost from the bytes do not converge: each
closed one path and the next round found another, and every over-counting guard added a false
refusal (a whole-file scan count refused phone motion photos with an appended video clip). So every
PNG/JPEG is decoded and normalized by `receipt_decode` (§ 5A) in a short-lived child under
OS-enforced memory and CPU limits — a Windows Job Object or Linux rlimits; any other host aborts the
stage — and a broker wall clock; the child returns only bounded raw pixels, which the broker
validates and encodes. **The bound is uniform:** whatever the format or decoder path, including
paths a later Pillow adds, the worst per-asset cost is the configured memory and wall time, and any
breach is a per-asset refusal. The limits start at 1.5 GiB memory, 15 s CPU and 30 s wall and are
calibrated per § 5A to 1.5× the largest of N = 3 measured runs per host for the known-good anchors
(job commit on Windows, bisected address space on Linux), with every anchor required to finish
within 80% of each limit; the largest legitimate in-process peak
measured so far is about 941 MiB working set and 4.6 s (an 80 MP CMYK progressive JPEG), and Step 39
replaces that figure with the per-host measurement § 5A defines. **Calibrated values (Step 39,
2026-10-10, final):** Pillow 12.2.0, N = 3 per anchor per host, each host in its § 5A unit
(Windows: Job peak commit and Job user time; Linux: bisected `RLIMIT_AS` need above the runtime
baseline, at 64 MiB resolution, and user + system time), every anchor a page at the starting
limits, measured with `scripts/calibrate_receipt_decode.py`. Largest reading per host, all from
the 80 MP CMYK progressive anchor (the 80 MP RGBA PNG in brackets), with the largest spread over
the readings the spread rule checks:

| host | memory | CPU | wall | spread |
|---|---|---|---|---|
| Windows dev box (Intel Core Ultra 7 155H, Python 3.12.13) | 933.1 MiB [701.9] | 4.73 s [1.13] | 5.11 s [1.42] | 1.083 |
| Linux, WSL2 on the dev box (Python 3.12.13) | 960 MiB [704] | 3.99 s [1.56] | 3.66 s [1.43] | 1.047 |
| `lint-type-test` runner, ubuntu (AMD EPYC 7763, Python 3.12.15) | 960 MiB [704] | 4.96 s [1.93] | 4.97 s [1.94] | 1.012 |
| `windows-native-sandbox` runner, windows-2022 (AMD family 25, Python 3.12.15) | 932.9 MiB [701.7] | 5.50 s [1.41] | 5.64 s [1.55] | 1.035 |

The three small anchors needed at most 128 MiB, 0.33 s and 0.42 s on any host. The CI records come
from run 38063930164. Formula inputs, M taken over all four hosts (CPU and wall on the slowest
runner, `windows-native-sandbox`): M_memory = 960 MiB (1,006,632,960 B), M_cpu = 5.50 s,
M_wall = 5.64 s. **Chosen values:** `memory_bytes` = ⌈1.5 × 960 MiB ÷ 64 MiB⌉ × 64 MiB = 1,472 MiB
(1,543,503,872 B), `cpu_seconds` = max(5, ⌈1.5 × 5.50⌉) = 9 and `wall_seconds` =
max(9, ⌈1.5 × 5.64⌉) = 9. Every known-good anchor then finishes at or below 80% of each limit:
65.2% of memory, 61.1% of CPU and 62.7% of wall at the worst reading, and the headroom tests run
at 1,177 MiB, 8 s and 8 s. The Pillow-loaded Linux interpreter baseline measured 49.9 MiB
(52,310,016 B) on the `lint-type-test` runner and 46.8 MiB under WSL, so `max_as_baseline`
(256 MiB, pinned) is 5.1× the larger. *Method change to the spread rule, recorded here for
ratification (§ 5A's text is unchanged):* the "spread above 1.2 invalidates" test was applied to
every memory reading and to every CPU or wall reading whose smallest run is at least 0.5 s, not to
sub-second time readings. The reason is resolution: Windows Job CPU accounting advances in
15.625 ms ticks, so a reading of a few ticks has a spread that is quantization, not run-to-run
variance (0.5 s is 32 ticks, about 3% quantization). The readings this exempted that would
otherwise have failed were all Windows CPU readings of the small anchors, none of which bounds a
limit: on the dev box, motion photo 0.156–0.219 s (spread 1.40), phone 0.203–0.266 s (1.31) and
MPO 0.031–0.078 s (2.50), with 1.23, 1.33 and 2.00 in an earlier run; and on the windows-2022
runner, MPO 0.094–0.141 s (1.50). Every other exempted reading was within 1.2 anyway (at most
1.17). Every reading that bounds a limit — the two 80 MP anchors — was checked and passed on every
host. The first WSL run, invalidated by a bounding reading (RGBA PNG CPU spread 1.252 under
concurrent load), was re-run rather than relaxed. Measured once on the dev box: the `cpu-bound`
sentinel's uncapped decode needs 14.6–15.0 s of CPU and the `wall-clock` sentinel's 22.6–25.9 s;
the `lanczos-strip` need (about 2.58 GB) stays above the chosen `memory_bytes`. Windows enforces
`PerProcessUserTimeLimit` with a lag — a 1 s limit ended the child at 2.0–2.6 s of user time, and
under heavy load a 2 s limit at 6.6 s — so on Windows the broker wall clock is the hard time bound
and the Job CPU limit a backstop. The header checks — pixel and source-edge
ceilings, the mode allowlist, the animated-PNG refusal — remain only as cheap fast paths and policy;
none is a safety bound, and the raw-byte scan, EXIF and multi-picture counts are deleted.
**Residual:** the child is still an ordinary user-level process running as the operator. A
memory-safety exploit in the image stack inherits no secret (§ 5A: minimal environment, empty
working directory, no inherited handle), but it can **read and write** whatever the operator's
account can — including the bundle and the credential files under `secrets/` — and open **network**
connections to exfiltrate them. On **either** host it could also outlive the run: on Linux by
leaving the process group (`setsid`), on Windows by starting a process outside the Job through a
per-user channel such as Task Scheduler, WMI or a Run key, which `ActiveProcessLimit = 1` does not
govern. Only code execution can do either, and the account reach is the same reach already granted
above. Its memory and CPU stay capped. That is the
containment the Step 42 fallback accepts for PDFs: below the LPAC bar, but no regression from
in-process decoding, which exposed the same reach inside the broker itself. **Deferred upgrade:** hosting the decode inside
the attested LPAC worker would also contain an exploit; revisit it once Step 43's render protocol
exists, the worker's 512 MiB hard memory ceiling can be raised under release review to cover the
calibrated budget, and its per-launch staging cost is acceptable per asset. The child protocol is
shaped to move there unchanged. Colour management (gAMA, ICC) is not applied, so a page can differ
in tone from a browser's view of the same upload; the page this toolkit shows is the evidence the
reviewer judges.

**6.4 The render protocol rides the existing limits envelope.** `_NATIVE_LIMIT_FIELD_CEILINGS` is
a flat name→ceiling table and `_deserialize_native_limits` validates by exact key-set equality, so
new integer fields are covered without touching the launcher or the worker's argument parser. The
worker emits **raw grayscale pixels plus zlib**, not PNG: the broker then validates with a
bounded `decompressobj().decompress(data, max_length=W*H)` and an empty-leftover assertion, which
is decompression-bomb-proof, and returns the validated raw gray8 pixels with their width and height
to its caller. No PNG is produced anywhere on this path: Step 44 passes those pixels to
`receipt_pages.pixels_to_page` (§ 5A), which downscales to the long-edge limit and encodes the JPEG
page, exactly as it does for the image child's output. Emitting PNG from inside the boundary
would instead force the broker to parse untrusted PNG chunks and allowlist ancillary chunks to
close the `tEXt`/`zTXt`/`iTXt`/`eXIf` covert channel — more attack surface, not less, and it
would break the boundary's central invariant that the broker re-derives everything the worker
sends. Note two traps found during verification: pdfium pads bitmap rows, so the buffer must be
copied row by row rather than wholesale; and `_page_dimensions` computes rendered pixels at a
hardcoded 300 DPI and hard-rejects anything that is not US Letter, so the render path needs its
own dimension gate and cannot reuse the statement extraction path.

**6.5 The budget check happens before the write, not inside the loader.** Today, crossing
`MAX_TOTAL_BYTES` raises an opaque error inside `load_receipts` — *after* `refresh_bundle` has
already rewritten the bundle, leaving the run at exit 1 with a stale HTML and no clear cause. The
fill stage computes projected totals up front and refuses with the crossing page and the
remaining budget named. Measured on 2026-09-16, from a 68.04 MiB base: fetching every asset then
unfetched would have landed at 94–96% of the cap with the old encoding, and at roughly 79 MiB with
the new pages normalized. That is why only new pages are normalized and the existing pages stay
untouched. From the 2026-10-09 base of 92.3 MiB (§ 2), that margin is gone: about 30 new
normalized pages fit. The pre-check's refusal is therefore expected soon, and every merge prints
the remaining headroom (§ 5A, Printed receipt summary).

**6.6 Normalization defaults to long edge 2200 / JPEG q85.** Measured across all 164 pages live
on 2026-09-16 rather than a sample: it saves 39% of bytes with *identical* fine-print line geometry, because
only 7 pages exceed a 2200 long edge — it is a transcode, not a downscale. The tighter variants
save more but push the worst 5% of pages under 8 px of text height, which is the practical floor
for reading a receipt line without zooming.

**6.7 Proposals cannot be loaded as a sidecar, in either direction.** `receipt_viewer._object`
compares exact top-level key sets, so a proposals document raises on its first check. The confirm
verb refuses a document carrying the sidecar's key set with a named error, so a swapped
`--proposals`/`--sidecar` pair fails loudly rather than half-merging. A regression test feeds the
committed fictional proposals example to `load_receipts` and asserts it raises.

**6.8 Printed output stays aggregate-only.** No URL, requestor, vendor, subject or filename may
reach stdout; existing CLI tests already assert this shape and the identity guard cannot see
inside a PNG or a base64 `data:` URI. There is one deliberate exception, `link-receipts hosts`
(Step 46). It prints only the distinct bare upload hostnames in the local archive, because a
hostname is the configuration value the operator must type into the private allowlist. Its output
goes only to the operator's terminal and is never written to a file. Cache files are named from the digest of their bytes, never
from the URL or the original filename, so no vendor filename lands on disk or in a page `path`.

---

## 8. Risks and Open Questions

| Item | Risk | Mitigation |
|---|---|---|
| LPAC render effort | The single largest cost here: four of the twelve steps (41–44) with a mandatory spike — the largest single cost in this plan, for a boundary that exists but has never carried image payloads. | Steps 41–42 gate it: the spike must pass before protocol work is funded, and a conditional fallback step re-scopes to a capped subprocess if it does not. |
| Silent blank renders | pdfium's Win32 font mapper reaches fonts through GDI/win32k; the worker has no window-station grant. A degraded mapper produces blank or box glyphs — wrong output, not a crash, invisible to fake-backend tests. | Step 41's gate is a real LPAC render measured for ink coverage and glyph similarity against a reference, not a mocked call. |
| `evidence_payload` blast radius | One new field there rotates every `source_evidence_sha256` → every `item_fingerprint` → every live link (190 as of 2026-10-09) dies and the refresh refuses outright. | Declared a hard constraint in § 4; Step 47's blast-radius test makes the coupling explicit and failing. |
| Page budget | 92.3% consumed as of 2026-10-09 (§ 2: 221 pages, about 7.7 MiB free; it was 68% on 2026-09-16). Roughly 30 new normalized pages remain before Step 45's whole-merge refusal, which links nothing when it fires. Crossing the cap today raises inside the loader *after* the bundle was rewritten. | Pre-check before write (§ 6.5) plus measured normalization (§ 6.6), and a `page budget` line after every merge (§ 5A) that Step 49 records. The 2026-09-16 projection (about 79 MiB after fetching everything then unfetched) no longer holds from the 2026-10-09 base; `link-receipts compact` stays out of scope (Deferred row); a budget refusal during Step 49 is recorded, verified as a no-op on the sidecar/bundle/HTML, and routed to a follow-up issue (operator decision 2026-10-09). |
| Small measured benefit today | On the 2026-09-16 data the auto-gate closes 1 of 84 unlinked items; 69 are adjudicated unlinkable and 11 are structural. | The benefit is prospective and evidence-preserving: 4 new items appeared in 2 days, and the hosted upload URL is the only pointer to the original receipt that exists anywhere — the bundle drops it and the toolkit keeps no copy. |
| First outbound HTTP fetcher | New lane, new failure modes, new trust in a third-party CDN. | HTTPS-only, config-declared allowlist, magic-byte sniffing with `Content-Type` ignored, hard size ceilings, per-asset isolation, digest-named cache, and a cache-only offline mode. |
| Corpus-wide unfetched count is uncertain | Two mappings of tickets to forms disagree: ~50 unfetched under one, 174 under another (superseded re-submissions), and 0 among exactly-keyed tickets. | Only the 4 new items' URLs are established beyond doubt. Step 49 measures the real number on live evidence rather than committing to either estimate. |
| Confirm UX friction | A six-upload ticket is confirmed by hand-editing JSON. | Accepted for this phase; the HTML picker is reserved as Step 50 in a later phase once the CLI path has been used on a real run. |
| **Plan collision with treasurer Wave 1 Step 16** | Wave 1 Step 16 (issue #43, still PENDING) claims `bank_statements.py`, `native_sandbox.py`, `native_worker.py` and `.github/workflows/ci.yml` for its bounded-Tesseract path. Steps 41 and 43–44 touch only `bank_statements.py` of those (Step 41 its minimal render branch; § 4 keeps the launcher and worker parser unchanged), and Step 39 makes a behavior-preserving wrapper refactor of `native_sandbox.py`'s Job Object helper into `process_limits.py` (not an import-only change: the wrapper maps the leaf's error and keeps the deferred close, § 5A), but both phases land in the same files and the same `windows-native-sandbox` job. Whichever lands second rebases onto a changed worker protocol or a moved helper. | **Two-sided, and resolved deterministically — the build does not halt for it.** This side: Steps 39, 41 and 43 each check whether #43 has landed; if it has, rebase onto it (Step 39 also routes Step 16's Job Object creation through the same wrapper, a minimal import-path change) and run both native suites; if it has not, land this phase's change first and comment on issue #43 — no build step edits the other plan's file. Other side: Wave 1 Step 16's brief (`treasurer-summary-wave-1-plan.md`) carries a reciprocal note, added at plan time on 2026-10-09, that it creates its Job through `native_sandbox._make_job_object` → `process_limits` rather than restating the primitive, and rebases if Phase 9 landed first. **Propagation:** that note reaches issue #43's body through the next `/repo-sync` run, which syncs `treasurer-summary-wave-1-plan.md` limited to #43 alongside this plan's changed Phase 9 issues; no build step posts it. The master plan's Phase 9 paragraphs were refreshed at plan time on 2026-10-09 (A1 decision, Step 39 state, and this collision naming Steps 39, 41 and 43). The operator may override the landing order at any time, but no decision is required before dispatch. |
| **Plan collision with Phase 10 (non-reimbursement action queue)** | Phase 10 Step 51 adds a separate `update-actions` command and subparser in `build_parser`, next to `update-reimbursements`; it touches neither `_cmd_update_reimbursements` nor `tests/test_reimbursement_cli.py`. Phase 10 Step 54 edits `_cmd_update_reimbursements` and `tests/test_reimbursement_cli.py` (its plan § 7 Files and "Parallel phase boundary", which already orders actions after receipt filling). Step 51 is paused with an unfinished `cli.py` change in its own worktree, so Step 46's line numbers will move under it, and Step 54 moves the pinned stage-order test. | **Resolved in Step 46's brief.** Step 46 re-reads `cli.py` at dispatch and anchors to function names, not lines. The fill stage stays before `build_report`; any action stage stays after it, so the stage-order test expects refresh, fill, report, then actions when that stage exists. Whichever phase lands second rebases and re-runs `tests/test_reimbursement_cli.py`. Neither phase changes the other's private schema. |
| **Plan collision with Phase 6 (board summary)** | [`reimbursement-board-summary-plan.md`](../plans/master_plan.md) is PLANNED (umbrella #55; automated Steps 26–30 in #56–60, attended Step 31 in #61). Its pending steps claim files Phase 9 also edits: `pta_finance/cli.py` and `tests/test_reimbursement_cli.py` (Step 26); `cli.py`, `pyproject.toml` (its `[summary]` extra), `uv.lock` and `.github/workflows/ci.yml` (Step 28); `README.md`, `CLAUDE.md` and `docs/loading-receipts.md` (Step 29); `ci.yml` (Step 30). Its Step 29 runner calls the existing refresh CLI (`update-reimbursements --fetch-since`) and stops on the first failure. Once Phase 9 lands, that command fetches receipt assets and spawns decode children by default when `[receipt_assets]` is enabled, and a fill-stage abort exits 1, so the runner inherits both. | **Resolved deterministically, with no build-time cross-plan edit.** Whichever phase lands second rebases onto the other's `cli.py`, CI and docs changes and re-locks with plain `uv lock` (never `--upgrade`), so neither extra moves the other's pins. Step 46 keeps exit codes in {0, 1}, names each abort's cause and remediation, and keeps `--no-fill-receipts` a forwardable opt-out, so the runner's stop-on-first-failure behavior is correct as planned. The board-summary `[summary]` carve-out stays true and is not edited (§ 6.3). **Rule and its one exception (default applied 2026-10-09):** a build step never edits another plan's file. A scoped coordination note in another plan is allowed only at plan time, with operator approval and a re-sync of that plan's issue — the precedent is the Wave 1 Step 16 note. A reciprocal note on Phase 6 Step 29, naming the runner's coupling to the fill-stage default and its exit 1, is therefore a documented **operator follow-up**: a plan-time edit of `reimbursement-board-summary-plan.md` plus a `/repo-sync` of #59, never a Phase 9 build step. |
| Spike verdict travels as a file, not a plan edit | `/build-phase` parses steps once at Step 0 and never re-reads the plan, so Step 42 cannot amend Steps 43–44 in place. | Step 42 writes `docs/findings/step-42-pdf-boundary.md`; Steps 43–44 read it at build time and fall back to the LPAC boundary when absent. |
| Image decoder cost | Untrusted PNG/JPEG bytes reach Pillow, libjpeg-turbo, zlib-ng and the resampler, whose cost on crafted input no header check bounds: Step 39's review rounds measured multi-GiB and tens-of-seconds amplifications from small uploads that passed every guard, and each new guard either failed open or false-refused real photos. | Mitigated by the decode child (§ 6.3, § 5A): OS-enforced memory and CPU limits plus a broker wall clock, starting at 1.5 GiB / 15 s / 30 s and calibrated per § 5A at 1.5× the largest of N = 3 runs per host for the known-good anchors, with each anchor required to finish within 80% of each limit; any breach is a per-asset refusal. § 9's decode-budget corpus and headroom tests are a standing gate that re-runs on every `uv.lock` refresh. |
| Image decoder exploit containment | A memory-safety bug in the image stack runs in an ordinary user-level child: it inherits no secret (minimal environment, empty working directory, no inherited handle), but it can read and write whatever the operator's account can, open network connections to exfiltrate it, and, on either host, start a process that outlives the run (Linux `setsid`; Windows through a per-user channel outside the Job). | Accepted residual, the same class as the Step 42 PDF fallback and no regression from in-process decoding. Upgrade path: host the child in the attested LPAC worker once Step 43's protocol exists (§ 6.3); the child protocol is shaped to move there unchanged. |
| Deferred, not open | `link-receipts compact` (re-encoding the existing verified pages: 221 as of 2026-10-09; on the 164 measured on 2026-09-16 it would have saved 39%) is **decided out of scope** for this phase — no step depends on it. It rewrites human-verified evidence, so it waits until the budget actually forces it. With about 7.7 MiB free on 2026-10-09 (§ 2), that may happen soon after this phase. | No action; recorded so a later phase does not re-derive the reasoning. |

---

## 9. Testing Strategy

**Pipeline smoke gate before any observation step.** This is a producer→consumer chain —
assets → pages → proposals → sidecar → rendered HTML — and every boundary is exactly where mocked
unit tests go blind. Step 47's end-to-end drive of `cli.main` with real components and no mocks is
that gate, and it precedes Step 49's attended run.

**New components are tested through their production caller.** Per the workspace rule, a unit test
of `receipt_link` alone would leave a silent-wiring failure invisible — the failure mode where a
module is built, unit-tested, and never actually invoked. Step 47 asserts the new component is
reached from `cli.main` and that its effect appears in the rendered HTML.

**Conventions to follow**, matching `tests/test_receipt_viewer.py` exactly: no pytest fixtures
(module-level helpers), no committed binary fixtures (synthesize PNG bytes in code, and emit the PDF fixtures Steps 41 and 44 need from a committed generator rather than checking in a .pdf), `tmp_path` on
every test with an assertion that the path never appears in rendered output, fake-organization
placeholders throughout, and an injection payload baked into the happy-path fixture and asserted
inert.

**Existing tests that will break, and what they become:** `test_reimbursement_cli.py:238-247`
(exact `refresh_kwargs` equality) and `:311` (stage ordering `['refresh', 'report']`) must accept
the new stage as its own call rather than a new kwarg. Beside the 19-case fail-closed parametrize
at `test_receipt_viewer.py:91-114`, Step 47 adds one case per class the fill stage can produce (its
Problem lists them), each keeping the assertion that the previous HTML survives untouched. The prior Step 39 iteration's
`tests/test_receipt_pages.py` (uncommitted, in the paused worktree) patches Pillow in-process and
asserts the scan, EXIF and MPF ceilings; under A1 those cases are rewritten as child-driven or
pre-spawn fast-path tests, or deleted with the ceilings (Step 39).

**Decode-budget corpus — a standing gate.** `tests/test_receipt_decode_budget.py` (Step 39) makes
"untrusted decode cost is bounded" a measured property of the production entry point, independent
of which guard, if any, handles an input — so a newly found amplifier becomes a corpus row that
passes **without** a new guard. It follows the conventions above, with every input synthesized in
code from `hashlib.shake_256` seeds. It is part of the full suite, so it re-runs on every
`uv.lock` refresh, and no test may substitute an in-process decode for the child (§ 5A).

- **Amplifier corpus**, one generator per known vector, run under the pinned test-module limits
  `CORPUS_MEMORY_BYTES = 512 MiB`, `CORPUS_CPU_SECONDS = 2` and `CORPUS_WALL_SECONDS = 6`, with every
  generated input at most 4 MiB: a many-scan progressive JPEG (400 scans, plus the lenient junk,
  stuffed-byte and short-length layouts); an EXIF IFD flood (256 KiB across segments); a 64 KiB
  SHORT-typed multi-picture index; 44.7M×1 and 1×44.7M PNG strips (a `source-edge` refusal at the
  production fast paths); `iCCP`, empty-key `zTXt`, invalid-UTF-8 `iTXt` and post-IDAT `iCCP`
  floods; repeated SOF segments; empty-APPn, `FF`-fill and `FF 00` floods; a giant `cHRM`; a
  private-chunk flood; and an ICC-fragment flood. **Floor:** every test-lowered `memory_bytes` in
  the module is at or above `MIN_TEST_MEMORY_BYTES = 256 MiB`, asserted at import, so a lowered
  child still clears its own interpreter baseline and a budget refusal is never really a failed
  start.
- **Known-good anchors**, which must each yield a page within budget: an 80 MP RGBA PNG and an 80 MP
  CMYK progressive 64-scan JPEG, both at **production** limits and in **both** CI jobs (Linux
  rlimit path in `lint-type-test`, Job Object path in `windows-native-sandbox`) — unmarked, so
  nothing deselects them; a **motion-photo-style JPEG** — a still plus an 8 MiB seeded trailer
  appended after its end-of-image marker, so its raw `FF DA` count exceeds 64; an MPO with
  per-frame EXIF; and a phone-shaped JPEG with a 60 KB EXIF and a thumbnail. They pin that the
  budget does not false-refuse, and they are what § 5A calibrates the limits against. **Headroom
  tests** apply § 5A's pinned tolerance band (default applied 2026-10-09). They re-run each 80 MP
  anchor at 80% of each limit and require a page: `memory_bytes × 4 // 5` rounded down to a whole
  MiB, and ⌈0.8 × `cpu_seconds`⌉ and ⌈0.8 × `wall_seconds`⌉ whole seconds, carried as integers. A
  Pillow move or a slower runner that erodes the calibrated margin therefore fails the suite.
- **Known-garbage sentinels**, which must be refused with the budget message. This is the
  red-on-garbage anchor; a budget that cannot fail proves nothing.
  - `lanczos-strip` (memory): the 1×44.7M PNG strip, whose LANCZOS need measured 2,582 MiB, with
    the request's `max_source_edge` and `max_source_pixels` lifted to `2**31 - 1` (exactly as the
    guard-independence run lifts them) and `memory_bytes` at the **chosen production** value. It
    asserts exit `EXIT_BUDGET` rather than any non-zero exit, and that no fast-path refusal occurred
    (§ 5A, Exit status). At the production fast paths the same strip is a `source-edge` refusal. Its
    edge is a test-module constant, lengthened if the chosen `memory_bytes` approaches its need.
  - `cpu-bound`: the corpus's 400-scan progressive JPEG generator at a size (a test-module
    constant) whose uncapped decode needs at least 10 s of CPU on the dev box, measured once and
    recorded in the checkpoint. It passes every fast path (under 80 MP, edges at most 65,535, an
    allowed mode) and runs under an **explicitly lowered** 1 s `cpu_seconds` carried in the
    request, so it exceeds that limit on any runner.
  - `wall-clock`: the same CPU-bound generator at its own size constant, whose uncapped decode needs
    at least 20 s of CPU on the dev box (measured once and recorded in the checkpoint), with
    `cpu_seconds` raised to 60 and `wall_seconds` lowered to 8 through the harness overrides, while
    `ready_seconds` stays at 5. A child start slower than 5 s is then a late ready line in production
    too, and a faster one is always accepted before the wall clock can fire, so the sentinel cannot
    flake into a stage abort (§ 5A wall-clock precedence); the 20 s need keeps the wall clock, not the
    decode finishing, the ending even on a runner 2.5× faster. It asserts the budget refusal, a measured
    `DecodeUsage.wall_seconds` below the raised CPU limit (so the wall clock, not CPU, ended it), and
    that no process of the child's Job (Windows) or process group (Linux) is alive afterward.
- **Harness.** Each case runs the production `to_pages` inside an **outer** test process, so a
  regression that moves decoding back in-process fails as "outer budget breached" instead of
  exhausting CI. The outer process runs `-I -c <harness source held in the test module>` (launched
  as one process exactly like the child, § 5A), reads one JSON line of `NORMALIZATION` overrides and
  the input path, and applies them **inside itself** — `dataclasses.replace` then
  `setattr(receipt_pages, "NORMALIZATION", ...)` — before calling `to_pages`; a monkeypatch in the
  pytest process could never reach it. Its caps are pinned. **Windows:** a Job from
  `process_limits.make_job_object(..., active_processes=2)` with memory exactly 2 × `memory_bytes`
  and CPU 2 × `cpu_seconds`, so the broker inside it can start its decode child, which then sits in
  its own nested Job. The test assigns the outer process to that Job and confirms the assignment
  **before** it writes the outer's input line, and the outer blocks on stdin until then. **Linux:**
  `RLIMIT_CPU` = 2 × `cpu_seconds`, and `RLIMIT_AS` = 2 × `memory_bytes` + the outer's own `VmSize`
  (read before it sets the limit) + `OUTER_THREAD_AS_ALLOWANCE`. `RLIMIT_AS` counts reserved
  address space, and one broker helper thread reserves about 136 MiB (an 8 MiB stack plus a glibc
  per-thread arena), so `OUTER_THREAD_AS_ALLOWANCE = 512 MiB` covers up to three helper threads
  (wall clock, ready timeout, stdin writer). The decode child inherits that hard limit and lowers its
  own below it. The timeout is `wall_seconds` + `SPAWN_SLACK_S`. The harness writes one result line
  — the outcome, the child's `DecodeUsage`, the outer wall time and the broker's memory growth —
  which the tests assert on and the calibration script reads. It asserts that the outcome is a page
  or a `ReceiptPageError`, never another exception; that outer wall time stays within
  `wall_seconds` + `SPAWN_SLACK_S`; and that the broker's own memory grows by at most input + page +
  `BROKER_GROWTH_ALLOWANCE`, so the cost sits in the child. Broker memory is measured on Windows as
  peak **commit**, `PeakPagefileUsage` from `GetProcessMemoryInfo`, never working set, which
  under-reports. On Linux it is `VmHWM` (peak resident set) from `/proc/self/status`, never
  `VmPeak`: `VmPeak` counts reserved but untouched address space. A WSL probe (Python 3.12.3) of one
  helper thread making small allocations measured `VmPeak` +136.0 MiB but `VmHWM` +1.9 MiB, and CI
  runners have no swap pressure at these sizes, so `VmHWM` does not under-report there. The
  allowance is calibrated by its own anchors. Red: the "decode in-process" mutation must exceed it
  (an 80 MP anchor decoded in the broker needs hundreds of MiB). Green: the motion-photo anchor
  stays under it. `SPAWN_SLACK_S = 5`, `BROKER_GROWTH_ALLOWANCE = 64 MiB` and
  `OUTER_THREAD_AS_ALLOWANCE = 512 MiB` are constants of the test module.
- **Guard independence.** The whole corpus runs twice: with the production fast paths, and with
  every numeric fast-path ceiling in the request lifted through `dataclasses.replace` to an explicit
  `2**31 - 1` (`max_source_pixels`, `max_source_edge`; JSON has no infinity). Because the child sets
  `Image.MAX_IMAGE_PIXELS` from the request, lifting the pixel ceiling lifts Pillow's own bomb check
  too. Both runs must end within budget, which proves the invariant is the boundary, not the guards.
- **Direct broker tests** (in `tests/test_receipt_pages.py`; § 5A permits them because they decode
  nothing): `test_broker_rejects_malformed_decode_response[...]` feeds the response validator
  crafted lines, with cases `wrong-length`, `extra-field`, `missing-field`, `bool-int`, `float-int`,
  `nan-scale`, `duplicate-key`, `crlf-terminator` and `oversize-header`, and asserts each is a
  per-asset failed validation. `test_broker_rejects_malformed_ready_line[...]` covers `bool-pid`,
  `extra-key`, `oversize` and, on Linux, `rlimit-out-of-band`, and asserts each is a stage abort.
  `test_broker_stdout_read_is_capped` feeds the capped reader one byte over the cap derived from the
  request and asserts it stops there and refuses as **exceeded the decode budget** (`budget`, the
  Exit status table's oversize-stream row), never `failed-validation`, which § 5A reserves for an
  oversize header line or a body length that disagrees with the header within the cap.
  `test_broker_maps_child_exit_status[...]` feeds the broker's exit-status mapper crafted exit
  outcomes, with cases `exit-0-valid`, `exit-0-malformed`, `exit-budget`, `exit-child-error`,
  `other-nonzero`, `signal`, `wall-clock` and `oversize-stream`, and asserts each yields its row of
  § 5A's Exit status table — in particular `exit-child-error` yields `child-error`, never `budget`.
  No crafted image makes the real child exit 4, so this direct case is that branch's only test route.
- **Mutation anchors**, each of which must turn its named test red and is recorded in the step
  checkpoint:

  | Mutation | Test that must go red |
  |---|---|
  | decode in-process | `test_known_good_anchor_yields_page[png-80mp-rgba]` (broker growth above `BROKER_GROWTH_ALLOWANCE`, or the outer budget breached) |
  | memory limit dropped | `test_known_garbage_sentinel_is_refused[lanczos-strip]` (ceilings lifted, so the strip reaches LANCZOS) |
  | CPU limit dropped | `test_known_garbage_sentinel_is_refused[cpu-bound]` |
  | wall timeout dropped | `test_known_garbage_sentinel_is_refused[wall-clock]` |
  | a wrong-length or extra-field response accepted | `test_broker_rejects_malformed_decode_response[wrong-length]` / `[extra-field]` |
  | stdout read uncapped | `test_broker_stdout_read_is_capped` |
  | exit 4 (`EXIT_CHILD_ERROR`) mapped to budget | `test_broker_maps_child_exit_status[exit-child-error]` |
  | Windows: child launched through the venv launcher (`sys.executable`) instead of the base interpreter | `test_decoding_pid_is_the_limited_process` |
- **Decoding-pid test.** `test_decoding_pid_is_the_limited_process` asserts that the pid on the
  ready line equals `Popen.pid` and is the process carrying the limits. On Windows, that pid's
  handle is in the job and `query_job_limits(job)` shows the requested values. On Linux,
  `/proc/<pid>/limits` shows soft = hard = the ready line's `rlimit_as` for "Max address space" and
  soft = hard = `cpu_seconds` for "Max cpu time", and that `rlimit_as` lies within
  `[memory_bytes, memory_bytes + max_as_baseline]`. A launcher process or a wrapper can therefore
  never hold the limits while another process decodes. Step 49 also runs it on the operator's
  machine.
- **CI and placement.** No new pytest marker is introduced; every case above runs unmarked in the
  full suite. If a later step adds a marker, it must be registered in `pyproject.toml`'s `markers`,
  and no CI job may deselect it. Both `lint-type-test` (in its JUnit check) and
  `windows-native-sandbox` (whose explicit file list names the module, with a JUnit check) require
  these exact cases to be present and **not skipped**, and assert that no case in
  `tests.test_receipt_decode_budget` is skipped:
  `test_known_good_anchor_yields_page[png-80mp-rgba]`,
  `test_known_good_anchor_yields_page[jpeg-80mp-cmyk-progressive]`,
  `test_known_good_anchor_has_headroom[png-80mp-rgba]`,
  `test_known_good_anchor_has_headroom[jpeg-80mp-cmyk-progressive]`,
  `test_known_garbage_sentinel_is_refused[lanczos-strip]`,
  `test_known_garbage_sentinel_is_refused[cpu-bound]`,
  `test_known_garbage_sentinel_is_refused[wall-clock]` and
  `test_decoding_pid_is_the_limited_process`. `lint-type-test`'s JUnit check also requires the
  `tests.test_receipt_pages` cases `test_broker_rejects_malformed_decode_response[wrong-length]`,
  `test_broker_rejects_malformed_decode_response[extra-field]`,
  `test_broker_stdout_read_is_capped` and
  `test_broker_maps_child_exit_status[exit-child-error]`, not skipped. Expected cost is about 60–120 s per job,
  dominated by the production-limit anchors and bounded above by the pinned corpus limits.

**Gate scope.** The gate that flips a step DONE runs the **full** suite — every declared test root
with dev, slides, web and the `receipts` extra installed and the Firestore emulator running — not the subset a step
iterated against. The checkpoint names which suites ran. A subset count cannot see a cross-suite
regression.

**End-to-end verification** is Step 49: a real refresh against the live private bundle, confirming
that the tickets which arrived after the cutoff (the 2026-10-09 manual receipt backfill) open their
source receipts — or recording N/A for an empty class ("N/A — no auto-eligible single-asset ticket"
for auto-linking, "N/A — none arrived after the cutoff" for proposals) — that no
previously-linked item regresses, that the decode child starts and attests on the operator's
machine, that at least one real allowlisted fetch and, if any fetched asset is a PDF, one real
PDF render run on that host (clause (g), through a no-write probe if needed), and that the rendered
report stays inside the page budget.
