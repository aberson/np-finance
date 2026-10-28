# Main Report Set guide

`np-finance end-to-end-run` produces the whole private report set from one captured set of
inputs:

| Report | Period | Files |
|---|---|---|
| Reimbursement Queue | every open request, prior-year carryovers included | HTML + copy text |
| Reimbursement Summary | school year (July 1–June 30) through the as-of date | HTML, PDF, PNG |
| Budget Snapshot | school year | HTML, PDF, PNG |
| Fundraising Summary | school year | HTML, PDF, PNG |
| CFO P&L Summary | calendar year (January 1–December 31) | HTML, PDF, PNG |

Each summary is a one-page board brief (the P&L adds a landscape appendix) that names its
period, basis, as-of date, run ID, input-set hash, when the inputs were captured, and counts of
adjustments, discrepancies and findings with pointers to the run's `records/*.json`. The index
adds per-source freshness and coverage. Layout contract:
[main-report-design.md](plan-reference/main-report-design.md). The supporting design is in the
[Main Report Set specification](plan-reference/cfo-main-report-set.md); the
[master plan](plans/master_plan.md) owns status.

## Before the first run

1. Install the toolkit with the browser export:

   ```powershell
   uv sync --extra dev --extra receipts --extra reports
   uv run playwright install chromium
   ```

   On Linux, use `uv run playwright install --with-deps chromium` to include Chromium
   system dependencies and the Liberation Sans font. Summaries use Arial on Windows and
   its compatible Liberation Sans fallback on Linux for stable one-page layout.

2. Add a `[main_reports]` section to your private `config.toml`. The commented example in
   `config.example.toml` lists every field: the CFO workbook ID, one binding per source tab
   with its exact header rows, declared coverage with its evidence, the category crosswalk,
   and `output_dir`. Keep `output_dir` a subfolder of `reports/output/` (the default is
   `reports/output/main-report-runs`) or a folder outside the project. The current-run page
   and the compatibility copies are written to the folder above it, which must pass the same
   check: inside the project it must also be under `reports/output/`. Outside the project the
   parent is your choice, so give the runs folder a dedicated private parent (not a drive
   root or a synced folder), because 17 fixed-name files are written there.
3. Share the CFO workbook **read-only** with the service account. The command reads it through
   a separate read-only client and never writes to it. Your own workbook keeps its existing
   access; only the optional adjustments journal is ever written there.
4. Complete the reimbursement setup in the [receipt guide](loading-receipts.md): a category map,
   the private review bundle and, optionally, Gmail access and `[receipt_refresh]`.

## Check first: dry run

```powershell
uv run np-finance end-to-end-run --as-of 2030-08-15 --dry-run
```

A dry run reads and validates the live Sheets, the existing reimbursement evidence and the
adjustments journal, plans the reimbursement refresh and builds every figure. It does not
exercise staging, rendering or publication, so it cannot predict a failure there. It writes
**nothing**: no run folder, lock, capture, snapshot, token, bundle, report or Sheets cell. It
refuses `--fetch-*` and `--adjustments-file`, because both of those write. A dry run that
fails prints a code (or, for an unexpected error, only its type name) and exits `1`; Ctrl+C
exits `130`. Neither writes a failure record. Reading the
service-account key file is its only local access beyond the inputs it checks.

### Confirm on the first live run

The adapters were built and tested against fictional workbooks. On the first real dry run,
check these assumptions; each one fails visibly (an unverified control, a discrepancy, or a
row issue) rather than producing a silent wrong total:

- The published P&L tab has a month header row with categories in the first column, and
  months with no activity show either `0` or a dash over an entered zero.
- Posted bank rows use the status `Posted`; other statuses are reported as not posted.
- Processor fees are signed the same way in the WIX and PayPal tabs (negative amounts).
- The bank, WIX and PayPal header labels resolve to the defaults. Padded labels (` AMOUNT `),
  WIX date labels with a time-zone suffix (`Payment Date GMT -07:00`), the WIX product column
  `Name` under `Products or Services`, and a unique `Transaction Status` label are recognized
  without overrides; any other label needs a `columns` override in your private
  `[main_reports]` config. WIX timestamps (`M/D/YYYY, H:MM:SS AM`) are dated as the export
  shows them: the offset in the label is not applied.
- PayPal `POS Payment` rows are incoming sales; any other unrecognized PayPal type (for
  example `Mass Pay Payment`) is listed as an `unknown_type` warning for review.
