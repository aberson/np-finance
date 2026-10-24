# pta_finance master plan

## 1. What This Is

Reusable private finance reporting and reimbursement evidence, with independently scoped delivery tracks.

Proposal: docs/plan-reference/cfo-main-report-set-proposal.html (Phase CFO only).

## Source

Reconciled 2026-10-14. Original bytes and source hashes are preserved in [source map](../plan-reconciliation/source-map.json).

- [plan.md](../archived-plans/plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__fy27-budget-adoption-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__gmail-ingest-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__non-reimbursement-action-queue-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__receipt-autofill-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__reimbursement-board-summary-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__reimbursement-refresh-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__shared-request-queue-plan.md)
- [docs/plans/master_plan.md](../completed/documentation__shared-workflow-proof-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__treasurer-slides-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__treasurer-summary-wave-1-plan.md)
- [docs/plans/master_plan.md](../archived-plans/documentation__shared-ticket-lifecycle-design.md)

## 2. Vision

Maintain a reusable, evidence-preserving small-nonprofit finance toolkit: accurate local reporting and reimbursement evidence, explicit human financial acceptance, and a separately bounded shared workflow. The root roadmap is the spine; concrete feature contracts replace its overlapping descriptions.

## 3. Principles

Public repository, private financial inputs. No real identities, values, private paths or credentials in tracked evidence. Preserve exact money, evidence identities, immutable accepted history, snapshot-before-write, strict validation, atomic publication and fail-closed behavior. An item recommendation is not approval; administrative completion is not payment. No mail sending, Sheet write, cloud deployment or permission widening is authorized by this documentation cleanup. Existing scoped approvals stand, and attended gates stay pending until observed.

## 4. Glossary

LPAC means Windows Low Privilege AppContainer. A capped decode child limits resource cost but is not the LPAC security boundary. M3/M5/M8/M9 are distinct manual/elapsed observation gates. Review keys and item fingerprints come from their production owners, never display references. UAT means actual acceptance, not passing code tests. Budget fiscal year and board reporting year remain distinct.

## 5. How to read this plan

This is the only dispatch/status plan. Each leaf carries scope/problem, status, dependencies, outputs and acceptance. Named supporting specifications retain exact schemas, algorithms and source section numbers; they are not independent queues. Original numeric IDs/issues stay stable; older local budget IDs use BUDGET- prefixes. Symbolic future-wave IDs replace conflicting provisional26-35 numbering. A missing issue is not permission to create one.

## 6. Execution mode

Implement in isolated worktrees using the existing build-step review flags and real repository gates. Execute only an eligible track, never the entire multi-track master unattended. Explicit operator steps, waits, conditional boundaries and holds stop dependent dispatch. Preserve paused Step41 and51 worktrees. No commits, pushes, issues, cloud actions or private-input access were performed by this reconciliation.

## 7. Track structure

Operational acceptance: M3, budget6-7, GmailM5 and coverage. Financial correctness: REPLAY1-3 then downstream roll-up/supersession. Capability: Slides16-25; independent board summary26-31; receipt41-49; actions51-56. Shared workflow: M8/37 then lifecycle engineering. Deferred roadmap is retained separately.

For each track: **goal/scope** are its leaves; **prerequisites** are explicit dependencies; **tests/validation** are the leaf Done-when and supporting spec; **effort** is the estimate sidecar; **gate** requires all code evidence plus separate acceptance; **kill criterion** is violated privacy/evidence integrity, unproven boundary or unresolved architecture; **rollback** retains prior valid outputs, original artifacts and paused work, and uses existing backups/inspected image procedures without destructive reset.

## 8. Decision graph

```text
DONE15 ->16 ->17 ->18 ->19 ->20 ->21 ->22 ->23 ->24 ->25 ->held W2 ->W3 ->W4
26 ->27 ->28 ->29 ->30 ->31 (independent of Slides)
DONE35 ->DONE36 ->37/M8 ->held LIFECYCLE
DONE38/39/40 ->BLOCKED41 ->conditional42 ->43 ->44 ->45 ->46 ->47 ->48 ->49/M9
DONE38 ->PAUSED51 ->52 ->53 ->54 ->55 ->56
REPLAY-1 ->REPLAY-2 ->REPLAY-3 ->deferred TIMESERIES/SUPERSEDE
```

Receipt39 already moved the Job primitive into process_limits; Slides16 uses its wrapper and rebases against render41/43. Run both native suites after shared-file changes. Whichever CLI track lands second rebases: refresh -> fill -> report -> actions. Board runner forwards --no-fill-receipts and stops on exit1; plain uv lock must not upgrade calibrated Pillow. No duplicate implementation of these shared seams.

## 9. Baseline

Project HEAD at inventory: `29856f63a19d8f02a5b3b5f8dfc7bcb519345d1c`. Initial tracked worktree clean. Code1-15 shipped where applicable; M1/M2 complete. GmailM4/11/12 completion is established by subsequent Step13 closeout and project CLAUDE's shipped connector record; longevityM5 remains deferred #18 and umbrella#22 open. Reimbursement refresh1-6 shipped but three documented replay gaps remain. Budget1-5 done;6-7 pending. Shared32-35 including actualM6/M7 accepted;36 built and actual image inspected,37/M8 pending. Receipt38,39,40 DONE; latest source Step41 is BLOCKED on second3/3 cap, not the stale root claim that39 is blocked. Spike glyph verdict is pass; timing risk and quiet-host full gate remain. Preserve branch build-step-1791658930 at2bfae6e; only operator can resolve timing risk, and blocked execution is not a blocked glyph verdict activating42. Step51 unfinished worktree and handoff remain. No implementation/UAT status changed by cleanup.

Budget current editable name is FY2027 - Editable Internal Budget (configurable budget_tab_template); old FY2027 - Internal Budget is comparison, public budget is separate. Historical FY2027 Budget names in source contracts are historical defaults, not new live write instructions. No old Sheet mutation recipe is to be replayed.

## 10. Phases

### Step M3: Monthly-report observation run (end-to-end)
- **Status:** PENDING
- **Type:** operator
- **Source step:** Step 8 (scheduled job, exercised end-to-end); requires Step 7 smoke gate green and Step M2 passed
- **Issue:** N/A (operator step)
- **Data boundary:** the CI run uploads both report variants to an artifact accessible to signed-in
  readers of this public repo. Use only data suitable for that audience in CI; observe private
  figures locally. Private Drive upload remains unimplemented.
- **Commands:**
  ```powershell
  # Local end-to-end (use the current fiscal year — FY2027 as of 2026-09):
  uv run pta-finance report --fy 2027 --variant both
  # CI end-to-end (after adding GOOGLE_SA_KEY_B64 + PTA_CONFIG_B64 secrets):
  gh workflow run monthly-report.yml
  ```
- **What to look for:**
  | Check | Expected outcome |
  |---|---|
  | Internal report | Full-detail schema renders from Budget Timeseries; charts and transaction table are present |
  | External report | Public-safe: totals, by-grade allocation, fundraising progress; **no payee names, no receipt links, no PII** |
  | Output destination | Reports in gitignored `reports/output/` + the ephemeral CI artifact; **not** committed; `report_log` row appended (live Drive upload is deferred) |
  | CI logs | No service-account JSON or config value echoed anywhere in the run log |

**Next manual step: M3** — observe one local and one dispatched monthly-report run end-to-end.

### Step F1: Retire the disconnected budget tabs
- **Legacy alias:** BUDGET-6

- **Type:** operator
- **Problem:** Several old, disconnected full-budget tabs (prior-year copies, the members' pending
  tab, "suggestions" copies) invite exactly the copy-then-rework drift this build is closing. Per the
  operator guide's archive step, they should be unmistakably retired.
- **Do:** once the Zero-Deficit budget is live and verified, rename each superseded tab to
  `ARCHIVE — DO NOT EDIT (replaced by FY2027 Budget)` (or delete). Keep the members' `FY27 Pending
  Approval Expense Budget` tab as a dated archive of the board's decision if useful for the record.
- **Guard:** never delete a tab other live tabs pull cell references from — check first. Snapshot the
  spreadsheet before any deletion.
- **Status:** PENDING

---

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/fy27-budget-adoption-contracts.md). Its complete interface, risk and testing clauses apply.


### Step F2: Point future edits at the one live tab
- **Legacy alias:** BUDGET-7

- **Type:** operator + docs
- **Problem:** The root cause was members working in a copy. The durable fix is process, not tooling.
- **Do:** ensure `docs/using-the-spreadsheet.md` is shared with the people who touch the budget; going
  forward, budget changes are made **directly in `FY2027 Budget`** and synced — which removes the
  transcription step this whole plan exists to perform.
- **Status:** PENDING

---

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/fy27-budget-adoption-contracts.md). Its complete interface, risk and testing clauses apply.


### Step M5: Refresh-token longevity check (wait)
- **Status:** PENDING
- **Problem:** Observe what the OAuth refresh token actually does once the Testing-mode 7-day window has passed. *(Amended 2026-08-26: this step was written to prove a Production setting had taken. Production is unreachable for this project, so the consent screen stays in **Testing** and the expiry is now an accepted, documented cost rather than a defect to detect.)* A same-day check cannot see any of this, because the token is valid for its first 7 days either way.
- **Type:** wait
- **Issue:** #18
- **Produces:** nothing — an observation only
- **Done when:** `pta-finance fetch-mail --since <recent-date> --dry-run` is run in a **fresh shell ≥8 days after consent** and the outcome is recorded. In *Testing* mode a re-consent prompt at that point is the **expected** result (amended 2026-08-26), and re-approving then exiting 0 satisfies this step — it confirms the ~weekly cadence the operator should plan around. A run that exits 0 with no prompt is also fine; neither outcome is a failure.
- **Depends on:** M4
- **Blocks:** nothing — this is a background confirmation, deliberately OFF the critical path so the backfill is not stalled for over a week.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/gmail-ingest-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 16: Add bounded positional Tesseract fallback

- **Problem:** Parse image-only supported pages without using plain OCR reading order, persisting raw
  OCR material, weakening the native statement contract, or letting the one-process PDF worker spawn
  Tesseract.
- **Type:** code
- **Issue:** #43
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/bank_statements.py`,
  `pta_finance/treasurer_slides/{native_sandbox,native_worker}.py`, `.github/workflows/ci.yml`,
  `tests/test_treasurer_slides_bank_statements_ocr.py`,
  `tests/test_treasurer_slides_native_sandbox.py`, and fictional raster PDF fixtures
- **Produces:** the OCR adapter plus a separately broker-launched `tesseract.exe` one-process LPAC
  Job; staged public Tesseract program/data assets and an explicitly tested minimum capability policy;
  Windows Tesseract 5 CI setup; fictional image-only/low-confidence/timeout fixtures; and OCR/
  sandbox regression tests
- **Done when:** real Tesseract 5 TSV at 300 DPI emits the same semantic observation as the paired
  native fixture; x-position—not token order—sets debit/credit direction; financial tokens below the
  threshold, timeouts, process failures, row ambiguity, or unsupported fingerprints block with safe
  errors; parser/OCR versions and evidence persist; raster input and TSV output use bounded pipes,
  while any allowed AppContainer-local fallback directory is removed only after Tesseract exits. The
  PDF worker never launches Tesseract because its Job is limited to one active process. Instead, the
  broker launches staged `tesseract.exe` directly as the one active process in a distinct LPAC Job and
  verifies its token, Job limits, and explicitly enumerated minimum capabilities before it writes
  raster bytes to the input pipe. The OCR process has no network or caller-profile/worktree access and
  never writes private raster/OCR data to ambient disk. Windows CI installs Tesseract and executes the
  real OCR fixture; Linux runs only portable OCR-contract and fail-closed coverage.
