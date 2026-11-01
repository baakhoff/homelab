"""Telegram accounts' private chats, into the warehouse.

Telegram's bot API sees only chats a bot is in, so this logs in as the
account itself, over MTProto with Telethon - the protocol the official apps
speak - and reads what the account can read. Private, one-to-one chats only,
the account's own Saved Messages included; no groups, no channels, no chats
with bots. Secret chats exist only on the phones and are out of reach.

Each message goes to Kafka topic raw.telegram in the usual envelope
(pipelines/dags/ingest.py), as text and metadata: who, when, the text, what
it replied to or was forwarded from, and for a photo, voice message or file
its kind, size, duration and name - never the file itself.

Not a full snapshot like the other sources: years of messages are too many to
send every hour. Variable telegram_sync holds, per chat, the newest message id
already sent, and each run sends what is newer; a chat seen for the first
time is read from its first message, as many chats per run as fit in
BUDGET. Chats with messages in the last EDIT_DAYS days are also read back
that far, so an edit made since reaches the warehouse - the ods model keeps
each message's newest version. A deletion does not: Telegram tells a client
about deletions only as they happen, and this one is not listening then.

The login is a Telethon session string, made once on the workstation by
pipelines/tools/telegram_login.py and kept in the airflow-sources Secret with
the app's api_id and api_hash. It is a full login to the account: ending it
under Settings -> Devices in Telegram cuts this DAG off. pipelines/telegram.md
has the setup.

Every session in the Secret is read, one account after another in a run:
TELEGRAM_SESSION is the account called `main`, TELEGRAM_SESSION_<NAME> the
account called <name>. Each record carries its account. `main` keeps the
ids and the Variable it had before there was more than one, so its history
in raw carries on; another account's ids start with "<name>:" and its
progress is in Variable telegram_sync_<name>. One account's dead session
fails the run after the others are read, not before.

A second task, photos, sends the photos and videos in new messages to
Immich, into the album Telegram: the same media pipelines/tools/
telegram_media.py fetches - photos, videos, round video messages, images and
videos sent as files; no stickers or GIFs, no video over 1 GB, nothing
self-destructing - named and dated the same way. That tool fetches the
history once; this carries on from where the account's chats stood on its
first run, which only notes that and uploads nothing. Variable
telegram_photos (telegram_photos_<name>) holds, per chat, the newest message
done; a chat new since gets all its media. It runs after sync, with the same
session, never at the same time, and is skipped until the Secret has
IMMICH_TELEGRAM_API_KEY: the owner's own Immich key with only asset.upload,
album.read, album.create and albumAsset.create (pipelines/telegram.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pendulum
from airflow.sdk import Variable, dag, task

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sensitive import mask_record  # noqa: E402

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.telegram"
# `main`'s progress; another account's is STATE + "_<name>".
STATE = "telegram_sync"
# Reading stops after this long, at the next save, and the next run carries
# on; the first runs work through the history this way.
BUDGET = timedelta(minutes=40)
EDIT_DAYS = 3
# The newest message id sent is saved every this many messages, so a run
# that fails part-way through a long chat does not start it over.
SAVE_EVERY = 2000

# The photos task's progress, as STATE's; its own share of the hour; the
# largest video it takes; and the album, the one telegram_media.py's upload
# goes to.
PHOTO_STATE = "telegram_photos"
PHOTO_BUDGET = timedelta(minutes=10)
VIDEO_LIMIT = 1 << 30
IMMICH = "http://immich-server.immich.svc.cluster.local/api"
ALBUM = "Telegram"
# The household's clock, for the names, as in telegram_media.py.
ZONE = ZoneInfo("Europe/Copenhagen")


def _media(m) -> dict | None:
    """What a message carried besides text, as metadata only."""
    if not m.media:
        return None
    for kind in ("voice", "video_note", "sticker", "gif", "video", "audio", "photo"):
        if getattr(m, kind):
            break
    else:
        kind = "document" if m.document else type(m.media).__name__.removeprefix("MessageMedia").lower()
    media = {"kind": kind}
    if m.file is not None:
        for field in ("mime_type", "size", "duration", "name", "width", "height"):
            try:
                value = getattr(m.file, field)
            except (AttributeError, TypeError):
                value = None
            if value is not None:
                media[field] = value
    if m.geo is not None:
        media["lat"], media["lon"] = m.geo.lat, m.geo.long
    if m.web_preview is not None:
        media["url"] = getattr(m.web_preview, "url", None)
    return media


def _action(m) -> dict | None:
    """A service message - a call, a pinned message, a changed photo - by kind."""
    if m.action is None:
        return None
    action = {"kind": type(m.action).__name__.removeprefix("MessageAction")}
    if action["kind"] == "PhoneCall":
        action["duration"] = getattr(m.action, "duration", None)
        action["video"] = bool(getattr(m.action, "video", False))
        reason = getattr(m.action, "reason", None)
        action["reason"] = type(reason).__name__.removeprefix("PhoneCallDiscardReason") if reason else None
    return action


def media_kind(m) -> str | None:
    """"photo" or "video" for a message whose file goes to Immich, else None.
    The same choice as kind() in pipelines/tools/telegram_media.py."""
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


def media_name(owner: int, chat: int, m, kind: str) -> str:
    """TG_<date>_<time>_<hash>.<ext>, the name telegram_media.py gives it."""
    h = hashlib.sha256(f"{owner}/{chat}/{m.id}".encode()).hexdigest()[:12]
    ext = (m.file.ext if m.file else None) or (".jpg" if kind == "photo" else ".mp4")
    return f"TG_{m.date.astimezone(ZONE):%Y%m%d_%H%M%S}_{h}{'.jpg' if ext == '.jpeg' else ext}"


class _Immich:
    """Uploads into the album, with the owner's upload-only key."""

    def __init__(self, key: str):
        import requests

        self.s = requests.Session()
        self.s.headers["x-api-key"] = key
        self.album = None

    def call(self, method: str, path: str, **kw):
        r = self.s.request(method, f"{IMMICH}{path}", timeout=600, **kw)
        r.raise_for_status()
        return r.json()

    def upload(self, path: str, name: str, when: datetime) -> None:
        """The file as the owner's, and into the album. A file Immich has
        already - from telegram_media.py, or sent in two chats - is not
        stored twice; it is put in the album all the same."""
        if self.album is None:
            owned = self.call("GET", "/albums", params={"isOwned": "true"})
            self.album = next((a["id"] for a in owned if a["albumName"] == ALBUM), None) \
                or self.call("POST", "/albums", json={"albumName": ALBUM})["id"]
        with open(path, "rb") as f:
            asset = self.call("POST", "/assets", files={"assetData": (name, f)}, data={
                "fileCreatedAt": _iso(when), "fileModifiedAt": _iso(when), "filename": name})
        self.call("PUT", f"/albums/{self.album}/assets", json={"ids": [asset["id"]]})


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def message_record(chat_id: int, m) -> dict:
    """The warehouse's view of one message."""
    fwd = m.fwd_from
    reply = m.reply_to
    return {
        "chat_id": chat_id,
        "id": m.id,
        "date": _iso(m.date),
        "edit_date": _iso(m.edit_date),
        "out": bool(m.out),
        "sender_id": m.sender_id,
        "text": m.message or "",
        "reply_to_msg_id": getattr(reply, "reply_to_msg_id", None) if reply else None,
        "forwarded": None if fwd is None else {
            "date": _iso(fwd.date),
            "from_id": getattr(fwd.from_id, "user_id", None)
            or getattr(fwd.from_id, "channel_id", None)
            or getattr(fwd.from_id, "chat_id", None),
            "from_name": fwd.from_name,
        },
        "grouped_id": m.grouped_id,
        "media": _media(m),
        "action": _action(m),
    }


