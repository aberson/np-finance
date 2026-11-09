[!] Detected non-blank Issue fields — repo-sync appears to have already run. Findings applied to plan.md will require corresponding `gh issue edit` updates (N+1 rework). See `.claude/references/plan-and-issue-flow.md` § Order.
Reviewing as: feature plan. Sections 17–21 apply.

Plan: `docs/plans/master_plan.md`, Phase CORE-BRIEFS only, Steps 65-69.
Date: 2026-11-04. Independence: same-session review, not an independent judgment.
The warning concerns existing unrelated master-plan issues. New Steps 65-69 have blank issue fields; no existing issue body needs changing for this addition.

## Evidence and check coverage

| Check | Result / evidence |
|---|---|
| 1 Data persistence | Pass: optional captured planning envelope, immutable runs, stored verification and compatibility/backout contract. |
| 2 External dependencies | Pass: existing two configured workbooks/read-only clients, bounded capture retry; no new dependency. `sources.py:1216,1242` and `pyproject.toml`. |
| 3 Authentication/secrets | Pass: existing service account; no credential contents, permissions or workbook IDs published. |
| 4 Concurrency | Pass: reuse runner lock and source consistency checks; include new private input in before/after checks. |
| 5 Error feedback | Pass: absent/partial inputs differ from invalid configured data; source findings on pages, previous complete publication retained on pre-switch failure. |
| 6 Toolchain | Pass: install, browser setup, CLI development, `uv build`, pytest, Ruff and mypy all specified; no dev server. `pyproject.toml` and CLI parser. |
| 7 Decisions | Pass: operator choices and labeled defaults enumerated; real roster is a live-acceptance prerequisite, not an undefined implementation branch. |
| 8 Setup | Pass: private input schema, workbook role/bindings, credential loading, dry-run then ordinary command. |
| 9 Deduplication | Pass: source identities/revisions, explicit shared-payment allocations, no amount-only matches, repeat-run verification. `models.py:290` owns existing record-key generation. |
| 10 Seams | Pass: config -> capture -> planning/facts -> renderer -> runner; hashes include supplemental data; no extra normalized bank feed. |
| 11 Scope | Pass: two report additions only; no dashboard, scheduler or broad reconciliation replacement. |
| 12 Security | Pass: private data boundary, exact configured inputs, autoescaped templates, offline exports and fake-only fixtures. |
| 13 Tests | Pass: Decimal arithmetic cases, old/new wire shapes, failure injection, report/export and production-caller tests. |
| 14 Operations | Pass: ordinary CLI, no-write dry-run, Ctrl+C behavior, retained old runs/backout and explicit alias-copy partial failure. |
| 15 End-to-end observation | Pass: one-shot workflow; Step 69 observes an actual run. No continuous-service claim or soak requirement. |
| 15.5 Pipeline smoke | Pass: Step 68 real parsers/facts/templates/Chromium/publication, existing bounded CLI test; external fake transport is disclosed. |
| 16 Clean context | Pass: schema, identities, formulas, dependencies, quickstart, missing-data behavior and financial acceptance supplied inline. |
| 17 Source claims | Pass: paths verified; `_load_main_reports`, `_capture_budget`, `_verify_stored`, `store_capture_set`, `build_from` and render/runner registries read. No claimed pre-existing typed capture loader. |
| 18 Consumers | Pass: search roots/exclusions and affected config, capture, reconciliation, facts, render, runner, fixtures, CI and docs recorded. |
| 19 Conflicts | Pass: tracked tree clean at baseline; unrelated `.build-step/` preserved; no renumbered leaves; existing Step 63 and F16/F17 acceptance not absorbed. |
| 20 Context | Pass: shared templates and publication architecture summarized, not merely named. |
| 21 Step size | Pass: capture through CLI, classroom publication, obligations publication, regression/operations proof, then attended acceptance. No isolated helper-only delivery step. |
| 22 Operator/code shape | Pass: Steps 65-68 automate implementation/mechanical checks; Step 69 records human/source acceptance, not shipped code. |
| 23 Conditional predicates | N/A: no conditional step. |
| 24 Reviewer flags | Pass: `--reviewers deep` is supported and requires no runtime URL; existing offline browser tests cover rendering. |
| 25 Parseable steps | Pass: unique numeric IDs and required fields checked by script; blank issues are expected before sync. |
| 26 Live substrate | Pass: Step 69 observes actual Sheets and the installed CLI on private sources. |
| 27 Stakes routing | Pass: schema, financial identities and publication changes already select deep review. No escalation edit needed. |

## Blockers

None.

## Significant gaps

None requiring a planning decision. Source completeness and the actual roster remain explicit live-acceptance prerequisites, not assumed successes.

## Missing items

None. New module/templates/test are explicitly marked as implementation outputs.

## Nice-to-haves

None. Publish issues only for this phase before build; existing unrelated issue IDs remain unchanged.

## Final design and central-case review

Rechecked the accepted design changes and production contracts in this session. Central case uses prior-year classroom utilization and the accepted prior-dollar fundraising benchmark, with future event income included once and a received-plus-event floor. Explicit policy fields cover category joins, confirmed event dates, prepaid costs, incompatible receipts, missing historical denominators and the specialist contract exclusion. Total sans SP is a subtotal, not another expense. Concise copy preserves central assumptions and material findings; source details stay in audit records. Four baseline/central scenario calculations are separately serialized and independently tested.

Current source evidence: `np_finance/main_reports/sources.py:1139` retains only proposed budget rows, so supplemental prior actual capture remains necessary; `sources.py:537` requires existing source kinds, so the new envelope stays optional. `models.py:595` serializes CaptureSet; `facts.py:1358` is the real facts caller; `runner.py:1148` wires capture through validation; `render.py:119` currently lists four summary exports. `tests/test_main_report_runner.py:1634` supplies the existing real Chromium CLI smoke. Paths for existing modules/tests were checked; new planning module/templates/tests are absent and explicitly marked new. No new package, API, scheduled process, or port is introduced. No other worktree changed during this review.

Decision scan: missing enrollment/rates, confirmed event dates and private mappings are explicit Step 69 source prerequisites, not unchosen implementation behavior. Optional/null fields have specified unavailable behavior. Blank Issue fields in Steps 65-69 are expected before repo-sync. No bare implementation TBD, conditional predicate or runtime-review flag omission remains.

Blockers: none. Significant gaps: none. Missing items: none. Nice-to-haves: none.

## Appendix amendment recheck

The operator added three summary rows per column and two complete appendix pages after initial sync. Re-ran all applicable review checks against the changed scope. The accepted presentation now specifies nine named rows plus Other, a one-page summary, complete paid and remaining lists on separate portrait pages, exact totals and signed nonzero detail coverage. Step 67 explicitly requires the three-page fundraising PDF; Step 69 confirms page 1 remains the summary. The existing exporter (`np_finance/main_reports/export.py:_render`) prints the complete HTML document, and the existing report family already supports appendices; no separate exporter, data read or report registration is needed. Layout and detail-coverage regressions are required through the real runner. Source/schema/code evidence above remains unchanged. Existing issues require UPDATE, not duplicate creation. No blocker, significant gap, missing item or new implementation choice.

Verdict: READY

Auto-applied 0 fixes. Plan is ready for `/plan-redline`, then `/plan-wrap` and `/repo-sync`.
