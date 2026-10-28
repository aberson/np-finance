# np-finance — project context

> **Identity rule (load-bearing).** This is a **generic, reusable finance toolkit** for a
> non-profit organization. **Never hard-code any organization, school, person,
> or email** in committed code, docs, tests, fixtures, or examples. All real identity remains in
> gitignored private inputs/configuration (`config.toml`, `mail_samples/`, and `reports/output/`,
> including the optional reimbursement anchors). Tests/examples use fake placeholders
> (`Example Non-profit`, `treasurer@example.org`). The repo is **public**; the data is **private**.

## 1. Overview

A command-line Python toolkit for budgets, financial reports, and reimbursement review.
**Google Sheets holds the budget data**; a private local email archive and review bundle hold
reimbursement evidence. It generates HTML reports, including a browser-readable review queue and
a five-report private Main Report Set built from a read-only CFO workbook (`end-to-end-run`).
An optional, separate web proof offers a fixed six-request fictional queue with shared comments and
an administrative reviewer-to-processor handoff, while retaining its single-request modes. Real Cloud Run comments acceptance (M6)
has passed; hosted handoff acceptance (M7) has also passed. There is no LLM dependency or Apps Script; scheduled
financial reports use GitHub Actions.

## 2. Stack

| Layer | Tool |
|---|---|
| Language | Python `>=3.12` |
| Build / deps | `uv` + `hatchling` |
| Sheets/Drive | `gspread` 6.x + `google-auth` (service account) |
| Gmail (optional) | `google-api-python-client` + `google-auth-oauthlib` (user OAuth, `gmail.readonly`) |
| Analytics | `pandas` |
| Charts | `matplotlib` (Agg backend) |
| Templating | `Jinja2`; optional `[pdf]` → `WeasyPrint` |
| Native statement parsing (foundation) | optional `[slides]` → `pypdfium2`, Windows LPAC worker |
| Receipt preparation (optional) | `[receipts]` → `pillow` |
| Main Report Set export (optional) | `[reports]` → `playwright` Chromium (offline PDF/PNG of the four summaries) |
| CLI / config | stdlib `argparse` / `tomllib` |
| Web proof (optional) | `[web]` → `fastapi` + `uvicorn` + `google-cloud-firestore` + `cryptography` |
| Scheduler | GitHub Actions cron (`0 9 1 * *`) + `workflow_dispatch` |
| Lint / type / test | `ruff`, `mypy --strict`, `pytest`, `playwright` (+ `httpx`) — all four are `[dev]` deps |

## 3. Key commands

```bash
uv sync --extra dev --extra web     # add [slides] for native-parser tests, [receipts]/[reports] for
                                    # receipt prep + end-to-end-run export, [pdf] for WeasyPrint;
                                    # uv sync removes extras you omit
uv run playwright install chromium  # required to execute browser tests locally
uv run pytest -q                    # test — with [web] installed this ALSO needs a loopback
                                    # Firestore emulator on FIRESTORE_EMULATOR_HOST, or 6 modules
                                    # fail at collection by design (see § 5)
uv run ruff check .                 # lint
uv run ruff format --check .        # format check
uv run mypy --strict np_finance    # typecheck
```

No live-Sheet write. Each comment names any local file the command touches:

```bash
uv run np-finance analyze                                # reads Budget Timeseries; no writes
uv run np-finance snapshot                               # safe CSV + exact tagged entered-value JSON under snapshots/<utc>/
uv run np-finance sync-budget --fy 2027                  # dry run: prints the diff, no writes
uv run np-finance fetch-mail --since <date> --dry-run    # counts; MAY mint secrets/gmail-token.json
uv run np-finance ingest-receipts --source mail_samples --profile --originals-only  # no writes
uv run np-finance map-receipts --source mail_samples                                # no writes
uv run np-finance update-reimbursements --dry-run       # validates local refresh; no bundle/HTML/Sheet writes
uv run np-finance end-to-end-run --as-of <date> --dry-run  # reads both workbooks + bundle; no writes
```

These write. Each comment names exactly what:

