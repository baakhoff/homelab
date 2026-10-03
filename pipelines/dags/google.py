"""Copy the Google account's data into Kafka topic raw.google.

Three DAGs, because Google's data comes out in three different ways:

  ingest_google              Calendar, Contacts, Tasks, Drive and the Gmail
                             labels: a full snapshot every 6 hours, like
                             ingest.py's sources.
  ingest_google_gmail        Gmail messages, metadata only: the whole mailbox
                             once, resumably, then only what changed (Gmail's
                             history), hourly. A full snapshot of every
                             message every run would be a request per message.
  ingest_google_portability  Everything Google has no ordinary API for - My
                             Activity (Search, YouTube, Maps, Play, Shopping,
                             ads), Chrome history, YouTube subscriptions and
                             playlists, saved places... - through the Data
                             Portability API: an export job per resource,
                             once a day, downloaded when Google has built it.

Every record goes out in ingest.py's envelope, with two optional fields:

    {"source": "google", "endpoint": "calendar/events", "extracted_at": "...",
     "run_id": "...", "id": "...", "record": {...Google's JSON...},
     "deleted": true,               - Gmail: the message is gone
     "file": "...", "section": ...} - Portability: where in the archive

Two refresh tokens, both from pipelines/tools/google_auth.py and both in the
airflow-sources Secret: GOOGLE_REFRESH_TOKEN for the ordinary APIs, read-only
scopes, and GOOGLE_PORTABILITY_REFRESH_TOKEN for the Data Portability API -
Google refuses one consent that mixes the two kinds. The Gmail scope is
gmail.metadata: with it, Google will not hand over a message body at all.
Setup and renewal: pipelines/google.md.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import pendulum
import requests
from airflow.sdk import PokeReturnValue, Variable, dag, task, task_group
from airflow.sdk.exceptions import AirflowSkipException

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.google"
TIMEOUT = 60
TOKEN_URL = "https://oauth2.googleapis.com/token"
SETUP = "pipelines/google.md"

DEFAULT_ARGS = {"retries": 2, "retry_delay": pendulum.duration(minutes=2)}
START = pendulum.datetime(2026, 10, 1, tz="UTC")


class _Google:
    """Requests as the account behind one refresh token.

    The access token is renewed before it runs out (an hour), so a long
    Gmail backfill outlives any one of them. Rate limits and Google's
    passing 5xx are retried with backoff; anything else is the caller's.
    Safe to share between threads: one requests session per thread.
    """

    RETRY = frozenset({429, 500, 502, 503, 504})

    def __init__(self, token_env: str):
        self._env = token_env
        self._lock = threading.Lock()
        self._local = threading.local()
        self._token = ""
        self._expires = 0.0
        self.scopes: set[str] = set()

    def _refresh(self) -> None:
        names = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", self._env)
        values = {n: os.environ.get(n) for n in names}
        missing = [n for n, v in values.items() if not v]
        if missing:
            raise RuntimeError(f"{', '.join(missing)} not set - see {SETUP}")
        r = requests.post(TOKEN_URL, timeout=TIMEOUT, data={
            "client_id": values["GOOGLE_CLIENT_ID"],
            "client_secret": values["GOOGLE_CLIENT_SECRET"],
            "refresh_token": values[self._env],
            "grant_type": "refresh_token",
        })
        if r.status_code == 400 and r.json().get("error") == "invalid_grant":
            raise RuntimeError(
                f"Google no longer accepts {self._env}: the consent expired or was "
                f"revoked. Give it again - {SETUP}, 'Renewing'"
            )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._expires = time.monotonic() + int(body.get("expires_in", 3600))
        self.scopes = set(body.get("scope", "").split())

    def authorise(self) -> None:
        with self._lock:
            if time.monotonic() > self._expires - 300:
                self._refresh()

    def request(self, method: str, url: str, retry=RETRY, **kwargs) -> requests.Response:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = requests.Session()
        for attempt in range(7):
            self.authorise()
            r = session.request(method, url, timeout=TIMEOUT,
                                headers={"Authorization": f"Bearer {self._token}"}, **kwargs)
            if r.status_code == 401 and attempt == 0:
                with self._lock:
                    self._expires = 0.0
                continue
            # Gmail says "slow down" as a 403 with a rate-limit reason.
            limited = r.status_code == 403 and "ateLimitExceeded" in r.text
            if (r.status_code in retry or limited) and attempt < 6:
                time.sleep(min(2 ** attempt, 60))
                continue
            return r
        return r

    def get(self, url: str, **params) -> dict:
        r = self.request("GET", url, params=params)
        r.raise_for_status()
        return r.json()

    def pages(self, url: str, key: str, **params):
        """Every item of a Google list endpoint: `key` holds a page, nextPageToken the next.

        An empty list is the key left out, not an empty one, so a missing
        key is no records rather than an error.
        """
        while True:
            body = self.get(url, **params)
            yield from body.get(key, [])
            if not body.get("nextPageToken"):
                return
            params["pageToken"] = body["nextPageToken"]


class _Raw:
    """Envelopes to raw.google, the way ingest.py writes them."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self._producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
            "message.max.bytes": 8_000_000,
        })
        self._errors: list[str] = []
        self._run_id = run_id
        self._extracted_at = datetime.now(timezone.utc).isoformat()
        self.counts: dict[str, int] = {}

    def _delivered(self, err, _msg):
        if err is not None:
            self._errors.append(str(err))

    def send(self, endpoint: str, rid: str, record, **extra) -> None:
        if not rid:
            raise RuntimeError(f"{endpoint}: a record without an id - the ods layer would drop it")
        envelope = {
            "source": "google",
            "endpoint": endpoint,
            "extracted_at": self._extracted_at,
            "run_id": self._run_id,
            "id": rid,
            "record": record,
            **extra,
        }
        value = json.dumps(envelope, ensure_ascii=False).encode()
        while True:
            try:
                self._producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                       on_delivery=self._delivered)
                break
            except BufferError:
                # A big archive outruns the local queue: wait for Kafka.
                self._producer.poll(1)
        self._producer.poll(0)
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def flush(self) -> None:
        left = self._producer.flush(120)
        if left or self._errors:
            raise RuntimeError(f"{left} undelivered, errors: {self._errors[:3]}")
        for endpoint, n in sorted(self.counts.items()):
            print(f"google/{endpoint}: {n} records to {TOPIC}")