- A bank split in FINAL CATEGORY whose amounts do not add up to the bank amount is published,
  not halted: the gap appears as an explicit `Unallocated split difference` line with a
  `split_sum_mismatch` warning (an unreadable split or a dash amount still stops the run).

## Run and publish

```powershell
uv run np-finance end-to-end-run --as-of 2030-08-15
```

Then open `reports/output/main-report-set.html`.

Optional flags:

| Flag | Effect |
|---|---|
| `--fetch-since YYYY-MM-DD` (`--fetch-until`, `--fetch-query`, `--fetch-limit`) | Fetch a Gmail window first, with the same read-only connector and window rules as `update-reimbursements`. `--fetch-until` is exclusive. |
| `--adjustments-file PATH` | Record the adjustments in this private JSON file in the Assumptions journal before building the reports (see below). |
| `--source`, `--data`, `--category-map`, `--anchors`, `--subject-filter`, `--received-since` / `--all-received` | The same reimbursement inputs as `update-reimbursements`, with the same defaults. |

One run, in order:

1. takes a local lock, so a second run started meanwhile stops with `run_busy`;
2. captures every bound CFO tab, your adopted budget and Assumptions once, and checks that
   nothing changed while reading (the whole capture is retried once, then stops);
3. fetches mail if asked, refreshes the reimbursement bundle and prepares receipts exactly as
   `update-reimbursements` does (it does not write the queue HTML yet);
4. records adjustments only if `--adjustments-file` was given, then captures again so the
   reports read the journal as it now stands;
5. copies the bundle, its receipt sidecar and every receipt page unchanged into the run's own
   `inputs/` folder and builds every report from that copy into a new run folder;
6. checks the complete set, writes `run-manifest.json`, and only then replaces the current-run
   page and refreshes the compatibility copies.

The command never extracts bank PDFs, sends mail, schedules anything or writes to the CFO
workbook. Exit codes: `0` published (or dry run validated), `1` operational failure, `2`
invalid arguments or configuration. Console messages name stages, codes and counts, never
amounts, cell contents or workbook IDs (local file paths can appear).

## Where things are

Under `reports/output/` (private and excluded from Git):

| Path | What it is |
|---|---|
| `main-report-set.html` | The single current-run page. It names the published run and links to its files. It is replaced in one step. |
| `main-report-runs/<run-id>/` | One immutable run: the five reports and exports, its own index, `inputs/`, `records/` (facts, reconciliation, adjusted ledger, journal) and `run-manifest.json`. |
| `main-report-runs/captures/` | Content-addressed source captures. Identical inputs are stored once. |
| `main-report-runs/adjustments/` | Pre-write Assumptions snapshots and readback evidence from journal writes. |
| `main-report-runs/failed-runs/` | One record per failed run: its stage code, without values. |
| Compatibility copies | The run's reports under their usual names beside the current-run page, plus the queue as `reimbursement-queue-breakdown.html` and its copy text. |

The manifest lists the input-set hash, the capture and journal hashes, the bundle, sidecar and
receipt-page hashes, the code revision, every artifact with its size and hash, the adjustments
written or already recorded, coverage warnings and each compatibility copy's refresh result.
Identical inputs give an identical input-set hash, in a new run folder.

## When something fails

- **Before publication** (capture, mail, refresh, adjustments, facts, rendering or the final
  check): the current-run page and every compatibility copy stay exactly as they were. The
  run is recorded in `main-report-runs/failed-runs/<run-id>.json` and its folder's
  `run-manifest.json` is marked `failed`, so it is never mistaken for a complete set. The
  record names the stage and a code; for an unexpected error it names only the error type,
  never its text. Fix the reported stage and run again.
- **The evidence bundle may already be refreshed.** Like `update-reimbursements`, the run
  refreshes the private reimbursement bundle and receipt sidecar in place before building the
  reports (an atomic, repeatable update of the evidence store). A run that fails afterwards
  keeps that refreshed evidence, but it never changes the published set. The failure record
  and manifest list the bundle and sidecar digests before and after the refresh.
- **Adjustments already written stay recorded.** If `--adjustments-file` wrote journal rows
  and a later stage failed, the failure record lists the adjustment IDs written and the
  pre-write snapshot. If the journal write itself failed, was interrupted, or its outcome is
  uncertain (a timeout, or a readback that differs from the plan), the record lists the
  adjustment IDs attempted, the writer's error code (if it classified the failure),
  `journal_write_may_have_landed`, and the retained pre-write snapshot and readback files
  (paths relative to `main-report-runs/`). The writer decides `may_have_landed`: false only
  when no journal cell can have been written (refused before the request, or rejected outright
  on its only attempt with the tab unchanged). Any other failure or Ctrl+C after the pre-write
  snapshot counts as possibly landed, and the console says so. Check the Assumptions tab, then run again: an entry that did
  land is recognized by its ID and is not written twice.
