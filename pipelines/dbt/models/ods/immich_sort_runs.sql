-- One row per try of an immich_sort run (pipelines/dags/immich_sort.py),
-- which describes Immich's photos and videos, gives each a type and sets
-- aside what nobody would miss: how many it sorted, set aside and skipped,
-- how many of each type, the types it made, the tokens Claude took, and
-- the error a failed try stopped on - its tokens count too. Each picture's
-- own row is in immich_photos.
--
-- estimated_usd is at Claude Haiku 4.5's list price, $1 per million tokens
-- in and $5 out.
with latest as (
  select
    JSONExtractString(payload, 'id') as attempt_key,
    JSONExtractString(payload, 'run_id') as run_id,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'immich') }}
  where JSONExtractString(payload, 'endpoint') = 'sort'
  order by kafka_ts desc
  limit 1 by attempt_key
)
select
  attempt_key,
  run_id,
  JSONExtractUInt(record, 'try') as try_number,
  JSONExtractString(record, 'model') as model,
  JSONExtractUInt(record, 'sorted') as sorted,
  JSONExtractUInt(record, 'to_delete') as set_aside,
  JSONExtractUInt(record, 'failed') as skipped,
  JSONExtract(record, 'types', 'Map(String, UInt64)') as by_type,
  JSONExtract(record, 'new_types', 'Array(String)') as new_types,
  JSONExtractUInt(record, 'input_tokens') as input_tokens,
  JSONExtractUInt(record, 'output_tokens') as output_tokens,
  round((input_tokens * 1 + output_tokens * 5) / 1e6, 4) as estimated_usd,
  nullIf(JSONExtractString(record, 'error'), '') as error,
  extracted_at as ran_at
from latest