def _run_id() -> str:
    from airflow.sdk import get_current_context

    return get_current_context()["run_id"]


# --- ingest_google: full snapshots ------------------------------------------

API_TOKEN = "GOOGLE_REFRESH_TOKEN"
CALENDAR = "https://www.googleapis.com/calendar/v3"
PEOPLE = "https://people.googleapis.com/v1"
TASKS = "https://tasks.googleapis.com/tasks/v1"
DRIVE = "https://www.googleapis.com/drive/v3"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"

PERSON_FIELDS = ",".join([
    "names", "nicknames", "emailAddresses", "phoneNumbers", "addresses",
    "organizations", "birthdays", "events", "relations", "urls",
    "biographies", "memberships", "metadata",
])
DRIVE_FIELDS = (
    "nextPageToken,files(id,name,mimeType,parents,createdTime,modifiedTime,"
    "viewedByMeTime,size,quotaBytesUsed,starred,trashed,shared,ownedByMe,"
    "fileExtension,owners(displayName),lastModifyingUser(displayName))"
)
# Recurring events are expanded into their occurrences, so an hour in the
# calendar is an hour in the warehouse. An endless series stops a year out.
CALENDAR_AHEAD = timedelta(days=366)


@dag(
    dag_id="ingest_google",
    description="Snapshot Google Calendar, Contacts, Tasks, Drive and Gmail labels into raw.google",
    schedule="40 */6 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "google"],
    default_args=DEFAULT_ARGS,
)
def ingest_google():
    @task
    def calendar() -> None:
        g, raw = _Google(API_TOKEN), _Raw(_run_id())
        until = (datetime.now(timezone.utc) + CALENDAR_AHEAD).strftime("%Y-%m-%dT%H:%M:%SZ")
        for cal in g.pages(f"{CALENDAR}/users/me/calendarList", "items",
                           maxResults=250, showHidden="true"):
            raw.send("calendar/calendars", cal["id"], cal)
            # The calendar's id is part of the event's: one event can be on
            # several calendars, under the same event id.
            events = f"{CALENDAR}/calendars/{quote(cal['id'], safe='')}/events"
            for ev in g.pages(events, "items", maxResults=2500,
                              singleEvents="true", timeMax=until):
                raw.send("calendar/events", f"{cal['id']}/{ev['id']}", ev)
        raw.flush()

    @task
    def contacts() -> None:
        g, raw = _Google(API_TOKEN), _Raw(_run_id())
        for person in g.pages(f"{PEOPLE}/people/me/connections", "connections",
                              pageSize=1000, personFields=PERSON_FIELDS):
            raw.send("contacts/people", person["resourceName"], person)
        for group in g.pages(f"{PEOPLE}/contactGroups", "contactGroups", pageSize=1000):
            raw.send("contacts/groups", group["resourceName"], group)
        raw.flush()

    @task
    def tasks() -> None:
        g, raw = _Google(API_TOKEN), _Raw(_run_id())
        for tl in g.pages(f"{TASKS}/users/@me/lists", "items", maxResults=100):
            raw.send("tasks/lists", tl["id"], tl)
            for t in g.pages(f"{TASKS}/lists/{tl['id']}/tasks", "items", maxResults=100,
                             showCompleted="true", showHidden="true"):
                raw.send("tasks/tasks", f"{tl['id']}/{t['id']}", t)
        raw.flush()

    @task
    def drive() -> None:
        """What is in Drive, never the files themselves."""
        g, raw = _Google(API_TOKEN), _Raw(_run_id())
        for f in g.pages(f"{DRIVE}/files", "files", pageSize=1000, fields=DRIVE_FIELDS):
            raw.send("drive/files", f["id"], f)
        raw.flush()

    @task
    def gmail_labels() -> None:
        g, raw = _Google(API_TOKEN), _Raw(_run_id())
        for label in g.get(f"{GMAIL}/labels").get("labels", []):
            raw.send("gmail/labels", label["id"], label)
        raw.flush()

    calendar()
    contacts()
    tasks()
    drive()
    gmail_labels()


