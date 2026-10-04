"""One Telegram account's private chats, into the warehouse.

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
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pendulum
from airflow.sdk import Variable, dag, task

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.telegram"
STATE = "telegram_sync"
# Reading stops after this long, at the next save, and the next run carries
# on; the first runs work through the history this way.
BUDGET = timedelta(minutes=40)
EDIT_DAYS = 3
# The newest message id sent is saved every this many messages, so a run
# that fails part-way through a long chat does not start it over.
SAVE_EVERY = 2000


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
    """The warehouse's view of one private chat: the person, and the chat's state."""
    u = d.entity
    return {
        "id": d.id,
        "name": d.name,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "username": u.username,
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
        envelope = {
            "source": "telegram",
            "endpoint": endpoint,
            "extracted_at": self.extracted_at,
            "run_id": self.run_id,
            "id": rid,
            "record": record,
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


def _client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    missing = [k for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} not set - see pipelines/telegram.md")
    return TelegramClient(
        StringSession(os.environ["TELEGRAM_SESSION"]),
        int(os.environ["TELEGRAM_API_ID"]),
        os.environ["TELEGRAM_API_HASH"],
        # Telegram answers "wait N seconds" when read too fast; Telethon
        # waits by itself up to this, and fails beyond it.
        flood_sleep_threshold=300,
        receive_updates=False,
        device_model="homelab warehouse",
    )


async def _sync(raw: _Raw, state: dict, save) -> None:
    from telethon.errors import AuthKeyUnregisteredError, SessionRevokedError

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    async with _client() as client:
        try:
            authorized = await client.is_user_authorized()
        except (AuthKeyUnregisteredError, SessionRevokedError):
            authorized = False
        if not authorized:
            raise RuntimeError("Telegram no longer accepts TELEGRAM_SESSION - the session was ended "
                               "under Settings -> Devices, or expired. pipelines/telegram.md, \"Renewing\"")

        dialogs = [d async for d in client.iter_dialogs() if is_private(d)]
        for d in dialogs:
            raw.send("chats", str(d.id), chat_record(d))

        # Chats with something new first, the backlog of unread history
        # after, so one long first import never holds up today's messages.
        def pending(d):
            return d.message is not None and d.message.id > state.get(str(d.id), 0)

        dialogs.sort(key=lambda d: (str(d.id) not in state, not pending(d)))
        for d in dialogs:
            if time.monotonic() - started > BUDGET.total_seconds():
                print("budget spent; the next run carries on")
                break
            key = str(d.id)
            last = state.get(key, 0)
            if pending(d):
                n = 0
                async for m in client.iter_messages(d.entity, reverse=True, min_id=last):
                    raw.send("messages", f"{d.id}/{m.id}", message_record(d.id, m))
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
                        raw.send("messages", f"{d.id}/{m.id}", message_record(d.id, m))


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

        state = json.loads(Variable.get(STATE, default="{}"))

        def save(s):
            Variable.set(STATE, json.dumps(s, sort_keys=True))

        raw = _Raw(get_current_context()["run_id"])
        asyncio.run(_sync(raw, state, save))
        raw.flush()

    sync()


ingest_telegram()
