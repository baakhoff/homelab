-- Everything the Takeout loader sent outside the mail and the activity
-- history, one row per record, as it came: the products with a model of
-- their own (Fit, Keep, Chat, Pay, Maps, Saved) and the ones without -
-- the devices and sign-ins in Access Log Activity, Maps' commute routes,
-- Shopping reviews. `endpoint` is takeout/<product>/<what>; `record` is
-- the CSV row or JSON item, with the file it came from as _file.
--
-- Here so the rest can be read from ods, which brand and CloudBeaver see,
-- until a model of its own is worth it.
select
  id as record_key,
  endpoint,
  file,
  record,
  extracted_at
from (
  select
    JSONExtractString(payload, 'id') as id,
    JSONExtractString(payload, 'endpoint') as endpoint,
    JSONExtractString(payload, 'file') as file,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'google') }}
  where startsWith(JSONExtractString(payload, 'endpoint'), 'takeout/')
  order by kafka_ts desc
  limit 1 by endpoint, id
)
