"""Backend enums against the TypeScript unions that mirror them.

`docs/reports/defects-1.md` records the failure this file exists to prevent. Phase 9 added
`CATALOGUE_EXHAUSTED` to `LoopOutcome` -- as the fix for a QA defect -- and the TypeScript union
kept four values under a comment reading *"All four are reportable outcomes"*. The most common
outcome rendered a blank headline and `outcomeLabel()` returned `undefined` at runtime. Nothing
failed: `tsc` was clean, the Python suite was clean, and the two halves of the contract had simply
stopped agreeing.

The `assertNever` guards added afterwards turn the next drift into a compile error -- but only from
the moment someone edits the union. **The drift happens on this side**, when a Python enum gains a
member, and nothing on this side had any reason to notice. That is the gap this test closes: the
check fires in the suite that runs when the backend changes, which is where the change is.

It reads the TypeScript as text rather than executing it. A parser for one union declaration is a
few lines; standing up a Node toolchain inside the Python suite to be more rigorous about it would
cost more than the thing being checked.

**Direction matters.** This asserts every backend member is present in the union, not that the two
are equal. A union carrying an extra value is a different (milder) problem -- a dead branch, caught
by `tsc`'s exhaustiveness checking as soon as it is switched on -- while a *missing* value is the
one that renders blank in front of a user.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.config import REPO_ROOT
from app.core.lots import WarningKind
from app.ingest.service import FileStatus
from app.institutions.service import InsufficientHistory
from app.paperdesk.models import Desk, Holding, Signal
from app.tax.models import HoldingTerm, ReconcileStatus
from app.thesis.models import LoopOutcome, Verdict

FRONTEND = REPO_ROOT / "frontend" / "src"

#: ``(python enum, typescript file, union type name)``. Add a row when a backend enum starts
#: crossing the wire; the point is that this list is the record of which ones do.
SHARED_UNIONS: list[tuple[type[StrEnum], str, str]] = [
    (FileStatus, "api/imports.ts", "FileStatus"),
    (LoopOutcome, "api/thesis.ts", "LoopOutcome"),
    (Verdict, "api/thesis.ts", "Verdict"),
    (ReconcileStatus, "api/tax.ts", "ReconcileStatus"),
    (HoldingTerm, "api/tax.ts", "HoldingTerm"),
]


def test_the_rule_editors_own_example_parses() -> None:
    """The placeholder in the expression field, fed through the real parser.

    It read `rsi:14 < 30 and close > sma:200` until 2026-08-14 — colon syntax this DSL has never
    accepted — so typing the application's own suggestion produced `unexpected character ':'` from
    the tokenizer, below a page whose whole purpose is helping you write a valid expression. A UAT
    persona found it and said it cost them trust in the rest of the page.

    Checked here rather than in the frontend suite because only this side can run the grammar. It is
    the same argument `TestEveryHintParses` makes about the parser's *suggestions*: an example that
    does not parse converts a user's correct suspicion that they mistyped into a belief that the
    engine is broken.
    """
    from app.rules.grammar import parse

    source = FRONTEND / "components" / "RuleEditor.tsx"
    if not source.exists():  # pragma: no cover - frontend absent from a partial checkout
        pytest.skip("RuleEditor.tsx not present")

    text = source.read_text(encoding="utf-8")
    match = re.search(r'export const PLACEHOLDER_EXPRESSION = "([^"]+)";', text)
    assert match is not None, "PLACEHOLDER_EXPRESSION was renamed or inlined"

    parse(match.group(1))  # raises if the example the UI offers is not valid


def test_every_warning_kind_has_a_label() -> None:
    """`WARNING_KIND_LABEL_KEY` is a lookup, not a union, so `tsc` cannot check it at all.

    An unlabelled kind does not blank the UI — `warningKindLabel` falls back to the raw token — but
    `split_without_ratio` on a tax page is a worse answer than a sentence, and the difference is
    invisible until someone hits the case. These are warnings about figures the user must not trust
    silently, which is the last place to render an internal identifier.

    The map moved from literal strings to i18n message keys (`Record<string, MessageKey>`), so each
    entry is now `kind: "tax.warningKind.<x>"` and `warningKindLabel` runs it through `t()`. This
    still checks the property that matters: every backend `WarningKind` has an entry.
    """
    source = FRONTEND / "api" / "tax.ts"
    if not source.exists():  # pragma: no cover - frontend absent from a partial checkout
        pytest.skip("api/tax.ts not present")

    text = source.read_text(encoding="utf-8")
    match = re.search(
        r"const WARNING_KIND_LABEL_KEY: Record<string, MessageKey> = \{(.*?)\};", text, re.DOTALL
    )
    assert match is not None, "WARNING_KIND_LABEL_KEY was renamed or removed"
    labelled = set(re.findall(r"^\s*(\w+):", match.group(1), re.MULTILINE))

    missing = {kind.value for kind in WarningKind} - labelled
    assert not missing, (
        f"WarningKind member(s) {sorted(missing)} have no entry in WARNING_KIND_LABEL_KEY, so they "
        "render as their raw token on the Tax and Portfolio pages"
    )


def _union_members(source: Path, type_name: str) -> set[str]:
    """The string literals in ``export type <type_name> = "a" | "b" | ...;``.

    Tolerates the declaration being spread over several lines, which every one of these is once it
    has more than three members and prettier-style wrapping has been applied by hand.
    """
    text = source.read_text(encoding="utf-8")
    match = re.search(
        rf"export type {re.escape(type_name)}\s*=\s*(.*?);",
        text,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(
            f"no `export type {type_name}` in {source.relative_to(REPO_ROOT)} -- it was renamed or "
            "removed, and this contract row needs updating"
        )
    return set(re.findall(r'"([^"]+)"', match.group(1)))


@pytest.mark.parametrize(
    ("enum_type", "relative_path", "type_name"),
    SHARED_UNIONS,
    ids=[f"{t[2]}" for t in SHARED_UNIONS],
)
def test_typescript_union_covers_every_backend_member(
    enum_type: type[StrEnum], relative_path: str, type_name: str
) -> None:
    source = FRONTEND / relative_path
    if not source.exists():  # pragma: no cover - frontend absent from a partial checkout
        pytest.skip(f"{relative_path} not present")

    declared = _union_members(source, type_name)
    expected = {member.value for member in enum_type}
    missing = expected - declared

    assert not missing, (
        f"{enum_type.__name__} has member(s) {sorted(missing)} that `{type_name}` in "
        f"{relative_path} does not carry. A value the union does not know about reaches the UI as "
        "an unhandled case -- which last time rendered a blank headline in front of a user and "
        "compiled clean on both sides. Add it to the union, then to the label/tone switches, which "
        "will now fail to compile until you do."
    )


#: ``(pydantic model, typescript file, interface name)``. Same idea as :data:`SHARED_UNIONS`, one
#: level down: a *field* the backend adds and the TypeScript interface never learns about is the
#: quiet half of this drift. `tsc` cannot see it -- an interface missing a field the server sends is
#: perfectly valid TypeScript describing a subset of the payload -- so the field crosses the wire on
#: every request and renders nowhere, which is a bug with no failing test anywhere in either suite.
#:
#: The reverse direction is already covered and deliberately not re-checked here: an interface field
#: the backend does *not* send breaks `tsc` at the first fixture that omits it.
SHARED_INTERFACES: list[tuple[type[BaseModel], str, str]] = [
    (Signal, "api/paperdesk.ts", "Signal"),
    (Desk, "api/paperdesk.ts", "Desk"),
    (Holding, "api/paperdesk.ts", "Holding"),
]


#: Everything from an interface's opening brace to the ``}`` in column zero that ends it. Split
#: out as a constant so the escaping stays readable at the one call site below.
BODY_TO_CLOSING_BRACE = r"\s*\{(.*?)^\}"


def _interface_fields(source: Path, interface_name: str) -> set[str]:
    """Field names declared in ``export interface <interface_name> { ... }``.

    Deliberately a regex over the text rather than a TypeScript parse, for the same reason
    :func:`_union_members` is -- see this module's docstring. It reads the body up to the first
    line-start ``}``, which is where every interface in this codebase ends, and picks off the
    ``name:`` and ``name?:`` at the head of each field line. Doc comments in between are skipped
    because they never start a line with an identifier followed by a colon.
    """
    text = source.read_text(encoding="utf-8")
    match = re.search(
        rf"export interface {re.escape(interface_name)}" + BODY_TO_CLOSING_BRACE,
        text,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise AssertionError(
            f"no `export interface {interface_name}` in {source.relative_to(REPO_ROOT)} -- it was "
            "renamed or removed, and this contract row needs updating"
        )
    return set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??:", match.group(1), re.MULTILINE))


@pytest.mark.parametrize(
    ("model", "relative_path", "interface_name"),
    SHARED_INTERFACES,
    ids=[row[2] for row in SHARED_INTERFACES],
)
def test_typescript_interface_carries_every_backend_field(
    model: type[BaseModel], relative_path: str, interface_name: str
) -> None:
    """Caught in practice by `Signal.rank_value`/`.entry_rank`.

    Those two fields answer the one question the desk's forward-looking panel could not: with more
    names firing than free slots, which one actually gets bought. Had the interface not been updated
    alongside the model, the backend would have computed and serialised both on every request, the
    Python suite would have asserted them present in the JSON and passed, `tsc` would have been
    clean, and the panel would have gone on showing the reader nothing -- with no failing test on
    either side pointing at the gap.
    """
    source = FRONTEND / relative_path
    if not source.exists():  # pragma: no cover - frontend absent from a partial checkout
        pytest.skip(f"{relative_path} not present")

    declared = _interface_fields(source, interface_name)
    expected = set(model.model_fields)
    missing = expected - declared

    assert not missing, (
        f"{model.__name__} has field(s) {sorted(missing)} that `{interface_name}` in "
        f"{relative_path} does not declare. The server sends them on every request and the page "
        "cannot read them -- a silent gap, since TypeScript is happy to describe a subset of a "
        "payload and nothing in either suite notices the difference."
    )


def test_the_pages_empty_state_guard_matches_the_error_the_server_actually_sends() -> None:
    """The Institutions page's "only one filing" branch, against the real exception text.

    A second shape of the drift this file exists to catch, and it happened here for real. The page
    and the endpoint were written in parallel against a shared contract that fixed the *response
    bodies* but never nailed down the *error* copy. The page guessed: it matched a **404** whose
    message read "not enough filing history". The endpoint chose **409** -- correctly, since the
    fund exists and the request is well-formed, so 404 would misdescribe the resource -- with a
    message that says "usable filing period". Neither the status nor the wording overlapped.

    Both sides were internally consistent and both suites were green, because the page's test
    asserted against a *fixture the page's own author invented* rather than the string the server
    produces. The single state the branch exists to render -- a freshly tracked fund with one
    filing, which every fund passes through -- reached the user as a red API error.

    So this asserts the two ends against each other: the real message, from the real exception,
    against the literal regex compiled into the page.
    """
    page = FRONTEND / "pages" / "Institutions.tsx"
    if not page.exists():  # pragma: no cover - frontend absent from a partial checkout
        pytest.skip("Institutions.tsx not present")

    message = str(
        InsufficientHistory(
            "'QQQ' has only 1 usable filing period on record -- at least 2 are required to "
            "compute a change; check back after the next quarterly filing."
        )
    )

    source = page.read_text(encoding="utf-8")
    # The page carries several of these guards, one per expected-empty state. Collect them all and
    # assert the *property* -- some guard admits this message on this status -- rather than
    # positionally picking one, which would break the moment a branch is added above it.
    guards = re.findall(r"e\.status === (\d{3}) &&\s*/([^/]+)/i\.test\(e\.message\)", source)
    assert guards, (
        "Could not find any status-plus-message guard in Institutions.tsx. If they were rewritten, "
        "update this test to read the new shape rather than deleting it -- the drift is silent."
    )

    admitted = [
        (status, pattern)
        for status, pattern in guards
        if int(status) == 409 and re.search(pattern, message, re.IGNORECASE)
    ]
    assert admitted, (
        "No guard in Institutions.tsx admits the real InsufficientHistory response.\n"
        f"  server sends: HTTP 409 {message}\n"
        f"  page guards:  {[(s, f'/{p}/i') for s, p in guards]}\n"
        "The page will render its generic red error for a state that is normal and expected -- a "
        "freshly tracked fund with one filing on record, which every fund passes through."
    )
