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
| Existing CLI command name | `pta-finance` is deprecated for new use; retained as a compatibility entry point to the same implementation. |
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

## Deprecation and external-reference audit (2026-10-26)

The [pre-rename source archive](archive/pta_finance/README.md) contains the 229
public tracked files from the last pre-rename commit. The active repository remains
`np-finance`. GitHub API checks resolve both names to repository ID `1278513113`;
deleting or archiving the old URL would target the active repository.

| Surface examined | Result |
|---|---|
| GitHub repository identity, remote, description | New canonical name; old URL redirects. History and issues preserved. No separate old repository exists. |
| Repository webhooks / Actions variables / secret names | No webhooks, repository variables or secrets returned by the available API checks. Workflow compatibility variable names remain supported. |
| GitHub profile (`aberson/aberson`) | README name, URL and description updated and pushed. |
| Public portfolio (`aberson.github.io`) | Finance row refreshed from Observatory export; card selectors, visual gallery, content identifier and narrative updated. Replaced older branded images with current fictional examples. |
| Observatory registry and snapshot | Exactly one finance entry, `np-finance`; preview showcases the full five-report runner. |
| Observatory source / test inventory | Remaining old project identifier updated; focused plan-status suite: 242 passed, 8 skipped, 2 expected failures. The real-workspace invariant skips because its separate legacy workspace sentinel is absent. |
| Editor tasks / linked Git worktrees | New checkout and commands; existing worktree metadata repaired during the migration. Unfinished historical branches preserved. |
| Codex project trust entry | Local trusted checkout path changed to `np-finance`; trust level unchanged. |
| Scheduled tasks / workspace scripts | No old-name references found in the inspected task actions or workspace script/config paths. |
| Yarvis source-reference documents | Finance module paths and project references updated and pushed; no runtime dependency changed. |
| Other local Git repositories | Matches in citation-needed, on-brand and skill-mesh are historical research/plan evidence; retained. No additional active code import found in the tracked-text scan. |
| Workspace histories / ship log / private handoffs | Historical names preserved to keep old evidence and links interpretable. Generated installed skill profiles were not edited. |
| Google credentials, workbooks, mail and report history | Private identities and immutable evidence preserved; checkout paths were migrated, and the new command published all five reports. |
| Optional cloud proof | Existing service names, IAP audience and wire identifiers retained. Live cloud resources were not redeployed or independently enumerated in this cleanup. |

Validation for the portfolio update: `npm run check`, `npm run build`, and
`npm run check:a11y` passed (zero accessibility violations on the two checked pages).
The finance portfolio row is copied from generated exporter output; unrelated
portfolio entries retain their existing published values.

Scope: tracked-text searches across local Git repositories, active workspace
configuration and launchers, local scheduled tasks, and the authenticated GitHub
surfaces above. This is not a claim to have searched every external account,
browser bookmark or private historical artifact. The empty old directory remains
locked by Windows; its failed move did not affect the archived source or active checkout.
