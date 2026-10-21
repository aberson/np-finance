# Plan merge overlap and disposition

Spine: root roadmap supplies project-wide authority; concrete scoped contracts replace overlapping summaries. User approved routine deduplication, sequencing and reference repair. Existing architecture holds remain.

#### Plan: plan.md
- Vision / goal: pta_finance — Plan (v1)
- Phase list: 1: Scaffold + tooling + config + IDs; 2: Sheet schema + entity models; 3: Sheets client + backup; 4: ETL / normalize; 5: Analytics engine; 6: Report generation (internal + external); 7: End-to-end smoke gate (code); 8: GitHub Actions monthly report workflow; M1: Google Cloud + service-account setup; M2: Real-sheet smoke (round-trip); M3: Monthly-report observation run (end-to-end)
- Data contracts: Identifiers; Tab column lists (single source of truth → `schema.py`); Private config schema (`config.toml`, gitignored — `config.example.toml` ships fake values)
- External dependencies: none; 1; 2; 3; 4; 5; 6; 7; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/plan.md](../archived-plans/plan.md).

#### Plan: documentation/fy27-budget-adoption-plan.md
- Vision / goal: FY2027 budget adoption — folding the members' "Pending Approval" expense budget in
- Phase list: 1: Confirm the four decisions in §3; 2: Transcribe the Zero-Deficit amounts + rationale into `FY2027 Budget`; 3: Preview the sync (writes nothing); 4: Apply the sync; 5: Confirm notes reached the database; 6: Retire the disconnected budget tabs; 7: Point future edits at the one live tab
- Data contracts: Exact source schemas/algorithms retained in archive; active contracts linked from master.
- External dependencies: (none found); existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__fy27-budget-adoption-plan.md](../archived-plans/documentation__fy27-budget-adoption-plan.md).

#### Plan: documentation/gmail-ingest-plan.md
- Vision / goal: Gmail read-only ingest connector — feature plan
- Phase list: 9: Gmail OAuth client + pinned read-only scope; 10: `fetch-mail` command + idempotent `.eml` writer; M4: Google Cloud OAuth client + one-time consent (operator); M5: Refresh-token longevity check (wait); 11: End-to-end smoke gate — fetch → ingest → map (operator); 12: Full backfill from the board cut-over + reconciliation (operator); 13: Docs + plan reconciliation
- Data contracts: Exact source schemas/algorithms retained in archive; active contracts linked from master.
- External dependencies: none; 9; 10 — the `Done when:` invokes `fetch-mail`, which Step 10 creates; depending on Step 9 alone would dispatch this step before the command exists.; M4; 10, M4; 11; 12; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__gmail-ingest-plan.md](../archived-plans/documentation__gmail-ingest-plan.md).

#### Plan: documentation/non-reimbursement-action-queue-plan.md
- Vision / goal: Non-reimbursement action queue — Phase 10 feature plan
- Phase list: 51: Propose actions from archived mail; 52: Preserve operator decisions across refreshes; 53: Render the private action queue; 54: Surface actions in the reimbursement end-to-end run; 55: Real-component archive-to-report smoke gate; 56: Attended private-archive acceptance
- Data contracts: Exact source schemas/algorithms retained in archive; active contracts linked from master.
- External dependencies: Phase 9 Step 38 / #72; 51; 52; 53; 54; 55; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__non-reimbursement-action-queue-plan.md](../archived-plans/documentation__non-reimbursement-action-queue-plan.md).

#### Plan: documentation/receipt-autofill-plan.md
- Vision / goal: Automatic source-receipt filling in the reimbursement refresh
- Phase list: 38: Repair the red CI browser gate; 39: Shared page geometry and deterministic normalization; 40: Allowlisted asset fetcher with a content-addressed cache; 41: LPAC render spike — prove glyphs actually rasterize; 42: Record the PDF-boundary decision when the LPAC render path is blocked; 43: Render protocol across the attested boundary; 44: PDF assets become display pages; 45: Provenance, the unambiguity gate, and the sidecar merge; 46: The refresh stage, config block, and `link-receipts` verbs; 47: Integration through the production caller; 48: Documentation, policy amendments, and the full-suite gate; 49: Attended run against the real private evidence (M9)
- Data contracts: The proposals document, specified; `[receipt_assets]` config block; Module signatures; Identifiers
- External dependencies: none; 38; 41; 41, 42; 39, 43; 40, 44; 45; 46; 47; 48; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__receipt-autofill-plan.md](../archived-plans/documentation__receipt-autofill-plan.md).

