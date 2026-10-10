"""The MCP server: registration only, no logic.

Everything of substance is in :mod:`app.mcp.tools`, which imports nothing from the ``mcp`` package.
This module is the shell that binds those functions to a protocol, and it is deliberately thin
enough that there is nothing here to test — if a behaviour matters, it belongs one module down where
it can be tested without a client.

## Running it

    pip install -e "backend[mcp]"
    python -m app.mcp.server

It speaks stdio, which is what an MCP client (Claude Code, or Agent Office once it passes
``--mcp-config``) launches and talks to. There is no network listener: stdio keeps the process
reachable only by whatever started it, which is the right default for a server whose tools read
someone's brokerage ledger.

## Read-only, on purpose

Every registered tool reads. Nothing here imports, mutates, rebuilds or places anything. That is
not an oversight to be filled in later — it is what makes this safe to leave running in a daily
toolset. A write tool on this surface would mean an agent could alter a tax ledger, and the
vendored trading agent's ``place_order``/``submit_order`` capability is deliberately not exposed
here either.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.mcp import tools

# `MCPServer`, not `FastMCP`. The class was called `FastMCP` and lived at `mcp.server.fastmcp`
# through the 1.x SDK; 2.0 renamed it and moved it here. Both facts were confirmed against the
# installed package rather than taken from memory -- the 1.x import raises `ModuleNotFoundError` on
# 2.0, which is exactly the failure this comment exists to stop the next person re-discovering.
# `pyproject.toml` pins `mcp>=2.0` for the same reason.
try:  # pragma: no cover - import guard, exercised only by the error path below
    from mcp.server.mcpserver import MCPServer
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        'the MCP extra is not installed -- run: pip install -e "backend[mcp]"\n'
        "(app.mcp.tools works without it; only this server shell needs the mcp package)"
    ) from exc


def _silence_request_url_logging() -> None:
    """Stop httpx logging full request URLs, which would print the FRED API key.

    Found by functional-testing this server, not by reading it, and the chain is worth writing down
    because no single link is wrong on its own:

    1. FRED authenticates by **query parameter** -- ``?api_key=...``. That is its API's design, not
       a choice this codebase can make; there is no header form to switch to.
    2. ``httpx`` logs every request line, full URL included, at INFO
       (``httpx/_client.py:1025``). Harmless by default, because httpx's logger sits at WARNING and
       nothing in this application ever raised it.
    3. **This server changes that.** ``MCPServer`` calls ``logging.basicConfig`` during startup
       (``mcp/server/mcpserver/utilities/logging.py:39``), which configures the root logger at INFO
       and switches on every library logger that had been inheriting it -- including httpx's.

    So a live key ends up in this process's stderr, which is exactly the stream an operator tails
    when an agent looks stuck, and which a parent process (Agent Office spawns MCP servers) captures
    wholesale. Nothing here was insecure before this module existed; adding an MCP server is what
    joined the three links together, which makes it this module's problem to sever.

    Scoped to httpx rather than clamping the root logger back down: the MCP framework's own INFO
    output is useful for debugging a server that will not start, and silencing everything to fix one
    leak would trade a real diagnostic for a blunt instrument. httpx is the only library here that
    makes outbound authenticated requests, so it is the only one whose request line can carry a
    credential.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)


mcp = MCPServer("investing-dashboard")


@mcp.tool()
def tax_summary(year: int) -> dict[str, Any]:
    """Realised gains, wash sales and Form 8949 totals for one US tax year.

    Returns a `data_quality` block alongside the figures. When `confidence` is `upper_bound`, the
    gain totals rest on disposals whose cost basis could not be verified from the broker export --
    quote them as provisional and say so, and never present them as final or file-ready.
    """
    return tools.tax_summary(get_settings(), year=year)


@mcp.tool()
def decision_table(symbol: str, interval: str = "1d") -> dict[str, Any]:
    """Every catalog rule evaluated for one symbol, with the forward-return evidence behind it.

    Each evidence entry carries `hit_rate` **and** `baseline_hit_rate`. Never quote one without the
    other: a 55% hit rate is not an edge when the baseline is 56%. `null` means "not measurable
    from the available history", which is different from zero.
    """
    return tools.decision_table(get_settings(), symbol=symbol, interval=interval)


@mcp.tool()
def macro_snapshot() -> dict[str, Any]:
    """Current macro backdrop: rates, the 2s10s curve, energy, volatility and sentiment.

    Every tile carries its own `as_of` and `source`; they routinely differ within one snapshot, so
    read the per-tile date rather than assuming the whole panel is current.
    """
    return tools.macro_snapshot(get_settings())


def main() -> None:
    # Before `run()`, which is what triggers the framework's `basicConfig`. Order matters: setting a
    # logger's level is not undone by a later `basicConfig` (that only configures the root handler),
    # so doing it first is safe -- but doing it *after* `run()` would never execute at all, because
    # `run()` blocks for the life of the server.
    _silence_request_url_logging()
    mcp.run()


if __name__ == "__main__":
    main()
