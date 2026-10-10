#!/usr/bin/env python3
"""Catch the class of leak `detect-secrets` cannot see.

`.pre-commit-config.yaml` already runs `detect-secrets` on every commit, and that hook is good at
its job: high-entropy strings that look like API keys, tokens, and passwords. It has no opinion at
all about a dollar figure in a design doc, a brokerage account slug outside the ledger, an e-mail
address in a docstring, or a Windows username baked into an absolute path -- none of those are
secrets in the credential sense, so a secret scanner has no reason to flag them. But they are
exactly the shape of leak this repository has actually produced: `.gitignore` already carries its
own "near-miss" banner recording a day five real broker CSV exports were one `git add -A` away from
being committed, caught only by a human re-reading the diff. This script is the mechanical version
of that re-read, run on every commit instead of hoped for.

It is deliberately narrow and deliberately blunt, in the same spirit as `detect-secrets`: false
positives are the cost of not having to trust every contributor's judgment on every commit. It runs
in two modes, and the split is the whole design.

**Default mode (what the pre-commit hook runs) enforces only the two leaks that have zero
legitimate occurrence in this tree**, so it exits 0 on the repository as it stands today and fires
only on a genuine *regression* -- the whole point of a per-commit gate:

1. **A Windows user-directory path naming a real account** -- the account-name segment of a
   `C:/Users/<name>` path, which is where the developer username used to be baked into absolute
   paths across docs, research scripts, and scheduled-task command files. The check is generic: it
   flags that captured segment unless it is a documentation placeholder (`<user>`, `%USERNAME%`, and
   the like) or a built-in Windows profile (Public, Default, Administrator, service accounts), so no
   real username is ever written into this file -- which would be the same leak it exists to prevent,
   and would make the hook flag itself. Scrubbed to zero on 2026-09-05; a hook is what keeps it there.
2. **E-mail addresses.** Any address at all inside `backend/**` or `strategy-program/**` source --
   application code has no legitimate reason to hard-code *anyone's* address (see
   `app.config.Settings.contact_email` for the correct pattern: a runtime setting, not a literal).
   Addresses at reserved example/placeholder domains (`example.com`/`.org`/`.net`/`.invalid`, or
   anything ending `.invalid`/`.test`/`.example`/`.localhost`, per RFC 2606) are exempt -- that is
   what a placeholder default is supposed to look like. Everywhere else in the scanned tree, an
   address at the owner's own domain-local part is flagged regardless of file type; that part is not
   a string literal in this file (hard-coding it here would be the same leak this script exists to
   prevent) -- it is read at scan time from `.env`'s `INVDASH_CONTACT_EMAIL` or, failing that,
   `git config user.email`, neither of which is a tracked file.

**Strict mode (`--strict`) adds the two patterns that need a human's judgment, not a blunt gate.**
These flag hundreds of *pre-existing and legitimate* occurrences -- brokerage account slugs are keys
threaded through the ledger, the tests, and the frontend; dollar figures in research and spec docs
are backtest notionals and institutional 13F totals, not personal disclosure -- so enforcing them on
every commit would fail the whole existing tree and teach people to pass `--no-verify`. They are the
repository-goes-public decision recorded in `docs/BEFORE-PUBLISHING.md`, and this mode is the tool
that decision is checked with, run deliberately, not the gate every commit trips over:

3. **Dollar figures shaped like `$N,NNN` or larger** in `*.md` at the repo root, `docs/**`, and
   `.claude/**`. `docs/local/**`, `data/rounds/**`, and `uat/**` are excluded: the first is
   gitignored entirely, the other two are where institutional and synthetic figures legitimately live.
4. **Account identifiers** (`rh-taxable`, `rh-roth`, `wb-margin`, `wb-roth`, `wb-cash`) outside
   `data/`, `tests/fixtures/`, and `backend/app/ingest/`.

Usage: `check_no_pii.py [--strict] [path ...]`. With no path arguments, scans every file `git
ls-files` currently tracks -- the same "whole tree, right now" scope `detect-secrets` runs at.
Pre-commit instead passes the staged files explicitly (and never `--strict`), so a hook run only
ever looks at what is about to be committed. Exits non-zero and lists every match -- file, line,
what matched, and what to do about it -- the moment there is at least one.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# RFC 2606 reserved domains/TLDs meant for documentation and examples -- never real, so an address
# there is a deliberate placeholder (see app.config.Settings.contact_email's default), not a leak.
_PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "example.invalid"}
_PLACEHOLDER_SUFFIXES = (".invalid", ".test", ".example", ".localhost")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MONEY_RE = re.compile(r"\$\d{1,3}(?:,\d{3})+")
# A Windows user-directory path, capturing the account-name segment. Generic on purpose: the real
# username is never a literal here (that would be the leak, and would make this file flag itself) --
# any name that is not a placeholder or a built-in account is flagged. The captured class covers
# real usernames plus the placeholder forms this repo uses (angle-bracket, %ENV%, $env:) and stops
# at any separator or punctuation, so a trailing backtick/comma in prose does not defeat the
# allowlist compare below.
_USERNAME_RE = re.compile(r"Users[\\/]([A-Za-z0-9._$%:<>-]+)")
# Names that are not a person: documentation placeholders and the built-in Windows profiles (the
# Public share, the default-profile skeleton, service accounts). Compared case-insensitively.
_USERNAME_ALLOWED = frozenset(
    {
        "<user>", "<username>", "<name>", "<you>", "<your-username>", "%username%", "$user", "$env:username",
        "public", "default", "default user", "defaultapppool", "all users", "administrator", "admin",
        "runneradmin", "runner", "vagrant", "user", "username", "containeradministrator", "systemprofile",
    }
)
_ACCOUNT_ID_RE = re.compile(r"\b(?:rh-taxable|rh-roth|wb-margin|wb-roth|wb-cash)\b")

_MONEY_SCOPE_EXCLUDE = ("docs/local/", "data/rounds/", "uat/")
_ACCOUNT_ID_ALLOWED_PREFIXES = ("data/", "tests/fixtures/", "backend/app/ingest/")


class Violation:
    def __init__(self, path: str, line_no: int, kind: str, matched: str, advice: str) -> None:
        self.path = path
        self.line_no = line_no
        self.kind = kind
        self.matched = matched
        self.advice = advice

    def __str__(self) -> str:
        return f"{self.path}:{self.line_no}: [{self.kind}] found {self.matched!r} -- {self.advice}"


def _git_tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _owner_email_local_domain() -> str | None:
    """The real contact address to watch for, read at scan time -- never a literal in this file.

    Tries `.env`'s `INVDASH_CONTACT_EMAIL` first (gitignored, machine-local -- see `app.config`),
    then falls back to `git config user.email` (local git config, not a repo file either). Returns
    `None` if neither is set, in which case pattern 2's owner-specific half is simply skipped --
    the `backend/**`/`strategy-program/**` blanket "any address" check still runs regardless.
    """
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("INVDASH_CONTACT_EMAIL="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value and _EMAIL_RE.fullmatch(value):
                        return value
        except OSError:
            pass
    try:
        out = subprocess.run(
            ["git", "config", "--get", "user.email"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if out and _EMAIL_RE.fullmatch(out):
            return out
    except OSError:
        pass
    return None


def _is_placeholder_domain(address: str) -> bool:
    domain = address.rsplit("@", 1)[-1].lower()
    if domain in _PLACEHOLDER_DOMAINS:
        return True
    return domain.endswith(_PLACEHOLDER_SUFFIXES)


def _money_in_scope(rel_path: str) -> bool:
    posix = rel_path.replace("\\", "/")
    if any(posix.startswith(prefix) for prefix in _MONEY_SCOPE_EXCLUDE):
        return False
    if "/" not in posix and posix.endswith(".md"):
        return True
    if posix.startswith("docs/"):
        return True
    return bool(posix.startswith(".claude/"))


def _account_id_in_scope(rel_path: str) -> bool:
    posix = rel_path.replace("\\", "/")
    return not any(posix.startswith(prefix) for prefix in _ACCOUNT_ID_ALLOWED_PREFIXES)


def _email_any_in_scope(rel_path: str) -> bool:
    posix = rel_path.replace("\\", "/")
    return posix.startswith("backend/") or posix.startswith("strategy-program/")


def scan_file(rel_path: str, owner_address: str | None, strict: bool) -> list[Violation]:
    abs_path = REPO_ROOT / rel_path
    try:
        text = abs_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # binary or unreadable -- not a text leak this script can see

    violations: list[Violation] = []
    # Patterns 3 and 4 (dollar figures, account slugs) are strict-mode only: they flag legitimate
    # pre-existing content, so on every commit they would fail the tree rather than catch a
    # regression. See the module docstring for why the split exists.
    money_scope = strict and _money_in_scope(rel_path)
    account_id_scope = strict and _account_id_in_scope(rel_path)
    email_any_scope = _email_any_in_scope(rel_path)

    for line_no, line in enumerate(text.splitlines(), start=1):
        if money_scope:
            for m in _MONEY_RE.finditer(line):
                violations.append(
                    Violation(
                        rel_path,
                        line_no,
                        "dollar-figure",
                        m.group(),
                        "remove the real magnitude, or rephrase with a placeholder shape "
                        "(e.g. `$N,NNN.NN`) that carries no real number",
                    )
                )

        for m in _EMAIL_RE.finditer(line):
            address = m.group()
            if _is_placeholder_domain(address):
                continue
            is_owner = owner_address is not None and address.lower() == owner_address.lower()
            if is_owner:
                violations.append(
                    Violation(
                        rel_path,
                        line_no,
                        "owner-email",
                        address,
                        "replace with a setting read at runtime (see app.config.Settings."
                        "contact_email) -- never a literal in tracked source",
                    )
                )
            elif email_any_scope:
                violations.append(
                    Violation(
                        rel_path,
                        line_no,
                        "email-in-source",
                        address,
                        "backend/** and strategy-program/** must not hard-code any e-mail "
                        "address -- read it from settings or an env var instead",
                    )
                )

        for m in _USERNAME_RE.finditer(line):
            name = m.group(1)
            if name.lower() in _USERNAME_ALLOWED:
                continue
            violations.append(
                Violation(
                    rel_path,
                    line_no,
                    "windows-username",
                    m.group(),
                    "replace the absolute path with a repo-relative one, a `pathlib.Path("
                    "__file__).resolve().parents[N]` computation, or `<repo>`/`<user>` in prose",
                )
            )

        if account_id_scope:
            for m in _ACCOUNT_ID_RE.finditer(line):
                violations.append(
                    Violation(
                        rel_path,
                        line_no,
                        "account-identifier",
                        m.group(),
                        "account identifiers belong in data/, tests/fixtures/, or "
                        "backend/app/ingest/ only -- genericise this mention or move the content",
                    )
                )

    return violations


def main(argv: list[str]) -> int:
    args = argv[1:]
    strict = "--strict" in args
    paths = [a for a in args if a != "--strict"]
    if not paths:
        paths = _git_tracked_files()
    owner_address = _owner_email_local_domain()

    all_violations: list[Violation] = []
    for rel_path in paths:
        all_violations.extend(scan_file(rel_path, owner_address, strict))

    if not all_violations:
        return 0

    mode = "strict" if strict else "default"
    print(f"check_no_pii ({mode}): {len(all_violations)} violation(s) found\n", file=sys.stderr)
    for v in all_violations:
        print(str(v), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
