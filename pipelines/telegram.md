# Telegram

Telegram accounts' private chats, in the warehouse: `raw.telegram`,
then `ods.telegram_chats`, `ods.telegram_messages` and
`ads.telegram_daily`. The DAG is `ingest_telegram`
([`dags/telegram.py`](dags/telegram.py)), hourly at :20.

| Model | One row per |
|---|---|
| `ods.telegram_chats` | person an account has ever had a private chat with, kept after the chat is deleted: their name, user id, username, profile link, phone number when Telegram shows it, every username and number seen for them before, whether they are a contact, unread count, last message; the account's own Saved Messages is one too |
| `ods.telegram_messages` | message, in its newest version: when, which way, the text, a reply or forward, and media and calls as metadata |
| `ads.telegram_daily` | day and account: messages sent and received, people written with, voice messages, calls, missed calls, call minutes |

## What is in it, and what is not

- **Private chats only**, one-to-one with people. No groups, no channels,
  no chats with bots.
- **Text in full.** Photos, voice messages, videos and files as metadata:
  the kind, size, duration and file name, never the file. The photos and
  videos go to Immich instead (below). A shared
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
of the 40 minutes.

The same person written with from two accounts is two rows in
`ods.telegram_chats`, one per account; `chat_key` tells them apart, and
`ods.telegram_messages` carries it too. Starting one account over is
clearing its own Variable, `telegram_sync_<name>`.

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

## The photos, into Immich

The files themselves are still on Telegram's servers.
[`tools/telegram_media.py`](tools/telegram_media.py) downloads the photos,
videos and round video messages from the same private chats, and the
images and videos sent as files, the uncompressed originals. It has its own
login, called *homelab photos*: one session used from two places at once
can make Telegram end it, and the DAG's has to stay. Run it on the machine
that will upload, with Telethon:

```bash
python3 -m venv /tmp/tg && /tmp/tg/bin/pip install telethon==1.45.0
```

**1. Survey** - how many photos and videos there are, by year, and their
size. The first run asks for the api_id and api_hash (not echoed; every
run asks for them), the phone number, the code and the two-step password,
and keeps the login in `tg.session`, readable by its owner only. Nothing
else is saved:

```bash
/tmp/tg/bin/python pipelines/tools/telegram_media.py survey tg.session
```

`--groups` at the end takes in group chats too.

**2. Fetch** into a folder. Each file is named `TG_<date>_<time>_<hash>.<ext>`
and dated by its message, since Telegram strips a photo's own date. Videos
over 1 GB and self-destructing media are skipped. Interrupted or run again,
it skips what it already has:

```bash
/tmp/tg/bin/python pipelines/tools/telegram_media.py fetch tg.session ~/tg-media
```

**3. Upload** with immich-go, as in [`vk.md`](vk.md), into an album of
their own and with the tag the hourly task gives too -
`--into-album=Telegram --tag=Source/Telegram`, `--dry-run` first. The same
photo sent in two chats is uploaded once.

Upload each folder once, then delete it (step 4). Fetching again later and
uploading that would bring back what has been deleted in Immich since; the
hourly task never does.

**4. Log out,** which also removes it from Settings -> Devices. Then delete
the folder and the virtualenv:

```bash
/tmp/tg/bin/python pipelines/tools/telegram_media.py logout tg.session
```

For another account, the same with a session file of its own, say
`tgold.session`, and a folder of its own.

**5. From then on, hourly.** `ingest_telegram` has a second task, `photos`,
that sends the photos and videos in new messages - every account's - to
the same album, with the tag `Source/Telegram`, chosen, named and dated as
above. Its first run only notes
where each chat stands; what came before is this tool's. It needs a key:
in Immich, Account settings -> API keys -> New, named `telegram`, with only
`asset.upload`, `album.read`, `album.create`, `albumAsset.create`,
`tag.create` and `tag.asset`. Then:

```bash
read -rsp 'immich telegram key: ' IK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["IMMICH_TELEGRAM_API_KEY"]' "\"$(printf %s "$IK" | base64 | tr -d '\n')\""
unset IK
```

Commit, push, and restart the scheduler as in step 4. Until the key is
there, the task says so and does nothing. It never uploads anything sent
before its first run - not for a chat it first sees later, not on a retry -
so a picture deleted in Immich stays deleted. Its progress is the Variable
`telegram_photos` (`telegram_photos_<name>`); clearing it starts it over
from that moment, not from the beginning. Run step 2 once more after its
first run, and the photos sent between the two are caught too.

**6. In the warehouse.** `ads.chat_media` ties each of these pictures to
its message: the chat and person, when it was sent and which way, the
text with it, and the picture's Immich link, type and description. The
hash in the file's name is the tie, so it holds for the history and the
hourly uploads alike; VK's pictures are in it too ([`vk.md`](vk.md)). Its
`status` is `active`, `deleted` once the picture is deleted in Immich, or
`duplicate` - removed by Immich's duplicate review, or a copy of a picture
first sent in another message. A deleted picture keeps its rows, with what
was in it; only Immich loses the file.

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
  `data/data-clickhouse-0`.
- **Telegram sets the pace.** When it says "wait", the client waits, up to
  five minutes at a time, and the run carries on. Reading one's own history
  this way is what every third-party Telegram app does.
- **Starting over** is clearing the Airflow Variable `telegram_sync`
  (Admin -> Variables; `telegram_sync_<name>` for another account): the next runs read every chat from the start
  again, and the ods model keeps each message once.
