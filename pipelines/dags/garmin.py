"""The Garmin Connect account's data, into Kafka topic raw.garmin.

Two DAGs, because Garmin gives it out two ways:

  ingest_garmin         Garmin Connect's own API, as the phone app calls it,
                        through python-garminconnect: each day's summary,
                        sleep, stress, Body Battery, heart rate, HRV,
                        respiration, SpO2, training readiness and status,
                        weigh-ins, hydration..., the activities, and a
                        snapshot of the devices, records, badges, goals and
                        workouts.
                        Every 6 hours: the last DAYS_AGAIN days again (a
                        watch syncs late), and the history, newest first, in
                        BUDGET-long portions until it runs out.
  ingest_garmin_export  Garmin's "Export Your Data" archive, by hand: every
                        JSON file in it, and the activities' own FIT files -
                        each second of each recording. Packed on the machine
                        that holds the zip by pipelines/tools/garmin_pack.py.

Every record goes out in ingest.py's envelope, masked first like every other
source. A day's record has the day as its id, so a day sent again replaces
itself in ods.

Garmin has no API for its users' own data, so the login is the phone app's:
pipelines/tools/garmin_login.py signs in once on the workstation, MFA
included, and puts the tokens - never the password - into the
airflow-sources Secret as GARMIN_TOKENS. Garmin may hand out a new refresh
token on each renewal, so the newest tokens live in Variable garmin_tokens
(encrypted with Airflow's Fernet key), next to a hash of the Secret's tokens
they came from: a new login in the Secret wins over the Variable. Garmin
changes this login now and then; the library follows, and the image's pin
moves with it. Setup and renewal: pipelines/garmin.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import pendulum
from airflow.sdk import Variable, dag, task

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sensitive import mask_record  # noqa: E402

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.garmin"
SETUP = "pipelines/garmin.md"
START = pendulum.datetime(2026, 11, 1, tz="UTC")

TOKENS = "garmin_tokens"
BACKFILL = "garmin_backfill"
# Days read again on every run: a watch that was not near the phone syncs
# its days later, and Garmin fills in sleep and HRV after the night.
DAYS_AGAIN = 4
# One run reads the history for at most this long, then saves its place.
BUDGET = 40 * 60
# Between two calls. Garmin limits clients that look like robots, and the
# whole history at this pace is a few days of runs, which is fine.
PAUSE = 0.5
# The history ends where this many days in a row had nothing.
EMPTY_DAYS = 180
OLDEST = date(2006, 1, 1)

# What is read for each day, after the day's summary. The endpoint's name
# is the record's; the id is the day.
DAILY = {
    "daily/sleep": lambda g, d: g.get_sleep_data(d),
    "daily/stress": lambda g, d: g.get_all_day_stress(d),
    "daily/body_battery": lambda g, d: g.get_body_battery(d),
    "daily/body_battery_events": lambda g, d: g.get_body_battery_events(d),
    "daily/heart_rates": lambda g, d: g.get_heart_rates(d),
    "daily/hrv": lambda g, d: g.get_hrv_data(d),
    "daily/respiration": lambda g, d: g.get_respiration_data(d),
    "daily/spo2": lambda g, d: g.get_spo2_data(d),
    "daily/steps": lambda g, d: g.get_steps_data(d),
    "daily/floors": lambda g, d: g.get_floors(d),
    "daily/intensity_minutes": lambda g, d: g.get_intensity_minutes_data(d),
    "daily/hydration": lambda g, d: g.get_hydration_data(d),
    "daily/weigh_ins": lambda g, d: g.get_daily_weigh_ins(d),
    "daily/blood_pressure": lambda g, d: g.get_blood_pressure_day(d),
    "daily/training_readiness": lambda g, d: g.get_training_readiness(d),
    "daily/training_status": lambda g, d: g.get_training_status(d),
    "daily/max_metrics": lambda g, d: g.get_max_metrics(d),
    "daily/all_day_events": lambda g, d: g.get_all_day_events(d),
}

# Sent whole every run, as snapshots: what there is now.
SNAPSHOTS = {
    "devices": lambda g: g.get_devices(),
    "personal_records": lambda g: g.get_personal_record(),
    "badges": lambda g: g.get_earned_badges(),
    "goals": lambda g: g.get_user_goals(),
    "workouts": lambda g: g.get_workouts(),
    "heart_rate_zones": lambda g: g.get_heart_rate_zones(),
    "lifetime_totals": lambda g: g.get_lifetime_totals(),
}


class _Raw:
    """Envelopes to raw.garmin, the way ingest.py writes them."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self._producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
            # A day's stress or heart rate, every two minutes, stays well
            # under this.
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
        record, flags = mask_record(record)
        value = json.dumps({
            "source": "garmin",
            "endpoint": endpoint,
            "extracted_at": self._extracted_at,
            "run_id": self._run_id,
            "id": rid,
            "record": record,
            **extra,
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


def _status(e: Exception) -> int | None:
    return getattr(getattr(e, "response", None), "status_code", None)


class _Garmin:
    """The account, logged in with the newest tokens; they are saved back
    whenever the library may have renewed them."""

    def __init__(self):
        from garminconnect import Garmin, GarminConnectAuthenticationError

        seed = os.environ.get("GARMIN_TOKENS", "")
        if not seed:
            raise RuntimeError(f"GARMIN_TOKENS not set - see {SETUP}")
        self._seed = hashlib.sha256(seed.encode()).hexdigest()
        saved = Variable.get(TOKENS, default=None, deserialize_json=True) or {}
        tokens = saved["tokens"] if saved.get("seed") == self._seed else seed
        self.api = Garmin()
        try:
            self.api.login(tokens)
        except GarminConnectAuthenticationError as e:
            raise RuntimeError(
                f"Garmin no longer accepts the saved login ({e}). Sign in again - "
                f"{SETUP}, 'Renewing'"
            ) from e
        self.save()

    def save(self) -> None:
        Variable.set(TOKENS, {"seed": self._seed, "tokens": self.api.client.dumps()},
                     serialize_json=True)

    def call(self, fn, *args):
        """fn's answer, or None for nothing there. Garmin answers 404, or a
        400 for a kind of data this account or its devices never had."""
        from garminconnect import GarminConnectConnectionError

        time.sleep(PAUSE)
        try:
            return fn(self.api, *args)
        except GarminConnectConnectionError as e:
            if _status(e) in (400, 404):
                return None
            raise


def _empty(summary) -> bool:
    """A day with nothing recorded: before the first watch, or one left at home."""
    if not isinstance(summary, dict):
        return True
    return not any(summary.get(k) for k in ("totalSteps", "restingHeartRate", "totalKilocalories",
                                            "sleepingSeconds", "averageStressLevel"))


def _day(g: _Garmin, raw: _Raw, d: date) -> bool:
    """Every record of one day; False if the day was empty."""
    day = d.isoformat()
    summary = g.call(lambda api, x: api.get_user_summary(x), day)
    if _empty(summary):
        return False
    raw.send("daily/summary", day, summary)
    for endpoint, fn in DAILY.items():
        answer = g.call(fn, day)
        if answer:
            raw.send(endpoint, day, answer)
    return True


def _activities(g: _Garmin, raw: _Raw, start: date, end: date) -> None:
    for a in g.call(lambda api, s, e: api.get_activities_by_date(s, e),
                    start.isoformat(), end.isoformat()) or []:
        raw.send("activities", str(a["activityId"]), a)


@dag(
    dag_id="ingest_garmin",
    description="Garmin Connect into raw.garmin: recent days, the history in portions, a snapshot",
    schedule="35 */6 * * *",
    start_date=START,
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "garmin"],
    # A rate limit is not over in two minutes.
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=30)},
)
def ingest_garmin():
    # One task: the tokens are saved after each run, and two tasks renewing
    # them at once would each save a different one.
    @task(execution_timeout=timedelta(minutes=55))
    def sync() -> None:
        from airflow.sdk import get_current_context

        from garminconnect import GarminConnectTooManyRequestsError

        g, raw = _Garmin(), _Raw(get_current_context()["run_id"])
        today = datetime.now(timezone.utc).date()
        state = Variable.get(BACKFILL, default=None, deserialize_json=True) or {
            "next": (today - timedelta(days=DAYS_AGAIN)).isoformat(), "empty": 0,
        }
        try:
            # The recent days, every run.
            for i in range(DAYS_AGAIN + 1):
                _day(g, raw, today - timedelta(days=i))
            _activities(g, raw, today - timedelta(days=DAYS_AGAIN + 3), today)
            for endpoint, fn in SNAPSHOTS.items():
                answer = g.call(fn)
                items = answer if isinstance(answer, list) else [answer] if answer else []
                for i, item in enumerate(items):
                    rid = str(item.get("id") or item.get("deviceId") or item.get("badgeId")
                              or item.get("workoutId") or item.get("typeId") or i) \
                        if isinstance(item, dict) else str(i)
                    raw.send(f"snapshot/{endpoint}", rid, item)
            raw.flush()

            # The history, newest first, a month of activities at a time.
            deadline = time.monotonic() + BUDGET
            while not state.get("done") and time.monotonic() < deadline:
                d = date.fromisoformat(state["next"])
                if d < OLDEST or state["empty"] >= EMPTY_DAYS:
                    state["done"] = True
                    print(f"history: read back to {d}; recent days only from now on")
                    break
                state["empty"] = 0 if _day(g, raw, d) else state["empty"] + 1
                if d.day == 1:
                    _activities(g, raw, d, (d + timedelta(days=32)).replace(day=1) - timedelta(days=1))
                state["next"] = (d - timedelta(days=1)).isoformat()
                # Each week's place is saved once Kafka has the week.
                if d.weekday() == 0:
                    raw.flush()
                    Variable.set(BACKFILL, state, serialize_json=True)
            raw.flush()
            Variable.set(BACKFILL, state, serialize_json=True)
            if not state.get("done"):
                print(f"history: at {state['next']}, the next run carries on")
        except GarminConnectTooManyRequestsError:
            # What is in Kafka stays; the place saved last week-boundary
            # makes the next run read at most a week again.
            raw.flush()
            raise RuntimeError("Garmin says too many requests - the next run carries on")
        finally:
            g.save()
            for endpoint, n in sorted(raw.counts.items()):
                print(f"garmin/{endpoint}: {n} records to {TOPIC}")

    sync()


ingest_garmin()


@dag(
    dag_id="ingest_garmin_export",
    description="A Garmin 'Export Your Data' archive, packed on the workstation, into raw.garmin",
    schedule=None,
    start_date=START,
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "garmin"],
    # Where `kubectl cp` put the file; another path can be given when
    # triggering.
    params={"path": "/tmp/garmin-export.jsonl.gz"},
    # A retry sends every record again; the ods models keep each once.
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=5)},
)
def ingest_garmin_export():
    @task(execution_timeout=timedelta(hours=3))
    def load() -> None:
        """Every line of the packed file to raw.garmin, then the file
        deleted, so the unmasked copy does not outlive the load. A failed
        run leaves it for the retry."""
        import gzip

        from airflow.sdk import get_current_context

        context = get_current_context()
        path = context["params"]["path"]
        raw = _Raw(context["run_id"])
        # One line at a time: the scheduler's memory is the tasks' memory.
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                raw.send(item["endpoint"], item["id"], item["record"], file=item.get("file", ""))
        raw.flush()
        os.remove(path)
        for endpoint, n in sorted(raw.counts.items()):
            print(f"garmin/{endpoint}: {n} records to {TOPIC}")
        print(f"{path} deleted")

    load()


ingest_garmin_export()