```bash
uv run np-finance check                                  # writes+deletes a probe row (test sheet)
uv run np-finance normalize                              # LEGACY: writes the live transactions tab
uv run np-finance report --fy YYYY --variant both        # HTML + 1 report_log row per variant
uv run np-finance sync-budget --fy 2027 --apply          # writes amount/notes to Budget Timeseries
uv run np-finance fetch-mail --since <date>              # .eml into [gmail] inbox_dir; no Sheet
uv run np-finance map-receipts --source mail_samples --write-tab Reimbursements  # replaces it
uv run np-finance report-reimbursements                  # atomically replaces private HTML (+ receipt sidecar if present); no Sheet
uv run np-finance update-reimbursements --fetch-since <date>  # .eml + private bundle + HTML; no Sheet
uv run np-finance end-to-end-run --as-of <date>          # private bundle + main-report-runs/<id>/ + pointer/copies; no Sheet
uv run np-finance end-to-end-run --as-of <date> --adjustments-file <json>  # same + journal rows in OUR Assumptions tab
```

Every live-Sheet writing verb above snapshots first, except `check` (it deletes its own probe row).
The email/report writers touch only gitignored local artifacts and use idempotent or atomic writes;
they never send email or write a Sheet. Receipt commands use `[fiscal_year] start_month` from config;
`--start-month` is an intentional override. `map-receipts` uses optional private
`[receipt_mapping] received_since` as its inclusive ledger cutoff; `fetch-mail --since` controls
acquisition only. `--received-since` overrides the configured cutoff and `--all-received` disables
it for one run. Filtering occurs before dedup. `ingest-receipts --profile` remains a full-source
view. `map-receipts` must cover `mail_samples/` in ONE run so all sources deduplicate together.
These rules are stated in full — and owned — by
[docs/loading-receipts.md](docs/loading-receipts.md).

## 4. Directory layout

```
np_finance/        package (flat layout): config, ids, schema, models, sheets,
                    backup, etl, cli, gmail_source (the ONLY Gmail surface: pinned
                    read-only OAuth + query/list/fetch + deterministic .eml writer),
                    receipt_ingest (.eml/.mbox parser + profiler),
                    receipt_map (Submission → flat "Reimbursements" ledger rows),
                    reimbursement_events (strict private anchors, actors, proposals, payments,
                    and item-complete operator reviews),
                    reimbursement_pipeline (stable original/supplemental evidence + scoped reducers),
                    reimbursement_report (strict schema-v2 bundle + v1 migration + deterministic
                    HTML/email rendering),
                    receipt_viewer (validates the optional private `<bundle>.receipts.json`
                    sidecar of PNG/JPEG receipt pages + fingerprinted item locations that the
                    queue HTML embeds as click-to-view source receipts),
                    budget_sync (editable-budget-tab → Budget Timeseries reconcile),
                    report_source (Budget Timeseries → report/analyze inputs),
                    treasurer_slides (strict private models + a Windows LPAC-isolated native-text
                    parser foundation; later Wave 1 steps add OCR, facts, review, and Slides),
                    budget_import (LEGACY one-shot budget loader),
                    shared_workflow/ (optional [web] proof — app, auth, catalog, config, and
                    packaged fictional bundles; NOT a top-level dir, it lives in the package),
                    main_reports/ (Main Report Set: read-only CFO sources, reconcile,
                    adjustments journal, facts, render/export, runner = end-to-end-run),
                    analytics/, reports/(templates/)
tests/              fake-org fixtures + mocked gspread; test_smoke_pipeline.py is the wiring gate
.github/            last-run.txt (scheduler keepalive) + workflows/ci.yml (PR gate)
                    + workflows/monthly-report.yml (cron — reports only, no mail)
secrets/            gitignored — service-account.json, gmail-client-secret.json,
                    gmail-token.json (minted at first consent; never printed)
mail_samples/       gitignored — fetched .eml + legacy Takeout .mbox, side by side (flat)
snapshots/          gitignored — safe CSV + exact tagged userEnteredValue .raw.json backups
config.toml         gitignored private config; config.example.toml ships fake values
                    (incl. optional [receipt_mapping] and [gmail] blocks)
docs/               public guides and supporting contracts; plans/master_plan.md owns all execution/status
docs/               operator guides, light/dark SVG workflows, fictional report screenshots,
                    and an editable fictional treasurer-snapshot.pptx example
deployment/         committed shared-workflow deployment assets (deployment/shared-workflow)
scripts/            identity guard, README screenshot capture and PowerPoint export helpers,
                    shared_workflow_smoke.py (local emulator/wheel/browser factory),
                    stage_shared_workflow.py (restricted-import source staging)
```

## 5. Architecture

