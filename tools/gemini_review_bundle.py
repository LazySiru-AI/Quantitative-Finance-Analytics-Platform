"""Assemble a single self-contained review packet to paste into the Gemini web app (or Antigravity).

**Why this exists.** A Google AI Pro / Ultra *subscription* has no API and, since June 2026, can no
longer drive the Gemini CLI or the Code Assist IDE extensions (those are Code Assist Standard/Enterprise
only now). The one surface the consumer subscription still unlocks is the *interactive* Gemini web app
at ``gemini.google.com`` and Google Antigravity -- both human-driven, both fed by pasting text. This
script is the automatable half of that workflow: it turns "review my branch" into one Markdown file a
person pastes into that chat, so the only manual step left is the paste itself. It never calls a model,
never touches the network, and never needs a credential -- it is a text bundler, nothing more.

**What goes in the packet, and why that order.** The file leads with a *role + rubric* block so the
model reads the review instructions before it has seen a single line of code (a rubric appended after
100k tokens of diff is a rubric the model has already stopped weighting). The rubric is not generic: it
is seeded with the failure modes this project has actually shipped and had to fix -- grounding-gate
false rejections, closed-union render crashes, service-layer-green-is-not-a-rendered-page, auth-fixture
401s, tests that build their own app and never exercise registration, ``pytest`` exiting 0 on a usage
error, percent-vs-fraction blowups, wall-clock stamps used as trading-session dates. Then repo context
(branch, base, exact diff spec), then the diff itself, then the full current text of each changed file
so the model can judge a hunk against the function it lives in rather than against three lines of
context. Full files come *after* the diff because the diff is the thing under review; the files are
reference material for it.

**The diff spec, and why uncommitted-vs-HEAD by default.** The default review target is the common one:
"what I have changed since my last commit" -- ``git diff HEAD`` (staged + unstaged working-tree edits).
It is chosen as the default precisely because it is *bounded*: a long-lived branch here can sit tens of
thousands of commits off ``main``, and "everything since we forked" is then a 30-million-token diff no
one can paste. That whole-branch review is still available, but as an explicit opt-in: ``--base <ref>``
reviews "everything this branch would merge into ``<ref>``, including uncommitted work" via
``git diff <merge-base(<ref>, HEAD)>`` -- merge-base rather than ``<ref>`` directly so commits that
landed on ``<ref>`` after this branch forked do not show up as deletions the branch never made.
``--staged`` reviews only the index; ``--range A..B`` diffs strictly those two points (no working-tree
overlay). One caveat this script cannot fix: in a checkout several sessions share, a working-tree diff
folds in *other* sessions' uncommitted hunks as if they were yours -- the packet reports the exact spec
it used so a reader can see what was included, but it cannot tell whose uncommitted line is whose.

**Size.** Gemini 2.5 Pro carries a very large context window, so the defaults are generous rather than
stingy, but a per-file cap (``--max-file-bytes``) and a total cap (``--max-total-bytes``) still apply:
a single vendored lockfile or a generated bundle in the diff should truncate, not silently produce a
packet too large to paste. Every truncation is stated inline in the packet so the model is told what it
is *not* seeing rather than left to assume the file ended where the text stopped.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where a bundle is written unless ``--out`` overrides it. Git-ignored (see this script's companion
#: ``.gitignore`` entry) because a review packet is a throwaway working file, not a tracked artifact.
DEFAULT_OUT_DIR = REPO_ROOT / ".gemini-review"

#: The review instructions the packet leads with. Seeded with THIS project's real, shipped-and-fixed
#: failure modes rather than a generic checklist -- a reviewer who does not know this codebase's traps
#: cannot look for them. Kept as prose the model reads top-to-bottom, not as a form to fill in.
REVIEW_RUBRIC = """\
You are a senior reviewer for an investing-dashboard codebase (Python/FastAPI backend, React/TS
frontend, an LLM "agent desk" layer, and a tax/holdings ledger pipeline). Review the diff below. Be
concrete: cite the file and line, state the failing input or state, and say what breaks. Rank findings
most-severe first. If you are unsure a finding is real, say so and explain what you'd check -- do not
pad the list with style nits presented as bugs.

