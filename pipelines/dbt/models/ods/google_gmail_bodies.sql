-- Gmail with its bodies, from Takeout exports loaded by hand
-- (ingest_google_takeout): one row per message, by its Message-ID header.
-- The hourly Gmail DAG cannot read a body (gmail.metadata), so this is
-- where they are - as of the newest export loaded.
--
-- Joins its message in google_gmail_messages on message_id_header, or on
-- thread_id, which is kept in the hex the Gmail API uses. Attachments are
-- names and sizes; the files stayed in the export.
select
  id as message_id_header,
  nullIf(JSONExtractString(record, 'gmail_thread_id'), '') as thread_id,
  nullIf(JSONExtractString(record, 'in_reply_to'), '') as in_reply_to,
  {{ ts("JSONExtractString(record, 'time')") }} as sent_at,
  JSONExtractString(record, 'subject') as subject,
  JSONExtractString(record, 'from', 'name') as from_name,
  JSONExtractString(record, 'from', 'address') as from_address,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'to')) as to_addresses,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'cc')) as cc_addresses,
  arrayMap(x -> JSONExtractString(x, 'address'), JSONExtractArrayRaw(record, 'bcc')) as bcc_addresses,
  JSONExtract(record, 'labels', 'Array(String)') as labels,
  has(labels, 'Sent') as is_sent,
  nullIf(JSONExtractString(record, 'list_id'), '') as list_id,
  JSONExtractString(record, 'body_text') as body_text,
  JSONExtractBool(record, 'body_truncated') as is_body_truncated,
  arrayMap(x -> JSONExtractString(x, 'name'), JSONExtractArrayRaw(record, 'attachments')) as attachment_names,
  extracted_at
from ({{ accumulated_records('google', ['gmail/takeout']) }})