ingest_google()


# --- ingest_google_gmail: the mailbox, then its changes ----------------------

# Where the sync is, between runs: {"history_id": "..."} once the mailbox
# has been read whole, {"backfill": {...}} while it is being read.
GMAIL_STATE = "google_gmail_sync"
# One run reads for at most this long, then saves its place: the first
# read of a large mailbox spans several runs instead of holding one of the
# scheduler's three task slots for hours.
GMAIL_BUDGET = 30 * 60
GMAIL_THREADS = 4
GMAIL_HEADERS = ["From", "To", "Cc", "Subject", "Date", "Message-ID", "In-Reply-To", "List-Id"]
# No `snippet`: that is the start of the body.
GMAIL_FIELDS = "id,threadId,labelIds,historyId,internalDate,sizeEstimate,payload/headers"


def _gmail_fetch(g: _Google, ids: list[str]):
    """(id, metadata) per message, or (id, None) for one deleted meanwhile."""
    def one(mid: str):
        r = g.request("GET", f"{GMAIL}/messages/{mid}", params={
            "format": "metadata", "metadataHeaders": GMAIL_HEADERS, "fields": GMAIL_FIELDS,
        })
        if r.status_code == 404:
            return mid, None
        r.raise_for_status()
        return mid, r.json()

    with ThreadPoolExecutor(GMAIL_THREADS) as pool:
        yield from pool.map(one, ids)


def _gmail_send(raw: _Raw, fetched) -> None:
    for mid, msg in fetched:
        if msg is None:
            raw.send("gmail/messages", mid, {"id": mid}, deleted=True)
        else:
            raw.send("gmail/messages", mid, msg)