Weight these failure modes especially heavily, because this project has shipped every one of them and
had to fix it in production:

CORRECTNESS / DATA
- A "200 OK" or a green service-layer check is NOT proof a page renders. One bad value has taken a
  whole page down while the API reported healthy. Trace values through to the render, not just the API.
- Closed unions / exhaustiveness checks over SERVER-SUPPLIED strings crash the page the instant the
  server sends a value the union does not list. Flag any throwing "impossible" branch fed by server data.
- Percent-vs-fraction confusion (a return stored as 0.06 rendered as 6027%). Check every place a ratio
  crosses a boundary (API<->UI, decimal<->percent).
- Dates: a wall-clock write timestamp (e.g. `filled_at`) used as an acquisition / trading-session date
  corrupts tax lots. Flag any "when it was written" value standing in for "when it happened."
- Stateful closures reused across iterations/windows leak state; the first cell of a sweep looks right,
  which hides it. Flag any mutable state captured by a function reused across calls.

LLM / AGENT LAYER
- Structured-output contract fidelity: does a new model call keep the caching prefix stable (volatile
  content in `user`, frozen prompt in `system`), handle refusals as a normal outcome, and degrade to a
  deterministic path on `AgentUnavailable` rather than crashing the caller?
- Grounding/number-check gates over-reject on legitimate tokens (ISO dates, RSI(14)). Flag validators
  tested only on rules-in-isolation, never on real caller sentences.
- Budget/cost caps: is every model call still gated by the budget check before it can spend?

TESTS
- Tests that construct their own app / router instead of importing the real one never exercise
  registration -- a missing `include_router` can pass every test. (Route checks via `app.routes` give a
  false negative on this FastAPI version; the real check is `app.openapi()["paths"]`.)
- `pytest` exits 0 on a usage error and a bare `python -m pytest` outside the repo venv prints "no
  module" and STILL exits 0 -- a green that ran zero tests. A passing suite is evidence only if an
  `N passed` line proves N>0 and it ran from the venv.
- Endpoint tests whose client fixture skips the auth `settings` fixture fail with 401s that are the
  fixture's fault, not the code's. Distinguish a real failure from a fixture gap.
- Unit-green means "consistent with the brief," not "correct" -- look for integration seams the unit
  tests assume rather than check.

SECURITY / SAFETY
- Any new endpoint or data path that bypasses the auth gate; any secret, key, or PII heading into a
  log line, URL query string, or error message.

Produce: (1) a ranked findings list (severity, file:line, failing scenario, fix direction), then
(2) a short "tests I would add" list targeting the seams above.
"""


@dataclass(frozen=True)
class DiffSpec:
    """The resolved git diff to bundle, plus a human-readable description of it for the packet header.

    ``args`` is the exact ``git diff`` argument list (after the ``diff`` subcommand) that both the diff
    text and the changed-file list are produced from, so the two can never describe different revisions.
    ``description`` is the one-line explanation printed into the packet so a reader knows precisely what
    revision range they are looking at -- and, by omission, what they are not.
    """

    args: list[str]
    description: str


def _git(*args: str) -> str:
    """Run ``git`` in :data:`REPO_ROOT` and return stdout, raising with git's own stderr on failure.

    Centralised so every git call in this module runs from the same cwd and surfaces the same kind of
    error message -- a bad ref or a not-a-repo failure reads as git's own text, not a bare non-zero exit.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def _resolve_spec(*, base: str | None, staged: bool, range_spec: str | None) -> DiffSpec:
    """Turn the mutually-exclusive CLI mode flags into one concrete :class:`DiffSpec`.

    Precedence, highest first: an explicit ``--range`` wins outright (the caller named exactly what they
    want, no working-tree overlay); then ``--base <ref>`` (the branch's whole contribution vs that ref,
    via merge-base, including uncommitted edits); then ``--staged`` (the index against HEAD); then the
    default, ``git diff HEAD`` -- uncommitted working-tree changes since the last commit. See the module
    docstring for why the *bounded* uncommitted diff is the default and the merge-base review is opt-in.
    """
    if range_spec is not None:
        return DiffSpec(args=[range_spec], description=f"explicit range `{range_spec}`")
    if base is not None:
        merge_base = _git("merge-base", base, "HEAD").strip()
        return DiffSpec(
            args=[merge_base],
            description=(
                f"branch changes vs `{base}` (merge-base `{merge_base[:12]}` -> working tree, "
                f"committed + uncommitted)"
            ),
        )
    if staged:
        return DiffSpec(args=["--cached"], description="staged changes (index vs HEAD)")

    return DiffSpec(args=["HEAD"], description="uncommitted changes (working tree vs HEAD)")