- **A compatibility copy cannot be refreshed** (for example, the file is open elsewhere): the
  current-run page already names the new run and is kept. The command exits `1`, names each
  copy that was not refreshed, and the manifest records each copy's result with a `partial`
  refresh state. Close the file and run again.
- **Replaced files are retained.** Each run keeps the bytes of the page and copies it replaced
  under `<run-id>/publication/previous/`.
- **`run_busy`:** another run holds `main-report-runs/main-report.lock`. If no run is active,
  check the process ID recorded in that file, then delete only that file.
- **`capture_failed: WorksheetNotFound`:** a bound CFO tab was renamed or removed. Bindings
  match the tab by name, so update that binding's `tab` in your private `[main_reports]`
  config. If you set `tab_id`, the run also checks that the named tab still has that id (code
  `tab_id_mismatch`); it does not find a renamed tab. A new tab in the CFO workbook is ignored until you bind it.
- **`capture_failed: APIError 429`:** Google's read quota was exhausted beyond the built-in
  backoff, which waits more than a minute in total. Wait a minute and run again.
- **Ctrl+C** is recorded like any other failure (code `interrupted`, with the stage it
  reached) and the command exits `130` without a traceback. Before the current-run page is
  replaced, the previous set stays published. After it is replaced, the interrupt stops the
  compatibility copies: the manifest marks the copies refreshed, failed and not attempted, and
  the refresh state is `partial`.

Copying files one by one is not atomic as a group; the current-run page is the authoritative
pointer. Just before the page is replaced, the run's manifest is written as `published` with
the copy refresh state `pending`; it becomes `complete` or `partial` once the copies are done.
A manifest left at `pending` belongs to a run that was interrupted (or whose final manifest
update failed, which the command reports) after it became current. The one exception is a hard kill
(power loss, a killed process) in the instant between that manifest write and the page
replacement: the folder then says `published` although the page never named it. The
current-run page is always the authority.

