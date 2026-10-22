# Main Report Set guide

`pta-finance end-to-end-run` produces the whole private report set from one captured set of
inputs:

| Report | Period | Files |
|---|---|---|
| Reimbursement Queue | every open request, prior-year carryovers included | HTML + copy text |
| Reimbursement Summary | school year (July 1–June 30) through the as-of date | HTML, PDF, PNG |
| Budget Snapshot | school year | HTML, PDF, PNG |
| Fundraising Summary | school year | HTML, PDF, PNG |
| CFO P&L Summary | calendar year (January 1–December 31) | HTML, PDF, PNG |

Every page names its period, basis, as-of date, run ID, input-set hash, source freshness and
finding counts. The supporting design is in the
[Main Report Set specification](plan-reference/cfo-main-report-set.md); the
[master plan](plans/master_plan.md) owns status.

## Before the first run

1. Install the toolkit with the browser export:

   ```powershell
   uv sync --extra dev --extra receipts --extra reports
   uv run playwright install chromium
   ```

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
uv run pta-finance end-to-end-run --as-of 2030-08-15 --dry-run
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
- The WIX and PayPal header labels match the defaults; if not, map them with `columns`
  overrides in your private `[main_reports]` config.

## Run and publish

```powershell
uv run pta-finance end-to-end-run --as-of 2030-08-15
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
uv run pta-finance end-to-end-run --as-of 2030-08-15 --adjustments-file reports/output/adjustments.json
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
