"""The Bambu Lab account's prints, into Kafka topic raw.bambu.

Bambu Lab's cloud, as Bambu Studio and Bambu Handy call it: every print
the account's printers ran through the cloud - model, plate, printer,
start and end, finished or failed, and the filament of each AMS slot with
its colour and grams - and the printers themselves. Records go out in
ingest.py's envelope, masked first like every other source.

Every run lists the whole print history: it is a few thousand records at
most, so nothing is kept between runs. A print's record has the print's id,
so ods keeps its newest copy, and one deleted in the app stays.

Bambu has no API for its users' data, so the login is the slicer's:
pipelines/tools/bambu_login.py signs in once on the workstation - the code
Bambu emails included - and puts the token, never the password, into the
airflow-sources Secret as BAMBU_TOKEN. The token lasts about three months
and cannot be renewed (Bambu's refresh endpoint answers 401 to everyone),
so the log counts down its last two weeks, and a run after it ends fails
asking for a new login. Calls go through curl_cffi as a browser would:
Cloudflare in front of the API turns plain clients away. Setup:
pipelines/bambu.md.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone

import pendulum
from airflow.sdk import dag, task

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sensitive import mask_record  # noqa: E402

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.bambu"
API = "https://api.bambulab.com"
TIMEOUT = 60
SETUP = "pipelines/bambu.md"
# Prints per page. The history is read page by page, older each time, until
# a page brings nothing new.
PAGE = 100
PAUSE = 0.5
# The log warns this many days before the token ends.
WARN_DAYS = 14
# A printer's LAN access code: a key to the printer, not data.
DROP = {"dev_access_code"}


class _Bambu:
    def __init__(self):
        from curl_cffi import requests

        self.token = os.environ.get("BAMBU_TOKEN", "").strip()
        if not self.token:
            raise RuntimeError(f"BAMBU_TOKEN not set - see {SETUP}")
        self.session = requests.Session(impersonate="chrome")
        self.session.headers["Authorization"] = f"Bearer {self.token}"

    def days_left(self) -> float | None:
        """Days until the token ends, from the expiry inside it; None if it
        is not a JWT, which Bambu does not promise."""
        try:
            body = self.token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            return (claims["exp"] - time.time()) / 86400
        except (IndexError, KeyError, TypeError, ValueError):
            return None

    def get(self, path: str, **params) -> dict:
        """One call's JSON. Errors name the path, never the token."""
        from curl_cffi.requests.exceptions import RequestException

        time.sleep(PAUSE)
        for attempt in range(5):
            try:
                r = self.session.get(f"{API}{path}", params=params or None, timeout=TIMEOUT)
            except RequestException as e:
                if attempt == 4:
                    raise RuntimeError(f"{path}: {type(e).__name__}") from None
                time.sleep(2 ** attempt * 5)
                continue
            if r.status_code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(min(2 ** attempt * 10, 120))
                continue
            if r.status_code == 401:
                raise RuntimeError(f"{path}: Bambu no longer accepts the token (401). Sign in "
                                   f"again - {SETUP}, 'Renewing'")
            if r.status_code == 403 and "cloudflare" in r.text.lower():
                raise RuntimeError(f"{path}: Cloudflare turned the request away (403) - "
                                   f"{SETUP}, 'Things to know'")
            if not r.ok:
                raise RuntimeError(f"{path}: Bambu answered {r.status_code}")
            return r.json()
        raise RuntimeError(f"{path}: Bambu kept answering {r.status_code}")


class _Raw:
    """Envelopes to raw.bambu, the way ingest.py writes them."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self._producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
        })
        self._errors: list[str] = []
        self._run_id = run_id
        self._extracted_at = datetime.now(timezone.utc).isoformat()
        self.counts: dict[str, int] = {}

    def _delivered(self, err, _msg):
        if err is not None:
            self._errors.append(str(err))

    def send(self, endpoint: str, rid, record) -> None:
        record, flags = mask_record(record)
        value = json.dumps({
            "source": "bambu",
            "endpoint": endpoint,
            "extracted_at": self._extracted_at,
            "run_id": self._run_id,
            "id": str(rid),
            "record": record,
            **flags,
        }, ensure_ascii=False).encode()
        while True:
            try:
                self._producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                       on_delivery=self._delivered)
                break
            except BufferError:
                self._producer.poll(1)
        self._producer.poll(0)
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def flush(self) -> None:
        left = self._producer.flush(120)
        if left or self._errors:
            raise RuntimeError(f"{left} undelivered, errors: {self._errors[:3]}")
        for endpoint, n in sorted(self.counts.items()):
            print(f"bambu/{endpoint}: {n} records to {TOPIC}")


@dag(
    dag_id="ingest_bambu",
    description="The Bambu Lab account into raw.bambu: every print with its filament, and the printers",
    schedule="25 */6 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "bambu"],
    default_args={"retries": 2, "retry_delay": pendulum.duration(minutes=10)},
)
def ingest_bambu():
    @task
    def sync() -> None:
        from airflow.sdk import get_current_context

        b, raw = _Bambu(), _Raw(get_current_context()["run_id"])
        left = b.days_left()
        if left is not None and left < WARN_DAYS:
            print(f"token: ends in {left:.0f} days - sign in again ({SETUP}, 'Renewing')")

        devices = b.get("/v1/iot-service/api/user/bind").get("devices") or []
        for d in devices:
            raw.send("devices", d["dev_id"], {k: v for k, v in d.items() if k not in DROP})

        # Newest first. Each page asks for the prints after the oldest one
        # so far; a page with nothing new is the end - also if Bambu ever
        # stops honouring `after` and answers the same page again.
        seen: set = set()
        total = None
        after = None
        while True:
            page = b.get("/v1/user-service/my/tasks", limit=PAGE,
                         **({"after": after} if after is not None else {}))
            total = page.get("total", total)
            new = [t for t in page.get("hits") or [] if t["id"] not in seen]
            if not new:
                break
            for t in new:
                seen.add(t["id"])
                raw.send("tasks", t["id"], t)
            after = min(t["id"] for t in new)
        raw.flush()

        if total is not None and len(seen) < total:
            print(f"tasks: Bambu says {total}, {len(seen)} read - the paging stopped early")
        if not devices and not seen:
            raise RuntimeError("Bambu lists no printer and no print - is the token the right "
                               f"account's? {SETUP}")

    sync()


ingest_bambu()
