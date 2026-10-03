# Google

One Google account's data, in the warehouse: `raw.google`, then
`ods.google_*` and `ads.google_daily`. Three Airflow DAGs in
[`dags/google.py`](dags/google.py), because Google gives it out three ways:

| DAG | What | How | When |
|---|---|---|---|
| `ingest_google` | Calendar (every calendar, events a year ahead), Contacts and their groups, Tasks, Drive's file list, Gmail's labels | full snapshot, like the other sources | every 6 hours |
| `ingest_google_gmail` | Gmail: sender, recipients, subject, date, labels, size - **no bodies** | the whole mailbox once, then only changes | hourly |
| `ingest_google_portability` | My Activity (Search, YouTube, Maps, Play, Shopping, ads seen), Chrome history and bookmarks, YouTube subscriptions, playlists, comments and music, Maps saved places and reviews, Play installs and purchases, Discover, Alerts | Google's [Data Portability API](https://developers.google.com/data-portability): an export job per resource; activity only since the last export | daily |

| Model | One row per |
|---|---|
| `ods.google_gmail_messages` | message (deleted ones drop out; spam and trash keep their label) |
| `ods.google_gmail_labels` | label |
| `ods.google_calendars`, `ods.google_calendar_events` | calendar; occurrence of an event |
| `ods.google_contacts`, `ods.google_contact_groups` | person; group |
| `ods.google_tasks` | task, with its list |
| `ods.google_drive_files` | file or folder - what is there, never the contents |
| `ods.google_activity` | search, video watched, Maps search, ... (`resource` says which) |
| `ods.google_chrome_history` | page visit |
| `ads.google_daily` | day: mail in and out, meetings and their hours, searches, videos, pages |

Everything else the portability exports bring - subscriptions, playlists,
saved places, purchases - is in `raw.google` as it came, until a model
wants it:

```sql
SELECT JSONExtractString(payload, 'endpoint') AS endpoint, count()
FROM raw.google GROUP BY endpoint ORDER BY endpoint
```

**Not here, and why.**
- **Mail bodies**: a choice. The Gmail token's scope is `gmail.metadata`, so
  Google refuses a body even if one is asked for.
- **Drive file contents and photos/videos**: files, not rows.
- **Location Timeline**: Google moved it onto the phone and out of reach of
  any API.
- **Google Fit**: being shut down. Health data comes in through SparkyFitness
  (`clusters/lab/sparkyfitness/README.md`).
- **Chrome autofill** (saved cards and addresses): deliberately left out.

## Setup

**1. A Google Cloud project.** In a browser, signed in as the account
whose data this is: <https://console.cloud.google.com> → new project (any
name, e.g. `homelab-warehouse`).

**2. Turn on the APIs.** APIs & Services → Library, and enable each:
Gmail API, Google Calendar API, People API, Google Tasks API, Google Drive
API, Data Portability API.

**3. The consent screen.** Google Auth Platform → Branding: an app name and
your address as the support email. Audience: **External**, then **Publish
app**, so it is "In production". This matters. An app left in Testing gets
refresh tokens that die after 7 days, and every DAG starts failing a week
later. An unverified production app is fine for your own account. The
consent page warns "Google hasn't verified this app": Advanced → continue.

**4. The OAuth client.** Google Auth Platform → Clients → Create client →
**Desktop app**. Keep the dialog with the client ID and secret open, or
download its JSON. Google shows the secret only now.

**5. The ordinary APIs' consent.** On the workstation, from the repo root:

```bash
python3 pipelines/tools/google_auth.py apis
```

It asks for the client ID and secret, which are not echoed, and opens
Google's consent page. Tick every box there. It then writes
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN` into
`clusters/lab/airflow/sources.sops.yaml` with `sops set`. Nothing secret
appears on the screen. It warns if a box was left unticked, or if the app is
still in Testing.

**6. The Data Portability consent.** Same machine, same place:

```bash
python3 pipelines/tools/google_auth.py portability
```

On the consent page, choose **180 days**, not "once" or "30 days": "once"
allows a single export and the next day's run fails. This writes
`GOOGLE_PORTABILITY_REFRESH_TOKEN`. The API is for accounts in the EEA,
which this one is.

**7. Commit, push, restart.** Commit and push the Secret. Once Flux has
applied it, restart the scheduler, which reads its environment only at
start:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
```

**8. Run them.** In the Airflow UI, trigger `ingest_google_portability`
**within 24 hours of step 6**. Google wants the first export that soon
after the consent. Then trigger `ingest_google` and `ingest_google_gmail`,
and afterwards `warehouse`.

- **Gmail's first read** takes as many hourly runs as it needs. Each reads
  for 30 minutes, then saves its place. A large mailbox is a few hours.
- **The first portability export** is your whole history. Google can take
  hours, sometimes days, to build it. `export.built` waits, checking every
  10 minutes, without holding a task slot.

**Check:**

```sql
SELECT * FROM ads.google_daily ORDER BY day DESC LIMIT 14
```

## Renewing

- **The portability consent lasts 180 days.** Google's limit; nothing extends
  it. When it runs out, `ingest_google_portability` fails with "Google no
  longer accepts GOOGLE_PORTABILITY_REFRESH_TOKEN". Run step 6 again, then
  step 7, and trigger the DAG within 24 hours.
- **The APIs' token has no end date.** It stops working if it is revoked at
  <https://myaccount.google.com/connections>, if it goes unused for six
  months, or if the account's password changes: Google revokes Gmail access
  on a password change. The DAGs then fail with the same message, naming
  `GOOGLE_REFRESH_TOKEN`. Run step 5 again, then step 7.

If the portability consent page errors, ask for fewer resources at once.
Google limits how many one consent may cover, and names after the command
replace the default list:

```bash
python3 pipelines/tools/google_auth.py portability myactivity.search myactivity.youtube myactivity.maps chrome.history
```

The DAG exports whatever the consent covers. It reads the list back from
Google, so nothing else changes.

## Things to know

- **Each resource is exported once a day at most.** That is Google's limit.
  A second run on the same day skips the resources already exported.
- **Activity overlaps by three days.** Each export starts three days before
  the previous one ended, to catch activity that reached Google late. A
  record's id is a hash of the record itself, so an item exported twice is
  one row.
- **Gmail's history covers about a week.** If `ingest_google_gmail` is off
  for longer, its next run reads the whole mailbox again. Messages deleted
  during that gap stay in `ods.google_gmail_messages`: nothing told the DAG
  they went.
- **The My Activity and Chrome models assume Takeout's field names.** The
  Data Portability API documents the same ones. If a field reads empty
  after the first export, the item as it arrived is in `record` (and
  `raw.google`), and the model is the thing to fix.
- **This is the most personal data in the lab.** All of it sits in
  ClickHouse, readable by its `admin` and `dbt` users, and in the nightly
  encrypted backup of `data/data-clickhouse-0`. Removing the app at
  <https://myaccount.google.com/connections> stops new data, and leaves what
  is already copied.
