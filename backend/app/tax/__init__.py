"""US federal tax engine: lot basis, wash sales, capital gains, Form 8949.

The output of this package is a **calculation, not tax advice**. It shows its work and states its
assumptions so it can be checked, and it must be reconciled against the user's 1099-B forms before
it informs a filing.

Module map:

``models``
    Shared shapes. Declared once so the four modules below compose without owning each other.
``washsale``
    IRC §1091 across all eight accounts at once, including the Rev. Rul. 2008-5 IRA case.
``gains``
    Short vs. long term off the possibly-tolled holding period, taxable accounts only.
``form8949``
    Form 8949 rows with box selection and the ``W`` adjustment code.
``reconcile``
    Diff against a supplied 1099-B, naming the specific lots that differ.
``engine``
    Composition: ledger in, :class:`~app.tax.models.TaxReport` out.
"""

from __future__ import annotations