Only the summary pages and the index carry the run ID and input-set hash inside the file.
The queue, its copy text and the PDF/PNG exports are tied to the run by the size and SHA-256
the manifest records for each file (the queue renderer's interface is unchanged).

## Disk use and pruning

Each run keeps its own copy of the bundle, receipt sidecar and receipt pages under
`inputs/`, and the queue embeds every receipt page. The compatibility copies add the queue
twice more beside the current-run page. A run can therefore take a few hundred megabytes
when many receipts are linked. Nothing is deleted automatically. To reclaim space, delete
whole older `main-report-runs/<run-id>/` folders that the current-run page does not name,
and old `failed-runs/` records you no longer need. Keep `captures/` and `adjustments/`: they
are the source and journal-write evidence.

## Email follow-ups and check review in the queue

The reimbursement report supports an operator-maintained **Email follow-ups and check review**
section. A linked index near the top shows open and resolved cases; matching cards include a
summary, next action, evidence provenance, and source images opened in the existing receipt viewer.
Follow-ups do not add reimbursement amounts, authorize payment, or change ticket statuses.

These cases live in the optional `appendix.follow_ups` array of the private schema-v2 reimbursement
bundle. Every record has `key` (unique lowercase letters/digits/hyphens), `title`, `status` (`OPEN`
or `DONE`), `summary`, `next_action`, `evidence` (text array), and `page_ids` (receipt-sidecar page
IDs). Omit the array for older bundles. Images use the existing confined, hash-checked PNG/JPEG
sidecar and its size limits; retain original evidence and use readable display copies when needed.
Missing referenced images fail validation rather than disappearing from the report.

`end-to-end-run` preserves these operator records during reimbursement refresh, captures them
with the bundle and sidecar, and embeds their images in the published queue. `report-reimbursements`
and `update-reimbursements` render the same section. The run needs no separate check-review HTML
or live `.work/` link: its captured image copies make the report self-contained. Earlier immutable
run URLs stay unchanged; use the current-run index for the combined report.

**Automatic discovery is not implemented.** The separate Phase 10 `update-actions` scanner and
action-decision workflow remain paused during Step 51 in the preserved worktree. They are not
called by `end-to-end-run`. See the [handoff](phase10-build-handoff.md). Until that feature ships,
explicitly promote actionable mail into follow-ups, including plain correspondence, paper requests,
and inline-image evidence that form ingestion can miss. A blank parsed reply is not proof that
its raw email contains no actionable text. Follow-up provenance text is operator-maintained;
only referenced image bytes have automatic hash validation in this report path.

## Check-payment and category-date limitations

Emailed check images are archived when Gmail fetching succeeds, but the runner does not recognize
them as payment confirmations or automatically match them to reimbursement tickets or bank rows.
Use the [check evidence review procedure](loading-receipts.md#checks-and-emailed-payment-evidence).
An archived email is not proof that the queue has accounted for its check payment.

Category Mapping currently reads `Keyword` and `Target Category`. If the live tab adds `Start Date`
and `End Date`, inspect the change and update the private binding's complete `header_signature`.
The capture retains those columns, but classification does **not** enforce their date limits.
Fundraising category breakdowns use this guidance, so date-limited category groupings require
review even when overall processor totals are unchanged. Bank `FINAL CATEGORY` and the
separate budget category crosswalk retain their existing roles.

## Recording adjustments

Adjustments correct how the reports read the CFO data (a category, a date, an amount, or an
evidence-backed additive entry). They never approve or pay a reimbursement. Write proposals to
a private JSON file:

```json
{
  "schema_version": 1,
  "adjustments": [
    {
      "adjustment_id": "ADJ-<uuid4 hex, created once and reused on retries>",
      "targets": [{"record_key": "<from the run records>", "revision_hash": "<from the run records>"}],
      "kind": "date_override",
      "effective_date": "2030-07-01",
      "prior_value": "2030-06-30",
      "replacement_value": "2030-07-01",
      "reason": "Statement shows the July posting",
      "evidence": ["statement-2030-07"]
    }
  ]
}
```

Record keys and revision hashes are in the latest run's `records/reconciliation.json`. Then:

```powershell
uv run np-finance end-to-end-run --as-of 2030-08-15 --adjustments-file reports/output/adjustments.json
```

The journal lives below the existing content of your Assumptions tab. Before writing, the
command snapshots the tab, rereads it and refuses if it changed; after writing, it reads the
tab back and stops if anything differs. A rerun with the same file records nothing twice.
Correct an entry with a new row that supersedes it; never edit journal rows by hand during a
run. Google Sheets has no compare-and-swap, so another editor's change that lands between the
last read and the write is detected afterward rather than prevented.

## Reimbursement-only commands

`update-reimbursements` and `report-reimbursements` are unchanged. Use them when you only need
the review queue; they never read the CFO workbook or touch the Main Report Set.

## Latest operational run: 2026-10-28

**Operational refresh (2026-10-28):** the dry run passed after inspecting the CFO
Category Mapping header expansion and updating the private signature to capture Start Date and
End Date. A live `end-to-end-run --as-of 2026-10-28` published all five reports: 15 artifacts
validated, 16 compatibility copies refreshed, and artifact hashes/current-run pointer verified.
No Sheet writes or payment-status edits were requested or made. The run reports 5,637 unresolved
discrepancies, 8 issues and 19 coverage flags; successful publication is not financial acceptance.
The largest discrepancy groups are processor-net arithmetic (3,785), missing overlaps (1,259)
and ambiguous category rules (518). Category-rule date limits are captured but not enforced;
fundraising category breakdowns require review.

Gmail fetch failed because the saved refresh token expired; renewed read-only consent timed out.
The local archive reaches 2026-10-23, so this is **not** a mail-current-through-October-28 run.
The newer self-emailed check evidence remains uninspected. Schema-v2 automatic payment links are
Zelle-only; verified checks can use audited operator records, but image-to-payment recognition,
source-bound check review and issued/cleared/voided/replacement states are not implemented.
See [check handling](loading-receipts.md#checks-and-emailed-payment-evidence).

Validation: 152 tests in `test_reimbursement_events.py` and `test_reimbursement_pipeline.py`,
plus 82 tests in `test_main_report_runner.py`, passed. Identity and whitespace checks passed.
This was focused validation, not a full-suite or financial-acceptance gate. Step 63 remains open.

### Same-day Gmail retry and check review

Read-only Gmail consent subsequently succeeded. Two ordinary bulk-fetch attempts returned a
message-level HTTP 403; a bounded retry through the existing read-only connector retrieved all
138 messages listed for October 1-28 with no remaining failures. A final ordinary CLI fetch for
October 23-28 passed: 30 matched, all unchanged. No mailbox writes or scope expansion occurred.

The second live run published all five reports with 15 validated artifacts and 16 refreshed
compatibility copies; hashes and the current pointer were verified. It added seven reimbursement
submissions (78 source submissions, 218 lines), with 191 events and 211 unmatched messages.
Receipt preparation reported 244 linked items and 112 review-needed items. The discrepancy,
source-issue and coverage counts remain 5,637 / 8 / 19. This supersedes the earlier mail-acquisition
blocker, but does not mark financial acceptance complete.

Five unique emailed check images were inspected and matched in a private, source-hashed review.
One full-request match and one two-check settlement were identified; the latter includes an earlier
posted bank check plus the newly photographed balance. Paper-only requests and a direct-vendor
invoice require separate reconciliation, including an apparent one-cent invoice/check difference.
No new payment statuses were written: split checks cannot be accumulated by the current reducer,
and exact matching does not itself record approval. Private review artifacts stay outside Git.

### Paid-status correction after check review

The operator requested that two verified paid requests no longer appear as clarification cases.
Their private bundle records now show PAID / SETTLED, item reviews are resolved, and stale
clarification questions are cleared. One request retains its two actual check references and
amounts separately; no synthetic aggregate payment event was created. The earlier operator review
was superseded through an audited private-data correction, with complete pre-change backups and
the retired evidence/event retained in the correction audit. Both consecutive refresh previews
preserved the paid states and all unrelated tickets were unchanged. This corrects the earlier
review-only outcome; it does not add general automatic split-check ingestion or prove bank clearing.

The corrected five-report set was published successfully: 15 artifact hashes/sizes verified,
16 compatibility copies refreshed, and both corrected cases checked in the actual published
HTML in Chromium as Paid under closed cases. Older run URLs remain immutable snapshots; use
`reports/output/main-report-set.html` to reach the latest corrected set.

### Combined follow-up publication validation (2026-10-28)

The live report set published with six manually maintained follow-up cases (four open, two
resolved) and six source-image dialogs. The actual published HTML was checked in Chromium;
all six image dialogs opened, the two previously settled reimbursement cases remained Paid,
and desktop/mobile preview checks found no horizontal overflow. All 15 artifact hashes/sizes
and the current-run pointer were verified; all 16 compatibility copies refreshed.

Focused validation: 164 tests across `test_reimbursement_report.py`, `test_receipt_viewer.py`,
`test_receipt_refresh.py`, and `test_main_report_runner.py` passed, including production-runner
coverage for follow-up persistence, captured images, escaped text and missing-page refusal.
Strict package mypy (55 files), changed-file Ruff/format, identity and whitespace checks passed.
This is not a full-suite or Phase 10 completion gate. The originals were retained privately;
smaller display copies kept the report inside the existing image-byte budget.

### Receipt amount and highlight correction validation (2026-10-28)

Four requests were visually reconciled against their source receipts: two omitted tax from
their item entries, one had a small item-entry typo, and one had a one-cent form-total error
with tax already included. Operator-authorized reviews now state exact payable amounts and
the evidence explaining each difference. Original source amounts remain unchanged, obsolete
clarification holds are cleared, and approval does not record payment. The private audit keeps
before-images, source hashes, allocations, and two identical refresh previews.

The report now compares original item sums, form totals, and reviewed totals. Corrected item
rows and receipt dialogs show the original and reviewed amounts together. Metadata-only
mismatch recommendations name the totals and difference, directing receipt inspection before
requester clarification without inventing a receipt-based correction.

Fifteen item links gained visually verified item and tax/total outlines. The final end-to-end
run published all five reports with 15 artifact hashes/sizes verified and 16 compatibility
copies refreshed. Receipt preparation retained 244 linked items, with review-needed items
reduced from 112 to 97 and no refused assets. There were no new submissions; the four reviews
raised the event count to 196. All 15 item dialogs were checked in Chromium, including the
actual published amount labels and red circles; mobile layout, six follow-ups, and the two
previously paid cases were preserved. Existing discrepancy/issue/coverage counts remain
5,637 / 8 / 19.

Validation covered 223 focused tests across the pipeline, report, receipt viewer, receipt
refresh, and runner suites (including the added render test and updated browser/replay tests),
strict package mypy, changed-file Ruff/format, identity, and whitespace checks. This is a
focused correction, not a full-suite or financial-acceptance completion gate.
