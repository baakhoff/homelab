# Proton Mail

A Proton Mail mailbox in the warehouse: `raw.proton`, then
`ods.proton_messages` and `ods.proton_attachments`. Loaded by hand from an
export - Proton has no API a server can read mail through - by the DAG
`ingest_proton` ([`dags/proton.py`](dags/proton.py)), which has no
schedule.

| Model | One row per |
|---|---|
| `ods.proton_messages` | message: when, from, to, cc, bcc, subject, folders and labels by name, sent or received, read, replied, forwarded, the body as plain text, attachment names |
| `ods.proton_attachments` | attachment: its message, name, type, size, and whether it is inline (an image in an HTML body) |

## What is in it, and what is not

- **The body as plain text.** The text part when a message has one, else
  its HTML with the tags taken out. A body over a million characters is cut
  there and flagged `is_body_truncated`.
- **Attachments as metadata.** Name, type and size, never the file. The
  files stay in the export.
- **Threads by header.** Proton's export carries no conversation id, so
  `thread_id` is the first message a mail's `References` header names - how
  mail clients thread. It groups replies, not Proton's own conversation
  view exactly.
- **Masked on the way in,** like every source (`sensitive.md`): passwords,
  codes, keys, card and account numbers in a mail never reach Kafka.
- **As of the export.** Nothing after it arrives until the next one is
  loaded, and a mail deleted in Proton since stays.

## Loading an export

The topic and `raw.proton` come from the hourly schema job; on a first
load, start it once rather than wait:
`kubectl -n data create job --from=cronjob/clickhouse-schema schema-now`.

**1. Export.** Proton's *Mail Export* tool, on the machine that will hold
the files. It writes one directory per address with a `.eml` and a
`.metadata.json` per message, and a log; the log's last lines give the
message count and `errorCount`.

**2. Pack.** On that machine, from the repo root - standard library only:

```bash
python3 pipelines/tools/proton_pack.py ~/proton-mail-export ~/proton.jsonl.gz
```

It prints the messages, attachments and any it skipped, never contents.
A gigabyte of export packs to a few tens of megabytes: the attachments
stay behind.

**3. Copy into the scheduler.** Tasks run inside the scheduler pod
(`clusters/lab/airflow/helmrelease.yaml`), so that is where the file goes:

```bash
POD=$(kubectl -n airflow get pod -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl -n airflow cp ~/proton.jsonl.gz "$POD":/tmp/proton.jsonl.gz -c scheduler
```

**4. Run it.** In the Airflow UI, trigger `ingest_proton`. Once every
message is delivered it deletes `/tmp/proton.jsonl.gz` and logs the count.
Then trigger `warehouse`, and:

```sql
SELECT count() FROM ods.proton_messages;
SELECT count() FROM ods.proton_attachments;
```

**5. Clean up.** The packed file and the export on the machine are the
mail unmasked: `rm ~/proton.jsonl.gz`, and the export directory too unless
it is kept as the copy of record. A restart of the scheduler pod before
step 4 also removes the copy in the pod.

A newer export loads the same way, on top: `ods.proton_messages` keeps
each message once, by Proton's message id.

## Things to know

- **Other people's words are in here,** as with Telegram: everyone who
  wrote to the mailbox, with their addresses. They sit in ClickHouse,
  readable by its `admin` and `dbt` users, by CloudBeaver, and by the
  `brand` agent, which reads `ods`, `ads` and `dm` on purpose; and in the
  nightly encrypted backup of `data/data-clickhouse-0`.
- **`raw.proton` keeps every load.** Each export loaded is in it in full.
  Dropping an old one is `ALTER TABLE raw.proton DELETE WHERE
  JSONExtractString(payload, 'run_id') = '...'` as `admin`.