@dag(
    dag_id="ingest_google_gmail",
    description="Gmail message metadata into raw.google: the mailbox once, then its changes",
    schedule="5 * * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "google"],
    default_args=DEFAULT_ARGS,
)
def ingest_google_gmail():
    @task
    def messages() -> None:
        g, raw = _Google(API_TOKEN), _Raw(_run_id())
        deadline = time.monotonic() + GMAIL_BUDGET
        state = Variable.get(GMAIL_STATE, default=None, deserialize_json=True) or {}

        if "history_id" not in state:
            # The whole mailbox, a page of 500 at a time, the place saved
            # after each page. The history id is taken first, so whatever
            # changes while the pages are read is picked up after.
            bf = state.get("backfill") or {
                "history_id": g.get(f"{GMAIL}/profile")["historyId"],
                "page_token": None,
            }
            while True:
                params = {"maxResults": 500, "includeSpamTrash": "true"}
                if bf["page_token"]:
                    params["pageToken"] = bf["page_token"]
                page = g.get(f"{GMAIL}/messages", **params)
                _gmail_send(raw, _gmail_fetch(g, [m["id"] for m in page.get("messages", [])]))
                raw.flush()
                bf["page_token"] = page.get("nextPageToken")
                if not bf["page_token"]:
                    state = {"history_id": bf["history_id"]}
                    Variable.set(GMAIL_STATE, state, serialize_json=True)
                    print("gmail: the whole mailbox is read; changes only from now on")
                    break
                Variable.set(GMAIL_STATE, {"backfill": bf}, serialize_json=True)
                if time.monotonic() > deadline:
                    print("gmail: out of time for this run, the next one carries on")
                    return

        # What changed since the saved history id.
        changed: set[str] = set()
        deleted: set[str] = set()
        latest = state["history_id"]
        params = {"startHistoryId": state["history_id"], "maxResults": 500}
        while True:
            r = g.request("GET", f"{GMAIL}/history", params=params)
            if r.status_code == 404:
                # Gmail keeps about a week of history. Older than that, the
                # only way back is reading the mailbox again - deletions in
                # the gap are not seen (pipelines/google.md).
                Variable.set(GMAIL_STATE, {}, serialize_json=True)
                raise RuntimeError("gmail: history expired - the next run reads the mailbox again")
            r.raise_for_status()
            body = r.json()
            for h in body.get("history", []):
                for kind in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                    changed.update(x["message"]["id"] for x in h.get(kind, []))
                deleted.update(x["message"]["id"] for x in h.get("messagesDeleted", []))
            latest = body.get("historyId", latest)
            if not body.get("nextPageToken"):
                break
            params["pageToken"] = body["nextPageToken"]

        _gmail_send(raw, ((mid, None) for mid in sorted(deleted)))
        _gmail_send(raw, _gmail_fetch(g, sorted(changed - deleted)))
        raw.flush()
        Variable.set(GMAIL_STATE, {"history_id": latest}, serialize_json=True)
        print(f"gmail: {len(changed - deleted)} changed, {len(deleted)} deleted")

    messages()


ingest_google_gmail()


# --- ingest_google_portability: the Data Portability API ---------------------

PORTABILITY_TOKEN = "GOOGLE_PORTABILITY_REFRESH_TOKEN"
PORTABILITY = "https://dataportability.googleapis.com/v1"
SCOPE_PREFIX = "https://www.googleapis.com/auth/dataportability."
# The resources Google can export by time range. These are asked only for
# what is new since their last export, minus an overlap for activity that
# reaches Google late (a phone that was offline); a record exported twice
# has the same id and counts once. Every other resource is exported whole
# each time - they are small: subscriptions, playlists, saved places.
TIME_FILTERED = frozenset({
    "myactivity.youtube", "myactivity.maps", "myactivity.search", "myactivity.myadcenter",
    "myactivity.shopping", "myactivity.play", "chrome.history",
})
OVERLAP = timedelta(days=3)
# Anything that cannot be part of a JSON number.
NUMBER_END = re.compile(r"[^0-9eE.+-]")


