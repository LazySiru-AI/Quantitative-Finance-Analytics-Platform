"""Tests for `app.agents.cli_transport`, plus the CLI-routing seams it adds to `app.agents.client`.

**Why this file exists at all.** `cli_transport.py` shipped with the client and models it plugs into
already wired up (`client.py` calls `cli_transport.is_available()` and `cli_transport.call_structured`
from three places; `models.py`'s `CredentialSource` already carries `"cli"`) but with no test coverage
of its own -- the worker who wrote it did not get to write tests before the session ended. Everything
below is new; nothing in `cli_transport.py` was assumed correct going in, and two real defects were
found and are documented at the bottom of `TestLiveClaudeCodeCli` and above `TestCliCommandConstruction`
respectively -- search this file for "DEFECT" to find both.

**Two boundaries, mirroring `tests/test_agents_designer.py`'s own split.** That file's docstring
explains its two-boundary approach for the SDK transport (fake `sys.modules["anthropic"]` at the
client boundary, monkeypatched `call_structured` at the designer boundary); this file needs the same
shape for a second transport:

* `TestResolveCliBinary`, `TestIsAvailable` and `TestCliCallStructured*` monkeypatch
  `app.agents.cli_transport.subprocess.Popen` (never the real binary) and, for the resolution tests,
  `app.agents.cli_transport.shutil.which` plus `APPDATA`/`LOCALAPPDATA` -- `Popen` is the seam
  `cli_transport._spawn` now spawns through, having moved off `subprocess.run(timeout=...)` so a
  timeout can kill the whole process tree the resolved binary roots, not just the direct child.
* `TestClientRouting` and `TestClientArchivesCliCall` monkeypatch `app.agents.client.cli_transport.
  call_structured` directly (the CLI analogue of faking `messages.parse`), since what those tests prove
  -- which transport wins, and that a CLI call is archived exactly like an SDK one -- sits above the
  subprocess boundary and does not need a fake binary at all.
* `TestLiveClaudeCodeCli`, gated behind `INVDASH_LIVE_AGENT_TEST`, is the only place in this file (or
  in this package) that spawns the real `claude.exe` on this machine. See its own docstring for why a
  green mocked suite does not stand in for this: the sibling reviewer-role gap in this same package
  (`tests/test_agents_reviewer.py`'s `TestReviewerRoleLiteralGap`) shipped with every unit test green
  while the real call path raised `pydantic.ValidationError` on an unwidened `Literal`, and nothing
  short of a real call would have caught it.

**Isolating binary resolution from the machine actually running this suite.** This machine has three
real Claude Code CLI installs (`2.1.234`, `2.1.237`, `2.1.246`) and, depending on the shell, may or may
not see `claude` on `PATH`. Every resolution test therefore runs under the `isolated_cli_roots` fixture,
which points `APPDATA`/`LOCALAPPDATA` at empty directories under `tmp_path` and monkeypatches
`shutil.which` to `None`, so a test that builds exactly one fake `claude.exe` is proving something about
`resolve_cli_binary`'s logic, not accidentally passing because the real install was still reachable
underneath it. `TestLiveClaudeCodeCli` is the one place that must NOT use this fixture -- it needs the
real roots, to resolve the real binary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.agents import cli_transport
from app.agents import client as client_module
from app.agents.cli_transport import CliCallResult
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentCall,
    AgentUnavailable,
    BudgetExhausted,
    agent_calls_dir,
)
from app.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """A `Settings` rooted entirely under `tmp_path` -- never the real `data/`, matching
    `tests/test_agents_designer.py`'s own fixture."""
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        store_dir=tmp_path / "store",
        cache_dir=tmp_path / "cache",
    )


