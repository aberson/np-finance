"""Main Report Set: CFO-workbook sources, reconciliation, adjustments, facts, and rendering.

The package is split by responsibility (see ``docs/plan-reference/cfo-main-report-set.md``
section 5): :mod:`~np_finance.main_reports.models` holds immutable, exact-money records
and identifier helpers; :mod:`~np_finance.main_reports.sources` holds the read-only CFO
workbook reader, dated source captures with provenance, and per-source adapters;
:mod:`~np_finance.main_reports.reconcile` builds the CFO-compatible source view, processor
enrichment, published-P&L control checks, crosswalk and discrepancy records;
:mod:`~np_finance.main_reports.adjustments` reads and appends the bounded Assumptions
adjustments journal and projects recorded corrections onto a copy of the source view;
:mod:`~np_finance.main_reports.facts` projects school-year and calendar-year facts,
reimbursement carryovers and reconciliation bridges from one captured input set.

This ``__init__`` deliberately imports nothing: :mod:`np_finance.config` imports the
source-kind vocabulary from :mod:`~np_finance.main_reports.models`, and
:mod:`~np_finance.main_reports.sources` imports the config, so eager imports here would
create a cycle.
"""
