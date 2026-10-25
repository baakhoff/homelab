"""Telegram accounts' private chats, into the warehouse.

Telegram's bot API sees only chats a bot is in, so this logs in as the
account itself, over MTProto with Telethon - the protocol the official apps
speak - and reads what the account can read. Private, one-to-one chats only,
the account's own Saved Messages included; no groups, no channels, no chats
with bots. Secret chats exist only on the phones and are out of reach.

Each message goes to Kafka topic raw.telegram in the usual envelope
(pipelines/dags/ingest.py), as text and metadata: who, when, the text, what
it replied to or was forwarded from, and for a photo, voice message or file
its kind, size, duration and name.

Not a full snapshot like the other sources: years of messages are too many to
send every hour. Variable telegram_sync holds, per chat, the newest message id
already sent, and each run sends what is newer; a chat seen for the first
time is read from its first message, as many chats per run as fit in
BUDGET. Chats with messages in the last EDIT_DAYS days are also read back
that far, so an edit made since reaches the warehouse - the ods model keeps
each message's newest version. A deletion does not: Telegram tells a client
about deletions only as they happen, and this one is not listening then.

The files go into the NAS archive (archive.py), in a second task, media:
photos, videos, voice messages, video notes, audio and documents, each up to
MEDIA_MAX. Stickers, GIFs and link previews stay metadata. Each file is
stored under its hash and gets a record on raw.files, endpoint `telegram`,
id the message's own id in raw.telegram - so ods.files' ref is
ods.telegram_messages' message_key. Variable telegram_media holds, per chat,
the newest message whose media was handled, never past telegram_sync's, so a
file's message is always in the warehouse first; a chat seen for the first
time is read from its first message, MEDIA_BUDGET per run. A file Telegram
will not hand over - an expired file reference, a message deleted since - is
logged and skipped. media runs after sync, never beside it: Telegram ends a
session used over two connections at once (AUTH_KEY_DUPLICATED).

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
progress is in Variables telegram_sync_<name> and telegram_media_<name>.
One account's dead session fails the run after the others are read, not
before.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pendulum
from airflow.sdk import Variable, dag, task

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file - and the NAS archive, archive.py. Airflow
# puts the DAG folder, pipelines/, on the import path, not dags/, so the
# directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archive  # noqa: E402
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
# The media task's progress, the same way: `main`'s, and MEDIA_STATE +
# "_<name>" for another account.
MEDIA_STATE = "telegram_media"
# The media kinds, as _media() names them, whose files go into the archive.
ARCHIVED = {"photo", "video", "voice", "video_note", "audio", "document"}
# A bigger file is skipped, and counted in the task's log.
MEDIA_MAX = 1 << 30
# Downloading stops after this long and the next run carries on, so the
# history's files go in a portion an hour.
MEDIA_BUDGET = timedelta(minutes=30)
# Progress is saved every this many files stored, so a failed run fetches
# at most this many again.
MEDIA_SAVE_EVERY = 20


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


def to_archive(media: dict | None) -> bool:
    """Whether a message's media, as _media() describes it, is a file for the
    archive. Not a link's preview, which _media() calls a photo when it has
    a picture, and not media whose file is gone - a self-destructing photo
    once seen - which has no size."""
    return media is not None and media["kind"] in ARCHIVED and "url" not in media and "size" in media


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


async def _authorize(client, session_key: str) -> None:
    """Fails, saying what to do, when Telegram no longer takes the session."""
    from telethon.errors import AuthKeyUnregisteredError, SessionRevokedError

    try:
        authorized = await client.is_user_authorized()
    except (AuthKeyUnregisteredError, SessionRevokedError):
        authorized = False
    if not authorized:
        raise RuntimeError(f"Telegram no longer accepts {session_key} - the session was ended "
                           "under Settings -> Devices, or expired. pipelines/telegram.md, \"Renewing\"")


async def _sync(raw: _Raw, account: str, session_key: str, state: dict, save, started: float) -> None:
    now = datetime.now(timezone.utc)
    prefix = "" if account == "main" else f"{account}:"

    def send(endpoint, rid, record):
        raw.send(endpoint, prefix + rid, {**record, "account": account})

    async with _client(session_key) as client:
        await _authorize(client, session_key)

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


async def _download(client, m, label: str) -> dict | None:
    """A message's file, stored in the archive: store()'s fields, or None
    when Telegram does not hand it over."""
    from telethon.errors import BadRequestError, ForbiddenError, NotFoundError

    tmp = archive.tmp_path()
    try:
        got = await client.download_media(m, file=str(tmp))
    # This file's own trouble: an expired file reference, a message deleted
    # since - Telethon, fetching it again, gets None, hence AttributeError.
    # Anything else - the connection, the NAS, a long "wait", the login -
    # fails the account, and the file is tried again next run.
    except (BadRequestError, ForbiddenError, NotFoundError, AttributeError) as e:
        print(f"{label}: not downloaded, {type(e).__name__}: {e}")
        got = None
    if got is None:
        for p in tmp.parent.glob(f"{tmp.name}*"):  # what was written of it
            p.unlink()
        return None
    # Telethon adds an extension to a name without one, so the file is
    # where it says, not at tmp.
    return archive.store(Path(got))


async def _store_media(files: archive.Files, account: str, session_key: str, synced: dict, state: dict,
                       save, started: float) -> None:
    prefix = "" if account == "main" else f"{account}:"
    stored = too_big = failed = unsaved = 0

    def spent():
        return time.monotonic() - started > MEDIA_BUDGET.total_seconds()

    async with _client(session_key) as client:
        await _authorize(client, session_key)

        dialogs = [d async for d in client.iter_dialogs() if is_private(d)]
        # Chats already under way first, the backlog after, so one long first
        # import never holds up today's photos.
        dialogs.sort(key=lambda d: str(d.id) not in state)
        for d in dialogs:
            if spent():
                print(f"{account}: budget spent; the next run carries on")
                break
            key = str(d.id)
            # No further than sync has sent, so a file's message is always in
            # the warehouse before the file is.
            last, upto = state.get(key, 0), synced.get(key, 0)
            if upto <= last:
                continue
            async for m in client.iter_messages(d.entity, reverse=True, min_id=last, max_id=upto + 1):
                if spent():
                    break
                media = _media(m)
                if to_archive(media):
                    if media["size"] > MEDIA_MAX:
                        too_big += 1
                    elif (record := await _download(client, m, f"{account}: {d.id}/{m.id}")) is None:
                        failed += 1
                    else:
                        files.send("telegram", f"{prefix}{d.id}/{m.id}", {
                            **record,
                            "name": m.file.name,
                            "mime_type": m.file.mime_type,
                            "kind": media["kind"],
                            "account": account,
                            "chat_id": d.id,
                            "message_id": m.id,
                        })
                        stored += 1
                        unsaved += 1
                state[key] = m.id
                if unsaved == MEDIA_SAVE_EVERY:
                    files.flush()
                    save(state)
                    unsaved = 0
            else:
                # The whole way: a message deleted since sync sent it is not
                # waited for.
                state[key] = upto
            files.flush()
            save(state)
            unsaved = 0
    print(f"{account}: {stored} files to {archive.TOPIC}; skipped {too_big} over MEDIA_MAX, "
          f"{failed} not downloaded")


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

    # MEDIA_BUDGET, and room for the file being fetched when it runs out. It
    # runs when sync failed too, so one account's dead session holds up no
    # other account's files; it never goes past what sync sent.
    @task(execution_timeout=timedelta(minutes=45), trigger_rule="all_done")
    def media() -> None:
        from airflow.sdk import get_current_context

        files = archive.Files(get_current_context()["run_id"])
        # One budget for the whole run, `main` first, as in sync.
        started = time.monotonic()
        failed = []
        for account, session_key in accounts().items():
            suffix = "" if account == "main" else f"_{account}"
            synced = json.loads(Variable.get(STATE + suffix, default="{}"))
            state = json.loads(Variable.get(MEDIA_STATE + suffix, default="{}"))

            def save(s, var=MEDIA_STATE + suffix):
                Variable.set(var, json.dumps(s, sort_keys=True))

            try:
                asyncio.run(_store_media(files, account, session_key, synced, state, save, started))
            except Exception as e:  # the other accounts' files are still stored
                print(f"{account}: {e}")
                failed.append(account)
        if failed:
            raise RuntimeError(f"accounts' files not stored: {', '.join(failed)} - see the lines above")

    # One after the other, never at once: Telegram ends a session used over
    # two connections at the same time.
    sync() >> media()


ingest_telegram()
