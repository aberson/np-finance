# np_finance master plan

## 1. What This Is

Reusable private finance reporting and reimbursement evidence, with independently scoped delivery tracks.

Proposal: docs/plan-reference/cfo-main-report-set-proposal.html (current CORE-BRIEFS extension; earlier CFO proposal retained as history).

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
  uv run np-finance report --fy 2027 --variant both
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
  forward, budget changes are made **directly in the configured editable tab (`FY2027 - Editable Internal Budget` for the current workbook)** and synced — which removes the
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
- **Done when:** `np-finance fetch-mail --since <recent-date> --dry-run` is run in a **fresh shell ≥8 days after consent** and the outcome is recorded. In *Testing* mode a re-consent prompt at that point is the **expected** result (amended 2026-08-26), and re-approving then exiting 0 satisfies this step — it confirms the ~weekly cadence the operator should plan around. A run that exits 0 with no prompt is also fine; neither outcome is a failure.
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
- **Files:** `np_finance/treasurer_slides/bank_statements.py`,
  `np_finance/treasurer_slides/{native_sandbox,native_worker}.py`, `.github/workflows/ci.yml`,
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
  primitive from `native_sandbox._make_job_object` into the shared leaf `np_finance/process_limits.py`,
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
- **Files:** `np_finance/treasurer_slides/reconciliation.py`,
  `tests/test_treasurer_slides_source_authority.py`, and fictional overlap/balance fixtures
- **Produces:** `np_finance/treasurer_slides/reconciliation.py`, overlap/balance fixtures, and
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
- **Files:** `np_finance/treasurer_slides/rules.py`,
  `np_finance/treasurer_slides/reconciliation.py`,
  `tests/test_treasurer_slides_rules.py`, `tests/test_treasurer_slides_reconciliation.py`, and
  fictional rule/cash-bridge fixtures
- **Produces:** `np_finance/treasurer_slides/{rules,reconciliation}.py`, fictional rule/cash-bridge
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
- **Files:** `np_finance/treasurer_slides/budget_goals.py`,
  `np_finance/treasurer_slides/facts.py`, `tests/test_treasurer_slides_budget_goals.py`,
  `tests/test_treasurer_slides_facts.py`, and fictional grid/fact fixtures
- **Produces:** `np_finance/treasurer_slides/{budget_goals,facts}.py`, fictional raw-grid/fact
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
- **Files:** `np_finance/treasurer_slides/summary.py`,
  `np_finance/treasurer_slides/template.py`, `tests/test_treasurer_slides_summary.py`, and
  `tests/test_treasurer_slides_template.py`
- **Produces:** `np_finance/treasurer_slides/{summary,template}.py`, fictional presentation
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
- **Files:** `np_finance/treasurer_slides/pipeline.py`,
  `np_finance/treasurer_slides/templates/fact_review.html.j2`, and
  `tests/test_treasurer_slides_pipeline.py`
- **Produces:** `np_finance/treasurer_slides/pipeline.py`,
  `np_finance/treasurer_slides/templates/fact_review.html.j2`, and
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
- **Files:** `np_finance/treasurer_slides/google_client.py`, `np_finance/config.py`,
  `config.example.toml`, `tests/test_config.py`, `tests/test_treasurer_slides_auth.py`, and
  `tests/test_treasurer_slides_workspace.py`
- **Produces:** the auth/workspace portion of `np_finance/treasurer_slides/google_client.py`,
  optional config in `np_finance/config.py`/`config.example.toml`, fake Google services,
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
- **Files:** `np_finance/treasurer_slides/google_client.py`,
  `np_finance/treasurer_slides/pipeline.py`, and
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
- **Files:** `np_finance/cli.py`, `scripts/check_no_identity.py`,
  `tests/test_treasurer_slides_cli.py`, `tests/test_treasurer_slides_smoke.py`, packaging/privacy
  tests, `docs/generating-treasurer-summary.md`, `README.md`, `SETUP.md`, `CLAUDE.md`, and `plan.md`
- **Produces:** three commands in `np_finance/cli.py`; extended `scripts/check_no_identity.py`;
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
  uv run np-finance init-treasurer-summary-template --pptx "<private-tokenized-template>" --config config.toml
  uv run np-finance prepare-treasurer-summary --inputs "<private-input-manifest>" --config config.toml
  Invoke-Item "<private-run-directory>\review.html"
  uv run np-finance create-treasurer-summary --run "<run-id>" --approval-sha256 "<approval-digest>" --config config.toml
  Invoke-Item "<private-run-directory>\candidate.receipt.json"
  uv run np-finance create-treasurer-summary --run "<run-id>" --approval-sha256 "<approval-digest>" --config config.toml
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
- **Files:** `np_finance/reimbursement_summary.py`, `np_finance/cli.py`, `tests/test_reimbursement_summary.py`, `tests/test_reimbursement_cli.py`, `tests/fixtures/reimbursement_summary/`.
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
- **Files:** `np_finance/reimbursement_summary_render.py`, `np_finance/reports/templates/reimbursement_board_summary.html.j2`, `np_finance/cli.py`, `tests/test_reimbursement_summary_render.py`, `tests/fixtures/reimbursement_summary/`.
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
- **Files:** `np_finance/reimbursement_summary_render.py`, `np_finance/cli.py`, `pyproject.toml`, `uv.lock`, `tests/test_reimbursement_summary_render.py`, `.github/workflows/ci.yml`.
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
- **Produces:** the minimal render request branch in `np_finance/treasurer_slides/bank_statements.py` (Problem above; Step 43 extends it). With it, so that the spike never scores unvalidated worker output, comes the broker-side reader for the `rendered` frame, together with its tampered-frame tests in `tests/test_treasurer_slides_lpac_render_spike.py`. The reader enforces exact key sets, bounded decompression with an empty-leftover assertion, `len(decompressed) == raw_length == width × height`, the digest check, and `page_number`/`page_count` agreement with the launch. The same step adds `RenderedPage`, the `ReceiptRenderError` base class only (no subclasses), and a single-page broker launch helper. Step 43 extends these and does not rebuild them (operator decision 2026-10-10). The step also produces a committed generator for two fictional fixture PDFs — the non-embedded-font subject and its embedded-font twin (§ 9: no committed binary). The subject is hand-written PDF syntax using the non-embedded standard Type1 `/Helvetica`, following the `_fictional_pdf_bytes` precedent in `tests/test_treasurer_slides_bank_statements_native.py`. The twin carries the same text and is built at test time with `pypdfium2` (`PdfDocument.new()`, the raw `FPDFText_LoadFont` / `FPDFPageObj_CreateTextObj` / `FPDFText_SetText` / `FPDFPage_InsertObject` / `FPDFPage_GenerateContent` calls, then `PdfDocument.save`). It embeds a TrueType face read at test time from the Windows font directory, `%WINDIR%\Fonts\arial.ttf`, which is the usual Windows substitute for Helvetica, so the glyph shapes match. No font byte is committed; `tests/test_treasurer_slides_lpac_render_spike.py` added to the `windows-native-sandbox` job's pytest file list in `.github/workflows/ci.yml` (that job runs a hardcoded file list, so a new test file it does not name never executes); and `docs/findings/step-41-lpac-render.md` recording the measured verdict, every anchor score and the pinned thresholds in every case — plus `docs/findings/step-41-lpac-render-blocked.md` on the failure verdict only
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
- **Produces:** render limits, request/response, and validation in `np_finance/treasurer_slides/bank_statements.py`; tests in `tests/test_treasurer_slides_bank_statements_native.py` — or, when `docs/findings/step-42-pdf-boundary.md` exists, the files and tests that findings file names for the recorded boundary
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
- **Produces:** PDF path in `np_finance/receipt_pages.py`; tests covering multi-page output, the page ceiling, the fail-closed path on hosts the recorded boundary does not support, the PDF outcome classes and start-failure abort below, and the cap pin below
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
- **Produces:** `np_finance/receipt_link.py`, `tests/test_receipt_link.py`, a committed fictional proposals example, and the additive accessor in `np_finance/receipt_ingest.py` that exposes an already-parsed `Submission` by its archived message without widening the frozen `source_receipt_urls_v1` digest surface
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
- **Produces:** `np_finance/cli.py` stage and subparsers, `np_finance/config.py` block, `config.example.toml` with fake hosts, updated `tests/test_reimbursement_cli.py`
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
- **Produces:** updates to `CLAUDE.md` (§§ 2, 3, 4, 7 and the "prepared offline" sentence), `docs/receipt-viewer.md`, `docs/loading-receipts.md`, `README.md`, and `uv.lock` re-locked with `uv lock` (no upgrade); no edit to `np_finance/receipt_geometry.py`, to this plan or to any other plan's file
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
uv run np-finance link-receipts hosts --mail-root mail_samples
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
uv run np-finance update-reimbursements --fetch-since 2026-10-02 --no-fill-receipts
```

Then record the baseline: the linked and unlinked counts (this re-renders the HTML from the
unchanged bundle; nothing else is written).

```powershell
uv run np-finance report-reimbursements
```

Then list the tickets that arrived after the cutoff, from the refreshed bundle, grouped by distinct
upload-asset count (offline; opens no socket).

```powershell
uv run np-finance link-receipts audit --since 2026-10-09
```

Then prove the decode child starts and attests on this machine. The summary must read exactly
`1 passed`; a skipped or deselected result fails clause (e).

```powershell
uv run pytest -q -rs tests/test_receipt_decode_budget.py -k decoding_pid_is_the_limited_process
```

Then run the fill stage, with no mail fetch.

```powershell
uv run np-finance update-reimbursements --fill-receipts
```

Then read the per-asset fetch and page outcomes, including any decode refusal or child error.
Candidate pages awaiting `confirm` are referenced by the proposals file, so they are never listed as
unreferenced; a listed page file is a leftover of an interrupted run, for the operator to delete.

```powershell
uv run np-finance link-receipts audit
```

Then, only if clause (g)'s evidence is missing, probe an already-linked ticket. The evidence is
missing when the fill run's `receipt assets` line shows no `fetched`, or when `audit` lists a `pdf`
asset with no `paged` PDF page outcome. Pick a linked ticket in the queue and replace REF with its
ref. For the PDF seam, prefer a ticket whose source receipt opens with page navigation, because a
multi-page upload is usually a PDF. The probe's line names each asset's media type, so try another
ticket if none is `pdf`. The probe writes nothing live, and the two hashes must match.

```powershell
Get-FileHash reports/output/reimbursement-report.receipts.json
uv run np-finance link-receipts probe --ticket REF
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
uv run np-finance link-receipts confirm --proposals reports/output/reimbursement-report.receipt-proposals.json
```

Only if `confirm` refused with `ReceiptProposalsStaleError`, regenerate the file while keeping its
edits (offline; opens no socket), then run `confirm` again:

```powershell
uv run np-finance link-receipts propose
```

Finally, re-render and record the final linked and unlinked counts:

```powershell
uv run np-finance report-reimbursements
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
- **Later bounded addition (2026-10-28):** manually flagged email/check follow-ups now render inside the reimbursement report and persist through `end-to-end-run`, with source images using the existing sidecar. This does not implement the automatic scanner or change this step's paused status. See [report integration](../main-report-set.md#email-follow-ups-and-check-review-in-the-queue).
- **Status:** PAUSED — unfinished worktree; resume from [handoff](../phase10-build-handoff.md), never restart or discard it.
- **Problem:** Make `np-finance update-actions` scan the local archive and produce a strict private proposal/uncategorized inventory with stable source keys, narrow type reasons, attachment provenance, and exact-thread deduplication.
- **Type:** code
- **Issue:** #87
- **Flags:** `--reviewers deep`
- **Files:** `np_finance/mail_actions.py`, `np_finance/cli.py`, `tests/test_mail_actions.py`, `tests/fixtures/mail_actions/*.txt`
- **Produces:** `np_finance/mail_actions.py`, the `update-actions` entry point in `np_finance/cli.py`, `tests/test_mail_actions.py`, fictional source fixtures with `.txt` suffix
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
- **Files:** `np_finance/mail_actions.py`, `docs/mail-actions.md`, `tests/test_mail_actions.py`
- **Produces:** strict decision loader/merge in `np_finance/mail_actions.py`, fictional decision example in `docs/mail-actions.md`, decision-cycle tests in `tests/test_mail_actions.py`
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
- **Files:** `np_finance/mail_action_report.py`, `np_finance/reports/templates/mail_action_queue.html.j2`, `np_finance/mail_actions.py`, `tests/test_mail_actions.py`
- **Produces:** `np_finance/mail_action_report.py`, `np_finance/reports/templates/mail_action_queue.html.j2`, report tests in `tests/test_mail_actions.py`
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
- **Files:** `np_finance/cli.py`, `tests/test_reimbursement_cli.py`, `docs/mail-actions.md`, `README.md`, `CLAUDE.md`
- **Produces:** action-stage dispatch in `np_finance/cli.py`, regression tests in `tests/test_reimbursement_cli.py`, operator guide in `docs/mail-actions.md`, updated `README.md` and `CLAUDE.md`
- **Done when:** the production CLI prints action counts after a successful local refresh; `--dry-run` writes neither action nor reimbursement artifacts; a failed action stage reports the already-refreshed reimbursement boundary and preserves the prior action report; the standalone command and current reimbursement output stay usable; no action stage calls a Sheets writer, payment function, or Gmail sender.
- **Depends on:** 53