@pytest.fixture(autouse=True)
def _hermetic_anthropic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test starts with no *SDK* credential, regardless of what is actually set on the machine
    running the suite -- copied verbatim from `tests/test_agents_designer.py` and
    `tests/test_agents_reviewer.py`'s own fixture of the same name, since this file needs the identical
    guarantee: a developer's own `ANTHROPIC_API_KEY` must never leak in and silently route a test down
    the SDK path this file is not testing.

    Deliberately does **not** touch `INVDASH_CLAUDE_CLI`, `APPDATA`, `LOCALAPPDATA` or `PATH` -- those
    are `cli_transport`'s own resolution inputs, isolated separately by `isolated_cli_roots` only where
    a test actually needs that isolation, so this fixture's job stays narrowly "no SDK credential" and
    nothing more.
    """
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic-config-unused"))


@pytest.fixture()
def isolated_cli_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Blanks every input `resolve_cli_binary` reads -- `INVDASH_CLAUDE_CLI`, `PATH` (via
    `shutil.which`), `APPDATA`, `LOCALAPPDATA` -- and points the two Windows env vars at empty
    directories under `tmp_path`. A test using this fixture is proving something about
    `cli_transport`'s own resolution *logic*; without it, the three real installs on this machine
    would make almost any "binary found" assertion trivially true for the wrong reason.

    Returns `tmp_path` so a test can build `tmp_path / "AppData" / "Roaming" / "Claude" /
    "claude-code" / <version> / "claude.exe"` (or the `LOCALAPPDATA` / `Packages` equivalent) without
    recomputing the base itself.
    """
    monkeypatch.delenv(cli_transport._CLI_ENV_OVERRIDE, raising=False)
    monkeypatch.setattr(cli_transport.shutil, "which", lambda name: None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    return tmp_path


def _make_binary(path: Path) -> Path:
    """An empty file at `path`, with its parent directories created -- `resolve_cli_binary` only ever
    checks `is_file()`, so an empty placeholder is indistinguishable from a real binary to every test
    in this file that never actually spawns it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _appdata_root(tmp_path: Path) -> Path:
    """`%APPDATA%\\Claude\\claude-code`, given the same `tmp_path` `isolated_cli_roots` pointed
    `APPDATA` at."""
    return tmp_path / "AppData" / "Roaming" / "Claude" / "claude-code"


def _localappdata_package_root(tmp_path: Path, package_id: str = "Claude_test0000") -> Path:
    """`%LOCALAPPDATA%\\Packages\\<package_id>\\LocalCache\\Roaming\\Claude\\claude-code` -- the
    non-virtualised root, whose `<package_id>` this module's own docstring is explicit is never a
    hardcoded constant. Defaulted here to an obviously-fake id so a test that does not care about the
    id's exact value does not have to invent one."""
    return (
        tmp_path
        / "AppData"
        / "Local"
        / "Packages"
        / package_id
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude-code"
    )


class _DummyOutput(BaseModel):
    """A trivial `output_format` for tests that never inspect the parsed content."""

    value: str = "x"


class _Widget(BaseModel):
    """A two-field `output_format` for tests that DO inspect the parsed content, standing in for the
    kind of small structured response `app.agents.designer`/`reviewer` actually ask for."""

    ok: bool
    count: int


def _make_cli_result(**overrides: Any) -> CliCallResult[Any]:
    defaults: dict[str, Any] = {
        "parsed_output": _DummyOutput(value="hello"),
        "result_text": '{"value": "hello"}',
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cost_usd": Decimal("0.01"),
        "stop_reason": "end_turn",
        "request_id": "sess-fake-0001",
    }
    defaults.update(overrides)
    return CliCallResult(**defaults)


def _install_fake_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: subprocess.CompletedProcess[str] | None = None,
    raises: BaseException | None = None,
) -> dict[str, Any]:
    """Replaces `cli_transport.subprocess.Popen` -- the seam `cli_transport._spawn` now spawns through
    (`Popen` + `.communicate(timeout=...)`, so a timeout can kill the whole process tree, not just the
    direct child) -- with a fake `Popen`-like object, and records the `cmd` list and kwargs it was
    constructed with so a test can inspect exactly what would have been spawned.

    The fake faithfully reproduces each seam behaviour the old `subprocess.run`-based helper did:

    * a `result` is surfaced by `.communicate()` as its `(stdout, stderr)`, with `result.returncode`
      exposed as `.returncode` -- exactly what `_spawn` reads back to build its `CompletedProcess`;
    * an `OSError` in `raises` is raised from *constructing* the fake `Popen`, mirroring a real spawn
      failure (binary missing/not executable) that `subprocess.Popen` itself raises before any process
      exists;
    * a `subprocess.TimeoutExpired` (or any other non-`OSError`) in `raises` is raised from
      `.communicate()`, mirroring the real timeout path `_spawn` catches, cleans up after, and re-raises.
    """
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, cmd: list[str], **kwargs: Any) -> None:
            # Monkeypatching `cli_transport.subprocess.Popen` patches the stdlib subprocess module's
            # `Popen` globally, so `_kill_process_tree`'s own `subprocess.run(["taskkill", ...])` on the
            # timeout path re-enters this fake too. That cleanup spawn is not the call under test: treat
            # it as a trivially-successful process (and never let it clobber the captured CLI argv).
            self.args = cmd  # real Popen exposes this; subprocess.run reads it for its CompletedProcess
            self._is_cleanup = bool(cmd) and cmd[0] == "taskkill"
            if self._is_cleanup:
                self.pid = 0
                self.returncode = 0
                return
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            if isinstance(raises, OSError):
                # A real spawn failure raises here, from Popen's own construction, before any child
                # process exists -- so `_spawn`'s `try`/`except TimeoutExpired` never even runs.
                raise raises
            self.pid = 424242  # never a real pid; `_kill_process_tree`'s taskkill/kill are no-ops on it
            self.returncode: int | None = result.returncode if result is not None else None

        def __enter__(self) -> _FakePopen:  # subprocess.run() drives its Popen as a context manager
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

        def communicate(
            self, input: str | None = None, timeout: float | None = None
        ) -> tuple[str, str]:
            if self._is_cleanup:
                return "", ""
            captured["stdin"] = input  # the prompt is piped here now, not passed as a final argv entry
            if raises is not None and not isinstance(raises, OSError):
                raise raises
            assert result is not None
            self.returncode = result.returncode
            return result.stdout, result.stderr

        def kill(self) -> None:  # called by `_kill_process_tree` on the timeout path
            pass

        def poll(self) -> int | None:  # subprocess.run() reads the taskkill retcode via poll()
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode if self.returncode is not None else 0

    monkeypatch.setattr(cli_transport.subprocess, "Popen", _FakePopen)
    return captured


