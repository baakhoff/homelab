# Google

One Google account's data, in the warehouse: `raw.google`, then
`ods.google_*` and `ads.google_daily`. Four Airflow DAGs in
[`dags/google.py`](dags/google.py), because Google gives it out four ways:

| DAG | What | How | When |
|---|---|---|---|
| `ingest_google` | Calendar (every calendar, events a year ahead), Contacts and their groups, Tasks, Drive's file list, Gmail's labels | full snapshot, like the other sources | every 6 hours |
| `ingest_google_gmail` | Gmail: sender, recipients, subject, date, labels, size - **no bodies** | the whole mailbox once, then only changes | hourly |
| `ingest_google_portability` | My Activity (Search, YouTube, Maps, Play, Shopping, ads seen), Chrome history and bookmarks, YouTube subscriptions, playlists, comments and music, Maps saved places and reviews, Play installs and purchases, Discover, Alerts | Google's [Data Portability API](https://developers.google.com/data-portability): an export job per resource; activity only since the last export | daily |
| `ingest_google_takeout` | Gmail **with bodies**; My Activity and Chrome history for an account the Portability API is closed to; Fit, Keep, Chat, Pay, Maps places, Saved lists and the sign-in log | a [Google Takeout](https://takeout.google.com) export, packed on the workstation | by hand |

| Model | One row per |
|---|---|
| `ods.google_gmail_messages` | message (deleted ones drop out; spam and trash keep their label) |
| `ods.google_gmail_bodies` | message from a Takeout export, with its body as plain text and its attachments' names |
| `ods.google_fit_daily`, `ods.google_fit_sessions` | day of Fit's history: steps, distance, calories, heart, weight; recorded activity |
| `ods.google_keep_notes` | Keep note, checklists included |
| `ods.google_chat_messages` | Google Chat / Hangouts message |
| `ods.google_pay_transactions` | purchase through Google, money sent or requested |
| `ods.google_maps_places` | saved, starred, reviewed, labelled (Home, Work) or followed place |
| `ods.google_saved_items` | item in a "Saved" list |
| `ods.google_takeout_records` | every other Takeout record as it came - the sign-in log's devices, commute routes, Shopping reviews |
| `ods.google_gmail_labels` | label |
| `ods.google_calendars`, `ods.google_calendar_events` | calendar; occurrence of an event |
| `ods.google_contacts`, `ods.google_contact_groups` | person; group |
| `ods.google_tasks` | task, with its list |
| `ods.google_drive_files` | file or folder - what is there, never the contents |
| `ods.google_activity` | search, video watched, Maps search, ... (`resource` says which) |
| `ods.google_chrome_history` | page visit |
| `ads.google_daily` | day: mail in and out, meetings and their hours, searches, videos, pages |
| `ads.people` | person, across Google Contacts, Telegram and mail - see below |

Everything else the portability exports bring - subscriptions, playlists,
saved places, purchases - is in `raw.google` as it came, until a model
wants it:

```sql
SELECT JSONExtractString(payload, 'endpoint') AS endpoint, count()
FROM raw.google GROUP BY endpoint ORDER BY endpoint
```

**Not here, and why.**
- **Mail bodies, live**: a choice. The Gmail token's scope is
  `gmail.metadata`, so Google refuses a body even if one is asked for - the
  other scope is "restricted" and wants an app review. Bodies come from a
  Takeout export instead, as of the day it was made.
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
`GOOGLE_PORTABILITY_REFRESH_TOKEN`.

The API serves accounts in the EEA, the UK and Switzerland only. Which
country an account is in: <https://policies.google.com/terms>, signed in -
the line "Country version:" at the top. Outside those, skip this step: the
consent page refuses, and `ingest_google_portability` stays off. My
Activity and Chrome history come from Takeout instead (below).

**7. Commit, push, restart.** Commit and push the Secret. Once Flux has
applied it, restart the scheduler, which reads its environment only at
start. Delete the pod rather than `rollout restart`, which Flux undoes,
restarting it a second time:

```bash
kubectl -n airflow delete pod -l component=scheduler
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

## A Takeout export

For the mail bodies, and for My Activity and Chrome history when the
Portability API is closed to the account. Load it again whenever a newer
copy is wanted; each item is kept once.

**1. Export.** <https://takeout.google.com>, signed in as the account.
Tick everything except what is files rather than data - **Google Photos**,
**Drive** and **YouTube** - and wherever a product offers *Multiple
formats*, choose **JSON**, not the default HTML; Mail stays mbox. What the
loader reads is in `TAKEOUT` at the top of
`pipelines/tools/google_takeout_pack.py`, plus Mail, My Activity and
Chrome; the rest of the export is left alone. Calendar, Contacts and
Tasks are skipped there on purpose: the live DAGs bring them, current.

Export once, `.zip`, the largest size Google offers. Google mails a link
when it is built, from minutes to days later. Download every part into
one folder; unpacking is not needed.

**2. Pack.** On the workstation, from the repo root - standard library
only:

```bash
python3 pipelines/tools/google_takeout_pack.py ~/Downloads/takeout ~/google-takeout.jsonl.gz
```

It prints the records per kind and any message it skipped, never contents.
Attachments, Fit's GPS tracks, Keep's images and every product not listed
stay behind.

**3. Copy into the scheduler**, where tasks run:

```bash
POD=$(kubectl -n airflow get pod -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl -n airflow cp ~/google-takeout.jsonl.gz "$POD":/tmp/google-takeout.jsonl.gz -c scheduler
```

**4. Run it.** Trigger `ingest_google_takeout`. It masks every record like
every other source (`sensitive.md`), sends it to `raw.google`, and deletes
the file once all of it is delivered. Then trigger `warehouse`.

**5. Clean up.** The packed file and the zips are the account unmasked:
`rm ~/google-takeout.jsonl.gz`, and the zips unless they are kept as the
copy of record.

### Every two months

What only Takeout has - My Activity (YouTube watched included), Chrome
history, mail bodies, Keep, Pay, the sign-in log - stays current only as
far as the last export. Takeout can repeat an export by itself: at step 1,
under *Frequency*, choose **Export every 2 months for 1 year**, and tick
just **My Activity** (JSON), **Chrome**, **Mail**, **Keep**, **Google
Pay**, **Access Log Activity**, **Maps (your places)** and **Saved** -
small, and nothing the live DAGs already bring. Renew the schedule when
the year is up; Google mails when it ends.

When the mail saying an export is ready arrives, download its zips into
`~/Downloads` and run, on the workstation, from the repo:

```bash
pipelines/tools/google_takeout_load.sh
```

It does steps 2 to 5 in one go: picks the newest export's parts, packs
them, copies the file into the scheduler, runs `ingest_google_takeout`,
waits until the file is gone (the DAG deletes it once all of it is
delivered), starts `warehouse`, deletes the packed file, and asks before
deleting the zips. Everything already loaded is skipped by id, so only
what is new since the last export adds rows. It stops with a pointer to
Airflow if the load fails or the scheduler restarts under it.

## People

`ads.people` is one row per person across the sources: every Google
contact, every Telegram user (one row for both Telegram accounts), and
every address mail was ever sent to, from Proton or Gmail. A contact takes
in the Telegram chats whose phone number it lists and the addresses it
lists, so a person who is all three is one row, with their phones,
addresses, Telegram ids and usernames, and the messages and mails
exchanged. `anchor` says what the row was built from.

Matching is exact: phone numbers compared with only digits and `+` left,
addresses lowercased. A contact saved without the country code does not
match its Telegram chat - adding the `+...` in Google Contacts does. An
address that only ever wrote in (newsletters, shops) is not a person here.

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
  ClickHouse, readable by its `admin` and `dbt` users, by CloudBeaver, and
  by the `brand` agent, which reads `ods`, `ads` and `dm` on purpose - the
  history included - and in the nightly encrypted backup of
  `data/data-clickhouse-0`. Secrets and identity numbers are masked on the
  way in, as for every source. Removing the app at
  <https://myaccount.google.com/connections> stops new data, and leaves what
  is already copied.
