"""Market data: providers, fallback registry, bar store, fundamentals.

The boundary this package defends is the one between *observed* market data and *recorded* ledger
data. Everything in :mod:`app.core` and :mod:`app.tax` is :class:`~decimal.Decimal`, because a cent
of drift in a cost basis is a wrong tax return. Everything here is :class:`float`, because these are
observations feeding statistics, the source itself hands them over as IEEE doubles, and DuckDB,
Parquet, pandas and every indicator formula are float-native.

Mixing the two is the failure mode. A quoted price must never reach a lot, a basis or a gain
computation; it may only reach a chart, an indicator or a study. See :mod:`app.market.models` for
the enforcement point.
"""
