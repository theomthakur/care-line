"""Isolated production-mode identity regression fixture. Synthetic data only.

Creates a fresh owner-only directory, ephemeral TLS trust, and a test-only policy
attestation. It never imports patients or issues successful identity reviews.
The attestation is a test fixture, not evidence about a deployment's encryption.
"""

import argparse
import ipaddress
import json
import os
import ssl
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.db import Database
from backend.credentials import rotate, write_private
from backend.lifecycle import RetentionPolicy
from backend.main import create_app
from backend.security import SecuritySettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--port", type=int, default=9443)
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    directory.mkdir(mode=0o700)  # Refuse reuse of a previous run's records.
    now = datetime.now(timezone.utc)
    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "identity-test-only")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    write_private(
        directory / "tls.key",
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    write_private(
        directory / "tls.pem", cert.public_bytes(serialization.Encoding.PEM).decode()
    )
    roots = "".join(
        ssl.DER_cert_to_PEM_cert(item)
        for item in ssl.create_default_context().get_ca_certs(binary_form=True)
    )
    if not roots:
        roots = Path(certifi.where()).read_text()
    write_private(
        directory / "trust.pem",
        roots + cert.public_bytes(serialization.Encoding.PEM).decode(),
    )
    rotate(
        directory / "credentials.json",
        directory / "agent.secret",
        "test-voice",
        "identity-test-only",
        "agent",
        days=1,
    )
    write_private(
        directory / "policy.json",
        json.dumps(
            asdict(
                RetentionPolicy(
                    "TEST-ONLY", "TEST-ONLY", now.isoformat(), 1, 1, 1, 1, 1, 1
                )
            )
        ),
    )
    write_private(
        directory / "evidence.json",
        json.dumps(
            {
                "organization": "identity-test-only",
                "encrypted_volume_id": "TEST-ONLY",
                "database_directory": str(directory),
                "restricted_access_review": "TEST-ONLY",
                "encrypted_backup_location": "TEST-ONLY",
                "recovery_test_reference": "TEST-ONLY",
                "valid_until": (now + timedelta(days=1)).isoformat(),
            }
        ),
    )
    settings = SecuritySettings(
        "production",
        "identity-test-only",
        str(directory / "credentials.json"),
        "TEST-ONLY",
        str(directory / "policy.json"),
        str(directory / "evidence.json"),
    )
    env = {
        "MEMBERGUIDE_ENV": "production",
        "MEMBERGUIDE_AGENT_KEY_FILE": str(directory / "agent.secret"),
        "BACKEND_URL": f"https://127.0.0.1:{args.port}",
        "SSL_CERT_FILE": str(directory / "trust.pem"),
        "AGENT_PROFILE": "mine",
        "USE_FAKE_BACKEND": "0",
    }
    write_private(
        directory / "runtime.env",
        "\n".join(f"{key}={value}" for key, value in env.items()),
    )
    os.umask(0o077)
    app = create_app(database=Database(directory / "fixture.db"), security=settings)
    print(f"Synthetic identity fixture: {directory / 'runtime.env'}", flush=True)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        ssl_keyfile=str(directory / "tls.key"),
        ssl_certfile=str(directory / "tls.pem"),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