def _since_key(resource: str) -> str:
    # One Variable per resource: the mapped loads finish at the same time,
    # and one shared dict would lose all but one of their updates.
    return f"google_portability_since_{resource}"


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _JsonStream:
    """A JSON file read a megabyte at a time, its top-level arrays one item at a time.

    The first export of a resource is its whole history - years of YouTube
    or Chrome in one file - and json.load of that inside the scheduler pod,
    where tasks share 2.5Gi, is how it would be killed.
    """

    def __init__(self, fh):
        self._reader = io.TextIOWrapper(fh, encoding="utf-8-sig")
        self._decoder = json.JSONDecoder()
        self._buf = ""
        self._pos = 0
        self._eof = False

    def _fill(self) -> bool:
        chunk = self._reader.read(1 << 20)
        if not chunk:
            self._eof = True
            return False
        self._buf = self._buf[self._pos:] + chunk
        self._pos = 0
        return True

    def peek(self) -> str:
        while True:
            while self._pos < len(self._buf) and self._buf[self._pos] in " \t\r\n":
                self._pos += 1
            if self._pos < len(self._buf):
                return self._buf[self._pos]
            if not self._fill():
                return ""

    def take(self, ch: str) -> None:
        if self.peek() != ch:
            raise ValueError(f"expected {ch!r} in JSON, found {self.peek()!r}")
        self._pos += 1

    def value(self):
        # Cut short, anything but a number fails to decode and is read
        # further. A number cut short is still a number - 1.5 out of
        # 1.5e10 - so one is read until its end is in the buffer.
        c = self.peek()
        if c and c in "-0123456789":
            while not self._eof and not NUMBER_END.search(self._buf, self._pos):
                self._fill()
        while True:
            try:
                v, end = self._decoder.raw_decode(self._buf, self._pos)
            except json.JSONDecodeError:
                if not self._fill():
                    raise
                continue
            self._pos = end
            return v

    def array(self):
        self.take("[")
        while self.peek() != "]":
            yield self.value()
            if self.peek() == ",":
                self.take(",")
        self.take("]")

    def items(self):
        """(section, item): a top-level array's items, or a top-level object's
        arrays' items under their key - Chrome writes {"Browser History": [...]}.
        The object's other members together are one more item."""
        c = self.peek()
        if c == "[":
            for v in self.array():
                yield None, v
        elif c == "{":
            self.take("{")
            rest = {}
            while self.peek() != "}":
                key = self.value()
                self.take(":")
                if self.peek() == "[":
                    for v in self.array():
                        yield key, v
                else:
                    rest[key] = self.value()
                if self.peek() == ",":
                    self.take(",")
            self.take("}")
            if rest:
                yield None, rest
        elif c:
            yield None, self.value()


def _file_items(name: str, fh):
    """(section, item) for every record in one archive file, or nothing for
    a file that is not data (an HTML index, an image)."""
    lower = name.lower()
    if lower.endswith(".json"):
        yield from _JsonStream(fh).items()
    elif lower.endswith(".csv"):
        for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")):
            yield None, row
    else:
        print(f"skipped {name}: not JSON or CSV")


def _archive_items(fh, name: str):
    """(file, section, item) out of one downloaded archive part."""
    if zipfile.is_zipfile(fh):
        fh.seek(0)
        with zipfile.ZipFile(fh) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                with z.open(info) as member:
                    for section, item in _file_items(info.filename, member):
                        yield info.filename, section, item
    else:
        fh.seek(0)
        for section, item in _file_items(name, fh):
            yield name, section, item


def _job_state(g: _Google, job: str) -> dict:
    return g.get(f"{PORTABILITY}/archiveJobs/{job}/portabilityArchiveState")


