"""Create (or re-enable) an administrator from the command line.

    docker compose -f docker-compose.prod.yml exec api python -m app.scripts.create_admin

The password is read interactively (never passed as an argument or env var,
so it does not end up in shell history, process lists or container metadata).
"""

import argparse
import getpass
import sys

from cmc_shared.enums import UserRole
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import User
from app.security.passwords import hash_password, validate_password_strength
from app.services.audit import AuditAction, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Amministratore")
    args = parser.parse_args(argv)

    password = getpass.getpass("Password (min. 10 caratteri): ")
    if password != getpass.getpass("Ripeti password: "):
        print("Le password non coincidono", file=sys.stderr)
        return 1
    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    email = args.email.strip().lower()
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email, name=args.name, role=UserRole.ADMIN, active=True, password_hash=""
            )
            db.add(user)
        user.role, user.active = UserRole.ADMIN, True
        user.password_hash = hash_password(password)
        db.flush()
        record(db, AuditAction.SETUP_ADMIN, actor="cli", details={"email": email})
        db.commit()
    print(f"Amministratore pronto: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
