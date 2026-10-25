# The NAS archive

The warehouse holds rows; the files those rows are about live on the NAS,
in `tank/archive`. Each file is stored once, named by its SHA-256 - a
fingerprint of its contents - and `ods.files` has a row for every place it
came from, with the hash, the size and the file's own name. A row elsewhere
in the warehouse finds its file through that index.

| | Where |
|---|---|
| The files | `tank/archive/objects/<first two of the hash>/<hash>`, no extension |
| Files waiting to be taken | `tank/archive/inbox/` |
| The index | `ods.files`, from `raw.files` |
| The DAG | `ingest_files` (`dags/files.py`, the work in `dags/archive.py`), hourly at :30 |

Setting up the dataset, its user and its shares is in the NAS runbook,
[the cluster's shares](../docs/runbooks/nas-bring-up.md#the-clusters-shares).

## Putting files in

Copy a folder into the inbox share, `\\nas.lab\archive-inbox`, logged in as
the NAS user `archive` (its password is in the password manager). From
Windows, in PowerShell:

```
net use I: \\nas.lab\archive-inbox /user:archive
robocopy "<folder>" "I:\<batch name>" /E /COPY:DAT /DCOPY:DAT /R:2 /W:5 /NP
```

From Linux, the file manager opens `smb://archive@nas.lab/archive-inbox`.

- **A folder is a batch.** Its name becomes the start of each file's key,
  so name it for what it holds: `receipts-2026`, `old-phone-scans`. A file
  copied in loose is a batch of one.
- **It is taken once nothing in it has changed for 30 minutes**, at the
  next half past. A copy still running is left alone. After that the files
  are gone from the inbox and each has its row; `ingest_files`' log names
  any batch it is still waiting on.
- **`.DS_Store`, `Thumbs.db` and `desktop.ini`** are deleted, not stored.

Each file's row then reads:

| Column | For a dropped file |
|---|---|
| `source` | `inbox` |
| `ref` | its path in the inbox, the batch folder first: `receipts-2026/march/rent.pdf` |
| `batch` | the batch folder |
| `file_name`, `mime_type` | its name, and the type its extension implies |
| `modified_at` | its own modification time, which robocopy and `cp -p` keep |
| `sha256`, `object`, `size_bytes` | the stored file |

### A manifest

A tool that knows more about its files than their paths - which message an
attachment belongs to, its name before it was saved - writes a
`files.jsonl` into the batch folder, one line per file:

```json
{"file": "12/1", "endpoint": "proton", "id": "Xq3vT9bLw0==/1", "record": {"name": "invoice.pdf", "mime_type": "application/pdf", "inline": false}}
```

`file` is the path in the batch; the row gets `source` = `endpoint` and
`ref` = `id`, and the fields in `record` over the ones the DAG works out
itself. A file the manifest does not list is an `inbox` row like any other.
A manifest line without `file`, `endpoint` or `id`, or with an endpoint
that is not lower-case letters, digits, `_`, `-` and `/`, fails the batch,
which then stays in the inbox untouched.

## Where files come from

| `source` | What | `ref` | Joins |
|---|---|---|---|
| `inbox` | anything dropped in that no manifest names | its path in the inbox, the batch folder first | - |
| `telegram` | photos, videos, voice messages, video notes, audio and documents in private Telegram chats, from `ingest_telegram` ([telegram.md](telegram.md)) | the message's `message_key`: `<chat id>/<message id>`, with `<account>:` in front for an account other than `main` | `ods.telegram_messages.file_key` |
| `proton` | Proton Mail attachments, packed with `--files` ([proton.md](proton.md)) | `<message_key>/<position>`: the message's Proton id, and the attachment's place in it from 1 | `ods.proton_attachments.file_key` |

## Finding a file from a row

```sql
SELECT file_name, mime_type, size_bytes, object
FROM ods.files
WHERE source = 'inbox' AND batch = 'receipts-2026';
```

`object` is the path in the read-only share `\\nas.lab\archive`, logged in
as `archive`: `\\nas.lab\archive\objects\2d\2d7116…`. Copy it out and give
it its `file_name` back - stored files have no extension.

A model with a `file_key` column joins on it:

```sql
SELECT a.file_name, f.object
FROM ods.proton_attachments AS a
JOIN ods.files AS f ON f.file_key = a.file_key
WHERE a.message_key = '…';
```

## Things to know

- **The same file is stored once.** Five copies under five names are one
  object and five rows.
- **The same path dropped again replaces its row**, not the earlier
  object, which stays under its own hash.
- **Nothing deletes an object.** Taking a file out of the archive is by
  hand, over SSH on the NAS, and its rows stay in `raw.files`.
- **Files are stored as they are.** The masking (`sensitive.md`) covers the
  rows - a card number in a file's name is masked there - never the files'
  contents.
- **Only Airflow's scheduler mounts the archive**, over NFS from its node;
  no other pod in the lab reaches the NAS
  ([why](../docs/network.md#pods-and-the-lan)). From the house, the two
  shares need the `archive` login.
- **One disk, no copy elsewhere.** ZFS snapshots it hourly and daily on the
  NAS; until the NAS has an off-site copy, keep the originals of anything
  that is not somewhere else too.
