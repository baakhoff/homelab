-- One row per attachment of a Proton Mail message: name, type and size.
-- The file itself goes to the NAS archive when the export is packed with
-- --files and the folder dropped into its inbox (pipelines/proton.md).
-- Inline ones are mostly images in an HTML body: logos, signatures.
select
  message_key,
  num as position,
  -- Its row in ods.files once the file is stored. An empty attachment has
  -- none.
  concat('proton:', message_key, '/', toString(position)) as file_key,
  JSONExtractString(att, 'name') as file_name,
  JSONExtractString(att, 'mime_type') as mime_type,
  JSONExtractInt(att, 'size') as size_bytes,
  JSONExtractBool(att, 'inline') as is_inline,
  sent_at,
  extracted_at
from (
  select
    JSONExtractString(payload, 'id') as message_key,
    JSONExtractArrayRaw(JSONExtractRaw(payload, 'record'), 'attachments') as atts,
    {{ ts("JSONExtractString(payload, 'record', 'time')") }} as sent_at,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'proton') }}
  where JSONExtractString(payload, 'endpoint') = 'messages'
  order by kafka_ts desc
  limit 1 by message_key
)
array join atts as att, arrayEnumerate(atts) as num
