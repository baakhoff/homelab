#!/usr/bin/env python3
"""Give the warehouse access to the Garmin Connect account: one login, on the workstation.

    uv run --with garminconnect==0.3.20 --with curl_cffi==0.16.0 \\
      python3 pipelines/tools/garmin_login.py

Signs in as the phone app does, through python-garminconnect - the same
version as in the Airflow image (images/airflow/Dockerfile) - asking for
the email, the password and, if the account has two-step verification,
the code, none of them echoed. Then it writes the tokens Garmin answered
with, never the password, into the airflow-sources Secret as GARMIN_TOKENS
with `sops set`. Nothing secret is printed. Run it from anywhere in the
repo, on a machine with sops and the age key, from home rather than a VPN:
Garmin blocks logins from addresses it does not like. The whole procedure:
pipelines/garmin.md.
"""

from __future__ import annotations

import base64
import getpass
import json
import subprocess
import sys
from pathlib import Path

SECRET = Path(__file__).resolve().parents[2] / "clusters/lab/airflow/sources.sops.yaml"


def main() -> None:
    try:
        from garminconnect import Garmin
    except ImportError:
        sys.exit("garminconnect is not installed - run this through uv, as the docstring says")
    if not SECRET.exists():
        sys.exit(f"{SECRET} not found")

    email = input("Garmin account email: ").strip()
    password = getpass.getpass("Password: ")
    api = Garmin(email, password, prompt_mfa=lambda: getpass.getpass("Two-step verification code: ").strip())
    api.login()
    tokens = api.client.dumps()
    if not json.loads(tokens).get("di_refresh_token"):
        sys.exit("Garmin answered without a refresh token - the DAG could not renew it; not written")
    print(f"Signed in as {api.get_full_name() or 'the account'}.", file=sys.stderr)

    encoded = json.dumps(base64.b64encode(tokens.encode()).decode())
    subprocess.run(["sops", "set", str(SECRET), '["data"]["GARMIN_TOKENS"]', encoded], check=True)
    print(f"Written to {SECRET.name}: GARMIN_TOKENS. Commit, push, then restart the "
          "scheduler (pipelines/garmin.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