#### Plan: documentation/reimbursement-board-summary-plan.md
- Vision / goal: Phase 6 — Monthly reimbursement board summary — Python workflow
- Phase list: 26: Prepare a dated summary review packet; 27: Render the accepted one-page HTML design; 28: Preserve an approved one-page export; 29: Provide the monthly Python runner; 30: Exercise one complete real-component cycle; 31: Accept the workflow on the treasurer's Windows machine
- Data contracts: Source contract used by this feature; New private files, schema version 1
- External dependencies: none.; Step 26.; Step 27.; Step 28.; Step 29.; Step 30.; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__reimbursement-board-summary-plan.md](../archived-plans/documentation__reimbursement-board-summary-plan.md).

#### Plan: documentation/reimbursement-refresh-plan.md
- Vision / goal: Reimbursement refresh pipeline plan
- Phase list: 1: Add the validated reimbursement report model and renderer; 2: Add local evidence preparation and the three-stage command surface; 3: Migrate and compare the current private report bundle; 4: Document and run the operator smoke gate; 5: Add supplemental email evidence and scoped lifecycle events; 6: Verify the live end-to-end supplemental flow
- Data contracts: Exact source schemas/algorithms retained in archive; active contracts linked from master.
- External dependencies: none; Step 1; Steps 1 and 2; Step 3; Steps 1 through 4; Step 5; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__reimbursement-refresh-plan.md](../archived-plans/documentation__reimbursement-refresh-plan.md).

#### Plan: documentation/shared-request-queue-plan.md
- Vision / goal: Phase 8 — Live shared request queue
- Phase list: 36: Work through a fixed shared request queue; 37: Accept the live shared queue with both accounts
- Data contracts: D2 — Preserve each request's storage contract
- External dependencies: 35 (external prerequisite in the proof plan; all M7 rows and operator acceptance must be recorded DONE).; 36.; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__shared-request-queue-plan.md](../archived-plans/documentation__shared-request-queue-plan.md).

#### Plan: documentation/shared-workflow-proof-plan.md
- Vision / goal: Shared workflow proof plan
- Phase list: 32: Make the fictional request available for authenticated shared comments; 33: Prove two independent Google users share durable state on Cloud Run; 34: Enforce the reviewer-to-processor handoff; 35: Accept the two-role handoff on the deployed service
- Data contracts: D5 — Small same-origin API and browser behavior
- External dependencies: none; review and issue synchronization prerequisites apply.; 32; 33; 34; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: completed; all32-35 and actualM6/M7 accepted; [docs/completed/documentation__shared-workflow-proof-plan.md](../completed/documentation__shared-workflow-proof-plan.md).

#### Plan: documentation/treasurer-slides-plan.md
- Vision / goal: Treasurer Slides staged roadmap
- Phase list: Why the build is staged; Global step ranges; Wave 1 - Summary slide; Wave 2 - Core financial story; Wave 3 - Operational rigor; Wave 4+ - Capability slices; Cross-wave invariants; Plan and issue transition
- Data contracts: Exact source schemas/algorithms retained in archive; active contracts linked from master.
- External dependencies: (none found); existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__treasurer-slides-plan.md](../archived-plans/documentation__treasurer-slides-plan.md).

