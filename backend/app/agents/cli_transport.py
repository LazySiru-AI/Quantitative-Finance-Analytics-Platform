"""A second way to reach the model: shell out to the locally-installed Claude Code CLI.

**The concrete failure this module exists to route around.** `app.agents.client.build_client` builds a
zero-arg `anthropic.Anthropic()`, which resolves a credential from exactly three places: an
`ANTHROPIC_API_KEY`, an `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile at
`%APPDATA%\\Anthropic\\credentials\\<profile>.json`. On a machine where none of those three is set --
this package's own owner's machine, among others -- `client.is_available()` returns
`(False, "no usable Anthropic credential: ...")` and every agent in this package falls back to its
deterministic proposer, even though Claude Code is installed and logged in right there. The two
credential stores do not overlap: Claude Code's own login lives at `~/.claude/.credentials.json` (or
platform equivalent), a file the `anthropic` SDK has never heard of and never will, because it belongs
to a different product surface (a subscription-backed CLI session, not an API key). Neither side can
read the other's store. The only bridge between them is the `claude` binary itself, which already
carries that login -- so this module spawns it as a subprocess instead of asking the SDK to authenticate
with credentials that were never going to be there.

**Binary resolution never hardcodes a version, because doing so is already wrong the day it ships.**
Claude Code installs itself under a version-numbered directory and updates in place by adding a new one
next to the old, never overwriting it -- this machine has both `2.1.234` and `2.1.237` installed
side by side. A path with `2.1.237` baked in is stale the moment `2.1.238` lands. So
:func:`resolve_cli_binary` never spells out a version: it checks an explicit override, then `PATH`,
then scans every version directory it can find under the known install roots and picks the highest by
parsing `major.minor.patch` as a tuple of ints -- never by sorting the directory names as strings, which
would rank `"2.1.9"` above `"2.1.10"`.

**Two Windows install roots exist, and searching only one is a real bug that presents as "not
installed."** `%APPDATA%\\Claude\\claude-code\\<version>\\claude.exe` is inside an MSIX-virtualised
package container: a process running *inside* that container's identity (Explorer, or a shell launched
through the Claude desktop app) sees it resolve; a plain terminal process -- exactly what actually runs
this backend -- can see it or not depending on how Windows' virtualisation happens to be feeling that
session, which was reproduced live while writing this module: the same path reported present through
one shell and absent through another, with nothing in between changed. `%LOCALAPPDATA%\\Packages\\
Claude_<id>\\LocalCache\\Roaming\\Claude\\claude-code\\<version>\\claude.exe` is the real,
non-virtualised location backing it and is what a server process reliably sees. Both are searched, in
that order, so this module works whichever way a given process happens to observe the filesystem, and a
`<id>` is never hardcoded (`Claude_pzs8sxrjxfjjc` on this machine is Windows Store's own per-install
suffix, not a constant).

**The call must be a pure model call, never an agent session -- three flags exist to guarantee it.**
`app.agents` proposes and reviews; it never touches a file, runs a command, or acts on the world, and a
CLI invocation that let the model reach for a tool would be a different, unaudited kind of call than
every SDK call this package also makes. `--system-prompt` (not `--append-system-prompt`) replaces
Claude Code's own agentic system prompt outright with the caller's frozen prompt constant, rather than
stacking on top of it -- appending would change the model's framing on every single call, which is
exactly the kind of prefix drift `client.call_structured`'s own docstring calls "load-bearing, not
stylistic" about cache placement, restated here for a transport that has no cache_control block to
protect it, only a stable prompt. `--exclude-dynamic-system-prompt-sections` strips the per-session
boilerplate (cwd, git branch, and similar) Claude Code would otherwise splice in regardless, which would
otherwise make two calls with an identical `system` string produce two different actual prompts.
`--allowedTools ""` passes an explicit *empty* allow-list rather than an enumerated `--disallowedTools`
list, deliberately: a deny-list has to name every tool that exists today and silently admits any tool a
future CLI release adds, while an empty allow-list admits nothing by construction regardless of what the
binary can do next month -- confirmed against a real `--help`, whose own text for `--allowedTools` is
"comma or space-separated list of tool names to allow," so an empty string denies all of them at once.

**`--dangerously-skip-permissions` is never passed, on purpose, and this is not an oversight to
revisit.** A tool-less call has nothing to ask permission for -- there is no edit, no command, no
approval prompt that `--allowedTools ""` leaves standing for that flag to bypass. Passing it anyway
would buy this module nothing while removing a real safety boundary from the one code path in this
package that spawns an actual OS process, so it is left off even though the flag exists and even though
`--print` mode would otherwise be silently blocked by a permission prompt with no tools to approve in
the first place (there being none is exactly why no prompt appears).

**Structured output is prompt-engineered here, not native.** The `anthropic` SDK's `messages.parse`
does native structured output; the CLI has no equivalent flag, so this module asks in prose: it appends
`output_format.model_json_schema()` to the *user* turn (never the system prompt -- see above on why that
stays untouched) with an instruction to return only JSON, strips a ```json fence if the model adds one
anyway (models add them even when told not to), and validates the result with
`output_format.model_validate_json`. A response that fails either step raises `AgentUnavailable` with
the raw text attached -- this module repairs nothing and substitutes nothing, the same rule
`app.agents.client.call_structured` already holds for the SDK path and `app.agents.designer`'s own
"validate, never repair" section holds one layer up.

**Cost comes from the CLI's own `total_cost_usd`, never from `client.estimate_cost_usd`'s price
table.** That table prices raw token counts against Anthropic's published first-party rates; a Claude
Code CLI call rides a subscription and can be heavily cache-read (this module measured a trivial
one-line reply costing $0.22 against a five-token completion, almost all of it a ~36k-token cache
write from Claude Code's own session bootstrap), so recomputing a number from token counts alone would
produce a confident, wrong figure. `total_cost_usd`, read straight off the envelope, is what the CLI
itself believes it spent, and it is what `--max-budget-usd` -- passed the caller's own remaining
`AgentBudget`, a second, process-level ceiling underneath the one `AgentBudget` already enforces --
polices against.

**Every failure degrades to `AgentUnavailable`, none of them crash the loop.** Binary not found, spawn
failure, a non-zero exit, `is_error: true`, a timeout, or stdout that will not parse as the envelope or
as the requested schema: all of these raise with a readable reason, exactly the shape every caller in
this package already catches to fall back to its deterministic path -- see `app.agents.models`'s own
module docstring on why the agent layer is an improvement to the search, never a dependency of it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from app.agents.models import (
    AgentResponseInvalid,
    AgentRole,
    AgentTransientError,
    AgentUnavailable,
)

__all__ = [
    "CliCallResult",
    "call_structured",
    "is_available",
    "resolve_cli_binary",
]

# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------

#: Follows this repo's `INVDASH_` env-var convention (see `backend/app/config.py`'s
#: `env_prefix="INVDASH_"`) even though this is a plain `os.environ` read rather than a `Settings`
#: field -- the same choice `app.agents.client` makes for `ANTHROPIC_PROFILE`, a variable that names a
#: *selection* rather than application configuration proper, read directly rather than routed through
#: `Settings` so a caller can override it without constructing one.
_CLI_ENV_OVERRIDE = "INVDASH_CLAUDE_CLI"

#: The binary's own name. `shutil.which` on Windows appends `PATHEXT` (`.EXE`, `.CMD`, `.BAT`, ...)
#: itself, so a bare `"claude"` finds `claude.exe` on Windows and `claude` on POSIX without this module
#: needing to special-case the extension.
_BINARY_NAME = "claude"

#: Generous: the measured call in this module's own docstring took ~3s of API time, but process
#: startup (loading Claude Code's own session bootstrap, which alone accounted for a ~36k-token cache
#: write in that measurement) is slow and worth budgeting for separately from the model's own latency.
DEFAULT_TIMEOUT_SECONDS = 300.0


def _parse_version(name: str) -> tuple[int, ...] | None:
    """`"2.1.237"` -> `(2, 1, 237)`, or `None` for anything that is not a dotted-integer version.

    A tuple of ints, never the string itself: `"2.1.9" < "2.1.10"` lexicographically is false (`"9" >
    "1"` as characters), which would rank a patch release below the one it superseded. A directory that
    does not parse this way (a stray file, a future non-numeric channel name) is skipped rather than
    raising -- this function's caller already tolerates a root containing nothing usable.
    """
    parts = name.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _windows_install_roots() -> list[Path]:
    """Both Windows install roots, in the order the app's own docstring documents: the MSIX-virtualised
    `%APPDATA%` path first, then every `%LOCALAPPDATA%\\Packages\\Claude_*\\...` package directory --
    there can be more than one if the Store has ever reinstalled under a new package identity, so this
    globs rather than assuming a single fixed suffix."""
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Claude" / "claude-code")
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        packages_dir = Path(localappdata) / "Packages"
        if packages_dir.is_dir():
            for entry in sorted(packages_dir.iterdir()):
                if entry.is_dir() and entry.name.startswith("Claude_"):
                    roots.append(entry / "LocalCache" / "Roaming" / "Claude" / "claude-code")
    return roots


def _posix_install_roots() -> list[Path]:
    """The one POSIX install root worth checking beyond `PATH`: Claude Code's own updater lays a local
    install under `~/.claude/local/` on macOS and Linux. Unlike Windows there is no known second root
    and no MSIX-style virtualisation problem to route around here, so this stays a single path rather
    than a version-directory scan."""
    return [Path.home() / ".claude" / "local"]


def _binary_name_for(directory: Path) -> str:
    return f"{_BINARY_NAME}.exe" if os.name == "nt" else _BINARY_NAME


def _highest_versioned_binary(root: Path) -> tuple[tuple[int, ...], Path] | None:
    """The highest-version `claude` binary directly under `root`, if `root` holds any version
    directories at all -- `root` itself need not exist (most machines have only one of the two Windows
    roots actually present)."""
    if not root.is_dir():
        return None
    best: tuple[tuple[int, ...], Path] | None = None
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        version = _parse_version(entry.name)
        if version is None:
            continue
        candidate = entry / _binary_name_for(entry)
        if not candidate.is_file():
            continue
        if best is None or version > best[0]:
            best = (version, candidate)
    return best


def resolve_cli_binary() -> Path | None:
    """The `claude` binary this process should invoke, or `None` if none can be found.

    Resolution order, each step skipped if it finds nothing: an explicit `INVDASH_CLAUDE_CLI` override
    (trusted at face value -- a caller who set it gets exactly that path, existing or not, so a typo
    fails loudly rather than silently falling through to a different install); `PATH`; then every
    version directory under the known install roots (both Windows roots, or the one POSIX root),
    picking the single highest version across *all* roots combined rather than the highest within
    whichever root is checked first -- a newer version under the second root must still win.
    """
    override = os.environ.get(_CLI_ENV_OVERRIDE)
    if override:
        return Path(override)

    on_path = shutil.which(_BINARY_NAME)
    if on_path:
        return Path(on_path)

    roots = _windows_install_roots() if os.name == "nt" else _posix_install_roots()
    best: tuple[tuple[int, ...], Path] | None = None
    for root in roots:
        found = _highest_versioned_binary(root)
        if found is not None and (best is None or found[0] > best[0]):
            best = found
    return best[1] if best is not None else None


def is_available() -> tuple[bool, str]:
    """Whether a Claude Code CLI call can be attempted right now, and why or why not -- the CLI
    transport's own analogue of `app.agents.client.is_available`, checked independently of the SDK's
    three credential slots so `client.is_available` can report "usable via either path" without this
    module knowing anything about `ANTHROPIC_API_KEY`."""
    binary = resolve_cli_binary()
    if binary is None:
        return False, (
            f"no Claude Code CLI binary found (checked {_CLI_ENV_OVERRIDE}, PATH, and the known "
            "install roots)"
        )
    return True, f"Claude Code CLI binary found at {binary}"


# ---------------------------------------------------------------------------
# Structured output over free text -- prompt-engineered, since the CLI has no native equivalent
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _schema_instructions(output_format: type[BaseModel]) -> str:
    schema_json = json.dumps(output_format.model_json_schema(), indent=2, sort_keys=True)
    return (
        "Respond with ONLY a single JSON object that validates against the following JSON Schema. "
        "Output the JSON object and nothing else -- no prose before or after it, and no markdown code "
        "fence.\n\nJSON Schema:\n" + schema_json
    )


def _extract_json(result_text: str) -> str:
    """`result_text` with a ```json fence stripped, if the model added one despite being told not to
    -- models do this reliably enough that tolerating it is cheaper than a second round trip. Text with
    no fence is returned trimmed and otherwise untouched; whether it is valid JSON is
    `output_format.model_validate_json`'s question, not this function's."""
    stripped = result_text.strip()
    match = _FENCE_RE.search(stripped)
    if match:
        stripped = match.group(1).strip()
    # A model told to emit ONLY a JSON object still sometimes emits the object and then keeps
    # writing -- a trailing "### What it would do next" section, a closing remark -- or opens with a
    # short "Here is the JSON:" preamble. Isolate the first complete JSON value with `raw_decode`,
    # which tracks string and escape boundaries correctly (so a `{` or `}` inside `report_md` never
    # confuses it), and drop whatever surrounds it -- the same category of deviation the ```json
    # fence stripping above already forgives, and extraction of a boundary rather than repair of the
    # JSON itself. Genuinely malformed or absent JSON falls through untouched, so
    # `output_format.model_validate_json` still raises the real error rather than a salvaged one.
    for i, ch in enumerate(stripped):
        if ch in "{[":
            try:
                _, end = json.JSONDecoder().raw_decode(stripped, i)
            except ValueError:
                break
            return stripped[i:end]
    return stripped