- **Optional shared-workflow proof** (`np_finance/shared_workflow/`, `[web]`): separate FastAPI/Uvicorn
  entry point, strict `PTA_WORKFLOW_CONFIG` JSON, verified IAP assertions, two pinned subjects,
  and bounded Firestore transactions. It loads only its packaged fictional bundles through
  the existing offline validator; it never discovers private CLI configuration or imports
  the CLI/Sheet/Gmail clients. `identity` mode never creates a store; `comments` mode provides
  a shared request and append-only plain-text comments, capped at 100 events. `handoff` mode
  adds reviewer approve/not-approve and processor administrative completion through the same
  transaction lane. Opt-in `queue` mode composes six independently validated Stores and serves
  authenticated summaries at `/api/requests`, the queue at `/`, and details at `/requests/{id}`.
  The catalog is package-owned; there is no creation/import or arbitrary discovery. Queue summaries
  reuse full-history reads under one request deadline; one failed row fails the whole list.
  Both outcomes are final; comments preserve state/owner in every state.
  Role checks precede receipt retries, which precede cap/state/version checks. There is no
  import, reset, or payment route. Production rejects emulator/test settings.
  `scripts/shared_workflow_smoke.py` is a nonpackaged local test factory using ephemeral keys,
  a real loopback emulator, an installed wheel, and headless Chromium. Test modules requiring
  the emulator fail when `web` is installed and `FIRESTORE_EMULATOR_HOST` is missing.
  See [docs/shared-workflow-proof.md](docs/shared-workflow-proof.md) for all commands,
  source staging, the fixed Cloud Build image-inspection recipe, and repeatable M6/M7 procedures.
  M6 and M7 / Steps 33 and 35 are verified DONE; the approved live queue is Steps 36–37.

- **Data layer** (`sheets.py`, `schema.py`, `models.py`, `ids.py`): one Google Spreadsheet.
  `schema.py` (column lists) and `ids.py` (ID formats) are **single sources of truth** — tests
  assert column identity with `is`. The full `schema.TABS` registry (`transactions`, `receipts`,
  `budget`, `events`, `report_log`) remains the column-shape source of truth, but the LIVE toolkit
  provisions/validates only `schema.REQUIRED_TABS` (just `report_log`) via `check` / `init-sheet`
  / `snapshot`. `report` / `analyze` source from the operator-maintained **Budget Timeseries** tab
  (`report_source.py`) and `report` writes one row per run to `report_log`; the other canonical
  tabs (filled by the legacy `normalize` / `import-budget`) are optional and may be deleted. IDs
  are stable, human-readable, fiscal-year-scoped (`TXN-FY26-0001`); Python assigns missing IDs and
  never rewrites existing ones.
- **Editable budget ↔ DB** (`budget_sync.py`): the operator hand-edits a readable **"FY&lt;fy&gt; Budget"**
  tab (styled after the hidden "Budget Share" tab); `sync-budget` reconciles those edits back into
  the Budget Timeseries. An optional private `sheets.budget_tab_template` overrides the editable
  tab title; `{fy}` is replaced with the requested year and the default remains `FY{fy} Budget`.
  PURE `parse_budget_tab` + `plan_budget_sync` (matches `(type, raw_category)`
  within `(fy, proposed)`), CLI orchestrates. Default dry-run diff; `--apply` snapshots first
  (`backup.snapshot_raw_tab`, safe CSV + exact tagged entered-value JSON) then writes ONLY changed amount/notes cells +
  appends new lines via schema-independent `SheetsClient.update_cells` / `append_raw_rows`. Never
  touches actuals, other years, or enrichment columns; removed lines are flagged, never deleted.
- **ETL** (`etl.py`): normalize legacy rows, assign IDs, dedup via `(date|amount|payee)` hash,
  flag ambiguous rows `needs_review`, snapshot-before-write. Idempotent.
- **Analytics** (`analytics/`): pandas aggregations + multi-year trends.
- **Reports** (`reports/`): builder computes a data model → Jinja2 renders internal + external
  variants (matplotlib charts; optional WeasyPrint PDF). **Real financial reports are never
  committed** — local output goes to gitignored `reports/output/`. The monthly workflow uploads
  both variants as Actions artifacts, downloadable by signed-in readers of this public repo.
  Private Drive upload is not implemented. Committed README examples use only fictional data.
