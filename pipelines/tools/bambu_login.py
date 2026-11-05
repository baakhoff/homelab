#!/usr/bin/env python3
"""Give the warehouse access to the Bambu Lab account: one login, on the workstation.

    uv run --with curl_cffi==0.16.0 python3 pipelines/tools/bambu_login.py

Signs in to Bambu Lab's cloud as the slicer does, asking for the email and
the password, then for the code Bambu emails when it wants one, or the
authenticator's code if the account has two-step verification - none of
them echoed. Checks the token by listing the printers, says how many there
are, and writes the token, never the password, into the airflow-sources
Secret as BAMBU_TOKEN with `sops set`. Nothing secret is printed. Run it
from anywhere in the repo, on a machine with sops and the age key. curl_cffi
is the same version as in the Airflow image (images/airflow/Dockerfile): it
gets past the Cloudflare in front of Bambu's API, which plain clients do
not. The whole procedure: pipelines/bambu.md.
"""

from __future__ import annotations

import base64
import getpass
import json
import subprocess
import sys
from pathlib import Path

SECRET = Path(__file__).resolve().parents[2] / "clusters/lab/airflow/sources.sops.yaml"
API = "https://api.bambulab.com"
WEB = "https://bambulab.com"


def fail(r, what: str) -> None:
    # The status and Bambu's own error message, never the request.
    try:
        msg = r.json().get("message") or r.json().get("error") or ""
    except ValueError:
        msg = "cloudflare" if "cloudflare" in r.text.lower() else ""
    sys.exit(f"{what}: Bambu answered {r.status_code} {msg}".rstrip())


def login(s) -> str:
    email = input("Bambu Lab account email: ").strip()
    password = getpass.getpass("Password: ")
    r = s.post(f"{API}/v1/user-service/user/login", json={"account": email, "password": password})
    if not r.ok:
        fail(r, "login")
    answer = r.json()
    if answer.get("accessToken"):
        return answer["accessToken"]

    kind = answer.get("loginType")
    if kind == "verifyCode":
        # Bambu wants an emailed code on a new device: ask it to send one.
        r = s.post(f"{API}/v1/user-service/user/sendemail/code", json={"email": email, "type": "codeLogin"})
        if not r.ok:
            fail(r, "asking for the code")
        code = getpass.getpass("The code Bambu just emailed: ").strip()
        r = s.post(f"{API}/v1/user-service/user/login", json={"account": email, "code": code})
        if not r.ok:
            fail(r, "login with the code")
        return r.json().get("accessToken", "")

    if kind == "tfa":
        # Two-step verification goes through the website, which wants its
        # CSRF cookie first, and answers with the token as a cookie.
        csrf = s.get(f"{WEB}/api/csrf")
        token = csrf.cookies.get("bbl_csrf_token")
        if not token:
            fail(csrf, "the website's CSRF cookie")
        code = getpass.getpass("Two-step verification code: ").strip()
        r = s.post(f"{WEB}/api/sign-in/tfa", json={"tfaKey": answer.get("tfaKey"), "tfaCode": code},
                   headers={"x-bbl-csrf-token": token})
        if not r.ok:
            fail(r, "two-step verification")
        return r.cookies.get("token") or ""

    sys.exit(f"Bambu asked for a login this does not know: {kind!r}")


def main() -> None:
    try:
        from curl_cffi import requests
    except ImportError:
        sys.exit("curl_cffi is not installed - run this through uv, as the docstring says")
    if not SECRET.exists():
        sys.exit(f"{SECRET} not found")

    s = requests.Session(impersonate="chrome")
    token = login(s)
    if not token:
        sys.exit("Bambu answered without a token - not written")

    r = s.get(f"{API}/v1/iot-service/api/user/bind", headers={"Authorization": f"Bearer {token}"})
    if not r.ok:
        fail(r, "listing the printers with the new token")
    devices = r.json().get("devices") or []
    print(f"Signed in: {len(devices)} printer(s) - "
          + (", ".join(d.get("dev_product_name", "?") for d in devices) or "none"), file=sys.stderr)

    encoded = json.dumps(base64.b64encode(token.encode()).decode())
    subprocess.run(["sops", "set", str(SECRET), '["data"]["BAMBU_TOKEN"]', encoded], check=True)
    print(f"Written to {SECRET.name}: BAMBU_TOKEN. Commit, push, then restart the "
          "scheduler (pipelines/bambu.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
