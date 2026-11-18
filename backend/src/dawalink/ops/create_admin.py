"""Creates an admin account: the only way one exists (docs/04 R-AU6, decision A-D1).

    uv run --env-file ../.env python -m dawalink.ops.create_admin \
        --email you@example.org --name "Your Name"

The password is asked for twice, without showing it. The command then prints **once**
the key to type into an authenticator app (Google Authenticator, Microsoft
Authenticator, Authy: "enter a setup key", time-based). Every login needs the 6-digit
code the app shows. The key can't be read again: if the phone is lost, an admin is made
again with this command (no recovery flow).

Nothing here is written to a file or a log. `ADMIN_PASSWORD` may hold the password
instead of typing it, for a setup that can't answer a prompt.
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


def _password() -> str:
    given = os.environ.get("ADMIN_PASSWORD")
    if given:
        return given
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
    args = parser.parse_args(argv)

    settings = load_settings()
    if settings.app_secret_key is None:
        raise SystemExit("APP_SECRET_KEY is not set: it protects the authenticator key.")
    secret_key = settings.app_secret_key.get_secret_value()
    sessions: sessionmaker[Session] = sessionmaker(
        make_engine(settings.database_url), expire_on_commit=False
    )
    try:
        with unit_of_work(sessions, SystemClock()) as tx:
            user, key = auth.create_admin(
                tx,
                email=args.email,
                password=_password(),
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
