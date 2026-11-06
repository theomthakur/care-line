"""Issue/rotate scoped service credentials without printing secret material.

Registry and token files belong on a secret-manager mount, outside the repo.
Atomic replacement is picked up by the API/adapter on their next request.
"""

import argparse
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.common import utc
from backend.security import digest, private_file, timestamp


def write_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".new")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def rotate(registry, token_file, subject, organization, role, *, days=30):
    if not 1 <= days <= 90:
        raise ValueError("Credential lifetime must be between 1 and 90 days")
    registry = Path(registry)
    records = json.loads(private_file(registry)) if registry.exists() else []
    now = datetime.now(timezone.utc)
    # A bounded overlap lets the old worker finish during rollout. Revocation
    # removes a record entirely for immediate denial on the next request.
    for record in records:
        if (record["subject"], record["organization"], record["role"]) == (
            subject,
            organization,
            role,
        ):
            record["expires_at"] = utc(
                min(timestamp(record["expires_at"]), now + timedelta(hours=1))
            )
    secret = secrets.token_urlsafe(48)
    records.append(
        {
            "id": secrets.token_hex(8),
            "subject": subject,
            "organization": organization,
            "role": role,
            "sha256": digest(secret),
            "not_before": utc(now),
            "expires_at": utc(now + timedelta(days=days)),
        }
    )
    # Publish acceptance before moving the adapter to the new secret.
    write_private(registry, json.dumps(records, indent=2))
    write_private(token_file, secret)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument(
        "--role",
        choices=["agent", "operator", "identity_reviewer", "admin"],
        required=True,
    )
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    rotate(
        args.registry,
        args.token_file,
        args.subject,
        args.organization,
        args.role,
        days=args.days,
    )
    print(
        "Credential rotated. Deploy the owner-only token file through your secret manager."
    )


if __name__ == "__main__":
    main()