def _forbid_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces `cli_transport.subprocess.Popen` with a fake that fails the test the instant it is
    constructed -- used to prove a code path (budget exhausted, no binary resolved, SDK preferred over
    CLI) never reaches the point of spawning a process at all, the same `fail_if_called` technique
    `tests/test_agents_designer.py`'s `test_focus_avoid_overlap_raises_before_calling_model` uses for
    the SDK side."""

    class _ForbiddenPopen:
        def __init__(self, cmd: list[str], **kwargs: Any) -> None:
            raise AssertionError(f"subprocess.Popen must not be called here; got cmd={cmd!r}")

    monkeypatch.setattr(cli_transport.subprocess, "Popen", _ForbiddenPopen)


def _envelope(**overrides: Any) -> dict[str, Any]:
    """A `--output-format json` envelope, shaped like the real sample recorded in this module's own
    docstring (`is_error`, `duration_api_ms`, `usage`, `total_cost_usd`, `result`, ...), with sane
    defaults a test only has to override what it cares about."""
    defaults: dict[str, Any] = {
        "is_error": False,
        "duration_api_ms": 2769,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "session_id": "sess-abc123",
        "total_cost_usd": 0.0863286,
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 12569,
            "cache_read_input_tokens": 32392,
            "output_tokens": 15,
        },
        "result": '{"ok": true, "count": 5}',
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# resolve_cli_binary -- version comparison, both Windows roots, the env override
# ---------------------------------------------------------------------------


class TestResolveCliBinary:
    def test_no_root_present_returns_none(self, isolated_cli_roots: Path) -> None:
        assert cli_transport.resolve_cli_binary() is None

    def test_version_comparison_is_numeric_not_lexicographic(self, isolated_cli_roots: Path) -> None:
        """`"2.1.9" < "2.1.10"` as strings is `False` (`"9" > "1"` character-wise) -- a string sort
        would rank the patch-9 release above patch-10, the exact bug this module's own docstring
        calls out `_parse_version` exists to route around. Both directories are seeded so a
        regression back to string comparison would resolve to `2.1.9`'s binary instead."""
        root = _appdata_root(isolated_cli_roots)
        older = _make_binary(root / "2.1.9" / "claude.exe")
        newer = _make_binary(root / "2.1.10" / "claude.exe")

        resolved = cli_transport.resolve_cli_binary()

        assert resolved == newer
        assert resolved != older

    def test_appdata_root_alone_is_found(self, isolated_cli_roots: Path) -> None:
        binary = _make_binary(_appdata_root(isolated_cli_roots) / "2.1.100" / "claude.exe")
        assert cli_transport.resolve_cli_binary() == binary

    def test_localappdata_packages_root_alone_is_found(self, isolated_cli_roots: Path) -> None:
        """The MSIX-virtualised `%APPDATA%` root is entirely absent here -- only the
        `%LOCALAPPDATA%\\Packages\\Claude_*\\...` root has anything under it -- so this proves that
        root is searched on its own, not merely as a fallback tie-breaker against the other."""
        binary = _make_binary(_localappdata_package_root(isolated_cli_roots) / "2.1.50" / "claude.exe")
        assert cli_transport.resolve_cli_binary() == binary

    def test_both_windows_roots_are_searched_and_highest_across_both_wins(
        self, isolated_cli_roots: Path
    ) -> None:
        """Searching only one root is the real bug this module's own docstring names as presenting
        as a false "not installed" -- and a version-tuple comparison that only compares *within* a
        root, rather than across all roots combined, would silently prefer whichever root happens to
        be scanned first even when the other holds a newer release. This seeds a *lower* version
        under the root searched first (`%APPDATA%`) and a *higher* one under the root searched
        second (`%LOCALAPPDATA%\\Packages\\...`), so only a correct global-max implementation picks
        the second root's binary."""
        _make_binary(_appdata_root(isolated_cli_roots) / "2.1.5" / "claude.exe")
        newer = _make_binary(_localappdata_package_root(isolated_cli_roots) / "2.1.20" / "claude.exe")

        assert cli_transport.resolve_cli_binary() == newer

    def test_multiple_package_ids_under_localappdata_are_all_globbed(self, isolated_cli_roots: Path) -> None:
        """`Claude_<id>` is a Windows-Store-assigned suffix, never a constant -- a machine that has
        been reinstalled under a new package identity can have more than one `Claude_*` directory.
        Only the second one seeded here holds a binary, so this fails if the glob stops at the first
        `Claude_*` entry it finds."""
        empty_package_root = _localappdata_package_root(isolated_cli_roots, package_id="Claude_old0000")
        empty_package_root.mkdir(parents=True, exist_ok=True)
        binary = _make_binary(
            _localappdata_package_root(isolated_cli_roots, package_id="Claude_new1111") / "2.1.1" / "claude.exe"
        )

        assert cli_transport.resolve_cli_binary() == binary

    def test_env_override_wins_over_path_and_both_install_roots(
        self, isolated_cli_roots: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`INVDASH_CLAUDE_CLI` is trusted at face value even though it need not exist -- a caller who
        set it gets exactly that path, per this module's own docstring on why a typo should fail
        loudly rather than silently falling through to whichever install happens to be highest
        version. A much newer version is seeded under both real roots to prove the override is not
        merely winning because nothing else was found."""
        _make_binary(_appdata_root(isolated_cli_roots) / "9.9.999" / "claude.exe")
        _make_binary(_localappdata_package_root(isolated_cli_roots) / "9.9.999" / "claude.exe")
        override_path = isolated_cli_roots / "custom" / "claude.exe"  # deliberately never created
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, str(override_path))

        assert cli_transport.resolve_cli_binary() == override_path

    def test_env_override_beats_path_too(
        self, isolated_cli_roots: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        override_path = isolated_cli_roots / "custom" / "claude.exe"
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, str(override_path))
        monkeypatch.setattr(cli_transport.shutil, "which", lambda name: r"C:\somewhere\claude.exe")

        assert cli_transport.resolve_cli_binary() == override_path


# ---------------------------------------------------------------------------
# is_available -- the transport's own health check
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_no_binary_reports_unavailable_naming_what_it_checked(self, isolated_cli_roots: Path) -> None:
        available, reason = cli_transport.is_available()
        assert available is False
        assert cli_transport._CLI_ENV_OVERRIDE in reason
        assert "PATH" in reason
        assert "install roots" in reason

    def test_binary_found_reports_available_with_its_path(self, isolated_cli_roots: Path) -> None:
        binary = _make_binary(_appdata_root(isolated_cli_roots) / "2.1.1" / "claude.exe")
        available, reason = cli_transport.is_available()
        assert available is True
        assert str(binary) in reason


# ---------------------------------------------------------------------------
# cli_transport.call_structured -- never spawns the real binary; subprocess.run is monkeypatched
# ---------------------------------------------------------------------------


class TestCliCallStructuredMissingBinary:
    def test_missing_binary_raises_agent_unavailable_never_file_not_found(
        self, isolated_cli_roots: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _forbid_run(monkeypatch)  # proves this path never reaches subprocess.run at all

        with pytest.raises(AgentUnavailable, match="no Claude Code CLI binary found"):
            cli_transport.call_structured(
                role="designer",
                system="s",
                user="u",
                output_format=_DummyOutput,
                model=DEFAULT_MODEL,
                max_budget_usd=Decimal("1.00"),
            )


class TestCliCommandConstruction:
    """The three flags this module's own docstring calls load-bearing for keeping a CLI call a *pure
    model call* -- `--allowedTools ""`, no `--dangerously-skip-permissions`, `--system-prompt` (not
    `--append-system-prompt`) -- proven present (or absent) in the literal argv list, not merely
    described in prose. A regression here would silently hand a future CLI release tool access this
    package's own docstring says must never exist.
    """

    def test_argv_carries_the_safety_flags_and_no_more(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        captured = _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(_envelope()), stderr=""
            ),
        )

        cli_transport.call_structured(
            role="scout",
            system="SYSTEM TEXT",
            user="USER TEXT",
            output_format=_Widget,
            model="claude-sonnet-5",
            max_budget_usd=Decimal("2.50"),
        )

        cmd = captured["cmd"]
        assert cmd[0] == r"C:\fake\claude.exe"
        assert "--print" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "json"
        assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5"
        assert cmd[cmd.index("--system-prompt") + 1] == "SYSTEM TEXT"
        assert "--append-system-prompt" not in cmd
        assert "--exclude-dynamic-system-prompt-sections" in cmd
        assert cmd[cmd.index("--allowedTools") + 1] == ""
        assert "--dangerously-skip-permissions" not in cmd
        assert cmd[cmd.index("--max-budget-usd") + 1] == "2.50"
        # The prompt is NOT an argv entry -- it is piped on stdin, so Windows' ~32KB command-line
        # limit cannot reject a large late-pipeline turn (WinError 206). The last argv token is the
        # final flag value, never the user text.
        assert not any("USER TEXT" in part for part in cmd)
        # The user turn, augmented with the JSON schema instructions, arrives on stdin instead --
        # never spliced into --system-prompt, per this module's own docstring on why that stays
        # untouched.
        assert captured["stdin"].startswith("USER TEXT")
        assert "JSON Schema" in captured["stdin"]

    def test_child_env_carries_no_invdash_vars_but_keeps_path_and_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect this guards: `Popen` with no `env=` inherits this whole process's environment,
        `INVDASH_*` settings included -- so a spawned CLI child would see every `Settings` field a
        deployment happens to have set as a plain environment variable, none of which is the CLI's
        business. `_child_env` must build an explicit allow-list instead: nothing starting with
        `INVDASH_`, but still `PATH` (needed to run at all) and the SDK-style credential variables
        the CLI itself can authenticate with."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        monkeypatch.setenv("INVDASH_CONTACT_EMAIL", "secret@example.com")
        monkeypatch.setenv("INVDASH_FRED_API_KEY", "shh-do-not-leak")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", r"C:\fake\claude-config")
        captured = _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(_envelope()), stderr=""
            ),
        )

        cli_transport.call_structured(
            role="scout", system="s", user="u", output_format=_Widget,
            model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
        )

        env = captured["kwargs"]["env"]
        assert not any(name.startswith("INVDASH_") for name in env), env
        assert "PATH" in env
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test-key"  # pragma: allowlist secret
        assert env["CLAUDE_CONFIG_DIR"] == r"C:\fake\claude-config"

    def test_the_prompt_is_piped_on_stdin_not_passed_as_an_argv_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Windows caps a command line at ~32KB. The portfolio-manager stage aggregates every upstream
        # summary into a user turn tens of KB long, so passing it as a final argv entry rejected the
        # spawn outright with WinError 206 -- a hard failure of the most important call. `claude
        # --print` reads a piped stdin, which has no such ceiling, so the transport opens stdin as a
        # PIPE and sends the whole prompt through it. A left-attached stdin would stall the CLI ~3s
        # ("no stdin data received in 3s"); piping the data immediately avoids that too.
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        captured = _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(_envelope()), stderr=""
            ),
        )

        big_user = "USER TEXT " + "x" * 40000  # larger than Windows' argv ceiling on purpose
        cli_transport.call_structured(
            role="scout",
            system="SYSTEM TEXT",
            user=big_user,
            output_format=_Widget,
            model="claude-sonnet-5",
            max_budget_usd=Decimal("2.50"),
        )

        assert captured["kwargs"]["stdin"] is subprocess.PIPE
        assert captured["stdin"].startswith(big_user)  # the whole turn went through the pipe
        assert not any(big_user in part for part in captured["cmd"])  # and nothing that big in argv


class TestCliCallStructuredSuccess:
    def test_valid_envelope_parses_and_cost_is_decimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        envelope = _envelope()
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope), stderr=""
            ),
        )

        result = cli_transport.call_structured(
            role="designer",
            system="s",
            user="u",
            output_format=_Widget,
            model=DEFAULT_MODEL,
            max_budget_usd=Decimal("1.00"),
        )

        assert result.parsed_output == _Widget(ok=True, count=5)
        assert result.input_tokens == 2
        assert result.output_tokens == 15
        assert result.cache_creation_input_tokens == 12569
        assert result.cache_read_input_tokens == 32392
        assert result.stop_reason == "end_turn"
        assert result.request_id == "sess-abc123"
        # The point of this test: a Decimal built from str(total_cost_usd), never the bare float --
        # Decimal(0.0863286) would carry that float's own binary rounding error into a figure this
        # package treats as authoritative for the budget cap, per cli_transport's own docstring.
        assert type(result.cost_usd) is Decimal
        assert result.cost_usd == Decimal("0.0863286")

    def test_json_fenced_result_still_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Models add a ```json fence even when explicitly told not to -- this module's own docstring
        says so, and `_extract_json` exists to tolerate it rather than round-tripping a second call."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        envelope = _envelope(result='```json\n{"ok": true, "count": 5}\n```')
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope), stderr=""
            ),
        )

        result = cli_transport.call_structured(
            role="designer",
            system="s",
            user="u",
            output_format=_Widget,
            model=DEFAULT_MODEL,
            max_budget_usd=Decimal("1.00"),
        )
        assert result.parsed_output == _Widget(ok=True, count=5)
        # result_text keeps the fence verbatim -- only the parsing step strips it.
        assert "```" in result.result_text

    def test_trailing_prose_after_the_json_object_still_parses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model told to emit ONLY a JSON object sometimes emits the object and then keeps writing
        -- an analyst report that closes its JSON and appends a `### What it would do next` section.
        `_extract_json` isolates the first complete JSON value so the trailing prose is dropped rather
        than failing the whole call with 'trailing characters at line 2 column 1' (the real defect
        this guards). The `}` inside the string must not confuse the boundary scan."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        trailing = (
            '{"ok": true, "count": 5}\n\n'
            "### What it would do next\nHold and reassess against the 200-day. }"
        )
        envelope = _envelope(result=trailing)
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope), stderr=""
            ),
        )

        result = cli_transport.call_structured(
            role="designer",
            system="s",
            user="u",
            output_format=_Widget,
            model=DEFAULT_MODEL,
            max_budget_usd=Decimal("1.00"),
        )
        assert result.parsed_output == _Widget(ok=True, count=5)


class TestCliCallStructuredFailureModes:
    """Every failure mode `call_structured`'s own docstring lists, each proven to raise
    `AgentUnavailable` and nothing else -- no `FileNotFoundError`, no `subprocess.TimeoutExpired`, no
    `pydantic.ValidationError` escaping to a caller that only ever catches `AgentUnavailable`."""

    def test_is_error_true_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        envelope = _envelope(is_error=True, result="internal error: request failed")
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope), stderr=""
            ),
        )

        with pytest.raises(AgentUnavailable, match="is_error=true") as exc_info:
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
            )
        assert "internal error" in str(exc_info.value)

    def test_nonzero_exit_code_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="boom: bad flag"),
        )

        with pytest.raises(AgentUnavailable, match="exited 2") as exc_info:
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
            )
        assert "boom: bad flag" in str(exc_info.value)

    def test_unparseable_envelope_raises_with_raw_stdout_in_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The outer envelope itself (not the model's `result` field) fails `json.loads` -- e.g. a
        CLI crash that dumped a stack trace to stdout instead of `--output-format json`'s envelope.
        Never repaired, never defaulted: the raw text must appear verbatim in the raised message."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Traceback (most recent call last): boom", stderr=""
            ),
        )

        with pytest.raises(AgentUnavailable, match="not valid JSON") as exc_info:
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
            )
        assert "Traceback (most recent call last): boom" in str(exc_info.value)

    def test_result_not_matching_schema_raises_with_raw_response_in_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The envelope itself is valid JSON, but the model's `result` field is not `_Widget`-shaped
        -- the inner "validate, never repair" step this module's own docstring describes."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        envelope = _envelope(result='{"ok": "not-a-bool"}')
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope), stderr=""
            ),
        )

        with pytest.raises(AgentUnavailable, match="did not parse as _Widget") as exc_info:
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
            )
        assert "not-a-bool" in str(exc_info.value)

    def test_refusal_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        envelope = _envelope(stop_reason="refusal", result="")
        _install_fake_run(
            monkeypatch,
            result=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope), stderr=""
            ),
        )

        with pytest.raises(AgentUnavailable, match="refused"):
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
            )

    def test_timeout_raises_agent_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`.communicate(timeout=...)` raises `TimeoutExpired`; `_spawn` catches it, kills the whole
        process tree via `_kill_process_tree`, and re-raises -- this test proves the catch-and-convert
        to `AgentUnavailable`, not the tree-kill itself (the fake process's `kill`/`wait` are no-ops
        and `_kill_process_tree`'s taskkill runs harmlessly against a pid that does not exist)."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        _install_fake_run(
            monkeypatch, raises=subprocess.TimeoutExpired(cmd=["claude"], timeout=300.0)
        )

        with pytest.raises(AgentUnavailable, match="timed out") as exc_info:
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"), timeout=300.0,
            )
        assert "300" in str(exc_info.value)

    def test_spawn_failure_raises_agent_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A resolved path that turns out not to be executable (permissions, a corrupted install) --
        `subprocess.Popen` itself raises `OSError` from construction in that case, before any process
        exists to kill or any timeout can fire."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        _install_fake_run(monkeypatch, raises=OSError("[WinError 5] Access is denied"))

        with pytest.raises(AgentUnavailable, match="failed to spawn") as exc_info:
            cli_transport.call_structured(
                role="designer", system="s", user="u", output_format=_Widget,
                model=DEFAULT_MODEL, max_budget_usd=Decimal("1.00"),
            )
        assert "Access is denied" in str(exc_info.value)


# ---------------------------------------------------------------------------
# app.agents.client routing -- SDK preferred, CLI as fallback; both audited identically
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, **kwargs: Any) -> None:
        self.input_tokens = kwargs.get("input_tokens", 100)
        self.output_tokens = kwargs.get("output_tokens", 50)
        self.cache_read_input_tokens = kwargs.get("cache_read_input_tokens", 0)
        self.cache_creation_input_tokens = kwargs.get("cache_creation_input_tokens", 0)


class _FakeResponse:
    def __init__(self, *, parsed_output: Any, stop_reason: str = "end_turn") -> None:
        self.parsed_output = parsed_output
        self.usage = _FakeUsage()
        self.stop_reason = stop_reason
        self._request_id = "req_fake_sdk_0001"
        self.content = ()
        self.stop_details = None


class _FakeMessages:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def parse(self, **kwargs: Any) -> _FakeResponse:
        return self._response


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> None:
    """A minimal fake `anthropic` module, installed into `sys.modules` -- the same trick
    `tests/test_agents_designer.py` uses, duplicated (not imported) here per that file's own
    docstring on why each test module keeps its own copy rather than sharing one."""
    from types import SimpleNamespace

    class _FakeAnthropicClient:
        def __init__(self, *, timeout: float | None = None) -> None:
            self.messages = _FakeMessages(response)

    module = SimpleNamespace(
        Anthropic=_FakeAnthropicClient,
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        PermissionDeniedError=type("PermissionDeniedError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        BadRequestError=type("BadRequestError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {"status_code": 500}),
    )
    monkeypatch.setitem(sys.modules, "anthropic", module)


class TestClientRouting:
    def test_cli_only_is_available_and_named_by_credential_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")

        assert client_module.credential_source() == "cli"
        available, reason = client_module.is_available()
        assert available is True
        assert "Claude Code CLI" in reason

    def test_neither_available_names_both_reasons(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No SDK credential (autouse fixture) and no CLI binary at all.
        monkeypatch.delenv(cli_transport._CLI_ENV_OVERRIDE, raising=False)
        monkeypatch.setattr(cli_transport.shutil, "which", lambda name: None)
        monkeypatch.setenv("APPDATA", "")
        monkeypatch.setenv("LOCALAPPDATA", "")

        available, reason = client_module.is_available()
        assert available is False
        assert "no usable Anthropic credential" in reason
        assert "Claude Code CLI" in reason

    def test_sdk_preferred_when_both_are_available(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """`call_structured`'s own docstring states the SDK wins whenever both transports are usable
        (lower latency, no subprocess spawn) -- confirmed here by making both available at once and
        proving the CLI subprocess boundary is never touched, rather than trusting the docstring."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        _forbid_run(monkeypatch)  # the CLI's own subprocess boundary must never be reached

        available, reason = client_module.is_available()
        assert available is True
        assert reason == "credential resolved via ANTHROPIC_API_KEY"
        assert client_module.credential_source() == "api_key"

        response = _FakeResponse(parsed_output=_DummyOutput(value="via-sdk"))
        _install_fake_anthropic(monkeypatch, response)

        parsed, call, _budget = client_module.call_structured(
            role="designer",
            system="s",
            user="u",
            output_format=_DummyOutput,
            settings=settings,
            budget=AgentBudget(cap_usd=Decimal("10.00")),
        )
        assert parsed.value == "via-sdk"
        assert call.request_id == "req_fake_sdk_0001"

    def test_cli_used_as_fallback_when_sdk_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        fake_result = _make_cli_result(parsed_output=_DummyOutput(value="via-cli"))
        captured: dict[str, Any] = {}

        def fake_cli_call_structured(**kwargs: Any) -> CliCallResult[Any]:
            captured.update(kwargs)
            return fake_result

        monkeypatch.setattr(client_module.cli_transport, "call_structured", fake_cli_call_structured)

        budget = AgentBudget(cap_usd=Decimal("10.00"))
        parsed, _call, new_budget = client_module.call_structured(
            role="designer", system="s", user="u", output_format=_DummyOutput,
            settings=settings, budget=budget,
        )

        assert parsed.value == "via-cli"
        assert captured["role"] == "designer"
        # The second, process-level ceiling client.py's own docstring describes: budget.remaining_usd,
        # not budget.cap_usd, is what a CLI call is handed.
        assert captured["max_budget_usd"] == budget.remaining_usd
        assert new_budget.spent_usd == fake_result.cost_usd
        assert new_budget.calls == 1


class TestBudgetExhaustedNeverSpawns:
    def test_exhausted_budget_raises_before_touching_the_cli_at_all(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        _forbid_run(monkeypatch)
        budget = AgentBudget(cap_usd=Decimal("1.00"), spent_usd=Decimal("1.00"))

        with pytest.raises(BudgetExhausted):
            client_module.call_structured(
                role="designer", system="s", user="u", output_format=_DummyOutput,
                settings=settings, budget=budget,
            )
        # Nothing archived -- the budget check happens before either transport is even asked whether
        # it is available, matching test_agents_reviewer.py's own equivalent assertion for the SDK.
        directory = agent_calls_dir(settings)
        assert not directory.exists() or not list(directory.glob("*.json"))


class TestClientArchivesCliCall:
    def test_cli_call_is_archived_through_the_identical_archive_call_path(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """The CLI path builds and archives an `AgentCall` through the same `_archive_call` an SDK
        call uses -- proven by reloading the archived JSON and comparing it to the returned `call`,
        exactly as `tests/test_agents_designer.py`'s `TestCallStructuredArchive` does for the SDK."""
        monkeypatch.setenv(cli_transport._CLI_ENV_OVERRIDE, r"C:\fake\claude.exe")
        fake_result = _make_cli_result(
            parsed_output=_Widget(ok=True, count=3),
            input_tokens=7,
            output_tokens=4,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=200,
            cost_usd=Decimal("0.033300"),
            stop_reason="end_turn",
            request_id="sess-archive-test",
        )
        monkeypatch.setattr(client_module.cli_transport, "call_structured", lambda **kw: fake_result)

        budget = AgentBudget(cap_usd=Decimal("10.00"))
        parsed, call, new_budget = client_module.call_structured(
            role="scout",
            system="SYSTEM PROMPT TEXT",
            user="USER TURN TEXT",
            output_format=_Widget,
            settings=settings,
            budget=budget,
        )

        assert parsed == _Widget(ok=True, count=3)
        assert call.role == "scout"
        assert call.system == "SYSTEM PROMPT TEXT"
        assert call.user == "USER TURN TEXT"
        assert call.input_tokens == 7
        assert call.output_tokens == 4
        assert call.cache_read_input_tokens == 100
        assert call.cache_creation_input_tokens == 200
        assert call.cost_usd == Decimal("0.033300")
        assert call.request_id == "sess-archive-test"
        assert call.stop_reason == "end_turn"
        assert new_budget.spent_usd == Decimal("0.033300")
        assert new_budget.calls == 1

        archive_path = agent_calls_dir(settings) / f"{call.call_id}.json"
        assert archive_path.is_file()
        reloaded = AgentCall.model_validate_json(archive_path.read_text(encoding="utf-8"))
        assert reloaded == call


# ---------------------------------------------------------------------------
# THE STEP THAT MATTERS MOST -- one real call against the real, installed Claude Code CLI
# ---------------------------------------------------------------------------


class Probe(BaseModel):
    """A trivial two-field structured-output contract for the live connectivity probe below -- small
    enough that a real model response either obviously matches it or obviously doesn't."""

    ok: bool
    word: str


@pytest.mark.skipif(
    not os.environ.get("INVDASH_LIVE_AGENT_TEST"),
    reason=(
        "spawns the real, locally-installed Claude Code CLI and costs real (subscription) spend; "
        "set INVDASH_LIVE_AGENT_TEST=1 to opt in, matching this repo's env-gated-test convention "
        "(see tests/conftest.py's own skipif fixtures for real broker exports)"
    ),
)
class TestLiveClaudeCodeCli:
    """One real call, through `app.agents.client.call_structured` -- not through this file's own
    `subprocess.run` monkeypatching -- against whichever `claude.exe` this machine actually resolves.

    **Why this class exists even though the whole rest of the file is mocked.** A green suite over a
    mocked subprocess proves `cli_transport.py`'s own logic is internally consistent; it proves nothing
    about whether the real binary's actual `--output-format json` envelope, actual flag names, or
    actual exit behaviour match what this file assumed they were. That exact gap already shipped one
    bug in this package: `tests/test_agents_reviewer.py`'s `TestReviewerRoleLiteralGap` documents every
    reviewer unit test passing green against a monkeypatched `call_structured` while the real call path
    raised `pydantic.ValidationError` on an `AgentCall.role` `Literal` that had never been widened to
    include `"reviewer"`. This class is the equivalent check for this transport: only a call that
    actually reaches `claude.exe` and comes back through the real envelope-parsing code can catch a
    flag this module got wrong, or an envelope shape that has changed since the docstring's sample was
    recorded.

    Uses `role="scout"` (not `"designer"`) for no reason other than to keep this call's archived
    `AgentCall.role` visually distinct from every other archived call in this file's temp directories,
    should anyone go looking.
    """

    def test_real_call_through_client_call_structured(
        self, settings: Settings
    ) -> None:
        budget = AgentBudget(cap_usd=Decimal("1.00"))

        parsed, call, new_budget = client_module.call_structured(
            role="scout",
            system=(
                "You are a connectivity probe with no tools and no task beyond answering exactly "
                "what is asked. Never explain yourself."
            ),
            user="Reply with ok=true and word set to exactly the string CONNECTED.",
            output_format=Probe,
            model="claude-sonnet-5",
            settings=settings,
            budget=budget,
            effort="low",
        )

        # --- what a human reading `-s` output for this test should be able to see ---
        print("\n--- live Claude Code CLI call ---")
        print("parsed output:", parsed.model_dump())
        print("raw response (archived):", call.raw_response)
        print(
            f"tokens: input={call.input_tokens} output={call.output_tokens} "
            f"cache_read={call.cache_read_input_tokens} cache_creation={call.cache_creation_input_tokens}"
        )
        print("cost_usd:", call.cost_usd, type(call.cost_usd))
        print("request_id (CLI session_id):", call.request_id)
        print("stop_reason:", call.stop_reason)
        print("new_budget:", new_budget)

        assert isinstance(parsed, Probe)
        assert parsed.ok is True
        assert parsed.word.strip().upper() == "CONNECTED"

        assert call.role == "scout"
        assert type(call.cost_usd) is Decimal
        assert call.cost_usd >= Decimal("0")
        assert new_budget.calls == 1
        assert new_budget.spent_usd == call.cost_usd

        archive_path = agent_calls_dir(settings) / f"{call.call_id}.json"
        assert archive_path.is_file()