<!-- autofix-applied: 2026-09-23 -->

**Contract context:** All section references in this step resolve within [the supporting specification](../plan-reference/non-reimbursement-action-queue-contracts.md). Its complete interface, risk and testing clauses apply.


### Step 55: Real-component archive-to-report smoke gate
- **Status:** PENDING
- **Problem:** Exercise one full offline cycle through `np-finance update-reimbursements` using fictional mail, a fictional reimbursement bundle, and the actual classifier, decision loader, renderer, and CLI to catch producer/consumer key drift.
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
- **Files:** `np_finance/main_reports/models.py`, `sources.py`, `np_finance/config.py`, `config.example.toml`, `tests/test_main_report_sources.py`, `tests/test_config.py` (new main_reports files; existing config extended).
- **Existing context:** SheetsClient accepts a separate spreadsheet_id and injected gspread client; default connect uses broad default scopes. Construct the CFO client with explicit spreadsheets.readonly scope. read_timeseries is the adopted budget adapter; its to_inputs annual synthetic dates are not transaction evidence.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** `main_reports` source/model components, optional config, fictional fixtures, and a provenance manifest.
- **Done when:** Each observed source shape is represented by a fictional fixture, including WIX two-row headers and PayPal repeated-ID detail rows, that reaches the production reader/adapter; duplicate import is idempotent; row edits, missing fields, changed source captures, subtotal rows, and missing coverage are handled explicitly. No CFO writes or bank PDF extraction occur.
- **Depends on:** discovery complete

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `np_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 58: Reconcile processor activity to the CFO bank basis
- **Status:** DONE (2026-10-21)
- **Type:** code
- **Problem:** Reconcile source identities, signed category splits, processor overlap, transfers, refunds, and fees into a CFO-compatible source view with explicit unresolved discrepancies. Do not count processor sales and bank settlements as additive revenue.
- **Issue:** #97
- **Legacy alias:** CFO-2
- **Files:** `np_finance/main_reports/reconcile.py`, `models.py`, `tests/test_main_report_reconcile.py` (new).
- **Existing context:** Consume the captured rows from Step 57. The source P&L expands signed bank splits, excludes exact Internal Transfer, and nets by category/month before income/expense classification. WIX and PayPal overlap; PayPal detail rows repeat parent IDs.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Reconciliation records, exact source P&L controls, category crosswalks, and discrepancy records.
- **Done when:** The production reconciliation caller proves split conservation, source monthly-category-net parity, legitimate duplicate preservation, WIX/PayPal overlap handling, no processor/bank double counting, and explicit unmatched/refund/fee conflicts. No financial writes occur.
- **Depends on:** 57

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `np_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 59: Apply recorded reporting adjustments
- **Status:** DONE (2026-10-21)
- **Type:** code
- **Problem:** Persist evidence-backed reporting corrections in the bounded Assumptions journal and immediately project them without changing source transactions or reimbursement decisions.
- **Issue:** #98
- **Legacy alias:** CFO-2 adjustments (split from reconciliation)
- **Files:** `np_finance/main_reports/adjustments.py`, `models.py`, `tests/test_main_report_adjustments.py` (new); reuse `np_finance/sheets.py`, `np_finance/backup.py`.
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
- **Files:** `np_finance/main_reports/facts.py`, `models.py`, `tests/test_main_report_facts.py` (new); preserve `np_finance/report_source.py` and reimbursement schemas.
- **Existing context:** plan_bundle_refresh returns a candidate without changing stable item identities. A reporting projection must not re-run payment adjudication or change receipt fingerprints. Keep annual adopted targets distinct from dated activity.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Shared reporting-period and fact projections, carryover sections, and a traceable reconciliation bridge.
- **Done when:** June/July and December/January boundaries, cross-year claims, missing dates, June expenses paid in July, and old outstanding requests behave as specified. Shared-scope totals reconcile; expense and settlement are not counted twice. Budget-year config, accepted decisions, receipt annotations, and collection cutoff remain intact.
- **Depends on:** 59

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `np_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 61: Render the complete Main Report Set
- **Status:** DONE (2026-10-22)
- **Type:** code
- **Problem:** Reuse the existing queue and accepted summary styling to generate Reimbursement Queue, Reimbursement Summary, Budget Snapshot, Fundraising Summary, and CFO P&L Summary. Replace private edition constants with validated facts. Preserve queue copy text and receipt images. Show period, source freshness, run identity, and differences between CFO source and adjusted totals; do not invent a calendar-year budget.
- **Issue:** #100
- **Legacy alias:** CFO-4
- **Files:** `np_finance/main_reports/render.py`, `export.py`, `np_finance/reports/templates/main_reports/`, `tests/test_main_report_render.py`, `pyproject.toml`, `uv.lock` (new render/export files; extend extras); reuse `np_finance/reimbursement_report.py`.
- **Existing context:** build_report(data_path, output_path) emits the queue, validates receipt sidecars, and writes .copy.txt. Reuse it unchanged. Existing private summary scripts are style references with dated constants. The public reports builder has an external privacy guard.
- **Flags:** --reviewers code --isolation worktree
- **Produces:** Four reusable summary renderers/templates, private HTML report index, summary PDF/PNG export, and existing queue/copy-text companions.
- **Done when:** A single fixture input set generates all five readable reports with correct date labels, monthly/YTD P&L, source-to-adjusted bridge, and matching shared-scope totals. Browser/export checks prove readable layouts and retained receipt access; unchanged external/public report models retain their privacy guard.
- **Depends on:** 60

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `np_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 62: Wire the end-to-end command and bounded smoke gate
- **Status:** DONE (2026-10-22)
- **Type:** code
- **Problem:** Add `np-finance end-to-end-run --as-of YYYY-MM-DD` with optional existing mail fetch-window flags and dry-run behavior. Reuse reimbursement refresh/receipt preparation, capture all sources, apply recorded adjustments, build every report in a versioned private run, and publish only after validation. Preserve reimbursement-only commands. Use a single current-run pointer and explicit compatibility-file refresh status; retain the previous complete set on failure.
- **Issue:** #101
- **Legacy alias:** CFO-5
- **Files:** `np_finance/main_reports/runner.py`, `np_finance/cli.py`, `tests/test_main_report_runner.py`, `tests/test_reimbursement_cli.py`, `docs/main-report-set.md`, `README.md`, `CLAUDE.md` (new runner/test/guide).
- **Existing context:** _cmd_update_reimbursements already wires refresh, receipt preparation, and queue output. Reuse production components with staged paths; calling its in-place command blindly would publish the queue too early.
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** Production runner/CLI wiring, operator docs, run manifest and index, failure recovery, and a bounded real-component smoke check.
- **Done when:** The production CLI completes a small source-to-five-report cycle with real adapters/facts/renderers/publication, targeting 60 seconds for local fixtures. Dry-run performs no local or remote writes and rejects mail acquisition and adjustment-write options, failed fetch/render preserves prior publication, reruns do not duplicate adjustments, and every artifact identifies the same captured input set. No bank PDF extraction, scheduler, mail sending, or CFO workbook write is invoked.
- **Depends on:** 61

**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `np_finance/main_reports/` when only a basename is shown.

