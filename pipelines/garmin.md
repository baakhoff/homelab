# Garmin

The Garmin Connect account's data, in the warehouse: `raw.garmin`, then
`ods.garmin_*`. Two Airflow DAGs in [`dags/garmin.py`](dags/garmin.py),
because Garmin gives it out two ways:

| DAG | What | How | When |
|---|---|---|---|
| `ingest_garmin` | Each day's summary, sleep, stress, Body Battery and its events, heart rate, HRV, breathing, SpO2, steps, floors, intensity minutes, hydration, weigh-ins, blood pressure, training readiness and status, VO2 max; the activities; devices, personal records, badges, goals, workouts, heart rate zones and lifetime totals | Garmin Connect's API, signed in as the phone app with [python-garminconnect](https://github.com/cyberjunky/python-garminconnect): the last 4 days again on every run, and the whole history, newest first, 40 minutes of it per run until it runs out | every 6 hours, at :35 |
| `ingest_garmin_export` | Every JSON file of Garmin's data export, and the activities' FIT files: each second of each recording | the export, packed on the workstation | by hand |

| Model | One row per |
|---|---|
| `ods.garmin_daily` | day: steps, distance, calories, floors, intensity minutes, heart rate, stress, Body Battery, SpO2, breathing, the night's sleep and score, HRV, training readiness |
| `ods.garmin_sleep` | night: start and end, deep, light, REM and awake time, score, breathing, HRV, stress |
| `ods.garmin_activities` | activity: type, start, time, distance, calories, heart rate, speed, ascent, steps, training effect, VO2 max, where it started |
| `ods.garmin_weigh_ins` | weigh-in: weight, BMI, body fat and water, bone and muscle mass, in kilograms |
| `ods.garmin_fit_sessions` | session of an activity's FIT file, from the export, with the Garmin Connect activity it is |
| `ods.garmin_fit_records` | second, or few, of an activity's recording: time, position, heart rate, speed, cadence, power, altitude, temperature |
| `ods.garmin_records` | every other record as it came: the minute-by-minute stress, Body Battery, heart rate and steps, the snapshots, the export's JSON, the FIT files' laps, lengths, sets and HRV (`endpoint` says which) |

```sql
SELECT endpoint, count() FROM ods.garmin_records GROUP BY endpoint ORDER BY endpoint
```

**Not here, and why.**
- **Monitoring FIT files** (the all-day files the watch writes beside the
  activities): the same days come from the API, already summed.
- **Golf, women's health, nutrition and training plans**: not read. Each is
  one more line in `DAILY` or `SNAPSHOTS` at the top of the DAG, if wanted.
- **Activities' FIT files from the API**: the export brings them all at
  once. A new activity has its totals in `ods.garmin_activities` the same
  day, and its recording at the next export.
- **Photos, courses and the files Garmin keeps as files**: files, not rows.

## Setup

**1. Wait for the image.** Merging this change rebuilds the Airflow image
with python-garminconnect (`images/airflow/`). Once the *airflow image*
workflow has finished, restart the scheduler onto it. Delete the pod rather
than `rollout restart`, which Flux undoes:

```bash
kubectl -n airflow delete pod -l component=scheduler
```

The topic and `raw.garmin` come from the hourly schema job. Start it once
rather than wait:
`kubectl -n data create job --from=cronjob/clickhouse-schema schema-garmin`.

**2. Sign in once.** On the workstation, from the repo root, at home rather
than on a VPN - Garmin refuses logins from addresses it does not like:

```bash
uv run --with garminconnect==0.3.20 --with curl_cffi==0.16.0 \
  python3 pipelines/tools/garmin_login.py
```

It asks for the email, the password and, with two-step verification on,
the code. None of them is echoed, and the password is not kept. Login
takes a while: the library waits between steps, as a person would. It
writes Garmin's tokens into `clusters/lab/airflow/sources.sops.yaml` as
`GARMIN_TOKENS` with `sops set`.

**3. Commit, push, restart.** Commit and push the Secret. Once Flux has
applied it, restart the scheduler again, as in step 1: it reads its
environment only at start.

**4. Run it.** In the Airflow UI, unpause `ingest_garmin` and trigger it.
The first runs read the history, 40 minutes each, every 6 hours. A few
years of a watch is a few days of runs. The log ends each run with
`history: at <day>`, then `history: read back to <day>` once there is
nothing older. Trigger `warehouse` afterwards, or wait for it.

**Check:**

```sql
SELECT * FROM ods.garmin_daily ORDER BY day DESC LIMIT 14
```

## The export

The history the API does not give: the activities' FIT files. Load it once
for the history; again later only for the recordings since.

**1. Ask for it.** In the Garmin account, <https://www.garmin.com/account/>
→ *Data Management* → *Export Your Data* → *Request Data Export*. Garmin
mails a link when it is built, usually within a day or two. Download the
zip. Unpacking it is not needed.

**2. Pack.** On the workstation, from the repo root.
[fitdecode](https://github.com/polyvertex/fitdecode) reads the FIT files:

```bash
uv run --with fitdecode==0.11.0 python3 pipelines/tools/garmin_pack.py \
  ~/Downloads/<the export>.zip ~/garmin-export.jsonl.gz
```

It prints the records per kind and what it skipped, never contents. Years
of activities are millions of records and a few hundred megabytes packed.

**3. Copy into the scheduler**, where tasks run:

```bash
POD=$(kubectl -n airflow get pod -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl -n airflow cp ~/garmin-export.jsonl.gz "$POD":/tmp/garmin-export.jsonl.gz -c scheduler
```

**4. Run it.** Trigger `ingest_garmin_export`. It masks every record like
every other source (`sensitive.md`), sends it to `raw.garmin`, and deletes
the file once all of it is delivered. Then trigger `warehouse`:

```sql
SELECT sport, count(), round(sum(distance_m) / 1000) AS km
FROM ods.garmin_fit_sessions GROUP BY sport ORDER BY km DESC
```

**5. Clean up.** `rm ~/garmin-export.jsonl.gz`, and the zip unless it is
kept as the copy of record.

## Renewing

The DAG renews its tokens by itself, and saves each new pair in the
Variable `garmin_tokens`. Nothing needs doing until Garmin refuses them: a
password change, a sign-out of all devices, or a change to Garmin's login.
The run then fails with "Garmin no longer accepts the saved login". Do
setup steps 2 and 3 again. The Variable notices the new tokens in the Secret
and makes way for them.

When Garmin changes its login, python-garminconnect usually follows within
days. Move the version in `images/airflow/Dockerfile` and in the
`uv run` line above together, and sign in again.

## Things to know

- **This is the phone app's login, not an API Garmin offers.** Garmin has
  none for a person's own data. It works the way the app does, and Garmin
  could block it. The DAG asks slowly, half a second between calls, and
  stops a run at the first "too many requests". The next run carries on
  from the week it was in.
- **Reading the history again**: delete the Variable `garmin_backfill` in
  the Airflow UI. The next run starts again from today. Days already
  loaded are the same rows, newest copy.
- **Days are the watch's local days**, as Garmin keeps them, not UTC days.
  Times (`started_at`, `ended_at`, `weighed_at`, `ts`) are UTC;
  `started_at_local` is the wall clock where the activity was.
- **This is health data.** It sits in ClickHouse, readable by its `admin`
  and `dbt` users, by CloudBeaver and by the `brand` agent, which reads
  `ods`, and in the nightly encrypted backup of `data/data-clickhouse-0`.
  The tokens are a full login to the Garmin account. Signing out of all
  devices in Garmin Connect's security settings ends them, and stops new
  data.
