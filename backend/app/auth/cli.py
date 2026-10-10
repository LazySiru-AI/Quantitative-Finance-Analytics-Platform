"""User administration from the command line.

The owner manages the ~ten users here; there is no self-registration and no admin web UI by design
(see ``docs/AUTH-PLAN.md``). Run it from the repository root with the project venv, the same way the
server is started::

    .venv/Scripts/python.exe -m app.auth.cli add-user alice
    .venv/Scripts/python.exe -m app.auth.cli list

A password is read interactively (never echoed) unless ``--password-stdin`` is given, in which case
it is read from stdin -- for scripting, and so the value never lands in shell history or the process
table the way a ``--password foo`` argument would. There is deliberately no way to pass a password
as an argument.

The database created here is ``Settings.auth_db_path``. On the deployed Docker backend that resolves
under the ``/data`` volume, so users persist across image rebuilds; run ``add-user`` once after the
first deploy, because auth is on by default and an instance with zero users is intentionally locked.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import passwords, store
from app.config import get_settings


def _read_password(args: argparse.Namespace, *, confirm: bool) -> str:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if confirm and password != getpass.getpass("Confirm password: "):
            print("passwords did not match", file=sys.stderr)
            raise SystemExit(2)
    try:
        passwords.validate_length(password)
    except passwords.WeakPasswordError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    return password


def _cmd_add_user(args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    password = _read_password(args, confirm=True)
    try:
        user = store.create_user(
            settings, args.username, passwords.hash_password(password), role=args.role
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"created user {user.username!r} ({user.role})")
    return 0


def _cmd_set_role(args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    try:
        changed = store.set_role(settings, args.username, args.role)
    except store.LastOwnerError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not changed:
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    print(f"{store.normalize_username(args.username)!r} is now {args.role}")
    return 0


def _cmd_set_password(args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    if store.get_user(settings, args.username) is None:
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    password = _read_password(args, confirm=True)
    store.set_password_hash(settings, args.username, passwords.hash_password(password))
    # A password change is also a revocation of that user's other sessions.
    user = store.get_user(settings, args.username)
    assert user is not None
    revoked = store.delete_sessions_for_user(settings, user.id)
    print(f"password updated for {user.username!r}; revoked {revoked} session(s)")
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    try:
        changed = store.set_disabled(settings, args.username, True)
    except store.LastOwnerError as exc:
        print(f"{exc}; promote another user with set-role first", file=sys.stderr)
        return 1
    if not changed:
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    print(f"disabled {store.normalize_username(args.username)!r} and revoked its sessions")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    if not store.set_disabled(settings, args.username, False):
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    print(f"enabled {store.normalize_username(args.username)!r}")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    users = store.list_users(settings)
    if not users:
        print("(no users -- run add-user; auth is on by default so the app is locked until then)")
        return 0
    width = max(len(u.username) for u in users)
    for u in users:
        state = "disabled" if u.disabled else "active"
        print(f"{u.username:<{width}}  {u.role:<6}  {state:<8}  created {u.created_at}")
    return 0


def _cmd_revoke_sessions(args: argparse.Namespace) -> int:
    settings = get_settings()
    store.init_db(settings)
    user = store.get_user(settings, args.username)
    if user is None:
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    revoked = store.delete_sessions_for_user(settings, user.id)
    print(f"revoked {revoked} session(s) for {user.username!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def _with_password(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--password-stdin",
            action="store_true",
            help="read the password from stdin instead of prompting (for scripting)",
        )

    p_add = sub.add_parser("add-user", help="create a new user (the first one is always the owner)")
    p_add.add_argument("username")
    p_add.add_argument(
        "--role",
        choices=sorted(store.ROLES),
        default=store.ROLE_MEMBER,
        help="owner sees the ledger, tax and user admin; member sees the research surfaces only",
    )
    _with_password(p_add)
    p_add.set_defaults(func=_cmd_add_user)

    p_role = sub.add_parser("set-role", help="promote or demote a user (never the last owner)")
    p_role.add_argument("username")
    p_role.add_argument("role", choices=sorted(store.ROLES))
    p_role.set_defaults(func=_cmd_set_role)

    p_set = sub.add_parser("set-password", help="change a user's password (revokes their sessions)")
    p_set.add_argument("username")
    _with_password(p_set)
    p_set.set_defaults(func=_cmd_set_password)

    p_dis = sub.add_parser("disable", help="lock a user out and revoke their sessions")
    p_dis.add_argument("username")
    p_dis.set_defaults(func=_cmd_disable)

    p_en = sub.add_parser("enable", help="re-enable a disabled user")
    p_en.add_argument("username")
    p_en.set_defaults(func=_cmd_enable)

    p_list = sub.add_parser("list", help="list users and their state")
    p_list.set_defaults(func=_cmd_list)

    p_rev = sub.add_parser("revoke-sessions", help="sign a user out of every session")
    p_rev.add_argument("username")
    p_rev.set_defaults(func=_cmd_revoke_sessions)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
