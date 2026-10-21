# Project handoff notes

- Canonical dispatch/status: `docs/plans/master_plan.md`. Execute only an explicitly selected track; never run this multi-track master without phase/step scope.
- Phase CFO plan reviewed, redlined with delegated approval, wrapped, and synced on 2026-10-21. Umbrella #95; code Steps 57–62 map to #96–#101; live acceptance Step 63 maps to #102. Implementation remains unbuilt.
- Supporting contracts: `docs/plan-reference/cfo-main-report-set.md`. Proposal and review/wrap/sync reports are linked from the phase. Existing board/receipt/action tracks keep their own pending, blocked or paused states.
- Future build uses the user's selected Opus Claude Code session; build-phase does not accept a model flag. Reviewer lanes keep their own routing. The automated invocation is `/build-phase --plan docs/plans/master_plan.md --phase CFO --steps 57,58,59,60,61,62`.
- Preserve pre-existing staged documentation migration and unstaged reimbursement/copy-text work. The current working-tree queue implementation includes copy-text changes not present in baseline 243212e. Step 61 must retain/integrate that work when preparing its isolated checkout, not assume a clean HEAD contains it or overwrite the user's changes.
- Use targeted changed-contract verification and one live report cycle for this phase, per the user's explicit testing preference; list exact suites, never claim subset evidence is a full-suite pass.
- Keep financial inputs, identities, credentials, snapshots and reconciliation findings private and gitignored. Public examples and issue bodies remain generic.
