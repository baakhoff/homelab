#!/usr/bin/env python3
"""Download the photos and videos in a Telegram account's chats, for Immich.

    python3 telegram_media.py survey tg.session
    python3 telegram_media.py fetch tg.session ~/tg-media
    python3 telegram_media.py logout tg.session

The warehouse (pipelines/telegram.md) keeps media as metadata only; the
files are still on Telegram's servers, and this fetches them. The same
chats the warehouse reads: private, one-to-one chats with people and the
account's own Saved Messages - no bots, no channels. `--groups` after the
command takes in group chats too.

- survey: how many photos and videos there are, by year, and their total
  size. Nothing is saved.
- fetch: downloads every photo, video and round video message, and every
  image or video sent as a file (the uncompressed original), into a
  folder, named TG_<date>_<time>_<hash>.<ext> and dated by the message, so
  Immich places it in its own day - Telegram strips a photo's own date.
  Videos over 1 GB are skipped, and so are self-destructing ones. Run it
  again and it skips what it already has. Then upload the folder with
  immich-go (pipelines/telegram.md).
- logout: ends the login, which removes it from Settings -> Devices.

Its own login, not the warehouse's: one session used from two places at
once can make Telegram end it, and the DAG's must stay. The first run asks
for the phone number, the code and the two-step password, and keeps the
login in the session file - a full login to the account, so it is
created readable by its owner only, and ended with `logout` when done. It
is called "homelab photos" in Settings -> Devices. The app's api_id and
api_hash are asked for every run, not echoed, or read from TG_API_ID and
TG_API_HASH.

Needs Telethon (pip install telethon==1.45.0). Prints counts, never names
or contents.
"""

from __future__ import annotations

import asyncio
import getpass
import hashlib
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

DEVICE = "homelab photos"
LIMIT = 1 << 30  # 1 GB, for videos
# The household's clock, for the names: immich-go reads a date in a name as
# local time.
ZONE = ZoneInfo("Europe/Copenhagen")
WORKERS = 4


def kind(m) -> str | None:
    """"photo" or "video" for a message worth fetching, else None."""
    if not m.media or getattr(m.media, "ttl_seconds", None) or m.sticker or m.gif:
        return None
    if m.photo:
        return "photo"
    if m.video or m.video_note:
        return "video"
    mime = (m.file.mime_type or "") if m.file else ""
    if m.document:
        if mime.startswith("image/"):
            return "photo"
        if mime.startswith("video/"):
            return "video"
    return None


def stem_for(owner: int, chat: int, m) -> str:
    h = hashlib.sha256(f"{owner}/{chat}/{m.id}".encode()).hexdigest()[:12]
    return f"TG_{m.date.astimezone(ZONE):%Y%m%d_%H%M%S}_{h}"


def ext_for(m, k: str) -> str:
    ext = (m.file.ext if m.file else None) or (".jpg" if k == "photo" else ".mp4")
    return ".jpg" if ext == ".jpeg" else ext


def have(folder: Path, stem: str) -> bool:
    return any(p.suffix != ".part" for p in folder.glob(stem + ".*"))


def _filters():
    from telethon.tl.types import (InputMessagesFilterDocument, InputMessagesFilterPhotoVideo,
                                   InputMessagesFilterRoundVideo)
    # Telegram filters by kind on its side, so the rest of a chat is never read.
    return [InputMessagesFilterPhotoVideo(), InputMessagesFilterRoundVideo(), InputMessagesFilterDocument()]


def _wanted(d, groups: bool) -> bool:
    if d.is_user:
        return not getattr(d.entity, "bot", False)
    return groups and d.is_group