#### Plan: documentation/treasurer-summary-wave-1-plan.md
- Vision / goal: Phase 5.1, Wave 1 - Treasurer summary Google Slide - feature plan
- Phase list: 14: Define private manifests and normalized finance contracts; 15: Parse supported native-text statement pages inside the pre-read LPAC boundary; 16: Add bounded positional Tesseract fallback; 17: Select authoritative activity and balance intervals; 18: Classify, pair, adjust, and reconcile signed cash; 19: Read adopted goals and build deterministic summary facts; 20: Encode the approved one-slide and template contract; 21: Create immutable runs and transaction-level fact/slide review; 22: Add exact-scope OAuth and recoverable template bootstrap; 23: Copy and populate one approved candidate idempotently; 24: Wire CLI, privacy gates, packaging, docs, and local smoke; 25: Run the private source-to-Google acceptance
- Data contracts: 5.1 Optional configuration; 5.7 Approved summary and template contract; Unit and contract tests
- External dependencies: none; Step 14; Step 15; Step 16; Step 17; Step 18; Step 19; Step 20; Step 21; Step 22; Step 23; Step 24; existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__treasurer-summary-wave-1-plan.md](../archived-plans/documentation__treasurer-summary-wave-1-plan.md).

#### Plan: documentation/shared-ticket-lifecycle-design.md
- Vision / goal: Ticket creation and lifecycle rules
- Phase list: 1. Create, read, update and delete; 2. State and permission rules; 3. New ticket form; 4. History and concurrency; 5. Implementation boundary; 6. Acceptance scenarios for that plan
- Data contracts: Exact source schemas/algorithms retained in archive; active contracts linked from master.
- External dependencies: (none found); existing Python/uv and explicitly described private/Google/operator prerequisites remain.
- Kill criteria and rollbacks: Fail closed on invalid evidence, privacy boundary violation or missing required acceptance; preserve prior outputs/history and source-specific backups. No automatic reset. Original source retains its exact limits.
- Disposition: merged; source requirements mapped into master leaves and supporting contracts; [docs/archived-plans/documentation__shared-ticket-lifecycle-design.md](../archived-plans/documentation__shared-ticket-lifecycle-design.md).

## Overlaps and resolutions

- [PATTERN: same-goal-different-fidelity] Root phases5-10 describe the same work as scoped plans. Detailed leaf acceptance replaces duplicate summaries; source contracts retained, not duplicate dispatch.
- [PATTERN: implicit-prerequisites] Receipt39/41/43 and Slides16 share Job wrapper and native parser. Use the shipped process_limits wrapper, rebase second landing and run both native suites.
- [PATTERN: implicit-prerequisites] Receipt46/actions54/board29 share CLI refresh. Preserve refresh -> fill -> report -> actions and runner stop-on-first-failure; board29 forwards no-fill option.
- [PATTERN: conflicting-invariants] Root stale receipt39 BLOCKED conflicts with later39/40 DONE and41 BLOCKED. Latest per-step execution records win; do not restore old worktree instructions or infer PDF fallback from execution halt.
- [PATTERN: conflicting-invariants] Staged Slides roadmap provisional26-35 collides with later assigned board/shared issues. Preserve global16-56 assignments; use W2/W3/W4 symbolic deferred IDs, never duplicate numeric queue.
- [PATTERN: same-data-different-schema] Private reimbursement schema, summary frozen run schema and hosted workflow state are separate consumers with different authority. Preserve each; do not unify payment and administrative completion.
- [PATTERN: same-goal-different-fidelity] Queue lifecycle product design expands root future admin direction. Retain LIFECYCLE behind37/M8 with all8 acceptance scenarios; broader UI remains deferred, no architecture picked.

## Source self-inconsistency

Receipt root Phase9 resume39 would undo later completed39/40 status; use latest scoped statuses. Shared proof footer still says34/35 pending while their own step andM7 acceptance blocks say DONE; dated accepted closeout wins. Refresh completion1-6 does not erase later payment replay defects; REPLAY1-3 remain pending. Budget older tab descriptions do not override current configured editable source; no historical mutation script replay. Source-local section numbers resolve in named supporting contracts, not arbitrary master sections.

## Scope exception

The ignored doc/ tree contains private application input, not public project documentation. Preserve it in place to avoid breaking private manifests or exposing identities. No private filenames/content enter this report. All public documentation/ content moved to docs/. No source original was modified after archive; SHA256 verification covers all12.
