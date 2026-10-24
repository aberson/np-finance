# CFO workbook and Main Report Set — v0 plan

Status: reviewed, redline approved by delegated authority, and wrapped READY, 2026-10-21. Workbook access and read-only schema/formula inspection succeeded after sharing was updated. User decisions and implementation defaults below are accepted; Steps 57-62 were built 2026-10-21/22 (issues #96-#101 closed); Step 63 live acceptance remains. Step 64 (one-page summaries, main-report-design.md) was built 2026-10-23. Step 63 is in progress: live sets were published 2026-10-22/23; acceptance and the category crosswalk remain.

The [master plan](../plans/master_plan.md#phase-cfo-cfo-workbook-and-main-report-set-v0) owns dispatch and status for Phase CFO Steps 57-64 (former CFO aliases are preserved there). This document is its supporting specification, not a second execution queue. Real workbook identifiers, account addresses, source samples, and financial findings stay in private configuration and evidence.

## 1. What This Is

Proposal: docs/plan-reference/cfo-main-report-set-proposal.html (the master owns decisions and status).

Replace ongoing Wells Fargo PDF imports with the CFO-maintained workbook's Wells Fargo, WIX, and PayPal tabs. Use that source consistently, record our adjustments in our own Google workbook, and regenerate a coordinated Main Report Set. School-year summaries use July 1–June 30; CFO P&L uses January 1–December 31. Prior-year reimbursement obligations remain visible. Every difference between source and adjusted totals must be explainable.

## 2. Existing context and verified baseline

- `pta_finance/sheets.py` already provides spreadsheet selection, retry handling, reads, and targeted writes. `backup.py` preserves formula-aware cell snapshots before mutations. Reuse these boundaries; the CFO workbook is read-only.
- `report_source.py:read_timeseries` reads the existing Budget Timeseries tab. `to_inputs` projects annual actuals using synthetic year-end dates. Those rows are not transaction evidence and must not become the monthly P&L input.
- `cli.py:_cmd_update_reimbursements` refreshes mail/evidence, prepares receipts, and renders the queue and copy text. It does not currently produce the complete five-report set.
- `reimbursement_report.py:build_report` emits HTML and `.copy.txt` and loads a fingerprint-validated receipt sidecar. Preserve those interfaces and evidence identities.
- Existing private summary, fundraising, and bank-ledger scripts contain dated inputs and edition-specific constants. They supply design/provenance references, not reusable production adapters. The private inspection inventory is recorded beside the planning decisions under `reports/output/.work/cfo-workbook-plan/`.
- Current configuration uses reporting-year start month 7. Existing budget/fundraising reports use July; reimbursement acquisition and older summaries begin in June. User approved aligning the summaries while retaining the collection window.
- Our workbook's Assumptions tab exists and contains live scenario constants and existing notes. Its complete values/formulas were inspected and preserved privately. Do not replace or clear it. The CFO workbook is now readable; all seven tabs were inspected, including source P&L and budget formulas. Detailed bindings, coverage, and reconciliation evidence are stored privately beside the planning decisions.

## 3. Scope

### Included

1. Read the three CFO transaction tabs plus Profit & Loss, the school-year Budget Tracker, and Category Mapping as reference/control inputs; retain dated private snapshots and normalize observed source fields. The Credit Card Transactions tab is currently empty and is not a fourth financial feed in v0.
2. Reconcile bank and processor activity without counting receipts and their payouts twice; preserve fees, refunds, reversals, and source corrections.
3. Record evidence-backed adjustments in a dedicated structured section of Assumptions. Valid recorded adjustments immediately affect our reports; there is no second approval gate for this reporting layer.
4. Align school-year summaries; keep all outstanding requests and receipts accessible across year boundaries.
5. Produce the five reports below, plus the existing copy text, a report index, a run manifest, and a discrepancy/reconciliation artifact.
6. Provide a repeatable local end-to-end command and regenerate the complete set with real source data after access and implementation.

### Excluded

Direct bank/WIX/PayPal APIs, new scheduling, mail sending, public publishing, rewriting CFO cells, automatic payment authorization, a new shared-workflow UI, and a general accounting-system rewrite. Bank PDF import leaves the default reporting path; historical PDFs and parser code are retained. **Receipt PDF/image processing remains in use** and is not retired by this change.

## 4. Impact analysis

Preserve existing public function signatures and schema-v2 reimbursement bundles. New reporting records and adapters live alongside them. These are planned changes, not claims that the components already exist.

| File / area | Change type | Reason | Verified |
|---|---|---|---|
| `pta_finance/config.py`, `config.example.toml` | Extend | Optional CFO source bindings and separate report-period settings | Read `Config`, `FiscalYear`, and `load_config`. Existing budget start month stays unchanged. Direct toolkit `Config`/loader references found in `config.py`, `cli.py`, `tests/conftest.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_gmail_source.py`, `tests/test_reports.py`; similarly named shared-workflow config is a separate contract and stays unchanged. |
| `pta_finance/sheets.py`, `backup.py` | Reuse; narrowly extend if needed | Read a separately configured workbook; snapshot and target adjustment cells | Read `SheetsClient.connect`, spreadsheet selection, retry boundary, and snapshot implementation. Do not change existing method signatures; add explicit read-only source connection behavior. |
| `pta_finance/report_source.py` | Preserve existing API; add a separate adapter | Keep adopted budget targets; use actual dated transactions for the new report set | `read_timeseries` calls in CLI schema validation, analyze, and report; `to_inputs` calls in CLI analyze/report. Tests in `test_report_source.py` and `test_budget_sync.py`. No global replacement of annual data with transactions. |
| `pta_finance/cli.py` | Extend | Add `end-to-end-run`; retain existing reimbursement commands | Inspected refresh → receipt preparation → `build_report` path and parser registrations. No all-report command exists today. |
| `pta_finance/reimbursement_pipeline.py` | Reuse | Stage a validated reimbursement refresh without changing review/payment semantics | `plan_bundle_refresh` called by `refresh_bundle` and CLI dry-run; `refresh_bundle` called by CLI normal update. Regression callers in `test_reimbursement_pipeline.py` and CLI tests. Signatures remain unchanged. |
| `pta_finance/reimbursement_report.py` | Reuse; add separate summary projection | Keep queue/copy text; classify summary items by school year | `build_report` callers: CLI report/update, `scripts/capture_readme.py`, `tests/test_receipt_pages.py`, `tests/test_receipt_viewer.py`, `tests/test_reimbursement_report.py`. Keep its two-argument API; do not rewrite fingerprints to change reporting periods. |
| `pta_finance/reports/builder.py`, templates | Extend with separate summary models/templates | Reuse report styling and money formatting without leaking private transactions into public reports | Read existing internal/external model distinction and external PII guard. New Main Report Set is private by default; existing external models remain unchanged. |
| Private dated report scripts | Replace in the normal workflow, retain originals | Remove dated constants and PDF-ledger dependency from future runs | Inspected existing bank-ledger and reimbursement-summary producers and fundraising CSV producer; private evidence inventory identifies exact files. Never copy private constants into tracked modules. |
| Tests and operator documentation | Extend | Focused source-to-report checks; clear command and period labels | Existing CLI, report-source, reimbursement, receipt-viewer, and config suites identified. Master remains sole dispatch plan. |

Before implementation changes any shared signature, grep its complete caller set again and amend this table. No identity/schema migration is authorized implicitly.

## 5. New components

Proposed package `pta_finance/main_reports/`, split by responsibility:

- `sources.py`: read-only CFO workbook reader, snapshot provenance, and per-source adapters bound to inspected headers.
- `models.py`: exact-money transaction, source reference, adjustment, reporting-period, and run-manifest records.
- `reconcile.py`: source identity, duplicate/transfer handling, category crosswalk, and discrepancy records.
- `adjustments.py`: parse, validate, snapshot, and idempotently append structured adjustment entries to our Assumptions section.
- `facts.py`: school-year, calendar-year, reimbursement carryover, budget, and fundraising projections.
- `render.py`: four summary documents plus report index; existing queue renderer is reused.
- `export.py`: offline headless Chromium PDF/PNG export of the four summaries (as built).
- `runner.py`: orchestration, staged generation, artifact validation, and publication.

Names are implementation defaults, not new external source column names. Keep the package small; do not introduce services or a generic plugin framework.

## 6. Design decisions

### A. Source authority and mappings — user-approved

The CFO workbook is the ongoing source for all three financial feeds. Preserve its values, categories, and accounting treatment in a source view. Use a versioned explicit crosswalk into our budget categories, allowing documented splits whose amounts sum to the original. Keep adopted school-year budget targets from our existing workbook. Do not overwrite them with CFO actuals or add legacy Budget Timeseries actuals on top of imported transactions.

Access and initial source binding inspection are complete. Exact tab IDs, headers, source snapshots, formula snapshots, and observed coverage are recorded privately. The workbook supplies a published P&L and school-year budget tracker. Preserve the distinction between published controls and our derived totals. The observed P&L basis is the bank DATE column and signed category allocations; it is not a processor-sale-date P&L or a general accrual ledger.

#### Verified source contracts

| Input | Observed shape | v0 handling |
|---|---|---|
| Wells Fargo Checking | Row 1 headers: DATE, DESCRIPTION, AMOUNT, CHECK #, STATUS, CATEGORY, OVERRIDE CATEGORY, FINAL CATEGORY; data begins row 2; no native transaction ID | Preserve all fields. FINAL CATEGORY prefers an override over the calculated CATEGORY. A plain category allocates the whole amount; `Category A: 100.00, Category B: -3.00` allocates signed components. Validate that splits sum to the bank amount (amended 2026-10-22 by operator decision: a split that does not sum is a `split_sum_mismatch` warning, not a row error; the row is published with the signed gap as an explicit `Unallocated split difference` component, while every other row error still fails closed). Preserve repeated legitimate bank rows without relying on row number alone. |
| WIX Transactions | Group headings in row 1; actual headers in row 2; data begins row 3; repeated billing/shipping labels and repeated Status labels | Bind by column position plus the complete expected header signature, not a lossy header-keyed dict. Preserve Provider Payment ID, payment date, transaction datetime and declared offset, Currency, Amount, Processing Fee, Service Fee, Net, Transaction Status, Refund Amount, Payment Provider, Order ID, product name and quantity. Distinguish successful, declined, authorized, refunded, partial refund, and chargeback states. Header labels match literally, then ignoring surrounding spaces; the default date labels also accept the export's " GMT -07:00" suffix and the product column may be "Name" under "Products or Services"; timestamps may use "M/D/YYYY, H:MM:SS AM". |
| Paypal Transactions | Row 1 headers; Transaction ID and Reference Txn ID; Date, Time, TimeZone, Type, Status, Currency, Gross, Fee, Net, Balance Impact, item details | Transaction IDs repeat because Shopping Cart Item rows are details, not additional balance movements. Preserve children for allocation; classify parent movements and separate Partner Fee and General Withdrawal rows. Never deduplicate solely on Transaction ID or sum every Gross/Net cell indiscriminately. PayPal "POS Payment" is an incoming sale; "Mass Pay Payment" stays `unknown_type`. |
| Profit & Loss | Formula in A1 expands bank FINAL CATEGORY splits, groups by category/month, and excludes exact category `Internal Transfer` | Reproduce this bank-based source view first. The formula has no explicit calendar-year or Posted-status filter; our calendar-year view must filter explicitly and explain scope differences. Flag future non-posted rows rather than silently claiming parity after excluding them. |
| School-year Budget Tracker | Budget targets are IMPORTRANGE references to our own public budget; actuals look up published P&L categories by exact name | Treat as a reconciliation control, not an independent budget or transaction feed. Keep our adopted budget source and report category-name/window mismatches; do not write derived tracker actuals back into budget inputs. |
| Category Mapping | Keyword / Target Category table | Read as classification guidance for processor enrichment. Do not override explicit bank FINAL CATEGORY with keyword matches. Resolve multiple matches visibly; do not invent unobserved keyword precedence. |
| Credit Card Transactions | Empty at inspection | Exclude from v0 ingestion; detect newly populated content as an uncovered-source warning requiring an explicit adapter. |

WIX contains both Wix Payments and PayPal provider rows, with shared payment IDs observed in the PayPal feed. Treat cross-feed payment overlap separately from processor-to-bank payout matching. Use provider/payment/reference identity and corroborating amounts/currency; preserve raw representations and flag conflicts. Bank splits already include processor fees in some payouts: do not charge those fees again when adding processor detail.

The P&L computes income/expenses from signs of **monthly category net amounts**, not each gross transaction. Categories with both inflows and outflows can show lower gross income/expense than a transaction-sign view while preserving the same net. Maintain a CFO-compatible view and label any gross activity presentation explicitly; do not silently correct this source basis. Local reproduction of every observed category/month cell matched the published P&L; exact checks and counts are private.

The feeds have unequal historical coverage; the bank snapshot does not establish complete January-to-date coverage. Show first/last observed dates and uncovered periods. An earliest transaction is not proof of coverage start, and a blank month is not proof of zero activity. Require coverage evidence or mark calendar-year totals partial. Never fill missing months from annual Budget Timeseries actuals.

### B. Periods and date semantics — user-approved

| Report | Membership / display period |
|---|---|
| Reimbursement Queue | All outstanding requests, including prior-year carryovers; retain settled appendix |
| Reimbursement Summary | July 1–June 30, year-to-date through the run's as-of date; prior-year obligations and current-year payments of them shown separately |
| Budget Snapshot | July 1–June 30; adopted school-year targets and comparable actuals |
| Fundraising Summary | July 1–June 30; campaign/category attribution and explicit gross/fee/refund/net basis |
| CFO P&L Summary | January 1–December 31, monthly columns plus year-to-date; CFO categories and source/adjusted totals |

Retain expense/purchase date, source posting/recognition date, payment date, and email received date separately. School-year expense attribution uses item-level expense date; missing dates go into a visible unresolved bucket, never a guessed year. Split cross-year claims at item level. Retain the existing email acquisition cutoff and accepted evidence; do not re-filter ingestion to July or drop settled/prior-year evidence.

A June expense paid in July is a prior-year expense with a current-year payment. Show both views without adding the payment again to expense totals. The P&L uses the CFO source's observed recognition date and separately explains timing. Use half-open date filters internally, with inclusive human-readable end dates. Preserve legacy FY labels/IDs in storage; display explicit `School year YYYY–YY` or `Fiscal year YYYY` with dates. Do not globally change `fiscal_year.start_month` to 1.

### C. Identity and reconciliation — implementation default

Use source-native IDs where available, scoped by source/account and row role; preserve snapshot hashes and row references as evidence. Row numbers alone are not identity. Bank rows lack native IDs: use a versioned fingerprint and occurrence/multiset policy preserving legitimate identical rows, with ambiguous edits kept reviewable. PayPal parent and detail rows can share an ID, so a transaction-ID-only unique constraint is invalid. Detect edits, missing rows, overlap, and ambiguous duplicates and keep them reviewable.

Processor sales, fees/refunds, and bank payouts describe related events, not additive revenue streams. Pair only on sufficiently strong source references or documented matching rules. Transfers between owned accounts are not income/expense. Unresolved payouts remain separately visible with affected totals marked incomplete; never silently recognize both sides. Preserve gross/fee/refund/net arithmetic and exact cents. Reject unsupported currency mixing rather than invent conversion rates.

### D. Adjustments and Assumptions — user-approved behavior, proposed structure

Reserve a named table section below the existing Assumptions content after rechecking the inspected full used range and formulas. Preserve scenario multipliers and existing prose. Proposed columns: adjustment ID, target source record(s), kind, effective date, prior value, replacement value or signed amount, destination category, reason, evidence reference, recorded-at timestamp, and superseded-by reference. Use distinct kinds for category/date overrides, amount corrections, and additive entries; never apply both a replacement and delta for the same correction.

Record defensible adjustments and apply them immediately in our projections. Do not manufacture balancing entries merely to erase discrepancies. Unknown differences remain findings. This authorization concerns reporting, not reimbursement approval or payment. Supersede/reverse entries to correct them, retaining the history. Before writing, snapshot exact cells, re-read the target section, reject changed content, and write only the intended cells. Keep stable adjustment IDs so reruns do not duplicate effects. If recording fails, do not publish a report pretending that adjustment was saved. Source-only runs do not mutate Assumptions.

### E. Report set and presentation — user-approved set, implementation defaults

Retain the familiar concise reimbursement-summary visual style. Generate private HTML for all five reports and PDF/PNG exports for the four summaries, using Playwright Chromium (the existing browser dependency and capture pattern; add a supported `reports` runtime extra for this new exporter). The receipt-heavy queue remains interactive HTML; preserve its `.copy.txt`. Reuse the existing queue, reimbursement-summary, and fundraising-summary filenames. New names: `budget-snapshot`, `cfo-pnl-summary`, and `main-report-set.html` for the index. Each summary is one US Letter portrait page; only the CFO P&L adds a landscape appendix (monthly matrix). The visual contract is owned by [main-report-design.md](main-report-design.md); this section keeps only the data contract.

Every summary shows period, basis, as-of date, run ID, input-set hash, one inputs-captured time, and adjustment/discrepancy counts with pointers to records/*.json; the index adds per-source freshness and coverage; the queue (reused unchanged from `build_report`), its copy text, and the PDF/PNG exports carry no in-file run ID and are tied to the run by the manifest's size and SHA-256 hashes. CFO P&L shows income, expenses, net, monthly/YTD figures, and source → adjustments → adjusted totals. Do not fabricate a calendar-year budget by halving school-year budgets. Keep budget comparisons in the school-year report until a comparable calendar-year budget exists.

Include an explicit reconciliation bridge: differing date windows, recognition/payment timing, category mapping, transfers/processor settlements, and adjustments. Each bridge amount links to underlying records; unexplained residuals remain visible. Shared-scope totals must reconcile exactly. Different-scope totals need an explanation, not artificial equality.

### F. Entry point, staging, and failure behavior — implementation default

Add `pta-finance end-to-end-run --as-of YYYY-MM-DD`, with optional existing Gmail fetch-window flags and `--dry-run`. Preserve `update-reimbursements` as the reimbursement-only command. The full command reads CFO tabs, budgets, Assumptions, and reimbursement evidence, then generates every report from one captured input set. It must not invoke bank PDF extraction. Continue receipt preparation and source-image embedding.

Capture each source's retrieval time and coverage; Google multi-tab reads are not assumed transactionally consistent. Check selected ranges/version evidence before and after capture; retry the entire capture once, then stop if still changed. Hash the validated input set into a manifest. Dry-run reads and validates existing local evidence and live Sheets but writes no files, tokens, or Sheets cells. Reject `--dry-run` combined with mail-fetch or adjustment-write arguments before authentication. Do not invoke the Gmail acquisition path in dry-run.

Stage the reimbursement bundle and copy receipt-sidecar dependencies without changing their bytes. Resolve pending adjustment writes before creating final facts. Generate into a private versioned run directory, validate the whole set, then atomically switch a single current-run pointer/index. Refresh compatibility filenames only after the complete set is valid, retaining backups and explicitly reporting partial alias-copy failures. Do not claim multi-file rename atomicity. On source/render failure retain the previous published set; record the failed run separately. Never show old data as freshly retrieved.

This is a user-invoked, finite command. No always-on/scheduled behavior or soak test is introduced.

### G. Existing roadmap and accepted work

The new track delivers this bounded spreadsheet-based report set. It does not complete the legacy Slides/PDF extraction track or paused receipt-boundary/action-queue work. Reuse overlapping board-summary render/export design from Steps 26–31 instead of commissioning a second implementation. Record any exact overlap disposition during plan review; do not mark old acceptance gates complete by implication. Preserve the installed receipt-refresh integration and all existing human annotations.

## 7. Build steps and acceptance

Dispatchable leaves, flags, statuses, and dependencies are in master Phase CFO Steps 57-63 (former CFO aliases are preserved there). Their order is:

1. Inspect and bind actual CFO source tabs; establish source snapshots and normalized transaction contracts.
2. Reconcile transactions and implement immediate, traceable Assumptions adjustments.
3. Implement shared school/calendar-year facts and reimbursement carryovers.
4. Render the five-report set and its period/basis reconciliation bridge.
5. Wire the full end-to-end command and run a small real-component smoke cycle.
6. Regenerate the live report set and reconcile its published figures to the source snapshots.

CFO-0 access and source inspection are complete. The verified bindings above passed scoped plan-review and plan-wrap before issue synchronization. Missing historical coverage is a visible data limitation, not permission to infer zero activity. Live regeneration is a separate bounded operator run after the tools exist, not a hidden requirement inside a code step.

## 8. Risks and open questions

| Item | Risk | Resolution / gate |
|---|---|---|
| CFO workbook permission | Future loss of access could leave reports stale | Access verified; fail clearly and preserve the last valid report set if access is lost. |
| Source schemas and history | Missing months, account coverage, or misread subtotal rows | CFO-1 records observed mappings/coverage and excludes summary rows explicitly; no invented columns. |
| Payout overlap | Double-counted revenue or mismatched fees | CFO-2 ties processor activity to bank movement; ambiguous cases stay unresolved. |
| Existing Assumptions structure | Accidental scenario/formula damage | Inspect used range, snapshot cells, append bounded table, detect concurrent edits. |
| Mixed date bases | Dropped June obligations or misleading P&L comparisons | CFO-3 boundary tests and explicit bridge; queue membership independent of year. |
| Missing expense dates | Unsupported school-year allocation | Visible unallocated-date bucket; preserve original request. |
| Annual budget adapter | Synthetic year-end dates mistaken for monthly evidence | Do not feed `report_source.to_inputs` actual rows into P&L; use dated source transactions. |
| Current private renderer constants | Old totals carried forward into new reports | Move reusable rendering into package code; all figures derived from the captured input set. |
| Partial refresh | Five reports appear current but use mixed runs | Versioned run + one current pointer; hashes, timestamps, and explicit alias failure reporting. |
| Excess testing | Repetition delays user delivery | Target changed contracts and one live report cycle; no repeated unrelated native-PDF/shared-workflow suites for this track. |

Source shape and P&L formula semantics are now verified. Remaining limitations are incomplete historical coverage, ambiguous matching/category cases, and live reconciliation (Step 63). Review and wrap evidence are in docs/plan-reconciliation/cfo-review.md and cfo-wrap.md; Steps 57-62 are implemented and closed.

## 9. Testing strategy

- Focused fictional fixtures cover each observed source shape, changed/reordered rows, legitimate identical records, repeated import, refunds/fees, transfer and payout overlap, and exact-cent conservation.
- Source-specific cases cover WIX row-2 headers with duplicate labels, WIX/PayPal shared provider IDs, PayPal parent/detail rows and partner fees, bank split conservation, exact Internal Transfer exclusion, monthly-category netting versus transaction gross totals, and unknown months displayed as partial coverage. Reproduce source P&L category/month controls before layering our adjustments.
- Date cases include June 30/July 1, December 31/January 1, a June expense paid in July, a cross-year request, missing expense dates, and a prior-year outstanding item. Distinguish source dates from received dates.
- Adjustment tests cover immediate effect, rerun idempotency, reversal/supersession, invalid conflicting corrections, source preservation, existing Assumptions formulas, and concurrent-edit/write failure behavior.
- Exercise the real production CLI with a small captured/fictional source snapshot through normalization, adjustments, facts, templates, and publication. Mock only external transport where necessary; verify financial output, not just function calls. Include a bounded local real-component smoke cycle targeting 60 seconds, excluding interactive authentication and full live receipt fetching.
- Browser/export checks confirm report titles, periods, readable summary layouts, consistent run IDs, receipt access/red marks, and the copy-text companion. Existing human receipt entries and claim amounts must remain unchanged.
- Run lint/type checks for touched package code and relevant config, CLI, report-source, reimbursement, and receipt regressions. Broaden only for a demonstrated shared-contract change or failure. Respect the user's explicit objection to redundant broad reruns; do not repeat unrelated Windows bank-PDF or Firestore suites by default.
- One live CFO-6 run verifies source totals, our adjustment totals, adjusted outputs, school/calendar bridge, preserved carryovers, and all five documents. Record actual discrepancies without forcing zero. No soak/observation campaign is needed for this finite CLI workflow.

Expedited review and issue synchronization are authorized; implementation (Steps 57-62) is complete; live regeneration (Step 63) is the next separate task. This planning run makes no financial writes.

## 10. Build contract and quickstart

These are v0 implementation decisions, accepted under delegated approval during plan-expedite. P&L means profit and loss; CFO means the finance officer maintaining the source workbook. A source view reproduces that workbook's treatment. An adjusted view applies our recorded journal to a copy of that source view.

### Records and identifiers

Define the following immutable records in `main_reports/models.py` (as built, `RunOptions`/`RunResult` live in `main_reports/runner.py`). Persist versioned JSON with sorted keys, UTF-8, decimal money strings and ISO dates; never floats for arithmetic. Money is USD Decimal quantized to cents; unsupported currency or precision is a visible validation error. Optional dates are null, not inferred from email dates.

| Record | Fields and constraints |
|---|---|
| SourceCapture | schema_version=1, source alias, tab ID, captured_at UTC, header signature, rectangular raw values, formula control values, SHA-256, observed first/last dates, declared coverage intervals with evidence, warnings |
| SourceRef | source/account alias, snapshot SHA-256, tab ID, one-based row number, stable record key, revision hash; private workbook binding stays in private config/manifest |
| Transaction | record key, revision hash, SourceRef list, row_role (bank/payment/detail/fee/refund/transfer), native/reference/order IDs, source status, currency, gross/fee/refund/net decimal strings, expense/posting/payment dates, original timestamp and offset, raw/final category, signed allocations, reconciliation state |
| Allocation | source record key and revision, category, signed amount; sum exactly equals its parent bank amount |
| Adjustment | ID, target key/revision list, kind, effective_date, prior_value, replacement_value or signed_amount, category, reason, evidence refs, recorded_at UTC, supersedes ID; exactly one correction representation |
| Discrepancy | stable ID, kind, affected refs, amount if known, coverage/basis impact, explanation, state (unresolved/resolved), resolution evidence |
| Period | basis (school/calendar), start inclusive, end exclusive, as_of inclusive; clip activity to min(end, as_of+one day) |
| ReportFacts | schema_version=1, periods, source totals, adjustments, adjusted totals, reimbursement expense/payment/carryover buckets, adopted budget, fundraising gross/fee/refund/net, monthly category cells, coverage flags and traceable bridge rows |
| RunManifest | schema_version=1, run ID, input-set hash, as_of, code revision, capture refs, adjustment-journal hash, bundle/sidecar hashes, status, artifact relative paths/hashes, alias refresh results, failure codes |
| CaptureSet | source captures keyed by configured source alias, adopted budget rows, Assumptions values/formulas, capture consistency result and aggregate hash |
| Reconciliation | immutable transactions, signed bank allocations, matched source-ref groups, source monthly category cells, discrepancies and coverage flags |
| AdjustedLedger | source reconciliation, active applied adjustment IDs, adjusted allocations/dates/categories, signed source-to-adjusted deltas and discrepancies |
| ArtifactSet | run-relative path, media type, byte length and SHA-256 per HTML/PDF/PNG/text artifact; queue and its copy text are included |
| RunOptions / RunResult | (defined in runner.py) options: as_of date, dry_run bool, optional adjustment file, optional mail window, plus the bundle/source/category-map/anchors/subject-filter/received-cutoff/config inputs shared with update-reimbursements; result: exit code, optional manifest/index path, coverage warnings and alias failures; dry-run has no output paths |

`record_key` is `v1:<source-alias>:<sha256-of-identity>:<occurrence>`. Source alias is a private configured ASCII slug. Identity uses provider/native ID plus row role when available; bank fallback hashes canonical original date, description, amount and check number. Legitimate identical rows retain their multiplicity using a deterministic occurrence index over equal identities; reordering does not collapse them. A revision hash covers all source fields. Do not pretend a changed bank fingerprint is the same transaction: expose added/missing candidates and require an explicit evidence-backed remap for affected adjustments. Bank category changes preserve identity but invalidate an adjustment targeting its old revision. PayPal details include their content hash and occurrence within the parent. Cross-feed matches retain both refs rather than deleting either raw row.

Adjustment IDs are `ADJ-` plus UUID4 hex, created once when a proposal is saved, reused across retries. Discrepancy IDs are `DISC-` plus SHA-256 of kind and sorted affected keys/revisions. Run IDs are `run-<UTC YYYYMMDDTHHMMSSffffffZ>-<UUID4 hex>`; an independent input hash makes identical inputs observable without reusing a directory. These IDs are generated by the new models/helpers and consumed by the journal, facts and manifest. They do not replace reimbursement IDs or receipt fingerprints.

### Source and fact boundaries

`sources.capture(config) -> CaptureSet` captures all seven source/control tabs, our budget and Assumptions once. `sources.normalize(captures) -> tuple[Transaction, ...]` uses source adapters with positional/header signatures; column definitions have one owner in sources.py. `reconcile.build(transactions, controls) -> Reconciliation` returns allocations, matches, source monthly cells and discrepancies. `adjustments.project(reconciliation, journal, as_of) -> AdjustedLedger` applies validated active records once. `facts.build(ledger, bundle, budget, periods, *, captures, crosswalk) -> ReportFacts` is pure; `facts.build_from(capture_set, ledger, bundle, config)` is its production caller (as built, it also verifies the crosswalk digest recorded by reconcile). `render.write(facts, staged_bundle, run_dir, *, context, chromium_path=None, sandbox=..., exporter=None) -> ArtifactSet` and `runner.run(options, config, *, mail_service, exporter, clock, out) -> RunResult` are the production callers, created in their owning steps (signatures as built). Test through these callers, then through the CLI in Step 62; private prototype scripts are not shipping entry points.

Budget cash actuals use the bank basis, with categorized reimbursement expense/obligation information shown separately. A reimbursement item joins a bank payment only with an explicit existing payment/check reference plus corroborating amount and date; ambiguous matches remain unmatched. Use joined item expense dates for an explicitly labeled expense-basis comparison, removing the corresponding bank expense from that comparison before adding item expense. Never add approved claims to bank spending indiscriminately. Reimbursement totals distinguish requested, approved, paid and outstanding states using existing reducers; adjustments never change them. Fundraising processor gross detail enriches reconciled bank categories; unmatched processor activity is separate and marked incomplete. Every report's comparable subtotal names its inclusion/status/date basis so the bridge can prove equality only for identical scopes.

Reconciliation is conservative: exact provider/payment/reference identity plus compatible currency/amount supports processor matches. Bank payouts require a source settlement reference or an explicit recorded match; date/amount proximity alone is a candidate, not a match. Unresolved processor detail cannot inflate CFO bank income. The bank view can still reproduce source controls while processor gross views are labeled incomplete.

### Adjustment writes and concurrent runs

The journal marker is `PTA_REPORT_ADJUSTMENTS_V1`, followed by the column schema above. Locate it uniquely; if absent, reserve a section after the full occupied used range plus two blank rows, after a fresh read. Invalid/duplicate markers fail closed. A later immutable row uses `supersedes` to replace/reverse an earlier entry; do not mutate the earlier row's superseded-by cell. Reject cycles, duplicate IDs with differing payloads, competing active replacements and prior-value/revision mismatches. Apply only entries effective on or before as_of. An additive entry requires independent evidence and cannot serve as an unexplained balancing plug.

Before a write, acquire an exclusive local run lock in the private output root, snapshot exact entered values/formulas, reread the journal and target range, and use targeted RAW cell writes. On uncertain network failure, reread by adjustment ID before retrying. Verify the entire intended journal and preserved pre-existing cells after writing; mismatch stops publication with a conflict and retained before/after evidence. Do not restore the whole live tab automatically. Google Sheets preflight/readback is **not atomic compare-and-swap** against another editor: the remaining read/write race is a stated limitation. Keep journal writes to this CLI writer during a write operation; manual corrections should be new journal rows between runs. An external concurrent edit triggers reconciliation, not an assertion that no overwrite was possible. No new server/locking service is in scope.

Existing journal reads use the captured hash. Proposed writes require explicit `--adjustments-file <private-json-path>`; an ordinary run never invents or writes corrections. The input JSON contains schema_version=1 and an adjustments array of the record above. Source-only runs read the journal but do not create its section. Reporting immediately reflects a valid recorded entry on the next generation; there is no watcher or second approval gate.

### Runtime, failure and publication contract

Use Python >=3.12, uv, existing gspread/google-auth, Jinja2 and Playwright Chromium. Add a `reports` optional dependency extra for runtime Playwright; keep the existing dev browser dependency. No HTTP server, database, API routes or new hosted service is required. A local synchronous CLI with finite network timeouts is sufficient. Reuse retry handling for 429/500/503; set a 20-second HTTP timeout and bounded attempts. The two read-only capture clients use CAPTURE_MAX_RETRIES=7 / CAPTURE_BASE_DELAY_SECONDS=1.0 (126 s of backoff) because one capture issues about 75 reads against a per-minute quota; other commands keep the SheetsClient defaults. Authentication/permission/schema errors do not retry blindly. Retain source freshness and partial coverage labels.

The proposed CLI accepts `--as-of`, `--dry-run`, `--adjustments-file`, and the existing mail window flags `--fetch-since`, `--fetch-until`, `--fetch-query` and `--fetch-limit` (as built; see docs/main-report-set.md). Config stays in gitignored config.toml: new optional `[main_reports]` holds source workbook ID, explicit tab bindings/header signatures, output root, coverage declarations and category crosswalk; credential paths come from `[google]`, own workbook from `[sheets]`, and mail from `[gmail]`. Legacy commands work without main_reports configuration. The new command refuses missing required bindings before side effects. Fake config.example.toml documents all fields; real bindings stay local. Use a separate explicitly readonly CFO client and existing write client only for our journal.

Exit 0 means a validated complete set was published (or dry-run validation succeeded); 1 means an operational failure/conflict, preserving the prior pointer; 2 means invalid arguments/config; 130 means interrupted (recorded as a failed or partially refreshed run). Coverage gaps are disclosed in a successful partial-coverage report, not concealed as zero. Runtime exceptions redact tokens and financial row values from console output; detailed evidence is private. HTML escapes source strings, source content is data, artifact paths are contained within the run root, and exact JSON snapshots preserve formula-like text without evaluating it.

Dry-run failures print the validation error only: no failed-run directory, lock file, snapshot, token or report is written. The ordinary run's private evidence/locking requirements do not override this no-write contract.

Persist captures, normalized records, journal snapshot, facts, discrepancy/bridge records and artifacts beneath `reports/output/main-report-runs/<run-id>/`. One input-set hash covers all captures, journal, bundle, sidecar, config semantics and as_of. Render all outputs from that frozen set; any journal write completes and is recaptured before facts are finalized. Hold the local writer lock through publication; a second writer fails with `run_busy`. Release it in finally; an abandoned lock requires inspecting the recorded PID/run before removing only that lock, not run data.

Publish an atomic replacement of `reports/output/main-report-set.html` containing links to the immutable validated run (the index is the single current pointer). Its prior bytes are retained for recovery. Refresh legacy report filenames after that switch; alias failure is explicit in the manifest and console and returns exit 1 without rolling back a valid authoritative index. A failure before the switch preserves all previously published files. No claim of atomic multi-file aliases is made. Queue bundle/sidecar staging preserves relative image dependencies and their hashes; the live source bundle is not overwritten by report publication. Missing or stale receipt data remains visible or fails validation under existing rules; never fabricate links.

### Quickstart and gates

1. Install: `uv sync --extra dev --extra receipts --extra reports` (see docs/main-report-set.md "Before the first run"). Install Chromium with `uv run playwright install chromium`. Receipt preparation may require the already configured local OCR/PDF tools; retain their existing boundaries.
2. Configure: copy the fake config example only for a new installation; extend the existing private config with inspected main_reports bindings. Keep keys/tokens ignored. Share the CFO workbook read-only with the configured service account; our existing workbook retains only its existing authorized write access. Do not print credential JSON.
3. Develop: use the production Python callers listed above against fictional snapshots; no dev server. Build/package: `uv build`, then smoke the installed wheel to ensure new templates/resources are included. Do not upgrade unrelated dependencies or calibrated Pillow when refreshing the lock.
4. Test: `uv run pytest -q tests/test_main_report_sources.py tests/test_main_report_reconcile.py tests/test_main_report_adjustments.py tests/test_main_report_facts.py tests/test_main_report_render.py tests/test_main_report_runner.py` once those files exist; each step runs only its available focused files plus affected regressions. Lint/format: `uv run ruff check <touched-files>` and `uv run ruff format --check <touched-files>`. Typecheck: `uv run mypy --strict pta_finance`. Report actual suites/counts; broaden only for demonstrated shared-contract risk.
5. First validation after Step 62: `uv run pta-finance end-to-end-run --as-of 2026-10-21 --dry-run`. This is a historical example; select the intended reporting as-of date for a real run. Then run without dry-run for Step 63 and open reports/output/main-report-set.html. No new schedule is introduced. Ctrl+C stops a local run; before pointer publication the last complete report stays available.

No new configuration or CLI named here is claimed to exist before its owning build step. The sole dispatch/status owner is the master. Steps 57-62 are built (2026-10-22); do not re-dispatch them. Step 64 is built (2026-10-23). Step 63 (live acceptance) is in progress; see the master plan live-use record.
