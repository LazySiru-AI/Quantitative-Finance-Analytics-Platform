"""Live paper-trading desk: three books -- savings, trading and roth -- each seating its own
strategies and traded forward from a common inception on the application's own stored daily bars.

Deliberately names no specific card or date here. An earlier version of this docstring named two
cards and a start date, and all three were wrong within the month: the roster is a configuration
value that eleven competition rounds have re-selected, and the inception has moved once and can be
moved again at runtime. The authority for both is :mod:`app.paperdesk.desk` -- :data:`~app.paperdesk.
desk.AGENT_IDS` and :func:`~app.paperdesk.desk.effective_inception` -- and a summary that restates
them here can only ever drift away from them.

See :mod:`app.paperdesk.desk` for the trading window, the mandate setup and every arithmetic
decision; :mod:`app.paperdesk.autopilot` for the one seat that reads a persisted ledger instead of
replaying bars; :mod:`app.paperdesk.models` for the wire shapes; and :mod:`app.api.paperdesk` for
the HTTP endpoints.
"""

from __future__ import annotations
