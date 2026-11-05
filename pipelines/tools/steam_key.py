#!/usr/bin/env python3
"""Give the warehouse the Steam account's Web API key, once, on the workstation.

    python3 pipelines/tools/steam_key.py

Asks for the key (steamcommunity.com/dev/apikey) without echoing it, and
for the account's SteamID64 - the 17 digits in the profile's address, or
steamid.io for a custom one. Checks both with Steam - the account's name,
and whether its game details are public, without which the library comes
back empty - then writes STEAM_API_KEY and STEAM_ID into the
airflow-sources Secret with `sops set`. Nothing secret is printed. Run it
from anywhere in the repo, on a machine with sops and the age key. Standard
library only. The whole procedure: pipelines/steam.md.
"""

from __future__ import annotations

import base64
import getpass
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRET = Path(__file__).resolve().parents[2] / "clusters/lab/airflow/sources.sops.yaml"
API = "https://api.steampowered.com"


def get(method: str, **params) -> dict:
    url = f"{API}/{method}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Never the URL: it holds the key.
        sys.exit(f"Steam answered {e.code} to {method}" +
                 (" - is the key right?" if e.code in (401, 403) else ""))


def sops_set(key: str, value: str) -> None:
    encoded = json.dumps(base64.b64encode(value.encode()).decode())
    subprocess.run(["sops", "set", str(SECRET), f'["data"]["{key}"]', encoded], check=True)


def main() -> None:
    if not SECRET.exists():
        sys.exit(f"{SECRET} not found")
    key = getpass.getpass("Steam Web API key: ").strip()
    steamid = input("SteamID64 (17 digits): ").strip()
    if not key or not (steamid.isdigit() and len(steamid) == 17):
        sys.exit("a key and a 17-digit SteamID64 are needed - pipelines/steam.md")

    players = get("ISteamUser/GetPlayerSummaries/v2", key=key, steamids=steamid)
    found = players.get("response", {}).get("players", [])
    if not found:
        sys.exit("Steam knows no account with that SteamID64")
    print(f"Account: {found[0].get('personaname', '?')}", file=sys.stderr)
    owned = get("IPlayerService/GetOwnedGames/v1", key=key, steamid=steamid).get("response", {})
    if "games" in owned:
        print(f"Library: {owned.get('game_count', len(owned['games']))} games", file=sys.stderr)
    else:
        print("Library: Steam lists none - set the profile's 'Game details' to Public "
              "(pipelines/steam.md); writing the key anyway.", file=sys.stderr)

    sops_set("STEAM_API_KEY", key)
    sops_set("STEAM_ID", steamid)
    print(f"Written to {SECRET.name}: STEAM_API_KEY, STEAM_ID. Commit, push, then restart "
          "the scheduler (pipelines/steam.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