async def _client(session: Path):
    from telethon import TelegramClient

    api_id = os.environ.get("TG_API_ID") or getpass.getpass("api_id: ").strip()
    api_hash = os.environ.get("TG_API_HASH") or getpass.getpass("api_hash: ").strip()
    if not api_id.isdigit() or not api_hash:
        sys.exit("api_id is a number and api_hash is needed - my.telegram.org -> API development tools")
    old = os.umask(0o077)  # the session file is the login
    try:
        client = TelegramClient(str(session), int(api_id), api_hash, device_model=DEVICE,
                                receive_updates=False, flood_sleep_threshold=300)
        await client.start(
            phone=lambda: input("Phone number, international (+45...): ").strip(),
            code_callback=lambda: input("The code Telegram just sent to your other devices: ").strip(),
            password=lambda: getpass.getpass("Two-step verification password: "),
        )
    finally:
        os.umask(old)
    return client


async def _media(client, groups: bool):
    """(chat id, message, kind) for every photo and video, chat by chat."""
    async for d in client.iter_dialogs():
        if not _wanted(d, groups):
            continue
        seen = set()
        for f in _filters():
            async for m in client.iter_messages(d.entity, filter=f):
                k = kind(m)
                if k and m.id not in seen:
                    seen.add(m.id)
                    yield d.id, m, k


async def survey(session: Path, groups: bool) -> None:
    client = await _client(session)
    async with client:
        stats = {"photo": {}, "video": {}}
        size = {"photo": 0, "video": 0}
        big = 0
        async for _, m, k in _media(client, groups):
            y = str(m.date.astimezone(ZONE).year)
            stats[k][y] = stats[k].get(y, 0) + 1
            n = (m.file.size or 0) if m.file else 0
            if k == "video" and n > LIMIT:
                big += 1
            else:
                size[k] += n
        for k in ("photo", "video"):
            print(f"{k}s: {sum(stats[k].values())}, {size[k] / 1e9:.1f} GB; by year: "
                  + ", ".join(f"{y}: {c}" for y, c in sorted(stats[k].items())))
        print(f"videos over 1 GB, skipped: {big}")


async def fetch(session: Path, folder: Path, groups: bool) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    client = await _client(session)
    async with client:
        owner = (await client.get_me()).id
        counts = {"saved": 0, "already here": 0, "too big": 0, "failed": 0}
        gate = asyncio.Semaphore(WORKERS)
        running = set()

        async def one(chat, m, k):
            stem = stem_for(owner, chat, m)
            path = folder / (stem + ext_for(m, k))
            tmp = path.with_suffix(".part")
            try:
                await client.download_media(m, file=str(tmp))
                ts = m.date.timestamp()
                os.utime(tmp, (ts, ts))
                tmp.rename(path)
                counts["saved"] += 1
            except Exception:
                tmp.unlink(missing_ok=True)
                counts["failed"] += 1
            finally:
                gate.release()

        seen = 0
        async for chat, m, k in _media(client, groups):
            seen += 1
            if seen % 500 == 0:
                print(f"  {seen} seen: {counts}")
            if have(folder, stem_for(owner, chat, m)):
                counts["already here"] += 1
                continue
            if k == "video" and m.file and (m.file.size or 0) > LIMIT:
                counts["too big"] += 1
                continue
            await gate.acquire()
            t = asyncio.create_task(one(chat, m, k))
            running.add(t)
            t.add_done_callback(running.discard)
        if running:
            await asyncio.gather(*running)
        print(f"done: {counts}")
        print(f"in {folder}")


async def logout(session: Path) -> None:
    client = await _client(session)
    await client.log_out()
    print("logged out: gone from Settings -> Devices")


def main() -> None:
    args = sys.argv[1:]
    groups = "--groups" in args
    args = [a for a in args if a != "--groups"]
    if len(args) == 2 and args[0] in ("survey", "logout"):
        session = Path(args[1]).expanduser()
        asyncio.run(survey(session, groups) if args[0] == "survey" else logout(session))
    elif len(args) == 3 and args[0] == "fetch":
        asyncio.run(fetch(Path(args[1]).expanduser(), Path(args[2]).expanduser(), groups))
    else:
        sys.exit("usage: telegram_media.py survey <session file> [--groups]\n"
                 "       telegram_media.py fetch <session file> <folder> [--groups]\n"
                 "       telegram_media.py logout <session file>")


if __name__ == "__main__":
    main()