- **Reimbursement refresh** (`reimbursement_events.py`, `reimbursement_pipeline.py`,
  `reimbursement_report.py`): stable-keyed original submissions plus an append-only supplemental
  email/event lane in a strict private schema-v2 bundle (with explicit v1 migration) and
  deterministic Jinja HTML. Exact RFC ancestry or a strict private anchor is required before
  follow-up evidence can mutate a ticket; unmatched/ambiguous mail remains visible. Existing
  reviewed evidence fails closed if it changes or disappears. Secondary approval applies only to
  an exact parsed proposal and trailing prose is not interpreted. Under schema-v2 anchors, payment
  is recorded only from exact `payment_links` (strict Zelle grammars, per-reference bindings,
  atomic group validation) or audited `operator_payments`; thread anchors and direct links never
  authorize payment, and operator records are content-addressed (a persisted review cannot be
  amended in place). A settled claim may retain declined lines when its approved lines were paid,
  preserving both amounts separately. `report-reimbursements` is
  offline; `update-reimbursements` may acquire Gmail first but never sends mail or writes Sheets.
  **Receipt viewer** (`receipt_viewer.py`, `reports/templates/receipt_viewer.*.j2`): `build_report`
  auto-detects a sibling `<bundle>.receipts.json`, validates it (exact keys, image hashes, item
  fingerprints via `item_fingerprint`, in-bounds boxes, path containment, 20 MiB/page and 100 MiB
  total), and embeds the pages so clicking a queue item opens its receipt with red outlines; an
  invalid or stale sidecar stops HTML replacement, and an absent one renders "Receipt not linked".
  The report command prints linked and unlinked item counts after validation.
  Locations are prepared offline by an operator or assistant; the toolkit never OCRs, downloads,
  or auto-matches at render time ([docs/receipt-viewer.md](docs/receipt-viewer.md)).
- **Treasurer-summary foundation** (`treasurer_slides/`): strict private models plus an optional
  Windows-only native-text parser in a pre-read LPAC boundary. It accepts private PDF bytes only
  after attestation, tests with fictional fixtures, and fails closed before a statement read on
  non-Windows hosts. It is not yet an operator command or Google Slides workflow; later Wave 1
  steps add OCR, finance facts, review, and presentation creation.
- **Main Report Set** (`main_reports/`, CLI `end-to-end-run`; guide
  [docs/main-report-set.md](docs/main-report-set.md)): `runner.run` takes the local writer lock,
  captures the CFO workbook through a `spreadsheets.readonly` client, refreshes the reimbursement
  bundle/receipts with the same components as `update-reimbursements`, records journal rows only
  for an explicit `--adjustments-file` (then recaptures), stages bundle + sidecar + pages byte
  for byte into an immutable `<output_dir>/<run-id>/`, renders five reports, validates the set
  and manifest, then atomically replaces the single pointer `main-report-set.html` (the folder
  above `output_dir`, same private-path guard) and refreshes compatibility copies one by one
  (per-copy results, `partial` state, exit 1, pointer kept). Every failure before the switch
  (typed, unexpected or Ctrl+C) leaves every published file unchanged and writes a value-free
  `failed-runs/<run-id>.json` (stage, code, error type only, journal writes, bundle digests
  before/after the in-place refresh); Ctrl+C exits 130. `--dry-run` writes nothing and refuses
  mail/adjustment options. No bank PDF extraction, scheduler, mail sending or CFO workbook write.
  The four summaries are one-page US Letter board briefs; the P&L adds a landscape appendix.
  The visual contract, owned by
  [docs/plan-reference/main-report-design.md](docs/plan-reference/main-report-design.md), is
  enforced by Chromium page-count tests. Audit detail appears as counts plus pointers to
  `records/*.json`. Source bindings match CFO tabs by NAME, so a CFO rename needs a config update.
- **Access:** Sheet/Drive access uses a Google **service account** (the Sheet + Drive folder are
  shared with its email); its JSON key is gitignored locally and supplied as a base64 GitHub
  Actions secret in CI. Optional Gmail fetching uses a separate OAuth Desktop-app client plus a
  user refresh token. Those Gmail credentials are also gitignored and deliberately never enter CI.

## 6. Current state

**Same-day follow-up supersedes the mail blocker below:** read-only Gmail consent succeeded;
all 138 listed October 1-28 messages are archived, and the ordinary October 23-28 fetch passed.
A second live run published all five reports with seven new submissions. Five unique check photos
were visually inspected and matched privately, including a two-check full-request match backed
by an earlier posted bank row. Payment statuses remain unchanged pending reconciliation: the
current reducer cannot accumulate partial checks. See the same-day retry record in the report
guide. No financial-acceptance claim is implied.

**Latest operational run (2026-10-28):** all five reports published and all compatibility copies
refreshed. Gmail re-consent timed out after token expiry; local mail remains through 2026-10-23.
Do not call the reports mail-current through the as-of date or financially accepted: 5,637
unresolved discrepancies, 8 issues and 19 coverage flags remain. Category Mapping now includes
date columns in the private signature, but classification does not apply their limits. New
self-emailed checks remain uninspected; schema-v2 automatic payment links are Zelle-only, while
verified checks can use audited `operator_payments`. See `docs/main-report-set.md` for the run
record and `docs/loading-receipts.md` for check handling. Focused tests: 234 passed; no full-suite
rerun. Step 63 remains in progress.

