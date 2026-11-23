"""Creates an admin account: the only way one exists (docs/04 R-AU6, decision A-D1).

    uv run --env-file ../.env python -m dawalink.ops.create_admin \
        --email you@example.org --name "Your Name"

The password is asked for twice, without showing it. The command then prints **once**
the key to type into an authenticator app (Google Authenticator, Microsoft
Authenticator, Authy: "enter a setup key", time-based). Every login needs the 6-digit
code the app shows. The key can't be read again: if the phone is lost, an admin is made
again with this command (no recovery flow).

The key is printed only to a terminal, where a person reads it. Without one (a container
started with no terminal), the output goes to the container's log, which keeps it for
days: the command then refuses before creating anything, unless
`--print-key-without-terminal` says that this is wanted, and the log is deleted right
after. `ADMIN_PASSWORD` may hold the password instead of typing it, for a setup that
can't answer a prompt. Nothing else is written to a file or a log.
"""

import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session, sessionmaker

from dawalink.config import load_settings
from dawalink.db.session import make_engine
from dawalink.domain.clock import SystemClock
from dawalink.services import auth
from dawalink.services.context import unit_of_work
from dawalink.services.errors import ServiceError

NO_TERMINAL_FOR_THE_KEY = (
    "There is no terminal: the authenticator key would be printed to wherever this "
    "command's output goes (in AWS, the task's log, kept for 30 days), and anyone who "
    "reads that log could make the admin's codes. Nothing was created. Run it in a "
    "terminal, or pass --print-key-without-terminal and delete that log right after."
)
NO_TERMINAL_FOR_THE_PASSWORD = (
    "There is no terminal to type the password in: set ADMIN_PASSWORD for this one run. "
    "Nothing was created."
)


def _password() -> str:
    given = os.environ.get("ADMIN_PASSWORD")
    if given:
        return given
    if not sys.stdin.isatty():
        raise SystemExit(NO_TERMINAL_FOR_THE_PASSWORD)
    first = getpass.getpass(
        "Password (10 characters or more, with a capital letter, a small letter, "
        "a number and a symbol): "
    )
    if first != getpass.getpass("The same password again: "):
        raise SystemExit("The two passwords are different. Nothing was created.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a DawaLink admin (two-factor login).")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="the admin's name, 2 to 80 characters")
    parser.add_argument(
        "--print-key-without-terminal",
        action="store_true",
        help="print the authenticator key even when no terminal shows it: it then goes to "
        "this command's log, which must be deleted right after",
    )
    args = parser.parse_args(argv)
    # Before anything is created: an admin whose key nobody saw can't log in.
    if not sys.stdout.isatty() and not args.print_key_without_terminal:
        raise SystemExit(NO_TERMINAL_FOR_THE_KEY)

    settings = load_settings()
    if settings.app_secret_key is None:
        raise SystemExit("APP_SECRET_KEY is not set: it protects the authenticator key.")
    secret_key = settings.app_secret_key.get_secret_value()
    # Asked before the transaction opens, so no database connection waits for a person.
    password = _password()
    sessions: sessionmaker[Session] = sessionmaker(
        make_engine(settings.database_url), expire_on_commit=False
    )
    try:
        with unit_of_work(sessions, SystemClock()) as tx:
            user, key = auth.create_admin(
                tx,
                email=args.email,
                password=password,
                full_name=args.name,
                secret_key=secret_key,
            )
            link = auth.totp_setup_link(key, user.email)
    except ServiceError as refused:
        print(f"Nothing was created: {refused.message}", file=sys.stderr)
        return 1
    print(f"Admin created: {user.email}")
    print("Type this key into your authenticator app now. It is shown only this once:")
    print(f"  {key}")
    print("Or open this link on the phone that has the app:")
    print(f"  {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
