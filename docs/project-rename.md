# np-finance migration

The project is a reusable finance toolkit for non-profit organizations. The repository and
checkout are named `np-finance`; Python imports use `np_finance`. Existing financial inputs,
Google service-account credentials, OAuth consent, workbook IDs and receipt evidence remain
private and retain their identities.

## Run the full report set

From the `np-finance` checkout:

```powershell
uv sync --extra dev --extra slides --extra receipts --extra reports
uv run np-finance end-to-end-run --as-of (Get-Date -Format yyyy-MM-dd) --dry-run
uv run np-finance end-to-end-run --as-of (Get-Date -Format yyyy-MM-dd)
Invoke-Item reports/output/main-report-set.html
```

The workspace `end-to-end-run` launcher now calls this five-report runner. It previously
called the reimbursement-only refresh. The full-report launcher retains an optional mail-fetch date prompt; leave it blank to use
the existing local archive. The separate `email-only` launcher and the documented
`--fetch-since` CLI option remain available. Runs without that option do not fetch new mail.

## Hookup inventory

| Hookup | Migration |
|---|---|
| GitHub repository | Existing repository renamed; history, issues, and old-link redirects retained. |
| Local checkout | `<workspace>/np-finance`; repair linked worktree Git pointers. |
| Python distribution / CLI | `np-finance`; reinstall dependencies after moving the checkout. |
| Python module / packaged resources | `np_finance`; imports, worker entry points, Docker staging and tests updated together. |
| Existing CLI command name | `pta-finance` remains a compatibility entry point to the same implementation. |
| Workspace registry / editor tasks | New project name/path and five-report commands. |
| Main documents / examples | Non-profit wording, new links and commands; regenerate fictional screenshots and presentation preview. |
| Private configuration | Preserve credentials and source IDs; update only paths referring to the moved checkout. |
| Private report history / source mail | Preserve existing bytes; publish a new versioned run. |
| Cloud deployment / journal schema | Retain existing wire identifiers below; no cloud resource recreation. |

The old checkout directory could not be removed while locked by Windows; it is an empty
leftover, not a forwarding alias. Open terminals and projects at the new checkout path.

## Stable compatibility identifiers

`PTA_CONFIG_B64`, `PTA_WORKFLOW_CONFIG`, `PTA_IDENTITY_DENYLIST`, `X-PTA-CSRF`,
`PTA_REPORT_ADJUSTMENTS_V1`, and existing report metadata names are technical compatibility
identifiers, not the organization's classification. Existing cloud resource names and IAP
identities are unchanged. Renaming a live cloud service would change its audience and requires
a separate deployment and authenticated acceptance run. This migration updates deployment
source paths but does not deploy that optional proof.

Saved Python scripts outside the repository must change imports to `np_finance`. Older
worktree branches keep their own code and environment; `git worktree repair` reconnects their
Git metadata without modifying their unfinished work. Existing journal and reimbursement
records must never be renamed by bulk text replacement.

[Migration progress and evidence](rename-progress.html).