**Naming migration delivered (2026-10-26).** Use the `np-finance` checkout and CLI,
with Python package `np_finance`. The renamed runner published all five reports.
The connected workbook's 36 tabs were scanned and eight stale text cells corrected;
readback confirmed other entered values/formulas, formatting, notes and validation
unchanged. Public source is archived under `docs/archive/pta_finance/`; private
cell-level audit evidence remains ignored. See `docs/project-rename.md` for external
hooks and retained compatibility identifiers. The old empty checkout's removal is
blocked; GitHub's old URL redirects to the same live repository. Financial
acceptance below remains open.

**Phase CFO Steps 57–62 (#96–#101) are DONE (2026-10-22)**: read-only CFO source import,
processor-to-bank reconciliation, the append-only Assumptions adjustments journal, school-year/P&L
facts, the five-report render/export, and `end-to-end-run` (runner, CLI, guide, bounded smoke with
fake workbooks and real renderers/publication). Final gate: 2,176 passed, 3 environment skips,
across every module except the six emulator modules.

**Step 63 (#102) is in progress.** Live sets were published on 2026-10-22/23.
- Live-only fixes: `5dc3c93` (real export labels, dates, POS type, 429 backoff) and `54595fc`
  (a split typo publishes with an explicit remainder).
- **Step 64 (#104) DONE (2026-10-23):** the summaries were rebuilt as one-page board briefs.
- Still open: a category crosswalk (budget actuals read Unknown without it), binding the CFO's
  new "Transactions"/"WIX Settlements" tabs, and operator acceptance.
- The reimbursement queue is current through 2026-10-23 mail, and the 10/21 Zelle batch is
  recorded privately.

**Phase 10 action queue is paused during Step 51 (#87).** The standalone archive scanner and
fictional tests are unfinished in a preserved worktree, not merged to main. Focused and static
checks passed; the Step 51 full suite was interrupted and independent review has not run.
Fix subject-only evidence drift before review. Steps 52–55 and attended Step 56 remain pending;
the [resume handoff](docs/phase10-build-handoff.md) has the exact worktree and gates.

**Phase 9 Step 38 (#72) is complete.** PR #93 passed all three CI jobs; the full post-merge
local suite passed 1,253 tests with 3 expected skips.
`playwright` ships in the `dev` extra. The `lint-type-test` job runs its full suite with a fresh,
empty Playwright browser directory and asserts that both receipt-viewer browser cases skip.
The test skips only when Playwright reports its executable missing. `shared-workflow` installs
Chromium and asserts that both receipt-viewer viewports run without skips. The three CI jobs
remain separate. The defect began at `7eb0c4f`; the preceding green
run was `b1e0a2c`.

**Phase 9 receipt autofill is partially built.** Steps38-40 are DONE, including the bounded image decode child, shared process_limits wrapper and allowlisted asset fetcher. Step41 is BLOCKED after its second3/3 iteration cap on2026-10-10: glyph measurements pass, but Windows timing risk needs operator disposition and the full gate needs a quiet-host rerun. Preserve its candidate. Steps42-49 remain pending/conditional; the remaining Phase 9 plan is not complete. A separate configured CLI integration shipped on 2026-10-21: allowlisted uploads, isolated image normalization, bounded sandboxed Chromium PDF pages, and conservative local OCR suggestions now run before HTML rendering. This does not mark the blocked Step 41 candidate or Steps 42-49 complete. The [master plan](docs/plans/master_plan.md) owns status and sequencing; [supporting contracts](docs/plan-reference/receipt-autofill-contracts.md) preserve exact schemas. Human red outlines and existing receipt fingerprints remain unchanged.

**Receipt viewer and configured end-to-end preparation (2026-10-21).** Queue items open
source receipts with red outlines from the private `reimbursement-report.receipts.json` sidecar.
The current bundle has 303 items: 218 linked across 260 embedded pages (217 reviewed annotations and one automatic
source-only suggestion) and 85 unlinked older or
structural lines. All active purchase lines are linked; the remaining active unlinked entry is a
replacement-check placeholder. Original uploads and prior annotations are retained privately.
With `[receipt_refresh]` configured, `update-reimbursements` prepares future uploaded sources before
rendering, preserves saved locations, labels automatic OCR suggestions for review, and attaches
source-only pages when no unique line match is available. It writes a separate review/refusal
summary and enforces the existing image budgets. See [docs/receipt-viewer.md](docs/receipt-viewer.md).
Private backfill proofs and backups live under `reports/output/.work/receipt-link-20261021/`.

**Shared workflow Step 32 delivered (2026-09-12 UTC).** The optional comments-only service passed local HTTP/browser/emulator and installed-wheel checks, the complete main-checkout suite, six independent reviews, and feature CI. Step 33/M6 subsequently passed actual cloud observations and operator acceptance on 2026-09-12. The private record satisfies the Phase B entry gate. Handoff behavior now has local implementation and automated coverage; M7 / Step 35 cloud acceptance now passes; all fifteen observations and the operator wording judgment are recorded privately. See the [delivery record](docs/shared-workflow-proof-sync.md#step-32-delivery--2026-09-12-utc).

**README refresh accepted (2026-09-08).** Public examples show the real reimbursement renderer
with fictional data and an editable native PowerPoint snapshot. The snapshot is a presentation
example, not evidence of a shipped slide-generation command. Workflow diagrams have matching
light/dark SVG sources; regeneration instructions are in the README.

**v1 automated build COMPLETE (Steps 1–8, issues #1–#8 closed).** The full pipeline works end-to-end
under test: Sheets client, ETL/normalize, analytics, internal/external reports (runtime PII guard),
smoke gate, and the monthly GitHub Actions workflow. The full test suite, `mypy --strict`, and Ruff
gates pass. **Treasurer-summary Wave 1 Step 15 is complete, but it is only a foundation:** the
optional `[slides]` extra runs native-text PDF parsing inside an attested Windows LPAC worker, with
fictional fixtures proving the boundary and non-Windows hosts failing closed before a statement
file is read. It is not yet an operator-facing slide command; OCR, reconciliation, facts, review,
Google creation, and private acceptance remain Steps 16–25. **Phase-4 receipt ingestion has shipped
end-to-end:** `receipt_ingest.py` (`.eml`/`.mbox`
parser + PII-free batch `Profile` + `Re:`/`Fwd:` dedup) + `receipt_map.py` (`Submission` → flat ledger
rows) drive the `ingest-receipts` (preview / `--profile`) and `map-receipts` (`--write-tab`) CLIs,
which land receipts in a flat **Reimbursements** Sheet tab (via `SheetsClient.replace_tab_grid`) that a
dropdown-driven **Receipts Explorer** dashboard reads; operator load guide in `docs/loading-receipts.md`.
`map-receipts` now partitions recognized originals by the optional inclusive
`receipt_mapping.received_since` outer-header date **before** its single mapper/dedup call, reports
the effective source + exclusion count, rejects missing/malformed headers under an active cutoff,
and refuses every zero-ledger-row `--write-tab` before constructing the Sheet client. Mapping
without explicit `--start-month` freezes one required config snapshot before category/source
parsing and reuses it for fiscal-year and cutoff policy; non-finite amounts remain reviewable.
Every receipt CSV uses the centralized formula-safe boundary, and full-grid pre-write backups pair
a safe inspection/import CSV with versioned tagged `userEnteredValue` JSON so even the first
replacement of an external grid preserves formulas versus identical literal text plus native
string/number/boolean/empty types. Snapshot directories are claimed atomically and collisions use
a suffix instead of overwriting an older set. Formatting/comments are not captured; Sheets version
history remains the primary recovery path, and there is no automated JSON restore command.
**The reimbursement refresh generator has shipped**
(`docs/plans/master_plan.md`, closeout issue #24): `report-reimbursements` rebuilds the private HTML
offline from one strict schema-v2 bundle, while `update-reimbursements` optionally fetches mail,
refreshes stable-keyed original submissions plus supplemental email events, appends only genuinely
new submissions as unreviewed, supplies non-authoritative item-level recommendations, and renders.
Exact RFC/private-anchor linkage supports follow-up receipts, clarification, payment, and scoped
secondary approval while quarantining ambiguity; existing reviewed evidence fails closed if it
changes or disappears. Neither command sends mail or writes Sheets. **Strict payment-confirmation lanes landed 2026-09-06**
(`01f7bff`, merge `aa9b1b1`): schema-v2 anchors carry `payment_links` (two exact Zelle grammars,
per-ticket reference-digest bindings, atomic quarantine) and `operator_payments`; three fail-closed
majors from the landing review remain open as the next fix step (see
`docs/plan-reference/reimbursement-refresh-contracts.md` § 2026-09-06 amendment; master REPLAY-1 through REPLAY-3). The Step 36 delivery gate
has **1,231 collected tests** with dev/slides/web installed and the local Firestore emulator running: 1,228 passed and 3 unchanged existing skips in both candidate and main; all 281 web cases pass without skips. Strict package mypy, Ruff, packaging/privacy checks, installed-wheel browser smoke and six fresh independent lenses pass, as did all three CI jobs **at that time** — that 1,231 figure predates `7eb0c4f`, which added the receipt-viewer suite, and the resulting CI failure was repaired by Step 38 (PR #93 all three jobs green; full main suite: 1,253 passed, 3 expected skips). Hosted handoff acceptance passed M7 / Step 35. The M8 image from delivered source `7f07ba3` passed actual cloud build and inspection; deployment and two-account acceptance remain pending in M8 / Step 37. Resume from private image and baseline receipts; do not repeat completed build steps.
**The Gmail read-only ingest connector has also shipped** (`docs/plans/master_plan.md`,
tracking span #15–#22; deferred #18 and its umbrella #22 remain open): `gmail_source.py` + the
`fetch-mail` CLI replace the manual Google Takeout export —
user OAuth pinned to `gmail.readonly` (exact-equality-tested, re-checked at runtime), a date-scoped
`after:`/`before:` query (no sender/subject filter, by design), and an idempotent `.eml` writer whose
filename is `<sanitised Message-ID stem>-<8 hex of sha256(full raw message bytes)>.eml` — the hash is
over the **whole message**, never over the Message-ID (amended 2026-08-25 after five extraction/
truncation collision vectors; the Message-ID supplies the readable stem only). Files land **beside**
the `.mbox` archives in `mail_samples/` so ONE `map-receipts` run dedups both
(`docs/plan-reference/gmail-ingest-contracts.md` § Design Decision 10). `fetch-mail` prints counts only — never
a subject, sender, or message id. **The cron half is deliberately NOT built:** no OAuth token goes
into CI (a personal-mailbox refresh token in a public repo's Actions secrets would expose the whole
inbox), so fetching is local-only and hands-on and the monthly workflow still does reports only
(§ Design Decision 7). OAuth consent stays in **Testing** mode with a test user — publishing to
Production would need a homepage + privacy-policy URL this project has no reason to host — so the
refresh token expires ~7 days after consent and a browser re-approval is **expected behaviour**, not
a bug (issue #18 tracks the longevity check). Known gap, still open with no tracker of its own:
submissions sent only to a *second* mailbox during a role handover are not in the fetched mail and
cannot be recovered by re-fetching — a thin month is the signal that a second, label-scoped export
is needed (found during the backfill, closed issue #20; `docs/loading-receipts.md` carries the
operator handling). Remaining: Budget Timeseries roll-up; live Drive fetch of linked receipt PDFs.
A **`sync-budget` command** (`budget_sync.py`) also landed: it reconciles an editable, operator-
maintained **"FY&lt;fy&gt; Budget"** Sheet tab back into the Budget Timeseries (dry-run diff by default;
`--apply` snapshots first, then writes only changed amount/notes cells + appends new lines; never
touches actuals/other-years/enrichment; removed lines flagged not deleted). **Google credentials are configured + working** — `secrets/service-account.json` (gitignored) +
`config.toml`; `np-finance check` round-trips read+write against the live Sheet (M1 service-account
setup + M2 real-sheet smoke are DONE). **Next = operator-gated observation:** M3 monthly-report run
(plan §11 Manual Steps). Live Drive upload is deferred to Phase 2 (`google-api-python-client`).

Current reimbursement review update (2026-10-28): manual follow-ups share the queue;
original item sums, form totals and reviewed totals are visible together. Corrected rows
and receipt dialogs retain the original claimed amount. Receipt-backed decisions belong
in private operator reviews, with verified item/tax/total regions and fresh fingerprints.
The focused pipeline/report/viewer/refresh/runner gate passed 223 tests; strict mypy and
changed-file Ruff/format passed. This does not complete Phase 10 or financial acceptance.

## 7. Environment requirements

- Windows 11 + Python `>=3.12`; `uv` on PATH. No `pip` (uv-managed).
- **Playwright is a `[dev]` dependency, not screenshot-only.** Four test modules (plus
  `tests/conftest.py`) import it. Run `uv run playwright install chromium` to execute browser tests
  locally; the receipt-viewer and `test_chromium_*` Main Report Set tests skip when the executable
  is absent (CI asserts exactly which). The shared-workflow browser tests and smoke require the
  binary and fail without it.
- **For a non-dry `end-to-end-run`:** `uv sync --extra dev --extra receipts --extra reports` plus
  `uv run playwright install chromium` (PDF/PNG export runs offline in headless Chromium,
  sandboxed on Windows); the CFO workbook shared **read-only** with the service account; an
  optional private `[main_reports]` block in `config.toml` (see config.example.toml and
  docs/main-report-set.md).
  The README capture helper additionally pins Playwright 1.58.0 ephemerally, and exporting the
  example slide requires desktop PowerPoint on Windows.
- **For the full local suite with `[web]`:** a loopback Firestore emulator reachable via
  `FIRESTORE_EMULATOR_HOST`. Those modules fail at collection rather than skipping without it, by
  design — a missing emulator must never look like a pass.
- **For the optional Treasurer Slides native-text foundation only:** a Windows host and
  `uv sync --extra dev --extra slides`. `pypdfium2` runs only in the LPAC worker; there is no
  supported operator command until the remaining Wave 1 steps ship.
- A Google account with a Cloud project (Sheets API + Drive API enabled) and a service account
  whose JSON key sits at `secrets/service-account.json`.
- The target spreadsheet + Drive folders shared with the service-account email (Editor).
- **For `fetch-mail` only (optional):** the Gmail API enabled in that same Cloud project, plus an
  OAuth **Desktop app** client whose JSON sits at `secrets/gmail-client-secret.json`, and a
  `[gmail]` block in `config.toml`. The service account is unusable here — reading a personal
  mailbox needs user OAuth (Workspace domain-wide delegation is the only alternative). First run
  opens a browser for a one-time read-only consent; `--dry-run` still mints the token, by contract.
  Consent shows an "unverified app" warning (`gmail.readonly` is a restricted scope) — clear it via
  Advanced → "go to … (unsafe)", but ONLY for the Desktop-app client the operator created themselves
  in their own Cloud project (SETUP.md §6 step 5); this is never general advice for a consent screen
  they did not initiate. Console labels drift: prefer the deep links
  (`console.cloud.google.com/auth/overview`, `/auth/clients`, `/auth/scopes`, `/auth/audience`), and
  do not upload a logo (it triggers app verification).
- **For supplemental reimbursement linkage/review only (optional):** a gitignored
  `reports/output/reimbursement-anchors.json` beside the private report bundle. It contains strict
  RFC/direct links, configured actor addresses, item-complete operator reviews, and (schema v2)
  exact `payment_links` / `operator_payments` payment records; committed code
  and documentation must never contain its real identities or decisions.
- **Never print, `cat`, or `Get-Content`** `secrets/gmail-token.json` or
  `secrets/gmail-client-secret.json`.
  Metadata checks (`Test-Path`, size) and effect-based verification (run `fetch-mail --dry-run`,
  check the exit code) only — the token file holds a live refresh token.
- **Gmail consent stays in Testing mode with a test user, by decision.** Production would require a
  homepage + privacy-policy URL this project has no reason to host, so the refresh token expires
  ~7 days after consent and hands-on runs need a browser re-approval roughly weekly — expected, not
  a fault. Mail fetching is **local-only by design**: there is **no Gmail credential in CI** and the
  monthly workflow does reports only.
- Optional `[pdf]` extra needs WeasyPrint's Pango/Cairo native libs (heavy on Windows — PDF is
  optional; HTML is the primary output).
- GitHub repo secrets for CI: `GOOGLE_SA_KEY_B64`, `PTA_CONFIG_B64`.
- **Scheduled-workflow keepalive.** GitHub disables scheduled workflows in **public** repos after
  60 days of no repository activity (the monthly cron firing does **not** count). `monthly-report.yml`
  pushes a `.github/last-run.txt` timestamp each run to reset that timer. If the workflow ever shows
  as disabled, re-enable it one-click under the repo's **Actions** tab → the workflow → "Enable
  workflow", or push any commit.

- Later operator-directed check correction: two verified requests now PAID / SETTLED, with separate actual check references retained and stale clarification prompts cleared. Private bundle/anchor backups and superseded review evidence retained; two refresh previews confirmed persistence and unchanged unrelated tickets. This supersedes the earlier review-only status.

- Manual follow-ups (2026-10-28): optional private `appendix.follow_ups` records now render alongside reimbursements with the existing receipt viewer. The runner captures/preserves them and their image pages; they never add payable totals. Automatic Phase 10 scanning remains paused. The actual private email and check review is now consolidated in the latest reimbursement report.
