-- Messages in the private chats: one row per message, in its newest
-- version. Not a snapshot - the ingest DAG sends each message once, and
-- again when it is edited (pipelines/dags/telegram.py) - so this keeps the
-- latest copy of every message ever sent. A message deleted in Telegram
-- stays: nothing reports the deletion.
--
-- Media is metadata only: what kind, its size, duration and file name, and
-- the coordinates of a shared location. Calls are service messages with
-- action = 'PhoneCall'.
with latest as (
  select
    JSONExtractString(payload, 'id') as message_key,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'telegram') }}
  where JSONExtractString(payload, 'endpoint') = 'messages'
  order by kafka_ts desc
  limit 1 by message_key
)
select
  message_key,
  JSONExtractInt(record, 'chat_id') as chat_id,
  JSONExtractInt(record, 'id') as message_id,
  {{ ts("JSONExtractString(record, 'date')") }} as sent_at,
  {{ ts("JSONExtractString(record, 'edit_date')") }} as edited_at,
  JSONExtractBool(record, 'out') as is_outgoing,
  JSONExtract(record, 'sender_id', 'Nullable(Int64)') as sender_id,
  JSONExtractString(record, 'text') as text,
  JSONExtract(record, 'reply_to_msg_id', 'Nullable(Int64)') as reply_to_message_id,
  JSONHas(record, 'forwarded') and JSONType(record, 'forwarded') = 'Object' as is_forwarded,
  JSONExtractString(record, 'forwarded', 'from_name') as forwarded_from_name,
  JSONExtract(record, 'grouped_id', 'Nullable(Int64)') as album_id,
  nullIf(JSONExtractString(record, 'media', 'kind'), '') as media_kind,
  nullIf(JSONExtractString(record, 'media', 'mime_type'), '') as media_mime_type,
  JSONExtract(record, 'media', 'size', 'Nullable(Int64)') as media_size_bytes,
  JSONExtract(record, 'media', 'duration', 'Nullable(Float64)') as media_duration_s,
  nullIf(JSONExtractString(record, 'media', 'name'), '') as media_file_name,
  JSONExtract(record, 'media', 'lat', 'Nullable(Float64)') as lat,
  JSONExtract(record, 'media', 'lon', 'Nullable(Float64)') as lon,
  nullIf(JSONExtractString(record, 'action', 'kind'), '') as action,
  JSONExtract(record, 'action', 'duration', 'Nullable(Int64)') as call_duration_s,
  JSONExtractBool(record, 'action', 'video') as is_video_call,
  nullIf(JSONExtractString(record, 'action', 'reason'), '') as call_end_reason,
  extracted_at
from latest
