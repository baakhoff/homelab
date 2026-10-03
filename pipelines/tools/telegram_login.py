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
"""

from __future__ import annotations

import asyncio
import base64
import getpass
import importlib.util
import json
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

    api_id = getpass.getpass("api_id: ").strip()
    api_hash = getpass.getpass("api_hash: ").strip()
    if not api_id.isdigit() or not api_hash:
        fail("api_id is a number and api_hash is needed - my.telegram.org -> API development tools")

    session, name = asyncio.run(login(int(api_id), api_hash))
    sops_set("TELEGRAM_API_ID", api_id)
    sops_set("TELEGRAM_API_HASH", api_hash)
    sops_set("TELEGRAM_SESSION", session)
    print(f"Logged in as {name}. Written to {SECRET.name}: TELEGRAM_API_ID, TELEGRAM_API_HASH, "
          "TELEGRAM_SESSION. Commit, push, then restart the scheduler (pipelines/telegram.md).",
          file=sys.stderr)


if __name__ == "__main__":
    main()