def _changed_files(spec: DiffSpec) -> list[str]:
    """The paths touched by ``spec``, in git's own order, excluding deletions (nothing to show)."""
    names = _git("diff", "--name-only", "--diff-filter=d", *spec.args)
    return [line.strip() for line in names.splitlines() if line.strip()]


def _read_current(path: str, *, max_bytes: int) -> tuple[str, bool]:
    """The working-tree text of ``path`` (up to ``max_bytes``) and whether it was truncated.

    Reads the file *as it is on disk right now*, not any git blob, so the reviewer sees the version the
    diff was computed against. A file that is in the diff but no longer on disk (a rename's old side that
    slipped past the delete filter, say) yields a short placeholder rather than raising.
    """
    full = REPO_ROOT / path
    if not full.is_file():
        return f"[file not present in working tree: {path}]", False
    data = full.read_bytes()
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return text, truncated


def _fence_lang(path: str) -> str:
    """A Markdown code-fence language hint from the file extension, for readability only."""
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx",
        ".css": "css", ".json": "json", ".toml": "toml", ".md": "markdown",
        ".sql": "sql", ".sh": "bash", ".cmd": "bat", ".yml": "yaml", ".yaml": "yaml",
    }.get(suffix, "")


def build_packet(
    *,
    base: str | None,
    staged: bool,
    range_spec: str | None,
    include_files: bool,
    max_file_bytes: int,
    max_total_bytes: int,
) -> str:
    """Assemble the whole review packet as one Markdown string.

    Returns the finished text; writing it out (or copying it to the clipboard) is :func:`main`'s job, so
    this function stays pure and testable -- no filesystem side effects, no ``print``.
    """
    spec = _resolve_spec(base=base, staged=staged, range_spec=range_spec)
    diff_text = _git("diff", *spec.args)
    files = _changed_files(spec)
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    head = _git("rev-parse", "--short", "HEAD").strip()
    generated = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = []
    parts.append("# Code review packet\n")
    parts.append(
        f"- Generated: {generated}\n"
        f"- Branch: `{branch}` @ `{head}`\n"
        f"- Diff spec: {spec.description}\n"
        f"- Files changed: {len(files)}\n"
    )
    parts.append("\n---\n\n## How to review this\n\n")
    parts.append(REVIEW_RUBRIC)

    if not diff_text.strip():
        parts.append("\n---\n\n## Diff\n\n_(empty -- the diff spec produced no changes)_\n")
        return "".join(parts)

    parts.append("\n---\n\n## Diff\n\n")
    parts.append(f"```diff\n{diff_text.rstrip()}\n```\n")

    if not include_files:
        return "".join(parts)

    parts.append("\n---\n\n## Full current text of changed files\n\n")
    parts.append(
        "_Reference material for the diff above -- the version on disk the diff was computed against._\n\n"
    )

    running = sum(len(p.encode("utf-8")) for p in parts)
    for path in files:
        if running >= max_total_bytes:
            parts.append(
                f"\n> **Total size cap ({max_total_bytes:,} bytes) reached** -- remaining files "
                f"omitted from full-text (they are still in the diff above): "
                f"{', '.join(f'`{p}`' for p in files[files.index(path):])}\n"
            )
            break
        text, truncated = _read_current(path, max_bytes=max_file_bytes)
        lang = _fence_lang(path)
        header = f"\n### `{path}`\n\n"
        note = (
            f"> _Truncated to first {max_file_bytes:,} bytes; see the diff for the changed region._\n\n"
            if truncated
            else ""
        )
        block = f"{header}{note}```{lang}\n{text.rstrip()}\n```\n"
        parts.append(block)
        running += len(block.encode("utf-8"))

    return "".join(parts)


