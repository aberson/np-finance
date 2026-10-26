> Supporting historical budget adoption context. Current remaining steps and current editable-tab naming are authoritative in [the master](../plans/master_plan.md). Do not replay historical Sheet mutations.

# FY2027 budget adoption — folding the members' "Pending Approval" expense budget in

> **Status:** Phases 1–3 DONE — Board-approved and APPLIED 2026-07-20 (see Execution log below).
> Phases 4–5 (archive old copies; process close-out) remain. The July tagging follow-up is complete.
>
> **Current naming (October 1, 2026):** the editable source is now `FY2027 - Editable Internal Budget`;
> the former public comparison is `FY2027 - Internal Budget`; a separate `FY2027 - Public Budget`
> follows the legacy share layout. Historical tab names below record the original adoption.
> Sync uses the private `sheets.budget_tab_template` setting; the CLI commands are unchanged.
>
> **Companion (private, gitignored):** `reports/output/fy27-budget-reconciliation.md` holds the real
> amounts, the full line-by-line delta table, and the board's rationale notes. This plan stays
> generic (no org name, no dollar figures) so it is safe on the public repo.

## 1. What this is

non-profit members worked a **copy** of the sheet into an expense-only "Enrichment Emphasis Plan" — now the
`FY27 Pending Approval Expense Budget` tab — with two scenarios (*Initial Deficit* / *Zero Deficit*)
and a written board rationale per line. The **Zero-Deficit column is the proposed budget**: it
applies 18 expense cuts + 2 new lines and turns the projected deficit into a surplus. This plan
adopts that column as the FY2027 proposed budget in the live system, **preserving the rationale
notes** (needed to justify choices to external groups) and **archiving the superseded copies**.

The reconciliation is done and **verified**: the members' *Initial* column equals our current budget
on every mapped line to the penny, so the name-mapping (their informal names → our canonical line
names) is confirmed. See the companion file.

## 2. Inputs and the mechanism this reuses

- **The one live budget tab** is `FY2027 Budget` (editable). It syncs into the `Budget Timeseries`
  database — the single source `report`/`analyze` read — via `uv run np-finance sync-budget --fy 2027`
  (preview) / `--apply`. That tool already: snapshots first, writes only changed amount/notes cells,
  appends new lines, **carries notes through to the database**, never touches actuals/other-years/tags,
  and flags (never deletes) removed lines. This build **reuses that path** — no new tooling required.
- **The name gap is handled by transcribing into canonical names**, not by syncing the members' tab
  directly (their informal names would create duplicate rows). The mapping is in the companion file.
- **The operator guide** `docs/using-the-spreadsheet.md` already documents this exact situation in its
  *"I already edited an old sheet — now what?"* section. This plan is that section, executed.

## 3. Decisions to confirm before Phase 2 (operator/board)

These gate the build; they are enumerated with specifics in the companion file §8:

1. Board has **approved** the Zero-Deficit column as the FY2027 budget.
2. **Fundraising bundle:** the 11 self-funded event lines stay at current amounts (the members
   summarized them as one rounded line marginally low; they proposed no cut to them).
3. **New lines** (two) are confirmed for inclusion.
4. **Home for the adopted budget:** overwrite `FY2027 Budget` in place (Step 2a) **or** stand up a
   distinct approved-budget tab (Step 2b). Recommendation: in place — `FY2027 Budget` *is* the
   proposed-budget tab by design; a second tab reintroduces the copy-drift this system exists to avoid.

---

## Execution log (2026-07-20)

_(Generic — all real amounts and line names live in the private companion file.)_

- **Phase 1 — decisions:** Board approved the Zero-Deficit column. Confirmed: keep the self-funded
  event lines at current amounts; the two new lines filed under their strategic sections; rationale
  notes carried on every line.
- **Phase 2 — transcribe + sync:** snapshotted `FY2027 Budget` + `Budget Timeseries`; transcribed the
  Zero-Deficit amounts + board notes into the existing canonical line names; inserted the two new
  lines *inside* their section `SUM` ranges (the tab total recomputed to the Zero-Deficit figure).
  `sync-budget --fy 2027` preview showed only the expected amount + note changes and the two new
  lines — **zero suspected renames, zero duplicates** — then `--apply`.
- **Phase 3 — notes durable:** verified every FY2027 proposed-expense row in `Budget Timeseries`
  carries its rationale note; net flipped from deficit to surplus (figures in the companion file).
- **Post-adoption dashboard refresh:** tagged the two new lines' `strategic_group` / `strategic_goal`
  (removing a phantom untagged group); recomputed the derived breakdown tables from live data — the
  Spending-by-Goal even-split matrix, the Income & Expense Breakdown color-key + item table, and the
  Year-over-Year + Forecast FY2027 figures — and regenerated the two manual-insert PNGs. QUERY/pivot
  dashboards auto-update.

**Still open:** (a) the `FY27 Strategic Budget` tab still reflects the pre-adoption scenario — refresh
or archive it separately; (b) Phase 4 archive of the old disconnected copies + the members' source tab.

## Execution log (2026-08-18) — member-facing publication

_(Generic — all real amounts live in the sheet, not this repo.)_

- **`FY2027 - Public Budget` tab generated** from the adopted budget: prior-year **actuals**
  (from `Budget Timeseries`) next to the FY2027 **proposed** amounts (from `FY2027 Budget`,
  rationale notes carried verbatim), with per-line deltas, category subtotals, and
  TOTAL INCOME / TOTAL EXPENSE / NET — all native formulas. Every per-fundraiser expense line
  (the cost side of each revenue-generating activity) is combined into one "Fundraising
  Expenses" row per year; a CD + cash reserve line sits outside the totals. Grand totals
  reconcile to `FY2027 Budget` and to the timeseries to the cent (machine-verified before and
  after the write; generation recipe recorded in the project memory).
- This gives members a shareable view without touching the live editable tab — the one-rule
  ("edit only `FY<year> Budget`") is unchanged, and the operator guide's tab table now lists
  the new tab as share-only.

## October 2026 maintenance closeout

The editable source can now be renamed without breaking `sync-budget`: set the optional string
`budget_tab_template` under `[sheets]` in private `config.toml`. The literal `{fy}` token is replaced
with the requested fiscal year. Omitting the setting preserves `FY{fy} Budget`.

- The presentation views distinguish editable allocations, internal analysis, and public sharing.
  The public layout pairs event income and expenses and shows prior-year budget and actuals.
- README, the spreadsheet guide, configuration example, and CLI documentation explain the setting.
- The CLI regression test exercises a renamed source; existing default-name tests still pass.
- Validation: 37 targeted config/budget-sync tests passed; scoped Ruff checks and strict mypy passed;
  live read-only sync reported no changes. This is not a full-suite or Phase 10 completion claim.
- Actual figures, snapshots, PDFs, rendering recipes, and verification records remain private in
  ignored `reports/output/budget-refresh/`. The one-time Sheet mutation scripts must not be replayed.
- Earlier execution logs describe historical layouts. Their combined fundraising expense row and
  dated reserve row are superseded by the current public view; reserves remain separate from the annual plan.

## Original adoption scope exclusions

- **No importer tool for the members' tab.** A one-time transcription through the existing, safe
  `sync-budget` path is cheaper and lower-risk than new code; the long-term fix is editing the live
  tab directly (Step 7), which makes any importer moot.
- **No income changes.** The members' work is expense-only.
- **No direct `Budget Timeseries` hand-edits.** All writes go through `sync-budget` so the snapshot +
  cell-targeted-write safety applies.
