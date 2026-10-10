"""Institutional and fund portfolio disclosures from SEC EDGAR.

Two filings, one shape. A **13F-HR** is what an institutional investment *manager* holds; an
**NPORT-P** is what a registered *fund* -- an ETF -- holds. They answer different questions and
this package deliberately does not blur them: see :class:`~app.institutions.models.Source`.
"""
