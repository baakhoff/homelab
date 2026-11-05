# Bambu Lab

The Bambu Lab account's prints, in the warehouse: `raw.bambu`, then
`ods.bambu_*`. One Airflow DAG, `ingest_bambu` ([`dags/bambu.py`](dags/bambu.py)),
every 6 hours at :25, through Bambu Lab's cloud as
[Bambu Studio](https://github.com/bambulab/BambuStudio) calls it. Bambu has
no public API for this; what is known of the private one is in
[OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI).

| Model | One row per |
|---|---|
| `ods.bambu_prints` | print: title, model and plate, printer, start, end and real duration, finished or failed, the slicer's estimated time and grams |
| `ods.bambu_print_filaments` | print and AMS slot it drew from: filament type, Bambu's filament id, colour, grams |
| `ods.bambu_printers` | printer bound to the account: name, product, nozzle, online, what it was doing at the last run |

Every run reads the whole print history: a few thousand prints at most.
A print deleted in the app stays in `ods`.

**The grams and times are the slicer's.** `weight_g` and `estimated_s` are
what the slice said the whole job would take. A failed print still shows
all of it. `duration_s`, from start to end, is the real time.

**Not here, and why.**
- **Prints that did not go through the cloud**: from the SD card, or while
  the printer was in LAN-only mode. Bambu never hears of them.
- **Live status** - temperatures, progress, the AMS's spools: the printer
  sends those over MQTT, and only while connected. Not read.
- **Timelapses and the sliced files**: files, not rows, on the printer's
  SD card. They belong with the NAS archive.
- **Projects**: Bambu's project list answers 405 to the slicer's call
  (November 2026), so it is not read. Each print names its model.
- **Cover images**: each print's record keeps the link Bambu gave, but the
  link expires.

## Setup

**1. Sign in once.** On the workstation, from the repo root.
[curl_cffi](https://github.com/lexiforest/curl_cffi) gets past the
Cloudflare in front of Bambu's API, which turns plain clients away:

```bash
uv run --with curl_cffi==0.16.0 python3 pipelines/tools/bambu_login.py
```

It asks for the email and the password, then for the code Bambu emails
when it does not know the machine, or the authenticator's code if the
account has two-step verification. None of them is echoed, and the
password is not kept. It checks the token by listing the printers, says
how many it sees, and writes the token into
`clusters/lab/airflow/sources.sops.yaml` as `BAMBU_TOKEN` with `sops set`.

**2. Commit, push, restart.** Commit and push the Secret. Once Flux has
applied it, restart the scheduler, which reads its environment only at
start. Delete the pod rather than `rollout restart`, which Flux undoes:

```bash
kubectl -n airflow delete pod -l component=scheduler
kubectl -n data create job --from=cronjob/clickhouse-schema schema-bambu
```

The second line creates the topic and `raw.bambu` now rather than at the
hourly run.

**3. Run it.** In the Airflow UI, unpause `ingest_bambu` and trigger it,
then `warehouse`. The log ends with the records per kind. If it says
`the paging stopped early`, Bambu has more prints than were read - see
*Things to know*.

```sql
SELECT toStartOfMonth(started_at) AS month, f.filament_type, round(sum(f.weight_g)) AS grams
FROM ods.bambu_print_filaments f
GROUP BY month, f.filament_type ORDER BY month DESC, grams DESC
```

## Renewing

The token lasts about three months and cannot be renewed: Bambu's refresh
endpoint answers 401 to everyone. In its last two weeks each run's log
starts with `token: ends in N days`. After that the run fails with "Bambu
no longer accepts the token". Do setup steps 1 and 2 again. A password
change or signing out of all devices ends it early in the same way.

## Things to know

- **This is the slicer's login, not an API Bambu offers.** It works the way
  Bambu Studio does, and Bambu could change or block it. Most Bambu Lab
  integrations log in the same way.
- **Cloudflare sits in front of the API.** curl_cffi presents itself as a
  browser. If Bambu tightens that, runs fail with "Cloudflare turned the
  request away", and a newer curl_cffi, in `images/airflow/Dockerfile` and
  the `uv run` line above together, is the first thing to try.
- **The print list is read page by page**, 100 at a time, older each time,
  until a page brings nothing new. If Bambu ever stops honouring the page
  marker, the run reads the newest 100 only and says so in its log; the
  older prints already in `ods` stay.
- **The printer's LAN access code** comes with the printer list. It is a
  key to the printer on the home network, so the DAG drops it before the
  record leaves. The printer's serial number stays, as `device_id`.
- **The token is a full login to the Bambu Lab account**, MakerWorld
  included. Signing out of all devices in the account's security settings
  ends it, and stops new data. The prints sit in ClickHouse, readable by
  its `admin` and `dbt` users, by CloudBeaver and by the `brand` agent, and
  in the nightly encrypted backup of `data/data-clickhouse-0`.
