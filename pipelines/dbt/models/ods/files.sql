-- The NAS archive's index: one row per place a file came from - a file
-- dropped into the inbox, and whatever else stores files there
-- (pipelines/files.md). The file itself is on the NAS under its hash:
-- `object` is its path in tank/archive, and the same file from five places
-- is one object and five rows here.
--
-- `source` and `ref` say what the file belongs to, in that source's own
-- key. For `inbox`, the path it was dropped under, its folder first.
--
-- Each row is sent once, when the file is stored, and newer copies replace
-- it - the same path dropped into the inbox again, say. Nothing removes
-- one.
with latest as (
  select
    JSONExtractString(payload, 'endpoint') as source,
    JSONExtractString(payload, 'id') as ref,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'files') }}
  order by kafka_ts desc
  limit 1 by source, ref
)
select
  concat(source, ':', ref) as file_key,
  source,
  ref,
  JSONExtractString(record, 'sha256') as sha256,
  JSONExtractString(record, 'object') as object,
  JSONExtractUInt(record, 'size') as size_bytes,
  nullIf(JSONExtractString(record, 'name'), '') as file_name,
  nullIf(JSONExtractString(record, 'mime_type'), '') as mime_type,
  {{ ts("JSONExtractString(record, 'modified_at')") }} as modified_at,
  nullIf(JSONExtractString(record, 'batch'), '') as batch,
  extracted_at as stored_at
from latest