def _copy_to_clipboard(text: str) -> bool:
    """Best-effort copy to the OS clipboard; returns whether it succeeded.

    Uses ``clip`` on Windows and ``pbcopy`` on macOS -- the two this project's machines actually run.
    Never raises: clipboard access is a convenience, and a headless or Linux host simply gets ``False``
    and the "written to <path>" message instead.
    """
    tool = {"win32": ["clip"], "darwin": ["pbcopy"]}.get(sys.platform)
    if tool is None:
        return False
    try:
        subprocess.run(tool, input=text.encode("utf-8"), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bundle the current branch's changes into one Markdown review packet to paste into the "
            "Gemini web app or Antigravity. Makes no model calls and needs no credential."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--base",
        default=None,
        help="review the whole branch vs this ref (via merge-base); default is uncommitted changes only",
    )
    mode.add_argument("--staged", action="store_true", help="review only staged (indexed) changes")
    mode.add_argument(
        "--range",
        dest="range_spec",
        metavar="A..B",
        help="explicit git range to diff, overriding --base/--staged (no working-tree overlay)",
    )
    parser.add_argument(
        "--no-files",
        dest="include_files",
        action="store_false",
        help="diff only; skip the full current text of changed files",
    )
    parser.add_argument("--max-file-bytes", type=int, default=120_000, help="per-file full-text cap")
    parser.add_argument("--max-total-bytes", type=int, default=3_000_000, help="overall full-text cap")
    parser.add_argument("--out", type=Path, default=None, help="output path (default: .gemini-review/)")
    parser.add_argument("--stdout", action="store_true", help="also print the packet to stdout")
    parser.add_argument("--clip", action="store_true", help="copy the packet to the clipboard")
    args = parser.parse_args(argv)

    packet = build_packet(
        base=args.base,
        staged=args.staged,
        range_spec=args.range_spec,
        include_files=args.include_files,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
    )

    if args.out is not None:
        out_path = args.out
    else:
        DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = DEFAULT_OUT_DIR / f"review-{stamp}.md"
    out_path.write_text(packet, encoding="utf-8")

    size_kb = len(packet.encode("utf-8")) / 1024
    approx_tokens = len(packet) // 4
    print(f"Wrote {out_path}  ({size_kb:,.0f} KB, ~{approx_tokens:,} tokens)")
    print("Paste it into gemini.google.com (or Antigravity) to review.")

    # Gemini 2.5 Pro's window is ~1M tokens; well past that the paste is impractical and the model
    # stops weighting the rubric at the top. A whole-branch `--base` review of a long-lived branch is
    # the usual cause -- point the user at the narrower modes rather than letting them paste blind.
    if approx_tokens > 800_000:
        print(
            f"  WARNING: ~{approx_tokens:,} tokens is very large to paste and may exceed the context "
            "window. Narrow it with --staged, --range A..B, or by reviewing uncommitted changes only "
            "(no --base)."
        )

    if args.clip:
        print("Copied to clipboard." if _copy_to_clipboard(packet) else "Clipboard copy unavailable on this platform.")
    if args.stdout:
        sys.stdout.write(packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