def chat_record(d) -> dict:
    """The warehouse's view of one private chat: the person, and the chat's state.

    Enough to tell later who someone was, whatever they rename: the user id,
    which never changes; every username, since a profile can hold several
    and change them; a link that opens the profile; and the phone number
    when Telegram shows it to this account - for contacts, and for people
    whose privacy settings allow it, otherwise None. `name` is the name the
    account saved the contact under, if it did, else the person's own.
    """
    u = d.entity
    usernames = [x.username for x in (u.usernames or []) if getattr(x, "active", True)]
    if u.username and u.username not in usernames:
        usernames.insert(0, u.username)
    return {
        "id": d.id,
        "user_id": u.id,
        "name": d.name,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "username": u.username or (usernames[0] if usernames else None),
        "usernames": usernames,
        "phone": f"+{u.phone}" if u.phone else None,
        # A username link works for anyone; the id link opens the profile in
        # the Telegram app only for an account that has seen this person,
        # which this one has.
        "link": f"https://t.me/{usernames[0]}" if usernames else f"tg://user?id={u.id}",
        "is_self": bool(u.is_self),
        "is_contact": bool(u.contact),
        "is_mutual_contact": bool(u.mutual_contact),
        "is_deleted": bool(u.deleted),
        "archived": bool(d.archived),
        "unread_count": d.unread_count,
        "last_message_at": _iso(d.date),
    }


