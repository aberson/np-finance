# Phase CFO issue synchronization

Target: `aberson/pta_finance`, default branch `main`, verified with `gh repo view`. Scope: master Phase CFO only; review and wrap evidence are in `cfo-review.md` and `cfo-wrap.md`. Redline D1–D7 were accepted under the user's explicit delegated authority before synchronization.

Footer shapes recognized:

```text
Create: Synced from [<plan>](...)
Enrich: Enriched by /repo-sync from <build-doc-path> @ <sha>
```

Fetched all 93 existing issues (open and closed); none matched Phase CFO. No cross-plan collision or existing CFO issue to classify. No unrelated issue was mutated.

Preview executed: CREATE one umbrella and seven step issues; ENRICH 0, UPDATE existing steps 0, CLOSE 0. All seven steps have explicit Files, Existing context, Done when, Produces and Depends on; six code steps also declare reviewer flags. The operator step intentionally has no build-step flag. Every issue declares sequential dependencies with a reason, and includes the shared record/runtime contract.

| Master unit | Issue | Type |
|---|---|---|
| Phase CFO | [#95](https://github.com/aberson/pta_finance/issues/95) | Umbrella |
| 57 / CFO-1 | [#96](https://github.com/aberson/pta_finance/issues/96) | code |
| 58 / CFO-2 reconciliation | [#97](https://github.com/aberson/pta_finance/issues/97) | code |
| 59 / CFO-2 adjustments | [#98](https://github.com/aberson/pta_finance/issues/98) | code |
| 60 / CFO-3 | [#99](https://github.com/aberson/pta_finance/issues/99) | code |
| 61 / CFO-4 | [#100](https://github.com/aberson/pta_finance/issues/100) | code |
| 62 / CFO-5 | [#101](https://github.com/aberson/pta_finance/issues/101) | code |
| 63 / CFO-6 | [#102](https://github.com/aberson/pta_finance/issues/102) | operator |

Umbrella re-edited with all seven actual issue numbers. The orchestrator backfilled all seven master Issue fields. Source footer records baseline `243212e`; issues describe planned work, not implementation completion. No private workbook identifiers, account addresses, transaction samples or financial results were sent to GitHub.

Next: `/build-phase --plan docs/plans/master_plan.md --phase CFO --steps 57,58,59,60,61,62` — run in `C:\Users\abero\dev\pta_finance` in an Opus Claude Code session. Step 63 is separate live acceptance. Preserve existing dirty work and paused worktrees; this synchronization does not release other tracks.

Plan pipeline: /plan-review + /plan-redline (delegated approval) + /plan-wrap → /repo-sync (step 4 of 5) → /build-phase