# ---------------------------------------------------------------------------
# The call itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CliCallResult[T: BaseModel]:
    """Everything `app.agents.client` needs to build an `AgentCall` record out of one CLI call.

    Deliberately not `AgentCall` itself -- this dataclass carries only what the envelope actually gave
    us; `call_id`, `created_at` and archiving are `client.py`'s job, exactly as they are for the SDK
    path, so a CLI call is archived through the identical `_archive_call` path and is auditable the
    same way an SDK call is.
    """

    parsed_output: T
    result_text: str
    """The model's raw `result` text, verbatim (including any ```json fence it added) -- kept
    separately from the parsed output for the same reason `client._raw_response_text` prefers the
    parsed JSON when one exists but keeps the raw text available: a caller archiving this call decides
    which one describes what actually happened."""
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    cost_usd: Decimal
    """`total_cost_usd` off the envelope, read as a `Decimal` via `str()` rather than passed through as
    the `float` the CLI's JSON actually is -- `Decimal(0.216336)` would carry that float's own binary
    rounding error into a figure this package treats as authoritative; `Decimal("0.216336")` does not.
    """
    stop_reason: str | None
    request_id: str | None
    """The CLI's `session_id`, standing in for the SDK response's `request_id` -- not the same kind of
    identifier (a CLI session, not an HTTP request), but it serves the identical purpose `AgentCall.
    request_id`'s own docstring names: something to hand upstream when reporting a failure."""