def is_private(d) -> bool:
    """A one-to-one chat with a person, or the account's own Saved Messages."""
    return d.is_user and not getattr(d.entity, "bot", False)


class _Raw:
    """The Kafka producer, in the envelope every source uses."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self.run_id = run_id
        self.extracted_at = datetime.now(timezone.utc).isoformat()
        self.errors: list[str] = []
        self.counts: dict[str, int] = {}
        self.producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
        })

    def send(self, endpoint: str, rid: str, record: dict) -> None:
        record, flags = mask_record(record)
        envelope = {
            "source": "telegram",
            "endpoint": endpoint,
            "extracted_at": self.extracted_at,
            "run_id": self.run_id,
            "id": rid,
            "record": record,
            **flags,
        }
        value = json.dumps(envelope, ensure_ascii=False).encode()
        while True:
            try:
                self.producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                      on_delivery=self._delivered)
                break
            except BufferError:
                self.producer.poll(1)
        self.producer.poll(0)
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def _delivered(self, err, _msg):
        if err is not None:
            self.errors.append(str(err))

    def flush(self) -> None:
        left = self.producer.flush(60)
        if left or self.errors:
            raise RuntimeError(f"{left} undelivered, errors: {self.errors[:3]}")
        print(f"to {TOPIC}: {self.counts or 'nothing new'}")


def accounts() -> dict[str, str]:
    """Account name -> the Secret key holding its session, `main` first."""
    found = {}
    for key in sorted(os.environ):
        if key == "TELEGRAM_SESSION":
            found = {"main": key, **found}
        elif key.startswith("TELEGRAM_SESSION_") and os.environ[key]:
            found[key.removeprefix("TELEGRAM_SESSION_").lower()] = key
    return found


def _client(session_key: str):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    missing = [k for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", session_key) if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} not set - see pipelines/telegram.md")
    return TelegramClient(
        StringSession(os.environ[session_key]),
        int(os.environ["TELEGRAM_API_ID"]),
        os.environ["TELEGRAM_API_HASH"],
        # Telegram answers "wait N seconds" when read too fast; Telethon
        # waits by itself up to this, and fails beyond it.
        flood_sleep_threshold=300,
        receive_updates=False,
        device_model="homelab warehouse",
    )


async def _sync(raw: _Raw, account: str, session_key: str, state: dict, save, started: float) -> None:
    from telethon.errors import AuthKeyUnregisteredError, SessionRevokedError

    now = datetime.now(timezone.utc)
    prefix = "" if account == "main" else f"{account}:"

    def send(endpoint, rid, record):
        raw.send(endpoint, prefix + rid, {**record, "account": account})

    async with _client(session_key) as client:
        try:
            authorized = await client.is_user_authorized()
        except (AuthKeyUnregisteredError, SessionRevokedError):
            authorized = False
        if not authorized:
            raise RuntimeError(f"Telegram no longer accepts {session_key} - the session was ended "
                               "under Settings -> Devices, or expired. pipelines/telegram.md, \"Renewing\"")

        dialogs = [d async for d in client.iter_dialogs() if is_private(d)]
        for d in dialogs:
            send("chats", str(d.id), chat_record(d))

        # Chats with something new first, the backlog of unread history
        # after, so one long first import never holds up today's messages.
        def pending(d):
            return d.message is not None and d.message.id > state.get(str(d.id), 0)

        dialogs.sort(key=lambda d: (str(d.id) not in state, not pending(d)))
        for d in dialogs:
            if time.monotonic() - started > BUDGET.total_seconds():
                print(f"{account}: budget spent; the next run carries on")
                break
            key = str(d.id)
            last = state.get(key, 0)
            if pending(d):
                n = 0
                async for m in client.iter_messages(d.entity, reverse=True, min_id=last):
                    send("messages", f"{d.id}/{m.id}", message_record(d.id, m))
                    state[key] = m.id
                    n += 1
                    if n % SAVE_EVERY == 0:
                        raw.flush()
                        save(state)
                        if time.monotonic() - started > BUDGET.total_seconds():
                            break
                raw.flush()
                save(state)
            # Edits in the recent past, for chats active in it. Read
            # up to what was already sent; anything newer was just read.
            if last and d.date and d.date > now - timedelta(days=EDIT_DAYS):
                async for m in client.iter_messages(d.entity, reverse=True, max_id=last + 1,
                                                    offset_date=now - timedelta(days=EDIT_DAYS)):
                    if m.edit_date:
                        send("messages", f"{d.id}/{m.id}", message_record(d.id, m))


async def _photos(immich: _Immich, account: str, session_key: str, state: dict, save,
                  started: float, counts: dict) -> None:
    async with _client(session_key) as client:
        if not await client.is_user_authorized():
            raise RuntimeError(f"Telegram no longer accepts {session_key}")
        owner = (await client.get_me()).id
        dialogs = [d async for d in client.iter_dialogs() if is_private(d)]
        if not state:
            # The first run: the history is telegram_media.py's.
            save({str(d.id): d.message.id if d.message else 0 for d in dialogs})
            print(f"{account}: photos start from here")
            return
        with tempfile.TemporaryDirectory() as tmp:
            for d in dialogs:
                key = str(d.id)
                if d.message is None or d.message.id <= state.get(key, 0):
                    continue
                if time.monotonic() - started > PHOTO_BUDGET.total_seconds():
                    print(f"{account}: photo budget spent; the next run carries on")
                    break
                try:
                    async for m in client.iter_messages(d.entity, reverse=True, min_id=state.get(key, 0)):
                        k = media_kind(m)
                        if k and not (k == "video" and m.file and (m.file.size or 0) > VIDEO_LIMIT):
                            if time.monotonic() - started > PHOTO_BUDGET.total_seconds():
                                break  # a chat new since, with its whole history
                            name = media_name(owner, d.id, m, k)
                            path = await client.download_media(m, file=os.path.join(tmp, name))
                            immich.upload(path, name, m.date)
                            os.unlink(path)
                            counts[k] = counts.get(k, 0) + 1
                        state[key] = m.id
                finally:
                    save(state)  # what is done stays done, whatever stopped it


@dag(
    dag_id="ingest_telegram",
    schedule="20 * * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "telegram"],
    default_args={"retries": 2, "retry_delay": pendulum.duration(minutes=5)},
)
def ingest_telegram():
    @task(execution_timeout=timedelta(minutes=55))
    def sync() -> None:
        from airflow.sdk import get_current_context

        found = accounts()
        if not found:
            raise RuntimeError("no TELEGRAM_SESSION in the Secret - see pipelines/telegram.md")
        raw = _Raw(get_current_context()["run_id"])
        # One budget for the whole run, `main` first: another account's long
        # first import never holds up main's new messages.
        started = time.monotonic()
        failed = []
        for account, session_key in found.items():
            var = STATE if account == "main" else f"{STATE}_{account}"
            state = json.loads(Variable.get(var, default="{}"))

            def save(s, var=var):
                Variable.set(var, json.dumps(s, sort_keys=True))

            try:
                asyncio.run(_sync(raw, account, session_key, state, save, started))
            except Exception as e:  # the other accounts are still read
                print(f"{account}: {e}")
                failed.append(account)
            raw.flush()
        if failed:
            raise RuntimeError(f"accounts not read: {', '.join(failed)} - see the lines above")

    @task(execution_timeout=timedelta(minutes=15), trigger_rule="all_done")
    def photos() -> None:
        if not os.environ.get("IMMICH_TELEGRAM_API_KEY"):
            print("no IMMICH_TELEGRAM_API_KEY in the Secret - photos skipped, see pipelines/telegram.md")
            return
        immich = _Immich(os.environ["IMMICH_TELEGRAM_API_KEY"])
        started = time.monotonic()
        failed, counts = [], {}
        for account, session_key in accounts().items():
            var = PHOTO_STATE if account == "main" else f"{PHOTO_STATE}_{account}"
            state = json.loads(Variable.get(var, default="{}"))

            def save(s, var=var):
                Variable.set(var, json.dumps(s, sort_keys=True))

            try:
                asyncio.run(_photos(immich, account, session_key, state, save, started, counts))
            except Exception as e:  # the other accounts are still done
                print(f"{account}: {e}")
                failed.append(account)
        print(f"to Immich: {counts or 'nothing new'}")
        if failed:
            raise RuntimeError(f"accounts without photos: {', '.join(failed)} - see the lines above")

    sync() >> photos()


ingest_telegram()
