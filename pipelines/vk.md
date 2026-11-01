# VK

The VK ("ВКонтакте") account's data, in the warehouse: `raw.vk`, then
`ods.vk_messages`, `ods.vk_conversations`, `ods.vk_audio` and
`ods.vk_items`. The account was deleted in 2020, so its data archive -
the HTML pages VK's "request your data" page gave before that - is the
only source there will ever be. It is loaded once, by hand, by the DAG
`ingest_vk` ([`dags/vk.py`](dags/vk.py)).

| Model | One row per |
|---|---|
| `ods.vk_messages` | message: conversation, who wrote it (or `is_outgoing`), when, the text, edited or not, attachments as VK described and linked them |
| `ods.vk_conversations` | conversation: its name, group chat or not, how many messages and when |
| `ods.vk_audio` | track of the music list: artist, title, length |
| `ods.vk_items` | entry of any other section - wall, comments, likes, bookmarks, profile, sessions, apps, ads, video, photos - as its text and links (`section` says which) |

## What is in it, and what is not

- **Times are local.** The archive wrote them in Russian, in the time zone
  the account was set to, with no zone attached: `sent_at_local`,
  `happened_at_local`. Other sources are in UTC.
- **Attachments are descriptions and links.** Photos, voice messages and
  documents were never in the archive, and VK's links to them mostly no
  longer resolve. The photos that still do can go into Immich (below).
- **People are names and profile links.** VK gave no phone numbers or
  addresses, so nobody here joins `ads.people`; `sender_vk_id` is the
  user id where the archive linked the profile.
- **Masked on the way in,** like every source (`sensitive.md`).

## Loading it

The topic and `raw.vk` come from the hourly schema job; start it once
rather than wait:
`kubectl -n data create job --from=cronjob/clickhouse-schema schema-vk`.

**1. Pack.** On the machine that holds the zip, from the repo root -
standard library only, no unpacking:

```bash
python3 pipelines/tools/vk_pack.py "$HOME/Downloads/Telegram Desktop/VK Data.zip" ~/vk.jsonl.gz
```

It prints the records per kind and any page it skipped, never contents.

**2. Copy into the scheduler**, where tasks run:

```bash
POD=$(kubectl -n airflow get pod -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl -n airflow cp ~/vk.jsonl.gz "$POD":/tmp/vk.jsonl.gz -c scheduler
```

**3. Run it.** Trigger `ingest_vk` in the Airflow UI. It masks every
record, sends it to `raw.vk`, and deletes the file once all of it is
delivered. Then trigger `warehouse`, and:

```sql
SELECT count() FROM ods.vk_messages;
SELECT name, messages FROM ods.vk_conversations ORDER BY messages DESC LIMIT 10;
```

**4. Clean up.** `rm ~/vk.jsonl.gz`. Keep the zip itself: it is the only
copy there is.

## The photos, into Immich

What still answers of the archive's photo and video links - from the
messages and every other section - can go into Immich, with
[`tools/vk_media.py`](tools/vk_media.py) on the machine that holds the zip.
It reads the zip as `vk_pack.py` does. Photos need only the standard
library; videos, whose links are VK's player pages, go through
[yt-dlp](https://github.com/yt-dlp/yt-dlp) - installed, or run through
`uvx` - at the best quality that fits in 1 GB, and one that never fits is
skipped.

**1. Survey** - how many photo and video links there are, by year, and how
many of a sample of each still answer. Nothing is saved:

```bash
python3 pipelines/tools/vk_media.py survey "$HOME/Downloads/Telegram Desktop/VK Data.zip"
```

**2. Fetch** what answers into a folder. Each file is named
`VK_<date>_<time>_<hash>.<ext>` and dated by its message or wall entry,
since VK stripped the files' own dates. Interrupted or run again, it skips what
it already has:

```bash
python3 pipelines/tools/vk_media.py fetch "$HOME/Downloads/Telegram Desktop/VK Data.zip" ~/vk-media
```

**3. Upload** with [immich-go](https://github.com/simulot/immich-go) and a
temporary all-permissions key, as for any import
(`clusters/lab/immich/README.md`), into an album of their own - `--dry-run`
first:

```bash
immich-go upload from-folder --server=https://photos.lab.baakhoff.com --api-key="$K" --into-album=VK --concurrent-tasks=2 ~/vk-media
```

Then delete the key and `rm -r ~/vk-media`. The hourly sorting gives them
types like the rest. What was sent in chats is other people's too - the
same as the messages around them.

## Things to know

- **Other people's words are in here,** as with Telegram and mail: 849
  conversations' worth, with names and profile links. They sit in
  ClickHouse, readable by its `admin` and `dbt` users, by CloudBeaver and
  by the `brand` agent, and in the nightly encrypted backup of
  `data/data-clickhouse-0`.
- **Loading again adds nothing.** Every record has a stable id - VK's
  message id, or a hash of the entry - and the models keep each once.