def _popen_kwargs() -> dict[str, Any]:
    """Platform-specific `Popen` kwargs that put the spawned process in its own process group/session,
    so `_kill_process_tree` can terminate the whole tree it roots -- not just the direct child -- on a
    timeout. See that function's own docstring for the concrete defect this exists to fix."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


#: Plain OS/shell plumbing the child needs to run at all -- never this application's own secrets.
#: `PATH` finds the interpreter (and, on Windows, `cmd.exe` for a `.cmd` npm shim -- see
#: `_kill_process_tree`'s docstring on why that shim can be what actually runs); `HOME`/`USERPROFILE`
#: is where Claude Code reads its own login (`~/.claude/.credentials.json`, this module's own
#: docstring); `TEMP`/`TMP` is where a CLI or its `node` runtime stages scratch files; `SYSTEMROOT`
#: is required for even a bare Windows process to start (DLL loading fails without it);
#: `APPDATA`/`LOCALAPPDATA`/`PROGRAMDATA` are where `_windows_install_roots` itself looks for the
#: binary, so the child inherits the same view of "where is Claude Code installed" this process
#: resolved it from; `COMSPEC`/`PATHEXT` are what actually lets Windows run a `.cmd` shim through
#: `cmd.exe` at all.
_INHERITED_ENV_VARS: Final[tuple[str, ...]] = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "COMSPEC",
    "PATHEXT",
)

#: The credential/endpoint variables the CLI itself may need -- see this module's own docstring on
#: the three places `anthropic.Anthropic()` (and, by the same convention, the CLI) can read a
#: credential from. Passed through by exact name; every other `CLAUDE_*` variable present in this
#: process's environment is also forwarded (see `_child_env`), since Claude Code defines more of its
#: own configuration variables than this module can enumerate and a future one should not have to be
#: added here by hand.
_INHERITED_CREDENTIAL_VARS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CONFIG_DIR",
)


def _child_env() -> dict[str, str]:
    """A minimal environment for the spawned CLI process -- everything it needs to run and
    authenticate, and nothing this application's own configuration carries.

    **The defect this closes.** `subprocess.Popen` with no `env=` argument inherits this whole
    process's environment verbatim, which includes every `INVDASH_*` setting -- among them
    `INVDASH_CONTACT_EMAIL`, API-adjacent secrets a deployment may have set as plain environment
    variables rather than in `.env`, and anything else a future `Settings` field adds. None of that
    is the CLI's business: it is a subprocess that answers one prompt and exits, not a part of this
    application, and hostname/credential leakage into the child process's own logs, crash reports, or
    (if it were ever compromised) a malicious tool call is a cost with no offsetting benefit -- the
    CLI already gets its model access through the credential variables named below.

    Builds the environment explicitly rather than filtering the inherited one, so a variable this
    function does not know about is excluded by default, not included by default -- an allow-list,
    the same posture `--allowedTools ""` takes in `call_structured` and for the identical reason
    given there: an omission fails safe, and a filter that admits anything not explicitly denied
    would silently start forwarding a new `INVDASH_*` field the day someone adds one.
    """
    env: dict[str, str] = {}
    for name in _INHERITED_ENV_VARS + _INHERITED_CREDENTIAL_VARS:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    # Every other `CLAUDE_*` variable present (profile selection, feature flags Claude Code defines
    # for itself) -- forwarded by prefix rather than enumerated by name, because this module cannot
    # keep pace with every configuration variable the CLI itself introduces, and the one thing this
    # prefix can never collide with is this application's own `INVDASH_` namespace.
    for name, value in os.environ.items():
        if name.startswith("CLAUDE_") and name not in env:
            env[name] = value
    return env


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate `process` and every descendant it spawned, not just the direct child.

    **The defect this fixes.** `resolve_cli_binary` can resolve a `.cmd` npm shim on Windows (found
    via `shutil.which` on a machine where Claude Code was installed through npm rather than the
    native installer) -- Windows runs a `.cmd` through `cmd.exe`, which execs `node.exe` as a
    grandchild that does the actual model call. Killing only the direct child (what a bare
    `Popen.kill()`, and the stdlib's own `subprocess.run(timeout=...)`, both do) kills the cmd.exe
    shim and leaves the node.exe grandchild running free -- it can complete the model call and spend
    real budget for a request this module has already told its caller timed out.

    Windows: there is no single Win32 API call for "kill this process and everything it spawned";
    `taskkill /F /T /PID` is the documented, reliable way to do it, and is what this uses.
    POSIX: `_popen_kwargs` above starts `process` in a new session, making it the leader of a new
    process group, so `os.killpg` signals every process in that group -- the child and anything it
    spawned -- without touching this server's own process group.

    Best-effort throughout: a process that has already exited (a race between the timeout firing and
    the process finishing on its own) raises `ProcessLookupError`/a non-zero `taskkill` exit, both
    swallowed here, since "already dead" is exactly the outcome this function is trying to reach.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        # `os.killpg`/`signal.SIGKILL` are POSIX-only -- absent from the Windows stubs mypy checks
        # against on this repo's own dev machine, hence the ignore. Never reached there at runtime
        # either: this whole branch is behind the `os.name == "nt"` check above. Suppressed error:
        # already gone, or never became a group leader -- `process.kill()` below still runs.
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
    with contextlib.suppress(OSError):
        process.kill()
    # Best effort -- nothing more this module can do if the OS itself will not reap it.
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5.0)


def _spawn(
    cmd: list[str], *, timeout: float, stdin_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """The one place this module launches the CLI process.

    Uses `Popen` directly rather than the simpler `subprocess.run(timeout=...)`, specifically so a
    timeout can kill the *whole process tree* the resolved binary roots, not just the direct child --
    see `_kill_process_tree`'s own docstring for the concrete defect that fixes (an npm `.cmd` shim
    surviving a call this module already reported as timed out, and spending budget on it). Callers
    see the identical contract `subprocess.run` gave them before this change: a
    `subprocess.CompletedProcess[str]` on success, `subprocess.TimeoutExpired` re-raised on timeout,
    and any `OSError` the spawn itself raised (binary missing, not executable, ...) propagating
    unchanged -- `call_structured`'s `except` clauses for both are untouched by this.

    `stdin_text`, when given, is the prompt, piped in and closed. `call_structured` passes the whole
    user turn this way rather than as a final argv entry because Windows caps a command line at ~32KB
    and the portfolio-manager stage, which aggregates every upstream summary, exceeds that and is
    rejected at spawn with WinError 206 -- a hard failure of the single most important call. Piped
    stdin has no such ceiling. When `stdin_text` is `None` the handle is `DEVNULL`, not inherited: an
    inherited stdin left attached makes the CLI wait, print ``Warning: no stdin data received in 3s``,
    and -- under a uvicorn worker on Windows -- sometimes exit non-zero, all artefacts of the handle
    rather than the call. Piping the prompt sidesteps that too: the CLI gets its data immediately and
    never waits.
    """
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=_child_env(),
        **_popen_kwargs(),
    )
    try:
        stdout, stderr = process.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        raise
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def call_structured[T: BaseModel](
    *,
    role: AgentRole,
    system: str,
    user: str,
    output_format: type[T],
    model: str,
    max_budget_usd: Decimal,
    effort: str = "high",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CliCallResult[T]:
    """One structured call through the Claude Code CLI, or `AgentUnavailable` naming exactly what went
    wrong.

    `role` is spelled out as the same three-value `Literal` `app.agents.client.call_structured` and
    `app.agents.models.AgentCall.role` both use, rather than imported from a shared alias -- restating
    `AgentCall.role`'s own docstring, this is a closed contract duplicated in three places on purpose,
    so a fourth role is an edit here too, not a silent gap.

    Never repairs a malformed response and never substitutes a default: a response that will not parse
    as the envelope, or whose `result` will not validate against `output_format`, raises
    `AgentUnavailable` with the raw text included in the message -- see this module's own docstring for
    why that is the same rule the SDK path already follows.
    """
    binary = resolve_cli_binary()
    if binary is None:
        _, reason = is_available()
        raise AgentUnavailable(reason)

    augmented_user = f"{user}\n\n{_schema_instructions(output_format)}"

    cmd = [
        str(binary),
        "--print",
        "--output-format", "json",
        "--model", model,
        "--effort", effort,
        "--system-prompt", system,
        "--exclude-dynamic-system-prompt-sections",
        # An explicit empty allow-list, not an enumerated `--disallowedTools` -- see this module's own
        # docstring on why an allow-list of nothing is the one form that stays correct as the CLI grows
        # new tools this package has never heard of.
        "--allowedTools", "",
        "--max-budget-usd", str(max_budget_usd),
    ]
    # The prompt goes on stdin, NOT as a final argv entry: a late-pipeline agent (the portfolio
    # manager, which receives every upstream summary) builds a user turn tens of KB long, and Windows'
    # ~32KB total command-line limit rejects the spawn outright with WinError 206 -- a hard, repeatable
    # failure of exactly the largest, most important call. `claude --print` reads the prompt from a
    # piped stdin (verified), which has no such ceiling; `_spawn` closes stdin otherwise.

    try:
        completed = _spawn(cmd, timeout=timeout, stdin_text=augmented_user)
    except subprocess.TimeoutExpired as exc:
        raise AgentUnavailable(
            f"Claude Code CLI call for {role} timed out after {timeout:g}s and was killed"
        ) from exc
    except OSError as exc:
        raise AgentUnavailable(f"failed to spawn Claude Code CLI at {binary}: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:2000]
        # A non-zero exit *after* the binary resolved and ran is call-specific, not systemic: a fatal
        # misconfiguration (bad flag, missing binary) would fail every call, but the transport that
        # reached this line has already carried other calls in this same process. So it is a transient
        # model/API error the same request usually clears on a retry -- `AgentTransientError`, which
        # `agentdesk.grounding.run_grounded` re-attempts, rather than the base `AgentUnavailable` that
        # fails the whole stage on one blip.
        raise AgentTransientError(
            f"Claude Code CLI exited {completed.returncode} for {role}: {detail or '(no output)'}"
        )

    try:
        envelope: dict[str, Any] = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AgentUnavailable(
            f"Claude Code CLI stdout for {role} was not valid JSON: {exc}; raw stdout: "
            f"{completed.stdout[:2000]!r}"
        ) from exc

    if envelope.get("is_error"):
        # The CLI itself ran fine (exit 0, valid envelope) but the model/API call inside it errored --
        # an overloaded backend, a transient 5xx. Retryable for the same reason as the non-zero-exit
        # case above: it is this one call that failed, not the transport.
        raise AgentTransientError(
            f"Claude Code CLI reported is_error=true for {role}: "
            f"{str(envelope.get('result', ''))[:2000]}"
        )

    stop_reason = envelope.get("stop_reason")
    if stop_reason == "refusal":
        raise AgentUnavailable(f"model refused the {role} request via the Claude Code CLI")

    result_text = str(envelope.get("result", ""))
    json_text = _extract_json(result_text)
    try:
        parsed_output = output_format.model_validate_json(json_text)
    except ValueError as exc:
        # `pydantic.ValidationError` is itself a `ValueError` subclass, and a `result` that is not even
        # syntactically JSON also raises through this same path (pydantic's own JSON parser, not
        # `json.loads`) -- one `except` covers both, and either way this call is refused whole rather
        # than salvaged, per this module's own "validate, never repair" section above. Raised as
        # `AgentResponseInvalid` (an `AgentUnavailable` subclass, so every existing `except
        # AgentUnavailable` still catches it) so a caller that can re-ask -- `agentdesk.grounding.
        # run_grounded` -- retries this transient formatting lapse rather than failing a whole pipeline
        # on one malformed turn; a caller that cannot still degrades exactly as before.
        raise AgentResponseInvalid(
            f"Claude Code CLI response for {role} did not parse as {output_format.__name__}: {exc}; "
            f"raw response: {result_text[:4000]!r}"
        ) from exc

    usage = envelope.get("usage") or {}
    cost_usd = Decimal(str(envelope.get("total_cost_usd", 0)))

    return CliCallResult(
        parsed_output=parsed_output,
        result_text=result_text,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
        cost_usd=cost_usd,
        stop_reason=stop_reason,
        request_id=envelope.get("session_id"),
    )
