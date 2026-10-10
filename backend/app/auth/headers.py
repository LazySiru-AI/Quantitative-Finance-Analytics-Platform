"""Security response headers for the API surface.

Four headers, appended to every ``/api/`` response:

- ``x-content-type-options: nosniff`` -- a browser must not re-guess the type of a JSON body it was
  told is JSON. The realistic vector here is a stored value (a ticker, a persona note, an imported
  filename) echoed back inside a JSON document that some old browser decides to sniff as HTML.
- ``x-frame-options: DENY`` -- nothing in this app is meant to be framed, and framing it is how a
  clickjacked page would drive a signed-in owner's session against, say, ``POST /api/import``.
- ``referrer-policy: no-referrer`` -- API paths carry identifiers (a genome id, a round id, a
  symbol); none of that should leak to a third-party host in a ``Referer``.
- ``cache-control: no-store`` -- the responses behind the login gate are personal (positions, tax
  figures) and must not sit in a shared or on-disk cache. Only appended when the route did not set
  its own ``cache-control``, so a route that deliberately allows caching keeps its own answer.

**Raw ASGI, and only the start message is touched.** Same reason as ``app.auth.gate``: Starlette's
``BaseHTTPMiddleware`` buffers the body, which would kill ``GET /api/paperlive/stream``. This wraps
``send`` and rewrites exactly one message type, ``http.response.start``; ``http.response.body``
frames pass through untouched and unbuffered, so the SSE stream still streams
(``tests/test_auth_gate_streaming.py`` pins that, and ``tests/test_security_headers.py`` pins that
the stream carries these headers too).

**What is deliberately *not* here:**

- **HSTS** (``strict-transport-security``). TLS does not terminate in front of this process today
  (see ``docs/AUTH.md``, "Exposing beyond loopback"), and an HSTS header served over plain HTTP is
  either ignored or -- once a TLS hop appears -- pins a hostname the operator may not be ready to
  serve over HTTPS forever. It belongs on the TLS terminator, added at the same time as
  ``INVDASH_AUTH_COOKIE_SECURE=1``.
- **CSP** (``content-security-policy``). This middleware only covers ``/api/``, which serves JSON
  and one event stream -- there is no document here for a CSP to constrain. The policy belongs on
  the thing that serves the HTML: the nginx config in ``frontend/Dockerfile``.
"""

from __future__ import annotations

#: ``(header, value)`` pairs appended to ``/api/`` responses, lowercase as ASGI requires.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)

#: Only the API is covered -- see the module docstring on CSP. Static assets are served by nginx in
#: the deployed topology and by the Vite dev server locally; neither passes through this process.
_PREFIX = "/api/"


class SecurityHeadersMiddleware:
    """Append :data:`_SECURITY_HEADERS` to every ``/api/`` response, without buffering a body."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or not scope.get("path", "").startswith(_PREFIX):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):  # type: ignore[no-untyped-def]
            if message.get("type") != "http.response.start":
                await send(message)
                return
            headers = list(message.get("headers") or [])
            present = {name.lower() for name, _ in headers}
            # Append rather than replace: a route that already set one of these (the gate's own
            # `cache-control: no-store` denial, or a route with a deliberate caching answer) keeps
            # what it said, and no header is ever sent twice.
            headers.extend(
                (name, value) for name, value in _SECURITY_HEADERS if name not in present
            )
            await send({**message, "headers": headers})

        await self.app(scope, receive, send_with_headers)
