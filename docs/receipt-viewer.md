# Inspecting a source receipt

In **Reimbursement Review — Current Queue**, click an item description to open its source
receipt. The red outline identifies the receipt line or lines behind that claim. Use **+**
and **−** to zoom, **Focus item** to return to the marked lines, **Fit page** to see the whole
page, and **Previous / Next** when a claim
has more than one source page. **Escape** or **Close** returns focus to the selected item.
This also works for tickets expanded in the closed-case appendix.

**Receipt not linked** means no source page has been associated with that item yet. A linked
page without a marked location opens with an explicit explanation and no red outline.
These are evidence-reading aids; they do not change reimbursement amounts or decisions.

The HTML embeds the receipt images and works offline without a server or third-party scripts.
It contains private receipt details as well as the queue. Keep it with the other private reports.

## Preparing source locations

Locations live in an optional private JSON file beside the report bundle. Replace the bundle's
`.json` suffix with `.receipts.json`. For the default bundle this is
`reports/output/reimbursement-report.receipts.json`. Both `report-reimbursements` and the render
stage of `update-reimbursements` pick it up automatically. Existing bundles need no migration.
Both commands print how many item lines have a validated receipt link and how many remain unlinked.

`update-reimbursements` can prepare future uploads when private config contains a
`[receipt_refresh]` block. It uses an allowlisted cache, isolated image normalization, and optional
local OCR. Every OCR outline is labelled **automatic suggested match** and must be checked by a
person. A ticket-level source page without a unique match has no outline and is recorded as
review-needed. Existing saved entries are preserved. `report-reimbursements` remains entirely
offline and never fetches, decodes, or OCRs anything.

Preparation writes its review/refusal summary beside the sidecar as
`reimbursement-report.receipts.review.json`. Read that file and the aggregate CLI counts after
each configured refresh, especially when the fixed 100 MiB embedded-page budget is nearly full.

Copy the commented `[receipt_refresh]` example from `config.example.toml` into private
`config.toml`, replacing its example hosts with the upload hosts you trust. Keep `pages_dir`
inside the report bundle's directory. PDF preparation needs Playwright and its full Chromium
browser (`uv sync --extra dev`, then `uv run playwright install chromium`). OCR additionally
needs a local Tesseract installation and `tesseract_path`; without it, pages are attached for
manual matching. Preview with `update-reimbursements --dry-run` before the normal command.
No additional receipt command is needed on later configured runs.

Generated sidecar item objects add `match_method: "automatic-ocr-v1"` for suggested outlines
or `match_method: "automatic-ticket-source-v1"` for unmarked source pages. Omit that field only
for locations checked against the original receipt. Automatic preparation never changes an
item's reimbursement decision or amount.

Manually prepared entries use **verified saved locations**. An operator or assistant inspecting
the original receipt prepares those locations. Retain original uploads privately; do not use a
reconstructed receipt or crop away its context.

The file has this structure (the hashes below must be replaced with real computed digests):

```json
{
  "schema_version": 1,
  "pages": [
    {
      "id": "receipt-1-page-1",
      "path": "receipt-pages/receipt-1-page-1.png",
      "sha256": "SHA256_OF_THE_IMAGE_BYTES",
      "label": "Example store receipt · page 1"
    }
  ],
  "items": [
    {
      "review_key": "EXACT_REVIEW_KEY_FROM_BUNDLE",
      "item_key": "EXACT_ITEM_KEY_FROM_BUNDLE",
      "item_sha256": "COMPUTED_ITEM_FINGERPRINT",
      "regions": [
        {"page_id": "receipt-1-page-1", "box": [0.12, 0.30, 0.72, 0.04]}
      ]
    }
  ]
}
```

Each box is `[left, top, width, height]`, as fractions of the full image measured from the
top-left corner. Divide horizontal pixel coordinates by image width, and vertical coordinates
by image height. Multiple regions can mark several purchases within one claim, across one or
more pages. Use `"box": null` only when the source page is verified but the location isn't.
Keep each page once in `pages` and reference it from every relevant item.

Compute an image hash with `hashlib.sha256(path.read_bytes()).hexdigest()`. Compute an item's
fingerprint from the validated report rather than duplicating the fingerprint algorithm:

```python
from pathlib import Path
from pta_finance import receipt_viewer, reimbursement_report

report = reimbursement_report.load_bundle(Path("reports/output/reimbursement-report.json"))
ticket = next(t for t in report.tickets if t.ref == "NEW-01")
item = ticket.items[0]  # Select the exact item that was visually checked.
fingerprint = receipt_viewer.item_fingerprint(ticket, item)
```

Paths must stay below the sidecar's directory, including resolved symlinks. Only PNG and JPEG
bytes are accepted (20 MiB per page; 100 MiB total). Remote URLs, active image formats, duplicate
keys, unknown items/pages, unused pages, and invalid coordinates are rejected. An image digest
mismatch or a changed source/claim invalidates the location and stops HTML replacement, preserving
the previous report. Reinspect the receipt before updating that entry; never just refresh hashes
to suppress an error. Changes only to review status or reviewer explanations retain the match.

Rebuild after saving the sidecar:

```powershell
uv run pta-finance report-reimbursements
```