<!-- autofix-applied: 2026-10-21 -->
### Step 63: Regenerate and reconcile the live Main Report Set
- **Paid-state correction (2026-10-28):** operator-directed correction settles two verified check-paid requests and removes stale clarification prompts. Individual checks and superseded review evidence retained privately; consecutive refresh previews preserve the corrected states without changing unrelated tickets. General split-check ingestion and financial acceptance remain open.
- **Same-day retry (2026-10-28):** read-only Gmail consent and acquisition succeeded; a second report set published with seven new submissions. Five check images were inspected and matched privately. Check reconciliation remains open (split payments, paper-only requests, direct vendor payment and an apparent one-cent mismatch); no payment-status edits or financial acceptance. This supersedes the earlier mail blocker below.
- **Status:** IN PROGRESS. Live runs were published on 2026-10-22 and 2026-10-23, after the live-only fixes and Step 64 recorded below. Still open: the category crosswalk (budget actuals read Unknown until it exists) and the operator's acceptance review.
- **2026-10-28 operational refresh:** all five reports published; 15 artifacts validated and 16 compatibility copies refreshed. Mail acquisition was blocked by expired OAuth and timed-out consent; local evidence reaches 2026-10-23. The run retains 5,637 discrepancies, 8 issues and 19 coverage flags. Category Mapping date columns are captured but not applied to guidance. Emailed check images cannot automatically record payment under schema v2; audited operator records are available after evidence review. New check emails remain uninspected. See [run record and limitations](../main-report-set.md#latest-operational-run-2026-10-28). Focused payment/pipeline/runner tests: 234 passed; no full-suite acceptance claim. Financial acceptance remains open.

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
- **Files:** `np_finance/main_reports/render.py`, `np_finance/reports/templates/main_reports/*.j2`, `tests/test_main_report_render.py` (plus `tests/test_main_report_runner.py` only where it asserts rendered layout), `.github/workflows/ci.yml` (browser-case allowlists).
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


**Contract:** Supporting specification sections 5, 6 and 10 define the records, algorithms, failure cases and commands. New module paths in Files are relative to `np_finance/main_reports/` when only a basename is shown.

## Phase CORE-BRIEFS: Classroom budgets, the combined Budget Snapshot and Treasurer Notes

**Objective:** Running `uv run np-finance end-to-end-run` refreshes three operator-approved core board documents in the same private, captured, validated Main Report Set: Classroom Budgets (new), the redesigned Budget Snapshot (which absorbs the former Fundraising vs. Obligations draft), and Treasurer Notes (new).
**Planning state:** REVISED 2026-11-09 after operator design review; Publication 7 approved by the operator 2026-11-11 with D48; REVIEW-READY for this phase only. Step 65 is implemented; no other implementation or financial acceptance is claimed.
**Accepted financial rules (2026-11-04, revised 2026-11-09):** One as-of date governs every financial figure in these documents: the academic ledger is cut at `--as-of`, and balances come from the latest complete balances row on or before `--as-of`. Reserves for the scenario comparisons are the captured time-account (CD) balance; checking, savings and the credit-card balance never enter the reserve denominator. Specialist teacher contracts paid at the start of a school year and assigned to that school year by the source academic ledger are that year's expense and are already paid: no second current-year obligation exists, and next year's contracts fall outside this year's projection. This 2026-11-09 operator decision supersedes the 2026-11-04 rule that kept a current-year specialist obligation outstanding. Real account bindings, thresholds and amounts remain private, never hard-coded in production or this public plan.
**Status:** Step 65 DONE (2026-11-09). Steps 66, 67, 74, 68 and 69 PENDING. The operator paused Step 66 during its first developer round; that unreviewed candidate is not authoritative. Numeric ID 74 is newly reserved for Treasurer Notes and runs between Steps 67 and 68 (Steps 70-73 are reserved by the separately planned QUEUE-ARCHIVE phase); no existing step is renumbered.
**Scope of dispatch and review:** CORE-BRIEFS only, Steps 65-69 and 74. Never dispatch the entire master. Existing CFO Step 63 remains in progress; this phase must not mark its broader reconciliation accepted.
**Parent relationship:** Extends the shipped CFO Steps 57-62 and 64. Reuses their capture, facts, render/export and publication machinery. The bounded reserve comparison here does not complete deferred F16 (broader sustainability views), and planned remaining spending does not complete F17 (a commitment ledger).
**Planning baseline:** Planned 2026-11-04 at `724c9ffd1d3767d1f5546cb9ad8920523474a949`; revised 2026-11-09 at `00177f369a82907da96d7c02a6dcbad744ec103e` (Step 65 landed), branch `main`. Pre-existing untracked `.build-step/` is unrelated and must be preserved.

### What This Feature Does

The board gets its approved designs every time the ordinary command refreshes the core documents. The set stays at seven reports with a different membership: the existing Reimbursement Queue, Reimbursement Summary, Fundraising Summary and CFO P&L Summary; the redesigned Budget Snapshot; and the new Classroom Budgets and Treasurer Notes. Fundraising vs. Obligations is no longer a separate document; its obligations detail, scenarios and assumptions move into the Budget Snapshot. Six summaries export HTML/PDF/PNG triplets beside the existing queue HTML and copy text. No separate report-generation command or manual copy of a prototype is needed.

Classroom Budgets shows teacher names on the horizontal axis, dollars on the vertical axis, a paid/remaining stacked bar per classroom, a short list of larger reimbursed purchases, and a factual spending description. The Budget Snapshot shows the school year's position on one as-of date: five headline boxes, progress against the adopted budget, where money went and came from, four fundraising and spending scenarios, their assumptions, and complete paid and not-yet-paid lists. Treasurer Notes is a one-page meeting brief: the Budget Snapshot's headline figures, operator-authored questions for the board, month-end bank balances, reimbursement-queue status and a short factual summary.

### Accepted report presentation

**Budget Snapshot (operator-approved design draft v3, 2026-11-09).** Keep the existing masthead, period line and teal/gold language; print one "as of" date on every page. The summary targets one portrait Letter page and may flow to a second page; complete appendix pages follow. In order:

1. Five headline boxes:
   - **Bank accounts:** total net of the credit-card balance, with checking, time account (buffer) and the signed credit-card balance beneath. Omit savings while its balance is zero; show it when nonzero.
   - **Raised:** fundraising received through as-of, with the percentage of the adopted fundraising target. A ledger category outside the adopted budget counts as raised only when the private category roles declare it `fundraising`; it then appears under its own category name with a zero target. Cost-offsetting event income declared `other_income` is not raised.
   - **Spent:** posted spending attributed to the school year through as-of.
   - **Spending still ahead:** the remaining adopted plan.
   - **Projected year-end balance (Central Case):** calculation rule 10, shown with its checking and time-account split. The projected checking amount is red, asterisked and followed by the operator's note when it is below the private checking floor; the time-account amount is red only when the projection draws it down.
2. **Progress against the adopted budget**, directly under the boxes. The fundraising bar shows raised plus a lighter, hatched segment for the budgeted break-even income of confirmed upcoming events, with a legend, against the adopted target. The spending bar shows spent against the annual plan. No time-elapsed markers or labels.
3. **Where money went** (largest spending categories plus an exact Other) and **Where money came from** (largest fundraising categories plus an exact Other), from the same ledger figures as the boxes.
4. **Fundraising and spending scenarios**, in this row order: No more fundraising; Minimum self-funding; Central Case (Last year's pace N%), highlighted; Full fundraising target. Columns: full-year raised, cuts needed, reserves needed / share, coverage at the same gap. Cuts assume no reserve draw.
5. **Scenario assumptions:** a Central Case paragraph (last year's achievement rate applied to this year's target, the implied gap, the projected year-end balance and its split); a specialist-contracts sentence (paid at the start of the year as this year's expense, next year's contracts outside this year's projection, the checking-floor note); and a Minimum self-funding paragraph (classroom utilization, break-even confirmed events, prior-year dollar benchmark and floor).
6. **Appendix pages:** every nonzero paid category, then every nonzero not-yet-paid category, in descending amount order with deterministic category tie-breaks. Each appendix total reconciles exactly to Spent or Spending still ahead before rounding. Preserve signed refunds and reversals; never print an aggregate Other row instead of its detail. Long lists paginate rather than clip.

Removed by operator decision: the former Unknown-actuals and adjusted-bank-net boxes, Largest budget lines, Data follow-ups, the Where things stand narrative, the audit-count block, page-1 obligations tables, the Fundraising versus the plan bar, the reserves strip, and formula, caption and fine-print lines. A compact footer keeps sources, as-of, run ID and input-set hash; counts, findings and evidence remain in the run records. Step 68 records this amendment in the Main Report Set design contract.

Displayed whole-dollar parts must add exactly to their displayed totals: use largest-remainder rounding, keep each correctly rounded total, and display a figure shared by two places identically in both. Machine records keep cents.

**Treasurer Notes (operator draft, 2026-11-09).** One portrait Letter page:

- Headline boxes for bank accounts, raised, spent and spending still ahead, taken from the same facts and displayed values as the Budget Snapshot; never recomputed on another basis.
- **Questions for the board:** numbered, operator-authored items from the private planning input. Item text may embed run figures only through declared placeholders resolved from facts, never typed-in numbers. An item may attach one reimbursement clarification group, listing that group's requester labels, request IDs and amounts from the staged review bundle. An unknown placeholder fails validation before publication. A group label that is absent from the run's staged bundle (its requests were resolved, or the APPROVED-LIST hold group has no held requests in this run) renders "No requests outstanding" under the question and adds a value-free entry in the run's existing `coverage_warnings` (manifest and CLI summary) naming the question ID, so a mistyped label stays visible without failing the run (D48). Question text is plain text, HTML-escaped on render, with no markup or links; a placeholder substitutes only the display-formatted figure. With no items recorded, print an explicit "No questions recorded" line.
- **Bank accounts** table: the previous month-end and the as-of month-end balances per account with the change, from the captured balances binding.
- **Reimbursement queue** table: paid (with the latest payment date), held per clarification group, and approved-unpaid, from the staged review bundle; totals reconcile to the bundle summary.
- **Where things stand:** one deterministic paragraph built from the same facts.
- The same compact footer. Financial figures use the run's as-of date; queue status uses the staged bundle's evidence time; both dates are printed.

### Existing Context

- `np_finance/cli.py:_cmd_end_to_end_run` dispatches to `runner.run`; `runner._build_run` captures sources, refreshes/stages reimbursement evidence, builds facts, renders, validates and publishes. `runner._dry_run` is strictly no-write.
- Step 65 (`00177f3`) added the optional `[main_reports.board_planning]` input: a private version-1 planning JSON plus supplemental `academic_ledger`, `prior_year_budget` and `balances` bindings, captured as an optional `PlanningCapture` on `CaptureSet` (typed, value-free validation errors, type-strict stored reconstruction, private-location confinement, input-hash participation). `SOURCE_KINDS` and bank reconciliation are unchanged.
- `sources.py:_capture_budget` retains proposed/adopted rows only; historical actuals are not available just because historical targets are present. `budget_tracker` is captured as a control, not a verified itemized payment ledger.
- `facts.py:build_from(capture_set, ledger, bundle, config)` is the production calculation seam. `models.py:ReportFacts.to_dict` writes the audit facts. `render.py:write` consumes facts and the staged review bundle; it does not query Sheets. The staged bundle's clarification groups and summary come from `np_finance.reimbursement_report`.
- `render.py:SUMMARY_NAMES`, `REPORT_TITLES`, `OUTPUT_NAMES`, `_links` and `pointer_page` govern exports and navigation. The tuple unpacking beside `SUMMARY_NAMES` needs updating. `runner.COMPATIBILITY_FILES` derives from `OUTPUT_NAMES`; `_check_set` verifies the set before the atomic pointer switch. The Budget Snapshot keeps its existing output names, so links and compatibility copies keep their paths.
- Existing templates under `np_finance/reports/templates/main_reports/` share `base.html.j2`, `style.css.j2` and `macros.html.j2`. Chromium exports are offline and already tested for page count. Keep the approved teal/gold visual language, masthead and Letter layout.
- The private prototypes (the classroom draft, the Budget Snapshot design drafts and the Treasurer Notes draft) supply visual reference only. Their roster, names, dates, amounts, equal allowances, amount-only check attribution, name parsing, operator overrides and free-text matching are not production inputs. Private artifact locations stay in private handoff state, not this public plan. A builder without those artifacts can implement from this specification and the existing template family.
- A concurrent, separately planned phase (QUEUE-ARCHIVE) changes reimbursement queue rendering and evidence handling. Treasurer Notes consumes the loaded bundle read-only and must not change reimbursement rendering.

### Scope

**In:** typed captured planning inputs; teacher/payment attribution; school-year spending and fundraising facts on one as-of date; four scenarios; projected year-end balance with its account split; explicit reserve basis; the redesigned Budget Snapshot template; Classroom Budgets and Treasurer Notes templates; operator-authored board questions with figure placeholders; shared exports/index/manifest/compatibility copies; privacy, failure and missing-data behavior; source detail records; focused tests; one real private acceptance cycle.

**Out:** a separate Fundraising vs. Obligations document, a new dashboard, hosted app, scheduler, email delivery, payments, approvals, CFO workbook writes, bank-PDF ingestion, automated roster inference, a comprehensive accounts-payable ledger, predictive fundraising models, a cash-flow forecast, generated question text, generic refactors, reimbursement-queue changes, or closing unrelated financial discrepancies. This is a one-shot CLI feature, not an always-on service; no elapsed soak is required.

### Impact Analysis

Search boundary: tracked Python under `np_finance/` and `tests/`, shared report templates, `config.example.toml`, `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml`, `pyproject.toml` and the report guides. Private outputs, archived plans and paused worktrees were excluded from consumer enumeration.

| File or interface | Change | Reason | Verified evidence |
|---|---|---|---|
| `np_finance/config.py`, `config.example.toml` | Optional typed board-planning configuration (Step 65, done) | Explicit private source and roster bindings | `MainReports`, `BoardPlanning`, `_load_board_planning` |
| `main_reports/sources.py`, `models.py` | Planning schema version 2: optional `budget_snapshot` and `treasurer_notes` blocks; version 1 stays valid | Checking floor and board questions must be captured, hashed and validated like other planning inputs | `PLANNING_SCHEMA_VERSION`, `_validate_planning_input`, `PlanningCapture`, `stored_planning` |
| `main_reports/planning.py` (new) | Pure parsing, attribution, scenario, projection and placeholder calculations | Keep new financial semantics separate from presentation | Invoked by existing `facts.build_from` |
| `main_reports/facts.py`, `models.py` | Add classroom, budget-snapshot (obligations, scenarios, projection, progress) and treasurer-notes facts with quality/provenance | Every displayed number must be auditable | `ReportFacts`, `build_from`, `to_dict` |
| `main_reports/runner.py` | Carry records; validate complete exports | Prevent mixed snapshots and partially published sets | `_input_components`, `_write_records`, `_check_set`, `_build_run`, `_dry_run`, `COMPATIBILITY_FILES` |
| `main_reports/render.py`; `budget-snapshot.html.j2` (rewritten), `classroom-budgets.html.j2` and `treasurer-notes.html.j2` (new) | Register two new summaries; replace the Budget Snapshot layout | Normal index, pointer and compatibility paths | `SUMMARY_NAMES`, `OUTPUT_NAMES`, `write`, `_write_set`, `_links`, `pointer_page` |
| `main_reports/export.py` | Reuse exporter; allow a one-or-two-page Budget Snapshot summary plus appendices in layout validation | No second PDF engine | `ExportJob`, `export_documents`, `verify_outputs` |
| `np_finance/reimbursement_report.py` | Read-only consumer (bundle summary, clarification groups, recently paid) | Treasurer Notes queue table and question groups | `load_bundle` exists on `main`; `ReimbursementReport.clarification_groups` (`ClarificationGroup.action/.tickets/.total`), `recently_paid` and `recently_paid_start` landed on `main` in `973f7b5` (QUEUE-ARCHIVE); re-run the consumer search before Step 74 starts |
| `tests/conftest.py`, `test_config.py`, `test_main_report_sources.py`, `test_main_report_facts.py`, `test_main_report_render.py`, `test_main_report_runner.py`; new `test_main_report_planning.py` | Fictional inputs and seam/regression cases | Constructor, artifact count, source/hash and publication consumers | Repository search for `MainReports(`, `CaptureSet(`, `ReportFacts(`, `build_from(`, `SUMMARY_NAMES`, `OUTPUT_NAMES` |
| `main_reports/reconcile.py` | Verify unchanged transaction routing; change only if the capture interface requires it | The supplemental annual ledger must never be counted as another bank feed | Consumer of transaction/control kinds and captures |
| `np_finance/cli.py`, README, CLAUDE, `docs/main-report-set.md`, `docs/plan-reference/main-report-design.md`, CI | Update report membership, counts, Budget Snapshot contract amendment and browser coverage expectations | Discoverability and installed-package evidence | CLI parser/help, guides, `.github/workflows/ci.yml` |

All `main_reports/` paths above are relative to `np_finance/`. Shared consumers found: config validation; sources capture/storage/load; reconcile; facts; render; runner; the reimbursement report loader; the listed test modules and `tests/conftest.py`. Re-run this search before changing a shared interface; preserve unrelated constructor callers and serialized fields.

### New Components and Input Contract

Introduce `np_finance/main_reports/planning.py`, templates `classroom-budgets.html.j2` and `treasurer-notes.html.j2`, a rewritten `budget-snapshot.html.j2`, and `tests/test_main_report_planning.py`. Use existing Decimal, dataclass, JSON, Jinja and Chromium facilities; no new service or dependency. No `fundraising-vs-obligations` template or output exists.

Implemented in Step 65: optional `[main_reports.board_planning]` with `input_file` pointing to a private versioned JSON document, resolved against the config directory and confined to a private location. It contains the roster, explicit mappings/policies and supplemental source bindings, not cached live amounts. All names, real identities and bindings remain private. The version-1 schema has these fields:

- `schema_version: 1`; `fiscal_year: int` (ending-year label); `roster_complete: bool`; `roster_as_of: YYYY-MM-DD`; `roster_evidence: nonempty string`.
- `classes[]`: `class_id` (unique stable private lowercase slug, e.g. `class-a`), `teacher_label`, `student_count` (nonnegative integer or null), `per_student_amount` (nonnegative decimal string or null), `effective_start`, `effective_end` (inclusive ISO dates), `eligible` (boolean). Allocation = count times rate; do not distribute the adopted total automatically. A teacher can have multiple class IDs; render class-qualified labels. No student identities are collected.
- `payee_aliases[]`: exact `source_payee` to `class_id`. Explicit mapping only; spelling normalization must not merge distinct people. `payment_allocations[]`: `source_record_key`, `source_revision_hash`, `class_id`, `amount` and `evidence`; multiple allocations must sum to the linked payment amount. These are reporting assignments, not payment-authority records.
- `category_roles[]`: `source_category`, `role` (`fundraising`, `other_income`, `expense`, `transfer`), `budget_category`; `classroom_categories[]` identifies eligible expense categories. A mapping is explicit and does not replace the existing category crosswalk or journal. Missing roles are unresolved, not income by sign alone.
- `bindings[]`: `role` (`academic_ledger`, `prior_year_budget`, `balances`), `workbook` (`cfo` or `own`, resolved only through existing configured workbook IDs), `tab`, `header_signature`, `columns` (logical field to exact label), `coverage_start`, `coverage_end`, `coverage_evidence`. At most one binding per role; no new credentials. `prior_fiscal_year` must equal the selected year minus one.
- `reserve_basis`: `kind: source_account_balance`, `binding_role: balances`, `component: cd`, and `evidence`. The reserve amount and date come from the latest captured CD-column row no later than as-of; do not store a manually estimated amount. Exclude checking and savings; do not subtract the credit-card balance from the CD. Missing, unreadable, future-only or stale CD data makes reserve columns unavailable; no fallback to total cash or an old estimate.
- `specialist_contract_categories[]`: exact current budget-category keys identifying specialist contract costs. They label the checking-floor note and the assumptions sentence; they no longer drive a remaining-obligation subtotal.
- `central_case`: the policy for the scenario now named **Minimum self-funding** (the key name is kept for version-1 compatibility): `fundraising_basis: prior_actual_dollars`; `classroom_budget_categories[]` and `prior_classroom_categories[]`; `future_events[]` with unique stable `event_id` slug, `label`, `income_categories[]`, `expense_categories[]`, `event_date` (ISO date after report as-of), `confirmed: bool`, and nonempty `evidence`. Each income/expense category belongs to at most one event, and its classroom categories cannot overlap event or specialist-contract categories. A past/unconfirmed date makes the Minimum self-funding forecast and the progress bar's projected segment partial/unavailable; zero transactions are not proof of a future date. An absent policy makes only those two items unavailable. Policy/schema corruption or duplicate/conflicting category bindings fails validation. Current targets come from the captured adopted budget, joined through `budget_category`; missing joins are unknown, not zero.
- `period_allocations[]`: exact `source_record_key`, `source_revision_hash`, `fiscal_year`, and `evidence` for an operator-verified attribution overriding an incorrect academic-year source label. Preserve both original and corrected assignments in facts; reject duplicate/conflicting assignments and conflicts with recorded journal adjustments. This changes report attribution only, not source data or payment status.

Schema version 2 (Steps 67 and 74) is additive; version-1 documents stay valid, and any other version is rejected. It adds two optional blocks:

- `budget_snapshot`: `checking_floor` with `amount` (positive decimal string) and `note` (nonempty plain text, at most one sentence). Absent means no checking warning.
- `treasurer_notes`: `questions[]` with `question_id` (unique stable lowercase slug following the `class_id` convention, e.g. `q-budget-gap`; used to cite a question in `coverage_warnings` and to key the serialized treasurer-notes facts; questions render in list order), `title`, optional `audience`, `text`, and optional `reimbursement_group` (the exact clarification-group label from the staged bundle). `text` may contain `{figure_key}` placeholders drawn from a closed list defined once in `planning.py`. The initial keys are `raised`, `fundraising_target`, `spent`, `spending_still_ahead`, `annual_plan`, `bank_total`, `time_account`, `projected_year_end_balance`, `projected_checking`, `central_case_cuts`, `central_case_rate`, `minimum_self_funding_cuts`, `no_more_fundraising_cuts`, `classroom_allocation_total`, `classroom_budget`, `classroom_allocation_difference` and `upcoming_event_income`; adding a key is a code change with a test. Unknown keys, unbalanced braces, duplicate IDs and an empty or non-plain-text `reimbursement_group` label fail validation with value-free messages; a well-formed label absent from the staged bundle renders "No requests outstanding" with a `coverage_warnings` entry (D48).

Supplemental source rows are captured verbatim with existing source row/ref/hash conventions:

| Role | Logical fields | Rules |
|---|---|---|
| Academic ledger | payment date, description, signed amount, category, fiscal year; optional explicit payment reference and payee | Each expense is negative; preserve academic-year allocation even if paid before the school-year start. Exclude transactions after `--as-of`. Require a declared academic-year mapping; do not infer it from payment date. |
| Prior-year budget | fiscal year (binding constant allowed), category, type, proposed, actual | Read both target and actual, never sum subtotal rows with detail. Distinguish blank/unknown from zero. Classify fundraising consistently across years; exclude interest from both sides of the historical fundraising ratio. |
| Balances | date, checking, savings, CDs, credit-card liability, total | Latest complete date no later than `--as-of`; reconcile components to total. Declare liability sign in column mapping. Flag mismatched/stale/incomplete snapshots. The previous month-end row feeds the Treasurer Notes table. |

Identifiers: existing run IDs, input hashes and reimbursement item/review keys retain their current generators and formats. New academic rows use the existing `v1:<alias>:<sha256>:<occurrence>` record-key convention, with a distinct planning alias and a deterministic occurrence index. Do not deduplicate distinct identical-looking source rows by amount. Rows lacking exact payment references stay unassigned until an evidence-backed private allocation identifies the source key/revision. No new public person identifier is introduced.

`ReportFacts` gets optional typed `classroom`, `budget_snapshot` and `treasurer_notes` sections with their own versioned serialized payloads. Each carries `status` (`complete`, `partial`, `unavailable`), source refs, coverage/as-of, amounts as decimal strings, and findings. Class rows contain class ID/label, enrollment, rate, allocation, paid, signed remainder and evidence. Budget-snapshot facts contain bank components and total, raised (with its category breakdown and any unbudgeted fundraising categories), other income, spent, the paid and remaining category rows, the annual plan, the four scenarios (annual spending, projected full-year fundraising, cuts, surplus, required reserve funding, usable reserve draw, reserves left, unfunded remainder, required-funding percentage, repeat-gap years, CD balance and basis date, plus the Minimum self-funding inputs), the progress segments, the projection with its split and warning states, and the displayed-value tie adjustments. Treasurer-notes facts contain the resolved questions with their placeholder values and group references, the month-end balance rows and changes, and the queue table with its evidence time. Preserve all existing facts fields and old-reader behavior; test explicit old/new shapes rather than changing every stored schema version globally.

### Design Decisions

| Choice | Decision | Provenance | Rationale / alternatives |
|---|---|---|---|
| Report membership | Seven reports: four existing, the redesigned Budget Snapshot, Classroom Budgets and Treasurer Notes; no separate Fundraising vs. Obligations | operator (2026-11-09) | One combined financial brief plus a meeting brief |
| Budget Snapshot design | Draft v3 layout, sections and removals above | operator (2026-11-09) | Approved after three review rounds |
| One as-of date | Every financial figure uses the run's `--as-of` cut; balances from the latest row on or before it | operator (2026-11-09) | No mixed-date figures in one document |
| Budget Snapshot basis | Academic-ledger basis, replacing the former bank-basis Budget Snapshot | agent default (from the operator's one-date decision) | Matches obligations and scenarios; the Fundraising Summary and CFO P&L keep their bank basis with a bridge in the run records |
| Bank accounts box | Checking, time account and credit card, total net of card; savings omitted while zero | operator (2026-11-09) | Card balance is a real liability; zero savings adds noise |
| Unbudgeted fundraising | Counts as raised under its own category when roles declare it fundraising | operator (2026-11-09) | Matching gifts outside the budget are still fundraising |
| Scenario names | Old central case renamed Minimum self-funding; last year's pace becomes the highlighted Central Case | operator (2026-11-09) | The board plans on last year's achieved pace |
| Projected year-end balance | Calculation rule 10; next year's contracts are outside the projection | operator (2026-11-09) | Contracts are paid after the school year ends |
| Checking floor | Private configured amount and note; projected checking below it renders red with the note | operator (2026-11-09) | Warns that next year's contracts would need a time-account draw |
| Specialist contracts | A start-of-year payment assigned to the school year is that year's expense and paid; no second current-year obligation | operator (2026-11-09) | Supersedes the 2026-11-04 rule; source ledger and budget tracker already agree |
| Board questions | Operator-authored private items with figure placeholders and optional reimbursement-group attachment | agent default | Questions are judgment; figures must stay current and verifiable |
| Absent reimbursement group | "No requests outstanding" under the question plus a value-free run warning naming the question ID; never fails the run | operator-approved recommendation (2026-11-11), D48 | Groups empty in normal operation (requests resolve; the APPROVED-LIST hold group appears only when needed); failing all seven reports over a board note is disproportionate. Rejected: fail closed on any absent label |
| Treasurer Notes dates | Financial figures at as-of; queue status at the staged bundle's evidence time; both printed | agent default | A meeting brief needs current queue status beside month-end finances |
| Missing planning input | The Budget Snapshot renders its ledger-based figures as unavailable; no fallback to the former bank-basis design | agent default | One design and one basis; bank figures remain on the Fundraising Summary and CFO P&L |
| Footer identity | Compact footer keeps sources, as-of, run ID and input-set hash; audit counts move to run records | agent default | Operator removed the audit block; run identity remains required |
| Displayed rounding | Largest-remainder tie of displayed parts to displayed totals | agent default (operator did not object) | Board readers check sums |
| Classroom allocations | Actual enrollment times rate in production; equal distribution is design-only | operator | Actual roster is still to be supplied; no fabricated production budget |
| Scenario policy | No reserve draw in cuts; additionally show draw dollars, share and repeat-gap years | operator | Reserve use is an alternative, never added to the cuts |
| Input maintenance | One private versioned planning JSON plus live bound finance tabs | agent default | Smallest explicit input surface; no new spreadsheet editor or automatic name guessing |
| Classroom paid basis | Posted payments allocated to the school year, reconciled to paid review evidence | agent default | Issued-but-unposted reimbursements appear separately and are not counted twice |
| Remaining obligations | Remaining adopted plan, not a claim of invoices legally owed | agent default | Label honestly |
| Reserve denominator | Captured time-account (CD) balance; never total cash or an estimate | operator | Operating money cannot be counted again as reserve capacity |
| Failure behavior | Invalid configured schemas, ambiguous duplicates, unknown placeholders and failed financial invariants halt publication; an absent reimbursement group is a coverage warning (D48) | agent default | Missing optional data is different from corrupt supplied data |

Calculation and display contract:

1. Let `B_i` be a readable adopted expense target and `P_i` the school-year attributed posted spending through as-of. Remaining `R_i = max(B_i - P_i, 0)`; annual spending estimate `E = sum(P_i + R_i)`. An explicitly unbudgeted expense has target zero and remains in `E`; an unmapped target is unknown, not zero. A start-of-year specialist-contract payment that the source ledger assigns to this school year is part of `P_i` for that line, so its remaining is zero and `E` counts it once. Show already-incurred overruns and explain any difference between `E` and the adopted budget. Refunds/reversals retain signed net effects and provenance; do not silently clamp anomalous negative net spending. Tracker totals are a reconciliation control, not added to the academic ledger. Never add this ledger to the bank P&L.
2. `F` = fundraising received on the academic-ledger basis through as-of, including categories that the roles declare fundraising outside the adopted budget; `T` = adopted fundraising target; `O` = other recorded income. Exclude transfers and do not add processor gross to posted receipts. Historical ratio `r = prior_actual / prior_target`, for the same declared fundraising scope. No more fundraising `A=F`; **Central Case (last year's pace)** `A=max(F,T*r)`; Full fundraising target `A=max(F,T)`. Cuts `max(E-A-O,0)`; surplus `max(A+O-E,0)`. Retain future fundraising costs until explicitly changed. A missing or nonpositive prior target makes the Central Case unavailable; never substitute 100%. Do not clamp ratios above 100%.
   **Minimum self-funding** (the former central case): use prior-year classroom actual / adopted classroom budget as utilization, with projected classroom spending floored at already-paid spending. Other expenses retain the full modeled plan. Treat an explicitly captured, confirmed set of future fundraising events as break-even: their full-year receipts equal full-year costs, including prepaid costs, with received/paid amounts retained and no impossible negative future receipts or costs. Use prior-year total fundraising dollars as the annual benchmark. Future event receipts count inside annual fundraising, not on top. For each event, full-year expense `E_j=paid_j+max(adopted_j-paid_j,0)` and required future receipts `N_j=E_j-received_j`. If observed receipts already exceed `E_j`, mark the case unavailable with a finding rather than inventing refunds. Let `N=sum(N_j)` for the confirmed future events: annual fundraising `A_m=max(prior_actual,F+N)`; annual expense `E_m=E-original_classroom_estimate+max(classroom_paid,current_classroom_budget*prior_classroom_actual/prior_classroom_budget)`. Round projected money to cents, then apply the same gap/reserve formulas with `E_m,A_m`. Missing prior classroom data or unverified event scope makes this case partial/unavailable without affecting the other cases. This utilization assumption never changes teacher entitlements or the Classroom Budgets chart. The progress bar's projected segment is `N`.
3. The Budget Snapshot uses the academic-ledger basis; the Fundraising Summary and CFO P&L keep their bank basis. The run records carry a source-backed bridge between the two bases (timing/prepayments, classification, gross/fees, exclusions and unresolved residual). No silent disagreement between core documents is acceptable; Treasurer Notes uses the Budget Snapshot's figures, never a third basis.
4. Required reserve funding equals the no-draw annual gap; usable draw = min(gap, available reserves), with the unfunded remainder shown separately. Percent needed = gap / captured CD balance; repeated-gap coverage = CD balance / gap. Zero gap means no draw needed. Missing/invalid reserves yield unavailable comparisons; a valid zero reserve means no coverage and the full gap unfunded, with percentage undefined. A gap larger than reserves must say insufficient, never claim the entire gap can be drawn. These are annual-gap comparisons, not months until cash runs out.
5. Classroom posted payments require exact source identifiers/verified mappings, not matching check amount alone. Reuse the project's record key and revision-hash identities; do not mint display-name payment IDs. Ambiguous/unassigned payments remain a visible total with refs. Assigned plus unassigned equals source classroom spending. Shared purchases use explicit amount splits. Roster coverage, specialists, unknown dates, carryovers, duplicates and issued-but-unposted items stay explicit. Larger purchases come from paid, dated itemized review evidence; aggregate paper totals are not invented individual products.
6. Signed classroom remainder = enrollment times rate minus posted payments. A negative remainder gets an over-budget marker; the visual does not draw a negative remaining stack or hide the overrun. Zero observed payments are distinct from absent coverage. Enrollment totals/rates need not sum to the adopted classroom envelope; show any difference rather than silently scaling them.
7. Keep a bounded list of large items/categories plus an exact other subtotal, with complete rows in private audit records. Narrative text (the classroom description, the Budget Snapshot assumptions, the Treasurer Notes summary) is deterministic from facts; no external model or unsupported conclusions. Long names, larger rosters and long questions must fit legibly without omitting rows; automated layout failure prevents publication rather than clipping data.
8. Each new or redesigned page carries run ID, input hash, as-of and data basis like existing pages. Machine records retain cents; display rounding follows rule 11. No real names, source IDs, amounts, thresholds, screenshots or private prototype paths in committed fixtures/docs.
9. Materially incomplete current income/spending coverage yields partial observed subtotals and unavailable definitive cuts and projection, not a precise forecast based on missing rows. Missing historical data affects the Central Case and Minimum self-funding only; missing reserves affects reserve columns only. A balances row dated before the calendar month preceding as-of is stale: the bank box, projection and reserve comparisons become unavailable. A current tracker snapshot is not a historical as-of control.
10. Projected year-end balance (Central Case) `Y = bank_total + (A_central - F) - sum(R_i)`, where `bank_total` = checking + savings + time account + the signed credit-card balance from the as-of balances row. It covers this school year's plan only; next year's specialist contracts are outside it. Split: shortfalls drain checking first, then the time account. If `Y` is at least the time-account balance, projected checking = `Y - time account` and the time account is unchanged; otherwise projected checking is zero and the time account = `Y`, rendered red as drawn down. A negative `Y` is shown as an overdraw finding, never clamped. When a checking floor is configured and projected checking is below it, render projected checking red with an asterisk and the configured note. This is a year-end position on the stated assumptions, not a cash-flow forecast.
11. Displayed whole-dollar parts add exactly to their displayed totals by largest-remainder rounding within each group (bank box lines, projection split, chart rows versus boxes, appendix rows versus totals). The correctly rounded total is kept; a figure shown in two places displays identically. The cents values in facts never change.

### Build Steps

### Step 65: Capture the planning inputs through the normal command
- **Status:** DONE (2026-11-09)
- **Problem:** The ordinary run cannot capture the roster and school-year planning sources needed to substantiate either new page.
- **Type:** code
- **Issue:** #109
- **Flags:** --reviewers deep
- **Files:** `np_finance/config.py`, `config.example.toml`, `np_finance/main_reports/models.py`, `sources.py`, `runner.py`, `tests/test_config.py`, `tests/test_main_report_sources.py`, `tests/test_main_report_runner.py`, `tests/conftest.py`
- **Produces:** The optional planning configuration/capture contract above, version-compatible stored snapshots and input-set hashing.
- **Done when:** `end-to-end-run --dry-run` validates fictional planning inputs without creating any files; a real-component normal CLI fixture run retains a hashed planning capture; changing roster/alias/policy/one source row changes the input hash; capture mutation is detected; an old config/capture still runs and retains old-source semantics; invalid configured inputs fail before pointer publication. Supplemental ledger rows never enter bank P&L reconciliation as a second bank feed.
- **Depends on:** 62, 64 (both DONE)

### Step 66: Refresh the classroom one-pager with the core report set
- **Status:** PENDING
- **Problem:** The approved classroom design is a private one-off rather than a reproducible core report.
- **Type:** code
- **Issue:** #110
- **Flags:** --reviewers deep
- **Files:** `np_finance/main_reports/planning.py` (new), `models.py`, `facts.py`, `render.py`, `runner.py`; `np_finance/reports/templates/main_reports/classroom-budgets.html.j2` (new), shared base/style/macros as needed; `tests/test_main_report_planning.py` (new), `test_main_report_facts.py`, `test_main_report_render.py`, `test_main_report_runner.py`
- **Produces:** Classroom HTML/PDF/PNG from captured actual allocations and attributed payments, private complete detail records, and all normal publication links/copies.
- **Done when:** A normal CLI fixture run publishes the classroom triplet and the existing reports with one run/input identity; source payments reconcile to assigned plus unassigned; verified shared/check mappings and issued-but-unposted cases do not duplicate spend; missing roster yields an explicit unavailable allocation rather than the draft's equal distribution; an over-budget case shows a signed negative remainder; large/long-label fixtures remain a single readable Letter page without hidden teacher rows. The failed-export case leaves the previous pointer unchanged.
- **Depends on:** 65

### Step 67: Absorb obligations and scenarios into the Budget Snapshot
- **Status:** PENDING
- **Problem:** The operator-approved Budget Snapshot redesign (five headline boxes, scenarios, projected year-end balance and complete obligation lists on one as-of date) exists only as a private design draft, while the published Budget Snapshot still shows the superseded bank-basis layout.
- **Type:** code
- **Issue:** #111
- **Flags:** --reviewers deep
- **Files:** `np_finance/main_reports/planning.py`, `models.py`, `facts.py`, `render.py`, `runner.py`, `sources.py` (planning schema version 2 `budget_snapshot` block), `export.py` (only if layout validation needs the one-or-two-page summary); `np_finance/reports/templates/main_reports/budget-snapshot.html.j2` (rewritten), shared style/macros as needed; `config.example.toml`; `tests/test_main_report_planning.py`, `test_main_report_sources.py`, `test_main_report_facts.py`, `test_main_report_render.py`, `test_main_report_runner.py`, `tests/conftest.py`
- **Produces:** The redesigned Budget Snapshot triplet (summary plus complete paid and not-yet-paid appendices), budget-snapshot audit facts and the basis-bridge records; no Fundraising vs. Obligations output.
- **Done when:** A production CLI fixture run publishes the redesigned Budget Snapshot with the other reports under one run/input identity, every figure on the as-of cut (ledger rows after as-of excluded; balances from the latest row on or before as-of); the five boxes, progress section, money-in/out charts, scenario table and assumptions match the accepted presentation and the removed sections are absent; paid plus remaining equals the annual plan; a source-assigned start-of-year specialist payment counts once as paid with no remaining obligation and no change to the annual plan; the four scenarios recompute independently from serialized facts with the new names and the Central Case highlighted; the projection follows rule 10 including both split branches, a negative-projection finding, the checking-floor warning on and off, and an absent floor; a declared unbudgeted fundraising category counts in Raised as its own category while declared other income does not; the projected-events segment equals the confirmed events' `N` and is unavailable for unconfirmed or past events; displayed parts tie to displayed totals; appendices list every nonzero category and reconcile; missing planning input, stale or missing balances and insufficient reserves render explicitly; version-1 planning documents still validate; no processor, transfer or alternate-ledger double counting occurs; the summary fits within two Letter pages and the appendices paginate without clipping.
- **Depends on:** 66

<!-- autofix-applied: 2026-11-11 -->
### Step 74: Publish Treasurer Notes with the core report set
- **Status:** PENDING
- **Problem:** The treasurer's board-meeting notes are assembled by hand from several private files for each meeting, so their figures can drift from the published reports.
- **Type:** code
- **Issue:** #125
- **Flags:** --reviewers deep
- **Files:** `np_finance/main_reports/planning.py`, `models.py`, `facts.py`, `render.py`, `runner.py`, `sources.py` (planning schema version 2 `treasurer_notes` block); `np_finance/reports/templates/main_reports/treasurer-notes.html.j2` (new); `config.example.toml`; `tests/test_main_report_planning.py`, `test_main_report_sources.py`, `test_main_report_facts.py`, `test_main_report_render.py`, `test_main_report_runner.py`, `tests/conftest.py`
- **Produces:** The Treasurer Notes triplet in every run, placeholder and group validation, the month-end balance table and the reimbursement-queue table, with treasurer-notes audit facts.
- **Done when:** A normal CLI fixture run publishes Treasurer Notes with the other reports under one run/input identity; its headline figures equal the Budget Snapshot's displayed figures exactly; questions render in order with placeholders resolved from facts, and an unknown placeholder or malformed text fails before pointer publication with a value-free message; a question whose reimbursement group is absent from the staged bundle renders "No requests outstanding", the run still publishes, and the run carries a value-free entry in the run's existing `coverage_warnings` (manifest and CLI summary) naming the question ID (no amounts or names); a question attached to a clarification group lists exactly that group's requests and total from the staged bundle; queue-table totals reconcile to the bundle summary; month-end balance changes equal the difference of the two captured rows, and a missing previous row renders unavailable; absent questions render "No questions recorded"; the page is one Letter page without clipping, and an overlong question fails layout validation rather than clipping; the financial as-of and queue evidence time are both printed; reimbursement rendering is unchanged; fixtures are fictional only.
- **Depends on:** 67; and the QUEUE-ARCHIVE `np_finance/reimbursement_report.py` interfaces (clarification groups and recently paid), satisfied on `main` from `973f7b5` (cross-phase prerequisite, not a CORE-BRIEFS step)

### Step 68: Verify the seven-report refresh and document operation
- **Status:** PENDING
- **Problem:** The changed publication needs evidence that the installed command refreshes all seven outputs together without regressing the existing ones.
- **Type:** code
- **Issue:** #112
- **Flags:** --reviewers deep
- **Files:** `tests/test_main_report_runner.py`, `test_main_report_render.py`, `test_main_report_sources.py`, `test_main_report_planning.py`, `tests/conftest.py`, `.github/workflows/ci.yml`, `np_finance/cli.py`, `README.md`, `CLAUDE.md`, `docs/main-report-set.md`, `docs/plan-reference/main-report-design.md`; bounded production fixes in `np_finance/main_reports/`
- **Produces:** Installed-wheel/template smoke, production-caller tests, actionable no-data/error pages, the updated seven-report guide, the Budget Snapshot design-contract amendment, and a live-acceptance checklist.
- **Done when:** The focused commands below pass; a real-component CLI/Chromium smoke completes under the existing bounded runner test (no mocked parser/facts/render/export/publication) and publishes exactly the seven reports (Reimbursement Queue, Reimbursement Summary, Budget Snapshot, Fundraising Summary, CFO P&L Summary, Classroom Budgets, Treasurer Notes); old and new capture/facts wire shapes and planning schema versions 1 and 2 are asserted; repeat runs preserve semantic totals and immutable prior outputs; dry-run writes nothing; injected capture/export/validation failures keep the old complete set; post-pointer alias-copy failure retains the new pointer and reports the existing partial-publication state. The Fundraising Summary, CFO P&L and reimbursement outputs keep their existing basis and receipt behavior. The built wheel contains the new and rewritten templates and no Fundraising vs. Obligations template. The guide and design contract describe the seven reports, the as-of rule and the Budget Snapshot footer amendment. Changed suites and exclusions are recorded explicitly.
- **Depends on:** 74

### Step 69: Accept the three core documents on actual private inputs
- **Status:** PENDING
- **Problem:** Correct fixtures do not establish actual roster/payment attribution, the board-meeting content, or the board's financial acceptance.
- **Type:** operator
- **Issue:** #113
- **Files:** Private roster/mapping/policy/question inputs, source evidence, generated run records, and the Step 68 acceptance checklist; no public source changes
- **Produces:** Private live-run observations and explicit acceptance or a bounded discrepancy list.
- **Done when:** The operator supplies/verifies actual roster counts/rates, mappings, the checking floor and board questions; observes one `end-to-end-run --dry-run` followed by one ordinary `end-to-end-run` at the selected month-end as-of date against real Sheets; opens the Budget Snapshot, Classroom Budgets and Treasurer Notes PDFs from the current index; verifies the Budget Snapshot boxes, scenarios, projection split and appendices against the approved design draft and source evidence, the Treasurer Notes figures against the Budget Snapshot and its queue status against the review bundle, and class allocations/payment totals against the roster; confirms the accepted layouts. Record unresolved issues without accepting fabricated allocations, calling cash unrestricted reserves, or marking CFO Step 63 complete by inference.
- **Depends on:** 68; actual roster, policy and source/evidence availability (data prerequisite, not an architectural decision)

### Risks and Open Questions

| Item | Consequence | Mitigation / owner | Blocking state |
|---|---|---|---|
| Actual enrollment/rates are not yet supplied | Classroom allocations cannot be financially final | Operator supplies source data in Step 69; code must support unavailable allocations | Blocks final live acceptance, not implementation |
| Ambiguous payees, checks and shared purchases | Wrong teacher budget usage | Exact IDs, revisions and private splits; visible unassigned total | Blocks affected attribution only; no invented match |
| Budget Snapshot (ledger basis) differs from the bank-basis Fundraising Summary and CFO P&L | Conflicting-looking totals across documents | Single as-of cut, prepayment treatment and an explicit basis bridge in the run records | A material unexplained residual blocks financial acceptance |
| Current cash/CD balance includes operating funds | Reserve coverage could be overstated | Captured CD component only; projection is labeled a year-end position, not reserve capacity | Missing/stale CD data blocks reserve columns only |
| Specialist payment period | A misassigned contract payment would distort Spent and the plan | Source academic ledger assignment, with operator-evidenced `period_allocations` only when the source is wrong | Resolved by operator decision 2026-11-09 for this year |
| Hand-written question text drifts from the facts | The meeting brief contradicts the reports | Figures only through placeholders; unknown placeholders fail validation; an absent group renders "No requests outstanding" with a coverage warning (D48) | Invalid input halts publication |
| Concurrent QUEUE-ARCHIVE and APPROVED-LIST (Steps 75-79) work on the reimbursement loader, queue, `README.md` and `docs/main-report-set.md` | Merge conflicts, a changed bundle interface, or overlapping guide edits; APPROVED-LIST adds a clarification group that can be absent in a run (handled by D48) | Treasurer Notes reads the loader read-only; Steps 74 and 68 start only from a `main` that contains `973f7b5` (landed 2026-11-09); re-run the consumer search before Step 74; QUEUE-ARCHIVE Step 72 depends on CORE-BRIEFS Step 68 | Prerequisite satisfied; interface drift is checked by the consumer search |
| Source/category/roster drift and later-date snapshots | Wrong historical or fiscal-year figures | As-of clipping, exact signatures, coverage, effective dates, consistency checks | Invalid configured input halts publication |
| Scope overlap with Step 63 and deferred F16/F17 | Accidental broader acceptance or duplicate machinery | Phase-scoped dispatch; reuse and separate acceptance boundaries | No blocker to this bounded phase |

Event scope/dates, actual enrollment, the checking floor and the board questions are private data prerequisites for Step 69, not unresolved implementation architecture. Agent defaults remain visible in the decision inventory and can be revised before build. The existing broader financial-acceptance issues are not silently waived.

### Testing Strategy and Quickstart

Use Python 3.12+ and the existing `uv` environment. Install with `uv sync --extra dev --extra web --extra slides --extra receipts --extra reports` (the full-suite gate imports all five extras; `uv sync` removes any extra it omits, and a missing `slides` extra shows up as dozens of baseline failures); install browser with `uv run playwright install chromium`. These are setup instructions for build execution, not commands run during planning. Configuration stays in ignored `config.toml`; the configured service-account file is read by the existing clients. Bind only already-authorized read-only workbook sources; do not print credentials or grant new permissions. Create the private input file from the documented schema, point `input_file` at it, and first run `uv run np-finance end-to-end-run --dry-run`. The ordinary run uses the same command without `--dry-run`; `--as-of YYYY-MM-DD` selects the cutoff (a month-end for board packages). Do not add `--fetch-*` or `--adjustments-file` to this feature's acceptance run.

There is no dev server, deployment command or stop daemon: the existing CLI is the development/production entry point and Ctrl+C retains its existing interrupt handling. Build with `uv build`. Test the installed wheel in a temporary environment with the reports extra and the existing fixture harness; do not install over unrelated environments. Explicitly check packaged resource presence and actual export through the normal runner.

Verified command surfaces (`pyproject.toml`, CLI parser and existing tests):

```powershell
uv run pytest tests/test_config.py tests/test_main_report_sources.py tests/test_main_report_facts.py tests/test_main_report_render.py tests/test_main_report_runner.py -q
uv run pytest tests/test_main_report_planning.py -q
uv run ruff check np_finance tests
uv run ruff format --check np_finance tests
uv run mypy --strict np_finance
uv run python scripts/check_no_identity.py
uv build
```

The planning test module is a new Step 66 output; that command becomes runnable after creation. Existing Chromium smoke: `tests/test_main_report_runner.py:test_chromium_end_to_end_run_publishes_real_exports_within_the_bound`. Exercise real parsing/facts/templates/Chromium/publication with fictional captured inputs; only the external network boundary is supplied by the fixture harness. Do not describe the fixture as a live finance run. No long observation period is applicable. Per-step DONE gates run the full suite except modules that cannot run on the build host, named explicitly (the six Firestore-emulator modules without emulator tooling; the two Treasurer Slides native-sandbox modules are deferred to the phase-end gate for duration).

Test calculations with Decimal cents and independent expected arithmetic, including unequal class sizes, zero enrollment, multiple classes per teacher, shared purchases, check revisions, missing data, ambiguous aliases, duplicate refs, refunds, start-of-year contract payments, target shortfalls, ratios above one, no-data reserve cases, both projection split branches, a negative projection, the checking floor on, off and absent, and largest-remainder ties. Assert exact per-document page counts (Classroom Budgets and Treasurer Notes one page; Budget Snapshot summary within two pages plus appendices), complete appendix category coverage and totals, visible table/SVG labels, non-overflow, no omitted classroom rows or questions, no external resource requests, accessible chart labels and fake-only fixture identities.

Regression acceptance: changing only the captured CD balance changes reserve percentages, usable draw, reserves left, unfunded remainder, coverage and the projection's time-account component, while leaving the annual plan and no-draw cuts unchanged. Changing only checking, savings or the credit-card balance changes the bank box and the projection but not the reserve calculations. Changing only the checking floor changes only the warning state. A start-of-year specialist payment assigned to the school year counts once as paid and leaves no remaining obligation without changing the annual plan. Never embed a prototype's captured amount or threshold as a constant.

Compatibility/backout: absent planning configuration yields Classroom Budgets, the Budget Snapshot and Treasurer Notes with explicit unavailable facts and keeps the other reports usable. Version-1 planning documents stay valid; new optional fields are versioned and old stored captures remain readable and immutable; no destructive migration or report-history rewrite. Capture/fact hashes include all policy, question and source inputs. Before publication, preserve the existing all-or-nothing pointer semantics; after the switch preserve the existing per-alias partial-copy reporting. On rollback, use the last known-good code/config and the retained prior complete run; do not edit historical records or silently point at a partial new run.

Planning handoff order for this revision only: `/plan-review --autofix docs/plans/master_plan.md`, `/plan-redline --plan docs/plans/master_plan.md`, `/plan-wrap --autofix docs/plans/master_plan.md`, then `/repo-sync --plan docs/plans/master_plan.md` scoped to CORE-BRIEFS (retitle #111 for Step 67, create the Step 74 issue, update #110, #112 and #113). After issue fields are populated, build Steps 66, 67, 74 and 68 in that order with `/build-phase --plan docs/plans/master_plan.md --phase CORE-BRIEFS --steps 66,67,74,68`; Step 69 remains attended.

## Phase QUEUE-ARCHIVE: Working queue and paid archives by submission month

**Objective:** The ordinary `uv run np-finance end-to-end-run` completes with receipt preparation enabled again: open requests keep their receipts in a small working queue, and every paid request stays findable, with its receipts, on an archive page for the month it was submitted.
**Planning state:** REVIEW-READY for this phase only. No implementation or acceptance is claimed.
**Status:** Steps 70-73 PENDING. Numeric IDs 70-73 are newly reserved; no existing step is renumbered.
**Scope of dispatch and review:** QUEUE-ARCHIVE only, Steps 70-73. Never dispatch the entire master. CORE-BRIEFS Steps 66-68 are being built concurrently; see the sequencing rule under Risks.
**Parent relationship:** Extends the shipped receipt viewer and configured receipt preparation (2026-10-21) and the Main Report Set publication (CFO Steps 57-62, 64). It does not change payment authorization, receipt fingerprints, item-location boxes, the bundle schema or the copy text.
**Planning baseline:** `00177f369a82907da96d7c02a6dcbad744ec103e`, branch `main`, 2026-11-09, plus uncommitted operator-requested queue changes (clarification grouped by recorded next step; recent payments in the copy text) in `np_finance/reimbursement_report.py`, `np_finance/reports/templates/reimbursement_queue.html.j2`, `tests/test_reimbursement_report.py`, `tests/test_reimbursement_pipeline.py`, `README.md`, `docs/loading-receipts.md` and `docs/main-report-set.md`. Those changes must be committed before Step 70 is dispatched. Untracked `.build-step/` is unrelated and must be preserved.

### What This Feature Does

The treasurer gets an end-to-end run that no longer stops at `receipts_failed`. The reimbursement queue page currently embeds every receipt image, and the shared 100 MiB embedded-image budget is full: on 2026-11-09 the sidecar held 296 pages totaling 100.0 MiB, of which 94.1 MiB belonged to paid requests, 4.5 MiB to open requests and 1.4 MiB to email follow-ups. The working queue will embed only open requests and follow-ups. Paid requests move to one archive page per submission month, because whoever asks about a past request usually knows when it was submitted, not when it was paid. Each page has its own budget; the busiest submission month so far (August 2026) is about 32 MiB.

### Existing Context

- `np_finance/receipt_viewer.py`: `MAX_PAGE_BYTES` (20 MiB) and `MAX_TOTAL_BYTES` (100 MiB) are the single budget owners. `load_receipts(path, report)` validates the whole sidecar against the total; `headroom_bytes(sidecar)` returns the remaining total and doubles as the runner's staging page guard.
- `np_finance/reimbursement_report.py`: `render_html(report, *, receipts=...)` renders one page; active cards come first and `report.closed_tickets` render in the closed-cases appendix of `reimbursement_queue.html.j2`, with their receipt data embedded. `build_report(data_path, output_path)` writes the HTML and `<stem>.copy.txt` atomically and returns `BuildResult`. Every ticket has a required `submitted` date, including legacy `P-` records.
- `np_finance/receipt_refresh.py`: `refresh_receipts(...)` admits new pages against `headroom_bytes(sidecar)`; when unlinked items are joinable but none can attach it raises "no unlinked receipt item could be attached" (the 2026-11-09 failure).
- `np_finance/main_reports/render.py`: `_write_set` calls `build_report(staged_bundle, staging / QUEUE_HTML)`; `OUTPUT_NAMES` is a fixed tuple and only those names are moved into the run folder and hashed into artifacts. `np_finance/main_reports/runner.py` compares artifacts with `OUTPUT_NAMES` (line 884), refreshes `COMPATIBILITY_FILES`, and calls `headroom_bytes` while staging the sidecar (line 836).
- CORE-BRIEFS Steps 66-68 change `render.py`, `runner.py`, `models.py`, the main-report templates, `tests/conftest.py`, the main-report tests and (Step 68) `np_finance/cli.py`.

### Scope

In scope: the split render (working queue plus paid archives by submission month), per-output budget validation, per-output admission during receipt preparation, publication of the archives in the Main Report Set, and the operator's live acceptance.

Out of scope: re-encoding or downscaling receipt images (measured at only 2.4x smaller, so deferred); disk growth from immutable run folders (18 runs used 7.8 GB on 2026-11-09; existing pruning guidance applies); any change to the bundle or sidecar schema, copy text, payment recording, fingerprints or item-location boxes; splitting one month across several pages.

### Impact Analysis

Search root: `np_finance`, `scripts`, `tests` (excluding `__pycache__`), plus `docs/*.md`, `README.md` and `CLAUDE.md` for budget wording.

| File or interface | Change | Reason | Verified evidence |
|---|---|---|---|
| `receipt_viewer.MAX_TOTAL_BYTES` | Becomes the per-output-file budget (rename allowed only with every consumer) | Budget applies per rendered page | receipt_viewer.py:32; tests/test_receipt_viewer.py:187-276; tests/test_receipt_pages.py:647-648 |
| `receipt_viewer.load_receipts` | Validates each output's page set rather than the whole sidecar total | Sidecar total may exceed one file's budget | Consumers: reimbursement_report.py:1801, receipt_refresh.py:385 and 601, tests |
| `receipt_viewer.headroom_bytes` | Replaced in the refresh by per-output headroom; runner staging guard switches in Step 72 | Whole-sidecar headroom causes the failure | Consumers: receipt_refresh.py:427, main_reports/runner.py:836, tests/test_receipt_refresh.py:216 and 299, tests/test_main_report_runner.py:1198 |
| `reimbursement_report.build_report` | Split mode writes the working queue plus `<queue-stem>.paid-YYYY-MM.html`; `BuildResult` lists archive paths | New outputs | Callers: cli.py:1076 (report-reimbursements), cli.py:1218 (update-reimbursements), main_reports/render.py:2337, scripts/capture_readme.py:252 |
| `render_html` and `reimbursement_queue.html.j2` | Working queue omits paid cards and receipt data and adds a text index; new archive template renders paid cards | Split | reimbursement_report.py:1640; template closed-cases section |
| `receipt_refresh.refresh_receipts` | Per-output admission mode | Unblocks receipt preparation | Callers: cli.py:1198, main_reports/runner.py:715 and 1120 |
| `render.OUTPUT_NAMES`, `_write_set`, pointer/index links; `runner` artifact check, `COMPATIBILITY_FILES` | Variable archive artifacts are staged, hashed, linked and copied | Archives are part of the set | render.py:117-135, 2265-2266, 2290-2380; runner.py:251-259, 884 |
| Docs | Budget and output wording | Accuracy | `docs/receipt-viewer.md`, `docs/main-report-set.md`, `CLAUDE.md` mention 100 MiB; `docs/loading-receipts.md`, `README.md` describe outputs |

`render_html` and `closed_tickets` have no consumers outside `reimbursement_report.py`, its template and tests.

### New Components

- `np_finance/reports/templates/reimbursement_paid_archive.html.j2`: one submission month's paid requests, reusing the queue's card macro and receipt viewer.
- Per-output page-set accounting in `receipt_viewer.py` (functions, not a new module).

### Design Decisions

| Choice | Decision | Provenance | Rationale | Alternatives or unresolved state |
|---|---|---|---|---|
| Split basis | Working queue embeds only active requests and email follow-ups; paid requests move to archives | Operator, 2026-11-09 | 94.1 of 100.0 MiB is paid-request receipts | Calendar split of the whole queue (scatters open work); a higher limit (the 140 MB page is already slow); separate image files (breaks the self-contained private page and the immutable run copy) |
| Archive grouping | Submission month (`Ticket.submitted`) | Operator, 2026-11-09 | Requesters know when they submitted | Payment month (rejected by the operator) |
| Archive granularity | One page per month | Operator, 2026-11-09 | Busiest month about 32 MiB (about 3x headroom); July-September together about 56 MiB | Quarter |
| Budget | 100 MiB of embedded page bytes per output file; 20 MiB per page unchanged | Agent default | Keeps tested bounds and browser load | A larger cap |
| Archive updates | Every run re-renders archives deterministically; a month's page changes only when a request submitted that month is paid or corrected | Agent default (consequence of submission-month grouping) | Late payments land in older months; immutable run folders keep history | Freezing months (would hide late payments) |
| Finding a paid request | Working queue lists every paid request as one text row (reference, requester, submitted date, amount, payment date) linking to its archive anchor; no images | Agent default | Browser search on the working queue finds any request, then one click opens its month | Month links only |
| Follow-ups | All email follow-ups stay in the working queue | Operator ("plus email follow-ups") | Small (1.4 MiB) and actionable | Archive resolved follow-ups (future) |
| File naming | `<queue-stem>.paid-YYYY-MM.html` beside the queue, relative links | Agent default | Works for CLI outputs, run folders and compatibility copies | A subfolder |
| Over-budget month | Validate every output before replacing any file; fail closed naming the month | Agent default | Receipts are never silently dropped | Automatic month splitting (future) |
| Refresh admission | A new page is admitted only if both the working-queue set and the request's submission-month set stay within budget | Agent default | Prevents a later archive overflow | Working-queue check only |
| Transition | Steps 70-71 add explicit split/per-output modes that the two reimbursement commands select; the Main Report Set keeps today's single-file behavior until Step 72 switches it and removes the old modes | Agent default | Avoids editing CORE-BRIEFS files while Steps 66-68 are in flight; `update-reimbursements` gains the fix sooner | Build everything after Step 68 |
| Copy text | Unchanged | Agent default | Derived from the bundle, not the HTML | none |

### Build Steps

### Step 70: Render paid requests into submission-month archive pages
- **Problem:** The queue page embeds every receipt, so paid requests exhaust the 100 MiB page budget.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep
- **Files:** `np_finance/reimbursement_report.py`, `np_finance/receipt_viewer.py`, `np_finance/reports/templates/reimbursement_queue.html.j2`, `np_finance/reports/templates/reimbursement_paid_archive.html.j2` (new), `np_finance/cli.py` (report-reimbursements and update-reimbursements handlers only), `tests/test_reimbursement_report.py`, `tests/test_receipt_viewer.py`, `tests/test_reimbursement_cli.py`, `tests/test_reimbursement_pipeline.py`, `docs/loading-receipts.md`, `docs/receipt-viewer.md`
- **Produces:** A split mode of `build_report`, selected by both reimbursement commands: the working queue embeds receipts only for active requests and follow-ups and lists each paid request as a linked text row; one archive page per submission month holds that month's paid cards and receipts; every output is budget-validated before any file is replaced; `BuildResult` lists the archives and the CLI prints them. The Main Report Set caller keeps single-file mode.
- **Done when:** A real `report-reimbursements` CLI fixture run whose fictional sidecar totals more than the per-file budget, while each split output stays under it, writes the working queue and one archive per submission month of settled requests; every settled request appears on exactly one archive (its submission month) and as one working-queue text row whose link resolves to its card; the working queue embeds no page referenced only by settled requests; receipt dialogs open in Chromium on the working queue and on an archive; an archive whose pages exceed the budget fails with an error naming its month and leaves every existing output unchanged; the copy text equals `render_copy_text` for the same bundle; the Main Report Set tests pass unchanged.
- **Depends on:** none (dispatch only when no concurrent build is editing `np_finance/cli.py`; CORE-BRIEFS Step 68 lists it)

### Step 71: Admit new receipt pages against the budget of the output that embeds them
- **Problem:** Receipt preparation refuses new pages once the whole sidecar reaches 100 MiB, even when the output that would show them has room.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep
- **Files:** `np_finance/receipt_refresh.py`, `np_finance/receipt_viewer.py`, `np_finance/cli.py` (update-reimbursements handler only), `tests/test_receipt_refresh.py`, `tests/test_receipt_viewer.py`, `tests/test_reimbursement_pipeline.py`, `docs/receipt-viewer.md`
- **Produces:** A per-output admission mode for `refresh_receipts`, selected by `update-reimbursements`: a page is admitted only if the working-queue set and the request's submission-month archive set both stay within budget; refusals name the request and the full output; existing links never move or drop. The runner keeps whole-sidecar admission until Step 72.
- **Done when:** A real `update-reimbursements` CLI fixture run with `[receipt_refresh]` configured and a sidecar above the per-file budget in total, but with room in the working queue, attaches the unlinked active request's page and renders every output within budget; when the target month's archive would exceed the budget, that page is refused with a review-needed detail naming the request and month while another eligible page still attaches; when no page can attach, the existing `receipts_failed` rule still stops before any output changes; existing receipt-refresh and runner tests pass unchanged.
- **Depends on:** 70

### Step 72: Publish the working queue and paid archives in the Main Report Set
- **Problem:** `end-to-end-run` still publishes one queue file and stops at `receipts_failed` whenever receipt preparation is configured.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep
- **Files:** `np_finance/main_reports/render.py`, `np_finance/main_reports/runner.py`, `np_finance/main_reports/models.py` (only if the manifest needs a variable artifact list), `np_finance/reports/templates/main_reports/` (pointer and index), `np_finance/reimbursement_report.py` and `np_finance/receipt_refresh.py` (remove the single-file and whole-sidecar modes), `np_finance/cli.py`, `scripts/capture_readme.py`, `tests/test_main_report_render.py`, `tests/test_main_report_runner.py`, `tests/test_reimbursement_report.py`, `tests/test_receipt_refresh.py`, `docs/main-report-set.md`, `docs/receipt-viewer.md`, `README.md`, `CLAUDE.md`
- **Produces:** `end-to-end-run` renders, validates, hashes and publishes the working queue plus every paid archive; the pointer and index link archives by submission month; compatibility copies include them; staging uses the per-output guard and preparation uses per-output admission; the transitional modes are removed from every caller; the documented temporary-config workaround is retired.
- **Done when:** The real-component Chromium smoke `test_chromium_end_to_end_run_publishes_real_exports_within_the_bound`, extended with settled requests in two submission months and a sidecar above the per-file budget in total, publishes the working queue and both archives with manifest hashes, pointer/index links and compatibility copies, each within budget; a failure staging or validating any archive leaves the previous pointer and every compatibility copy unchanged; `--dry-run` writes nothing; a repository search finds no caller of the removed modes; `scripts/capture_readme.py` still produces its fictional output.
- **Depends on:** 70, 71, 68

### Step 73: Accept the split queue on the actual private queue
- **Problem:** Fixture evidence does not show the actual queue linking receipts again under the ordinary command.
- **Type:** operator
- **Issue:** #
- **Files:** Private config, bundle, sidecar and published outputs only; no public source changes
- **Produces:** Private live-run observations and explicit acceptance or a bounded discrepancy list.
- **Done when:** With the unmodified private config (receipt preparation enabled), the operator observes one `end-to-end-run --dry-run` and one ordinary `end-to-end-run` complete without `receipts_failed`; opens the working queue from `reports/output/main-report-set.html` and an open request's receipt; finds a paid request through its submission month and opens its receipt; confirms from the run record that every queue and archive output is within budget; and confirms that requests unlinked on 2026-11-09 are now linked or listed as review-needed, not refused for budget.
- **Depends on:** 72

### Risks and Open Questions

| Item | Consequence | Mitigation / owner | Blocking state |
|---|---|---|---|
| CORE-BRIEFS Steps 66-68 edit the same Main Report Set files and `cli.py` | Merge conflicts or a red gate | Step 72 depends on 68; Steps 70-71 change only the reimbursement CLI handlers and must not run concurrently with Step 68 | Sequencing only |
| Uncommitted baseline changes in the reimbursement report files | Step 70 would build on a moving base | Operator commits them before dispatch | Blocks Step 70 dispatch |
| One submission month exceeds 100 MiB | That archive fails closed | Busiest month is about 32 MiB; deferred options are month splitting or image re-encoding | Not blocking |
| A late payment changes an older month's archive | Page content changes after its month | Expected and documented; immutable run folders keep history | Not blocking |
| Older archive files left beside a CLI output after a rename | Possible confusion | Only the current set is linked; nothing is deleted automatically; documented | Not blocking |
| Interim before Step 72 | `end-to-end-run` still needs the temporary config without `[receipt_refresh]` | `update-reimbursements` produces the split queue after Steps 70-71 | Not blocking |
| Run-folder disk growth | Disk use keeps rising | Out of scope; existing pruning guidance | Not blocking |

### Testing Strategy

Triggered obligations: compatibility (no bundle or sidecar migration; existing private inputs must render under the new code and the copy text stays identical; backout is a code revert, and prior run folders stay immutable); producer/consumer chain (the CLI fixture runs in Steps 70-71 and the real-component Chromium smoke in Step 72 exercise sidecar to render to publication with real components); one-shot CLI, so no autonomous or scheduled observation applies; no deployment seam (local CLI only; private config unchanged).

Narrow tests exercise page-set partitioning by status and submission month, per-output budget arithmetic at the boundary, a shared page referenced from two outputs, an empty month, legacy `P-` submissions, settled tickets with declined lines, follow-up pages, admission refusals, and atomic all-or-nothing replacement. Integration goes through the production callers named in each step's acceptance. Verified command surfaces (`pyproject.toml`, CLI parser, existing test files):

```powershell
uv run pytest tests/test_reimbursement_report.py tests/test_receipt_viewer.py tests/test_receipt_refresh.py tests/test_receipt_pages.py tests/test_reimbursement_cli.py tests/test_reimbursement_pipeline.py -q
uv run pytest tests/test_main_report_render.py tests/test_main_report_runner.py -q
uv run ruff check np_finance tests
uv run ruff format --check np_finance tests
uv run mypy --strict np_finance
uv run python scripts/check_no_identity.py
```

The gate that marks each step DONE runs the full suite; with the `web` extra installed it needs the Firestore emulator, or the gate record must name the emulator modules it could not collect. Step 73 manual checks, run separately so each result can be read:

```powershell
uv run np-finance end-to-end-run --as-of <YYYY-MM-DD> --dry-run
```

```powershell
uv run np-finance end-to-end-run --as-of <YYYY-MM-DD>
```

Planning handoff order for this phase only: `/plan-review --autofix docs/plans/master_plan.md`, `/plan-redline --plan docs/plans/master_plan.md`, `/plan-wrap --autofix docs/plans/master_plan.md`, then `/repo-sync --plan docs/plans/master_plan.md` scoped to QUEUE-ARCHIVE, then `/build-phase --plan docs/plans/master_plan.md --phase QUEUE-ARCHIVE`. Step 73 remains attended.

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
| P1 | P | CFO workbook is the ongoing Wells Fargo, WIX and PayPal source; retire default bank PDF imports. | stands |
| P2 | P | July-June school summaries, January-December P&L; retain all outstanding carryovers and the existing mail collection window. | stands |
| P3 | P | Valid adjustments recorded in our Assumptions journal affect reports immediately. | stands |
| P4 | P | Publish the five-report Main Report Set with receipts/red marks and copy text retained. | stands |
| P5 | P | Targeted verification and one live cycle; avoid repeated unrelated test campaigns. | stands |
| P6 | P | Review, redline with delegated approval, wrap and sync now; build later in an Opus session. | stands |
| D1 | D | Preserve CFO bank-based monthly-category net treatment, with processor detail as reconciled enrichment. | stands |
| D2 | D | Append a versioned immutable journal below existing Assumptions content; require target revision/precondition matches. | stands |
| D3 | D | Publish immutable private run folders through one atomic HTML index; refresh compatibility filenames afterwards. | stands |
| D4 | D | Use numeric Steps 57-63 in Phase CFO, split reconciliation and adjustment writes, and build only 57-62 automatically. | stands |
| D5 | D | Use deep review for financial identities, reconciliation, journal, facts and publication; code review plus browser evidence for rendering. | stands |
| D6 | D | Treat source coverage gaps and ambiguous matching as visible unresolved data, never invented zeroes or balancing entries. | stands |
| D7 | D | Use strict no-write dry-run, bounded capture retries and local serialization with explicit Sheets external-edit race limits. | stands |

| P7 | P | Superseded by P18: Add Classroom Budgets and Fundraising vs. Obligations to the ordinary end-to-end-run core documents. | changed 2026-11-09 |
| P8 | P | Retain the accepted one-page design; equal classroom distributions are design-only until actual enrollment and rates arrive. | stands |
| P9 | P | Calculate cuts with no reserve draw, also showing alternative draw dollars, percent and approximate repeated-gap years. | stands |
| P10 | P | Plan production integration now; implementation is a later task. | stands |
| D8 | D | Use one private versioned roster/policy JSON and read-only live financial bindings. | stands |
| D9 | D | Use school-year attributed posted classroom payments, with issued-but-unposted items separately identified. | stands |
| D10 | D | Publish explicit unavailable/partial new pages when optional data is missing. | stands |
| D11 | D | Treat not-yet-paid spending as remaining adopted plan, retaining already-incurred overruns. | stands |
| D12 | D | Superseded by P11: do not use total cash/CDs as a reserve proxy. | changed 2026-11-04 |
| D13 | D | Reuse capture, facts, templates, exports, manifests and atomic publication. | stands |
| D14 | D | Superseded by D24: Build four code slices, then perform one attended live acceptance. | changed 2026-11-09 |
| P11 | P | Separate reserves from operating cash; the later P13 selects the actual CD balance instead of a rough estimate. | changed 2026-11-04 |
| P12 | P | Superseded by P23: The earlier specialist payment does not satisfy the current year-end obligation; correct period attribution without counting the annual cost twice. | changed 2026-11-09 |
| P13 | P | Reserves equal the captured CD account balance. Exclude checking/savings; replace the earlier rough estimate. | stands |
| P14 | P | Add a central scenario using prior-year classroom utilization and break-even future fundraising events; account for their interaction with total fundraising. | stands |
| P15 | P | Superseded by P20/P23: Show bold Total sans SP immediately above remaining Total, excluding specialist teacher contracts. | changed 2026-11-09 |
| P16 | P | Superseded by P20/P21: Keep concise approved copy and a distinct central-case assumptions section; omit the generic outlook subtitle and separate other-income sentence without changing calculations. | changed 2026-11-09 |
| P17 | P | Superseded by P20: Expand summary obligations by three rows per column and add complete paid and remaining appendices, one portrait page each after the one-page summary. | changed 2026-11-09 |
| D15 | D | Use prior-year total fundraising dollars as the central benchmark and floor it at received plus future break-even event receipts; count event income once. | stands |
| D16 | D | Require explicit comparable classroom/category mappings and confirmed future-event dates; keep unavailable assumptions visible instead of guessing. | stands |
| P18 | P | Seven-report set: the redesigned Budget Snapshot absorbs Fundraising vs. Obligations; add Classroom Budgets and Treasurer Notes; no separate Fundraising vs. Obligations output. | stands |
| P19 | P | One as-of date for every financial figure: academic ledger cut at as-of, balances from the latest row on or before as-of. | stands |
| P20 | P | Budget Snapshot design draft v3: five headline boxes; progress section (no time markers, projected-events segment) above where money went/came from; scenarios and assumptions; complete paid and not-yet-paid appendices; Largest budget lines, data follow-ups, narrative, audit block, page-1 obligations tables, Fundraising versus the plan and the reserves strip removed. | stands |
| P21 | P | Rename the old central case Minimum self-funding; last year's pace becomes the highlighted Central Case. | stands |
| P22 | P | Projected year-end balance (Central Case) = bank net of card + Central Case fundraising still to come - spending still ahead; next year's contracts outside; checking-first split; checking red with note below a private floor; time account red only when drawn down. | stands |
| P23 | P | Specialist contracts paid at the start of the school year are that year's expense and already paid; no second current-year obligation. | stands |
| P24 | P | Bank-accounts box shows checking, time account and credit card with a total net of the card; savings omitted while zero; the card balance enters the projection. | stands |
| P25 | P | Fundraising categories outside the adopted budget, when declared fundraising, count as raised under their own category. | stands |
| P26 | P | Remove formula, caption and fine-print lines; a two-page summary is acceptable. | stands |
| P27 | P | Add Treasurer Notes to the standard documents produced by end-to-end-run. | stands |
| D17 | D | Budget Snapshot uses the academic-ledger basis; the Fundraising Summary and CFO P&L keep the bank basis, bridged in run records. | stands |
| D18 | D | Board questions are operator-authored private plain-text items with closed-list figure placeholders and an optional reimbursement clarification-group attachment. | stands |
| D19 | D | Treasurer Notes prints financial figures at as-of and queue status at the staged bundle's evidence time. | stands |
| D20 | D | Without planning input the Budget Snapshot shows its ledger figures as unavailable; no fallback to the former bank-basis design. | stands |
| D21 | D | Keep a compact footer with run ID and input-set hash; move audit counts to run records and amend the design contract. | stands |
| D22 | D | Displayed parts tie to displayed totals through largest-remainder rounding; cents unchanged in facts. | stands |
| D23 | D | Planning schema version 2 is additive: budget_snapshot.checking_floor and treasurer_notes.questions; version 1 stays valid. | stands |
| D24 | D | Five code slices (65, 66, 67, 74, 68) then one attended acceptance (69); Treasurer Notes is Step 74 because QUEUE-ARCHIVE reserves 70-73; Step 74 builds on that phase's reimbursement_report.py commit (`973f7b5`). | stands |
| D48 | D | CORE-BRIEFS: a Treasurer Notes question whose reimbursement group is absent from the staged bundle renders "No requests outstanding" plus a value-free run warning naming the question; it never fails the run (operator-approved 2026-11-11). | stands |

## Project naming migration

See [the migration guide](../project-rename.md) and [progress](../rename-progress.html).
Existing feature acceptance boundaries remain unchanged.


## Naming migration and workbook documentation closeout (2026-10-26)

**Delivered scope:** `np-finance` repository, checkout and command; `np_finance`
imports; workspace launchers and public project links; pre-rename public source
archive; non-profit terminology in maintained documentation and the connected workbook.
This is a completion record, not a new build queue or acceptance of unrelated tracks.

- The renamed `end-to-end-run` published all five reports; 15 output files and 16
  compatibility copies were verified during the migration.
- A complete Sheets API scan of 36 workbook tabs found eight remaining text cells
  across five tabs. Scoped text updates were reread and verified: no old project
  names or PTA wording remained in returned workbook data. Other entered values,
  formulas, cell formatting, notes, rich text and validation were unchanged.
- Public source history is preserved in `docs/archive/pta_finance/source-e65e848.zip`;
  all 229 members match the pre-rename commit's Git blobs. Private workbook audit
  snapshots and cell-level changes remain gitignored and are never issue attachments.
- GitHub profile, deployed portfolio, Observatory and Yarvis references are updated.
  The old GitHub URL redirects to the same repository and must not be deleted.

### Files refreshed at closeout

| File | Change |
|---|---|
| `README.md` | User-visible migration outcome |
| `docs/plans/master_plan.md` | This closeout and current editable-tab instruction |
| `CLAUDE.md` | Current naming and workbook-audit status |
| `MEMORY.md` | Replace stale unbuilt implementation handoff |

### Verification and remaining boundaries

The workbook audit is live readback evidence, not a pytest count. Previously observed
rename checks: 281 web tests passed; four layout scenarios passed on each of Windows
and Linux; strict mypy, Ruff, packaging and privacy checks passed. The earlier local
non-web run recorded 2,206 passes, three failures and 13 skips; all three failures
passed on isolated recheck. Observatory's focused suite recorded 242 passes, eight
skips and two expected failures. The portfolio check, build, accessibility and live
publication checks passed. This documentation-only closeout does not rerun product
qualification or mark Step 63 accepted.

The empty legacy checkout remains after Windows denied its move and automatic
approval review blocked its removal. Existing cloud/wire/schema identifiers remain
compatible. Step 63's category crosswalk and operator financial review, the paused
and blocked worktrees, and all other pending tracks retain their existing statuses.

Fresh checkout: Python 3.12+, `uv sync --extra dev --extra slides --extra receipts
--extra reports`, `uv run playwright install chromium`, and private configuration
per [SETUP](../../SETUP.md). Run `uv run np-finance end-to-end-run --as-of YYYY-MM-DD
--dry-run` before publication. Preserve installed extras when syncing. Full test
setup including the optional web emulator is documented in [CLAUDE.md](../../CLAUDE.md).

## Reimbursement evidence and report review closeout (2026-10-28)

Delivered operational/reporting scope; no numbered build step or unrelated acceptance gate
is marked complete by this record.

### What was built

- Optional private `appendix.follow_ups` records render email/check work in the reimbursement
  queue with captured source pages and the existing receipt viewer; repeated runs preserve them.
- The queue compares original item sums, form totals and reviewed totals, retaining original
  claimed amounts on corrected rows and in receipt dialogs.
- Metadata mismatch advice gives exact totals/differences and directs receipt inspection.
  Authorized receipt corrections and verified regions persist through normal refresh.
- The live end-to-end command published the five-report set, with 15 verified artifacts and
  16 refreshed compatibility copies. Private corrections, confirmations and source images
  remain outside Git; no payment was sent by the reporting work.

### Files changed

| File | Change |
|---|---|
| `np_finance/reimbursement_report.py` | Strict optional follow-up records and viewer projection |
| `np_finance/receipt_viewer.py` | Validate referenced follow-up source pages |
| `np_finance/reimbursement_pipeline.py` | Specific amount mismatch explanations |
| `np_finance/reports/templates/` | Combined follow-up cards and original/reviewed amounts |
| `tests/test_main_report_runner.py` and report/pipeline/viewer tests | Persistence, validation, amount and browser regression checks |
| `docs/main-report-set.md`, `docs/loading-receipts.md`, `docs/receipt-viewer.md` | Run evidence and receipt correction procedure |

### Validation and boundaries

223 focused tests cover pipeline, report, receipt viewer, receipt refresh and runner behavior;
strict package mypy, changed-file Ruff/format, identity and whitespace checks passed. Published
HTML was inspected in Chromium, including amount labels, red outlines, follow-ups and mobile
layout. This is not a full-suite acceptance claim.

Phase 10 Step 51 remains paused in its preserved worktree. The manual follow-up records do
not implement the automatic scanner. Step 63 financial acceptance, dated category-mapping
behavior, automatic split-check settlement and issued/cleared check lifecycle remain open.
The exact follow-up schema and receipt correction procedure are in the linked operator guides;
live financial evidence and private continuation pointers are never public issue attachments.
