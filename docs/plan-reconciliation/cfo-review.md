Reviewing as: feature plan. Sections 17–21 apply.

Scope: master Phase CFO (Steps 57–63) and its supporting specification. This does not review or release other master tracks. Reviewed 2026-10-21, with autofix and the user's delegated decision authority.

## Blockers

- Resolved: former `### Step CFO-1:` headings were not numeric build-phase headings. The installed build-phase Arguments/Plan document format supports `--phase` and `--steps`, so the master now uses unique Steps 57–63 under Phase CFO. Its handoff selects only 57–62. Original CFO aliases remain visible; discovery is already complete.
- Resolved: `versioned fingerprint and occurrence/multiset policy` and `transaction, source reference, adjustment ... records` lacked concrete shapes and revision semantics. Supporting §10 now defines them, including legitimate duplicate preservation, explicit ambiguous bank edits, and adjustment target revisions.
- Resolved: `snapshot and check for concurrent edits before targeted writes` could imply atomic protection the current client does not provide. §10 distinguishes local serialization, preflight/readback detection and uncertain-write recovery from server-side compare-and-swap. Residual external-edit races are explicit; conflicts stop publication.

## Significant gaps

- Resolved: CFO-2 combined source reconciliation and a live journal writer. These are separate observable behaviors, now Steps 58 and 59, each with its production caller and acceptance.
- Resolved: plain code review on the source-identity, reconciliation, journal, and financial-fact steps was mis-tiered for the blast surface. Steps 57–60 use deep review; publication Step 62 also uses deep review. Trigger owner: installed `review-deep/core.md`, header paragraph (schema/key-shape changes, producer-consumer chains, expensive silent misses). Consider the provider's high-stakes review tier; the plan does not override lens models. Step 61 keeps code review and explicitly requires browser/export evidence.
- Resolved: old board-summary Steps 26–31 overlap this feature. Phase CFO owns shared render/export and the combined runner; the older track must reuse those capabilities and retain only its additional accepted requirements. Existing pending/held statuses are not marked complete.
- Resolved: source-vs-expense facts lacked an explicit double-counting rule. §10 defines separate cash/expense/obligation bases and removes a matched bank payment before including its item expense in an expense-basis view. Unmatched processor detail never inflates CFO bank income.
- Resolved: the previous dry-run wording allowed Gmail token writes. The new command rejects mail-fetch and adjustment-write combinations before authentication and does not invoke Gmail during dry-run.

## Missing items

- Auto-applied per-step Files and Existing context fields to all seven pending steps.
- Added install/dev/build/test/lint/typecheck commands, runtime reports extra ownership, and wheel resource validation. Playwright currently lives in the dev extra; a new runtime exporter must not depend on an undeclared dev-only package.
- Added input-set hashing, CLI exits, local lock, bounded capture retries, immutable runs and authoritative HTML-index publication. Alias-copy failure is explicitly distinct from failure before publication.
- Added exact journal append/supersession conventions, proposed-adjustments input, record IDs, production seam signatures, config loading and no-write normal operation.

## Nice-to-haves

None. No additional platform, accounting service, scheduler, or test campaign is proposed.

## Evidence and complete checklist