@dag(
    dag_id="ingest_google_portability",
    description="Google's Data Portability exports into raw.google, a job per resource",
    schedule="0 3 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "google"],
    default_args=DEFAULT_ARGS,
)
def ingest_google_portability():
    @task
    def granted() -> list[str]:
        """The resources the consent covers - the scopes it was given, read
        back from Google, so the list lives in one place: the consent
        (pipelines/tools/google_auth.py)."""
        g = _Google(PORTABILITY_TOKEN)
        g.authorise()
        resources = sorted(s[len(SCOPE_PREFIX):] for s in g.scopes if s.startswith(SCOPE_PREFIX))
        if not resources:
            raise RuntimeError(f"{PORTABILITY_TOKEN} carries no Data Portability scope - {SETUP}")
        return resources

    @task(map_index_template="{{ resource_label }}")
    def start(resource: str) -> dict:
        from airflow.sdk import get_current_context

        get_current_context()["resource_label"] = resource
        g = _Google(PORTABILITY_TOKEN)
        end = datetime.now(timezone.utc).replace(microsecond=0)
        body: dict = {"resources": [resource]}
        if resource in TIME_FILTERED:
            body["endTime"] = _iso(end)
            since = Variable.get(_since_key(resource), default=None)
            if since:
                body["startTime"] = _iso(datetime.fromisoformat(since.replace("Z", "+00:00")) - OVERLAP)
        # 429 here is not "slow down": it is "this resource was exported in
        # the last 24 hours", which waiting a minute does not change.
        r = g.request("POST", f"{PORTABILITY}/portabilityArchive:initiate", json=body,
                      retry=frozenset({500, 502, 503, 504}))
        if r.status_code == 429:
            raise AirflowSkipException(f"{resource}: exported less than 24 hours ago")
        r.raise_for_status()
        answer = r.json()
        if answer.get("accessType") == "ACCESS_TYPE_ONE_TIME":
            print(f"{resource}: the consent was for one export only - "
                  f"tomorrow's run will fail until it is given for 180 days ({SETUP})")
        print(f"{resource}: export {answer['archiveJobId']} started, "
              f"{body.get('startTime', 'everything')} to {body.get('endTime', 'now')}")
        return {"resource": resource, "job": answer["archiveJobId"], "end": _iso(end)}

    # Google builds an archive in minutes or in days. Rescheduled, the
    # waiting holds no task slot between looks.
    @task.sensor(poke_interval=600, timeout=4 * 24 * 3600, mode="reschedule",
                 map_index_template="{{ resource_label }}")
    def built(job: dict) -> PokeReturnValue:
        from airflow.sdk import get_current_context

        get_current_context()["resource_label"] = job["resource"]
        state = _job_state(_Google(PORTABILITY_TOKEN), job["job"]).get("state")
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"{job['resource']}: Google's export job {job['job']} ended {state}")
        return PokeReturnValue(is_done=state == "COMPLETE", xcom_value=job)

    # One at a time: each holds a whole archive part on disk and streams
    # it, and three at once is the scheduler's every task slot.
    @task(map_index_template="{{ resource_label }}", max_active_tis_per_dag=1)
    def load(job: dict) -> None:
        from airflow.sdk import get_current_context

        context = get_current_context()
        context["resource_label"] = job["resource"]
        g, raw = _Google(PORTABILITY_TOKEN), _Raw(context["run_id"])
        endpoint = f"portability/{job['resource']}"
        # The download links are signed and good for six hours, so they
        # are read here, never passed between tasks (or kept in XCom).
        state = _job_state(g, job["job"])
        if state.get("state") != "COMPLETE":
            raise RuntimeError(f"{job['resource']}: export {job['job']} is {state.get('state')}")
        for url in state.get("urls", []):
            with tempfile.TemporaryFile() as fh:
                with requests.get(url, stream=True, timeout=TIMEOUT) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                fh.seek(0)
                part = os.path.basename(urlparse(url).path)
                for name, section, item in _archive_items(fh, part):
                    # No ids in these files: the id is the record itself, so
                    # the same activity exported twice is one row in ods.
                    digest = json.dumps([job["resource"], section, item], sort_keys=True, ensure_ascii=False)
                    rid = hashlib.sha256(digest.encode()).hexdigest()[:32]
                    raw.send(endpoint, rid, item, file=name, section=section)
        raw.flush()
        if job["resource"] in TIME_FILTERED:
            Variable.set(_since_key(job["resource"]), job["end"])

    # A task group per resource, so each resource's three steps follow
    # each other alone: one resource skipped (exported in the last 24
    # hours) or failed leaves the others running.
    @task_group
    def export(resource: str):
        load(built(start(resource)))

    export.expand(resource=granted())


ingest_google_portability()