- **Coordination (2026-10-09):** receipt-autofill Phase 9 Step 39 (issue #73) moves the Job Object
  primitive from `native_sandbox._make_job_object` into the shared leaf `pta_finance/process_limits.py`,
  keeping `_make_job_object` as a thin wrapper (`docs/plans/master_plan.md` § 4, § 5A).
  Create the Tesseract Job through that wrapper, never by restating the primitive. Whichever step
  lands second rebases and runs both native suites; if Phase 9 lands first, it comments on #43.
- **Depends on:** Step 15
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 17: Select authoritative activity and balance intervals

- **Problem:** Combine overlapping closed statements and current captures without allowing later OCR
  to override closed posted activity, while deriving complete per-account opening/latest intervals.
- **Type:** code
- **Issue:** #44
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/reconciliation.py`,
  `tests/test_treasurer_slides_source_authority.py`, and fictional overlap/balance fixtures
- **Produces:** `pta_finance/treasurer_slides/reconciliation.py`, overlap/balance fixtures, and
  `tests/test_treasurer_slides_source_authority.py`
- **Done when:** closed-monthly precedence, current post-cutoff/pending/latest supplementation,
  semantic overlap equality, exact disagreement resolution, legitimate duplicate occurrences,
  explicit and back-solved openings, multiple-anchor validation, pending-inclusive latest balances,
  mixed account dates, interval filtering, and inclusive boundaries are tested; any source gap,
  contradictory anchor, or unexplained overlap blocks before classification
- **Depends on:** Step 16
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 18: Classify, pair, adjust, and reconcile signed cash

- **Problem:** Apply reviewed rules to every selected transaction and produce exhaustive signed
  contributions without silently dropping refunds, returns, transfers, or prior-period outflows.
- **Type:** code
- **Issue:** #45
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/rules.py`,
  `pta_finance/treasurer_slides/reconciliation.py`,
  `tests/test_treasurer_slides_rules.py`, `tests/test_treasurer_slides_reconciliation.py`, and
  fictional rule/cash-bridge fixtures
- **Produces:** `pta_finance/treasurer_slides/{rules,reconciliation}.py`, fictional rule/cash-bridge
  fixtures, and `tests/test_treasurer_slides_{rules,reconciliation}.py`
- **Done when:** zero/multiple classification matches block; automatic pairs require matching
  pair-key/amount/direction/account/window and uniqueness; ambiguous pairs require exact two-row
  resolution; fundraising chargebacks, spending refunds, paired reversals, boundary-crossing returns,
  posted/pending contributions, one-leg mixed-cutoff transfer rejection, and the exact prior-board
  exclusion follow the contribution table; the exclusion changes only its declared
  numerator/categories/pace; operating-surplus/cash-change equations are exact; negative aggregates
  block; and every account plus the combined bridge reconciles exactly to the cent
- **Depends on:** Step 17
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 19: Read adopted goals and build deterministic summary facts

- **Problem:** Read strict proposed goals through a narrow raw-grid interface and combine them with
  reconciled bank facts into the approved summary, pace, grouping, and narrative contract.
- **Type:** code
- **Issue:** #46
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/budget_goals.py`,
  `pta_finance/treasurer_slides/facts.py`, `tests/test_treasurer_slides_budget_goals.py`,
  `tests/test_treasurer_slides_facts.py`, and fictional grid/fact fixtures
- **Produces:** `pta_finance/treasurer_slides/{budget_goals,facts}.py`, fictional raw-grid/fact
  fixtures, and `tests/test_treasurer_slides_{budget_goals,facts}.py`
- **Done when:** duplicate/blank/missing headers, malformed relevant rows, duplicate logical rows,
  including whitespace/case variants, invalid/non-positive goals, or attempted source writes block;
  proposed income/expense totals use exact Decimal; board/budget calendars and inclusive elapsed-day
  math remain distinct; category fold/tie/Other and largest-remainder rules are exact; tolerance boundaries and deterministic story
  strings are pinned; pace is labeled as a straight-line screen, not a forecast; and all five
  existing `read_timeseries()` callers retain their behavior
- **Depends on:** Step 18
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 20: Encode the approved one-slide and template contract

- **Problem:** Turn approved facts into the exact generic text and geometry required by the locked
  design while keeping organization identity and branding static in a private tagged template.
- **Type:** code
- **Issue:** #47
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/summary.py`,
  `pta_finance/treasurer_slides/template.py`, `tests/test_treasurer_slides_summary.py`, and
  `tests/test_treasurer_slides_template.py`
- **Produces:** `pta_finance/treasurer_slides/{summary,template}.py`, fictional presentation
  structures, and `tests/test_treasurer_slides_{summary,template}.py`
- **Done when:** every approved fact maps to one declared variable role; static identity is not a
  role or request; money/percent/date/story text is deterministic; four spending and five fundraising
  slots preserve totals; stacked/progress geometry stays inside the exact 16:9 contract; and
  missing/duplicate/unknown tags, stale literals, unresolved markers, invalid ratios, overflow,
  overlap, zero totals, or source-facts-hash mismatch block without Google access
- **Depends on:** Step 19
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 21: Create immutable runs and transaction-level fact/slide review

- **Problem:** Persist the complete producer and canonical slide-plan snapshots, then require a
  human-readable digest-bound transaction and slide-string review before any Google client can be
  constructed.
- **Type:** code
- **Issue:** #48
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/pipeline.py`,
  `pta_finance/treasurer_slides/templates/fact_review.html.j2`, and
  `tests/test_treasurer_slides_pipeline.py`
- **Produces:** `pta_finance/treasurer_slides/pipeline.py`,
  `pta_finance/treasurer_slides/templates/fact_review.html.j2`, and
  `tests/test_treasurer_slides_pipeline.py`
- **Done when:** a valid prepare uses Step 20's canonical `SummarySlidePlan`, writes facts and plan
  snapshots atomically with manifest last, and produces stable facts/plan/approval hashes; every
  selected/rejected transaction, financial equation, slide string, and geometry value appears in the
  autoescaped private review; the approval digest binds both snapshot chains; partial writes,
  existing run IDs, bad hashes, bad approval syntax, changed sources, duplicate formatting, and
  canary leakage block; a failed rule/reconciliation pass writes only a private non-approvable
  selector-rich diagnostic; a rejected review requires a new run; and candidate receipt creation
  cannot rewrite prepared files
- **Depends on:** Step 20
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 22: Add exact-scope OAuth and recoverable template bootstrap

- **Problem:** Authorize one dedicated Slides surface and import/validate one private app-owned
  template without duplicate resources, wider Drive access, or permission changes.
- **Type:** code
- **Issue:** #49
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/google_client.py`, `pta_finance/config.py`,
  `config.example.toml`, `tests/test_config.py`, `tests/test_treasurer_slides_auth.py`, and
  `tests/test_treasurer_slides_workspace.py`
- **Produces:** the auth/workspace portion of `pta_finance/treasurer_slides/google_client.py`,
  optional config in `pta_finance/config.py`/`config.example.toml`, fake Google services,
  `tests/test_config.py`, and `tests/test_treasurer_slides_{auth,workspace}.py`
- **Done when:** the granted set must equal `drive.file`; Gmail/missing/extra scopes fail; dedicated
  token load/mint/refresh/atomic persistence and `invalid_grant` guidance are safe; import support,
  one-slide 16:9, tags, and canonical projection hash gate initialization; zero/one/multiple
  broad-anchor bootstrap resources with client/principal/source-hash/role provenance
  create/resume/block across partial failures and pagination; a different OAuth client or
  reauthorized different principal blocks before search; an atomic workspace-init lock serializes
  bootstrap/search/create/manifest and stale-lock recovery is explicit;
  every create uses `ignoreDefaultVisibility=true` and readback proves an unshared exact-parent
  workspace; every private config/PPTX path passes the ignored-or-outside-worktree gate; config omission preserves all legacy loads; failures redact canary IDs/URLs; and no permission/sharing/publish/email method exists in or is called by the boundary
- **Depends on:** Step 21
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 23: Copy and populate one approved candidate idempotently

- **Problem:** Cross the Google write boundary exactly once for an approved run, then reconcile and
  validate the native editable candidate without mutating the template or source workbook.
- **Type:** code
- **Issue:** #50
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/treasurer_slides/google_client.py`,
  `pta_finance/treasurer_slides/pipeline.py`, and
  `tests/test_treasurer_slides_google_candidate.py`
- **Produces:** candidate/render support in `google_client.py` and `pipeline.py`, fake Drive/Slides
  cases, and `tests/test_treasurer_slides_google_candidate.py`
- **Done when:** no Google client exists before digest/local-hash validation; template drift blocks;
  one atomic run lock serializes creators; zero/one/multiple app-property matches create/resume/block;
  OAuth-client/principal equality and broad paginated workspace/run search turn every
  digest/role/MIME/parent mismatch into a block rather than a false zero; copy writes candidate provenance in its original
  request and ambiguous copy reconciles rather than issuing a second mutation;
  pristine/post/other candidate-state classification plus required
  revision makes a lost batch response resumable without blind retry; one atomic batch applies the
  full request plan; copy/readback enforce ignored default visibility, `shared=false`, and the exact
  private parent; readback validates slide/roles/text/geometry; one private create-once receipt records
  the candidate; rerun resolves the same candidate; and template, workbook, permissions, and console
  remain unchanged/redacted
- **Depends on:** Step 22
- **Status:** PENDING

<!-- autofix-applied: 2026-08-31 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 24: Wire CLI, privacy gates, packaging, docs, and local smoke

- **Problem:** Expose the complete one-shot workflow through the installed CLI and prove the local
  producer-consumer chain before real authorization and Google acceptance.
- **Type:** code
- **Issue:** #51
- **Flags:** `--reviewers deep --isolation worktree`
- **Files:** `pta_finance/cli.py`, `scripts/check_no_identity.py`,
  `tests/test_treasurer_slides_cli.py`, `tests/test_treasurer_slides_smoke.py`, packaging/privacy
  tests, `docs/generating-treasurer-summary.md`, `README.md`, `SETUP.md`, `CLAUDE.md`, and `plan.md`
- **Produces:** three commands in `pta_finance/cli.py`; extended `scripts/check_no_identity.py`;
  CLI/privacy/packaging/smoke tests; `docs/generating-treasurer-summary.md`; and status/setup updates
  in `README.md`, `SETUP.md`, `CLAUDE.md`, and `plan.md`
- **Done when:** dispatch resolves all three commands and old commands are unchanged; missing
  extra/config/Tesseract/workspace/approval and stale locks fail actionably; a Windows-only
  60-second smoke uses real pypdfium2 in the Step 15 PDF worker, real Tesseract in Step 16's
  directly broker-launched LPAC Job, real statement/rule/reconciliation/budget/fact/review/
  summary/template-request components, and a fictional in-memory read-only grid to complete
  PDF-to-Slides-request without mocks inside the data pipeline; Linux proves portable/static and
  pre-read fail-closed coverage; tracked-file guard rejects canary private artifacts;
  runtime path-gate tests reject tracked/non-ignored private locations before read/write/network;
  wheel build/isolated install loads package/templates/entry point; full pytest, strict mypy, Ruff,
  existing report/reimbursement/CLI regressions, and identity guard pass; and docs cover diagnostic
  rule authoring, API/consent setup, seven-day Testing tokens, recovery, exact commands, review, and
  privacy boundaries
- **Depends on:** Step 23
- **Status:** PENDING

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 25: Run the private source-to-Google acceptance

- **Problem:** Run this attended acceptance against the real private statements, workbook, OCR
  executable, template, OAuth account, and Google rendering:

  ```powershell
  uv run pta-finance init-treasurer-summary-template --pptx "<private-tokenized-template>" --config config.toml
  uv run pta-finance prepare-treasurer-summary --inputs "<private-input-manifest>" --config config.toml
  Invoke-Item "<private-run-directory>\review.html"
  uv run pta-finance create-treasurer-summary --run "<run-id>" --approval-sha256 "<approval-digest>" --config config.toml
  Invoke-Item "<private-run-directory>\candidate.receipt.json"
  uv run pta-finance create-treasurer-summary --run "<run-id>" --approval-sha256 "<approval-digest>" --config config.toml
  git status --short
  uv run python scripts/check_no_identity.py
  ```

  | Check | Expected outcome |
  |---|---|
  | Template init | Dedicated grant is exactly `drive.file`; one app-owned unshared template is validated under the private folder |
  | Prepare | Real sources yield one immutable run; transaction review and every account/combined equation reconcile exactly |
  | Review | Every transaction, exclusion, headline, category, progress value, pace line, story, and source note agrees with the locked v0 |
  | First create | Exactly one editable, unshared, exact-parent one-slide candidate is recorded in the private receipt |
  | Visual check | Candidate has no clipping, wrapping, overlap, wrong geometry, or theme drift |
  | Second create | The same candidate/readback is resumed; no duplicate appears |
  | Repository check | Source workbook/template/permissions are unchanged and no private artifact is tracked |
- **Type:** operator
- **Issue:** #52
- **Files:** no tracked files; only configured gitignored private inputs/outputs and private Google
  artifacts are inspected or created
- **Produces:** only gitignored private input/rules/run/workspace artifacts, one app-owned private
  template, one private Google Slides candidate, and generic pass/fail plan/issue bookkeeping; no
  tracked code or detailed evidence
- **Done when:** the operator tokenizes a private copy of the approved v0 PPTX; init authorizes only
  the dedicated `drive.file` grant and converts/validates that template; prepare processes the real
  statement set and live budget goals; transaction-level review agrees with the locked v0 on every
  headline, category, exclusion, progress value, pace statement, narrative, and source note; every
  account and combined bridge reconciles; the operator supplies the displayed digest; create yields
  exactly one editable private one-slide candidate; visual comparison finds no clipping, wrapping,
  overlap, wrong bar geometry, or theme drift; rerun resolves the same candidate; source workbook,
  template, and Drive permissions remain unchanged; Drive readback reports the folder, template, and
  candidate unshared under the exact private parent; and git status/identity guard show no private
  artifact tracked
- **Depends on:** Step 24
- **Status:** PENDING

Steps are deliberately sequential producer/consumer slices. Step 14 establishes normalized source
contracts; Step 15 adds native parsing and the enforceable pre-read LPAC boundary as one atomic slice;
Step 16 adds bounded OCR; Steps 17-18 establish bank truth; Step 19 builds summary facts; Step 20
fixes the presentation plan; Step 21 binds both into the reviewed approval; Steps 22-23 cross the
Google boundary in two recoverable stages; Step 24 proves the installed local workflow; and Step 25 is
the only real-service visual acceptance.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/treasurer-summary-wave-1-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 26: Prepare a dated summary review packet

- **Problem:** Expose a preparation command that derives an editable monthly summary packet from validated frozen reimbursement inputs.
- **Type:** code
- **Status:** PENDING
- **Issue:** #56
- **Flags:** --reviewers deep --isolation worktree
- **Files:** `pta_finance/reimbursement_summary.py`, `pta_finance/cli.py`, `tests/test_reimbursement_summary.py`, `tests/test_reimbursement_cli.py`, `tests/fixtures/reimbursement_summary/`.
- **Produces:** `prepare-reimbursement-summary`, strict new private schemas, deterministic facts/suggestions, input snapshots, and synthetic examples.
- **Done when:** The actual CLI prepares a packet with correct date windows, cumulative counts, exact active-C totals, payment deduplication and unknown-check-date handling; conflicting/malformed inputs fail before publication. Suggestions cannot turn unreviewed advice into approval. Repeated preparation preserves earlier edited notes. Existing reimbursement CLI tests pass.
- **Depends on:** none.

<!-- autofix-applied: 2026-09-10 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/reimbursement-board-summary-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 27: Render the accepted one-page HTML design

- **Problem:** Expose a render command that turns a reviewed packet into the approved style of offline board summary.
- **Type:** code
- **Status:** PENDING
- **Issue:** #57
- **Flags:** --reviewers deep --isolation worktree
- **Files:** `pta_finance/reimbursement_summary_render.py`, `pta_finance/reports/templates/reimbursement_board_summary.html.j2`, `pta_finance/cli.py`, `tests/test_reimbursement_summary_render.py`, `tests/fixtures/reimbursement_summary/`.
- **Produces:** `report-reimbursement-summary --html-only`, the generic template, adjacent detailed report, and a receipt with export checks pending.
- **Done when:** The real command reproduces all approved sections with fictional data; every displayed count/date/chart description is derived, text is escaped, case/form links resolve, empty/all-open/all-closed examples render correctly, and stale notes or invalid selections fail without replacing the previous complete HTML. Markup and source-link checks pass.
- **Depends on:** Step 26.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/reimbursement-board-summary-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 28: Preserve an approved one-page export

- **Problem:** Finalize an unchanged reviewed preview into a validated immutable HTML/PDF edition.
- **Type:** code
- **Status:** PENDING
- **Issue:** #58
- **Flags:** --reviewers deep --isolation worktree
- **Files:** `pta_finance/reimbursement_summary_render.py`, `pta_finance/cli.py`, `pyproject.toml`, `uv.lock`, `tests/test_reimbursement_summary_render.py`, `.github/workflows/ci.yml`.
- **Produces:** Default render with PDF/PNG, summary export extra, `finalize-reimbursement-summary`, hash manifests, read-only editions, concurrency/error handling, and browser-export CI coverage.
- **Done when:** Chromium produces one Letter page offline on Windows and Linux; the final command copies precisely the reviewed content, rejects edited/stale inputs and missing/failed export checks, returns an unchanged valid existing edition on retry, preserves old finals on all failures, and creates a separate edition after a legitimate wording change. Overflow and concurrent-write probes fail visibly without corrupting a prior output set. The built wheel contains the template.
- **Depends on:** Step 27.

<!-- autofix-applied: 2026-09-10 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/reimbursement-board-summary-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 29: Provide the monthly Python runner

- **Problem:** Let the treasurer prepare the monthly summary through one local command with the existing refresh behavior.
- **Type:** code
- **Status:** PENDING
- **Issue:** #59
- **Flags:** --reviewers deep --isolation worktree
- **Files:** `scripts/run_reimbursement_summary.py`, `docs/reimbursement-board-summary.md`, `docs/examples/reimbursement-summary-launchers.toml`, `tests/test_reimbursement_summary_pipeline.py`, `README.md`, `CLAUDE.md`, `SETUP.md`, `docs/loading-receipts.md`.
- **Produces:** A runner calling the existing refresh CLI followed by summary prepare/render, concrete setup/recovery/review instructions, copyable launchers, and a private-reference conversion procedure for the accepted payment register.
- **Done when:** The runner accepts the documented dates and forwarded arguments, honors no-refresh/dry-run, stops on the first failure, preserves finals, and prints a usable resume command. The guide explains editing/reviewing notes, separate intake/payment/reporting dates, receipt-proof optionality, one-page failures, and source-review limits. Launcher commands parse and preserve exit status without modifying the workspace registry.
- **Depends on:** Step 28.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/reimbursement-board-summary-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 30: Exercise one complete real-component cycle

- **Problem:** Prove the packaged commands can complete one summary cycle through their actual interfaces.
- **Type:** code
- **Status:** PENDING
- **Issue:** #60
- **Flags:** --reviewers code --isolation worktree
- **Files:** `tests/test_reimbursement_summary_pipeline.py`, `tests/fixtures/reimbursement_summary/`, `.github/workflows/ci.yml`, `docs/reimbursement-board-summary.md`.
- **Produces:** A bounded smoke gate wiring an actual synthetic email archive, anchor/category inputs, refresh CLI, snapshot preparation, note edit, render, finalize, and final manifest verification; no mocks at the producer/consumer boundaries.
- **Done when:** With dependencies/browser already installed, one fixture cycle completes within a 60-second smoke budget, outputs one validated page, and resolves detailed links from the archived copy. Repeating finalization changes no bytes; a second period creates a separate edition; a deliberately changed note requires re-render; a render failure preserves the previous final. Google construction/network access is forbidden in this smoke. Run full appropriate repository quality gates and build/install the wheel before the step is marked done.
- **Depends on:** Step 29.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/reimbursement-board-summary-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 31: Accept the workflow on the treasurer's Windows machine

- **Problem:** Confirm that the installed monthly workflow produces a usable private board packet from the actual reviewed queue.
- **Type:** operator
- **Status:** PENDING
- **Issue:** #61
- **Files:** No code changes; run the acceptance procedure already written in `docs/reimbursement-board-summary.md`.
- **Produces:** Private run evidence, a checked comparison with the accepted reference, and an operator acceptance result or a concrete defects list.
- **Done when:** The operator runs the real helper with the chosen date windows, reviews the suggested wording, verifies a known paid case and a received clarification against the queue, confirms paper checks remain undated where evidence is absent, previews/prints one legible page, and finalizes a new edition. A retry returns the same final and a later run leaves it unchanged. Record source refresh failures as findings rather than weakening evidence rules. A private no-refresh replay reproduces the accepted reference's figures and editorial choices with its narrower payment window. Acceptance may not be claimed solely from unit tests.
- **Depends on:** Step 30.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/reimbursement-board-summary-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 37: Accept the live shared queue with both accounts

- **Problem:** Verify the deployed six-request queue matches independent Google users' durable actions.
- **Type:** operator
- **Status:** PENDING
- **Issue:** #69
- **Progress (2026-09-14 UTC):** Delivered source staging and actual cloud image inspection passed. The checked image and private receipts are retained; no queue deployment or two-account observation has run. Resume after fresh desktop coordination and verification of both accepted M7 baselines, without repeating completed staging/build steps.
- **Files:** Execute the Step 36 M8 runbook; use existing private runtime/env and new ignored `reports/output/shared-workflow/` acceptance records.
- **Existing context:** Step 35 establishes the original completed request/history, Step 36 supplies the new catalog/UI and immutable image inspection, and the same two real subjects remain configured.
- **Produces:** Private M8 observations, source/build/image/revision and policy receipts, preservation comparisons, and an operator functional-proof judgment. No shipped code artifacts.
- **Done when:** Every D7/M8 observation passes with the two pinned real subjects, all six histories survive a fresh revision, the original M7 history remains unchanged, and the operator can locate work, identify next ownership/history, and distinguish administrative completion from payment. Actual image inspection and cloud/IAP observations are required; local tests and preview approval do not satisfy this gate.
- **Depends on:** 36.
- **Parallel-safe with:** none — acceptance runs against Step 36's verified build after Step 35 acceptance.

M8 execution is delegated to the agent wherever mechanical checks and available tools permit; “operator” reserves genuine browser availability/sign-in and product judgment, not a requirement that the user type every command. Do not run Step 36 while the external Step 35 dependency is still open.

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/shared-request-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 41: LPAC render spike — prove glyphs actually rasterize
- **Problem:** pdfium rasterizes on CPU with no GPU or Skia, and the LPAC can read `C:\Windows\Fonts`, but pdfium's Win32 font mapper reaches fonts through GDI/win32k and the worker is launched with no window-station grant. Text *extraction* needs no glyph outlines; *rendering* does. A degraded mapper yields blank or boxed text — silently wrong output that no fake-backend unit test can see. Prove a real LPAC render of a fixture PDF with non-embedded fonts produces legible glyphs before funding the protocol work. **Render path:** the worker has no render path today (`native_worker.py` and `native_sandbox.py` contain no render call), and the LPAC runs only the closed five-file staged allowlist (`native_sandbox.py:36-42`). The spike therefore adds the **minimal render request branch to `bank_statements.py`** — the smallest change that returns one page's raw gray8 pixels from inside the real LPAC, within the existing worker ceilings — selected by the envelope's `operation` = 2 and answering with the `rendered` response shape (§ 5A, LPAC render request). The broker validates that frame before the spike scores it (Produces), and Step 43 later extends and hardens both into the full protocol. It never widens the staged allowlist and adds no test-only staging seam. On the blocked verdict, Step 43 removes this branch, the frame reader, `RenderedPage` and the `ReceiptRenderError` base while implementing the boundary Step 42 records. **Coordinate with [treasurer-summary Wave 1](master_plan.md) Step 16 (issue #43)**, which claims `bank_statements.py` and `ci.yml`: if #43 has landed, rebase and re-run both native suites; if it has not, land this first and comment on issue #43 (a build step never edits another plan's file).
- **Type:** code
- **Issue:** #75
- **Flags:** `--reviewers deep`
- **Produces:** the minimal render request branch in `pta_finance/treasurer_slides/bank_statements.py` (Problem above; Step 43 extends it). With it, so that the spike never scores unvalidated worker output, comes the broker-side reader for the `rendered` frame, together with its tampered-frame tests in `tests/test_treasurer_slides_lpac_render_spike.py`. The reader enforces exact key sets, bounded decompression with an empty-leftover assertion, `len(decompressed) == raw_length == width × height`, the digest check, and `page_number`/`page_count` agreement with the launch. The same step adds `RenderedPage`, the `ReceiptRenderError` base class only (no subclasses), and a single-page broker launch helper. Step 43 extends these and does not rebuild them (operator decision 2026-10-10). The step also produces a committed generator for two fictional fixture PDFs — the non-embedded-font subject and its embedded-font twin (§ 9: no committed binary). The subject is hand-written PDF syntax using the non-embedded standard Type1 `/Helvetica`, following the `_fictional_pdf_bytes` precedent in `tests/test_treasurer_slides_bank_statements_native.py`. The twin carries the same text and is built at test time with `pypdfium2` (`PdfDocument.new()`, the raw `FPDFText_LoadFont` / `FPDFPageObj_CreateTextObj` / `FPDFText_SetText` / `FPDFPage_InsertObject` / `FPDFPage_GenerateContent` calls, then `PdfDocument.save`). It embeds a TrueType face read at test time from the Windows font directory, `%WINDIR%\Fonts\arial.ttf`, which is the usual Windows substitute for Helvetica, so the glyph shapes match. No font byte is committed; `tests/test_treasurer_slides_lpac_render_spike.py` added to the `windows-native-sandbox` job's pytest file list in `.github/workflows/ci.yml` (that job runs a hardcoded file list, so a new test file it does not name never executes); and `docs/findings/step-41-lpac-render.md` recording the measured verdict, every anchor score and the pinned thresholds in every case — plus `docs/findings/step-41-lpac-render-blocked.md` on the failure verdict only
- **Done when:** the `windows-native-sandbox` CI job renders the subject fixture inside the **real** LPAC — never a mocked call — and scores it on two metrics against a **reference**, the embedded-font twin rendered outside the LPAC: *ink coverage* (a pixel is dark when its gray value is below 128; with r = the subject's dark-pixel fraction ÷ the reference's, the score is min(r, 1/r), and 0 when r = 0, so 1.0 means the reference's ink and a blank page and over-inked box glyphs both score low) and *glyph-shape similarity* (normalized cross-correlation with the reference). Each metric's pass threshold *T* is a constant pinned in the test module, and it is trusted only after calibration in the same test, per the workspace measurement-validity rule: the **known-good anchor** (the subject rendered outside the LPAC, where the font mapper works normally) must score above *T*, and both **known-garbage anchors** — an all-white page and a box-glyph page synthesized in code from the reference's glyph bounding boxes — must score below it, i.e. `score(good) > T > max(score(garbage))` on each metric before the LPAC render is judged. A metric that fails its calibration yields no verdict, which is a failure. **The step is DONE on either verdict with the full suite green:** with the LPAC render above *T* on both metrics, the test asserts the pass; below *T* on either (blank or box glyphs), the same measurement is asserted as the blocked verdict rather than left as a red test, and the step also writes the blocked findings file on the branch that merges, so Step 42's predicate can observe it. A spike that cannot produce a measurement at all is still a failure.
- **Depends on:** 38
- **Status:** BLOCKED (2026-10-10, second run). The resume run also ended BLOCKED at its 3/3 iteration cap. review-deep returned NEEDS-WORK with no Block and one bugs Nit: the gating Windows test can time out against the 15 s `wall_seconds` deadline. That deadline covers launch, staging and the response wait, and windows-2022 runner spans were 8.02, 8.95, 15.92, 8.98 and 7.31 s. The scope dispute was resolved by the plan amendment `01d20b5`, after which plan-conformance passed. The spike verdict itself is pass on the dev box and in every CI run (the latest, 38116138438, is green on all three jobs). The DONE-gate full suite on `2bfae6e` is void: it failed only from host resource exhaustion (MemoryError, WinError 1450, and the sandbox worker unable to start) while another session's suite was running, and it must be re-run on a quiet host. The worktree is preserved on branch `build-step-1791658930` at `2bfae6e`, and the operator decides the timing risk.

<!-- autofix-applied: 2026-09-16 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 42: Record the PDF-boundary decision when the LPAC render path is blocked
- **Status:** PENDING
- **Problem:** If Step 41 recorded a blocked verdict, decide and record the fallback PDF rasterization boundary — a capped, short-lived subprocess — as a findings file that Steps 43–44 read at build time. This step must NOT try to amend this plan's later step briefs: `/build-phase` parses every step once at Step 0 and does not re-read the plan mid-run, so an in-place plan edit would never reach Step 43's dispatch. The decision travels as a file instead.
- **Type:** conditional
- **Condition:** `test -s docs/findings/step-41-lpac-render-blocked.md`
- **Issue:** #76
- **Flags:** `--reviewers code`
- **Produces:** `docs/findings/step-42-pdf-boundary.md` — the authoritative boundary decision read by Steps 43 and 44; `docs/plans/master_plan.md` — the § 6.3 pointer to that file only
- **Done when:** the findings file names the exact isolation mechanism, its wall-clock / memory / page-count caps, precisely what an exploit of the PDF parser would reach under it, and how the non-Windows path differs; § 6.3 of this plan is annotated with a pointer to the file (a documentation edit, not a step-brief edit)
- **Depends on:** 41

<!-- autofix-applied: 2026-09-16 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 43: Render protocol across the attested boundary
- **Status:** PENDING
- **Problem:** Implement the PDF rasterization boundary recorded in `docs/findings/step-42-pdf-boundary.md`; **when that file is absent, the boundary is the LPAC worker per § 6.3** and this brief applies as written. Extend the worker's limits envelope with render parameters, extend Step 41's minimal render branch into the full render request and the raw-grayscale-plus-zlib response (or, under a recorded fallback boundary, remove that branch). Then extend the broker-side frame validation Step 41 landed rather than rebuild it. That validation already covers bounded decompression with an empty-leftover assertion, the wire length check `len(decompressed) == raw_length == width × height` (gray8, one byte per pixel), and the digest check. This step adds the remaining § 5A refusals (an unknown `reason`, a `width` or `height` outside the gate, and a `page_count` that disagrees across launches). It also maps every wire-check refusal to the named subclasses below, in place of the `ReceiptRenderError` base. **Output interface to Step 44:** the broker returns each page's validated raw gray8 pixels with its width and height to its caller through `render_receipt_pdf` (§ 5A gives the signature, the `operation` selector, the six new envelope fields with their public values and ceilings, the one-page-per-launch page-count discovery, and every response shape); it encodes no PNG (or any image) — Step 44 passes the pixels to `receipt_pages.pixels_to_page` (§ 5A, § 6.4). The render path needs its own page-dimension gate, bounding both edges — § 5A's `RENDER_MAX_EDGE` and `max_render_raw_bytes_per_page`, applied in the worker before any bitmap is allocated and again by the broker — because it cannot reuse the statement path, which rejects anything that is not US Letter and requires a minimum non-whitespace character count. **Coordinate with [treasurer-summary Wave 1](master_plan.md) Step 16 (issue #43, still PENDING)**, which claims the same three worker files and `ci.yml` for its own bounded-Tesseract path — rebase and re-run both suites if it has landed; if it has not, land this first and comment on issue #43 (a build step never edits another plan's file). Step 41 landed the wire length check above; this step extends it and does not rewrite it. The **final** mode-and-length check of the pixels handed on is not written a second time: it lives once, in `pixels_to_page`, which both this path and the image decode child's output pass through. `bank_statements.py` is staged into the LPAC and may import only the allowlisted worker files (`native_sandbox.py:36-42`), so it keeps exactly its wire checks (bounded decompression, empty leftover, the wire length check, digest) and imports nothing from `receipt_pages`. **Outcome names (§ 5A, LPAC responses table):** each wire-check refusal (malformed, bomb-shaped, wrong-length, digest-mismatched) raises `ReceiptRenderInvalidError`, which Step 44 records as `pdf-render-invalid`; a page outside the dimension gate raises `ReceiptRenderPageTooLargeError` (`pdf-page-too-large`); a document over `max_pages` raises `ReceiptRenderTooManyPagesError` (`pdf-too-many-pages`); a render the started worker reports it could not complete (an unparseable PDF, or the worker ended by its own limits) raises `ReceiptRenderFailedError` (`pdf-render-failed`). A worker that cannot **start** is not a page error: unlike the statement path's catch at `bank_statements.py:4105`, the render entry lets `NativeSandboxUnavailable` propagate, and Step 44 maps it to the stage abort `ReceiptRenderUnavailableError`.
- **Type:** code
- **Issue:** #77
- **Flags:** `--reviewers deep`
- **Produces:** render limits, request/response, and validation in `pta_finance/treasurer_slides/bank_statements.py`; tests in `tests/test_treasurer_slides_bank_statements_native.py` — or, when `docs/findings/step-42-pdf-boundary.md` exists, the files and tests that findings file names for the recorded boundary
- **Done when:** a multi-page fictional fixture renders end-to-end through the boundary recorded in `docs/findings/step-42-pdf-boundary.md` when that file exists (in the CI job or jobs it names), otherwise through the real LPAC in the Windows CI job, and the broker returns raw gray8 pixels with their dimensions (no PNG is produced); a malformed, bomb-shaped, wrong-length (decompressed length ≠ `raw_length` or ≠ `width × height`, even with a matching digest), or digest-mismatched response is refused with `ReceiptRenderInvalidError`, a page outside the dimension gate with `ReceiptRenderPageTooLargeError`, and each other § 5A response row with its own named error; an extraction request (`operation` = 1) carrying the new fields still extracts exactly as before; a request with `operation` outside {1, 2} is refused by the envelope check; a worker start failure on the render path propagates as `NativeSandboxUnavailable`, never as a page error; the existing statement-extraction tests are unchanged and green; the row-stride copy is covered by a test using a width that forces padding
- **Depends on:** 41, 42

<!-- autofix-applied: 2026-10-09 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 44: PDF assets become display pages
- **Status:** PENDING
- **Problem:** Wire the rasterization boundary from Step 43 — the LPAC worker, or whatever `docs/findings/step-42-pdf-boundary.md` records if it exists — into `receipt_pages.py` so a cached PDF asset yields normalized page images, with § 5A's page-count ceiling (`max_pages`, 25) and per-page progress, by calling `render_receipt_pdf` and writing the pages only after it returns (§ 5A broker entry point); a PDF over the ceiling is refused whole as `pdf-too-many-pages`, never truncated. On hosts the recorded boundary does not support (non-Windows for the LPAC), fail closed before any PDF byte is read and report the assets as needing manual export (`pdf-not-rendered`). On a host it supports, record Step 43's refusals as `pdf-page-too-large`, `pdf-render-failed` and `pdf-render-invalid`, and map a boundary that cannot start to `ReceiptRenderUnavailableError`, a stage abort rather than N per-asset refusals (§ 5A Errors). **Broker-derived PDF pages are normalized in the broker, never re-sent through Step 39's untrusted-image decode child:** their pixels are broker-validated (Step 43) and both edges are bounded by Step 43's render dimension gate, so Step 43's raw gray8 pixels and dimensions go straight into `receipt_pages.pixels_to_page` — the same one function that encodes the child's output (§ 5A). That function applies the long-edge downscale, so a PDF page rendered larger than `NORMALIZATION.max_long_edge` is LANCZOS-downscaled to it before the JPEG encode, exactly as § 5 promises for every page; the resampler's cost is bounded by the render gate because these pixels are trusted and render-bounded, never upload-shaped. The untrusted PNG/JPEG entry point gains no "trusted" flag or bypass, so the two paths cannot drift and an upload can never reach the in-broker path.
- **Type:** code
- **Issue:** #78
- **Flags:** `--reviewers deep`
- **Produces:** PDF path in `pta_finance/receipt_pages.py`; tests covering multi-page output, the page ceiling, the fail-closed path on hosts the recorded boundary does not support, the PDF outcome classes and start-failure abort below, and the cap pin below
- **Done when:** a fictional 3-page PDF fixture produces 3 normalized pages on a host the recorded boundary supports (Windows for the LPAC) and a clean, counted `pdf-not-rendered` refusal on every host it does not support; a PDF one page over the ceiling is refused whole as `pdf-too-many-pages` with zero pages written; each Step 43 refusal reaches `ReceiptPageError.reason` as its § 5A value (`pdf-page-too-large`, `pdf-render-failed`, `pdf-render-invalid`); a boundary start failure (the launcher substituted to raise `NativeSandboxUnavailable`, or the recorded Step 42 boundary's equivalent) raises `ReceiptRenderUnavailableError` — never a `ReceiptPageError` — before any page outcome is recorded; a page rendered with a long edge above `NORMALIZATION.max_long_edge` comes out with its long edge exactly at the limit; output is byte-identical across two runs; a test asserts a PDF page never spawns the decode child while an uploaded PNG/JPEG always does, and that both reach `pixels_to_page`; a refusal on page 2 of a 3-page PDF leaves zero pages written for that asset; a test asserts `bank_statements.RENDER_MAX_EDGE == receipt_geometry.NORMALIZATION.max_source_edge`; a test asserts `receipt_geometry.NORMALIZATION.max_source_bytes <= bank_statements.MAX_PDF_BYTES`, so the fetch and read cap can never exceed what the renderer accepts (`is` is impossible: `bank_statements` is staged into the LPAC and cannot import `receipt_geometry`, § 5A config note)
- **Depends on:** 39, 43

<!-- autofix-applied: 2026-09-16 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 45: Provenance, the unambiguity gate, and the sidecar merge
- **Status:** PENDING
- **Problem:** Create `receipt_link.py`. **It owns the ticket→receipt-URL join, which nothing else does today:** the bundle keeps no receipt pointer (§ 2), so for each ticket this module re-derives the submission's upload URLs by matching `review_key` back to its `.eml` in the configured mail archive — `review_key` is the only durable join, and it hashes the **raw** stripped `Message-ID` header (§ 5A) — and reads `Submission.receipt_urls`, which `receipt_ingest._extract_receipt_urls` already parses. A legacy ticket with no message-derived key has no automatic join and is reported as such, never guessed. Then: choose the fill stage's working set with `fill_working_set` (tickets with at least one unlinked item, first URL per `canonical_key`; § 5A), build the proposals document under § 5's one membership rule (every ticket with at least one unlinked item and at least one candidate page; auto-eligible tickets pre-filled with `auto_eligible: true`), auto-commit `box: null` regions only for single-asset tickets, and merge confirmed entries into the sidecar. `apply` returns § 5A's `MergeResult`, and `write_proposals` is the file's one writer, which drops every item a merge linked. Hard refusals with no silent skip: unknown `(review_key, item_key)`, overriding an entry that already carries a human-verified box, duplicates, stale fingerprints, and any merge that would cross the page budget. Call `receipt_viewer.item_fingerprint`; never re-derive it. Self-validate through the production `load_receipts` and `build_report` before replacing anything, and back up the prior sidecar. **Regenerating proposals must preserve operator edits:** a rewrite merges into the existing file by `(review_key, item_key)` rather than truncating it, and refuses rather than discarding an edit it cannot reconcile. Only `items[].confirmed_page_ids` is editable, the four irreconcilable cases are listed in § 5, and `confirm` refuses a changed `bundle_sha256` with `ReceiptProposalsStaleError`. It is also the fetch ledger's writer for `unjoinable_tickets[]` and `page_outcomes[]`, through `record_fill_ledger` and the `TicketUrls`/`PageOutcome` types whose signatures § 5A gives (§ 5A fetch ledger: exact top-level key set, the closed 19-value outcome vocabulary including the PDF classes, rows updated in place).
- **Type:** code
- **Issue:** #79
- **Flags:** `--reviewers deep`
- **Produces:** `pta_finance/receipt_link.py`, `tests/test_receipt_link.py`, a committed fictional proposals example, and the additive accessor in `pta_finance/receipt_ingest.py` that exposes an already-parsed `Submission` by its archived message without widening the frozen `source_receipt_urls_v1` digest surface
- **Done when:** § 5A's three auto-commit conditions each have a test — a one-asset ticket auto-links, a two-asset ticket does not, a one-asset ticket whose asset produced zero pages does not, and a ticket with any already-linked item does not; a ticket whose `review_key` resolves to no archived message is reported unjoinable rather than skipped silently; a page outcome is written to `page_outcomes[]` under the exact ledger key set, a re-run updates that row in place, and a ledger created by either writer carries the other writers' lists as empty lists; every value of § 5A's closed `page_outcomes[]` vocabulary, all five `pdf-*` classes included, round-trips through `record_fill_ledger`, and a value outside it is refused; regenerating proposals over a hand-edited file preserves every operator edit, and each of § 5's four irreconcilable edits refuses with the file byte-unchanged instead of overwriting; a fully linked ticket appears in neither `fill_working_set` nor the proposals document, and a ticket's later size-variant URL under one `canonical_key` is not in the working set; a ticket whose assets all yielded zero pages is not in the document; an auto-eligible ticket appears pre-filled with `auto_eligible: true` and, once merged, is absent from the file `write_proposals` writes; `confirm`'s merge path refuses a changed `bundle_sha256` with `ReceiptProposalsStaleError` before any write; `apply` returns a `MergeResult` whose `items_linked`, `pages_added`, `linked_total`, `unlinked_total` and `headroom_bytes` equal independently computed values (`headroom_bytes` = `receipt_viewer.headroom_bytes` on the written sidecar), and an empty merge writes nothing and returns `items_linked` and `pages_added` of 0 with the totals and headroom still computed; each refusal class has a test asserting the sidecar is byte-unchanged afterward; the fictional proposals example fed to `load_receipts` raises; the budget refusal names the crossing page and the remaining bytes; the `receipt_ingest.py` accessor imports nothing outside the hosted-image `source-manifest.txt` files (§ 4) and `tests/test_shared_workflow_packaging.py` passes
- **Depends on:** 40, 44

<!-- autofix-applied: 2026-10-09 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 46: The refresh stage, config block, and `link-receipts` verbs
- **Status:** PENDING
- **Problem:** Insert the fill stage inside `_cmd_update_reimbursements`, between the refresh summary and its `build_report` call, running § 5A's fill-stage order exactly (working set, fetch, pages, ledger, propose, auto-eligible merge, proposals write, then the printed receipt summary's three lines), add the `[receipt_assets]` config block per § 5A (its `max_asset_mib` upper bound derived at use from the imported `receipt_geometry.NORMALIZATION` object's `max_source_bytes`, never restated as 25), and add these exact CLI surfaces in `build_parser`: on `update-reimbursements`, the mutually-exclusive pair `--fill-receipts` / `--no-fill-receipts` (**default: on when `[receipt_assets]` exists with `enabled = true`, off otherwise**) plus `--fill-receipts-offline` (serve from cache only; never opens a socket — it passes `offline=True` to Step 40's `fetch_assets`, so this step does not edit `receipt_assets.py`); and a `link-receipts` verb group with exactly `audit`, `propose`, `confirm`, `probe` and `hosts`, whose arguments are exactly these (Step 49's commands use them verbatim): every verb except `hosts` takes `--config` (default `config.toml`, as `update-reimbursements` does) and `--data` (default `reports/output/reimbursement-report.json`); `link-receipts audit [--since YYYY-MM-DD]` reads `<cache_dir>/fill-ledger.json` from `[receipt_assets]` and prints per-asset fetch outcomes and media types by ticket ref and asset ordinal (joined through `page_outcomes[]`; never a URL), the page-outcome counts and every non-`paged` page-outcome row by ticket ref and asset ordinal (§ 5A fetch ledger), plus any unreferenced page files under `pages_dir`, by page id — a file referenced by neither the sidecar's `pages[]` nor a `candidates[]` entry of the current proposals file (`Path(--data).with_suffix(".receipt-proposals.json")`), so a candidate awaiting `confirm` is never listed for deletion; an absent sidecar or proposals file references nothing, and a present one that cannot be read makes `audit` exit 1 naming that file rather than list every page as unreferenced; with `--since` (inclusive) it also lists, offline from the bundle and the `mail_root` archive, the tickets whose bundle `Ticket.submitted` date is on or after that date and that have at least one unlinked item (`Ticket.submitted` is the header-local calendar date of the submission's outer `Date` header, never converted to UTC — `receipt_ingest.parse_received_date`, the same date `map-receipts`' `received_since` filters on), grouped by distinct upload-asset count (none, exactly one, two or more), and within the exactly-one class marks each ticket that § 5A's auto-commit rule excludes, with the rule — rule 3 when an item on it is already linked, rule 2 once the ledger records a zero-page outcome for its asset — ticket refs, rules and counts only, opening no socket; `link-receipts propose` rebuilds `<bundle>.receipt-proposals.json` from the cache without fetching, preserving operator edits (Step 45): it runs § 5A's fill-stage order with `offline=True` and without the merge, so any missing candidate page is rendered from the cache through `to_pages` under the same sequential loop, the same `ReceiptDecodeUnavailableError`/`ReceiptRenderUnavailableError` aborts and the same § 5A workspace rule; `link-receipts confirm --proposals PATH [--sidecar PATH]`, where `--proposals` is required and `--sidecar` defaults to `Path(--data).with_suffix(".receipts.json")` — for the default `--data`, exactly `reports/output/reimbursement-report.receipts.json` — the same expression `build_report` uses (`reimbursement_report.py:1615`) and so the file it reads; `confirm` runs § 5's stale-bundle check, merges every confirmed item, rewrites the proposals file without the items it linked, and prints § 5A's two `confirm` summary lines; `link-receipts probe --ticket REF` is Step 49's no-write seam probe: for the one ticket whose bundle `ref` is REF, it fetches each distinct asset (first URL per `canonical_key`) from the real allowlist into a fresh temporary cache — a network fetch even when the asset is already cached — and runs `to_pages` on each into a temporary pages directory, through the real decode child or PDF boundary. It prints one line per asset ordinal (media type, fetch outcome, page outcome, page count; never a URL), removes both temporary directories, and writes nothing else: not the live cache, ledger, `pages_dir`, proposals file, sidecar, bundle or HTML. An unknown or unjoinable REF, or a stage-abort class, exits 1; `link-receipts hosts [--mail-root PATH]` (default `mail_samples`) reads no config and opens no socket. It prints each distinct lowercased hostname in `Submission.receipt_urls` across the archive, one per line with its URL count, sorted, and never a scheme, path, query, filename, requestor or ticket ref. It is the § 6.8 exception, the one command that prints a vendor hostname, so the operator can write the private allowlist. Keep exit codes in {0, 1}; keep printed output aggregate-only (counts and ticket refs; never a URL, filename, vendor or requestor), except the bare hostnames `hosts` exists to print (§ 6.8), with budget refusals and decode child errors counted separately (§ 5A); keep `--dry-run` writing nothing and opening no socket. The new stage is its own call — never a new `refresh_kwargs` key, which is pinned by test. The page loop stays sequential even when `max_parallel` > 1 (that pool is for fetching only), so at most one decode child is alive and total decode memory is one child's cap. `--fill-receipts-offline` assets go through the same `to_pages` path: the broker's read of a cached file is capped at `max_source_bytes` and its decode cost by the child (§ 5A). A `ReceiptDecodeUnavailableError` (the child cannot start or be limited) or a `ReceiptRenderUnavailableError` (the PDF boundary cannot start on a host it supports) aborts the stage before `build_report`, while a per-asset decode refusal is recorded in the ledger's `page_outcomes[]` with its `reason` and `usage` (§ 5A). On any stage abort, apply § 5A's workspace rule: unlink the page files this run newly created, write no proposals or sidecar, keep the cache and ledger. **Coordinate with Phase 10** ([non-reimbursement action queue](master_plan.md)): its Step 51 adds a separate `update-actions` command and subparser in `build_parser`, next to `update-reimbursements`, and its unfinished `cli.py` change is paused in its own worktree; its Step 54 edits `_cmd_update_reimbursements` and `tests/test_reimbursement_cli.py`. Re-read `cli.py` at dispatch; the fill stage stays before `build_report` and any action stage stays after it, so the stage-order test expects refresh, fill, report, then actions when that stage exists. Whichever phase lands second rebases. **Coordinate with Phase 6** ([board summary](master_plan.md), Steps 26–28 add commands to `cli.py` and Step 26 edits `tests/test_reimbursement_cli.py`): its planned Step 29 runner calls `update-reimbursements` and stops on the first failure, so it inherits this stage's default and its abort exit code. Keep the exit codes in {0, 1}, make every abort message name its cause and remediation, and keep `--no-fill-receipts` a forwardable opt-out; whichever phase lands second rebases (§ 8).
- **Type:** code
- **Issue:** #80
- **Flags:** `--reviewers deep`
- **Produces:** `pta_finance/cli.py` stage and subparsers, `pta_finance/config.py` block, `config.example.toml` with fake hosts, updated `tests/test_reimbursement_cli.py`
- **Done when:** Every criterion in the complete Acceptance detail below passes; preserve all required real-boundary evidence, negative cases and full-suite gates.

**Acceptance detail:** absent config is a no-op with byte-identical output to today; a malformed block raises `ConfigError` rather than skipping; `max_asset_mib` = 26 is refused and the bound comes from `receipt_geometry`, asserted with `is` on the object config holds — `config`'s `NORMALIZATION` (or its byte constant, 26,214,400, which CPython does not cache) `is receipt_geometry.NORMALIZATION` — never on the derived MiB value 25, which a restated copy would also pass; `--dry-run` writes nothing and opens no socket; stage ordering and `refresh_kwargs` equality tests pass in their updated form; no URL, filename, vendor or requestor appears in any printed line; a partial fetch (some assets fail) prints an aggregate failure count **and names the private ledger path as the triage surface**, so aggregate-only output never leaves the operator with no way to diagnose which asset failed and why; `link-receipts audit` reports per-asset outcomes from that ledger, and a test shows a decode-budget refusal and a decode child error on fictional assets each appearing in the audit output as its own `page_outcomes[]` row (`budget`, `child-error`) with its ticket ref and asset ordinal — that test may seed those rows directly in a fictional ledger, because `audit` only reads the ledger and no crafted input can make the real child exit 4 (§ 9 tests that mapping directly); `audit` lists a page file referenced by neither the sidecar nor the current proposals file, and never lists a candidate page that only the proposals file references; `audit --since` lists fictional tickets in the right asset-count classes, with rule-2 and rule-3 exclusions marked, without opening a socket; a test parses Step 49's exact command lines with `build_parser` (`update-reimbursements --fetch-since 2026-10-02 --no-fill-receipts`, `update-reimbursements --fill-receipts`, `link-receipts audit --since 2026-10-09`, `link-receipts audit`, `link-receipts propose`, `link-receipts confirm --proposals reports/output/reimbursement-report.receipt-proposals.json`, `link-receipts probe --ticket REF`, `link-receipts hosts --mail-root mail_samples`) and asserts `--sidecar` defaults to exactly `reports/output/reimbursement-report.receipts.json` — equal to `Path(--data).with_suffix(".receipts.json")`, never `reimbursement-report.json.receipts.json` — and a round trip shows a default-path `confirm` writes the file `report-reimbursements` then embeds; with `max_parallel` > 1, a test shows at most one decode child alive at any time (peak concurrent spawn count is 1); a decode child that cannot start aborts the stage with exit 1 and the prior HTML untouched, and so does a PDF boundary that cannot start (the host treated as supported and the boundary start substituted to raise `NativeSandboxUnavailable`); a stage abort after the first asset leaves `pages_dir` as it was before the run, with no proposals file or sidecar written; an offline-cache asset is decoded by the real child; the fill stage prints exactly § 5A's three summary lines and `confirm` its two, and a test asserts their values against the `MergeResult`, the fetch outcomes and the `receipt links` line that follows (linked/unlinked equal), including a zero-merge run that prints `0 newly linked` with the headroom in bytes and MiB; the fill stage never fetches for a fully linked ticket or a later size-variant URL; `link-receipts propose` renders a missing candidate page from the cache and opens no socket; `audit --since` lists a ticket whose `Ticket.submitted` equals the date and omits one submitted the day before; `link-receipts probe` calls the opener seam even for an already-cached asset, reaches the real decode child, prints no URL, and leaves the live cache, ledger, `pages_dir`, proposals file and sidecar byte-unchanged with its temporary directories gone; `link-receipts hosts` over fictional `.eml` files prints exactly their distinct `.invalid` hostnames with counts, and no scheme, path, query or ref
- **Depends on:** 45

<!-- autofix-applied: 2026-09-16 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 47: Integration through the production caller
- **Status:** PENDING
- **Problem:** Prove the wiring, not just the parts. Drive `cli.main(["update-reimbursements", ...])` end-to-end against a local fixture source and assert the new link reaches the rendered HTML; the drive runs the real image decode child, never an in-process decode substitute (§ 5A). Add the producer→consumer round trip on the `page_id` join key, and add the fingerprint blast-radius test. Beside the 19-case fail-closed parametrize, add one case per class the fill stage can produce. The classes are a malformed `[receipt_assets]` block (`ConfigError`), `ReceiptPagesDirectoryError`, `ReceiptDecodeUnavailableError`, `ReceiptRenderUnavailableError`, an irreconcilable proposals edit (§ 5), and each `ReceiptLinkError` merge refusal: unknown key, stale fingerprint, attempted override of a human-verified box, duplicate entry and budget crossing. Each case drives `cli.main(["update-reimbursements", ...])` over an existing HTML and asserts exit 1, with that HTML, the sidecar and the proposals file byte-unchanged.
- **Type:** code
- **Issue:** #81
- **Flags:** `--reviewers code`
- **Produces:** integration tests in `tests/test_reimbursement_cli.py` and `tests/test_receipt_viewer.py`
- **Done when:** the only substitution in the end-to-end test is Step 40's transport opener seam — `to_pages`, `receipt_decode` and `receipt_link` run for real, and the test observes at least one decode-child spawn; it asserts a sidecar entry was created, the rendered HTML shows `View source receipt` for that item, and the embedded item map grew by exactly one; the blast-radius test mutates one ticket-level evidence field and asserts **every** item on that ticket loses its link; the prior-HTML-preserved assertion holds for each class listed in the Problem
- **Depends on:** 46

<!-- autofix-applied: 2026-09-16 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 48: Documentation, policy amendments, and the full-suite gate
- **Status:** PENDING
- **Problem:** Amend every sentence this feature makes false, in lockstep: the "prepared offline" clause, the "never downloads during rendering" wording plus its new refresh-time carve-out, the operator guide's rebuild instructions, and the command lists. (The board-summary plan's `[summary]` carve-out stays true as written and is not edited — § 6.3; a build step never edits another plan's file, § 8.) The command lists are `CLAUDE.md` § 2 Stack, which gains a row for the `receipts` extra, and § 3 Key commands, whose comments must name exactly what each command writes: `link-receipts audit` (no writes), `link-receipts propose` (the proposals file and the fetch ledger, plus any candidate page it renders from the cache into `pages_dir`), `link-receipts confirm` (the sidecar, its backup, and the proposals file without the items it linked), `link-receipts probe` (only temporary directories, which it removes; it fetches from the network), `link-receipts hosts` (no writes; prints bare upload hostnames for the private allowlist, never to be committed), and `update-reimbursements`' new write set (asset cache, fetch ledger, pages, proposals file and sidecar, in addition to the `.eml`, bundle and HTML it already writes; still no Sheet). Also record the new facts A1 introduced: add `receipt_geometry`, `receipt_pages`, `receipt_decode`, `process_limits`, `receipt_assets` and `receipt_link` to `CLAUDE.md` § 4's layout (noting that `treasurer_slides/native_sandbox.py` now wraps `process_limits`); state the fill stage's supported hosts — Windows and Linux; on any other host (macOS included) the stage aborts before any decode child is spawned — in `CLAUDE.md` § 7 and `docs/receipt-viewer.md`; and record the calibrated decode limits from § 6.3 (memory, CPU and wall budget, and the Pillow version they were measured under) in `docs/receipt-viewer.md`. Refresh the lock with exactly `uv lock` — never `--upgrade` or `--upgrade-package` — so Pillow stays at the version Step 39 calibrated, then run the full suite, which already includes § 9's decode-budget corpus and headroom tests. **If the locked Pillow moved anyway (default applied 2026-10-09):** this step never re-tunes the decode limits. A limit change re-tunes an untrusted-input boundary and edits `receipt_geometry.py`, which this `--reviewers code` docs step must not do. The move is a quality-gate failure: the checkpoint records the old and new versions, and recalibration returns through `/plan-review` as a `--reviewers deep` code step.
- **Type:** code
- **Issue:** #82
- **Flags:** `--reviewers code`
- **Produces:** updates to `CLAUDE.md` (§§ 2, 3, 4, 7 and the "prepared offline" sentence), `docs/receipt-viewer.md`, `docs/loading-receipts.md`, `README.md`, and `uv.lock` re-locked with `uv lock` (no upgrade); no edit to `pta_finance/receipt_geometry.py`, to this plan or to any other plan's file
- **Done when:** the **full** suite runs — every declared test root with dev, slides, web and the new imaging extra installed and the Firestore emulator running, not a subset — with collected count at or above **the `Baseline tests:` count recorded in Step 39's checkpoint** — the full-suite collected count on `main` at the commit the resumed Step 39 was dispatched from, before any Phase 9 code merged (Step 39 Done-when) — not a number copied from an older phase (CLAUDE.md's 1,231 is stale: the non-web suites alone collect 1,018 as of 2026-09-16, so a hard-coded 1,231 would let a change that deletes tests pass); strict mypy, Ruff lint and format, the identity guard, and all three CI jobs pass; no committed file contains a real host, organization, person or email; the checkpoint states the locked Pillow version after `uv lock` — if it equals the version recorded in § 6.3 it says "Pillow unchanged"; if it moved, the gate fails, the checkpoint records both versions, and recalibration is routed back through `/plan-review` as a deep-reviewed code step (Problem above), never done here; `CLAUDE.md` § 2 lists the `receipts` extra, § 3 lists `link-receipts audit`/`propose`/`confirm`/`probe`/`hosts` and `update-reimbursements`' new write set with exactly what each writes, § 4 lists the new modules, and § 7 and `docs/receipt-viewer.md` state the supported hosts; the checkpoint names M9 (Step 49, #83) as the next, attended action, because `/build-phase`'s own handoff omits it (Manual UAT, M9)
- **Depends on:** 47

---


Attended M9 is Step49 below; it is one acceptance unit, not a second queue.

### Step 49: Attended run against the real private evidence (M9)
- **Status:** PENDING
- **Problem:** Run the real end-to-end refresh on the live private bundle with the fill stage enabled, complete the confirm round-trip for any ambiguous ticket, and verify that items on tickets that arrived after the **cutoff** — the 2026-10-09 manual receipt backfill, the last time links were added by hand — open their source receipts, with no regression to any existing link and with the decode child proven on the operator's own machine.
- **Type:** operator
- **Issue:** #83
- **Produces:** none — observation only (private checkpoint notes)
- **Done when:** Every criterion in the complete Acceptance detail below passes; preserve all required real-boundary evidence, negative cases and full-suite gates.

**Acceptance detail:** all of the following hold. **Baseline, taken after acquisition and before the fill (default applied 2026-10-09):** the operator first acquires mail and refreshes the bundle with the fill stage off (`update-reimbursements --fetch-since 2026-10-02 --no-fill-receipts`, or the date of the last routine fetch if that is later — see Operator commands), so every post-cutoff ticket the fill run will consider is already in the bundle. The operator then records in the step checkpoint the `linked` / `unlinked` counts that `report-reimbursements` prints, and the `link-receipts audit --since 2026-10-09` listing of that refreshed bundle as class counts only: tickets with exactly one distinct upload asset (and how many of those the listing marks as excluded under § 5A rule 3), with two or more, and with none. Ticket refs stay in private notes, never in a committed file. Then the fill run (`update-reimbursements --fill-receipts`, no mail fetch), and: (a) **(default applied 2026-10-09)** this clause covers only the single-asset tickets that § 5A's auto-commit rules make eligible, and every such ticket auto-links with no operator action. Each single-asset ticket the rules exclude is listed privately with its rule: rule 2 when its asset produced zero pages (with the ledger's page outcome), or rule 3 when an item on it was already linked — for example a ticket partly backfilled on the 2026-10-09 cutoff day, which the inclusive `--since` lists. Each excluded ticket either completes through (b) or is recorded as unlinkable with that rule. If no auto-eligible single-asset ticket exists — none arrived, or every one that did is excluded under rule 2 or 3 — record "N/A — no auto-eligible single-asset ticket"; (b) if the multi-asset class is non-empty, each of those tickets that produced at least one candidate page appears in the proposals file (§ 5 membership; one whose assets all yielded zero pages is recorded as unlinkable with its ledger page outcomes), the operator confirms them via `link-receipts confirm` (procedure under Operator commands), and their items then open their pages — **the auto-gate closes only single-asset tickets, so whenever such a ticket exists the confirm round-trip is part of this step, not an optional extra**; if the class is empty, record "N/A — none arrived after the cutoff"; (c) zero regressions: the newly linked counts come from the fill run's `receipt fill` line and each `link-receipts confirm:` line (§ 5A, Printed receipt summary; Step 46 tests them), and the final `report-reimbursements` `receipt links` linked count equals the baseline linked count plus the sum of those newly linked counts. Because no merge ever deletes or rewrites an existing entry (§ 5A refusal rules), that equality means every previously linked item is still linked. Fingerprint drift is zero exactly when that final `report-reimbursements` succeeds, because a stale `item_sha256` makes `load_receipts` refuse (the `stale` case of `tests/test_receipt_viewer.py`'s fail-closed parametrize); (d) the sidecar validates through `load_receipts` (the same successful `report-reimbursements`), and the rendered HTML stays under the page budget, with the remaining headroom recorded in bytes and MiB from the last `page budget` line printed (§ 5A). If the fill run or a `confirm` instead aborts on the budget pre-check (§ 2: about 7.7 MiB was free on 2026-10-09), record the remaining bytes from the abort message, keeping the crossing page id in private notes only; the refusal is the designed fail-safe, so clause (d) still passes when the sidecar, bundle and HTML are byte-identical to their pre-run state (nothing half-merged, every existing link and fingerprint unchanged), and the operator opens a follow-up issue for page-budget relief (for example `link-receipts compact` or a smaller page encoding) and cites it here **(operator decision 2026-10-09)**; (e) the decode child starts and attests on the operator's machine: `uv run pytest -q -rs tests/test_receipt_decode_budget.py -k decoding_pid_is_the_limited_process` there reports exactly `1 passed` — a skipped or deselected result fails this clause — proving the Job Object path on the operator's interactive host, not only on a CI runner, and the fill run raises no `ReceiptDecodeUnavailableError`. **Triage (default applied 2026-10-09):** any non-zero decode-budget refusal or child-error count is triaged from the ledger's `page_outcomes[]` through `link-receipts audit`, against the § 5A calibration. A refusal of a genuine amplifier, or a child error caused by a malformed upload, is recorded as correct. A refusal of a legitimate upload, or a child error that is a bug, is recorded with its ledger `usage`, and the operator opens a follow-up issue (or links an existing one) for a code step through `/plan-review`, because a limit change is code. This step is then marked DONE citing that issue. A `pdf-render-failed` row is triaged the same way: a PDF the boundary genuinely cannot parse is recorded as correct, any other cause gets a follow-up issue. A non-zero `failed-validation` or `pdf-render-invalid` count is never recorded as correct — a correct child or worker cannot produce output the broker refuses, so each row is a bug or a compromised decoder — and a non-zero `digest-mismatch` count means a cached asset changed after it was fetched; each such row is recorded with its ledger row, its cache file is kept for review, and a follow-up issue is opened (or linked) the same way. The attended step only records: it never edits a limit, `receipt_geometry.py` or any other code; (f) the operator confirms by eye that each newly linked item opens the right receipt — a link that opens the wrong page passes every automated check — and, when (a) and (b) are both N/A, that a sample of existing links still opens the right receipt; (g) **real seams on this host, required even when (a) and (b) are N/A:** at least one **real** allowlisted fetch and, if any fetched asset is a PDF, at least one **real** PDF render through the LPAC (or the recorded Step 42 boundary). The evidence is the fill run's `receipt assets` line showing at least one `fetched`, and, when `link-receipts audit` lists a `pdf` asset, a `paged` page outcome on a PDF asset. If the fill run fetched nothing new, because every asset was already cached or no unlinked ticket has an upload, or if no fetched PDF reached `paged`, run `link-receipts probe --ticket REF` on an **already-linked** ticket (Operator commands). The probe fetches that ticket's uploads from the real allowlist into temporary directories and renders them through the real decode child or PDF boundary. It writes nothing live, so the sidecar's hash is the same before and after. The clause holds once the fill run and any probes together show a `fetched` asset and, if any asset either fetched or probed was a PDF, a `paged` PDF asset. A PDF the probe refuses is triaged like `pdf-render-failed` above, and another linked ticket's PDF is probed. Record outcome classes and counts only, never a ref, in any committed file. A clause recorded as N/A does not block the step; the remaining clauses must still hold.
- **Depends on:** 48

**Before running.** Three prerequisites, none created by an earlier step: (1) a `[receipt_assets]`
block per § 5A exists in gitignored `config.toml` with the **real** allowlist — no committed file
carries it, so the stage is a no-op until the operator writes it; (2) the `receipts` extra is
installed (`uv sync --extra dev --extra slides --extra receipts`); (3) Gmail one-time setup is
already in place if `--fetch-since` is used — an OAuth Desktop-app client at
`secrets/gmail-client-secret.json`, a `[gmail]` config block, and a browser consent that expires
roughly weekly by design (SETUP.md §6). To skip mail acquisition entirely, drop `--fetch-since` and
run against the existing local archive. This step needs no browser install; Chromium matters only
for the full-suite gate (§ 5A Development commands).

To learn the real upload hosts for (1), list the hostnames already present in the local archive.
The command reads only the archive, opens no socket, and prints each distinct hostname with a
count, and nothing else (§ 6.8). § 2 expects exactly two, both on the intake form vendor's CDN.

```powershell
uv run pta-finance link-receipts hosts --mail-root mail_samples
```

Copy each printed hostname into `allowed_hosts` in `config.toml` as an exact host. Never put a
hostname in a committed file, an issue or a checkpoint. Start the rest of the block from
`config.example.toml`. Keep `cache_dir` and `pages_dir` under the gitignored `reports/output/`,
and keep `pages_dir` under the sidecar's own directory (`reports/output/`, as in the example),
because `load_receipts` refuses any page outside that directory.

**Operator commands**

Every `update-reimbursements` and `link-receipts` argument below is defined in Step 46, whose tests
parse these exact lines. First acquire mail and refresh the bundle **with the fill stage off**, so
the post-cutoff listing below is taken from the same bundle the fill run will process. The fetch
date is pinned at 2026-10-02, seven days before the cutoff, to cover the arrivals under test with
margin. **If a routine fetch has run since then, use that fetch's date instead** — mail before it is
already in the archive — because Step 49 may run weeks after the cutoff, and a fetch window over
roughly 100 messages has tripped Gmail's per-minute quota before. The fetch window controls
acquisition only, never report membership. To skip mail acquisition, drop `--fetch-since`.

```powershell
uv run pta-finance update-reimbursements --fetch-since 2026-10-02 --no-fill-receipts
```

Then record the baseline: the linked and unlinked counts (this re-renders the HTML from the
unchanged bundle; nothing else is written).

```powershell
uv run pta-finance report-reimbursements
```

Then list the tickets that arrived after the cutoff, from the refreshed bundle, grouped by distinct
upload-asset count (offline; opens no socket).

```powershell
uv run pta-finance link-receipts audit --since 2026-10-09
```

Then prove the decode child starts and attests on this machine. The summary must read exactly
`1 passed`; a skipped or deselected result fails clause (e).

```powershell
uv run pytest -q -rs tests/test_receipt_decode_budget.py -k decoding_pid_is_the_limited_process
```

Then run the fill stage, with no mail fetch.

```powershell
uv run pta-finance update-reimbursements --fill-receipts
```

Then read the per-asset fetch and page outcomes, including any decode refusal or child error.
Candidate pages awaiting `confirm` are referenced by the proposals file, so they are never listed as
unreferenced; a listed page file is a leftover of an interrupted run, for the operator to delete.

```powershell
uv run pta-finance link-receipts audit
```

Then, only if clause (g)'s evidence is missing, probe an already-linked ticket. The evidence is
missing when the fill run's `receipt assets` line shows no `fetched`, or when `audit` lists a `pdf`
asset with no `paged` PDF page outcome. Pick a linked ticket in the queue and replace REF with its
ref. For the PDF seam, prefer a ticket whose source receipt opens with page navigation, because a
multi-page upload is usually a PDF. The probe's line names each asset's media type, so try another
ticket if none is `pdf`. The probe writes nothing live, and the two hashes must match.

```powershell
Get-FileHash reports/output/reimbursement-report.receipts.json
uv run pta-finance link-receipts probe --ticket REF
Get-FileHash reports/output/reimbursement-report.receipts.json
```

Then confirm every ticket the proposals file lists (§ 5 membership: each has an unlinked item and
at least one candidate page). If its `tickets` list is empty, skip to the final
`report-reimbursements`.

1. Open `reports/output/reimbursement-report.receipt-proposals.json` in a text editor. It is
   private: never commit it or paste its contents anywhere.
2. Work through the tickets in file order, which is the queue's `display_order`. Find each ticket
   in the queue HTML (`reports/output/reimbursement-queue-breakdown.html`) by its `ref`, which heads
   its ticket card.
3. Open each of the ticket's candidate pages. `candidates[].path` is relative to the sidecar's
   directory, `reports/output/`, so `"path": "receipt-pages/auto/EX-01-a2-p1.jpg"` is the file
   `reports/output/receipt-pages/auto/EX-01-a2-p1.jpg`. Open it with `Invoke-Item` and that path.
   The page's `label` says which upload and which page it is.
4. Identify each entry in `items[]` by its `source_index`. That is the line's 1-based position as
   submitted on the form: line 1 is the first item row of the form in the ticket's submission
   email. Do not use the queue's row order, because the queue groups items by category.
5. For each item whose receipt appears on one or more candidate pages, set `confirmed_page_ids` to
   those pages' `page_id` values in page order, for example
   `"confirmed_page_ids": ["EX-01-a2-p1"]`. Leave `[]` for an item you cannot place; it stays in
   the file for a later run. Change nothing else. Every other field is generated, and `confirm`
   checks the confirmed items against the bundle and the page files (§ 5).
6. Save the file and run `confirm` (below) before any other refresh. A refresh rewrites the bundle,
   and `confirm` then refuses with `ReceiptProposalsStaleError`. If that happens, run
   `link-receipts propose` (below), which keeps your edits, and then run `confirm` again.
7. Note the printed `link-receipts confirm:` and `page budget` lines for clauses (c) and (d).

```powershell
uv run pta-finance link-receipts confirm --proposals reports/output/reimbursement-report.receipt-proposals.json
```

Only if `confirm` refused with `ReceiptProposalsStaleError`, regenerate the file while keeping its
edits (offline; opens no socket), then run `confirm` again:

```powershell
uv run pta-finance link-receipts propose
```

Finally, re-render and record the final linked and unlinked counts:

```powershell
uv run pta-finance report-reimbursements
```

**What to look for**

| Check | Expected |
|---|---|
| Baseline | after the no-fill acquisition run: linked / unlinked counts and the post-cutoff listing's class counts, recorded before the fill run |
| Decode child | the attestation test reports exactly `1 passed` on this machine; zero `ReceiptDecodeUnavailableError`; budget refusals and child errors each 0, or each triaged from the ledger's `page_outcomes[]` — recorded as correct, or recorded with a follow-up issue cited; never a limit edit |
| Validation and cache integrity | `failed-validation`, `pdf-render-invalid` and `digest-mismatch` each 0, or each row recorded with a follow-up issue cited — never recorded as correct; `pdf-render-failed` triaged like a child error |
| Unreferenced page files | none, or only leftovers of an interrupted run — never a candidate awaiting `confirm` |
| Fill-stage receipt lines | aggregate counts only — no URL, vendor, filename or requestor |
| Auto-linked | every listed single-asset ticket that § 5A's rules make eligible, with no operator action; each excluded one listed privately with its rule — or "N/A — no auto-eligible single-asset ticket" |
| Proposals file | includes every listed multi-asset ticket that produced at least one candidate page, one entry each, hand-editable, never auto-merged — or "N/A — none arrived after the cutoff"; no already-linked item |
| Existing links | final `receipt links` linked = baseline linked + every `newly linked` count printed; every existing link preserved; zero fingerprint drift (the final render succeeded) |
| Page budget | the last `page budget` line's headroom in bytes and MiB, still under the cap — or a budget abort recorded with its remaining bytes |
| Real seams (g) | at least one `fetched` asset and, if any asset was a PDF, a `paged` PDF asset, from the fill run or a probe of a linked ticket; the sidecar hash unchanged across each probe |
| Opened receipt | the correct receipt for that item — verify by eye, not by count |

---

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/receipt-autofill-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 51: Propose actions from archived mail
- **Status:** PAUSED — unfinished worktree; resume from [handoff](../phase10-build-handoff.md), never restart or discard it.
- **Problem:** Make `pta-finance update-actions` scan the local archive and produce a strict private proposal/uncategorized inventory with stable source keys, narrow type reasons, attachment provenance, and exact-thread deduplication.
- **Type:** code
- **Issue:** #87
- **Flags:** `--reviewers deep`
- **Files:** `pta_finance/mail_actions.py`, `pta_finance/cli.py`, `tests/test_mail_actions.py`, `tests/fixtures/mail_actions/*.txt`
- **Produces:** `pta_finance/mail_actions.py`, the `update-actions` entry point in `pta_finance/cli.py`, `tests/test_mail_actions.py`, fictional source fixtures with `.txt` suffix
- **Done when:** running the CLI on a fictional mixed `.eml`/`.mbox` archive yields one proposal for each of the three scoped types, groups an exact reply without duplicating an action, and leaves unrelated/reimbursement-like mail uncategorized; a second identical run reports zero new proposals; a duplicate key with changed evidence fails before output replacement; ambiguous ancestry is quarantined without changing existing actions; stdout contains counts and paths only.
- **Depends on:** Phase 9 Step 38 / #72

<!-- autofix-applied: 2026-09-23 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 52: Preserve operator decisions across refreshes
- **Status:** PENDING
- **Problem:** Validate a separate operator decision file and merge its confirmed type, owner, next action, status, ticket relation, and required outcomes with completion evidence into the action inventory without rewriting those fields on a repeat scan.
- **Type:** code
- **Issue:** #88
- **Flags:** `--reviewers deep`
- **Files:** `pta_finance/mail_actions.py`, `docs/mail-actions.md`, `tests/test_mail_actions.py`
- **Produces:** strict decision loader/merge in `pta_finance/mail_actions.py`, fictional decision example in `docs/mail-actions.md`, decision-cycle tests in `tests/test_mail_actions.py`
- **Done when:** the production `update-actions` command retains an `OPEN` decision after new thread replies, retains a `DONE` decision and its evidence after a repeat refresh, refuses `DONE` until every required outcome has evidence (including both seeded budget surfaces), refuses unknown/duplicate source or action keys, and refuses changed or missing previously accounted evidence before replacing private output.
- **Depends on:** 51

<!-- autofix-applied: 2026-09-23 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 53: Render the private action queue
- **Status:** PENDING
- **Problem:** Render the validated action inventory into a self-contained, autoescaped HTML report that lets an operator inspect proposals, active work, completed work, and uncategorized sources.
- **Type:** code
- **Issue:** #89
- **Flags:** `--reviewers deep`
- **Files:** `pta_finance/mail_action_report.py`, `pta_finance/reports/templates/mail_action_queue.html.j2`, `pta_finance/mail_actions.py`, `tests/test_mail_actions.py`
- **Produces:** `pta_finance/mail_action_report.py`, `pta_finance/reports/templates/mail_action_queue.html.j2`, report tests in `tests/test_mail_actions.py`
- **Done when:** `update-actions` writes the private report with source/thread/attachment references and the operator's next action/status; hostile subject/body text renders inert; a validation or render failure leaves the prior report intact; no private value enters public stdout or a tracked artifact.
- **Depends on:** 52

<!-- autofix-applied: 2026-09-23 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 54: Surface actions in the reimbursement end-to-end run
- **Status:** PENDING
- **Problem:** Add the local action stage and aggregate new/open/done/uncategorized counts to `update-reimbursements` while keeping its current reimbursement, receipt, no-Sheets, no-send, and dry-run contracts.
- **Type:** code
- **Issue:** #90
- **Flags:** `--reviewers deep`
- **Files:** `pta_finance/cli.py`, `tests/test_reimbursement_cli.py`, `docs/mail-actions.md`, `README.md`, `CLAUDE.md`
- **Produces:** action-stage dispatch in `pta_finance/cli.py`, regression tests in `tests/test_reimbursement_cli.py`, operator guide in `docs/mail-actions.md`, updated `README.md` and `CLAUDE.md`
- **Done when:** the production CLI prints action counts after a successful local refresh; `--dry-run` writes neither action nor reimbursement artifacts; a failed action stage reports the already-refreshed reimbursement boundary and preserves the prior action report; the standalone command and current reimbursement output stay usable; no action stage calls a Sheets writer, payment function, or Gmail sender.
- **Depends on:** 53

<!-- autofix-applied: 2026-09-23 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 55: Real-component archive-to-report smoke gate
- **Status:** PENDING
- **Problem:** Exercise one full offline cycle through `pta-finance update-reimbursements` using fictional mail, a fictional reimbursement bundle, and the actual classifier, decision loader, renderer, and CLI to catch producer/consumer key drift.
- **Type:** code
- **Issue:** #91
- **Flags:** `--reviewers deep`
- **Files:** `tests/test_mail_actions_smoke.py`, `tests/fixtures/mail_actions/*.txt`
- **Produces:** `tests/test_mail_actions_smoke.py` with a complete fictional fixture and repeat-run proof
- **Done when:** a no-mock CLI cycle creates both private reports and the expected three action proposals, a confirmed budget-follow-up action stays open until both completion references are recorded, an exact reply joins its existing action, a repeat cycle has zero new actions and preserves the decision bytes, and unrelated mail remains uncategorized. All three CI jobs pass after the Step 38 browser repair, including the emulator and native jobs; Ruff, strict mypy, and identity guard pass. Record local-suite scope explicitly if the emulator is unavailable there.
- **Depends on:** 54

<!-- autofix-applied: 2026-09-23 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 56: Attended private-archive acceptance
- **Status:** PENDING
- **Problem:** Run the new action stage on the current private archive and check that its proposals correspond to the three non-reimbursement cases in the September 23 triage, with no reimbursement request, approval email, acknowledgment, or meeting-only mail incorrectly promoted.
- **Type:** operator
- **Issue:** #92
- **Files:** `reports/output/mail-actions.json`, `reports/output/mail-action-decisions.json`, `reports/output/mail-action-queue.html`, `reports/output/mail-action-acceptance.md`
- **Produces:** a private acceptance record under `reports/output/` containing checked source keys, any manual classifications, counts, and the operator's judgment
- **Done when:** the operator inspects the private action report, confirms source/thread/attachment references for the three triage cases, records the correct owner and next action for each, checks that the budget follow-up remains open until both budget surfaces are evidenced, and verifies a second run preserves the decisions. No actual budget update or outgoing email is performed by this step.
- **Depends on:** 55

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step F3: Preserve generated-single payment context after settlement
- **Legacy alias:** REPLAY-1
- **Status:** PENDING
- **Type:** code
- **Problem / scope:** Restore replay when settlement clears email_context but the generated-single grammar is bound to bundle-held context and no live operator review is present. Reproduce through refresh_bundle and strict load_bundle; preserve frozen evidence identities and fail closed for changed mail. A refreshed settled bundle must replay identically.
- **Depends on:** none
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F4: Reconcile v1 payment amount with reviewed-effective totals
- **Legacy alias:** REPLAY-2
- **Status:** PENDING
- **Type:** code
- **Problem / scope:** The frozen v1 lane records source total while the loader checks reviewed-effective total. Preserve historical reproducibility without accepting mismatched v2 payments; define explicit migration/compatibility handling and round-trip via actual refresh and loader. Do not silently rewrite settled history.
- **Depends on:** F3
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F5: Replay historical Check and discrepancy histories
- **Legacy alias:** REPLAY-3
- **Status:** PENDING
- **Type:** code
- **Problem / scope:** Repair v1 non-Zelle/Check and discrepancy histories that cannot replay under v2 although reproducibility is promised. Pin old accepted cases and v2 quarantine negatives through production callers; keep strict payment authorization and companion clarification/receipt events.
- **Depends on:** F4
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F6: Close second-mailbox handover coverage gap
- **Legacy alias:** MAIL-COVERAGE
- **Status:** PENDING
- **Type:** operator
- **Problem / scope:** Obtain and privately reconcile the handover mailbox/archive; current mailbox refetch cannot fill absent mail. Check received-date coverage, especially thin June. Use alternate mailbox export if necessary, union and dedup sources, retain original evidence. Record generic coverage outcome only.
- **Depends on:** none
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F7: Engineer the approved shared-ticket lifecycle
- **Legacy alias:** LIFECYCLE
- **Status:** BLOCKED (held for the stated prerequisite or operator decision)
- **Type:** planning
- **Problem / scope:** After M8 acceptance, specify durable discovery/catalog capacity and pagination, IDs, source/revision compatibility, transaction/API/error contracts, rollback and code/hosted gates. Processor-only creation/edit/submit/withdraw/archive/restore; both roles read shared drafts/history; positive exact-cent complete items required at submit; immutable submitted revisions; reviewer approval vs withdrawal race has one winner; no permanent deletion; archived state read-only except restore/replay. Preserve all eight acceptance scenarios in the [product contract](../plan-reference/shared-ticket-lifecycle-contracts.md).
- **Depends on:** 37
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F8: Roll reimbursement actuals into Budget Timeseries
- **Legacy alias:** TIMESERIES
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Aggregate reviewed per-category ledger actuals into reporting source with provenance, snapshot-before-write and idempotent reconciliation. Reports currently read Budget Timeseries rather than Reimbursements; do not imply integration exists. Design before implementation.
- **Depends on:** F5
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F9: Define explicit operator-review supersession
- **Legacy alias:** SUPERSEDE
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Persisted content-addressed operator review cannot be edited in place; current retirement workaround is not an implemented supersede contract. Plan audited replacement preserving event history and frozen evidence before building.
- **Depends on:** F5
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step 50: Add local receipt proposal picker
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** After real CLI confirm acceptance, replace JSON-edit friction with a local HTML picker for ambiguous multi-asset proposals. Preserve stale-bundle refusal, confirmed_page_ids-only editing, human boxes, exact per-item page identity and no hidden auto-approval.
- **Depends on:** 49
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F10: Consider verified receipt-page budget relief
- **Legacy alias:** COMPACT
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Only when the 100 MiB cap forces it, separately plan compaction/re-encoding of human-verified pages with backups, independent readability comparison and preservation of every link/box/fingerprint. Current baseline 221 pages, 92.3 MiB; do not rewrite them during autofill.
- **Depends on:** 49
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F11: Move image decode into attested LPAC boundary
- **Legacy alias:** LPAC-IMAGE
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Once render protocol exists, assess migration of the bounded image-child protocol into LPAC. Ordinary capped child residual account-level filesystem/network authority remains explicitly accepted A1, not a security sandbox claim. Preserve Windows/Linux policy and real boundary tests.
- **Depends on:** 43
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F12: Plan direct MIME receipt attachment harvesting
- **Legacy alias:** ATTACHMENTS
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Separately assess MIME attachment harvesting beyond hosted URLs; preserve per-ticket source provenance, bounded untrusted decoding and same sidecar verification. No parsing-policy expansion is implied by docs cleanup.
- **Depends on:** 49
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F13: Carry reciprocal cross-track issue notes
- **Legacy alias:** COORDINATION
- **Status:** PENDING
- **Type:** code
- **Problem / scope:** At the next explicitly authorized repo-sync, update #43 and #59 with wrapper/receipt stage coupling and relevant Phase9 issue amendments. This cleanup records the merged dependency but sends no GitHub messages.
- **Depends on:** none
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step F14: Retain decode CPU spread exception for ratification
- **Legacy alias:** CALIBRATION
- **Status:** BLOCKED (held for the stated prerequisite or operator decision)
- **Type:** operator
- **Problem / scope:** Review Step39 calibration record: Pillow12.2.0, 1472MiB memory and9s CPU/wall, ready5s and baseline256MiB. Subsecond CPU spread exception used15.625ms resolution rather than blindly applying>=1.2 ratio. Preserve measured record; no retuning under a docs gate.
- **Depends on:** none
- **Produces:** Verified implementation and regression evidence for code work; a reviewed bounded specification or private observation record for planning/operator work.
- **Done when:** The stated scope and failure cases are demonstrated through the real consumer; held/deferred work additionally requires its named entry gate. No model estimate is execution evidence.


### Step W2: Core financial story
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Core financial story: retain accepted summary; add projected expense composition with detailed raw-category legend; add actual spending and fundraising channel/progress with unclassified evidence disclosed. Prior wave real acceptance required; design chart contracts before build.
- **Depends on:** 25
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step W3: Operational rigor
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Operational rigor: source provenance and refresh, richer approvals/revisions, template drift, bounded retry and Google recovery, rendered visual QA, runtime audience guards, successor packaging and retention. No implicit scheduling/sharing authorization.
- **Depends on:** W2
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F15: Historical comparisons
- **Legacy alias:** W4-HISTORY
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Historical comparisons.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F16: Reserve and sustainability views
- **Legacy alias:** W4-RESERVES
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Reserve and sustainability views.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F17: Reimbursement commitments
- **Legacy alias:** W4-COMMITMENTS
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Reimbursement commitments.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F18: Budget-versus-actual comparisons
- **Legacy alias:** W4-VARIANCE
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Budget-versus-actual comparisons.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F19: Appendix generation
- **Legacy alias:** W4-APPENDIX
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Appendix generation.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F20: Additional graphics beyond accepted waves
- **Legacy alias:** W4-GRAPHICS
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Additional graphics beyond accepted waves.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F21: Themes and organization profiles
- **Legacy alias:** W4-THEMES
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Themes and organization profiles.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F22: CSV/QFX/OFX bank adapters
- **Legacy alias:** W4-IMPORT
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** CSV/QFX/OFX bank adapters.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F23: Insert into a larger presentation
- **Legacy alias:** W4-INSERT
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Insert into a larger presentation.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F24: Scheduling, separately authorized and observed
- **Legacy alias:** W4-SCHEDULE
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Scheduling, separately authorized and observed.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F25: Sharing and publishing with separate explicit permissions
- **Legacy alias:** W4-SHARE
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Sharing and publishing with separate explicit permissions.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F26: Assisted narrative from validated facts
- **Legacy alias:** W4-NARRATIVE
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Assisted narrative from validated facts.
- **Depends on:** W3
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F27: Apps Script nag emails/calendar triggers, Chrome-editable configuration, Google sign-in allowlist plumbing and flexible Vega-Lite charts; live private Drive report upload, concurrent-modification check and Markdown/plain-text report variants
- **Legacy alias:** ROOT-CLOUD
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Apps Script nag emails/calendar triggers, Chrome-editable configuration, Google sign-in allowlist plumbing and flexible Vega-Lite charts; live private Drive report upload, concurrent-modification check and Markdown/plain-text report variants.
- **Depends on:** none
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F28: Broader admin UI (React or HtmlService unresolved) beyond the bounded accepted Cloud Run workflow
- **Legacy alias:** ROOT-ADMIN
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Broader admin UI (React or HtmlService unresolved) beyond the bounded accepted Cloud Run workflow. Choose architecture separately; do not replace accepted IAP/Firestore proof.
- **Depends on:** none
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F29: One-year-ahead forecasting, bank-CSV/QuickBooks import, model-assisted narrative and board-ramp wiki (LLM and people-friendly)
- **Legacy alias:** ROOT-POWER
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** One-year-ahead forecasting, bank-CSV/QuickBooks import, model-assisted narrative and board-ramp wiki (LLM and people-friendly). Preserve existing deterministic reporting.
- **Depends on:** none
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.


### Step F30: Unattended receipt ingestion and linked Drive-file fetch remain deferred
- **Legacy alias:** ROOT-MAIL
- **Status:** DEFERRED
- **Type:** planning
- **Problem / scope:** Unattended receipt ingestion and linked Drive-file fetch remain deferred. Gmail tokens remain local and out of public Actions; changing that is a separate deliberate decision. Optional automatic inbox clearing remains unapproved; manual clearing is current.
- **Depends on:** none
- **Produces:** Bounded reviewed design with source contracts, code gates and real acceptance separated.
- **Done when:** Scope is designed and explicitly released from its deferred state; no implementation completion is asserted by this roadmap.

## Phase CFO: CFO workbook and Main Report Set v0

**Objective:** Replace ongoing bank PDF imports with the CFO workbook's Wells Fargo, WIX and PayPal tabs, preserving CFO source treatment and evidence, and produce the five coordinated private reports.
**Status:** Steps 57-62 DONE (2026-10-22; issues #96-#101 closed) and Step 64 DONE (2026-10-23; #104). Step 63 (#102) is IN PROGRESS: live runs were published on 2026-10-22 and 2026-10-23. Acceptance waits on the operator's review and the category crosswalk. Do not re-dispatch 57-62 or 64.
**Scope:** This phase only. Master remains the only dispatch/status owner. Steps 57-62 were dispatched with `--phase CFO --steps 57,58,59,60,61,62`; never dispatch the entire master. Step 63 is separate live operator acceptance.
**Contracts:** [CFO supporting specification](../plan-reference/cfo-main-report-set.md), including the inline record/identifier/quickstart contracts in section 10. Proposed files are explicitly new, not missing prerequisites.
**Discovery:** Former CFO-0 is DONE: read-only access, all seven tabs, source formulas, occupied Assumptions cells and P&L reproduction were verified privately. No issue is needed for completed discovery.
**Aliases:** CFO-1 = 57; CFO-2 = 58 + 59; CFO-3 = 60; CFO-4 = 61; CFO-5 = 62; CFO-6 = 63; Step 64 has no alias. No existing numeric step is renumbered.
**Dependencies:** 57 -> 58 -> 59 -> 60 -> 61 -> 62 -> 64 -> 63. Sequential because each step consumes the prior production contract. No parallel-safe code pair.
**Accepted direction:** July-June school summaries; January-December P&L; all outstanding carryovers and June mail acquisition preserved; valid recorded adjustments apply immediately; receipt images/red marks and copy text retained. The five reports are Reimbursement Queue, Reimbursement Summary, Budget Snapshot, Fundraising Summary and CFO P&L Summary.
**Overlap disposition:** Existing board-summary Steps 26-31 remain pending and are outside this invocation. Step 61 owns the shared summary render/export capability for this phase; Step 62 owns the combined runner. Future board-track dispatch must reuse that implementation and build only its additional accepted packet/single-page/launcher requirements. Do not mark any old acceptance complete or build a second competing renderer. Receipt 41-49 and actions 51-56 remain held/paused as recorded elsewhere.
**Review scope:** Review/redline/wrap and issue sync cover only Phase CFO and its supporting specification. They do not certify unrelated master tracks. Review artifacts live in `docs/plan-reconciliation/cfo-{review,wrap,sync}.md` and the proposal in `docs/plan-reference/cfo-main-report-set-proposal.html`.
**Model:** User selected an Opus session in Claude Code for the future build. The developer arm inherits that session; independent review lanes keep their own tier routing. No unsupported build-phase model flag is introduced. Codex cannot switch this session to Opus.
**Verification:** Focused tests for changed contracts, lint/type checks, installed-wheel resource smoke and one bounded real-component CLI cycle; Step 63 observes one live cycle. The user's targeted-testing instruction overrides default unrelated full-suite reruns. Record exact suites and counts; never call a subset the full suite.
**Stop/rollback:** Stop on source schema drift, invalid financial invariants, conflicting adjustments or private-data leakage. Preserve the prior complete publication and source snapshots. No CFO writes, payments, email sending, new scheduler or deployment.
**Effort:** Seven sequential code slices plus one live run; no wall-clock promise. Reassess after each slice against the user-visible command rather than adding infrastructure.
**Build record (2026-10-22, Steps 57-62):** each step passed independent review (`deep` for 57-60 and 62, `code` for 61); checkpoint commits 448d7ec, fb4b60d, d5af712, 8f05d31, 6d23d94, fc1de4f on top of baseline 47877bf. Final post-merge gate: mypy --strict, ruff check/format, identity guard and every test module except the six Firestore-emulator `test_shared_workflow_*` modules — 2,176 passed, 3 environment skips; empty-browser run skips exactly the 7 `test_chromium_*` and 2 receipt-viewer cases (11 `test_chromium_*` after Step 64: 10 in test_main_report_render.py, 1 in test_main_report_runner.py); installed-wheel template smoke passed; `end-to-end-run` fixture cycle ~0.5 s browser-free / ~5 s with Chromium. Files beyond the per-step Files lines (all review-accepted): `report_source.py` (shared `row_measure`), `sources.py`/`reconcile.py`/`models.py` shared helpers across later steps, `sheets.py` (single owners: `SHEETS_FAILURES`, `http_status`, `is_transient_status`, `backoff_delay`, `pause`, `write_raw_ranges(retry=False)`, plus a fix for a pre-existing retry bug that doubled ranges), `reimbursement_report.py` (public `PNG_SIGNATURE` alias only), `tests/conftest.py` shared fakes, `ci.yml` browser-skip assertions, `config.example.toml`. Contract §10 signatures were amended to the shipped forms (`facts.build_from`, keyword-only `captures`/`crosswalk`, `render.write` context/exporter, `runner.run(options, config, ...)`, exit 130). Live-only assumptions for Step 63 are listed in docs/main-report-set.md ("Confirm on the first live run", plus the `output_dir` rule under "Before the first run"): published P&L layout and zero-as-dash, "Posted" status, WIX/PayPal fee sign, header-label overrides.

<!-- autofix-applied: 2026-10-21 -->
### Step 57: Import the three CFO feeds with provenance
- **Status:** DONE (2026-10-21)
- **Type:** code
- **Problem:** Implement private config bindings and read-only source adapters for the inspected Wells Fargo, WIX, and PayPal tabs. Capture dated snapshots, validate schemas and source coverage, retain exact money and original values, and detect source changes. Keep adopted budget targets and source-native dates separate from annual synthetic report rows. Retire bank PDF extraction from this new reporting path, retaining historical files and receipt processing.
- **Issue:** #96
- **Legacy alias:** CFO-1
- **Files:** `pta_finance/main_reports/models.py`, `sources.py`, `pta_finance/config.py`, `config.example.toml`, `tests/test_main_report_sources.py`, `tests/test_config.py` (new main_reports files; existing config extended).
- **Existing context:** SheetsClient accepts a separate spreadsheet_id and injected gspread client; default connect uses broad default scopes. Construct the CFO client with explicit spreadsheets.readonly scope. read_timeseries is the adopted budget adapter; its to_inputs annual synthetic dates are not transaction evidence.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** `main_reports` source/model components, optional config, fictional fixtures, and a provenance manifest.
- **Done when:** Each observed source shape is represented by a fictional fixture, including WIX two-row headers and PayPal repeated-ID detail rows, that reaches the production reader/adapter; duplicate import is idempotent; row edits, missing fields, changed source captures, subtotal rows, and missing coverage are handled explicitly. No CFO writes or bank PDF extraction occur.
- **Depends on:** discovery complete

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `pta_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 58: Reconcile processor activity to the CFO bank basis
- **Status:** DONE (2026-10-21)
- **Type:** code
- **Problem:** Reconcile source identities, signed category splits, processor overlap, transfers, refunds, and fees into a CFO-compatible source view with explicit unresolved discrepancies. Do not count processor sales and bank settlements as additive revenue.
- **Issue:** #97
- **Legacy alias:** CFO-2
- **Files:** `pta_finance/main_reports/reconcile.py`, `models.py`, `tests/test_main_report_reconcile.py` (new).
- **Existing context:** Consume the captured rows from Step 57. The source P&L expands signed bank splits, excludes exact Internal Transfer, and nets by category/month before income/expense classification. WIX and PayPal overlap; PayPal detail rows repeat parent IDs.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Reconciliation records, exact source P&L controls, category crosswalks, and discrepancy records.
- **Done when:** The production reconciliation caller proves split conservation, source monthly-category-net parity, legitimate duplicate preservation, WIX/PayPal overlap handling, no processor/bank double counting, and explicit unmatched/refund/fee conflicts. No financial writes occur.
- **Depends on:** 57

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `pta_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 59: Apply recorded reporting adjustments
- **Status:** DONE (2026-10-21)
- **Type:** code
- **Problem:** Persist evidence-backed reporting corrections in the bounded Assumptions journal and immediately project them without changing source transactions or reimbursement decisions.
- **Issue:** #98
- **Legacy alias:** CFO-2 adjustments (split from reconciliation)
- **Files:** `pta_finance/main_reports/adjustments.py`, `models.py`, `tests/test_main_report_adjustments.py` (new); reuse `pta_finance/sheets.py`, `pta_finance/backup.py`.
- **Existing context:** Assumptions already contains formulas and prose. backup.snapshot_raw_tab preserves typed entered values. Use a new bounded append-only journal below existing cells; do not edit earlier adjustment rows to supersede them.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Validated adjustment journal reader/writer and source-to-adjusted projection.
- **Done when:** Production adjustment operations prove exact preconditions, immediate effect after verified recording, idempotent uncertain-write recovery, append-only supersession/reversal, formula preservation, and visible concurrent-edit/write failures. Conflicting or unresolved target revisions block adjusted publication. Source-only mode never writes. Reporting corrections cannot approve or pay a claim.
- **Depends on:** 58

**Contract:** Supporting specification sections 6D and 10; Sheets preflight/readback checks are not a server-side compare-and-swap guarantee.

<!-- autofix-applied: 2026-10-21 -->
### Step 60: Align school-year facts and preserve carryovers
- **Status:** DONE (2026-10-22)
- **Type:** code
- **Problem:** Build item/transaction-level projections for July–June summaries and January–December P&L. Preserve June acquisition and historical evidence. Keep all outstanding requests in the queue; separate prior-year obligations and current payments of them from current-year expense activity. Explain period, recognition, and payment differences without changing stored IDs or receipt fingerprints.
- **Issue:** #99
- **Legacy alias:** CFO-3
- **Files:** `pta_finance/main_reports/facts.py`, `models.py`, `tests/test_main_report_facts.py` (new); preserve `pta_finance/report_source.py` and reimbursement schemas.
- **Existing context:** plan_bundle_refresh returns a candidate without changing stable item identities. A reporting projection must not re-run payment adjudication or change receipt fingerprints. Keep annual adopted targets distinct from dated activity.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Shared reporting-period and fact projections, carryover sections, and a traceable reconciliation bridge.
- **Done when:** June/July and December/January boundaries, cross-year claims, missing dates, June expenses paid in July, and old outstanding requests behave as specified. Shared-scope totals reconcile; expense and settlement are not counted twice. Budget-year config, accepted decisions, receipt annotations, and collection cutoff remain intact.
- **Depends on:** 59

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `pta_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 61: Render the complete Main Report Set
- **Status:** DONE (2026-10-22)
- **Type:** code
- **Problem:** Reuse the existing queue and accepted summary styling to generate Reimbursement Queue, Reimbursement Summary, Budget Snapshot, Fundraising Summary, and CFO P&L Summary. Replace private edition constants with validated facts. Preserve queue copy text and receipt images. Show period, source freshness, run identity, and differences between CFO source and adjusted totals; do not invent a calendar-year budget.
- **Issue:** #100
- **Legacy alias:** CFO-4
- **Files:** `pta_finance/main_reports/render.py`, `export.py`, `pta_finance/reports/templates/main_reports/`, `tests/test_main_report_render.py`, `pyproject.toml`, `uv.lock` (new render/export files; extend extras); reuse `pta_finance/reimbursement_report.py`.
- **Existing context:** build_report(data_path, output_path) emits the queue, validates receipt sidecars, and writes .copy.txt. Reuse it unchanged. Existing private summary scripts are style references with dated constants. The public reports builder has an external privacy guard.
- **Flags:** --reviewers code --isolation worktree
- **Produces:** Four reusable summary renderers/templates, private HTML report index, summary PDF/PNG export, and existing queue/copy-text companions.
- **Done when:** A single fixture input set generates all five readable reports with correct date labels, monthly/YTD P&L, source-to-adjusted bridge, and matching shared-scope totals. Browser/export checks prove readable layouts and retained receipt access; unchanged external/public report models retain their privacy guard.
- **Depends on:** 60

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `pta_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 62: Wire the end-to-end command and bounded smoke gate
- **Status:** DONE (2026-10-22)
- **Type:** code
- **Problem:** Add `pta-finance end-to-end-run --as-of YYYY-MM-DD` with optional existing mail fetch-window flags and dry-run behavior. Reuse reimbursement refresh/receipt preparation, capture all sources, apply recorded adjustments, build every report in a versioned private run, and publish only after validation. Preserve reimbursement-only commands. Use a single current-run pointer and explicit compatibility-file refresh status; retain the previous complete set on failure.
- **Issue:** #101
- **Legacy alias:** CFO-5
- **Files:** `pta_finance/main_reports/runner.py`, `pta_finance/cli.py`, `tests/test_main_report_runner.py`, `tests/test_reimbursement_cli.py`, `docs/main-report-set.md`, `README.md`, `CLAUDE.md` (new runner/test/guide).
- **Existing context:** _cmd_update_reimbursements already wires refresh, receipt preparation, and queue output. Reuse production components with staged paths; calling its in-place command blindly would publish the queue too early.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Production runner/CLI wiring, operator docs, run manifest and index, failure recovery, and a bounded real-component smoke check.
- **Done when:** The production CLI completes a small source-to-five-report cycle with real adapters/facts/renderers/publication, targeting 60 seconds for local fixtures. Dry-run performs no local or remote writes and rejects mail acquisition and adjustment-write options, failed fetch/render preserves prior publication, reruns do not duplicate adjustments, and every artifact identifies the same captured input set. No bank PDF extraction, scheduler, mail sending, or CFO workbook write is invoked.
- **Depends on:** 61

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `pta_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 63: Regenerate and reconcile the live Main Report Set
- **Status:** IN PROGRESS. Live runs were published on 2026-10-22 and 2026-10-23, after the live-only fixes and Step 64 recorded below. Still open: the category crosswalk (budget actuals read Unknown until it exists) and the operator's acceptance review.
- **Type:** operator
- **Problem:** Run the completed command against the authorized live source tabs and our workbook. Record defensible adjustments as authorized, generate all five current reports, and expose actual remaining discrepancies. Check the report experience and period bridge using retained snapshots; preserve originals and prior published outputs.
- **Issue:** #102
- **Legacy alias:** CFO-6
- **Files:** Private versioned report outputs and reconciliation evidence under `reports/output/`; no source-code artifacts.
- **Existing context:** Run only after Step 62 is delivered. This observes real Sheets/authentication, source reconciliation, receipt images, and report publication; local fictional smoke is not live acceptance.
- **Produces:** Updated private Main Report Set, adjustment/discrepancy evidence, and source-to-report reconciliation results.
- **Done when:** All five reports open; the four summary pages and the index show one run/as-of identity with their correct periods, and the queue, its copy text and the PDF/PNG exports match the run manifest's hashes (the reused queue carries no in-file run ID); school-year summaries agree on comparable totals; every P&L difference is explained or explicitly unresolved; prior-year outstanding requests, receipt images/red circles, and copy text are present. The source workbook is unchanged. A second full unrelated native-PDF/shared-workflow test campaign is not part of this acceptance.
- **Depends on:** 62, 64

### Step 64: Rebuild the four summaries to the accepted one-page board design
- **Status:** DONE (2026-10-23; 96a57a5 + follow-up 38efe36)
- **Type:** code
- **Problem:** The first live run (2026-10-22) showed that Step 61 did not reuse the accepted summary styling. The accepted briefs lived only in private files that the public build could not read, so it produced fluid audit pages: the summaries printed to 42-95 pages each against 1 for each accepted reference. Rebuild the Reimbursement Summary, Fundraising Summary, Budget Snapshot and CFO P&L Summary templates and their render models to the public design contract, preserving every fact, total, reconciliation rule and the run-identity/privacy guards.
- **Issue:** #104
- **Flags:** `--reviewers code`
- **Files:** `pta_finance/main_reports/render.py`, `pta_finance/reports/templates/main_reports/*.j2`, `tests/test_main_report_render.py` (plus `tests/test_main_report_runner.py` only where it asserts rendered layout), `.github/workflows/ci.yml` (browser-case allowlists).
- **Existing context:** Design contract: [main-report-design.md](../plan-reference/main-report-design.md) (operator decisions D1-D6 recorded 2026-10-23: template narratives only, bank-basis fundraising income labelled, net-flow Budget Snapshot without balances, default header wording, P&L appendix may take two landscape pages). Data contract unchanged: [cfo-main-report-set.md](../plan-reference/cfo-main-report-set.md). Audit detail moves to counts plus pointers to the run's `records/*.json`; unknown is still never shown as zero.
- **Produces:** Four one-page portrait summaries (the P&L adds a landscape appendix), a short index, and deterministic one-page-fit tests on fictional fixtures.
- **Done when:** With fictional fixtures, each of the three summaries prints exactly one US Letter portrait page and the P&L prints one portrait page plus its landscape appendix (Chromium export). No inline discrepancy-ID or bridge-evidence lists remain. Every spec section 5 acceptance item passes. Existing fact, privacy and run-identity tests pass. ruff, format, `mypy --strict` and the main-report test modules are green.
- **Depends on:** 61, 62

**Live-use record (2026-10-22/23, Step 63 in progress):**
- *First live use exposed four adapter assumptions that held only for fictional fixtures* (`5dc3c93`, user-debug plus `code` review):
  - padded header labels;
  - WIX date labels carrying a `GMT ±H:MM` suffix, and the product column labelled `Name`;
  - comma timestamps;
  - the PayPal `POS Payment` type.
  The same commit gave the read-only capture clients more than 60 s of 429 backoff, because one capture makes about 75 reads against Google's ~60-per-minute quota.
- *A single CFO split typo blocked the whole set with no in-tool remedy* (`54595fc`). By operator decision, `split_sum_mismatch` is now a warning with an explicit "Unallocated split difference" remainder.
- *Step 64* rebuilt the summaries (`525626b` contract, `96a57a5`, follow-up `38efe36`). Review was `code` plus a private visual-parity lens against the accepted briefs, over 3 iterations. The live set now prints 1/1/1 pages, and the P&L 1 portrait + 2 landscape pages, against 42-95 pages before.
- *Root cause of the design miss:* Step 61 was told to reuse accepted styling that existed only in private files the public build could not read. Carry private designs into a public, identity-free contract before dispatch.
- *Gates:* main-report, config and smoke modules: 831 passed. mypy --strict, ruff, format and the identity guard are clean. The full suite was not re-run: spec section 5 item 14 (full suite) was waived under the Verification clause above, and the CI allowlists in `ci.yml` were not exercised until the allowlist fix. Run the full suite or CI before flipping Step 63.
- *Live configuration notes:*
  - Bank coverage is declared privately, with operator evidence.
  - Tab bindings match by name, so the CFO's 2026-10-23 tab renames ("Profit & Loss 2026", "Budget Tracker 2026-2027") required a config update.
  - The new CFO tabs "Transactions" and "WIX Settlements" are not yet bound.


**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `pta_finance/main_reports/` when only a basename is shown.

## 11. Compute target

Python3.12+/uv on Windows. Native statement/PDF LPAC and Tesseract5 require supported Windows and actual boundaries; portable image child supports Windows/Linux only. Chromium export needs explicitly installed browser. Shared integration uses local Firestore emulator and actual installed wheel; live Google evidence is separate. No private financial data enters a model service.

## 12. Time budget

See [build-estimates.json](build-estimates.json) and [estimate notes](build-estimates.md). Ranges are model forecasts, not measured performance or calendar promises. Held/deferred units are excluded from an executable critical path. Manual waits and operator attention are separate. Details are tied to the exact master hash.

## 13. What's NOT in this plan

No new automatic execution is authorized. Existing exclusions remain in supporting contracts. Old root summaries are subsumed by the detailed track leaves; old provisional Slides26-35 numbering is superseded by symbolic future-wave IDs; completed32-35 proof is archived complete, not rebuilt. No change to payment authorization, evidence_payload/source_receipt_urls_v1 fingerprints, verified human boxes or accepted Google/IAP architecture. No generic multi-bank parser, universal UI, scheduler, public-data migration, private input move or token relocation is implied. Private doc/ remains application input, intentionally excluded from documentation consolidation.

## 14. Tracking

Ambition-compatible F identifiers map to legacy semantic labels in [unit aliases](../plan-reconciliation/unit-aliases.json). Those source labels remain meaningful in prose; dependency fields use canonical identifiers.


Existing issue IDs in leaves are retained. Umbrellas: Gmail22, Slides40, board55, shared proof62, queue67, receipt71, actions86. Source maps and overlap report explain every disposition. Future issue synchronization is a separately authorized operation; no duplicate issues created. The root plan.md is only a discovery redirect. Master status overrides dated supporting baseline prose.

## 15. Plan history

2026-10-14: merged root roadmap and all feature plans; preserved exact source bytes; completed proof32-35 archived to completed; other originals archived as merged with outstanding acceptance/followups retained. Public documentation consolidated into docs, private doc/ input tree preserved. Reconciled receipt39/40 DONE versus stale root prose; kept41 timing hold and51 paused handoff; replay defects and all deferred scopes retained. Routine sequencing/duplication decisions use the user's delegated discretion; no architecture hold resolved by assumption.

## Appendix: CFO decisions

Approval: 2026-10-21. P entries preserve explicit user choices. D entries accepted by the assistant on the user's explicit delegated authority for this planning handoff; no claim of separate human visual review. This approval does not mark implementation or live acceptance complete.

### Decision Inventory

| ID | P/D | choice | status |
|---|---|---|---|
| P1 | P | CFO workbook is the ongoing Wells Fargo, WIX and PayPal source; retire default bank PDF imports. | operator-picked |
| P2 | P | July-June school summaries, January-December P&L; retain all outstanding carryovers and the existing mail collection window. | operator-picked |
| P3 | P | Valid adjustments recorded in our Assumptions journal affect reports immediately. | operator-picked |
| P4 | P | Publish the five-report Main Report Set with receipts/red marks and copy text retained. | operator-picked |
| P5 | P | Targeted verification and one live cycle; avoid repeated unrelated test campaigns. | operator-picked |
| P6 | P | Review, redline with delegated approval, wrap and sync now; build later in an Opus session. | operator-picked |
| D1 | D | Preserve CFO bank-based monthly-category net treatment, with processor detail as reconciled enrichment. | accepted by delegated approval 2026-10-21 |
| D2 | D | Append a versioned immutable journal below existing Assumptions content; require target revision/precondition matches. | accepted by delegated approval 2026-10-21 |
| D3 | D | Publish immutable private run folders through one atomic HTML index; refresh compatibility filenames afterwards. | accepted by delegated approval 2026-10-21 |
| D4 | D | Use numeric Steps 57-63 in Phase CFO, split reconciliation and adjustment writes, and build only 57-62 automatically. | accepted by delegated approval 2026-10-21 |
| D5 | D | Use deep review for financial identities, reconciliation, journal, facts and publication; code review plus browser evidence for rendering. | accepted by delegated approval 2026-10-21 |
| D6 | D | Treat source coverage gaps and ambiguous matching as visible unresolved data, never invented zeroes or balancing entries. | accepted by delegated approval 2026-10-21 |
| D7 | D | Use strict no-write dry-run, bounded capture retries and local serialization with explicit Sheets external-edit race limits. | accepted by delegated approval 2026-10-21 |