| Check | Result / primary evidence |
|---|---|
| 1 Persistence | Versioned private JSON captures/manifests; live append-only Assumptions journal; §10 defines corruption/conflict behavior. Existing typed backup producer: `pta_finance/backup.py:266`, `:372`. |
| 2 Integrations | Google Sheets, existing optional Gmail, Chromium; scopes, failure/retry and capture stability specified. `pta_finance/sheets.py:179`, `:224`; CLI fetch flags at `pta_finance/cli.py:1719`, `:1726`. |
| 3 Secrets/auth | Existing config paths and separate readonly CFO client; `pta_finance/config.py:84`, `:195`; default `SheetsClient.connect` calls service_account without readonly scope, so reuse requires an explicitly scoped injected client. |
| 4 Concurrency | Finite synchronous CLI; local lock and Sheets race limitations explicit. No background job status service needed. |
| 5 Failure feedback | §10 defines exit codes, private error evidence, stale/partial coverage and alias-copy status. |
| 6 Toolchain | All six command classes documented in §10; `pyproject.toml` declares Python >=3.12, hatchling, uv-compatible dependencies and CLI entry. |
| 7 Unresolved decisions | Former proposed structures resolved in §10. Optional arguments are deliberate parameters, not unresolved choices. Missing coverage/matches remain data findings, not architecture TBDs. |
| 8 Setup | Existing private config is extended, never replaced; explicit runtime extra/browser setup and auth sharing requirements. |
| 9 Idempotency | Source multiset/revisions, adjustment IDs and uncertain-write reread; same inputs are hash-identifiable. |
| 10 Seams | Typed records, pure projections and production callers defined in §10. Dependency direction sources -> reconciliation -> adjustments -> facts -> render -> runner. |
| 11 Scope | Reuse existing queue/receipt implementation; no provider APIs, scheduler, payments or new service. |
| 12 Security | Source strings escaped, formula-safe snapshots, contained artifact paths, private output; external source content is data. Existing public report guard remains separate. |
| 13 Tests | §9/§10 and step acceptance cover financially consequential edge cases and failure preservation with fictional source fixtures. |
| 14 Operations | Start, stop, lock recovery, rollback and publication described; user-invoked command only. |
| 15 Full-system observation | Step 63 is one live source-to-report observation; no time-dependent background system to soak. |
| 15.5 Smoke | Step 62 wires real production adapters/facts/renderers/publication through CLI; local fixture target 60 seconds. Step 61 checks installed-wheel template resources. |
| 16 Clean context | Inline source shapes, new schemas, IDs, quickstart and boundaries added; plan-wrap follows. |
| 17 Existing code | `report_source.py:101` reads annual budget data; `:149` projects annual actuals. `reimbursement_pipeline.py:1947` plans refresh; `reimbursement_report.py:1660` renders queue and `:1665` copy text. `cli.py:1082` owns existing update; search found no end-to-end-run command. New paths are explicitly proposed. |
| 18 Impact | Config loader/callers, CLI, source projections, templates, tests and runtime dependency packaging are named. Reimbursement wire schema, IDs and fingerprints remain unchanged. |
| 19 Conflicts/conventions | Master-only dispatch retained. Existing board/receipt/action lanes separated. `git worktree list` shows preserved old candidates; no recent commit in the last hour at review. Dirty pre-existing migration/code work is outside review scope. Public identity rule in CLAUDE.md applies to all fixtures and issue bodies. |
| 20 Context sufficiency | Each step now describes its existing producer and intended caller; full contracts accompany the phase. |
| 21 Sizing | Six code slices, with reconciliation/journal separated; one live operator step. Rendering is one cohesive fact-to-report-set behavior and runner owns publication. |
| 22 Step type | Code acceptance is mechanical/agent-executable. Step 63 produces private observation artifacts, not code or a new ops guide. |
| 23 Conditions | N/A: no conditional steps in Phase CFO. |
| 24 Reviewer runtime | No full/runtime flags requiring start-cmd/URL. Static HTML browser checks are explicit acceptance for Step 61. |
| 25 Parseability | Seven unique numeric headings, each with Problem/Type/Issue; blank Issue fields expected before sync. |
| 26 Substrate | Step 63 exercises actual Sheets/authentication/local CLI/browser rather than inferring live success from fixtures. |
| 27 Stakes | Deep routing on financial identity/journal/facts/publication; ordinary render review remains scoped. No model override invented. |
| Control plane | Master has What This Is/objective and inline numeric statuses; no new server ports. |

Auto-applied 11 fixes: seven missing Files lists; four plain-code-to-deep reviewer substitutions (57, 58, 59, 60; Step 59 was split from former CFO-2). Additional design edits above use the user's explicit delegated judgment, including deep routing for Step 62, seven context summaries, parser-safe scope, and the record/runtime contract.

0 items need your input. Targeted source inspection and plan checks only; no application tests or live financial mutations were needed for this documentation review.

Verdict: READY for Phase CFO. Redline approval and plan-wrap precede issue sync.
