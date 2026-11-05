#!/usr/bin/env python3
"""Log the warehouse in to Telegram, once, on the workstation.

    python3 -m venv /tmp/tg && /tmp/tg/bin/pip install telethon==1.45.0
    /tmp/tg/bin/python pipelines/tools/telegram_login.py

Asks for the app's api_id and api_hash (my.telegram.org -> API development
tools) without echoing them, then logs in the way a new Telegram app does:
the phone number, the code Telegram sends to the account's other devices,
and the two-step verification password if one is set. The result is a
Telethon session string - a full login to the account - which goes straight
into the airflow-sources Secret with `sops set`, beside the api_id and
api_hash. Nothing secret is printed. Run it from anywhere in the repo, on a
machine with sops and the age key. The whole procedure: pipelines/telegram.md.

    /tmp/tg/bin/python pipelines/tools/telegram_login.py <name>

logs in one more account, called <name> in the warehouse: its session goes
to TELEGRAM_SESSION_<NAME>, and the api_id and api_hash already in the
Secret are used rather than asked for - one app serves every account.
Without a name it is the account called `main`, in TELEGRAM_SESSION.
"""

from __future__ import annotations

import asyncio
import base64
import getpass
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

SECRET = Path(__file__).resolve().parents[2] / "clusters/lab/airflow/sources.sops.yaml"
# The name the session has in Telegram's Settings -> Devices, the same one
# the DAG connects with (pipelines/dags/telegram.py).
DEVICE = "homelab warehouse"


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def sops_set(key: str, value: str) -> None:
    """One key of the Secret, base64 as a Secret's data is."""
    encoded = json.dumps(base64.b64encode(value.encode()).decode())
    subprocess.run(["sops", "set", str(SECRET), f'["data"]["{key}"]', encoded], check=True)


def sops_get(key: str) -> str | None:
    """One key of the Secret, decoded - kept in memory, never printed."""
    r = subprocess.run(["sops", "-d", "--extract", f'["data"]["{key}"]', str(SECRET)],
                       capture_output=True, text=True)
    return base64.b64decode(r.stdout.strip()).decode() if r.returncode == 0 and r.stdout.strip() else None


async def login(api_id: int, api_hash: str) -> tuple[str, str]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(), api_id, api_hash, device_model=DEVICE, receive_updates=False)
    await client.start(
        phone=lambda: input("Phone number, international (+45...): ").strip(),
        code_callback=lambda: input("The code Telegram just sent to your other devices: ").strip(),
        password=lambda: getpass.getpass("Two-step verification password: "),
    )
    me = await client.get_me()
    session = client.session.save()
    await client.disconnect()
    return session, me.first_name or "the account"


def main() -> None:
    if importlib.util.find_spec("telethon") is None:
        fail(__doc__.split("\n\n")[1])
    if not SECRET.exists():
        fail(f"{SECRET} not found")

    account = sys.argv[1].lower() if len(sys.argv) > 1 else "main"
    if not re.fullmatch(r"[a-z][a-z0-9]{0,19}", account):
        fail("the account name is a short word of letters and digits, e.g. work")
    session_key = "TELEGRAM_SESSION" if account == "main" else f"TELEGRAM_SESSION_{account.upper()}"

    if account == "main":
        api_id = getpass.getpass("api_id: ").strip()
        api_hash = getpass.getpass("api_hash: ").strip()
    else:
        api_id, api_hash = sops_get("TELEGRAM_API_ID") or "", sops_get("TELEGRAM_API_HASH") or ""
        if not api_id:
            fail("no TELEGRAM_API_ID in the Secret yet - log in the main account first, without a name")
    if not api_id.isdigit() or not api_hash:
        fail("api_id is a number and api_hash is needed - my.telegram.org -> API development tools")

    session, name = asyncio.run(login(int(api_id), api_hash))
    written = [session_key]
    if account == "main":
        sops_set("TELEGRAM_API_ID", api_id)
        sops_set("TELEGRAM_API_HASH", api_hash)
        written = ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", session_key]
    sops_set(session_key, session)
    print(f"Logged in as {name}, account '{account}'. Written to {SECRET.name}: {', '.join(written)}. "
          "Commit, push, then restart the scheduler (pipelines/telegram.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
