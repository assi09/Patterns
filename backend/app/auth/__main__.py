"""Command line for accounts: `python -m app.auth <command>`.

Run on the server, from the repository root. `approve` is also how the owner approves their own
account the first time: sign-up has no email check yet, so an admin email is never approved
automatically (someone else could have registered it first). `set-password` asks for the password
without echoing it, so it never lands in the shell history; it is how the data owner created by
the sync claims their account, and how a forgotten password is replaced until there is a reset.
`delete` removes an account and everything held about the person, after the email is typed again;
it is how a deletion request is honoured (the pilot invitation promises one).
"""

import argparse
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth import accounts
from app.auth.accounts import AuthError
from app.auth.deletion import DeletionError, delete_account, held, teams_supervised
from app.db.models import USER_ROLES, User
from app.db.session import session_scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending", help="list sign-ups waiting for approval")
    for name in ("approve", "reject"):
        command = commands.add_parser(name, help=f"{name} a sign-up")
        command.add_argument("email")
    command = commands.add_parser("set-password", help="set or replace an account's password")
    command.add_argument("email")
    command = commands.add_parser("set-role", help="make an account a supervisor or a member")
    command.add_argument("email")
    command.add_argument("role", choices=USER_ROLES)
    command = commands.add_parser("delete", help="delete an account and all of the person's data")
    command.add_argument("email")
    args = parser.parse_args(argv)

    with session_scope() as session:
        if args.command == "pending":
            waiting = accounts.pending(session)
            for user in waiting:
                print(f"{user.created_at:%Y-%m-%d %H:%M}  {user.email}")
            print(f"{len(waiting)} waiting")
            return 0
        user = session.scalar(select(User).where(User.email == args.email.strip().lower()))
        if user is None:
            print(f"No account for {args.email}", file=sys.stderr)
            return 1
        if args.command == "set-password":
            password = getpass.getpass("New password: ")
            if getpass.getpass("Repeat it: ") != password:
                print("The passwords do not match.", file=sys.stderr)
                return 1
            try:
                accounts.set_password(session, user, password)
            except AuthError as error:
                print(error.message, file=sys.stderr)
                return 1
            print(f"Password set for {user.email}; every device was signed out.")
            return 0
        if args.command == "delete":
            return _delete(session, user)
        if args.command == "set-role":
            if user.status != "approved":
                print(f"{user.email} is not approved yet.", file=sys.stderr)
                return 1
            user.role = args.role
            print(f"{user.email}: {user.role}")
            return 0
        accounts.decide(session, user.id, args.command == "approve", datetime.now(UTC))
        print(f"{user.email}: {user.status}")
        if user.status == "approved":
            print("Also add them as a test user on the Google Cloud console's OAuth screen.")
    return 0


def _delete(session, user: User) -> int:
    """Shows what will go, asks for the email again, deletes, and reports counts only."""
    rows = held(session, user.id)
    teams = teams_supervised(session, user.id)
    print(f"This deletes {user.email} and {sum(rows.values())} rows that point at them:")
    for table, n in sorted(rows.items()):
        print(f"  {table}: {n}")
    if teams:
        names = ", ".join(sorted(t.name for t in teams))
        print(f"They supervise {len(teams)} team(s), deleted too with every membership: {names}")
    if input("Type the email again to delete: ").strip().lower() != user.email:
        print("Not deleted.", file=sys.stderr)
        return 1
    try:
        done = delete_account(session, user)
    except DeletionError as error:
        session.rollback()
        print(f"Not deleted: {error}", file=sys.stderr)
        return 1
    session.commit()
    print(f"Deleted {done.email}: {sum(done.rows.values())} rows, nothing left.")
    print("Their Google sign-in is gone; they can also remove the app's access in their Google")
    print("Account, and remove them as a test user on the OAuth consent screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
