"""Main Report Set: CFO-workbook sources, reconciliation, adjustments, facts, and rendering.

The package is split by responsibility (see ``docs/plan-reference/cfo-main-report-set.md``
section 5): :mod:`~pta_finance.main_reports.models` holds immutable, exact-money records
and identifier helpers; :mod:`~pta_finance.main_reports.sources` holds the read-only CFO
workbook reader, dated source captures with provenance, and per-source adapters;
:mod:`~pta_finance.main_reports.reconcile` builds the CFO-compatible source view, processor
enrichment, published-P&L control checks, crosswalk and discrepancy records.

This ``__init__`` deliberately imports nothing: :mod:`pta_finance.config` imports the
source-kind vocabulary from :mod:`~pta_finance.main_reports.models`, and
:mod:`~pta_finance.main_reports.sources` imports the config, so eager imports here would
create a cycle.
"""
