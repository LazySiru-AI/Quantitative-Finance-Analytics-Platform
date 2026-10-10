"""MCP (Model Context Protocol) surface for the dashboard.

Split in two on purpose:

- :mod:`app.mcp.tools` is pure. Every function takes settings/inputs and returns plain JSON-able
  dicts, imports nothing from the ``mcp`` package, and is fully testable without it installed.
- :mod:`app.mcp.server` is the thin shell that registers those functions with an MCP server.

That split is what keeps ``pytest`` green on a checkout that has not installed the optional ``mcp``
extra, and it is the same "pure core, imperative shell" shape the rest of this codebase uses (see
``app.rules.service`` versus ``app.api.rules``). It also means the interesting logic -- what a tool
says about how much its own numbers can be trusted -- is unit-testable rather than reachable only
through a running MCP client.
"""
