# Telegram

Telegram accounts' private chats, in the warehouse: `raw.telegram`,
then `ods.telegram_chats`, `ods.telegram_messages` and
`ads.telegram_daily`. The photos, videos and files in them are in the NAS
archive, each with its row in `ods.files` ([files.md](files.md)). The DAG
is `ingest_telegram` ([`dags/telegram.py`](dags/telegram.py)), hourly at
:20: its `sync` task sends the messages, then its `media` task stores the
files.

| Model | One row per |
|---|---|
| `ods.telegram_chats` | person an account has ever had a private chat with, kept after the chat is deleted: their name, user id, username, profile link, phone number when Telegram shows it, every username and number seen for them before, whether they are a contact, unread count, last message; the account's own Saved Messages is one too |
| `ods.telegram_messages` | message, in its newest version: when, which way, the text, a reply or forward, media and calls as metadata, and `file_key`, the media's row in `ods.files` once its file is stored |
| `ads.telegram_daily` | day and account: messages sent and received, people written with, voice messages, calls, missed calls, call minutes |

## What is in it, and what is not

- **Private chats only**, one-to-one with people. No groups, no channels,
  no chats with bots.
- **Text in full.** Media as metadata: the kind, size, duration and file
  name. A shared location keeps its coordinates. Calls are messages too:
  `action = 'PhoneCall'`, with their length and how they ended.
- **The files too**, up to 1 GiB each: photos, videos, voice messages,
  video notes, audio and documents, stored in the NAS archive. Stickers,
  GIFs and the previews of links are metadata only, and so is a larger
  file.
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
large account takes a few hourly runs. The files follow, 30 minutes of
them a run, never ahead of the messages they belong to. Then trigger
`warehouse`, and:

```sql
SELECT * FROM ads.telegram_daily ORDER BY day DESC LIMIT 14
```

A message's file, once stored:

```sql
SELECT m.sent_at, f.file_name, f.mime_type, f.size_bytes, f.object
FROM ods.telegram_messages m
JOIN ods.files f ON f.file_key = m.file_key
ORDER BY m.sent_at DESC LIMIT 10
```

`object` is the file's path in the archive's read-only share
([files.md](files.md#finding-a-file-from-a-row)).

## Another account

Every account is logged in the same way and read by the same DAG, one
after another in each run. Each has a name in the warehouse - the
`account` column in every model. The first is `main`; the next is named
on the command line. On the workstation, from the repo root:

```bash
python3 -m venv /tmp/tg && /tmp/tg/bin/pip install telethon==1.45.0
/tmp/tg/bin/python pipelines/tools/telegram_login.py <name>
```

`<name>` is a short word, for example `work`. It reuses the api_id and
api_hash already in the Secret - one app serves every account - so it asks
only for the phone number, the code and the two-step password, and
writes `TELEGRAM_SESSION_<NAME>`. Then steps 3 and the restart from step
4. The first runs read that account's history while `main` carries on as
before: `main` goes first in every run, the new account gets what is left
of the 40 minutes, and of the files' 30.

The same person written with from two accounts is two rows in
`ods.telegram_chats`, one per account; `chat_key` tells them apart, and
`ods.telegram_messages` carries it too. Starting one account over is
clearing its own Variables, `telegram_sync_<name>` and
`telegram_media_<name>`.

Removing an account is ending its session in Telegram and deleting its
key from the Secret (`sops unset`); what it already sent stays.

## Renewing

The session has no end date. It stops working when it is ended in
Telegram (Settings -> Devices -> *homelab warehouse*), when the account
logs out of all other sessions, or when Telegram ends it after long
disuse - which an hourly DAG never is. The DAG then fails with "Telegram
no longer accepts TELEGRAM_SESSION" (or `TELEGRAM_SESSION_<NAME>`), after
reading the other accounts. Run step 2 again - with the account's name for
any but `main` - then 3 and the restart from step 4.

## Things to know

- **The session is a full login to the account.** Whoever holds it can
  read and send messages as you. It lives only in the encrypted Secret,
  and the DAG only reads. Ending it under Settings -> Devices cuts the DAG
  off at once.
- **Other people's words are in here.** Everyone who writes to the account
  privately has their messages copied, in full, with their usernames,
  profile link and, when Telegram shows it, their phone number - kept so a
  message can always be traced to a person. They sit in ClickHouse,
  readable by its `admin` and `dbt` users, by CloudBeaver, and by the
  `brand` agent, which reads the `ods`, `ads` and `dm` layers on purpose, to
  help manage things; and in the nightly encrypted backup of
  `data/data-clickhouse-0`. The photos, voice messages and files they sent
  are in the NAS archive, which the `archive` login reads from the house.
- **The files are in the NAS archive**, under their hashes, each with a
  row in `ods.files`: `source = 'telegram'`, and `ref` the message's
  `message_key`. The same photo forwarded to five chats is one file on the
  NAS and five rows. The archive's own things to know - one disk, nothing
  ever deleted - are in [files.md](files.md#things-to-know).
- **1 GiB is the limit.** A larger file - a long video, a disk image - is
  not fetched; the media task's log counts it, and its message keeps its
  metadata and a `file_key` with no row behind it. So does a file Telegram
  will not hand over, an expired one say, which the log names by chat and
  message id. Neither is tried again.
- **The history's files take many runs.** Each run stores 30 minutes of
  them, chats already under way first, oldest file first in each chat;
  years of photos and videos take days. Once through, a file is stored in
  the same run as its message.
- **They take room.** The archive has a 200 GiB quota on the NAS
  ([the NAS runbook](../docs/runbooks/nas-bring-up.md#8-storage)). What
  the files will take, before they are fetched, and what they take so far:

  ```sql
  SELECT account, formatReadableSize(sum(media_size_bytes))
  FROM ods.telegram_messages
  WHERE file_key IS NOT NULL AND media_size_bytes <= 1073741824
  GROUP BY account;

  SELECT formatReadableSize(sum(size_bytes)) FROM ods.files WHERE source = 'telegram';
  ```

  A file kept under several rows counts once per row in both. Downloads go
  straight onto the NAS, never the node's own disk. A full archive fails
  the media task, its log says so, and the files wait until there is room.
- **Telegram sets the pace.** When it says "wait", the client waits, up to
  five minutes at a time, and the run carries on. Reading one's own history
  this way is what every third-party Telegram app does.
- **Starting over** is clearing the Airflow Variable `telegram_sync`
  (Admin -> Variables; `telegram_sync_<name>` for another account): the next runs read every chat from the start
  again, and the ods model keeps each message once. For the files it is
  `telegram_media` (`telegram_media_<name>`): each is fetched again, and
  still stored once.
