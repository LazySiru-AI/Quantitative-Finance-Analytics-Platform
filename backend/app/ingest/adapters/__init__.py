"""Broker CSV adapters.

Each module here converts one broker's export into canonical :class:`~app.core.models.Transaction`
objects. Adapters are the only code in the system that knows what a Robinhood or Webull row looks
like.

Submodules are deliberately **not** imported here. Registration happens explicitly in
:func:`app.ingest.registry.load_builtin_adapters`, so importing this package never has the side
effect of mutating the registry -- which keeps test isolation possible and makes the set of active
adapters something you can read off one function rather than infer from import order.
"""
