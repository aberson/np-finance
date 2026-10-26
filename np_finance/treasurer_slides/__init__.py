"""Private-input contracts for the optional Treasurer Slides workflow.

The package is deliberately generic. Real statements, finance facts, OAuth material,
and presentation identifiers belong only in gitignored operator inputs and outputs.
The stable contract surface is ``np_finance.treasurer_slides.models``.
"""

from np_finance.treasurer_slides.models import TreasurerSlidesError

__all__ = ["TreasurerSlidesError"]
