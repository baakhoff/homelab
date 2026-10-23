-- Proton Mail: one row per message, from exports loaded by hand
-- (pipelines/dags/proton.py). Not a snapshot - a later export loads on top,
-- and this keeps each message's newest copy by Proton's message id, so a
-- message deleted in Proton since stays.
--
-- Addresses are lowercased. Folders and labels are by name, Proton's own
-- (Inbox, Sent, Archive ...) included. Attachments are their names here and
-- one row each in proton_attachments; the files never left the export.
with latest as (
  select
    JSONExtractString(payload, 'id') as message_key,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'proton') }}
  where JSONExtractString(payload, 'endpoint') = 'messages'
  order by kafka_ts desc
  limit 1 by message_key
)
select
  message_key,
  JSONExtractString(record, 'account') as account,
  nullIf(JSONExtractString(record, 'message_id'), '') as message_id_header,
  nullIf(JSONExtractString(record, 'thread_id'), '') as thread_id,
  nullIf(JSONExtractString(record, 'in_reply_to'), '') as in_reply_to,
  {{ ts("JSONExtractString(record, 'time')") }} as sent_at,
  JSONExtractString(record, 'subject') as subject,
  JSONExtractString(record, 'from', 'name') as from_name,
  JSONExtractString(record, 'from', 'address') as from_address,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'to')) as to_addresses,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'cc')) as cc_addresses,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'bcc')) as bcc_addresses,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'reply_to')) as reply_to_addresses,
  JSONExtract(record, 'labels', 'Array(String)') as labels,
  JSONExtract(record, 'label_ids', 'Array(String)') as label_ids,
  -- Proton's All Sent and All Drafts.
  has(label_ids, '2') as is_sent,
  has(label_ids, '1') as is_draft,
  JSONExtractBool(record, 'unread') as is_unread,
  JSONExtractBool(record, 'replied') or JSONExtractBool(record, 'replied_all') as is_replied,
  JSONExtractBool(record, 'forwarded') as is_forwarded,
  JSONExtract(record, 'size', 'Nullable(Int64)') as size_bytes,
  JSONExtractString(record, 'body_text') as body_text,
  JSONExtractBool(record, 'body_truncated') as is_body_truncated,
  arrayMap(x -> JSONExtractString(x, 'name'), JSONExtractArrayRaw(record, 'attachments')) as attachment_names,
  notEmpty(attachment_names) as has_attachments,
  extracted_at
from latest
