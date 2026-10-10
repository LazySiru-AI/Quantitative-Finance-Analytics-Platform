"""Market data providers.

Each module here speaks exactly one upstream API and returns the shapes in
:mod:`app.market.models`. Provider modules never cache, never persist and never fall back to one
another -- :mod:`app.market.registry` owns all three of those.
"""
