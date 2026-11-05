#!/usr/bin/env python3
"""Give the warehouse access to the Google account: one consent, on the workstation.

    python3 pipelines/tools/google_auth.py apis
    python3 pipelines/tools/google_auth.py portability [resource ...]

`apis` is Gmail (metadata only), Calendar, Contacts, Tasks and Drive's file
list, all read-only. `portability` is the Data Portability API - My
Activity, Chrome history, YouTube, Maps, Play, ...; name resources after it
to ask for only those. Google refuses one consent that mixes the two, so
each is its own run, and its own refresh token.

It asks for the OAuth client's id and secret without echoing them, opens
Google's consent page in the browser, takes the answer on a one-off
listener on 127.0.0.1, and writes the client and the refresh token
straight into the airflow-sources Secret with `sops set`. Nothing secret is
printed. Run it from anywhere in the repo, on a machine with sops and the
age key. Standard library only. The whole procedure: pipelines/google.md.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SECRET = Path(__file__).resolve().parents[2] / "clusters/lab/airflow/sources.sops.yaml"

API_SCOPES = [
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

# What the portability DAG exports: records, not media. Left out on
# purpose - videos, photos and Street View imagery (files, not rows),
# Chrome autofill (saved cards and addresses), and settings.
PORTABILITY_RESOURCES = [
    "myactivity.search", "myactivity.youtube", "myactivity.maps", "myactivity.play",
    "myactivity.shopping", "myactivity.myadcenter",
    "chrome.history", "chrome.bookmarks", "chrome.reading_list",
    "youtube.subscriptions", "youtube.public_playlists", "youtube.private_playlists",
    "youtube.unlisted_playlists", "youtube.comments", "youtube.music", "youtube.channel",
    "maps.starred_places", "maps.reviews", "maps.aliased_places", "maps.commute_routes",
    "saved.collections",
    "play.installs", "play.library", "play.purchases", "play.subscriptions",
    "discover.follows", "discover.likes",
    "alerts.subscriptions",
]
PORTABILITY_SCOPE = "https://www.googleapis.com/auth/dataportability."

TOKEN_KEYS = {"apis": "GOOGLE_REFRESH_TOKEN", "portability": "GOOGLE_PORTABILITY_REFRESH_TOKEN"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def consent(client_id: str, client_secret: str, scopes: list[str]) -> dict:
    """The token response for one consent: the browser to Google and back to 127.0.0.1."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    answer: dict[str, str] = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(404)
                self.end_headers()
                return
            answer.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done - back to the terminal; this tab can be closed.\n")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Callback)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    print(f"\nOpening Google's consent page. If no browser opens, open this:\n\n{url}\n",
          file=sys.stderr)
    webbrowser.open(url)
    while not answer:
        server.handle_request()
    server.server_close()
    if "error" in answer:
        fail(f"Google answered: {answer['error']}")

    data = urllib.parse.urlencode({
        "code": answer["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        fail(f"Google refused the exchange ({e.code}): {e.read().decode(errors='replace')}")


def sops_set(key: str, value: str) -> None:
    """One key of the Secret, base64 as a Secret's data is."""
    encoded = json.dumps(base64.b64encode(value.encode()).decode())
    subprocess.run(["sops", "set", str(SECRET), f'["data"]["{key}"]', encoded], check=True)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TOKEN_KEYS:
        fail(__doc__.split("\n\n")[1])
    kind = sys.argv[1]
    if kind == "apis":
        if len(sys.argv) > 2:
            fail("apis takes no resource names")
        scopes = API_SCOPES
    else:
        resources = sys.argv[2:] or PORTABILITY_RESOURCES
        scopes = [PORTABILITY_SCOPE + r for r in resources]
    if not SECRET.exists():
        fail(f"{SECRET} not found")

    client_id = getpass.getpass("OAuth client ID: ").strip()
    client_secret = getpass.getpass("OAuth client secret: ").strip()
    if not client_id or not client_secret:
        fail("both are needed - Google Cloud Console, Google Auth Platform -> Clients")

    body = consent(client_id, client_secret, scopes)
    token = body.get("refresh_token")
    if not token:
        fail("Google sent no refresh token - remove the app's access at "
             "myaccount.google.com/connections and run this again")

    granted = set(body.get("scope", "").split())
    unticked = [s.rsplit("/", 1)[1] for s in scopes if s not in granted]
    if unticked:
        print(f"Not granted (unticked on the consent page?): {', '.join(unticked)}", file=sys.stderr)
    lasts = body.get("refresh_token_expires_in")
    if lasts:
        days = int(lasts) // 86400
        print(f"This consent lasts {days} days.", file=sys.stderr)
        if days <= 7:
            print("Seven days means the app is still in Testing: publish it "
                  "(Google Auth Platform -> Audience -> Publish app) and run this again.",
                  file=sys.stderr)

    sops_set("GOOGLE_CLIENT_ID", client_id)
    sops_set("GOOGLE_CLIENT_SECRET", client_secret)
    sops_set(TOKEN_KEYS[kind], token)
    print(f"Written to {SECRET.name}: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, {TOKEN_KEYS[kind]}. "
          "Commit, push, then restart the scheduler (pipelines/google.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
