"""Service authentication and organization/call boundaries.

Each deployment owns exactly one organization's database. Network callers never
choose a database, organization, patient, or role through request parameters.
"""

import hashlib
import hmac
import json
import os
import stat
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.core.errors import DomainError


def private_file(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Secret/configuration files must be regular owner-only files")
    return path.read_text().strip()


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Credential timestamps must include a timezone")
    return result


@dataclass(frozen=True)
class Principal:
    subject: str
    organization: str
    role: str


@dataclass(frozen=True)
class Access:
    principal: Principal
    call_key: str


access_context = ContextVar("memberguide_access", default=None)


@dataclass(frozen=True)
class SecuritySettings:
    environment: str = "synthetic"
    organization: str = "synthetic"
    credentials_file: str = ""
    identity_policy: str = ""
    retention_policy_file: str = ""
    storage_evidence_file: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            environment=os.getenv("MEMBERGUIDE_ENV", "synthetic"),
            organization=os.getenv("MEMBERGUIDE_ORGANIZATION", "synthetic"),
            credentials_file=os.getenv("MEMBERGUIDE_CREDENTIALS_FILE", ""),
            identity_policy=os.getenv("MEMBERGUIDE_IDENTITY_POLICY", ""),
            retention_policy_file=os.getenv("MEMBERGUIDE_RETENTION_POLICY_FILE", ""),
            storage_evidence_file=os.getenv("MEMBERGUIDE_STORAGE_EVIDENCE_FILE", ""),
        )

    def validate(self, database_path=None):
        if self.environment not in {"synthetic", "production"}:
            raise ValueError("MEMBERGUIDE_ENV must be synthetic or production")
        if not self.organization:
            raise ValueError("An organization is required")
        if self.environment == "production":
            if self.organization == "synthetic" or not all(
                (
                    self.credentials_file,
                    self.identity_policy,
                    self.retention_policy_file,
                    self.storage_evidence_file,
                )
            ):
                raise ValueError(
                    "Production requires organization, credentials and approved policies/storage evidence"
                )
            records = json.loads(private_file(self.credentials_file))
            now = datetime.now(timezone.utc)
            if not any(
                record["role"] == "agent"
                and record["organization"] == self.organization
                and timestamp(record["not_before"])
                <= now
                < timestamp(record["expires_at"])
                for record in records
            ):
                raise ValueError(
                    "Production requires a current organization-scoped agent credential"
                )
            evidence = json.loads(private_file(self.storage_evidence_file))
            if (
                evidence.get("organization") != self.organization
                or not evidence.get("encrypted_volume_id")
                or not evidence.get("restricted_access_review")
                or not evidence.get("encrypted_backup_location")
                or not evidence.get("recovery_test_reference")
                or timestamp(evidence["valid_until"]) <= datetime.now(timezone.utc)
            ):
                raise ValueError("Current storage/access/recovery evidence is required")
            if database_path is not None and not Path(
                database_path
            ).resolve().is_relative_to(Path(evidence["database_directory"]).resolve()):
                raise ValueError(
                    "Database path is outside the reviewed encrypted volume directory"
                )
            from backend.lifecycle import RetentionPolicy

            RetentionPolicy.load(self.retention_policy_file)


class Authenticator:
    def __init__(self, settings, development_key=""):
        self.settings = settings
        self.development_key = development_key

    def authenticate(self, request, roles):
        # Trust ASGI scheme only; deployments must restrict forwarded headers to
        # their TLS ingress. Never use an arbitrary X-Forwarded-Proto here.
        peer = request.client.host if request.client else ""
        if request.url.scheme != "https" and (
            self.settings.environment == "production"
            or peer not in {"127.0.0.1", "::1", "testclient", "test"}
        ):
            raise DomainError("FORBIDDEN")
        authorization = request.headers.get("authorization", "")
        supplied = (
            authorization.removeprefix("Bearer ")
            if authorization.startswith("Bearer ")
            else request.headers.get("x-agent-key", "")
        )
        if not supplied:
            raise DomainError("UNAUTHORIZED")
        if self.settings.environment == "production" and len(supplied) < 32:
            raise DomainError("UNAUTHORIZED")
        principal = None
        if self.settings.credentials_file:
            # Reload on every request: atomic secret-file replacement revokes a
            # credential without restarting or disturbing other active calls.
            records = json.loads(private_file(self.settings.credentials_file))
            now = datetime.now(timezone.utc)
            for record in records:
                if hmac.compare_digest(
                    digest(supplied), record["sha256"]
                ) and timestamp(record["not_before"]) <= now < timestamp(
                    record["expires_at"]
                ):
                    principal = Principal(
                        record["subject"], record["organization"], record["role"]
                    )
                    break
        elif (
            self.settings.environment == "synthetic"
            and supplied
            and self.development_key
            and hmac.compare_digest(supplied.encode(), self.development_key.encode())
        ):
            principal = Principal(
                "development-agent", self.settings.organization, "agent"
            )
        if principal is None:
            raise DomainError("UNAUTHORIZED")
        if (
            principal.organization != self.settings.organization
            or principal.role not in roles
        ):
            raise DomainError("FORBIDDEN")
        return principal


def authorize_call(conn, call_id, access):
    row = conn.execute(
        "SELECT owner_subject, key_hash FROM call_access WHERE call_id=?", (call_id,)
    ).fetchone()
    if (
        not row
        or not access.call_key
        or row["owner_subject"] != access.principal.subject
        or not hmac.compare_digest(row["key_hash"], digest(access.call_key))
    ):
        # Same refusal for unknown and inaccessible calls; no existence oracle.
        raise DomainError("FORBIDDEN")
