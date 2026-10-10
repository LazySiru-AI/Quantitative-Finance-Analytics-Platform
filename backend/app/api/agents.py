"""HTTP surface for the Claude-backed agent layer's own health, and nothing else.

**Read-only, deliberately.** Every other router under `app.api` that touches `app.agents` (there are
none yet besides this one) would trigger a model call on a person's action -- starting a loop, asking
the scout for picks. This router exists so the Competition page can show "is the agent layer usable
right now" on an ordinary, unauthenticated page load, without that load costing a cent. Nothing here
calls `app.agents.client.call_structured` or anything that reaches Anthropic; `is_available()` only
resolves which credential source would be used, it never opens a connection.

**Never a 500.** `app.agents` degrading is the entire point of the package's design (see its own
module docstring); a health endpoint that could itself throw when the thing it is reporting on is
broken would be the one component in this feature that is not allowed to fail gracefully. If the
`app.agents` package -- or the `anthropic` SDK it wraps -- cannot even be imported, that is reported
as `sdk_installed: false`, `available: false`, with the import error as the reason, not as an
exception escaping this router.

**Never a credential value.** `reason` says which source won (`"api_key"`, `"auth_token"`,
`"profile"`) or why none did; it is built entirely from `app.agents.client.is_available`'s own
classification, never by reading an environment variable's value into this response.

**Never a filesystem path, either.** `app.agents.cli_transport.is_available` reports the CLI binary
it resolved at its absolute path, which on a Windows install spells out the operator's account name
(the account's home directory is part of the path). This is the endpoint the Competition page loads on an ordinary
page view, so :func:`_redact_paths` reduces any absolute path in `reason` to its file name before it
leaves this module. The unredacted reason is logged server-side at INFO instead, where an operator
debugging a missing binary can still read the path in full.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import PurePosixPath

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/agents", tags=["agents"])

logger = logging.getLogger(__name__)

#: Characters that end a path token inside an English sentence -- `is_available`'s reasons put paths
#: at the end of a clause or inside parentheses, never mid-word.
_TRAILING_PUNCTUATION = ",.;:)]}'\""


def _looks_absolute(token: str) -> bool:
    """Whether `token` is an absolute path rather than an ordinary word.

    Three shapes, matching the three ways `app.agents.cli_transport.resolve_cli_binary` can answer:
    a POSIX absolute path, a Windows drive-letter path, and a UNC path. A dotted module name
    (`app.agents.client`) or a bare environment variable name has no separator and is left alone.
    """
    if not any(sep in token for sep in ("/", "\\")):
        return False
    if token.startswith(("/", "\\")):
        return True
    return len(token) > 2 and token[1] == ":" and token[2] in "/\\"


def _redact_paths(reason: str) -> str:
    """`reason` with every absolute path reduced to its file name.

    Applied to whatever `app.agents.client.is_available` returns, rather than to one known sentence,
    so a reason that grows a second path later is covered without this module having to learn about
    it. A reason with no path in it comes back unchanged, character for character.
    """
    words = []
    for word in reason.split(" "):
        body = word.rstrip(_TRAILING_PUNCTUATION)
        trailer = word[len(body):]
        if _looks_absolute(body):
            words.append(PurePosixPath(body.replace("\\", "/")).name + trailer)
        else:
            words.append(word)
    return " ".join(words)


class AgentHealth(BaseModel):
    """`GET /api/agents/health` response body."""

    available: bool
    credential_source: str
    reason: str
    model: str
    sdk_installed: bool


@router.get("/health", response_model=AgentHealth)
def health() -> AgentHealth:
    """Whether the agent layer is usable right now, and why -- with no model call and no possibility
    of a 500.

    Imports `app.agents.client` and `app.agents.models` inside this function, not at module scope, so
    a broken or absent `app.agents` package (or a missing `anthropic` dependency) fails this one
    request with a reported, human-readable reason rather than making the whole application
    unimportable -- the same defensive shape `app.evolution.loop.default_collaborators` uses for the
    same package.

    Uses `importlib.import_module` rather than a plain `import`/`from...import` statement so the
    import goes through `sys.modules` unambiguously -- both for real (a genuinely absent module
    raises `ModuleNotFoundError`) and in this file's own tests (`sys.modules["app.agents.client"] =
    None` is the standard way to force that same exception for a module that *is* installed, and a
    test double dropped into `sys.modules` is picked up the same way a real submodule would be).
    """
    try:
        client_module = importlib.import_module("app.agents.client")
        models_module = importlib.import_module("app.agents.models")
        default_model = models_module.DEFAULT_MODEL
    except ModuleNotFoundError as exc:
        return AgentHealth(
            available=False,
            credential_source="none",
            reason=f"app.agents is not importable: {exc}",
            model="",
            sdk_installed=False,
        )
    except Exception as exc:  # any other import-time failure -- still never a 500
        return AgentHealth(
            available=False,
            credential_source="none",
            reason=f"app.agents failed to import: {type(exc).__name__}: {exc}",
            model="",
            sdk_installed=False,
        )

    try:
        importlib.import_module("anthropic")
        sdk_installed = True
    except ModuleNotFoundError:
        sdk_installed = False

    try:
        available, reason = client_module.is_available()
        # The unredacted reason goes to the server log -- an operator debugging "why is the agent
        # layer down" needs the path this endpoint deliberately will not publish.
        logger.info("agent layer health: available=%s reason=%s", available, reason)
        reason = _redact_paths(reason)
    except Exception as exc:  # `is_available` is documented to resolve, never call out -- degrade anyway
        return AgentHealth(
            available=False,
            credential_source="none",
            reason=f"is_available() raised {type(exc).__name__}: {exc}",
            model=default_model,
            sdk_installed=sdk_installed,
        )

    try:
        credential_source = client_module.credential_source()
    except Exception as exc:
        return AgentHealth(
            available=False,
            credential_source="none",
            reason=f"credential_source() raised {type(exc).__name__}: {exc}",
            model=default_model,
            sdk_installed=sdk_installed,
        )

    return AgentHealth(
        available=available,
        credential_source=credential_source,
        reason=reason,
        model=default_model,
        sdk_installed=sdk_installed,
    )
