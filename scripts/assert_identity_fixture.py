"""Check the real saved outcome after the isolated identity scenario."""

import argparse
import sqlite3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    try:
        assert (
            conn.execute("SELECT organization FROM deployment_scope").fetchone()[0]
            == "identity-test-only"
        )
        calls = conn.execute("SELECT count(*) FROM calls").fetchone()[0]
        assert calls > 0, "The scenario never reached the real backend"
        assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM calls WHERE verification_status='verified'"
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT count(*) FROM identity_reviews").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM tasks WHERE category='verification_failed'"
            ).fetchone()[0]
            == calls
        )
    finally:
        conn.close()
    print(
        "Identity outcome verified: help saved, no patient verified, no appointment booked."
    )


if __name__ == "__main__":
    main()
