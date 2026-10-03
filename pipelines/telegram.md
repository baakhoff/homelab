# Telegram

One Telegram account's private chats, in the warehouse: `raw.telegram`,
then `ods.telegram_chats`, `ods.telegram_messages` and
`ads.telegram_daily`. The DAG is `ingest_telegram`
([`dags/telegram.py`](dags/telegram.py)), hourly at :20.

| Model | One row per |
|---|---|
| `ods.telegram_chats` | private chat: the person's name and username, whether they are a contact, unread count, last message; the account's own Saved Messages is one too |
| `ods.telegram_messages` | message, in its newest version: when, which way, the text, a reply or forward, and media and calls as metadata |
| `ads.telegram_daily` | day: messages sent and received, people written with, voice messages, calls, missed calls, call minutes |

## What is in it, and what is not

- **Private chats only**, one-to-one with people. No groups, no channels,
  no chats with bots.
- **Text in full.** Photos, voice messages, videos and files as metadata:
  the kind, size, duration and file name, never the file. A shared
  location keeps its coordinates. Calls are messages too: `action =
  'PhoneCall'`, with their length and how they ended.
- **Secret chats are not here.** They exist only on the phones; no login
  can read them.
- **Deletions are not seen.** A message deleted in Telegram stays in the
  warehouse: Telegram reports deletions only to a client that is connected
  at that moment.
- **Edits are caught for three days.** Each run reads the last three days
  of every active chat again; an edit to an older message is missed.

## Setup

**1. An API app.** In a browser: <https://my.telegram.org>, log in with
the account's phone number (the code arrives in Telegram), then **API
development tools**. Create an app: any title and short name, for example
`homelab warehouse` and `homelabwh`, platform *Desktop*, URL empty. Keep
the page with **api_id** and **api_hash** open. If the form only answers
"ERROR", turn off any VPN or ad blocker and try again; that is a known
quirk of the page.

**2. The login.** On the workstation, from the repo root. Telethon goes
into a throwaway virtualenv, not the system Python:

```bash
python3 -m venv /tmp/tg && /tmp/tg/bin/pip install telethon==1.45.0
/tmp/tg/bin/python pipelines/tools/telegram_login.py
```

It asks for the api_id and api_hash (not echoed), the phone number, the
code Telegram sends to your other devices, and the two-step verification
password if there is one. It then writes `TELEGRAM_API_ID`,
`TELEGRAM_API_HASH` and `TELEGRAM_SESSION` into
`clusters/lab/airflow/sources.sops.yaml` with `sops set` and prints only
the name it logged in as. Telegram shows a "new login" message in the app,
from a device called *homelab warehouse*: that is this.

Afterwards the virtualenv can go: `rm -rf /tmp/tg`.

**3. Commit and push** the Secret.

**4. The image, then the restart.** The DAG needs Telethon, which is in
the Airflow image from this change on. Once it is merged, the *airflow
image* workflow on GitHub builds the image; wait for it to go green under
the Actions tab. Then restart the scheduler, which pulls the new image and
reads the new Secret:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
kubectl -n airflow rollout status deployment/airflow-scheduler --timeout=5m
```

**5. Run it.** In the Airflow UI, trigger `ingest_telegram`. The first
runs work through the whole history 40 minutes at a time: chats with new
messages first, then the backlog, oldest message first in each chat. A
large account takes a few hourly runs. Then trigger `warehouse`, and:

```sql
SELECT * FROM ads.telegram_daily ORDER BY day DESC LIMIT 14
```

## Renewing

The session has no end date. It stops working when it is ended in
Telegram (Settings -> Devices -> *homelab warehouse*), when the account
logs out of all other sessions, or when Telegram ends it after long
disuse - which an hourly DAG never is. The DAG then fails with "Telegram
no longer accepts TELEGRAM_SESSION". Run step 2 again, then 3 and the
restart from step 4.

## Things to know

- **The session is a full login to the account.** Whoever holds it can
  read and send messages as you. It lives only in the encrypted Secret,
  and the DAG only reads. Ending it under Settings -> Devices cuts the DAG
  off at once.
- **Other people's words are in here.** Everyone who writes to the account
  privately has their messages copied, in full. They sit in ClickHouse,
  readable by its `admin` and `dbt` users, and in the nightly encrypted
  backup of `data/data-clickhouse-0`.
- **Telegram sets the pace.** When it says "wait", the client waits, up to
  five minutes at a time, and the run carries on. Reading one's own history
  this way is what every third-party Telegram app does.
- **Starting over** is clearing the Airflow Variable `telegram_sync`
  (Admin -> Variables): the next runs read every chat from the start
  again, and the ods model keeps each message once.
